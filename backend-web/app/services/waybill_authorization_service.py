"""官方免登与店铺回调；登录确认不授予面单、取号或发货能力。"""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import parse_qsl

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.services.waybill_platform_service import WaybillPlatformService
from common.models.waybill import WaybillAuthorization, WaybillPlatform
from common.models.xy_account import XYAccount
from common.services.waybill_client import KdzsClient, safe_print_url, sign_request
from common.utils.time_utils import get_beijing_now_naive, safe_isoformat

CALLBACK_PATH = '/api/v1/waybills/provider/callback'
_FIELDS = {'appKey', 'method', 'mallUserId', 'timestamp', 'format', 'v', 'signMethod', 'sign', 'appParam'}


def parse_callback(body: bytes) -> dict[str, str]:
    if not body or len(body) > 16384:
        raise HTTPException(400, '回调报文大小无效')
    try:
        pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=12)
        params = dict(pairs)
        if len(params) != len(pairs) or not set(params) <= _FIELDS:
            raise ValueError()
        return params
    except (ValueError, UnicodeError):
        raise HTTPException(400, '回调参数无效或重复') from None


def verify_callback(params: dict[str, str], secret: str):
    if not set(params) <= _FIELDS or params.get('method') not in ('user.push', 'user.login'):
        raise HTTPException(400, '不支持的授权回调')
    if params.get('v') != '1.0' or params.get('signMethod', 'md5').lower() != 'md5' or params.get('format', 'json') != 'json':
        raise HTTPException(400, '回调协议版本无效')
    stamp = params.get('timestamp', '')
    if not re.fullmatch(r'\d{13}', stamp) or abs(int(stamp) - int(time.time() * 1000)) > 600000:
        raise HTTPException(400, '回调已过期')
    supplied = params.get('sign', '')
    if not re.fullmatch(r'[A-Fa-f0-9]{32}', supplied):
        raise HTTPException(403, '回调签名无效')
    # 官方调用说明与回调示例分别公布的两种拼接格式，均涵盖全部原参数。
    joined = '&'.join(f'{key}={params[key]}' for key in sorted(params) if key != 'sign' and params[key] != '')
    documented = hashlib.md5((secret + joined + secret).encode()).hexdigest().upper()
    compact = sign_request(params, secret)
    if not (hmac.compare_digest(supplied.upper(), documented) | hmac.compare_digest(supplied.upper(), compact)):
        raise HTTPException(403, '回调签名无效')


def fingerprint(config):
    return hashlib.sha256((config.app_key + '\0' + config.credentials_ciphertext).encode()).hexdigest()


