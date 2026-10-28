"""按账号在后台补全完整资料；不修改平台商品或已导入素材。"""
import asyncio
import json
import time
from uuid import uuid4
from types import SimpleNamespace
from contextlib import asynccontextmanager

from sqlalchemy import select
from loguru import logger

from common.db.redis_client import get_redis_client
from common.db.session import async_session_maker
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from app.services.catalog_detail_cache import cache_catalog_form, has_complete_catalog_form
from app.services.xianyu_item_edit_service import fetch_seller_item_edit_detail

THROTTLE_SECONDS = 1
LEASE_SECONDS = 120
STATUS_SECONDS = 86400
_tasks = set()
_concurrency = asyncio.Semaphore(2)


def _task_done(task):
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning('商品资料任务提前退出: error_type={}', type(task.exception()).__name__)

_SAVE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""
_RENEW = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('EXPIRE', KEYS[1], ARGV[2])
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
return redis.call('DEL', KEYS[1])
"""


class LeaseLost(Exception):
    pass


class CatalogDetailSyncService:
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def lease_key(account_pk):
        return f'catalog-detail:lease:{account_pk}'

    @staticmethod
    def job_key(account_pk, job_id):
        return f'catalog-detail:job:{account_pk}:{job_id}'

    @asynccontextmanager
    async def _control(self, account_pk):
        # 启动和结束使用短锁，避免“刚好结束时又获取一批商品”丢失补全请求。
        key, token = f'catalog-detail:control:{account_pk}', uuid4().hex
        for _ in range(20):
            if await self.redis.set(key, token, nx=True, ex=10):
                break
            await asyncio.sleep(0.05)
        else:
            raise ValueError('资料任务正在更新，请稍后重试')
        try:
            yield
        finally:
            await self.redis.eval(_RELEASE, 1, key, token)

    async def get(self, account_pk, job_id=None):
        job_id = job_id or await self.redis.get(f'catalog-detail:latest:{account_pk}')
        if not job_id:
            return None
        raw = await self.redis.get(self.job_key(account_pk, job_id))
        if not raw:
            return None
        job = json.loads(raw)
        if job['state'] in ('queued', 'running') and await self.redis.get(self.lease_key(account_pk)) != job_id:
            job.update(state='interrupted', message='资料补全已中断，可重新补全；已获取的资料已保留')
        return job

    async def start(self, account, priority_item_ids=None, *, fetch_catalog=False):
        async with self._control(account.id):
            return await self._start_locked(account, priority_item_ids, fetch_catalog)

    async def _prioritize(self, account_pk, job_id, item_ids):
        if not item_ids:
            return
        key = f'catalog-detail:priority:{account_pk}:{job_id}'
        old = json.loads(await self.redis.get(key) or '[]')
        priority = list(dict.fromkeys([*item_ids, *old]))[:200]
        await self.redis.set(key, json.dumps(priority), ex=STATUS_SECONDS)

    async def _start_locked(self, account, priority_item_ids, fetch_catalog):
        account_pk, owner_id, account_id = account.id, account.owner_id, account.account_id
        active = await self.redis.get(self.lease_key(account_pk))
        if active:
            job = await self.get(account_pk, active)
            if job and job['state'] in ('queued', 'running'):
                await self._prioritize(account_pk, active, priority_item_ids)
                if fetch_catalog:
                    await self.redis.set(f'catalog-detail:fetch:{account_pk}:{active}', '1', ex=STATUS_SECONDS)
                await self.redis.set(f'catalog-detail:rescan:{account_pk}:{active}', '1', ex=STATUS_SECONDS)
                return job
            await self.redis.eval(_RELEASE, 1, self.lease_key(account_pk), active)
        job_id = uuid4().hex
        if not await self.redis.set(self.lease_key(account_pk), job_id, nx=True, ex=LEASE_SECONDS):
            job = await self.get(account_pk, await self.redis.get(self.lease_key(account_pk)))
            if job:
                return job
            raise ValueError('资料补全任务正在启动，请稍后重试')
        job = dict(job_id=job_id, account_id=account_id, state='queued', total=0, processed=0,
                   succeeded=0, cached=0, failed=0, failures=[], checked_item_ids=[], message='等待补全商品资料', updated_at=time.time())
        try:
            await self._save(account_pk, job)
            await self._prioritize(account_pk, job_id, priority_item_ids)
            if fetch_catalog:
                await self.redis.set(f'catalog-detail:fetch:{account_pk}:{job_id}', '1', ex=STATUS_SECONDS)
            await self.redis.set(f'catalog-detail:latest:{account_pk}', job_id, ex=STATUS_SECONDS)
            self._spawn(account_pk, owner_id, job_id)
        except BaseException:
            await self.redis.eval(_RELEASE, 1, self.lease_key(account_pk), job_id)
            raise
        return job

    def _spawn(self, account_pk, owner_id, job_id):
        task = asyncio.create_task(self.run(account_pk, owner_id, job_id))
        _tasks.add(task)
        task.add_done_callback(_task_done)

    async def _save(self, account_pk, job):
        job['updated_at'] = time.time()
        owned = await self.redis.eval(_SAVE, 2, self.lease_key(account_pk), self.job_key(account_pk, job['job_id']),
                                      job['job_id'], json.dumps(job, ensure_ascii=False), STATUS_SECONDS, LEASE_SECONDS)
        if not owned:
            raise LeaseLost()

    async def _heartbeat(self, account_pk, job_id):
        while True:
            await asyncio.sleep(20)
            if not await self.redis.eval(_RENEW, 1, self.lease_key(account_pk), job_id, LEASE_SECONDS):
                return

    async def _item_ids(self, account_pk, owner_id):
        async with async_session_maker() as session:
            result = await session.execute(select(XYCatalogItem.item_id).where(
                XYCatalogItem.account_pk == account_pk, XYCatalogItem.owner_id == owner_id,
            ).order_by(XYCatalogItem.id.desc()))
            return list(dict.fromkeys(result.scalars().all()))

    async def _fetch_catalog(self, account_pk, owner_id):
        """登录成功后独立获取列表，不占用登录请求的数据库会话。"""
        from common.services.item_service import ItemService
        async with async_session_maker() as session:
            account = (await session.execute(select(XYAccount).where(
                XYAccount.id == account_pk, XYAccount.owner_id == owner_id,
            ))).scalars().first()
            if not account or account.status in ('inactive', 'disabled', 'suspended', 'deleted'):
                return {'success': False}
            return await ItemService(session).fetch_all_items_from_account(account=account)

    async def _fill_one(self, account_pk, owner_id, item_id):
        async with async_session_maker() as session:
            account = (await session.execute(select(XYAccount).where(
                XYAccount.id == account_pk, XYAccount.owner_id == owner_id,
            ))).scalars().first()
            if not account:
                return dict(status='failed', message='店铺已移除，已停止补全', stop=True)
            if account.status in ('inactive', 'disabled', 'suspended', 'deleted'):
                return dict(status='failed', message='店铺已禁用，已停止补全', stop=True)
            item_query = select(XYCatalogItem).where(XYCatalogItem.account_pk == account_pk,
                XYCatalogItem.owner_id == owner_id, XYCatalogItem.item_id == item_id)
            catalog = (await session.execute(item_query)).scalars().first()
            if not catalog:
                return dict(status='failed', message='商品已从商品管理移除')
            if has_complete_catalog_form(catalog):
                return dict(status='cached')
            params = dict(account_id=account.account_id, cookie=account.cookie, owner_id=owner_id, item_id=item_id)
            # 网络读取不占用数据库事务，返回后重新加锁合并最新元数据。
            await session.rollback()
            result = await asyncio.wait_for(fetch_seller_item_edit_detail(**params), timeout=75)
            if not result.get('success'):
                message = str(result.get('message') or '平台暂未返回完整资料')[:500]
                stop = bool(result.get('account_invalid')) or any(word in message for word in ('未开通鱼小铺', '风控', '验证', '限流'))
                return dict(status='failed', message=message, stop=stop)
            form = (result.get('data') or {}).get('form')
            candidate = SimpleNamespace(metadata_json={'material_form': form})
            if not has_complete_catalog_form(candidate):
                return dict(status='failed', message='平台返回的完整描述、图片或发货资料不完整，可稍后重试')
            catalog = (await session.execute(item_query.with_for_update())).scalars().first()
            if not catalog:
                return dict(status='failed', message='商品已从商品管理移除')
            if has_complete_catalog_form(catalog):
                return dict(status='cached')
            cache_catalog_form(catalog, form)
            await session.commit()
            return dict(status='success')

    async def run(self, account_pk, owner_id, job_id):
        job = await self.get(account_pk, job_id)
        if not job or job['state'] != 'queued':
            return
        heartbeat = asyncio.create_task(self._heartbeat(account_pk, job_id))
        try:
            async with _concurrency:
                job.update(state='running', message='正在读取商品完整资料')
                await self._save(account_pk, job)
                seen = set()
                while True:
                    async with self._control(account_pk):
                        fetch_key = f'catalog-detail:fetch:{account_pk}:{job_id}'
                        fetch_catalog = bool(await self.redis.get(fetch_key))
                        if fetch_catalog:
                            await self.redis.delete(fetch_key)
                    if fetch_catalog:
                        result = await self._fetch_catalog(account_pk, owner_id)
                        if not result.get('success'):
                            job['catalog_error'] = '商品列表获取未完成，已有资料已保留，可在导入时重试'
                            logger.warning('登录后商品列表获取未完成: account_pk={}', account_pk)
                        else:
                            job.pop('catalog_error', None)
                    item_ids = [item_id for item_id in await self._item_ids(account_pk, owner_id) if item_id not in seen]
                    seen.update(item_ids)
                    job['total'] += len(item_ids)
                    await self._save(account_pk, job)
                    while item_ids:
                        priority = json.loads(await self.redis.get(f'catalog-detail:priority:{account_pk}:{job_id}') or '[]')
                        item_id = next((item_id for item_id in priority if item_id in item_ids), item_ids[0])
                        item_ids.remove(item_id)
                        await self._save(account_pk, job)  # 租约丢失时不再请求平台。
                        try:
                            result = await self._fill_one(account_pk, owner_id, item_id)
                        except TimeoutError:
                            result = dict(status='failed', message='读取超时，可重试')
                        except Exception as exc:
                            logger.warning('补全商品资料失败: item_id={}, error_type={}', item_id, type(exc).__name__)
                            result = dict(status='failed', message='读取资料失败，请稍后重试')
                        job['processed'] += 1
                        job['checked_item_ids'].append(item_id)
                        key = {'success': 'succeeded', 'cached': 'cached', 'failed': 'failed'}[result['status']]
                        job[key] += 1
                        if key == 'failed' and len(job['failures']) < 50:
                            job['failures'].append(dict(item_id=item_id, message=result['message']))
                        if result.get('stop'):
                            job.update(state='failed', message=result['message'] + '；已停止后续读取，恢复账号后可重试')
                            break
                        await self._save(account_pk, job)
                        if key != 'cached' and job['processed'] < job['total']:
                            await asyncio.sleep(THROTTLE_SECONDS)
                    async with self._control(account_pk):
                        rescan_key = f'catalog-detail:rescan:{account_pk}:{job_id}'
                        if job['state'] != 'running' and await self.redis.get(f'catalog-detail:fetch:{account_pk}:{job_id}'):
                            # 旧 Cookie 的失败不能吞掉刚保存的新登录；使用新凭据重新扫描。
                            seen.clear()
                            job.update(state='running', total=0, processed=0, succeeded=0, cached=0,
                                       failed=0, failures=[], checked_item_ids=[], message='正在获取登录账号的商品资料')
                            await self.redis.delete(rescan_key)
                            await self._save(account_pk, job)
                            continue
                        if job['state'] == 'running' and await self.redis.get(rescan_key):
                            await self.redis.delete(rescan_key)
                            continue
                        if job['state'] == 'running':
                            job.update(state='completed', message='商品资料补全完成' if not job['failed'] else '部分商品未补全，可重试失败项')
                            if job.get('catalog_error'):
                                job.update(state='failed', message=job['catalog_error'])
                        await self._save(account_pk, job)
                        await self.redis.eval(_RELEASE, 1, self.lease_key(account_pk), job_id)
                        break
        except LeaseLost:
            pass
        except asyncio.CancelledError:
            job.update(state='interrupted', message='资料补全已中断，可重新补全')
            try:
                await self._save(account_pk, job)
            except Exception:
                pass
            raise
        except Exception as exc:
            logger.warning('商品资料任务中断: account_pk={}, error_type={}', account_pk, type(exc).__name__)
            job.update(state='failed', message='资料补全服务暂不可用，已获取的资料已保留，请重试')
            try:
                await self._save(account_pk, job)
            except Exception:
                pass
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                await self.redis.eval(_RELEASE, 1, self.lease_key(account_pk), job_id)
            except Exception:
                pass


async def enqueue_catalog_detail_sync(account, *, fetch_catalog=False):
    """列表已成功入库时，后台补全不可用不能把列表结果改成失败。"""
    try:
        return {'detail_sync': await CatalogDetailSyncService(await get_redis_client()).start(account, fetch_catalog=fetch_catalog)}
    except Exception as exc:
        logger.warning('无法启动商品资料补全: error_type={}', type(exc).__name__)
        return {'detail_sync_error': '完整商品资料暂未补齐，导入时将自动重试'}
