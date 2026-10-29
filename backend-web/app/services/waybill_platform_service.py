"""统一平台凭据管理；保存凭据不代表服务商审核通过或商家已授权。"""
import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from common.models.waybill import WaybillPlatform


class WaybillPlatformService:
    def __init__(self, db):
        self.db = db

    def _fernet(self):
        secret = get_settings().jwt_secret_key
        if not secret or len(secret) < 16 or secret == 'change-me-in-production-please':
            raise HTTPException(503, '服务密钥尚未初始化，请重启后再保存平台应用')
        key = hmac.new(secret.encode(), b'waybill-platform:v1', hashlib.sha256).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def secret(self, config):
        try:
            return self._fernet().decrypt(config.credentials_ciphertext.encode()).decode()
        except (InvalidToken, UnicodeError, AttributeError):
            raise HTTPException(409, '平台密钥无法读取，请管理员重新保存') from None

    async def _config(self, *, lock=False):
        stmt = select(WaybillPlatform).where(WaybillPlatform.id == 1)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalars().first()

    async def settings(self):
        config = await self._config()
        configured = bool(config and config.app_key and config.credentials_ciphertext)
        return dict(configured=configured,
                    app_key=config.app_key if config else '',
                    has_secret=bool(config and config.credentials_ciphertext),
                    authorization_available=configured, embedded_print_available=False)

    async def save(self, data):
        config = await self._config(lock=True)
        if not data.app_secret and (not config or config.app_key != data.app_key):
            raise HTTPException(422, '新增或更换平台AppKey时请填写对应AppSecret')
        if config and not data.app_secret:
            self.secret(config)  # 损坏或服务密钥变化时不能假装已保存有效凭据。
        if not config:
            config = WaybillPlatform(id=1)
            self.db.add(config)
        config.app_key = data.app_key
        if data.app_secret:
            config.credentials_ciphertext = self._fernet().encrypt(data.app_secret.get_secret_value().encode()).decode()
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, '平台配置已被其他管理员修改，请刷新后重试') from None
        return await self.settings()
