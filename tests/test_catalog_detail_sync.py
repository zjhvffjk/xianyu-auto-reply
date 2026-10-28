import asyncio
import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '/app/backend-web')
from app.services.catalog_detail_cache import cache_catalog_form, has_complete_catalog_form
from app.services.catalog_detail_sync import CatalogDetailSyncService
from common.models.xy_account import XYAccount


def complete_form():
    return dict(title='原始标题', description='完整原文\n不润色', images=['a', 'b'],
                shipping_method='free', price='1.00', quantity=0, videos=[])


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    async def eval(self, script, count, *args):
        keys, values = args[:count], args[count:]
        if self.values.get(keys[0]) != values[0]:
            return 0
        if 'SET' in script:
            self.values[keys[1]] = values[1]
        elif 'DEL' in script:
            self.values.pop(keys[0], None)
        return 1


class CacheTests(unittest.TestCase):
    def test_cache_preserves_settings_and_zero_stock_without_sharing_form(self):
        item = SimpleNamespace(metadata_json={'custom': {'keep': True}, 'detail': json.dumps({'quantity': 9, 'item_status': -2}),
                                              'seller_detail': {'source': 'seller', 'quantity': 9}})
        form = complete_form()
        cache_catalog_form(item, form)
        self.assertEqual(item.metadata_json['custom'], {'keep': True})
        self.assertEqual(item.metadata_json['seller_detail']['quantity'], 0)
        self.assertEqual(json.loads(item.metadata_json['detail']), {'quantity': 0, 'item_status': -2})
        self.assertEqual(item.metadata_json['listing_price'], '1.00')
        form['images'].append('changed')
        self.assertEqual(item.metadata_json['material_form']['images'], ['a', 'b'])
        self.assertTrue(has_complete_catalog_form(item))

    def test_list_summary_is_not_complete_and_bad_snapshot_is_retried(self):
        for metadata in [{}, {'description': '摘要', 'images': ['thumbnail']}, {'material_form': {}},
                         {'material_form': {**complete_form(), 'images': []}},
                         {'material_form': {**complete_form(), 'quantity': True}}]:
            self.assertFalse(has_complete_catalog_form(SimpleNamespace(metadata_json=metadata)))

    def test_zero_platform_price_retains_snapshot_but_material_import_rejects_price(self):
        from app.services.xianyu_item_edit_mapper import _cent_to_yuan
        from app.services.catalog_material_service import material_data_from_catalog
        self.assertEqual(_cent_to_yuan('0'), 0)
        for invalid in [None, '', 'invalid', '-1']:
            self.assertIsNone(_cent_to_yuan(invalid))
        form = {**complete_form(), 'price': _cent_to_yuan('0')}
        item = SimpleNamespace(metadata_json={'material_form': form})
        self.assertTrue(has_complete_catalog_form(item))
        with self.assertRaisesRegex(ValueError, '有效售价'):
            material_data_from_catalog(item)


