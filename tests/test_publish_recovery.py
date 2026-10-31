"""发布前失败与结果核查回归；所有远端发布均使用替身。"""
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '/app/backend-web')
from common.services.batch_publish_item import publish_prepared_batch_item


class PublishBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def context(self, fish=True):
        return dict(is_fish_shop=fish, material={}, cookie='test-only',
                    account_id='test-account', user_id=9, static_root=None)

    async def test_preparation_exception_is_failed_without_unknown_result(self):
        for fish, name in [(True, 'publish_single_item'), (False, 'publish_personal_single_item')]:
            with self.subTest(fish=fish):
                with patch('common.services.batch_publish_item.' + name, AsyncMock(side_effect=TimeoutError('secret-url'))):
                    result = await publish_prepared_batch_item(self.context(fish))
                self.assertFalse(result['success'])
                self.assertFalse(result.get('unknown', False))
                self.assertIn('未调用商品发布接口', result['message'])
                self.assertNotIn('secret-url', result['message'])

    async def test_exception_after_submit_boundary_remains_unknown(self):
        async def publish(**kwargs):
            await kwargs['before_submit']()
            raise TimeoutError('private-context')
        with patch('common.services.batch_publish_item.publish_single_item', publish):
            result = await publish_prepared_batch_item(self.context())
        self.assertTrue(result['unknown'])
        self.assertNotIn('private-context', result['message'])

    async def test_success_and_explicit_rejection_are_preserved(self):
        for response in [dict(success=True, item_id='123456'), dict(success=False, message='平台明确拒绝')]:
            with patch('common.services.batch_publish_item.publish_single_item', AsyncMock(return_value=response)):
                self.assertEqual(await publish_prepared_batch_item(self.context()), response)

    async def test_real_publishers_mark_boundary_only_after_preparation(self):
        from common.services.xianyu_publish_service import (
            get_xianyu_direct_publisher_class, get_xianyu_personal_publisher_class,
        )
        for factory, prepare_name in [(get_xianyu_direct_publisher_class, 'build_item_payload'),
                                      (get_xianyu_personal_publisher_class, '_resolve_item_address')]:
            cls = factory(); module = sys.modules[cls.__module__]
            boundary = AsyncMock()
            with patch.object(module, prepare_name, AsyncMock(side_effect=TimeoutError())), \
                 patch.object(module, 'mtop_call', AsyncMock()) as remote:
                with self.assertRaises(TimeoutError):
                    await cls().publish_item(item_data={'title':'test', 'description':'test', 'images':['test']},
                        cookie='test-only', account_id='test', owner_id=9, before_submit=boundary)
                boundary.assert_not_called()
                remote.assert_not_called()


class PublishTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_uncertain_publication_request_is_never_resent(self):
        from common.services.xianyu_mtop import mtop_call
        http = MagicMock()
        request = MagicMock(); request.__aenter__ = AsyncMock(side_effect=TimeoutError('test-only'))
        http.post.return_value = request
        client = MagicMock(); client.__aenter__ = AsyncMock(return_value=http)
        with patch('common.services.xianyu_mtop.aiohttp.ClientSession', return_value=client), \
             patch('common.services.xianyu_mtop.asyncio.sleep', AsyncMock()):
            result = await mtop_call('test', '_m_h5_tk=test_999;', 'mtop.idle.pc.backend.idleitem.publish',
                                    '1.0', {}, retry_on_transport_error=False)
        self.assertTrue(result['_request_status_unknown'])
        self.assertEqual(http.post.call_count, 1)


