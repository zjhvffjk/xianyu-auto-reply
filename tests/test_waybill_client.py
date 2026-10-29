import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from common.services.waybill_client import (
    KdzsClient, WaybillRemoteError, sign_request, validate_recipient, safe_print_url,
)


class WaybillContractTests(unittest.IsolatedAsyncioTestCase):
    def test_official_signature_vector(self):
        params = dict(appKey='1111111', cpCode='ZTO', format='json', mailNo='75491257306780',
                      method='kdzs.logistics.trace.get', sign_method='md5',
                      timestamp='2021-07-28 18:15:31', version='1.0')
        # 文档示例中公布的摘要与其列出的参数不一致；此值由该组参数的
        # 固定规范字符串经独立MD5实现核算，不能照抄文档中的错误摘要。
        self.assertEqual(sign_request(params, 'helloworld'), '1754811FF4FD86EE45FE646C2CAE1522')
        self.assertEqual(sign_request({**params, 'sign': 'ignored', 'empty': ''}, 'helloworld'),
                         sign_request(params, 'helloworld'))

    def test_masked_or_incomplete_recipient_never_passes(self):
        recipient = dict(name='测试', phone='13800138000', province='浙江省', city='杭州市', county='西湖区', address='测试路1号')
        self.assertEqual(validate_recipient(recipient), [])
        for field, value in [('phone', '138****8000'), ('name', '张＊'), ('address', '***'), ('county', '')]:
            self.assertTrue(validate_recipient({**recipient, field: value}))

    def test_official_workbench_url_only(self):
        self.assertEqual(safe_print_url('https://open.kuaidizs.cn/workbench?a=1'), 'https://open.kuaidizs.cn/workbench?a=1')
        for url in ['javascript:alert(1)', 'http://open.kuaidizs.cn/', 'https://kuaidizs.cn.evil.test/', 'https://user:pass@open.kdzs.com/']:
            with self.assertRaises(WaybillRemoteError):
                safe_print_url(url)

    async def test_real_form_request_and_session(self):
        requests = []
        def transport(request):
            requests.append(request)
            if request.url.path == '/api/token':
                return httpx.Response(200, json={'code': 200, 'data': {'success': True, 'accessToken': 'test-session'}})
            return httpx.Response(200, json={'success': True, 'data': []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = KdzsClient('app', 'secret', http=http)
            await client.call('kdzs.print.template.get', {})
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(r.url.scheme == 'https' for r in requests))
        self.assertIn(b'session=test-session', requests[1].content)
        self.assertNotIn(b'appSecret', requests[1].content)
        self.assertEqual(requests[1].url.path, '/open/api')

    async def test_timeout_is_uncertain_and_is_not_retried(self):
        calls = []
        def transport(request):
            calls.append(request)
            raise httpx.ReadTimeout('contains-secret-and-address', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            client = KdzsClient('app', 'secret', http=http, session='session')
            with self.assertRaises(WaybillRemoteError) as caught:
                await client.call('kdzs.print.elecno.batch.get', {'tids': ['order1']})
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(calls), 1)
        self.assertNotIn('contains-secret', str(caught.exception))

    async def test_malformed_success_does_not_pass(self):
        for payload in [{'success': 'true'}, {'code': 200}, [], {'success': False, 'msg': 'secret'}]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as http:
                with self.assertRaises(WaybillRemoteError) as caught:
                    await KdzsClient('app', 'secret', http=http, session='session').call('kdzs.print.template.get', {})
                self.assertNotIn('secret', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
