"""退款申请消息发送：先提交唯一占位，再触达IM；不自动重试不确定发送。"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from common.models.refund_message import RefundMessageConfig, RefundMessageRecord
from common.models.xy_account import XYAccount
from common.models.xy_order import XYOrder
from common.services.refund_tools import message_content_for
from common.utils.time_utils import BEIJING_TZ, get_beijing_now_naive


def refund_event_at(raw_message: dict) -> datetime | None:
    try:
        millis = (raw_message.get('1') or {}).get('5')
        if not millis:
            return None
        return datetime.fromtimestamp(float(millis)/1000, BEIJING_TZ).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


async def send_refund_message(session_factory, account_id: str, order_no: str,
                              chat_id: str, event_at: datetime | None, send):
    """send(chat_id, buyer_id, text) 返回 submitted/failed/unknown。"""
    async with session_factory() as session:
        account = (await session.execute(select(XYAccount).where(XYAccount.account_id == account_id))).scalar_one_or_none()
        if not account or account.status in {'inactive', 'disabled', 'suspended', 'deleted'}:
            return 'disabled'
        config = await session.get(RefundMessageConfig, account_id)
        if not config or config.owner_id != account.owner_id:
            return 'disabled'
        orders = (await session.execute(select(XYOrder).where(
            XYOrder.account_id == account_id, XYOrder.order_no == order_no,
            XYOrder.owner_id == account.owner_id))).scalars().all()
        # 数据冲突时不能猜买家。
        if len(orders) != 1:
            return 'missing_order'
        order = orders[0]
        content = message_content_for(config, order, event_at, get_beijing_now_naive())
        if not content:
            return 'skipped'
        if not order.buyer_id or not chat_id or (order.chat_id and order.chat_id != chat_id):
            return 'missing_recipient'
        recipient = order.buyer_id
        record = RefundMessageRecord(account_id=account_id, owner_id=account.owner_id,
                                     order_no=order_no, content=content, status='processing', detail='已占位，等待发送结果')
        session.add(record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return 'duplicate'
        record_id = record.id

    # 不持有数据库事务等待IM应答；进程中断后留下processing，不重复发送。
    try:
        outcome = await send(chat_id, recipient, content)
        status = outcome if outcome in {'submitted', 'failed', 'unknown'} else 'unknown'
    except Exception:
        status = 'unknown'
    async with session_factory() as session:
        record = await session.get(RefundMessageRecord, record_id)
        record.status = status
        record.detail = {'submitted': '已提交IM，未确认买家收悉', 'failed': '平台明确拒绝发送',
                         'unknown': '发送结果未知，请查看聊天；不自动重试'}[status]
        await session.commit()
    return status
