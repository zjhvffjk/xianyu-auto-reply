"""连接私有临时表验证清空展示记录；不删除业务表、不触发远端发布。"""
import sys
import unittest
from datetime import datetime
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, '/app/backend-web')
from common.db.session import async_engine
from common.models.publish_batch import PublishBatch
from common.models.publish_log import PublishLog
from common.services.publish_batch_jobs import PublishBatchJobs
from common.services.publish_log_service import PublishLogService


class PublishHistoryClearTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await async_engine.connect()
        for table in ('xy_publish_batches', 'xy_publish_logs'):
            ddl = (await self.conn.execute(text(f'SHOW CREATE TABLE {table}'))).one()[1]
            await self.conn.execute(text(ddl.replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', 1)))
            fields = (await self.conn.execute(text(f'SHOW COLUMNS FROM {table}'))).all()
            if 'history_cleared_at' not in {r[0] for r in fields}:
                await self.conn.execute(text(f'ALTER TABLE {table} ADD COLUMN history_cleared_at DATETIME NULL'))
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.db.close()
        for table in ('xy_publish_logs', 'xy_publish_batches'):
            await self.conn.execute(text(f'DROP TEMPORARY TABLE {table}'))
        await self.conn.commit()
        await self.conn.close()
        await async_engine.dispose()

    async def batch(self, status, owner=9, claim=None):
        row = PublishBatch(id=str(uuid4()), user_id=owner, mode='scheduled', status=status,
            start_at=datetime(2099,1,1), next_run_at=datetime(2099,1,1) if status=='waiting' else None,
            interval_seconds=60, account_ids=['test-shop'], materials=[], sync_results={}, claim_token=claim)
        self.db.add(row); await self.db.flush()
        return row

    async def log(self, status, batch=None, owner=9):
        row = PublishLog(user_id=owner, account_id='test-shop', title='test-only', status=status,
            batch_id=batch.id if batch else None, publish_request_id=str(uuid4()))
        self.db.add(row); await self.db.flush()
        return row

    async def test_clear_recent_history_in_both_lists_without_deleting_safety_records(self):
        from common.services.publish_history_clear import clear_publish_history
        done=await self.batch('completed'); cancelled=await self.batch('cancelled')
        archived=await self.log('success',done)
        await self.log('cancelled',cancelled); await self.log('failed'); await self.log('success')
        waiting=await self.batch('waiting'); await self.log('success',waiting); await self.log('pending',waiting)
        running=await self.batch('running',claim='test-active'); await self.log('publishing',running)
        uncertain=await self.batch('cancelled'); await self.log('unknown',uncertain); await self.log('cancelled',uncertain)
        other=await self.batch('completed',owner=10); await self.log('success',other,owner=10)
        await self.db.commit()
        result=await clear_publish_history(self.db,9)
        self.assertEqual((result['cleared_logs'],result['cleared_batches']),(4,2))
        self.assertEqual((result['retained_logs'],result['retained_batches']),(5,3))
        self.assertEqual((await PublishLogService(self.db).list_logs(9))['total'],5)
        self.assertEqual((await PublishBatchJobs(self.db).list(9))['total'],3)
        self.assertEqual((await PublishLogService(self.db).list_logs(10))['total'],1)
        self.assertEqual((await PublishBatchJobs(self.db).list(10))['total'],1)
        self.assertEqual((await PublishLogService(self.db).get_by_request_id(archived.publish_request_id)).id,archived.id)
        self.assertEqual((await PublishBatchJobs(self.db).detail(done.id,9))['success'],1)
        self.assertTrue((await PublishBatchJobs(self.db).detail(done.id,9))['history_cleared'])
        self.assertFalse(waiting.cancel_requested)
        self.assertEqual(waiting.status,'waiting')
        second=await clear_publish_history(self.db,9)
        self.assertEqual((second['cleared_logs'],second['cleared_batches']),(0,0))

    async def test_running_task_completion_after_clear_still_has_new_visible_result(self):
        from common.services.publish_history_clear import clear_publish_history
        job=await self.batch('waiting'); row=await self.log('pending',job)
        await self.db.commit(); await clear_publish_history(self.db,9)
        row.status='success'; job.status='completed'; job.next_run_at=None
        await self.db.commit()
        self.assertEqual((await PublishLogService(self.db).list_logs(9))['total'],1)
        self.assertEqual((await PublishBatchJobs(self.db).list(9))['total'],1)
        await clear_publish_history(self.db,9)
        self.assertEqual((await PublishLogService(self.db).list_logs(9))['total'],0)
        self.assertEqual((await PublishBatchJobs(self.db).list(9))['total'],0)

    async def test_terminal_batch_with_claim_or_pending_rows_is_kept(self):
        from common.services.publish_history_clear import clear_publish_history
        for claim,status in [('test-late','success'),(None,'pending')]:
            job=await self.batch('cancelled',claim=claim); await self.log(status,job)
        await self.db.commit(); result=await clear_publish_history(self.db,9)
        self.assertEqual(result['cleared_batches'],0)
        self.assertEqual(result['cleared_logs'],0)


class PublishHistoryClearRouteTests(unittest.TestCase):
    def test_clear_is_scoped_to_current_user_including_admin(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes import product_publish as routes
        from common.models.user import UserRole
        for role in (UserRole.MEMBER,UserRole.ADMIN):
            with self.subTest(role=role):
                db=AsyncMock(); user=SimpleNamespace(id=9,role=role)
                app=FastAPI(); app.include_router(routes.router)
                app.dependency_overrides[routes.get_current_active_user]=lambda:user
                app.dependency_overrides[routes.get_db_session]=lambda:db
                counts=dict(cleared_logs=4,cleared_batches=2,retained_logs=5,retained_batches=3)
                with TestClient(app) as client, patch('common.services.publish_history_clear.clear_publish_history',
                        AsyncMock(return_value=counts)) as clear:
                    result=client.delete('/product-publish/logs/clear').json()
                    self.assertTrue(result['success'])
                    self.assertEqual(result['data'],counts)
                    self.assertNotIn('10天',result['message'])
                    self.assertIn('保留',result['message'])
                    self.assertEqual(clear.call_args.args,(db,9))


if __name__=='__main__': unittest.main()
