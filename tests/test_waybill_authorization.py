"""店铺授权与官方回调协议；真实MySQL临时表，服务商完全模拟。"""
import hashlib
import json
import sys
import time
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi import HTTPException
from fastapi import FastAPI
import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, '/app/backend-web')
from app.services.waybill_authorization_service import WaybillAuthorizationService, parse_callback, verify_callback
from app.api.routes.waybills import PlatformInput
from app.services.waybill_platform_service import WaybillPlatformService
from common.db.session import async_engine
from common.db.waybill_schema import WAYBILL_DDL
from common.models.waybill import WaybillAuthorization, WaybillPlatform
from common.models.xy_account import XYAccount
from common.utils.time_utils import get_beijing_now_naive


def callback(token, *, method='user.push', mall='123', secret='unit-platform-secret', **extra):
    payload = dict(token=token)
    if method == 'user.push':
        payload.update(mallUserId=int(mall), shopName='隔离测试店铺')
    params = dict(appKey='unit-platform', method=method, mallUserId=mall, v='1.0',
                  timestamp=str(int(time.time() * 1000)), appParam=json.dumps(payload, ensure_ascii=False), **extra)
    # 官方回调示例的固定格式，与被测实现分别构造。
    canonical = '&'.join(f'{key}={params[key]}' for key in sorted(params))
    params['sign'] = hashlib.md5((secret + canonical + secret).encode()).hexdigest().upper()
    return params


class CallbackProtocolTests(unittest.TestCase):
    def test_signed_callback_and_original_unicode_json(self):
        params = callback('synthetic-token')
        parsed = parse_callback(urlencode(params).encode())
        verify_callback(parsed, 'unit-platform-secret')
        self.assertEqual(json.loads(parsed['appParam'])['shopName'], '隔离测试店铺')

    def test_tamper_timestamp_duplicate_and_unsupported_method_are_rejected(self):
        valid = callback('synthetic-token')
        for params in [{**valid, 'mallUserId': '456'}, callback('synthetic-token', timestamp_override='0'),
                       callback('synthetic-token', method='trade.send')]:
            if 'timestamp_override' in params:
                params['timestamp'] = '0'
            with self.assertRaises(HTTPException):
                verify_callback(params, 'unit-platform-secret')
        with self.assertRaises(HTTPException):
            parse_callback((urlencode(valid) + '&appKey=other').encode())
        with self.assertRaises(HTTPException):
            parse_callback(b'x=' + b'x' * 16385)


class MerchantAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await async_engine.connect()
        self.names = ['xy_waybill_authorizations', 'xy_waybill_platform', 'xy_accounts']
        for name in self.names:
            await self.conn.execute(text(f'DROP TEMPORARY TABLE IF EXISTS {name}'))
        for name in self.names[:2]:
            await self.conn.execute(text(WAYBILL_DDL[name].replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE')))
        from sqlalchemy.schema import CreateTable
        account_ddl = str(CreateTable(XYAccount.__table__).compile(dialect=self.conn.dialect)).replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', 1)
        await self.conn.execute(text(account_ddl))
        await self.conn.commit()
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)
        self.secret_patch = patch('app.services.waybill_platform_service.get_settings', return_value=SimpleNamespace(jwt_secret_key='only-for-unit-test-32-char-secret'))
        self.secret_patch.start()
        await WaybillPlatformService(self.db).save(PlatformInput(app_key='unit-platform', app_secret='unit-platform-secret'))
        self.account = SimpleNamespace(id=990011, owner_id=990011, account_id='isolated-auth-shop', status='active')
        self.db.add(XYAccount(**vars(self.account), cookie='synthetic-fixture-only', login_method='qr'))
        await self.db.commit()
        self.remote = SimpleNamespace(call=AsyncMock(return_value={'success': True, 'url': 'https://xygj.kuaidizs.cn/fixture-login'}))
        self.service = WaybillAuthorizationService(self.db, self.account)
        self.service.client = lambda config: self.remote

    async def asyncTearDown(self):
        self.secret_patch.stop()
        await self.db.rollback()
        await self.db.close()
        for name in self.names:
            await self.conn.execute(text(f'DROP TEMPORARY TABLE IF EXISTS {name}'))
        await self.conn.commit()
        await self.conn.close()
        await async_engine.dispose()

    def token(self):
        return self.remote.call.call_args.args[1]['userName'].rsplit('_', 1)[1]

    async def push(self, params):
        return await WaybillAuthorizationService(self.db).receive_callback(params)

    async def test_start_is_pending_and_never_exposes_secret_or_token_in_status(self):
        result = await self.service.start()
        self.assertEqual(result['url'], 'https://xygj.kuaidizs.cn/fixture-login')
        status = await self.service.status()
        self.assertEqual(status['status'], 'pending')
        self.assertNotIn(self.token(), str(status))
        self.assertNotIn('unit-platform-secret', str(status))
        row = (await self.db.execute(select(WaybillAuthorization))).scalars().one()
        self.assertNotIn(self.token(), row.token_ciphertext)
        await self.service.start()
        self.assertEqual(self.token(), self.remote.call.call_args_list[0].args[1]['userName'].rsplit('_', 1)[1])

    async def test_signed_confirmation_login_and_duplicate_are_idempotent(self):
        await self.service.start()
        token = self.token()
        await self.push(callback(token))
        await self.push(callback(token))
        await self.push(callback(token, method='user.login'))
        status = await self.service.status()
        self.assertEqual(status['status'], 'authorized')
        self.assertIsNotNone(status['authorized_at'])
        self.assertFalse(status['embedded_print_available'])

    async def test_expired_or_revoked_request_cannot_bind(self):
        await self.service.start()
        token = self.token()
        row = (await self.db.execute(select(WaybillAuthorization))).scalars().one()
        row.expires_at = get_beijing_now_naive() - timedelta(seconds=1)
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.push(callback(token))
        await self.db.rollback()
        await self.service.start()
        token = self.token()
        await self.service.revoke()
        with self.assertRaises(HTTPException):
            await self.push(callback(token))
        self.assertEqual((await self.service.status())['status'], 'revoked')

    async def test_other_token_different_mall_and_owner_transfer_do_not_overwrite(self):
        await self.service.start()
        token = self.token()
        with self.assertRaises(HTTPException):
            await self.push(callback('wrong-token'))
        await self.db.rollback()
        await self.push(callback(token))
        with self.assertRaises(HTTPException):
            await self.push(callback(token, mall='456'))
        await self.db.rollback()
        await self.db.execute(update(XYAccount).where(XYAccount.id == self.account.id).values(owner_id=990012))
        await self.db.commit()
        with self.assertRaises(HTTPException):
            await self.push(callback(token, method='user.login'))

    async def test_platform_change_invalidates_old_callback(self):
        await self.service.start()
        token = self.token()
        await WaybillPlatformService(self.db).save(PlatformInput(app_key='unit-platform', app_secret='rotated-unit-secret'))
        self.assertEqual((await self.service.status())['status'], 'stale')
        with self.assertRaises(HTTPException):
            await self.push(callback(token, secret='rotated-unit-secret'))

    async def test_unsafe_provider_url_is_rejected_without_authorizing(self):
        self.remote.call.return_value = {'success': True, 'url': 'https://evil.test/'}
        from common.services.waybill_client import WaybillRemoteError
        with self.assertRaises(WaybillRemoteError):
            await self.service.start()
        self.assertEqual((await self.service.status())['status'], 'pending')

    async def test_same_remote_shop_cannot_bind_to_another_local_account(self):
        await self.service.start()
        await self.push(callback(self.token()))
        other_account = SimpleNamespace(id=990012, owner_id=990012, account_id='other-auth-shop', status='active')
        self.db.add(XYAccount(**vars(other_account), cookie='synthetic-fixture-only', login_method='qr'))
        await self.db.commit()
        other = WaybillAuthorizationService(self.db, other_account)
        other.client = lambda config: self.remote
        await other.start()
        other_token = self.token()
        with self.assertRaises(HTTPException) as caught:
            await self.push(callback(other_token))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual((await self.service.status())['status'], 'authorized')
        self.assertEqual((await other.status())['status'], 'pending')

    async def test_revoke_during_remote_request_invalidates_returned_link(self):
        async def remote(*args):
            await self.service.revoke()
            return {'success': True, 'url': 'https://xygj.kuaidizs.cn/fixture-login'}
        self.remote.call.side_effect = remote
        with self.assertRaises(HTTPException) as caught:
            await self.service.start()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual((await self.service.status())['status'], 'revoked')


class AuthorizationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from app.api.routes import waybills
        self.routes = waybills
        self.app = FastAPI()
        self.app.include_router(waybills.router)
        self.app.dependency_overrides[waybills.get_db_session] = lambda: None
        self.app.dependency_overrides[waybills.get_current_active_user] = lambda: SimpleNamespace(id=7, role='USER')
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.http.aclose()

    async def test_other_accounts_are_rejected_before_contacting_provider(self):
        with patch('app.api.routes.waybills.scoped_account', AsyncMock(side_effect=HTTPException(404, '店铺不存在或无权访问'))), \
                patch('app.services.waybill_authorization_service.KdzsClient') as remote:
            for method in ('get', 'post', 'delete'):
                response = await self.http.request(method, '/waybills/other/authorization')
                self.assertEqual(response.status_code, 404)
            remote.assert_not_called()

    async def test_callback_is_public_but_requires_bounded_form_and_has_no_cache(self):
        public_user = AsyncMock(side_effect=AssertionError('回调不应调用用户登录'))
        self.app.dependency_overrides[self.routes.get_current_active_user] = public_user
        with patch('app.api.routes.waybills.WaybillAuthorizationService') as service:
            service.return_value.receive_callback = AsyncMock(return_value={'code': 200, 'message': 'success'})
            response = await self.http.post('/waybills/provider/callback', data=callback('synthetic-token'))
            self.assertEqual(response.json(), {'code': 200, 'message': 'success'})
            self.assertEqual(response.headers['cache-control'], 'no-store')
            for kwargs, expected in [({'json': {}}, 415),
                    ({'content': b'x=' + b'x' * 16385, 'headers': {'content-type': 'application/x-www-form-urlencoded'}}, 413)]:
                bad = await self.http.post('/waybills/provider/callback', **kwargs)
                self.assertEqual(bad.status_code, expected)
                self.assertEqual(bad.json()['code'], expected)
            self.assertEqual(service.return_value.receive_callback.await_count, 1)


if __name__ == '__main__':
    unittest.main()
