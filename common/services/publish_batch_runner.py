"""持久化逐件调度：行锁领取、调用前取消检查、中断后不重发。"""
from datetime import timedelta
import asyncio
from uuid import uuid4
from sqlalchemy import and_, or_, select
from loguru import logger
from common.db.session import async_session_maker
from common.models.publish_batch import PublishBatch
from common.models.publish_log import PublishLog
from common.services.batch_publish_item import prepare_batch_item, publish_prepared_batch_item, sync_batch_item
from common.utils.time_utils import get_beijing_now_naive

LEASE_SECONDS = 900


def result_status(result):
    if result.get('success') and (result.get('item_id') or result.get('item_url')):
        return 'success'
    if result.get('success') or result.get('unknown') or result.get('_request_status_unknown') or result.get('result_unknown'):
        return 'unknown'
    return 'failed'


class PublishBatchRunner:
    def __init__(self, static_root='static', *, prepare=prepare_batch_item,
                 publish=publish_prepared_batch_item, sync=sync_batch_item, clock=get_beijing_now_naive):
        self.static_root, self.prepare, self.publish, self.sync, self.clock = static_root, prepare, publish, sync, clock
        self._tasks = set()

    async def execute(self):
        now = self.clock()
        async with async_session_maker() as session:
            ids = (await session.execute(select(PublishBatch.id).where(or_(
                and_(PublishBatch.status == 'waiting', PublishBatch.next_run_at <= now),
                and_(PublishBatch.claim_token.is_not(None), PublishBatch.lease_until <= now),
            )).order_by(PublishBatch.next_run_at).limit(10))).scalars().all()
        for batch_id in ids:
            if len(self._tasks) >= 4:
                break
            task = asyncio.create_task(self._run_guarded(batch_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_guarded(self, batch_id):
        try:
            await self.run_one(batch_id)
        except Exception:
            logger.error('[批量发布] 执行异常，保留领取记录待核查 batch={}', batch_id)

    async def close(self):
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def claim(self, batch_id):
        now = self.clock()
        async with async_session_maker() as session:
            job = (await session.execute(select(PublishBatch).where(PublishBatch.id == batch_id)
                .with_for_update(skip_locked=True))).scalars().first()
            if not job:
                return None
            if job.claim_token:
                if job.lease_until and job.lease_until <= now:
                    log = await session.get(PublishLog, job.current_log_id) if job.current_log_id else None
                    uncertain = log is None or log.status in {'publishing', 'unknown'}
                    if log and log.status == 'publishing':
                        log.error_message = '执行中断，请核查平台商品；本项不会自动重发'
                        log.status = 'unknown'
                    pending = (await session.execute(select(PublishLog.id).where(
                        PublishLog.batch_id == job.id, PublishLog.status == 'pending',
                    ).limit(1))).scalar()
                    if job.cancel_requested:
                        job.status = 'cancelled'; job.next_run_at = None
                    elif uncertain:
                        job.status = 'attention'; job.next_run_at = None
                    elif pending is not None:
                        job.status = 'waiting'
                        job.next_run_at = now + timedelta(seconds=job.interval_seconds)
                    else:
                        job.status = 'completed'; job.next_run_at = None
                    job.last_error = '执行跟踪中断，请核查发布日志和平台商品，未自动重发' if uncertain else None
                    job.claim_token = None; job.current_log_id = None; job.lease_until = None
                    await session.commit()
                return None
            if job.status != 'waiting' or job.cancel_requested or not job.next_run_at or job.next_run_at > now:
                return None
            log = (await session.execute(select(PublishLog).where(
                PublishLog.batch_id == job.id, PublishLog.user_id == job.user_id, PublishLog.status == 'pending',
            ).order_by(PublishLog.id).limit(1).with_for_update())).scalars().first()
            if log is None:
                job.status = 'completed'; job.next_run_at = None
                await session.commit()
                return None
            material = next((m for m in job.materials if m['id'] == log.material_id), None)
            token = str(uuid4())
            job.claim_token = token; job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
            job.current_log_id = log.id; job.status = 'preparing'
            claim = {'batch_id': job.id, 'user_id': job.user_id, 'log_id': log.id,
                     'account_id': log.account_id, 'material': material, 'token': token}
            await session.commit()
            return claim

    async def begin_request(self, claim):
        async with async_session_maker() as session:
            job = (await session.execute(select(PublishBatch).where(PublishBatch.id == claim['batch_id']).with_for_update())).scalars().first()
            if not job or job.claim_token != claim['token']:
                return False
            log = await session.get(PublishLog, claim['log_id'])
            if job.cancel_requested or not log or log.status != 'pending':
                job.status = 'cancelled' if job.cancel_requested else 'attention'
                job.claim_token = None; job.lease_until = None; job.current_log_id = None; job.next_run_at = None
                if log and log.status == 'pending':
                    log.status = 'cancelled'
                await session.commit()
                return False
            log.status = 'publishing'; job.status = 'running'
            await session.commit()
            return True

    async def record_result(self, claim, status, result):
        async with async_session_maker() as session:
            log = (await session.execute(select(PublishLog).where(
                PublishLog.id == claim['log_id'], PublishLog.user_id == claim['user_id'],
            ).with_for_update())).scalars().first()
            if log and log.status != 'cancelled':
                log.status = status
                log.item_id = result.get('item_id')
                log.item_url = result.get('item_url')
                log.error_message = None if status == 'success' else str(result.get('message') or '平台结果待核查')[:1000]
                await session.commit()

    async def finish(self, claim, status, sync_result):
        async with async_session_maker() as session:
            job = (await session.execute(select(PublishBatch).where(PublishBatch.id == claim['batch_id']).with_for_update())).scalars().first()
            if not job or job.claim_token != claim['token']:
                return  # 超时后的迟到结果已由日志保留，不重新启动队列。
            job.sync_results = {**(job.sync_results or {}), claim['account_id']: sync_result}
            pending = (await session.execute(select(PublishLog.id).where(
                PublishLog.batch_id == job.id, PublishLog.status == 'pending',
            ).limit(1))).scalar()
            if job.cancel_requested:
                job.status = 'cancelled'; job.next_run_at = None
            elif status == 'unknown':
                job.status = 'attention'; job.next_run_at = None
                job.last_error = '有商品发布结果待核查，剩余任务已暂停，未自动重发'
            elif pending is None:
                job.status = 'completed'; job.next_run_at = None
            else:
                job.status = 'waiting'
                job.next_run_at = self.clock() + timedelta(seconds=job.interval_seconds)
            job.claim_token = None; job.lease_until = None; job.current_log_id = None
            await session.commit()

    async def run_one(self, batch_id):
        claim = await self.claim(batch_id)
        if not claim:
            return
        try:
            if not claim['material']:
                raise ValueError('任务素材快照缺失，本项未发布')
            context = await self.prepare(claim['user_id'], claim['account_id'], claim['material'], claim['log_id'], self.static_root)
        except Exception as exc:
            result = {'message': str(exc) if isinstance(exc, ValueError) else '发布准备失败，本项未调用发布接口'}
            await self.record_result(claim, 'failed', result)
            await self.finish(claim, 'failed', {'sync_status': 'skipped', 'sync_message': '准备失败，未同步'})
            return
        if not await self.begin_request(claim):
            return
        try:
            result = await self.publish(context)
            if not isinstance(result, dict):
                result = {'unknown': True, 'message': '发布接口返回无法识别的结果，请核查平台商品'}
        except Exception:
            result = {'unknown': True, 'message': '发布调用异常，结果待核查，请检查平台商品后处理'}
        status = result_status(result)
        await self.record_result(claim, status, result)
        try:
            sync_result = await self.sync(context, result)
        except Exception:
            sync_result = {'sync_status': 'failed', 'sync_message': '自动同步失败，请稍后刷新商品管理'}
        await self.finish(claim, status, sync_result)
