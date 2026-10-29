"""平台凭据与多用户访问隔离；不调用外部快递接口。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI, HTTPException

sys.path.insert(0, '/app/backend-web')
from app.api.routes import waybills
from app.services.waybill_service import WaybillService


class PlatformRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(waybills.router)
        self.user = SimpleNamespace(id=7, role='USER')
        self.app.dependency_overrides[waybills.get_current_active_user] = lambda: self.user
        empty = MagicMock()
        empty.scalars.return_value.first.return_value = None
        self.db = MagicMock(execute=AsyncMock(return_value=empty), commit=AsyncMock(), rollback=AsyncMock())
        self.app.dependency_overrides[waybills.get_db_session] = lambda: self.db
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.http.aclose()

    async def test_non_admin_cannot_read_or_write_platform_keys(self):
        for method in ['get', 'put']:
            result = await self.http.request(method, '/waybills/platform/config',
                                             **({'json': {'app_key': 'test', 'app_secret': 'test-secret'}} if method == 'put' else {}))
            self.assertEqual(result.status_code, 403)
        self.db.commit.assert_not_awaited()

    async def test_admin_can_read_unconfigured_platform_without_secret(self):
        self.user.role = 'ADMIN'
        result = await self.http.get('/waybills/platform/config')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(result.json()['data']['configured'], False)
        self.assertNotIn('app_secret', result.json()['data'])

    async def test_owning_user_cannot_save_legacy_developer_credentials(self):
        account = SimpleNamespace(id=1, owner_id=7)
        with patch('app.api.routes.waybills.scoped_account', AsyncMock(return_value=account)):
            result = await self.http.put('/waybills/shop/settings', json={'app_key': 'test', 'app_secret': 'test-secret'})
        self.assertEqual(result.status_code, 403)
        self.db.commit.assert_not_awaited()

    async def test_existing_legacy_connection_is_not_merchant_authorization(self):
        from common.models.waybill import WaybillConnection
        account = SimpleNamespace(id=1, owner_id=7)
        config = WaybillConnection(account_pk=1, owner_id=7, app_key='private-app-key',
                                   credentials_ciphertext='ciphertext', login_user='private-login',
                                   mall_user_id='123', verified_at=None)
        service = WaybillService(self.db, account)
        service.connection = AsyncMock(return_value=config)
        result = await service.settings()
        self.assertFalse(result['legacy_allowed'])
        self.assertFalse(result['authorization_available'])
        self.assertFalse(result['embedded_print_available'])
        self.assertEqual(result['app_key'], '')
        self.assertEqual(result['mall_user_id'], '')
        self.assertFalse(result['configured'])

    async def test_user_remote_operations_stop_before_provider_even_with_legacy_connection(self):
        service = WaybillService(self.db, SimpleNamespace(id=1, owner_id=7, status='active'))
        self.db.execute.return_value.scalars.return_value.first.return_value = SimpleNamespace(
            account_pk=1, owner_id=7, app_key='private-app', credentials_ciphertext='private-cipher',
            login_user='private-login', mall_user_id='123', verified_at=True)
        self.app.dependency_overrides[waybills.service_for] = lambda: service
        with patch('app.services.waybill_service.KdzsClient') as client:
            for suffix, data in [('templates', None), ('workbench', None),
                                 ('sync', {'order_no': '1', 'recipient': dict(name='测试', phone='13800138000', province='浙江省', city='杭州市', county='西湖区', address='路1号')}),
                                 ('number', {'order_no': '1', 'template_id': '1'})]:
                result = await self.http.post(f'/waybills/shop/{suffix}', json=data)
                self.assertEqual(result.status_code, 409, suffix)
                self.assertIn('授权', result.json()['detail'])
            client.assert_not_called()

    async def test_merchant_status_exposes_only_public_platform_progress(self):
        self.db.execute.return_value.scalars.return_value.first.return_value = SimpleNamespace(
            app_key='private-platform-app', credentials_ciphertext='private-platform-cipher')
        with patch('app.api.routes.waybills.scoped_account', AsyncMock(return_value=SimpleNamespace(id=1, owner_id=7))):
            result = await self.http.get('/waybills/shop/settings')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['cache-control'], 'no-store')
        status = result.json()['data']
        self.assertTrue(status['platform_configured'])
        self.assertTrue(status['authorization_available'])
        self.assertFalse(status['configured'])
        self.assertIsNone(status['verified_at'])
        self.assertNotIn('private-platform', result.text)

    async def test_platform_rejects_blank_or_oversized_secrets(self):
        self.user.role = 'ADMIN'
        for secret in ['', '   ', 'x' * 501]:
            result = await self.http.put('/waybills/platform/config', json={'app_key': 'test', 'app_secret': secret})
            self.assertEqual(result.status_code, 422)
        self.db.commit.assert_not_awaited()


class PlatformDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession
        from common.db.session import async_engine
        from common.db.waybill_schema import WAYBILL_DDL
        from app.services.waybill_platform_service import WaybillPlatformService
        self.engine = async_engine
        self.conn = await self.engine.connect()
        await self.conn.execute(text(WAYBILL_DDL['xy_waybill_platform'].replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE')))
        await self.conn.commit()
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)
        self.service = WaybillPlatformService(self.db)
        self.secret_patch = patch('app.services.waybill_platform_service.get_settings', return_value=SimpleNamespace(jwt_secret_key='only-for-unit-test-32-char-secret'))
        self.secret_patch.start()

    async def asyncTearDown(self):
        from sqlalchemy import text
        self.secret_patch.stop()
        await self.db.rollback()
        await self.db.close()
        await self.conn.execute(text('DROP TEMPORARY TABLE IF EXISTS xy_waybill_platform'))
        await self.conn.commit()
        await self.conn.close()
        await self.engine.dispose()

    async def test_platform_secret_encrypted_and_never_returned(self):
        from sqlalchemy import select
        from common.models.waybill import WaybillPlatform
        result = await self.service.save(waybills.PlatformInput(app_key='platform', app_secret='unit-platform-secret'))
        self.assertTrue(result['configured'])
        self.assertTrue(result['authorization_available'])
        self.assertNotIn('unit-platform-secret', str(result))
        config = (await self.db.execute(select(WaybillPlatform))).scalars().one()
        self.assertNotIn('unit-platform-secret', config.credentials_ciphertext)
        self.assertEqual(self.service.secret(config), 'unit-platform-secret')

    async def test_keep_secret_and_require_new_secret_on_key_change(self):
        await self.service.save(waybills.PlatformInput(app_key='platform', app_secret='unit-platform-secret'))
        await self.service.save(waybills.PlatformInput(app_key='platform'))
        with self.assertRaises(HTTPException) as caught:
            await self.service.save(waybills.PlatformInput(app_key='other'))
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual((await self.service.settings())['app_key'], 'platform')
        await self.service.save(waybills.PlatformInput(app_key='other', app_secret='other-secret'))
        self.assertEqual((await self.service.settings())['app_key'], 'other')

    async def test_platform_ciphertext_cannot_be_decrypted_as_shop_secret(self):
        from sqlalchemy import select
        from common.models.waybill import WaybillPlatform
        await self.service.save(waybills.PlatformInput(app_key='platform', app_secret='unit-platform-secret'))
        config = (await self.db.execute(select(WaybillPlatform))).scalars().one()
        service = WaybillService(self.db, SimpleNamespace(id=1, owner_id=7))
        with patch('app.services.waybill_service.get_settings', return_value=SimpleNamespace(jwt_secret_key='only-for-unit-test-32-char-secret')):
            with self.assertRaises(HTTPException):
                service._secret(config)


if __name__ == '__main__':
    unittest.main()
