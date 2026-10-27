"""MySQL隔离模拟：所有任务开始于2099年，所有平台调用均由测试替身注入。"""
import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4
from sqlalchemy import delete, select, text
sys.path.insert(0, '/app/backend-web')
from common.db.session import async_engine, async_session_maker
from common.db.publish_batch_schema import PUBLISH_BATCH_DDL
from common.models.publish_batch import PublishBatch
from common.models.publish_log import PublishLog
from common.models.product_material import ProductMaterial
from common.services.publish_batch_jobs import PublishBatchJobs, normalize_batch_start
from common.services.publish_batch_runner import PublishBatchRunner, LEASE_SECONDS, result_status
from app.services.batch_publish_service import BatchPublishService
from app.services.product_publish_service import ProductMaterialService

OWNER = -20261025
FUTURE = datetime(2099, 1, 1, 12)


class TimeTests(unittest.TestCase):
    def test_beijing_and_offset_normalize_to_same_time(self):
        now = datetime(2026,10,25,15)
        self.assertEqual(normalize_batch_start('scheduled', datetime(2026,10,25,8,tzinfo=timezone.utc), now), datetime(2026,10,25,16))
        self.assertEqual(normalize_batch_start('scheduled', datetime(2026,10,25,16), now), datetime(2026,10,25,16))

    def test_past_or_empty_scheduled_never_runs_immediately(self):
        for value in [None, datetime(2026,10,25,14), datetime(2026,10,25,15)]:
            with self.assertRaises(ValueError):
                normalize_batch_start('scheduled', value, datetime(2026,10,25,15))

    def test_unknown_results_never_become_failures_for_retry(self):
        for value in [dict(success=True), dict(_request_status_unknown=True), dict(result_unknown=True)]:
            self.assertEqual(result_status(value), 'unknown')
        self.assertEqual(result_status(dict(success=True,item_id='known')), 'success')
        self.assertEqual(result_status(dict(success=False)), 'failed')


class ScheduleDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ids = []
        self.material_ids = []
        self.now = FUTURE
        self.prepare = AsyncMock(return_value={'test_only':True})
        self.publish = AsyncMock(return_value={'success':True, 'item_id':'test-only-item'})
        self.sync = AsyncMock(return_value={'sync_status':'success', 'sync_message':'test-only'})
        self.runner = self.new_runner()
        async with async_engine.begin() as conn:
            await conn.execute(text(PUBLISH_BATCH_DDL))

    def new_runner(self):
        return PublishBatchRunner(prepare=self.prepare, publish=self.publish, sync=self.sync, clock=lambda:self.now)

    async def asyncTearDown(self):
        async with async_session_maker() as session:
            if self.ids:
                await session.execute(delete(PublishLog).where(PublishLog.batch_id.in_(self.ids), PublishLog.user_id == OWNER))
                await session.execute(delete(PublishBatch).where(PublishBatch.id.in_(self.ids), PublishBatch.user_id == OWNER))
            if self.material_ids:
                await session.execute(delete(ProductMaterial).where(ProductMaterial.id.in_(self.material_ids), ProductMaterial.user_id == OWNER))
            await session.commit()
        await async_engine.dispose()

    async def create(self, count=2, start=None):
        batch_id = str(uuid4()); self.ids.append(batch_id)
        materials = [dict(id=900000+i, title='test-only', description='test-only', price=1, images=['https://example.com/test.png']) for i in range(count)]
        async with async_session_maker() as session:
            await BatchPublishService(session).register(OWNER,batch_id,['test-only-account'],materials,
                start_at=start or FUTURE, interval_seconds=60, mode='scheduled')
        return batch_id

    async def detail(self, batch_id):
        async with async_session_maker() as session:
            return await PublishBatchJobs(session).detail(batch_id, OWNER)

    async def cancel(self, batch_id):
        async with async_session_maker() as session:
            return await PublishBatchJobs(session).cancel(batch_id, OWNER)

    async def test_not_due_does_not_publish_then_each_item_waits_from_completion(self):
        bid = await self.create(start=FUTURE+timedelta(seconds=10))
        await self.runner.run_one(bid); self.publish.assert_not_called()
        self.now += timedelta(seconds=10)
        async def publish(context):
            self.now += timedelta(seconds=7)
            return {'success':True, 'item_id':'test-only-item'}
        self.publish.side_effect = publish
        await self.runner.run_one(bid)
        self.assertEqual(self.publish.await_count,1)
        first = await self.detail(bid)
        self.assertEqual(first['status'],'waiting')
        self.assertEqual(first['next_run_at'],'2099-01-01T12:01:17+08:00')
        # 新实例模拟进程重启，从数据库恢复队列，不重发首项。
        self.runner = self.new_runner()
        self.now += timedelta(seconds=59)
        await self.runner.run_one(bid); self.assertEqual(self.publish.await_count,1)
        self.now += timedelta(seconds=1)
        await self.runner.run_one(bid)
        self.assertEqual(self.publish.await_count,2)
        self.assertTrue((await self.detail(bid))['finished'])

    async def test_cancel_before_due_never_calls_platform(self):
        bid = await self.create()
        result = await self.cancel(bid)
        self.assertEqual(result['cancelled'],2)
        await self.runner.run_one(bid)
        self.publish.assert_not_called()
        self.assertEqual((await self.detail(bid))['status'],'cancelled')

    async def test_cancel_during_preparation_never_calls_publish(self):
        bid = await self.create()
        async def prepare(*args):
            await self.cancel(bid)
            return {'test_only':True}
        self.prepare.side_effect = prepare
        await self.runner.run_one(bid)
        self.publish.assert_not_called()
        self.assertEqual((await self.detail(bid))['cancelled'],2)

    async def test_cancel_during_request_keeps_success_and_cancels_remaining(self):
        bid = await self.create()
        async def publish(context):
            response = await self.cancel(bid)
            self.assertEqual(response['status'],'cancelling')
            return {'success':True,'item_id':'test-only-item'}
        self.publish.side_effect = publish
        await self.runner.run_one(bid)
        result = await self.detail(bid)
        self.assertEqual((result['status'],result['success'],result['cancelled']),('cancelled',1,1))
        self.now += timedelta(days=1)
        await self.runner.run_one(bid)
        self.publish.assert_awaited_once()

    async def test_two_runners_claim_only_once(self):
        bid = await self.create(count=1)
        started, release = asyncio.Event(), asyncio.Event()
        async def publish(context):
            started.set(); await release.wait()
            return {'success':True,'item_id':'test-only-item'}
        self.publish.side_effect = publish
        first = asyncio.create_task(self.runner.run_one(bid))
        await asyncio.wait_for(started.wait(),3)
        await self.new_runner().run_one(bid)
        release.set(); await first
        self.publish.assert_awaited_once()

    async def test_expired_request_pauses_unknown_without_republish(self):
        bid = await self.create()
        claim = await self.runner.claim(bid)
        self.assertTrue(await self.runner.begin_request(claim))
        self.now += timedelta(seconds=LEASE_SECONDS+1)
        await self.new_runner().run_one(bid)
        self.assertEqual((await self.detail(bid))['unknown'],1)
        self.assertEqual((await self.detail(bid))['status'],'attention')
        await self.runner.run_one(bid)
        self.publish.assert_not_called()

    async def test_network_unknown_stops_remaining_but_explicit_failure_advances(self):
        bid = await self.create()
        self.publish.side_effect = TimeoutError('test-only')
        await self.runner.run_one(bid)
        result = await self.detail(bid)
        self.assertEqual((result['status'],result['unknown'],result['pending']),('attention',1,1))
        await self.runner.run_one(bid); self.publish.assert_awaited_once()
        other = await self.create()
        self.publish.side_effect = None
        self.publish.return_value = {'success':False,'message':'平台明确拒绝'}
        await self.runner.run_one(other)
        self.assertEqual((await self.detail(other))['status'],'waiting')
        self.now += timedelta(seconds=60)
        await self.runner.run_one(other)
        self.assertEqual((await self.detail(other))['failed'],2)
        self.assertTrue((await self.detail(other))['finished'])

    async def test_recovery_before_request_revokes_old_token_and_waits_interval(self):
        bid = await self.create(count=1)
        old = await self.runner.claim(bid)
        self.now += timedelta(seconds=LEASE_SECONDS+1)
        await self.new_runner().run_one(bid)
        self.assertEqual((await self.detail(bid))['status'],'waiting')
        self.assertFalse(await self.runner.begin_request(old))
        self.publish.assert_not_called()
        self.now += timedelta(seconds=60)
        await self.new_runner().run_one(bid)
        self.publish.assert_awaited_once()

    async def test_committed_result_survives_crash_without_republishing_finished_item(self):
        bid = await self.create()
        claim = await self.runner.claim(bid)
        await self.runner.begin_request(claim)
        await self.runner.record_result(claim,'success',{'item_id':'known-test-only'})
        self.now += timedelta(seconds=LEASE_SECONDS+1)
        await self.new_runner().run_one(bid)
        self.assertEqual((await self.detail(bid))['success'],1)
        self.assertEqual((await self.detail(bid))['status'],'waiting')
        self.now += timedelta(seconds=60)
        await self.new_runner().run_one(bid)
        self.publish.assert_awaited_once()
        self.assertEqual((await self.detail(bid))['success'],2)

    async def test_owner_isolation_and_idempotent_registration(self):
        bid = await self.create()
        async with async_session_maker() as s:
            self.assertIsNone(await PublishBatchJobs(s).detail(bid, OWNER-1))
            with self.assertRaises(ValueError): await PublishBatchJobs(s).cancel(bid, OWNER-1)
        async with async_session_maker() as s:
            result = await BatchPublishService(s).existing(OWNER,bid,['test-only-account'],[900000,900001])
            self.assertTrue(result['reused'])
        self.assertEqual((await self.detail(bid))['total'],2)

    async def test_cancel_uses_current_read_despite_earlier_pending_snapshot(self):
        bid = await self.create()
        async with async_session_maker() as old_session:
            await old_session.execute(select(PublishLog).where(PublishLog.batch_id == bid))
            claim = await self.runner.claim(bid)
            self.assertTrue(await self.runner.begin_request(claim))
            await PublishBatchJobs(old_session).cancel(bid, OWNER)
        result = await self.detail(bid)
        self.assertEqual(result['publishing'],1)
        self.assertEqual(result['cancelled'],1)
        await self.runner.record_result(claim,'success',{'item_id':'test-only-item'})
        await self.runner.finish(claim,'success',{})
        self.assertEqual((await self.detail(bid))['status'],'cancelled')

    async def test_store_filter_includes_handmade_when_requested(self):
        async with async_session_maker() as s:
            m = await ProductMaterialService(s).create(OWNER,{'title':'test-only-manual','description':'test-only',
                'price':1,'quantity':1,'images':['https://example.com/test.png']})
            self.material_ids.append(m.id)
            strict = await ProductMaterialService(s).list_materials(OWNER,source_account_id='no-such-test-shop')
            combined = await ProductMaterialService(s).list_materials(OWNER,source_account_id='no-such-test-shop',include_unlinked=True)
            self.assertEqual(strict['total'],0)
            self.assertEqual(combined['total'],1)
            self.assertEqual(combined['list'][0]['id'],m.id)


if __name__ == '__main__':
    unittest.main()
