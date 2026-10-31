"""任务历史分页契约与轻量查询；隔离临时表，不执行真实任务。"""
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, '/app/backend-web')
from app.api.routes import product_publish as routes
from common.db.session import async_engine
from common.models.publish_batch import PublishBatch
from common.models.publish_log import PublishLog
from common.services.publish_batch_jobs import PublishBatchJobs


class TaskPaginationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI(); app.include_router(routes.router)
        app.dependency_overrides[routes.get_current_active_user] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[routes.get_db_session] = lambda: None
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_requested_page_size_and_owner_reach_query(self):
        for size in (10, 20, 50, 100):
            with self.subTest(size=size), patch.object(PublishBatchJobs, 'list', AsyncMock(return_value={})) as query:
                response = await self.client.get(f'/product-publish/publish/batches?page=2&page_size={size}')
                self.assertEqual(response.status_code, 200)
                query.assert_awaited_once_with(7, 2, size)

    async def test_legacy_default_stays_ten(self):
        with patch.object(PublishBatchJobs, 'list', AsyncMock(return_value={})) as query:
            self.assertEqual((await self.client.get('/product-publish/publish/batches')).status_code, 200)
            query.assert_awaited_once_with(7, 1, 10)

    async def test_invalid_page_and_size_do_not_query(self):
        with patch.object(PublishBatchJobs, 'list', AsyncMock(return_value={})) as query:
            for params in ('page=0', 'page_size=0', 'page_size=101', 'page_size=bad'):
                self.assertEqual((await self.client.get('/product-publish/publish/batches?' + params)).status_code, 422)
            query.assert_not_awaited()


class TaskPaginationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await async_engine.connect()
        for table in ('xy_publish_batches', 'xy_publish_logs'):
            ddl = (await self.conn.execute(text(f'SHOW CREATE TABLE {table}'))).one()[1]
            await self.conn.execute(text(ddl.replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', 1)))
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.db.close()
        for table in ('xy_publish_logs', 'xy_publish_batches'):
            await self.conn.execute(text(f'DROP TEMPORARY TABLE {table}'))
        await self.conn.commit(); await self.conn.close(); await async_engine.dispose()

    async def test_large_history_page_preserves_counts_owner_and_clear_scope(self):
        for i in range(103):
            batch_id = f'test-history-{i:03}'
            owner = 8 if i == 102 else 7
            self.db.add(PublishBatch(id=batch_id, user_id=owner, mode='immediate', status='completed',
                start_at=datetime(2026, 10, 31), interval_seconds=60, account_ids=['test-shop'],
                materials=[{'description':'快照不应参与历史查询' * 100}], sync_results={},
                history_cleared_at=datetime(2026, 10, 31) if i == 101 else None))
            for status in ('success', 'failed', 'unknown'):
                self.db.add(PublishLog(user_id=owner, account_id='test-shop', batch_id=batch_id,
                    title='test-only', description='日志正文不应参与历史查询' * 100, status=status))
        await self.db.commit(); self.db.expunge_all()
        service = PublishBatchJobs(self.db)
        result = await service.list(7, 1, 100)
        self.assertEqual((result['total'], result['page_size'], len(result['list'])), (101, 100, 100))
        self.assertTrue(all((j['total'], j['success'], j['failed'], j['unknown']) == (3, 1, 1, 1) for j in result['list']))
        self.assertTrue(all('items' not in j for j in result['list']))
        last = await service.list(7, 2, 100)
        self.assertEqual(len(last['list']), 1)
        self.assertTrue(set(j['batch_id'] for j in result['list']).isdisjoint(j['batch_id'] for j in last['list']))
        self.assertNotIn('test-history-101', [j['batch_id'] for j in result['list'] + last['list']])
        self.assertNotIn('test-history-102', [j['batch_id'] for j in result['list'] + last['list']])
