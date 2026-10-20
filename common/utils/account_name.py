"""账号显示名解析（会员名优先）

背景：
    闲鱼账号在系统内以数字 account_id（如 2219497676740）标识，但用户在界面上认的是
    **会员名**（如 xy663550356691，等同于手机「账号与安全 - 会员名」）。

    会员名可以从 Cookie 的 tracknick 字段拿到（URL 编码，中文需 unquote）；
    平台部分接口返回的昵称会打码（如 x***1），这类值不能当作展示名。

本模块只做纯字符串解析，不含数据库/网络访问，便于单测。
"""
from urllib.parse import unquote

from common.utils.xianyu_utils import trans_cookies

# 打码昵称的标记（平台返回 x***1 / x***8 这类）
MASK_MARK = "*"


def is_masked_name(name: str | None) -> bool:
    """是否为平台打码昵称（含 * 即视为打码，不可作为展示名）"""
    return bool(name) and MASK_MARK in (name or "")


def _cookie_tracknick(cookie_str: str | None) -> str:
    """从 Cookie 中解析 tracknick（会员名），失败返回空串"""
    if not cookie_str:
        return ""
    try:
        cookies = trans_cookies(cookie_str)
    except Exception:
        return ""
    raw = cookies.get("tracknick") or ""
    if not raw:
        return ""
    try:
        return unquote(raw).strip()
    except Exception:
        return raw.strip()


def resolve_member_name(cookie_str: str | None, stored_name: str | None = None) -> str:
    """解析会员名

    优先级：
        1. Cookie.tracknick（闲鱼真实会员名，如 xy663550356691）
        2. 库内 display_name（仅当未打码）
        3. 空串（由调用方决定回退展示 account_id）

    Args:
        cookie_str: 账号 Cookie 字符串
        stored_name: 数据库中已存的 display_name

    Returns:
        会员名；无法确定时返回空串
    """
    tracknick = _cookie_tracknick(cookie_str)
    if tracknick and not is_masked_name(tracknick):
        return tracknick

    stored = (stored_name or "").strip()
    if stored and not is_masked_name(stored):
        return stored

    return ""


def resolve_nickname(stored_name: str | None, member_name: str) -> str:
    """解析昵称（用户自设的店铺名，如「樱岛资源工坊」）

    仅当库内 display_name 未打码、且与会员名不同才返回，避免两行显示重复。
    """
    stored = (stored_name or "").strip()
    if not stored or is_masked_name(stored) or stored == member_name:
        return ""
    return stored
