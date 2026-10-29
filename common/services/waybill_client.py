"""快递助手公开协议客户端；不自动重试有副作用的请求，不记录原始报文。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

GATEWAY = 'https://gw.kuaidizs.cn/open/api'
TOKEN_URL = 'https://gw.superboss.cc/api/token'


class WaybillRemoteError(Exception):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


def sign_request(params: dict, secret: str) -> str:
    joined = ''.join(f'{key}{params[key]}' for key in sorted(params)
                     if key != 'sign' and params[key] is not None and str(params[key]) != '')
    return hashlib.md5(f'{secret}{joined}{secret}'.encode('utf-8')).hexdigest().upper()


def validate_recipient(recipient: dict) -> list[str]:
    names = dict(name='姓名', phone='电话', province='省份', city='城市', county='区县', address='详细地址')
    errors = []
    for key, label in names.items():
        value = str(recipient.get(key) or '').strip()
        if not value:
            errors.append(f'请补充收件人{label}')
        elif any(char in value for char in ('*', '＊', '●', '•')) or '已隐藏' in value:
            errors.append(f'收件人{label}已脱敏，请核对完整信息')
    phone = str(recipient.get('phone') or '').strip()
    if phone and not re.fullmatch(r'[+\d][\d\s()\-]{5,30}', phone):
        errors.append('收件电话格式不正确')
    return errors


def safe_print_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        valid_host = any(host == domain or host.endswith('.' + domain)
                         for domain in ('kuaidizs.cn', 'kdzs.com', 'superboss.cc'))
        if parsed.scheme != 'https' or not valid_host or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
    except (ValueError, TypeError):
        raise WaybillRemoteError('打印工作台地址未通过校验，请联系服务商核对') from None
    return url


class KdzsClient:
    def __init__(self, app_key: str, secret: str, *, http=None, session: str | None = None):
        self.app_key = app_key
        self.secret = secret
        self.http = http
        self.session = session

    async def _post(self, url, *, data=None, files=None):
        try:
            if self.http is not None:
                response = await self.http.post(url, data=data, files=files)
            else:
                async with httpx.AsyncClient(timeout=25, follow_redirects=False) as http:
                    response = await http.post(url, data=data, files=files)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (httpx.HTTPError, ValueError):
            # 无法判断服务商是否已受理，尤其不能在取号时自动重试。
            raise WaybillRemoteError('服务商响应未确认，请先在打印工作台核对结果，不要重复取号', uncertain=True) from None

    async def _session(self):
        if self.session:
            return self.session
        try:
            result = await self._post(TOKEN_URL, files={
                'appKey': (None, self.app_key), 'appSecret': (None, self.secret), 'expires': (None, '86400000'),
            })
        except WaybillRemoteError:
            raise WaybillRemoteError('开放平台授权连接未完成，尚未发送业务请求，请稍后检测连接') from None
        data = result.get('data')
        if result.get('code') != 200 or not isinstance(data, dict) or data.get('success') is not True or not data.get('accessToken'):
            raise WaybillRemoteError('开放平台授权失败，请检查应用是否已审核及AppKey、AppSecret是否正确')
        self.session = str(data['accessToken'])
        return self.session

    async def call(self, method: str, business: dict):
        session = await self._session()
        params = dict(method=method, appKey=self.app_key, session=session,
                      timestamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),
                      format='json', version='1.0', sign_method='md5')
        for key, value in business.items():
            if value is not None:
                params[key] = json.dumps(value, ensure_ascii=False, separators=(',', ':')) if isinstance(value, (dict, list)) else str(value)
        params['sign'] = sign_request(params, self.secret)
        result = await self._post(GATEWAY, data=params)
        if result.get('success') is not True:
            if result.get('success') is False:
                raise WaybillRemoteError('服务商未受理，请检查应用权限、面单授权及套餐状态')
            raise WaybillRemoteError('服务商返回格式异常，请在工作台核对处理结果', uncertain=True)
        return result
