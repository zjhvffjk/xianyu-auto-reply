"""人工核查未知发布结果；不调用发布接口、不恢复旧批次队列。"""
import re
from sqlalchemy import select
from common.models.publish_log import PublishLog
from common.models.publish_batch import PublishBatch
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from common.utils.xianyu_utils import canonical_goofish_item_url


async def reconcile_publish_log(session, log_id, user_id, *, actor_id, resolution,
                                confirmed, item_id=None):
    if confirmed is not True or resolution not in {'published', 'not_published'}:
        raise ValueError('请先在目标店铺核查商品，再明确确认核查结果')
    if resolution == 'published' and not re.fullmatch(r'\d{6,24}', item_id or ''):
        raise ValueError('请填写已发布商品的数字ID')
    if resolution == 'not_published' and item_id:
        raise ValueError('未发布的核查结果不能填写商品ID')

    def scoped_log():
        query = select(PublishLog).where(PublishLog.id == log_id)
        return query.where(PublishLog.user_id == user_id) if user_id is not None else query

    initial = (await session.execute(scoped_log())).scalar_one_or_none()
    if not initial:
        raise ValueError('发布记录不存在或无权操作')
    # 锁顺序与调度器保持一致：批次在先，日志在后；终态日志的迟到结果不能被覆盖。
    if initial.batch_id:
        job = (await session.execute(select(PublishBatch).where(
            PublishBatch.id == initial.batch_id, PublishBatch.user_id == initial.user_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if job and (job.claim_token or job.status in {'preparing', 'running', 'cancelling'}):
            raise ValueError('该批次仍在执行，请等待执行结束后核查')
    log = (await session.execute(scoped_log().with_for_update()
          .execution_options(populate_existing=True))).scalar_one_or_none()
    if not log or log.status != 'unknown':
        raise ValueError('仅可核查结果未知的发布记录，请刷新后查看当前状态')
    if log.source_event_id is not None:
        raise ValueError('自动续售记录请在对应素材的续售记录中核查')
    if resolution == 'published':
        item = (await session.execute(select(XYCatalogItem).join(
            XYAccount, XYAccount.id == XYCatalogItem.account_pk,
        ).where(XYAccount.owner_id == log.user_id, XYAccount.account_id == log.account_id,
                XYCatalogItem.owner_id == log.user_id, XYCatalogItem.item_id == item_id))).scalar_one_or_none()
        if not item:
            raise ValueError('商品管理中未找到该店铺的商品ID，请先在目标店铺刷新商品后核查')
        log.status, log.item_id = 'success', item_id
        log.item_url = canonical_goofish_item_url(item_id)
        note = '已在目标店铺确认发布成功，并补录商品ID'
    else:
        log.status = 'failed'
        log.item_id = log.item_url = None
        note = '已核查目标店铺，确认本次未发布；可重新创建发布任务'
    log.error_message = f'人工核查（用户{actor_id}）：{note}。原记录：{log.error_message or "无"}'[:1000]
    await session.commit()
    return log