class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = MemoryRedis()
        self.service = CatalogDetailSyncService(self.redis)
        self.account = SimpleNamespace(id=3, owner_id=7, account_id='shop')

    async def start(self):
        with patch.object(self.service, '_spawn') as spawn:
            job = await self.service.start(self.account)
        self.assertTrue(spawn.called)
        return job

    async def test_duplicate_start_reuses_account_job(self):
        first = await self.start()
        with patch.object(self.service, '_spawn') as spawn:
            second = await self.service.start(self.account)
        self.assertEqual(first['job_id'], second['job_id'])
        spawn.assert_not_called()

    async def test_login_fetches_catalog_before_filling_details(self):
        with patch.object(self.service, '_spawn'):
            job = await self.service.start(self.account, fetch_catalog=True)
        events = []
        async def fetch(*args):
            events.append('catalog')
            return {'success': True}
        async def item_ids(*args):
            events.append('details')
            return ['one']
        self.service._fetch_catalog = AsyncMock(side_effect=fetch)
        self.service._item_ids = AsyncMock(side_effect=item_ids)
        self.service._fill_one = AsyncMock(return_value={'status': 'success'})
        await self.service.run(3, 7, job['job_id'])
        self.assertEqual(events, ['catalog', 'details'])
        self.assertEqual((await self.service.get(3, job['job_id']))['state'], 'completed')

    async def test_new_login_during_active_job_also_refreshes_catalog(self):
        job = await self.start()
        self.service._item_ids = AsyncMock(side_effect=[['first'], ['new', 'first']])
        self.service._fetch_catalog = AsyncMock(return_value={'success': True})
        async def fill(account_pk, owner_id, item_id):
            if item_id == 'first':
                await self.service.start(self.account, fetch_catalog=True)
            return {'status': 'success'}
        self.service._fill_one = AsyncMock(side_effect=fill)
        with patch('app.services.catalog_detail_sync.THROTTLE_SECONDS', 0):
            await self.service.run(3, 7, job['job_id'])
        self.service._fetch_catalog.assert_awaited_once_with(3, 7)
        self.assertEqual((await self.service.get(3, job['job_id']))['checked_item_ids'], ['first', 'new'])

    async def test_new_login_survives_old_cookie_failure_and_checks_all_items(self):
        job = await self.start()
        self.service._item_ids = AsyncMock(return_value=['first', 'second'])
        self.service._fetch_catalog = AsyncMock(return_value={'success': True})
        calls = []
        async def fill(account_pk, owner_id, item_id):
            calls.append(item_id)
            if len(calls) == 1:
                await self.service.start(self.account, fetch_catalog=True)
                return {'status': 'failed', 'message': '旧账号登录失效', 'stop': True}
            return {'status': 'success'}
        self.service._fill_one = AsyncMock(side_effect=fill)
        with patch('app.services.catalog_detail_sync.THROTTLE_SECONDS', 0):
            await self.service.run(3, 7, job['job_id'])
        result = await self.service.get(3, job['job_id'])
        self.assertEqual(result['state'], 'completed')
        self.assertEqual((result['total'], result['processed'], result['failed']), (2, 2, 0))
        self.assertEqual(calls, ['first', 'first', 'second'])

    async def test_new_items_fetched_during_run_are_not_missed(self):
        job = await self.start()
        self.service._item_ids = AsyncMock(side_effect=[['first'], ['new', 'first']])
        async def fill(account_pk, owner_id, item_id):
            if item_id == 'first':
                await self.service.start(self.account)
            return {'status': 'success'}
        self.service._fill_one = AsyncMock(side_effect=fill)
        with patch('app.services.catalog_detail_sync.THROTTLE_SECONDS', 0):
            await self.service.run(3, 7, job['job_id'])
        result = await self.service.get(3, job['job_id'])
        self.assertEqual((result['total'], result['processed']), (2, 2))
        self.assertEqual(result['checked_item_ids'], ['first', 'new'])
        self.assertEqual(self.service._fill_one.await_count, 2)

    async def test_selected_import_items_move_ahead_of_unrelated_history(self):
        job = await self.start()
        self.service._item_ids = AsyncMock(return_value=['first', 'history', 'selected'])
        async def fill(account_pk, owner_id, item_id):
            if item_id == 'first':
                await self.service.start(self.account, ['selected'])
            return {'status': 'success'}
        self.service._fill_one = AsyncMock(side_effect=fill)
        with patch('app.services.catalog_detail_sync.THROTTLE_SECONDS', 0):
            await self.service.run(3, 7, job['job_id'])
        result = await self.service.get(3, job['job_id'])
        self.assertEqual(result['checked_item_ids'], ['first', 'selected', 'history'])

    async def test_run_skips_cache_and_isolates_individual_failures(self):
        job = await self.start()
        self.service._item_ids = AsyncMock(return_value=['sold', 'ready', 'bad', 'on-sale'])
        self.service._fill_one = AsyncMock(side_effect=[
            {'status': 'success'}, {'status': 'cached'},
            {'status': 'failed', 'message': '平台已删除，无法读取'}, {'status': 'success'},
        ])
        with patch('app.services.catalog_detail_sync.THROTTLE_SECONDS', 0):
            await self.service.run(3, 7, job['job_id'])
        status = await self.service.get(3, job['job_id'])
        self.assertEqual(status['state'], 'completed')
        self.assertEqual((status['total'], status['processed'], status['succeeded'], status['cached'], status['failed']), (4, 4, 2, 1, 1))
        self.assertEqual(status['failures'][0]['item_id'], 'bad')
        self.assertNotIn(self.service.lease_key(3), self.redis.values)

    async def test_account_invalid_stops_further_platform_reads(self):
        job = await self.start()
        self.service._item_ids = AsyncMock(return_value=['one', 'two'])
        self.service._fill_one = AsyncMock(return_value={'status': 'failed', 'message': '账号登录失效', 'stop': True})
        await self.service.run(3, 7, job['job_id'])
        status = await self.service.get(3, job['job_id'])
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(status['processed'], 1)
        self.assertEqual(self.service._fill_one.await_count, 1)

    async def test_lost_lease_reports_interrupted_and_never_runs_stale_job(self):
        job = await self.start()
        self.redis.values.pop(self.service.lease_key(3))
        status = await self.service.get(3, job['job_id'])
        self.assertEqual(status['state'], 'interrupted')
        self.service._item_ids = AsyncMock()
        await self.service.run(3, 7, job['job_id'])
        self.service._item_ids.assert_not_awaited()

    async def test_unauthorized_account_denied_before_job_or_platform_call(self):
        from app.api.routes.catalog_details import start_detail_sync
        accounts = SimpleNamespace(get_account_for_user=AsyncMock(return_value=None))
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as failure:
            await start_detail_sync('other', SimpleNamespace(id=7, role='USER'), accounts)
        self.assertEqual(failure.exception.status_code, 404)

    async def test_status_route_denies_invisible_account(self):
        from app.api.routes.catalog_details import get_detail_sync
        from fastapi import HTTPException
        accounts = SimpleNamespace(get_account_for_user=AsyncMock(return_value=None))
        with self.assertRaises(HTTPException) as failure:
            await get_detail_sync('other', None, SimpleNamespace(id=7, role='USER'), accounts)
        self.assertEqual(failure.exception.status_code, 404)


