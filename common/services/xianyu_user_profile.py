"""闲鱼账号自身资料（昵称 / 头像）的获取与缓存

背景：
    账号对外展示的名字有三种来源，容易混淆——
    1. 数字 account_id：闲鱼用户ID（unb），如 2217257506103
    2. 会员名：Cookie.tracknick，如 xy813599502354，可用 common.utils.account_name 本地解析
    3. 昵称：用户在闲鱼 App 里自设的店铺名，如「明星周边奢侈品」

    昵称既不在 Cookie 里，也不能从商品详情接口（mtop.taobao.idle.pc.detail）的
    sellerDO.nick 拿到——那里返回的其实是会员名。唯一稳定的来源是个人页接口
    mtop.idle.web.user.page.nav：它按当前登录账号返回 data.module.base.displayName，
    正是昵称本身，同时附带头像、卖出数、粉丝数。

缓存：
    昵称不会频繁变化，而账号列表是高频接口，因此结果写入 xy_accounts.metadata 的
    profile 节点（无需新增表字段），带 TTL；失败的账号做短退避，避免反复打接口触发风控。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

from loguru import logger

from common.services.xianyu_mtop import mtop_call

PROFILE_API = "mtop.idle.web.user.page.nav"
PROFILE_VERSION = "1.0"

# xy_accounts.metadata 中存放资料的键名
PROFILE_META_KEY = "profile"

# 资料缓存有效期（秒）：过期后下次列表请求会顺带刷新一次
CACHE_TTL_SECONDS = 6 * 60 * 60

# 拉取失败后的退避时间（秒）：避免每次列表请求都去撞风控
FAIL_BACKOFF_SECONDS = 10 * 60

# 单次列表请求里并发刷新资料的最大账号数（控制延迟与风控风险）
MAX_REFRESH_PER_REQUEST = 5

# 单个账号资料请求超时（秒）
REFRESH_TIMEOUT_SECONDS = 8.0


def _module_base(result: Dict[str, Any]) -> Dict[str, Any]:
    """从 page.nav 响应中取出 data.module.base 节点"""
    data = (result.get("res") or {}).get("data") or {}
    module = data.get("module") or {}
    base = module.get("base") or {}
    return base if isinstance(base, dict) else {}


async def fetch_my_profile(
    account_id: str,
    cookies_str: str,
    *,
    owner_id: Optional[int] = None,
    proxy: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """获取当前登录账号的个人资料（昵称优先）。

    Returns:
        成功：{"nickname", "avatar", "sold_count", "followers", "following", "refreshed_at"}
        失败或未取到昵称：None
    """
    if not account_id or not cookies_str:
        return None

    try:
        result = await mtop_call(
            account_id,
            cookies_str,
            PROFILE_API,
            PROFILE_VERSION,
            {},
            owner_id=owner_id,
            proxy=proxy,
            extra_params={"spm_cnt": "a21ybx.personal.0.0"},
        )
    except Exception as exc:  # 网络异常不应影响账号列表返回
        logger.warning(f"【账号资料】{account_id} 请求个人页资料异常: {exc}")
        return None

    if not result.get("success"):
        logger.warning(
            f"【账号资料】{account_id} 获取失败: {str(result.get('error') or '')[:120]}"
        )
        return None

    base = _module_base(result)
    nickname = str(base.get("displayName") or "").strip()
    if not nickname:
        logger.warning(f"【账号资料】{account_id} 响应中没有 displayName，跳过")
        return None

    return {
        "nickname": nickname,
        "avatar": base.get("avatar") or "",
        "sold_count": base.get("soldCount"),
        "followers": base.get("followers"),
        "following": base.get("following"),
        "refreshed_at": int(time.time()),
    }


def read_cached_profile(account: Any) -> Optional[Dict[str, Any]]:
    """读取账号上已缓存的资料（不发起网络请求）"""
    metadata = getattr(account, "metadata_json", None) or {}
    if not isinstance(metadata, dict):
        return None
    profile = metadata.get(PROFILE_META_KEY)
    return profile if isinstance(profile, dict) else None


def cached_nickname(account: Any) -> str:
    """取缓存里的昵称，没有则返回空串"""
    profile = read_cached_profile(account) or {}
    return str(profile.get("nickname") or "").strip()


def needs_refresh(account: Any, now: Optional[int] = None) -> bool:
    """判断是否需要为该账号刷新资料

    - 从未成功取到昵称：尝试（失败过则按退避时间）
    - 已取到昵称：超过 TTL 才刷新
    """
    profile = read_cached_profile(account)
    current = int(now if now is not None else time.time())
    if not profile:
        return True

    if profile.get("nickname"):
        refreshed_at = int(profile.get("refreshed_at") or 0)
        return (current - refreshed_at) >= CACHE_TTL_SECONDS

    # 上次失败：记录在 failed_at，退避期内不再重试
    failed_at = int(profile.get("failed_at") or 0)
    if failed_at and (current - failed_at) < FAIL_BACKOFF_SECONDS:
        return False
    return True


def store_profile(account: Any, profile: Optional[Dict[str, Any]]) -> bool:
    """把资料写回账号 metadata，返回是否有实际变化

    注意：必须整体替换 metadata 对象，JSON 列的原地修改不会被 SQLAlchemy 感知。
    """
    metadata = getattr(account, "metadata_json", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    payload = dict(profile) if profile else {"failed_at": int(time.time())}
    if profile and not payload.get("nickname"):
        payload["failed_at"] = int(time.time())

    if metadata.get(PROFILE_META_KEY) == payload:
        return False

    new_metadata = dict(metadata)
    new_metadata[PROFILE_META_KEY] = payload
    account.metadata_json = new_metadata
    return True


def pick_refresh_targets(accounts: Iterable[Any], limit: int = MAX_REFRESH_PER_REQUEST) -> list:
    """从账号列表里挑出本次需要刷新资料的账号（限制并发数量）"""
    now = int(time.time())
    targets = [acc for acc in accounts if needs_refresh(acc, now)]
    return targets[:limit]