class WaybillAuthorizationService:
    def __init__(self, db, account=None):
        self.db, self.account = db, account
        self.platform = WaybillPlatformService(db)

    async def _platform(self):
        # populate_existing避免同一请求中等待远端返回后读到旧配置缓存。
        return (await self.db.execute(select(WaybillPlatform).where(WaybillPlatform.id == 1)
                    .execution_options(populate_existing=True))).scalars().first()

    async def _binding(self, *, lock=False):
        stmt = select(WaybillAuthorization).where(WaybillAuthorization.account_pk == self.account.id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt.execution_options(populate_existing=True))).scalars().first()

    async def status(self):
        config = await self._platform()
        configured = bool(config and config.app_key and config.credentials_ciphertext)
        binding = await self._binding()
        state = 'not_started'
        if binding and binding.owner_id == self.account.owner_id:
            state = binding.status
            if state != 'revoked' and (not configured or fingerprint(config) != binding.platform_fingerprint):
                state = 'stale'
            elif state == 'pending' and binding.expires_at <= get_beijing_now_naive():
                state = 'expired'
        return dict(platform_configured=configured, authorization_available=configured, status=state,
                    shop_name=binding.shop_name if state == 'authorized' else '',
                    authorized_at=safe_isoformat(binding.authorized_at) if state == 'authorized' else None,
                    expires_at=safe_isoformat(binding.expires_at) if state == 'pending' else None,
                    embedded_print_available=False, callback_path=CALLBACK_PATH)

    def client(self, config):
        return KdzsClient(config.app_key, self.platform.secret(config))

    def _token(self, binding):
        try:
            value = self.platform._fernet().decrypt(binding.token_ciphertext.encode()).decode()
            if not value.startswith('waybill-auth:'):
                raise ValueError()
            return value[len('waybill-auth:'):]
        except (InvalidToken, UnicodeError, ValueError):
            raise HTTPException(409, '授权请求无法读取，请撤销后重新发起') from None

    async def _commit(self):
        try:
            await self.db.commit()
        except (IntegrityError, OperationalError):
            await self.db.rollback()
            raise HTTPException(409, '授权状态有冲突，请刷新后重试') from None

    async def start(self):
        config = await self._platform()
        if not config or not config.app_key or not config.credentials_ciphertext:
            raise HTTPException(409, '平台应用尚未配置，请联系管理员')
        config_fingerprint = fingerprint(config)
        binding = await self._binding(lock=True)
        now = get_beijing_now_naive()
        reusable = bool(binding and binding.owner_id == self.account.owner_id
                        and binding.platform_fingerprint == config_fingerprint
                        and (binding.status == 'authorized' or (binding.status == 'pending' and binding.expires_at > now)))
        if reusable:
            token = self._token(binding)
        else:
            token = secrets.token_hex(24)
            if not binding:
                binding = WaybillAuthorization(account_pk=self.account.id)
                self.db.add(binding)
            binding.owner_id, binding.app_key = self.account.owner_id, config.app_key
            binding.platform_fingerprint = config_fingerprint
            binding.token_hash = hashlib.sha256(token.encode()).hexdigest()
            binding.token_ciphertext = self.platform._fernet().encrypt(('waybill-auth:' + token).encode()).decode()
            binding.status, binding.mall_user_id, binding.shop_name = 'pending', None, ''
            binding.expires_at, binding.authorized_at = now + timedelta(minutes=15), None
        expected_token_hash = binding.token_hash
        remote = self.client(config)
        secret = self.platform.secret(config)
        username = f'{config.app_key}_xy{self.account.owner_id}-{self.account.id}_{token}'
        # 先提交请求，使服务商即时回调也能找到请求。远端失败仍为待确认，不会授权。
        await self._commit()
        result = await remote.call('kdzs.print.loginurl.get', dict(userName=username, secret=secret))
        url = safe_print_url(result.get('url') or '')
        latest_config = await self._platform()
        latest = await self._binding()
        if (not latest_config or fingerprint(latest_config) != config_fingerprint or not latest
                or latest.token_hash != expected_token_hash or latest.status == 'revoked'):
            raise HTTPException(409, '授权请求已失效，请刷新后重试')
        return dict(url=url, status=latest.status, expires_at=safe_isoformat(latest.expires_at))

    async def revoke(self):
        binding = await self._binding(lock=True)
        if binding and binding.owner_id == self.account.owner_id:
            binding.status, binding.token_ciphertext = 'revoked', ''
            await self._commit()
        return await self.status()

    async def receive_callback(self, params):
        config = await self._platform()
        if not config or not hmac.compare_digest(params.get('appKey', '').encode(), config.app_key.encode()):
            raise HTTPException(403, '授权应用无效')
        verify_callback(params, self.platform.secret(config))
        try:
            payload = json.loads(params['appParam'])
            if not isinstance(payload, dict):
                raise ValueError()
            token = payload.get('token', '')
            if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{48}', token):
                raise ValueError()
            mall = str(payload.get('mallUserId') or params.get('mallUserId') or '')
            if not re.fullmatch(r'[1-9]\d{0,18}', mall) or int(mall) > 9223372036854775807:
                raise ValueError()
            if params.get('mallUserId') and params['mallUserId'] != mall:
                raise ValueError()
            shop_name = payload.get('shopName', '')
            if not isinstance(shop_name, str) or len(shop_name) > 200:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, '授权回调内容无效') from None
        binding = (await self.db.execute(select(WaybillAuthorization).where(
            WaybillAuthorization.token_hash == hashlib.sha256(token.encode()).hexdigest())
            .with_for_update().execution_options(populate_existing=True))).scalars().first()
        if not binding or binding.status == 'revoked' or binding.platform_fingerprint != fingerprint(config):
            raise HTTPException(409, '未找到有效的店铺授权请求')
        account = (await self.db.execute(select(XYAccount).where(XYAccount.id == binding.account_pk,
            XYAccount.owner_id == binding.owner_id).execution_options(populate_existing=True))).scalars().first()
        if not account or account.status in ('deleted', 'disabled', 'suspended'):
            raise HTTPException(409, '店铺归属或状态已变化')
        if binding.status == 'authorized':
            if binding.mall_user_id != mall:
                raise HTTPException(409, '店铺授权已确认，不能覆盖为其他店铺')
        elif params['method'] != 'user.push' or binding.status != 'pending' or binding.expires_at <= get_beijing_now_naive():
            raise HTTPException(409, '授权请求尚未确认或已过期')
        else:
            binding.status, binding.mall_user_id, binding.shop_name = 'authorized', mall, shop_name
            binding.authorized_at = get_beijing_now_naive()
            await self._commit()
        return dict(code=200, message='success')
