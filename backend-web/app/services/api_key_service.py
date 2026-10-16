"""
对外统一调用入口的秘钥校验服务。

功能：
1. 按请求头 X-API-Key 的值校验调用方身份。
2. 优先匹配对外秘钥表 xy_api_keys（校验状态与过期时间）。
3. 未命中时回落匹配 users.secret_key，便于用本系统已有的分销秘钥零配置自测。

说明：
- M1 只读校验，不写回 last_used_at / total_calls（用量统计留给 M2）。
- 回落查询只新增读取，不改变 users.secret_key 的既有生成与使用逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.api_key import XYApiKey
from common.models.user import User, UserStatus
from common.utils.time_utils import get_beijing_now_naive


# 与 xy_api_keys.key_value、xy_users.secret_key 的字段长度保持一致
MAX_API_KEY_LENGTH = 64

# xy_api_keys.status 的有效值
API_KEY_STATUS_ACTIVE = "active"

# 调用方来源标识
CALLER_SOURCE_API_KEY = "api_key"
CALLER_SOURCE_USER_SECRET = "user_secret"


class InvokeAuthError(RuntimeError):
    """对外统一调用入口鉴权失败时抛出的业务异常。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class InvokeCaller:
    """已通过校验的调用方身份。"""

    key: str
    source: str
    owner_user_id: int = 0
    api_key_id: int = 0
    name: str = ""


def _to_naive(value: datetime | None) -> datetime | None:
    """把可能带时区的时间转为无时区时间（MySQL DATETIME 不保存时区）。"""
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


async def _resolve_api_key(session: AsyncSession, key: str) -> InvokeCaller | None:
    """按 key_value 查对外秘钥表，校验状态与过期时间。

    Args:
        session: 数据库会话。
        key: 已规范化的请求秘钥。
    Returns:
        命中并校验通过时返回调用方身份；未命中返回 None。
    Raises:
        InvokeAuthError: 秘钥存在但已禁用或已过期。
    """
    record = (
        await session.execute(select(XYApiKey).where(XYApiKey.key_value == key).limit(1))
    ).scalar_one_or_none()
    if record is None:
        return None

    if (record.status or "").strip().lower() != API_KEY_STATUS_ACTIVE:
        raise InvokeAuthError(40001, "秘钥已被禁用")

    expire_at = _to_naive(record.expire_at)
    if expire_at is not None and expire_at < get_beijing_now_naive():
        raise InvokeAuthError(40001, "秘钥已过期")

    return InvokeCaller(
        key=key,
        source=CALLER_SOURCE_API_KEY,
        owner_user_id=int(record.owner_user_id or 0),
        api_key_id=int(record.id or 0),
        name=str(record.name or ""),
    )


async def _resolve_user_secret(session: AsyncSession, key: str) -> InvokeCaller | None:
    """回落按 users.secret_key 匹配本系统用户的分销秘钥。

    该回落只用于让部署方用现成的分销秘钥自测连通性，不改变原字段语义。

    Args:
        session: 数据库会话。
        key: 已规范化的请求秘钥。
    Returns:
        命中且用户未被删除时返回调用方身份，否则返回 None。
    """
    user = (
        await session.execute(select(User).where(User.secret_key == key).limit(1))
    ).scalar_one_or_none()
    if user is None or user.status == UserStatus.DELETED:
        return None
    return InvokeCaller(
        key=key,
        source=CALLER_SOURCE_USER_SECRET,
        owner_user_id=int(user.id or 0),
        name=str(user.username or ""),
    )


async def resolve_invoke_caller(session: AsyncSession, raw_key: str | None) -> InvokeCaller:
    """校验 POST /api/v1/external/invoke 的调用方身份。

    Args:
        session: 数据库会话。
        raw_key: 请求头 X-API-Key 的原始值。
    Returns:
        已通过校验的调用方身份。
    Raises:
        InvokeAuthError: 秘钥为空、超长、不存在、已禁用或已过期。
    """
    key = str(raw_key or "").strip()
    if not key:
        raise InvokeAuthError(40001, "秘钥不能为空")
    if len(key) > MAX_API_KEY_LENGTH:
        raise InvokeAuthError(40001, f"秘钥长度不能超过{MAX_API_KEY_LENGTH}位")

    caller = await _resolve_api_key(session, key)
    if caller is not None:
        return caller

    caller = await _resolve_user_secret(session, key)
    if caller is not None:
        return caller

    raise InvokeAuthError(40001, "秘钥不存在或已失效")


__all__ = [
    "API_KEY_STATUS_ACTIVE",
    "CALLER_SOURCE_API_KEY",
    "CALLER_SOURCE_USER_SECRET",
    "MAX_API_KEY_LENGTH",
    "InvokeAuthError",
    "InvokeCaller",
    "resolve_invoke_caller",
]
