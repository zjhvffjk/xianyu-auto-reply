"""退款提交占位和官方验证衔接。验证token仅在Redis保存10分钟，不落SQL/日志。"""
import json
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from common.models.refund_approval import RefundApproval
from common.services.refund_client import RefundPlatformError


def as_result(op, url=None):
    return dict(id=op.id, order_no=op.order_no, refund_id=op.refund_id,
                refund_amount=format(op.amount, '.2f'), status=op.status, detail=op.detail,
                verification_url=url)


def matches(row, entry):
    return (row and row['eligible'] and row['order_no'] == entry['order_no']
            and row['refund_id'] == entry['refund_id']
            and row['refund_amount'] == entry['refund_amount'])


class RefundApprovalService:
    def __init__(self, session, account, actor_id, platform, cache):
        self.session, self.account, self.actor_id = session, account, actor_id
        self.platform, self.cache = platform, cache

    def key(self, op_id):
        return 'refund-approval-context:' + op_id

    async def prepare(self, entries):
        rows = {row['refund_id']: row for row in await self.platform.applications()}
        results = []
        for entry in entries:
            row = rows.get(entry['refund_id'])
            if not matches(row, entry):
                results.append(dict(**entry, id='', status='conflict',
                    detail='申请状态、类型或金额已变化，请重新读取清单', verification_url=None))
                continue
            op = RefundApproval(id=str(uuid4()), owner_id=self.account.owner_id,
                actor_id=self.actor_id, account_id=self.account.account_id,
                order_no=row['order_no'], refund_id=row['refund_id'],
                amount=Decimal(row['refund_amount']), status='queued', detail='已核对，等待逐笔验证')
            self.session.add(op)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                old = (await self.session.execute(select(RefundApproval).where(
                    RefundApproval.account_id == self.account.account_id,
                    RefundApproval.refund_id == entry['refund_id']))).scalar_one()
                # 同一申请只保留一次提交机会；未知结果绝不自动重试。
                result = as_result(old)
                if old.actor_id == self.actor_id and old.status == 'awaiting_verification':
                    cached = await self.cache.get(self.key(old.id))
                    if cached:
                        result['verification_url'] = json.loads(cached)['verify_url']
                    else:
                        old.status, old.detail = 'expired', '验证已过期，尚未提交退款，可重新生成验证页'
                        await self.session.commit(); result = as_result(old)
                results.append(result)
                continue
            results.append(as_result(op))
        return results

    async def verification(self, op_id, refresh=False):
        op = (await self.session.execute(select(RefundApproval).where(
            RefundApproval.id == op_id, RefundApproval.account_id == self.account.account_id,
            RefundApproval.owner_id == self.account.owner_id,
            RefundApproval.actor_id == self.actor_id).with_for_update()
            .execution_options(populate_existing=True))).scalar_one_or_none()
        if not op:
            raise LookupError('退款处理记录不存在')
        if refresh and op.status in {'queued', 'awaiting_verification', 'expired', 'verification_failed'}:
            # 官方核验可能先于本地TTL失效；仅店主主动请求时更新未提交的核验上下文。
            await self.cache.delete(self.key(op.id))
            op.status = 'expired'
        if op.status == 'awaiting_verification':
            cached = await self.cache.get(self.key(op.id))
            if cached:
                return as_result(op, json.loads(cached)['verify_url'])
            op.status, op.detail = 'expired', '验证已过期，尚未提交退款，可重新生成验证页'
            await self.session.commit()
            return as_result(op)
        if op.status not in {'queued', 'expired', 'verification_failed'}:
            return as_result(op)
        # 按实际处理进度生成验证页，后续订单不提前消耗验证有效期。
        op.status, op.detail = 'preparing', '准备官方验证'
        await self.session.commit()
        try:
            context = await self.platform.verification(op.refund_id)
            await self.cache.set(self.key(op.id), json.dumps(context), ex=600)
            op.status, op.detail = 'awaiting_verification', '等待店主在支付宝官方页面验证，验证后执行退款'
            await self.session.commit()
            return as_result(op, context['verify_url'])
        except Exception:
            op.status, op.detail = 'verification_failed', '准备官方验证失败，尚未提交退款，可以重新读取验证页'
            await self.session.commit()
            return as_result(op)

    async def confirm(self, op_id):
        op = (await self.session.execute(select(RefundApproval).where(
            RefundApproval.id == op_id, RefundApproval.account_id == self.account.account_id,
            RefundApproval.owner_id == self.account.owner_id,
            RefundApproval.actor_id == self.actor_id).with_for_update()
            .execution_options(populate_existing=True))).scalar_one_or_none()
        if not op:
            raise LookupError('退款处理记录不存在')
        if op.status != 'awaiting_verification':
            return as_result(op)
        cached = await self.cache.get(self.key(op.id))
        if not cached:
            op.status, op.detail = 'expired', '验证已过期，尚未提交退款，可重新生成验证页'
            await self.session.commit()
            return as_result(op)
        context = json.loads(cached)
        try:
            rows = {row['refund_id']: row for row in await self.platform.applications()}
        except Exception:
            await self.session.rollback()
            raise RefundPlatformError('提交前重新核对失败，尚未提交退款，请刷新')
        entry = dict(order_no=op.order_no, refund_id=op.refund_id, refund_amount=format(op.amount, '.2f'))
        if not matches(rows.get(op.refund_id), entry):
            op.status, op.detail = 'conflict', '申请已变化或不再可处理，没有提交退款'
            await self.session.commit(); await self.cache.delete(self.key(op.id))
            return as_result(op)
        # 提交前持久化占位。双击、超时、重启均不能造成第二次财务调用。
        op.status, op.detail = 'submitting', '已开始提交，结果未返回前请勿重复操作'
        await self.session.commit()
        try:
            result = await self.platform.agree(op.refund_id, context['token'])
            if result == 'success':
                op.status, op.detail = 'success', '平台退款成功清单已确认退款完成'
            else:
                op.status, op.detail = 'submitted', '平台已受理，退款完成状态待同步；请刷新记录核实'
            # 部分退款不能直接把整笔订单标记为已退款；由官方订单同步更新状态。
        except RefundPlatformError as exc:
            op.status, op.detail = 'failed', str(exc)[:300]
        except Exception:
            op.status, op.detail = 'unknown', '平台响应超时或异常，结果未知；请到官方核实，不自动重试'
        finally:
            try:
                await self.cache.delete(self.key(op.id))
            except Exception:
                pass  # 缓存有TTL；清理失败不能覆盖已经获得的平台结果。
        await self.session.commit()
        return as_result(op)
