"""批量检查与提交保护；发布器和后台任务只模拟，不调用平台。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

sys.path.insert(0, '/app/backend-web')
from fastapi import BackgroundTasks
from app.services.batch_publish_service import BatchPublishService, material_publish_errors
from app.api.routes import product_publish as routes
from app.services.publish_execution_service import PublishLogService
from app.services.publish_execution_service import PublishExecutorService


def material(**changes):
    data = dict(id=1, title='测试素材', description='真实描述', images=['https://example.com/item.jpg'],
                price=1, quantity=1, platform_category_id='1', platform_channel_category_id='2',
                specifications=[], sku_rows=[], address='测试所在地')
    return {**data, **changes}


class ValidationTests(unittest.TestCase):
    def test_valid_and_unknown_condition_does_not_change_material(self):
        data = material(condition='')
        before = dict(data)
        self.assertEqual(material_publish_errors(data), [])
        self.assertEqual(data, before)

    def test_limits_and_utf16(self):
        self.assertEqual(material_publish_errors(material(title='测'*30, description='测'*1500)), [])
        for changes in [dict(title='😀'*16), dict(title='换\n行'), dict(description='😀'*751),
                        dict(description=''), dict(title=''), dict(images=[]), dict(price=float('nan')),
                        dict(quantity=0), dict(quantity=None), dict(quantity=1.1), dict(platform_channel_category_id='')]:
            with self.subTest(changes=changes):
                self.assertTrue(material_publish_errors(material(**changes)))

    def test_specs_need_complete_unique_combinations(self):
        specs = [dict(name='颜色', values=[dict(name='红'), dict(name='蓝')])]
        rows = [dict(specs={'颜色':'红'}, price=1, stock=0), dict(specs={'颜色':'蓝'}, price=2, stock=3)]
        self.assertEqual(material_publish_errors(material(specifications=specs, sku_rows=rows)), [])
        for invalid in [rows[:1], rows + rows[:1], [{**r, 'stock':0} for r in rows]]:
            self.assertTrue(material_publish_errors(material(specifications=specs, sku_rows=invalid)))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_foreign_resource_rejects_without_write(self):
        session = AsyncMock()
        empty = MagicMock(); empty.scalars.return_value.all.return_value = []
        session.execute.return_value = empty
        with self.assertRaises(ValueError):
            await BatchPublishService(session).inspect(7, ['account'], [1])
        session.commit.assert_not_called()
        for call in session.execute.call_args_list:
            self.assertIn(7, call.args[0].compile().params.values())

    async def test_history_and_fingerprint_are_readonly(self):
        session = AsyncMock()
        account = SimpleNamespace(account_id='a', cookie='test-only')
        m = SimpleNamespace(id=1, quantity=1)
        history = [SimpleNamespace(account_id='a', material_id=1, status='success')]
        def result(rows):
            r = MagicMock(); r.scalars.return_value.all.return_value = rows; return r
        session.execute.side_effect = [result([account]), result([m]), result(history)] * 2
        with patch('app.services.batch_publish_service._material_to_dict', return_value=material()):
            report, _ = await BatchPublishService(session).inspect(7, ['a','a'], [1,1])
            same, _ = await BatchPublishService(session).inspect(7, ['a'], [1])
        self.assertEqual(report['total'], 1)
        self.assertEqual(report['duplicate_count'], 1)
        self.assertEqual(report['fingerprint'], same['fingerprint'])
        self.assertTrue(report['ready'])
        session.commit.assert_not_called()

    async def test_unresolved_history_blocks_and_material_change_invalidates_fingerprint(self):
        session = AsyncMock()
        def result(rows):
            r = MagicMock(); r.scalars.return_value.all.return_value = rows; return r
        history = [SimpleNamespace(account_id='a', material_id=1, status='unknown')]
        session.execute.side_effect = [result([SimpleNamespace(account_id='a', cookie='test-only')]),
            result([SimpleNamespace(id=1, quantity=1)]), result(history)] * 2
        with patch('app.services.batch_publish_service._material_to_dict', side_effect=[material(), material(price=2)]):
            report, _ = await BatchPublishService(session).inspect(7, ['a'], [1])
            changed, _ = await BatchPublishService(session).inspect(7, ['a'], [1])
        self.assertFalse(report['ready'])
        self.assertTrue(report['items'][0]['uncertain'])
        self.assertNotEqual(report['fingerprint'], changed['fingerprint'])

    async def test_existing_request_must_match_owner_and_all_pairs(self):
        session = AsyncMock()
        r = MagicMock(); session.execute.return_value = r
        r.scalars.return_value.all.return_value = [SimpleNamespace(user_id=7, account_id='a', material_id=1)]
        svc = BatchPublishService(session)
        self.assertTrue((await svc.existing(7, 'request', ['a'], [1]))['reused'])
        for owner, materials in [(8, [1]), (7, [2])]:
            with self.assertRaises(ValueError):
                await svc.existing(owner, 'request', ['a'], materials)

    async def test_source_shop_match_warns_without_assuming_item_is_on_sale(self):
        session = AsyncMock()
        def result(rows):
            r = MagicMock(); r.scalars.return_value.all.return_value = rows; return r
        session.execute.side_effect = [result([SimpleNamespace(id=2, account_id='a', cookie='test-only')]),
            result([SimpleNamespace(id=1, quantity=1)]), result([])]
        with patch('app.services.batch_publish_service._material_to_dict', return_value=material(catalog_account_pk=2, catalog_item_id='source')):
            report, _ = await BatchPublishService(session).inspect(7, ['a'], [1], lock=True)
        self.assertTrue(report['ready'])
        self.assertEqual(report['duplicate_count'], 1)
        self.assertEqual(report['items'][0]['source_item_id'], 'source')
        self.assertTrue(all(call.args[0]._for_update_arg is not None for call in session.execute.call_args_list))

    async def test_register_commits_whole_batch_with_unique_ids_once(self):
        session = AsyncMock(); session.add = MagicMock()
        await BatchPublishService(session).register(7, 'request', ['a','b'], [material(), material(id=2)])
        self.assertEqual(session.add.call_count, 4)
        logs = [call.args[0] for call in session.add.call_args_list]
        self.assertEqual(len({log.publish_request_id for log in logs}), 4)
        self.assertTrue(all(log.status == 'pending' for log in logs))
        session.commit.assert_awaited_once()

    async def test_log_claim_reuses_pending_but_rejects_started_row(self):
        session = AsyncMock()
        row = SimpleNamespace(id=12, status='pending')
        result = MagicMock(); result.scalars.return_value.first.return_value = row
        session.execute.return_value = result
        log = await PublishLogService(session).create_log(7, 'a', '素材', material_id=1, batch_id='b', status='publishing')
        self.assertEqual(log.id, 12)
        with self.assertRaises(ValueError):
            await PublishLogService(session).create_log(7, 'a', '素材', material_id=1, batch_id='b', status='publishing')


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patcher = patch('common.services.publish_batch_jobs.PublishBatchJobs.detail', new=AsyncMock(return_value=None))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def invoke(self, *, existing=None, ready=True, fingerprint='a'*64, duplicates=0, allow=False, schedule=None):
        service = SimpleNamespace(existing=AsyncMock(return_value=existing),
            inspect=AsyncMock(return_value=({'ready':ready, 'fingerprint':fingerprint, 'duplicate_count':duplicates}, [material()])),
            register=AsyncMock())
        request = routes.CheckedBatchPublishRequest(account_ids=['a','a'], material_ids=[1,1],
            request_id=uuid4(), fingerprint='a'*64, allow_duplicates=allow, **(schedule or {}))
        tasks = BackgroundTasks()
        with patch('app.services.batch_publish_service.BatchPublishService', return_value=service), \
             patch.object(routes.PublishBatchStatusService, 'init_batch', new=AsyncMock()):
            response = await routes.publish_batch(request, tasks, SimpleNamespace(id=7), AsyncMock())
        return response, service, tasks

    async def test_good_submission_queues_exactly_once(self):
        response, service, tasks = await self.invoke()
        self.assertTrue(response.success)
        service.register.assert_awaited_once()
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(tasks.tasks[0].kwargs['account_ids'], ['a'])

    async def test_retry_same_request_does_not_queue_again(self):
        response, service, tasks = await self.invoke(existing={'batch_id':'same', 'total':1})
        self.assertTrue(response.success)
        service.inspect.assert_not_called(); service.register.assert_not_called()
        self.assertEqual(tasks.tasks, [])

    async def test_stale_invalid_and_unconfirmed_duplicate_never_queue(self):
        for changes in [dict(ready=False), dict(fingerprint='b'*64), dict(duplicates=1)]:
            response, service, tasks = await self.invoke(**changes)
            self.assertFalse(response.success)
            service.register.assert_not_called(); self.assertEqual(tasks.tasks, [])

    async def test_duplicate_can_be_explicitly_confirmed(self):
        response, _, tasks = await self.invoke(duplicates=1, allow=True)
        self.assertTrue(response.success); self.assertEqual(len(tasks.tasks), 1)

    async def test_scheduled_submission_is_persisted_without_immediate_background_task(self):
        response, service, tasks = await self.invoke(schedule={'mode':'scheduled',
            'start_at':'2099-01-01T12:00:00+08:00','interval_seconds':300})
        self.assertTrue(response.success)
        self.assertEqual(tasks.tasks, [])
        self.assertEqual(service.register.call_args.kwargs['mode'],'scheduled')
        self.assertEqual(service.register.call_args.kwargs['interval_seconds'],300)

    async def test_past_schedule_never_registers_or_runs_immediately(self):
        response, service, tasks = await self.invoke(schedule={'mode':'scheduled',
            'start_at':'2000-01-01T12:00:00+08:00','interval_seconds':30})
        self.assertFalse(response.success)
        self.assertEqual(tasks.tasks, [])
        service.register.assert_not_called()

    async def test_immediate_with_interval_uses_same_durable_queue(self):
        response, service, tasks = await self.invoke(schedule={'mode':'immediate','interval_seconds':60})
        self.assertTrue(response.success)
        self.assertEqual(tasks.tasks, [])
        self.assertEqual(service.register.call_args.kwargs['mode'],'immediate')

    async def test_status_never_reveals_another_users_cache(self):
        session = AsyncMock()
        result = MagicMock(); result.scalars.return_value.all.return_value = []
        session.execute.return_value = result
        with patch.object(routes.PublishBatchStatusService, 'get_batch_snapshot', new=AsyncMock()) as cache:
            response = await routes.get_batch_status('other', SimpleNamespace(id=7), session)
            self.assertFalse(response.success); cache.assert_not_called()

    async def status_with(self, status, snapshot):
        session = AsyncMock()
        result = MagicMock(); result.scalars.return_value.all.return_value = [object()]
        counts = MagicMock(); counts.all.return_value = [SimpleNamespace(status=status, cnt=1)]
        groups = MagicMock(); groups.all.return_value = [SimpleNamespace(account_id='a', status=status, cnt=1)]
        session.execute.side_effect = [result, counts, groups]
        with patch('app.services.publish_execution_service._log_to_dict', return_value={'id':1, 'status':status}), \
             patch.object(routes.PublishBatchStatusService, 'get_batch_snapshot', new=AsyncMock(return_value=snapshot)):
            return await routes.get_batch_status('batch', SimpleNamespace(id=7), session)

    async def test_lost_cache_preserves_logs_and_never_claims_finished(self):
        response = await self.status_with('success', None)
        self.assertTrue(response.success)
        self.assertTrue(response.data['tracking_lost'])
        self.assertFalse(response.data['finished'])
        self.assertEqual(response.data['items'], [{'id':1, 'status':'success'}])

    async def test_unknown_result_is_not_reported_as_pending_or_finished(self):
        response = await self.status_with('unknown', {'material_count':1, 'account_order':['a'],
            'accounts':{'a':{'sync_status':'skipped'}}})
        self.assertFalse(response.data['finished'])
        self.assertEqual(response.data['pending'], 0)
        self.assertTrue(response.data['tracking_lost'])

    async def test_executor_preserves_unknown_platform_results(self):
        for outcome in [dict(success=False, _request_status_unknown=True), dict(success=True), RuntimeError('test timeout')]:
            svc = PublishExecutorService(AsyncMock())
            svc._get_account_map = AsyncMock(return_value={'a': SimpleNamespace(account_id='a', cookie='test-only')})
            log_svc = SimpleNamespace(create_log=AsyncMock(return_value=SimpleNamespace(id=1)), update_log=AsyncMock())
            address_svc = SimpleNamespace(build_queue_state=AsyncMock(return_value=object()),
                resolve_publish_address=AsyncMock(return_value=SimpleNamespace(
                    apply_to_item_data=lambda data: data, to_log_fields=lambda: {})))
            publisher = AsyncMock(side_effect=outcome) if isinstance(outcome, Exception) else AsyncMock(return_value=outcome)
            with patch('app.services.publish_execution_service.PublishLogService', return_value=log_svc), \
                 patch('app.services.publish_execution_service.PublishAddressService', return_value=address_svc), \
                 patch('app.services.publish_execution_service.detect_publish_account_capability', new=AsyncMock(return_value={'success':True, 'is_fish_shop':True})), \
                 patch('app.services.publish_execution_service.publish_single_item', new=publisher), \
                 patch.object(routes.PublishBatchStatusService, 'mark_account_sync_skipped', new=AsyncMock()):
                await svc.batch_publish(7, ['a'], [material()], 'test-only')
            self.assertEqual(log_svc.update_log.call_args.kwargs['status'], 'unknown')
            publisher.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
