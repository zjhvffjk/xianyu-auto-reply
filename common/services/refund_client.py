"""官方卖家工作台退款协议。接口名称及参数核对自官方交易微应用0.0.26。"""
import json
import time
from urllib.parse import urlsplit
import aiohttp
from common.utils.xianyu_utils import trans_cookies, generate_sign
from common.services.order_service import OrderService


class RefundPlatformError(Exception):
    pass


def valid_verification_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname == 'pcauth-site.alipay.com'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and parsed.path == '/home')
    except (ValueError, TypeError):
        return False


class RefundPlatformClient:
    def __init__(self, session, account):
        self.session, self.account = session, account

    async def applications(self):
        from common.services.refund_tools import parse_refund_application
        result = await OrderService(self.session)._fetch_refund_orders_page(
            self.account.cookie, '1', self.account.account_id)
        if not result or result.get('error'):
            raise RefundPlatformError('读取平台退款申请失败，请检查店铺登录')
        return [parse_refund_application(item) for item in result.get('items') or []]

    async def _request(self, api: str, payload: dict):
        # 禁止执行平台响应中任意API；所有调用在这里静态指定。
        if api not in {'mtop.idle.alipay.verify.url.query',
                       'mtop.taobao.idle.merchant.refund.agree.refund'}:
            raise RefundPlatformError('未支持的退款操作')
        data = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
        stamp = str(int(time.time()*1000))
        token = trans_cookies(self.account.cookie).get('_m_h5_tk', '').split('_')[0]
        params = dict(jsv='2.7.2', appKey='34839810', t=stamp, sign=generate_sign(stamp, token, data),
                      v='1.0', type='json', accountSite='xianyu', dataType='json', api=api,
                      sessionOption='AutoLoginOnly')
        # 提交接口绝不自动重试。异常可能发生在平台已执行之后。
        async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as http:
            async with http.post(f'https://h5api.m.goofish.com/h5/{api}/1.0/', params=params,
                data={'data': data}, headers={'cookie': self.account.cookie,
                    'idle_site_biz_code': 'COMMONPRO', 'Referer': 'https://seller.goofish.com/?site=COMMONPRO'},
                timeout=aiohttp.ClientTimeout(total=25)) as response:
                result = await response.json()
        ret = result.get('ret') or []
        if not ret or str(ret[0]).split('::', 1)[0] != 'SUCCESS':
            # 不把含验证上下文的原始响应/异常写入日志或返回前端。
            code = str(ret[0]).split('::', 1)[0] if ret else 'EMPTY_RESPONSE'
            if not code.replace('_', '').isalnum() or len(code) > 80:
                code = 'PLATFORM_REJECTED'
            raise RefundPlatformError(f'平台拒绝退款操作（{code}），请重新核对或在官方后台处理')
        return result.get('data') or {}

    async def verification(self, refund_id: str):
        data = await self._request('mtop.idle.alipay.verify.url.query', dict(
            bizId=refund_id, scene='REFUND_PC',
            callBackUrl='https://seller.goofish.com/?site=COMMONPRO#/seller-trade/refund-manage'))
        module = data.get('module') or {}
        url, token = module.get('verifyUrl'), module.get('token')
        if not isinstance(url, str) or not valid_verification_url(url) or not isinstance(token, str) or not token:
            raise RefundPlatformError('平台未返回受支持的支付宝验证页，请到官方后台处理')
        return dict(verify_url=url, token=token)

    async def agree(self, refund_id: str, token: str):
        result = await self._request('mtop.taobao.idle.merchant.refund.agree.refund',
                                    dict(refundId=refund_id, authToken=token))
        # ret=SUCCESS 是官方界面采用的业务成功判据，仍拒绝显式业务失败。
        if result.get('success') is False or (isinstance(result.get('data'), dict) and result['data'].get('success') is False):
            raise RefundPlatformError('平台未确认退款成功，请到官方后台核实')
        # 受理成功与资金退款完成分开标记，以官方退款成功清单再次确认。
        try:
            if refund_id in await self.refunded_ids():
                return 'success'
        except Exception:
            pass
        return 'submitted'

    async def refunded_ids(self):
        result = await OrderService(self.session)._fetch_refund_orders_page(
            self.account.cookie, '5', self.account.account_id)
        if not result or result.get('error'):
            raise RefundPlatformError('退款完成状态暂无法核实')
        return {str((item.get('refundInfoVO') or {}).get('refundId') or '')
                for item in result.get('items') or []
                if str((item.get('commonData') or {}).get('refundStatus')) == '5'}
