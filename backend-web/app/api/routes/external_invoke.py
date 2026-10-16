"""
对外统一调用入口（公开接口，无需登录）。

功能：
1. 提供 POST /api/v1/external/invoke 单一入口，按请求体 type 分发到具体能力。
2. 使用请求头 X-API-Key 鉴权（对外秘钥表 xy_api_keys，回落 users.secret_key）。
3. M1 实现 type=xianyu_token：用 Cookie 换取闲鱼 accessToken。

路径说明：本路由 prefix 为 /external/invoke，由 _bootstrap.py 统一挂在 /api/v1 下，
因此完整地址是 <域名>/api/v1/external/invoke。

协议约定（由本系统客户端 common/services/remote_token_api.py 反推并冻结）：
    请求：POST /api/v1/external/invoke
          X-API-Key: <秘钥>
          {"type": "xianyu_token", "data": {"cookies": "<完整闲鱼Cookie>"}}
    成功：{"success": true,  "code": 200, "message": "...", "data": {"token", "device_id", "api_mode"}}
    失败：{"success": false, "code": <业务码>, "message": "...", "data": null}

注意：HTTP 状态码恒为 200（本项目全局约定），真实结果看 body 的 success 与 code。
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
from fastapi import APIRouter, Body, Depends, Header
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.routes.external_api_route import ExternalApiRoute
from app.api.routes.external_shared import ExternalApiResponse, external_error
from app.services.api_key_service import (
    InvokeAuthError,
    InvokeCaller,
    resolve_invoke_caller,
)
from common.services.account_cooldown import AccountCooldownManager
from common.services.im_token_api import (
    extract_im_access_token,
    is_session_expired_token_result,
    request_im_token,
)
from common.services.remote_token_api import REMOTE_TOKEN_TYPE
from common.services.token_api_mode import TOKEN_API_MODE_WEB
from common.utils.xianyu_utils import (
    extract_account_user_id_from_cookie,
    generate_device_id,
)


router = APIRouter(
    prefix="/external/invoke",
    tags=["公开统一调用"],
    route_class=ExternalApiRoute,
)

# 请求头名称，与客户端 common/services/remote_token_api.py 发送的一致
API_KEY_HEADER_NAME = "X-API-Key"

# 单次取 Token 的上游请求超时（秒），与系统设置中测试远程接口的 30 秒保持一致
INVOKE_TOKEN_TIMEOUT_SECONDS = 30

# 无法从 Cookie 解析出账号标识时，用 Cookie 哈希派生，保证同一账号的 device_id 稳定
FALLBACK_USER_ID_LENGTH = 16


class InvokeRequest(BaseModel):
    """对外统一调用请求体。"""

    type: str | None = None
    data: dict[str, Any] | None = None


# 处理函数签名：会话、调用方身份、业务参数
InvokeHandler = Callable[[AsyncSession, InvokeCaller, dict[str, Any]], Awaitable[ExternalApiResponse]]


def _extract_upstream_message(response_json: Any) -> str:
    """从上游 mtop 响应中提取可读的失败原因。

    Args:
        response_json: 上游返回的 JSON 数据。
    Returns:
        拼接后的 ret 文本；无法解析时返回空字符串。
    """
    if not isinstance(response_json, dict):
        return ""
    ret_value = response_json.get("ret", []) or []
    if isinstance(ret_value, str):
        ret_value = [ret_value]
    return "；".join(str(item).strip() for item in ret_value if str(item).strip())


async def handle_xianyu_token(
    session: AsyncSession,
    caller: InvokeCaller,
    payload: dict[str, Any],
) -> ExternalApiResponse:
    """处理 type=xianyu_token：用账号 Cookie 换取闲鱼 accessToken。

    Args:
        session: 数据库会话（M1 未使用，M2 将用于写调用计量）。
        caller: 已通过校验的调用方身份（M1 未使用，M2 将用于归属用量）。
        payload: 业务参数，需包含 cookies 字段。
    Returns:
        统一响应；成功时 data 含 token、device_id、api_mode。
    """
    cookies = str(payload.get("cookies") or "").strip()
    if not cookies:
        # 文案必须命中客户端 REMOTE_TOKEN_EMPTY_COOKIES_HINTS，
        # 否则系统设置里的「测试远程接口」会误判为连通失败
        return external_error(40001, "cookies不能为空")

    user_id = extract_account_user_id_from_cookie(cookies) or hashlib.md5(
        cookies.encode("utf-8")
    ).hexdigest()[:FALLBACK_USER_ID_LENGTH]
    device_id = generate_device_id(str(user_id))

    try:
        result = await request_im_token(
            cookies_str=cookies,
            device_id=device_id,
            api_mode=TOKEN_API_MODE_WEB,
            timeout_seconds=INVOKE_TOKEN_TIMEOUT_SECONDS,
        )
    except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
        logger.warning(f"对外取Token上游异常: {type(exc).__name__}: {exc}")
        return external_error(50301, "上游接口超时，请稍后重试")
    except Exception as exc:
        logger.error(f"对外取Token异常: {type(exc).__name__}: {exc}")
        return external_error(50001, f"取Token失败：{type(exc).__name__}")

    token = extract_im_access_token(result.response_json)
    if token:
        return ExternalApiResponse(
            success=True,
            code=200,
            message="取Token成功",
            data={
                "token": token,
                "device_id": device_id,
                "api_mode": TOKEN_API_MODE_WEB,
            },
        )

    if is_session_expired_token_result(result):
        return external_error(40101, "Cookie 已失效，请重新登录")

    upstream_message = _extract_upstream_message(result.response_json)
    if AccountCooldownManager.is_risk_control_error(upstream_message):
        return external_error(40202, "触发风控验证，请稍后重试")

    return external_error(50001, f"取Token失败：{upstream_message or '上游未返回有效Token'}")


# type -> 处理函数；新增能力只需在此登记一个 handler
INVOKE_HANDLERS: dict[str, InvokeHandler] = {
    REMOTE_TOKEN_TYPE: handle_xianyu_token,
}


@router.post("", response_model=ExternalApiResponse)
async def invoke_external_api(
    payload: InvokeRequest | None = Body(default=None),
    x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER_NAME),
    session: AsyncSession = Depends(get_db_session),
) -> ExternalApiResponse:
    """对外统一调用入口：鉴权后按 type 分发到具体能力。

    Args:
        payload: 请求体，含 type 与 data。
        x_api_key: 请求头 X-API-Key 中的对外秘钥。
        session: 数据库会话。
    Returns:
        统一响应；HTTP 状态码恒为 200，业务结果看 success 与 code。
    """
    try:
        caller = await resolve_invoke_caller(session, x_api_key)
    except InvokeAuthError as exc:
        return external_error(exc.code, exc.message)
    except Exception as exc:
        logger.error(f"对外统一调用鉴权异常: {type(exc).__name__}: {exc}")
        return external_error(50001, "秘钥校验失败，请稍后重试")

    invoke_type = str(payload.type or "").strip() if payload else ""
    if not invoke_type:
        return external_error(40004, "缺少接口类型 type")

    handler = INVOKE_HANDLERS.get(invoke_type)
    if handler is None:
        return external_error(40004, f"不支持的接口类型: {invoke_type}")

    logger.info(
        f"对外统一调用: type={invoke_type}, source={caller.source}, "
        f"owner_user_id={caller.owner_user_id}"
    )

    try:
        return await handler(session, caller, payload.data or {})
    except Exception as exc:
        logger.error(f"对外统一调用异常: type={invoke_type}, error={type(exc).__name__}: {exc}")
        return external_error(50001, f"{invoke_type} 处理失败，请稍后重试")


__all__ = ["INVOKE_HANDLERS", "handle_xianyu_token", "router"]