class DetailReadTests(unittest.IsolatedAsyncioTestCase):
    def session(self, objects):
        def result(value):
            r = MagicMock(); r.scalars.return_value.first.return_value = value
            return r
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[result(value) for value in objects])
        session.rollback = AsyncMock(); session.commit = AsyncMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=session)
        context.__aexit__ = AsyncMock(return_value=False)
        return session, context

    async def test_complete_snapshot_never_calls_platform(self):
        account = XYAccount(id=3, owner_id=7, status='active', account_id='shop', cookie='test-only')
        catalog = SimpleNamespace(metadata_json={'material_form': complete_form()})
        session, context = self.session([account, catalog])
        with patch('app.services.catalog_detail_sync.async_session_maker', return_value=context), \
             patch('app.services.catalog_detail_sync.fetch_seller_item_edit_detail', new_callable=AsyncMock) as fetch:
            result = await CatalogDetailSyncService(MemoryRedis())._fill_one(3, 7, 'sold')
        self.assertEqual(result['status'], 'cached')
        fetch.assert_not_awaited(); session.commit.assert_not_awaited()

    async def test_missing_snapshot_uses_read_only_detail_and_preserves_originals(self):
        account = XYAccount(id=3, owner_id=7, status='active', account_id='shop', cookie='test-only')
        catalog = SimpleNamespace(metadata_json={'custom': {'bound_card': 4}})
        session, context = self.session([account, catalog, catalog])
        form = complete_form()
        with patch('app.services.catalog_detail_sync.async_session_maker', return_value=context), \
             patch('app.services.catalog_detail_sync.fetch_seller_item_edit_detail', new=AsyncMock(return_value={'success': True, 'data': {'form': form}})) as fetch:
            result = await CatalogDetailSyncService(MemoryRedis())._fill_one(3, 7, 'sold')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(catalog.metadata_json['material_form'], form)
        self.assertEqual(catalog.metadata_json['custom'], {'bound_card': 4})
        session.rollback.assert_awaited_once(); session.commit.assert_awaited_once()
        self.assertEqual(fetch.call_args.kwargs['item_id'], 'sold')
        self.assertEqual(fetch.call_args.kwargs['owner_id'], 7)

    async def test_incomplete_platform_reply_is_not_saved_as_full_detail(self):
        account = XYAccount(id=3, owner_id=7, status='active', account_id='shop', cookie='test-only')
        catalog = SimpleNamespace(metadata_json={'custom': {'keep': True}})
        session, context = self.session([account, catalog])
        with patch('app.services.catalog_detail_sync.async_session_maker', return_value=context), \
             patch('app.services.catalog_detail_sync.fetch_seller_item_edit_detail', new=AsyncMock(return_value={'success': True, 'data': {'form': {'title': '摘要'}}})):
            result = await CatalogDetailSyncService(MemoryRedis())._fill_one(3, 7, 'sold')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(catalog.metadata_json, {'custom': {'keep': True}})
        session.commit.assert_not_awaited()

    async def test_fetch_api_enqueues_only_after_list_success(self):
        from app.api.routes import items
        from common.schemas.item import ItemFullFetchRequest
        account = SimpleNamespace(id=3, owner_id=7, account_id='shop')
        accounts = SimpleNamespace(get_account_for_user=AsyncMock(return_value=account))
        for success in [False, True]:
            service = SimpleNamespace(fetch_all_items_from_account=AsyncMock(return_value={'success': success}))
            with patch.object(items, 'enqueue_catalog_detail_sync', new=AsyncMock(return_value={'detail_sync': {'account_id': 'shop'}})) as enqueue:
                result = await items.fetch_all_items_from_account(ItemFullFetchRequest(cookie_id='shop'), SimpleNamespace(id=7, role='USER'), accounts, service)
            self.assertEqual(enqueue.await_count, int(success))
            if success:
                self.assertIn('detail_sync', result)


class AccountLoginHooksTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_login_result_survives_warmup_database_error(self):
        from app.api.routes import password_login
        response = MagicMock(status_code=200)
        response.json.return_value = {'status': 'success', 'account_id': 'shop'}
        client = MagicMock(); client.get = AsyncMock(return_value=response)
        context = MagicMock(); context.__aenter__ = AsyncMock(return_value=client); context.__aexit__ = AsyncMock(return_value=False)
        accounts = SimpleNamespace(get_account_for_user=AsyncMock(side_effect=RuntimeError('test database failure')))
        with patch.object(password_login.httpx, 'AsyncClient', return_value=context):
            result = await password_login.check_login_status('browser-test-session', SimpleNamespace(id=7), accounts)
        self.assertEqual(result, {'status': 'success', 'account_id': 'shop'})

    async def test_all_backend_login_save_paths_warm_catalog_after_commit(self):
        from app.services.account_service import AccountService
        for method in ['create', 'cookie', 'qr', 'password']:
            with self.subTest(method=method):
                account = XYAccount(id=3, owner_id=7, account_id='shop', status='active', cookie='test-only', metadata_json={})
                session = MagicMock(); session.commit = AsyncMock(); session.refresh = AsyncMock()
                service = AccountService(session)
                service.account_id_exists = AsyncMock(return_value=False)
                service.get_account_by_unb = AsyncMock(return_value=account)
                service.get_account_by_identifier = AsyncMock(return_value=account)
                service._warm_profile = AsyncMock()
                async def warmed(saved):
                    session.commit.assert_awaited()
                with patch.object(service, '_warm_catalog', new=AsyncMock(side_effect=warmed)) as warm, \
                     patch('app.services.account_service.AccountLimitService') as limits:
                    limits.return_value.ensure_can_add_account = AsyncMock()
                    if method == 'create':
                        await service.create_account(7, 'new-shop', 'test-only')
                    elif method == 'cookie':
                        await service.update_cookie(account, 'test-new')
                    elif method == 'qr':
                        await service.upsert_account_from_qr(7, 'test-new', 'test-unb')
                    else:
                        await service.upsert_account_from_password(owner_id=7, account_id='shop', account='test-user', password='test-only', cookies='test-new', unb='test-unb')
                warm.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
