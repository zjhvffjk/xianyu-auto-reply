"""批量任务持久化查询与取消；与网页、scheduler共用。"""
from collections import Counter
from datetime import datetime
from sqlalchemy import func, select
from common.models.publish_batch import PublishBatch
from common.models.publish_log import PublishLog
from common.utils.time_utils import BEIJING_TZ, get_beijing_now_naive
from common.utils.xianyu_utils import canonical_goofish_item_url

TERMINAL_BATCH_STATES = {'completed', 'cancelled'}


def normalize_batch_start(mode: str, start_at: datetime | None, now: datetime | None = None) -> datetime:
    now = now or get_beijing_now_naive()
    if mode == 'immediate':
        return now.replace(microsecond=0)
    if mode != 'scheduled' or start_at is None:
        raise ValueError('定时发布请选择开始时间（北京时间）')
    if start_at.tzinfo is not None:
        start_at = start_at.astimezone(BEIJING_TZ).replace(tzinfo=None)
    start_at = start_at.replace(microsecond=0)
    if start_at <= now:
        raise ValueError('定时开始时间必须晚于当前北京时间，请重新选择')
    return start_at


def beijing_iso(value):
    return value.replace(tzinfo=BEIJING_TZ).isoformat() if value else None


def batch_data(job, logs, *, details=True):
    counts = Counter(log.status for log in logs)
    accounts = []
    for aid in job.account_ids:
        c = Counter(log.status for log in logs if log.account_id == aid)
        sync = (job.sync_results or {}).get(aid, {})
        accounts.append({'account_id': aid, 'total': sum(c.values()), 'success': c['success'],
            'failed': c['failed'], 'publishing': c['publishing'], 'pending': c['pending'],
            'sync_status': sync.get('sync_status', 'pending'), 'sync_message': sync.get('sync_message', '等待发布后同步商品'),
            'sync_total_count': sync.get('sync_total_count', 0), 'sync_saved_count': sync.get('sync_saved_count', 0)})
    data = {'batch_id': job.id, 'mode': job.mode, 'status': job.status,
        'start_at': beijing_iso(job.start_at), 'next_run_at': beijing_iso(job.next_run_at),
        'interval_seconds': job.interval_seconds, 'created_at': beijing_iso(job.created_at),
        'total': len(logs), 'success': counts['success'], 'failed': counts['failed'],
        'publishing': counts['publishing'], 'pending': counts['pending'], 'cancelled': counts['cancelled'],
        'unknown': counts['unknown'], 'finished': job.status in TERMINAL_BATCH_STATES,
        'tracking_lost': job.status == 'attention', 'message': job.last_error or '',
        'cancel_requested': job.cancel_requested, 'account_statuses': accounts,
        'account_ids': job.account_ids, 'history_cleared': getattr(job, 'history_cleared_at', None) is not None}
    if details:
        data['items'] = [{'id': log.id, 'account_id': log.account_id, 'material_id': log.material_id,
            'title': log.title, 'status': log.status, 'item_id': log.item_id,
            'item_url': canonical_goofish_item_url(log.item_id) if log.item_id else None,
            'error_message': log.error_message} for log in logs]
    return data


class PublishBatchJobs:
    def __init__(self, session):
        self.session = session

    async def get(self, batch_id, user_id, *, lock=False):
        query = select(PublishBatch).where(PublishBatch.id == batch_id, PublishBatch.user_id == user_id)
        return (await self.session.execute(query.with_for_update() if lock else query)).scalars().first()

    async def logs(self, batch_id, user_id, *, lock=False):
        query = select(PublishLog).where(
            PublishLog.batch_id == batch_id, PublishLog.user_id == user_id,
        ).order_by(PublishLog.id)
        return (await self.session.execute(query.with_for_update() if lock else query)).scalars().all()

    async def detail(self, batch_id, user_id):
        job = await self.get(batch_id, user_id)
        return batch_data(job, await self.logs(batch_id, user_id)) if job else None

    async def list(self, user_id, page=1, page_size=10):
        total = (await self.session.execute(select(func.count()).select_from(PublishBatch).where(
            PublishBatch.user_id == user_id, PublishBatch.history_cleared_at.is_(None)))).scalar() or 0
        jobs = (await self.session.execute(select(PublishBatch).where(PublishBatch.user_id == user_id,
            PublishBatch.history_cleared_at.is_(None))
            .order_by(PublishBatch.created_at.desc(), PublishBatch.id.desc()).offset((page-1)*page_size).limit(page_size))).scalars().all()
        logs = (await self.session.execute(select(PublishLog).where(
            PublishLog.user_id == user_id, PublishLog.batch_id.in_([j.id for j in jobs]),
        ).order_by(PublishLog.id))).scalars().all() if jobs else []
        return {'list': [batch_data(j, [log for log in logs if log.batch_id == j.id], details=False) for j in jobs],
                'total': total, 'page': page, 'page_size': page_size}

    async def cancel(self, batch_id, user_id):
        job = await self.get(batch_id, user_id, lock=True)
        if job is None:
            raise ValueError('任务不存在或无权操作')
        if job.status in TERMINAL_BATCH_STATES:
            return await self.detail(batch_id, user_id)
        job.cancel_requested = True
        logs = await self.logs(batch_id, user_id, lock=True)
        for log in logs:
            if log.status == 'pending':
                log.status = 'cancelled'
                log.error_message = '用户取消，未调用发布接口'
        # 有领取令牌时，先等待执行者确认停止；已发往平台的请求不能撤回。
        job.status = 'cancelling' if job.claim_token else 'cancelled'
        job.next_run_at = None
        await self.session.commit()
        return await self.detail(batch_id, user_id)
