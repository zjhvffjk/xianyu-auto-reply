"""公开状态接口边界验证；外部探测与数据库均使用模拟，不访问平台。"""
import asyncio
import io
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from loguru import logger

from app.api.routes import public_status as routes
from app.services import public_status_service as service
from app.services.service_status_service import probe_health


def state():
    return dict(services=[], online_accounts=2, online_accounts_available=True,
                total_users=1, total_accounts=3, totals_available=True)


class PublicStatusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix='/api/v1')
        self.limiter = patch.object(routes, 'check_sliding_window_limit', new_callable=AsyncMock)
        self.limit = self.limiter.start()
        self.limit.return_value = NS(allowed=True, remaining=14, retry_after=0)
        self.status_patch = patch.object(routes, 'get_public_status', new_callable=AsyncMock)
        self.status = self.status_patch.start()
        self.status.return_value = state()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=('127.0.0.1', 1234)), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.status_patch.stop()
        self.limiter.stop()

    async def test_unauthenticated_and_trailing_slash_return_same_data(self):
        for path in ['/api/v1/public/status', '/api/v1/public/status/']:
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['data'], state())
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.limit.await_count, 2)

    async def test_rate_limit_and_redis_failure_never_probe_services(self):
        self.limit.return_value = NS(allowed=False, remaining=0, retry_after=12)
        response = await self.client.get('/api/v1/public/status')
        self.assertEqual(response.json()['code'], 42901)
        self.assertEqual(response.headers['retry-after'], '12')
        self.status.assert_not_awaited()
        self.limit.side_effect = RuntimeError('test unavailable')
        response = await self.client.get('/api/v1/public/status')
        self.assertEqual(response.json()['code'], 50301)
        self.assertFalse(response.json()['success'])
        self.status.assert_not_awaited()

    async def test_unsupported_methods_are_limited_without_status_query(self):
        for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            response = await self.client.request(method, '/api/v1/public/status')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['code'], 40501)
        self.assertEqual(self.limit.await_count, 4)
        self.status.assert_not_awaited()

    async def test_unavailable_counts_stay_null(self):
        self.status.return_value = dict(state(), online_accounts=None, online_accounts_available=False,
                                       total_users=None, total_accounts=None, totals_available=False)
        data = (await self.client.get('/api/v1/public/status')).json()
        self.assertIsNone(data['data']['online_accounts'])
        self.assertIsNone(data['data']['total_accounts'])
        self.assertIn('暂不可用', data['message'])

    async def test_request_logs_do_not_record_credentials(self):
        stream = io.StringIO()
        sink = logger.add(stream, format='{message}', diagnose=False)
        try:
            await self.client.get('/api/v1/public/status',
                headers={'authorization': 'Bearer fake-auth-secret', 'cookie': 'session=fake-cookie-secret'},
                params={'token': 'fake-query-secret'})
        finally:
            logger.remove(sink)
        for value in ['fake-auth-secret', 'fake-cookie-secret', 'fake-query-secret']:
            self.assertNotIn(value, stream.getvalue())

    async def test_failed_internal_probe_does_not_log_token_or_cookies(self):
        stream = io.StringIO()
        sink = logger.add(stream, format='{message}', diagnose=False)
        class Response:
            status = 503
            url = httpx.URL('http://internal/health')
            headers = {'set-cookie': 'fake-response-secret'}
            request_info = NS(headers={'authorization': 'fake-internal-secret'})
            async def text(self): return '{"success":false,"message":"unavailable"}'
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        class Session:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def get(self, *args, **kwargs): return Response()
        try:
            with patch('app.services.service_status_service.aiohttp.ClientSession', Session):
                result = await probe_health('http://internal/health', headers={'authorization': 'fake-internal-secret'})
            self.assertFalse(result['online'])
        finally:
            logger.remove(sink)
        for value in ['fake-internal-secret', 'fake-response-secret']:
            self.assertNotIn(value, stream.getvalue())

    async def test_service_output_contains_only_public_summary(self):
        backend = [dict(key='websocket', label='消息服务', online=True, message='private detail', port=8090)]
        with patch.object(service, 'get_backend_services_status', AsyncMock(return_value=backend)), \
             patch.object(service, 'probe_health', AsyncMock(return_value={'online': True})), \
             patch.object(service, '_get_online_accounts', AsyncMock(return_value=None)), \
             patch.object(service, '_get_dashboard_totals', AsyncMock(return_value=None)):
            result = await service.get_public_status()
        self.assertIsNone(result['online_accounts'])
        self.assertFalse(result['totals_available'])
        self.assertEqual(set(result['services'][1]), {'key', 'label', 'online'})
        self.assertNotIn('private detail', str(result))

    async def test_probe_timeout_with_production_diagnostics_never_logs_token(self):
        stream = io.StringIO()
        sink = logger.add(stream, format='{message}', diagnose=True, backtrace=True)
        class Session:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def get(self, url, headers): raise asyncio.TimeoutError()
        try:
            with patch('app.services.service_status_service.aiohttp.ClientSession', Session):
                result = await probe_health('http://internal/health', headers={'authorization': 'fake-timeout-secret'})
            self.assertFalse(result['online'])
            self.assertIn('超时', result['message'])
        finally:
            logger.remove(sink)
        self.assertNotIn('fake-timeout-secret', stream.getvalue())


if __name__ == '__main__':
    unittest.main()