class ReconciliationTests(unittest.IsolatedAsyncioTestCase):
    def session(self, *, status='unknown', batch=None, source=None, catalog=True):
        self.log = NS(id=5, user_id=9, account_id='account', status=status,
                      batch_id='batch' if batch else None, source_event_id=source,
                      error_message='原始异常', item_id=None, item_url=None)
        self.db = AsyncMock()
        values = [self.log]
        if batch:
            values.append(batch)
        values.append(self.log)
        values.append(NS(item_id='123456') if catalog else None)
        results = []
        for value in values:
            result = MagicMock(); result.scalar_one_or_none.return_value = value
            results.append(result)
        self.db.execute.side_effect = results
        return self.db

    async def test_not_published_unlocks_only_target_and_keeps_original_error(self):
        from common.services.publish_log_reconciliation import reconcile_publish_log
        db = self.session(batch=NS(claim_token=None, status='cancelled'))
        result = await reconcile_publish_log(db, 5, 9, actor_id=9, resolution='not_published', confirmed=True)
        self.assertEqual(result.status, 'failed')
        self.assertIn('原始异常', result.error_message)
        db.commit.assert_awaited_once()
        for call in db.execute.call_args_list[:3]:
            self.assertIn(9, call.args[0].compile().params.values())

    async def test_confirmation_and_unknown_state_required(self):
        from common.services.publish_log_reconciliation import reconcile_publish_log
        for status, confirmed in [('unknown', False), ('success', True), ('publishing', True), ('failed', True)]:
            with self.subTest(status=status):
                db = self.session(status=status)
                with self.assertRaises(ValueError):
                    await reconcile_publish_log(db, 5, 9, actor_id=9, resolution='not_published', confirmed=confirmed)
                db.commit.assert_not_called()

    async def test_active_job_and_auto_relist_cannot_be_overridden(self):
        from common.services.publish_log_reconciliation import reconcile_publish_log
        for batch, source in [(NS(claim_token='active', status='running'), None), (None, 8)]:
            db = self.session(batch=batch, source=source)
            with self.assertRaises(ValueError):
                await reconcile_publish_log(db, 5, 9, actor_id=9, resolution='not_published', confirmed=True)
            db.commit.assert_not_called()

    async def test_success_requires_item_in_same_users_shop(self):
        from common.services.publish_log_reconciliation import reconcile_publish_log
        for catalog in [False, True]:
            db = self.session(catalog=catalog)
            if not catalog:
                with self.assertRaises(ValueError):
                    await reconcile_publish_log(db, 5, 9, actor_id=9, resolution='published', confirmed=True, item_id='123456')
                db.commit.assert_not_called()
            else:
                result = await reconcile_publish_log(db, 5, 9, actor_id=9, resolution='published', confirmed=True, item_id='123456')
                self.assertEqual((result.status, result.item_id), ('success', '123456'))
                self.assertEqual(result.item_url, 'https://www.goofish.com/item?id=123456')
            params = db.execute.call_args.args[0].compile().params.values()
            self.assertIn(9, params)
            self.assertIn('account', params)

    async def test_other_users_record_is_not_returned(self):
        from common.services.publish_log_reconciliation import reconcile_publish_log
        db = AsyncMock(); result = MagicMock(); result.scalar_one_or_none.return_value = None
        db.execute.return_value = result
        with self.assertRaises(ValueError):
            await reconcile_publish_log(db, 5, 8, actor_id=8, resolution='not_published', confirmed=True)
        self.assertIn(8, db.execute.call_args.args[0].compile().params.values())
        db.commit.assert_not_called()


class ReconciliationRouteTests(unittest.TestCase):
    def test_route_scopes_user_and_rejects_unconfirmed_or_invalid_input(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes import product_publish as routes
        from common.models.user import UserRole
        db = AsyncMock()
        user = NS(id=9, role=UserRole.MEMBER)
        app = FastAPI(); app.include_router(routes.router)
        app.dependency_overrides[routes.get_current_active_user] = lambda: user
        app.dependency_overrides[routes.get_db_session] = lambda: db
        with TestClient(app) as client, \
             patch('common.services.publish_log_reconciliation.reconcile_publish_log', AsyncMock(side_effect=ValueError('仅可核查结果未知的发布记录'))) as reconcile:
            for body in [{'resolution':'not_published'}, {'resolution':'not_published','confirmed':False},
                         {'resolution':'published','confirmed':True,'item_id':'unsafe'}]:
                self.assertEqual(client.post('/product-publish/logs/5/reconcile',json=body).status_code,422)
            reconcile.assert_not_called()
            response = client.post('/product-publish/logs/5/reconcile',json={'resolution':'not_published','confirmed':True})
            self.assertFalse(response.json()['success'])
            self.assertEqual(reconcile.call_args.args[1:3], (5,9))
            self.assertEqual(reconcile.call_args.kwargs['actor_id'], 9)
            db.rollback.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
