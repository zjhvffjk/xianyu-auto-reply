"""清空已结束发布历史的展示；保留执行状态、幂等记录和待核查事项。"""
from sqlalchemy import select
from common.models.publish_batch import PublishBatch
from common.models.publish_log import PublishLog
from common.utils.time_utils import get_beijing_now_naive

FINAL_LOG_STATES = {'success', 'failed', 'cancelled'}
FINAL_BATCH_STATES = {'completed', 'cancelled'}


def batch_history_deletable(job, logs):
    return (job.history_cleared_at is None and not job.claim_token
            and job.status in FINAL_BATCH_STATES
            and all(log.status in FINAL_LOG_STATES for log in logs))


async def clear_selected_batch_history(session, user_id, batch_ids):
    """仅移除所选任务的历史展示，保留发布日志和执行/幂等数据。"""
    selected = set(batch_ids)
    # 锁顺序与执行器、取消及清空日志一致；重新读取状态，不能信任网页的旧结果。
    jobs = (await session.execute(select(PublishBatch).where(
        PublishBatch.user_id == user_id, PublishBatch.id.in_(selected),
        PublishBatch.history_cleared_at.is_(None),
    ).order_by(PublishBatch.id).with_for_update()
      .execution_options(populate_existing=True))).scalars().all()
    logs = (await session.execute(select(PublishLog).where(
        PublishLog.user_id == user_id, PublishLog.batch_id.in_([j.id for j in jobs]),
    ).order_by(PublishLog.id).with_for_update()
      .execution_options(populate_existing=True))).scalars().all() if jobs else []
    stamp = get_beijing_now_naive()
    cleared = 0
    for job in jobs:
        if batch_history_deletable(job, (log for log in logs if log.batch_id == job.id)):
            job.history_cleared_at = stamp
            cleared += 1
    await session.commit()
    return {'cleared_batches': cleared, 'retained_batches': len(jobs) - cleared,
            'unavailable_batches': len(selected) - len(jobs)}


async def clear_publish_history(session, user_id):
    # 与执行器/核查流程相同的锁顺序：先批次，再日志。
    jobs = (await session.execute(select(PublishBatch).where(
        PublishBatch.user_id == user_id, PublishBatch.history_cleared_at.is_(None),
    ).order_by(PublishBatch.id).with_for_update()
      .execution_options(populate_existing=True))).scalars().all()
    logs = (await session.execute(select(PublishLog).where(
        PublishLog.user_id == user_id, PublishLog.history_cleared_at.is_(None),
    ).order_by(PublishLog.id).with_for_update()
      .execution_options(populate_existing=True))).scalars().all()
    open_batches = {j.id for j in jobs if j.claim_token or j.status not in FINAL_BATCH_STATES}
    open_batches.update(log.batch_id for log in logs if log.batch_id and log.status not in FINAL_LOG_STATES)
    stamp = get_beijing_now_naive()
    cleared_logs = cleared_batches = 0
    for log in logs:
        if log.status in FINAL_LOG_STATES and log.batch_id not in open_batches:
            log.history_cleared_at = stamp
            cleared_logs += 1
    for job in jobs:
        if job.id not in open_batches:
            job.history_cleared_at = stamp
            cleared_batches += 1
    await session.commit()
    return {'cleared_logs': cleared_logs, 'cleared_batches': cleared_batches,
            'retained_logs': len(logs) - cleared_logs, 'retained_batches': len(jobs) - cleared_batches}
