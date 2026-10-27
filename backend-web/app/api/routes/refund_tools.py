"""退款消息配置与官方申请核对、手动核验退款。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_active_user, get_db_session
from common.models.user import User
from common.models.xy_account import XYAccount
from common.models.refund_message import RefundMessageConfig, RefundMessageRecord
from common.services.refund_tools import parse_refund_application
from common.services.order_service import OrderService
from common.utils.auth_scope import resolve_owner_scope
from common.utils.time_utils import get_beijing_now_naive
from common.models.refund_approval import RefundApproval
from common.services.refund_client import RefundPlatformClient, RefundPlatformError
from app.services.refund_approval_service import RefundApprovalService, as_result

router = APIRouter(prefix='/refund-tools', tags=['退款处理'])


class RefundEntry(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    refund_id: str = Field(min_length=1, max_length=64)
    refund_amount: str = Field(pattern=r'^(?:0|[1-9]\d{0,9})\.\d{2}$')


class RefundPrepareRequest(BaseModel):
    entries: list[RefundEntry] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def no_duplicates(self):
        if len({entry.refund_id for entry in self.entries}) != len(self.entries):
            raise ValueError('不能重复选择同一退款申请')
        return self


class RefundVerificationRequest(BaseModel):
    refresh: bool = False


async def approval_service(db, user, account_id):
    from common.db.redis_client import get_redis_client
    account = await scoped_account(db, user, account_id)
    if account.status in {'inactive', 'disabled', 'suspended', 'deleted'}:
        raise HTTPException(409, '店铺已停用，请先恢复登录后处理退款')
    return RefundApprovalService(db, account, user.id, RefundPlatformClient(db, account), await get_redis_client())


@router.post('/{account_id}/approvals/prepare')
async def prepare_approvals(account_id: str, data: RefundPrepareRequest,
                            db: AsyncSession = Depends(get_db_session),
                            user: User = Depends(get_current_active_user)):
    service = await approval_service(db, user, account_id)
    try:
        results = await service.prepare([entry.model_dump() for entry in data.entries])
    except RefundPlatformError as exc:
        raise HTTPException(502, str(exc))
    return dict(success=True, data=results)


@router.post('/{account_id}/approvals/{operation_id}/confirm')
async def confirm_approval(account_id: str, operation_id: str,
                           db: AsyncSession = Depends(get_db_session),
                           user: User = Depends(get_current_active_user)):
    service = await approval_service(db, user, account_id)
    try:
        result = await service.confirm(operation_id)
    except LookupError:
        raise HTTPException(404, '退款处理记录不存在')
    except RefundPlatformError as exc:
        raise HTTPException(502, str(exc))
    return dict(success=True, data=result)


@router.post('/{account_id}/approvals/{operation_id}/verification')
async def approval_verification(account_id: str, operation_id: str,
                                data: RefundVerificationRequest | None = None,
                                db: AsyncSession = Depends(get_db_session),
                                user: User = Depends(get_current_active_user)):
    service = await approval_service(db, user, account_id)
    try:
        result = await service.verification(operation_id, refresh=bool(data and data.refresh))
    except LookupError:
        raise HTTPException(404, '退款处理记录不存在')
    return dict(success=True, data=result)


class MessageSettings(BaseModel):
    enabled: bool = False
    unshipped_enabled: bool = False
    shipped_enabled: bool = False
    unshipped_content: str = Field(default='', max_length=1500)
    shipped_content: str = Field(default='', max_length=1500)

    @model_validator(mode='after')
    def valid_message(self):
        if self.enabled:
            if not self.unshipped_enabled and not self.shipped_enabled:
                raise ValueError('请至少启用一种订单类型')
            for prefix in ('unshipped', 'shipped'):
                if getattr(self, prefix+'_enabled') and not getattr(self, prefix+'_content').strip():
                    raise ValueError('已启用的订单类型必须填写消息文案')
        return self


async def scoped_account(db, user, account_id):
    owner_id, _ = resolve_owner_scope(user)
    stmt = select(XYAccount).where(XYAccount.account_id == account_id)
    if owner_id is not None:
        stmt = stmt.where(XYAccount.owner_id == owner_id)
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is None:
        raise HTTPException(404, '店铺不存在')
    return account


@router.get('/{account_id}/messages')
async def message_settings(account_id: str, db: AsyncSession = Depends(get_db_session),
                           user: User = Depends(get_current_active_user)):
    account = await scoped_account(db, user, account_id)
    config = await db.get(RefundMessageConfig, account_id)
    data = MessageSettings().model_dump()
    if config and config.owner_id == account.owner_id:
        data = {key: getattr(config, key) for key in data}
    records = (await db.execute(select(RefundMessageRecord).where(
        RefundMessageRecord.account_id == account_id, RefundMessageRecord.owner_id == account.owner_id
    ).order_by(RefundMessageRecord.id.desc()).limit(20))).scalars().all()
    return dict(success=True, data=data, records=[dict(id=r.id, order_no=r.order_no,
                status=r.status, detail=r.detail, created_at=r.created_at.isoformat()) for r in records])


@router.put('/{account_id}/messages')
async def save_message_settings(account_id: str, data: MessageSettings,
                                db: AsyncSession = Depends(get_db_session),
                                user: User = Depends(get_current_active_user)):
    account = await scoped_account(db, user, account_id)
    # 锁定店铺行，串行首次创建和启用时间更新。
    await db.execute(select(XYAccount.id).where(XYAccount.id == account.id).with_for_update())
    config = await db.get(RefundMessageConfig, account_id)
    if config is None:
        config = RefundMessageConfig(account_id=account_id, owner_id=account.owner_id, enabled=False)
        db.add(config)
    if config.owner_id != account.owner_id or (data.enabled and not config.enabled):
        config.enabled_at = get_beijing_now_naive()
    config.owner_id = account.owner_id
    for key, value in data.model_dump().items():
        setattr(config, key, value)
    await db.commit()
    return dict(success=True, message='退款消息配置已保存')


@router.get('/{account_id}/applications')
async def refund_applications(account_id: str, db: AsyncSession = Depends(get_db_session),
                              user: User = Depends(get_current_active_user)):
    account = await scoped_account(db, user, account_id)
    # 只查询等待卖家处理，不走会触发旧注销服务的同步入口。
    try:
        result = await OrderService(db)._fetch_refund_orders_page(account.cookie, '1', account.account_id)
    except Exception:
        raise HTTPException(502, '平台退款清单读取失败，请稍后刷新')
    if not result or result.get('error'):
        raise HTTPException(502, '平台退款清单读取失败，请检查店铺登录后刷新')
    rows = [parse_refund_application(item) for item in result.get('items') or []]
    history = (await db.execute(select(RefundApproval).where(
        RefundApproval.account_id == account_id, RefundApproval.owner_id == account.owner_id
    ).order_by(RefundApproval.created_at.desc()).limit(20))).scalars().all()
    pending = [op for op in history if op.status in {'submitted', 'unknown', 'submitting'}]
    if pending:
        try:
            completed = await RefundPlatformClient(db, account).refunded_ids()
            for op in pending:
                if op.refund_id in completed:
                    op.status, op.detail = 'success', '平台退款成功清单已确认退款完成'
            await db.commit()
        except Exception:
            pass  # 查询不确定不能改变原结果，更不能再次提交退款。
    return dict(success=True, data=rows, checked_at=get_beijing_now_naive().isoformat(),
                limited=len(rows) >= 20, can_submit=True, history=[as_result(op) for op in history],
                capability_message='仅同意已有的仅退款申请。提交前重新核对实际金额；需要支付宝验证时逐笔停留，验证后执行该笔退款。')
