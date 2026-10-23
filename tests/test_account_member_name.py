"""账号会员名 / 昵称显示测试

背景：
    账号管理里原先「账号ID」列直接展示数字 account_id（2219497676740），
    但用户认的是闲鱼**会员名**（如 xy663550356691，与手机「账号与安全-会员名」一致）。
    会员名存在 Cookie 的 tracknick 字段里（URL 编码），平台部分接口返回的昵称是打码值
    （x***1），不能直接当展示名。

    昵称（用户在闲鱼 App 里自设的店铺名，如「明星周边奢侈品」）既不在 Cookie 里，
    也不在商品详情接口的 sellerDO.nick 里（那里给的是会员名），只能通过个人页接口
    mtop.idle.web.user.page.nav 的 data.module.base.displayName 取得。

   最终展示层级（用户定稿）：主行 = 会员名，副行 = 昵称。

覆盖：
    [1] 纯函数行为：resolve_member_name / resolve_nickname / is_masked_name
    [2] 昵称服务：page.nav 解析、metadata 缓存、TTL 与失败退避
    [3] 后端契约：账号列表返回 member_name/nickname、聊天列表纠正打码值、账号筛选支持会员名
    [4] 前端契约：账号列主行会员名 + 副行昵称、类型定义、筛选文案
"""
import asyncio
import importlib.util
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_UTILS = os.path.join(REPO_ROOT, "common", "utils")
COMMON_SERVICES = os.path.join(REPO_ROOT, "common", "services")
ACCOUNT_NAME_PY = os.path.join(COMMON_UTILS, "account_name.py")
PROFILE_PY = os.path.join(COMMON_SERVICES, "xianyu_user_profile.py")
COOKIES_PY = os.path.join(REPO_ROOT, "backend-web", "app", "api", "routes", "cookies.py")
CHAT_NEW_PY = os.path.join(REPO_ROOT, "backend-web", "app", "api", "routes", "chat_new.py")
ACCOUNT_SERVICE_PY = os.path.join(REPO_ROOT, "backend-web", "app", "services", "account_service.py")
ACCOUNTS_TSX = os.path.join(REPO_ROOT, "frontend", "src", "pages", "accounts", "Accounts.tsx")
API_ACCOUNTS_TS = os.path.join(REPO_ROOT, "frontend", "src", "api", "accounts.ts")
TYPES_TS = os.path.join(REPO_ROOT, "frontend", "src", "types", "index.ts")
CHAT_NEW_TSX = os.path.join(REPO_ROOT, "frontend", "src", "pages", "chat-new", "ChatNew.tsx")
CHAT_API_TS = os.path.join(REPO_ROOT, "frontend", "src", "api", "chatNew.ts")
ACCOUNT_SCHEMA_PY = os.path.join(REPO_ROOT, "common", "schemas", "account.py")
ACCOUNT_LABEL_TS = os.path.join(REPO_ROOT, "frontend", "src", "utils", "accountLabel.ts")
BATCH_LOG_HELPERS_TS = os.path.join(REPO_ROOT, "frontend", "src", "components", "common", "BatchLogDetailHelpers.tsx")
BATCH_LOG_DETAIL_TSX = os.path.join(REPO_ROOT, "frontend", "src", "components", "common", "BatchLogDetail.tsx")

# 8 类批量日志详情页：表头都应是「账号」，不能是「账号ID」
BATCH_DETAIL_PAGES = [
    os.path.join(REPO_ROOT, "frontend", "src", "pages", d, f)
    for d, f in [
        ("apiCookieRenewLogs", "ApiCookieRenewBatchDetail.tsx"),
        ("closeNoticeLogs", "CloseNoticeBatchDetail.tsx"),
        ("cookiesRefreshLogs", "CookiesRefreshBatchDetail.tsx"),
        ("loginRenewLogs", "LoginRenewBatchDetail.tsx"),
        ("polishLogs", "PolishBatchDetail.tsx"),
        ("rateLogs", "RateBatchDetail.tsx"),
        ("redeliveryLogs", "RedeliveryBatchDetail.tsx"),
        ("redFlowerLogs", "RedFlowerBatchDetail.tsx"),
        ("tokenRenewalLogs", "TokenRenewalBatchDetail.tsx"),
    ]
]

# 使用账号下拉的页面（都必须走统一文案，避免各写一套数字ID）
ACCOUNT_LABEL_PAGES = [
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "items", "Items.tsx"), "商品管理筛选"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "ProductMaterials.tsx"), "商品发布素材库"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "keywords", "Keywords.tsx"), "关键词管理"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "messageFilters", "MessageFilters.tsx"), "消息过滤"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "orders", "Orders.tsx"), "订单管理"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "notifications", "MessageNotifications.tsx"), "消息通知"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "autoReplyLogs", "AutoReplyLogs.tsx"), "自动回复日志"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "feedback", "Feedback.tsx"), "意见反馈"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "blacklist", "PersonalBlacklistFormModal.tsx"), "个人黑名单"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "ProductPublishForm.tsx"), "商品发布表单"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "BatchPublish.tsx"), "批量发布"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "PublishLogs.tsx"), "发布日志"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "AutoRelistModal.tsx"), "自动重新上架"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "crawler", "GoofishScheduledCrawler.tsx"), "定时采集"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "messageFilters", "MessageFilterFormModal.tsx"), "消息过滤弹窗"),
]

# 展示账号列的表格/详情（不是下拉），同样不能露数字账号ID
ACCOUNT_TABLE_PAGES = [
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "orders", "Orders.tsx"), "订单管理"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "items", "Items.tsx"), "商品管理表格"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "notifications", "MessageNotifications.tsx"), "消息通知表格"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "admin", "RiskLogs.tsx"), "风控日志"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "admin", "AccountLoginLogs.tsx"), "登录日志"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "crawler", "GoofishScheduledCrawler.tsx"), "定时采集表格"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "messageFilters", "MessageFilterRulesTable.tsx"), "消息过滤规则表格"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "BatchPublish.tsx"), "批量发布进度"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "product-publish", "PublishLogs.tsx"), "发布日志表格"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "feedback", "Feedback.tsx"), "意见反馈"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "shared-scan", "SharedScanManager.tsx"), "共享扫码"),
    (os.path.join(REPO_ROOT, "frontend", "src", "pages", "blacklist", "PersonalBlacklist.tsx"), "个人黑名单列表"),
]

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name}" + (f" —— {detail}" if detail else ""))


def _stub_loguru():
    """loguru stub：本机测试环境未安装，仅需占位"""
    if "loguru" in sys.modules:
        return
    stub = types.ModuleType("loguru")
    stub.logger = types.SimpleNamespace(
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )
    sys.modules["loguru"] = stub


def _stub_package(name, path):
    """构造一个包占位，避免加载 __init__.py 拉入重依赖"""
    if name in sys.modules:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [path]
    sys.modules[name] = pkg


def load_account_name_module():
    """按文件路径加载 account_name.py（跳过 common.utils 包级导入，避免拉入重依赖）"""
    _stub_loguru()
    _stub_package("common", os.path.join(REPO_ROOT, "common"))
    _stub_package("common.utils", COMMON_UTILS)

    xu_spec = importlib.util.spec_from_file_location(
        "common.utils.xianyu_utils", os.path.join(COMMON_UTILS, "xianyu_utils.py")
    )
    xu_module = importlib.util.module_from_spec(xu_spec)
    sys.modules["common.utils.xianyu_utils"] = xu_module
    xu_spec.loader.exec_module(xu_module)

    spec = importlib.util.spec_from_file_location("account_name", ACCOUNT_NAME_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeAccount:
    """最小账号替身：只需要 account_id / cookie / owner_id / metadata_json"""

    def __init__(self, account_id="2217257506103", metadata=None, owner_id=1):
        self.account_id = account_id
        self.cookie = "cookie2=x; tracknick=xy813599502354"
        self.owner_id = owner_id
        self.metadata_json = metadata


def load_profile_module():
    """加载昵称服务模块，并把 mtop_call 替换成可控桩"""
    _stub_loguru()
    _stub_package("common", os.path.join(REPO_ROOT, "common"))
    _stub_package("common.services", COMMON_SERVICES)

    holder = {"response": {"success": False, "error": "stub 未设置"}, "calls": []}

    async def fake_mtop_call(account_id, cookies_str, api, version, data, **kwargs):
        holder["calls"].append({"account_id": account_id, "api": api, "version": version, "data": data})
        return holder["response"]

    mtop_stub = types.ModuleType("common.services.xianyu_mtop")
    mtop_stub.mtop_call = fake_mtop_call
    sys.modules["common.services.xianyu_mtop"] = mtop_stub

    spec = importlib.util.spec_from_file_location("xianyu_user_profile", PROFILE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, holder


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# ---------- 1. 纯函数行为 ----------

def test_resolver_behavior():
    print("\n[1] 行为：会员名 / 昵称解析")
    mod = load_account_name_module()
    resolve_member_name = mod.resolve_member_name
    resolve_nickname = mod.resolve_nickname
    is_masked_name = mod.is_masked_name

    # Cookie.tracknick = 会员名（明文）
    check("明文 tracknick 直接作为会员名",
          resolve_member_name("cookie2=abc; tracknick=xy663550356691; unb=2219497676740", None)
          == "xy663550356691")
    # URL 编码的中文昵称需解码
    check("URL 编码 tracknick 正确解码",
          resolve_member_name("tracknick=%E6%A8%B1%E5%B2%9B%E8%B5%84%E6%BA%90%E5%B7%A5%E5%9D%8A", None)
          == "樱岛资源工坊")
    # tracknick 优先于库内打码值
    check("tracknick 优先于打码的 display_name",
          resolve_member_name("tracknick=xy813599502354", "x***1") == "xy813599502354")
    # 无 Cookie 时回退未打码 display_name
    check("无 Cookie 时回退未打码 display_name",
          resolve_member_name("", "樱岛资源工坊") == "樱岛资源工坊")
    # 打码值不可用
    check("打码 display_name 不作为会员名", resolve_member_name("", "x***1") == "")
    check("打码 tracknick 不作为会员名", resolve_member_name("tracknick=x***8", "") == "")
    # 空/脏数据不抛异常
    check("空 Cookie 返回空串", resolve_member_name(None, None) == "")
    check("非法 Cookie 串不抛异常", resolve_member_name("这不是cookie", "") == "")

    # 打码判定
    check("is_masked_name 识别打码", is_masked_name("x***1") and not is_masked_name("xy663550356691"))
    check("is_masked_name 空值不算打码", is_masked_name("") is False and is_masked_name(None) is False)

    # 昵称：仅当未打码且与会员名不同才展示
    check("昵称与会员名不同则返回昵称",
          resolve_nickname("樱岛资源工坊", "xy663550356691") == "樱岛资源工坊")
    check("昵称与会员名相同则不重复展示",
          resolve_nickname("xy663550356691", "xy663550356691") == "")
    check("打码昵称不展示", resolve_nickname("x***1", "xy663550356691") == "")
    check("空昵称不展示", resolve_nickname(None, "xy663550356691") == "")


# ---------- 2. 昵称服务 ----------

def test_profile_service():
    print("\n[2] 行为：昵称服务（page.nav + 缓存）")
    import time

    mod, holder = load_profile_module()

    # 接口名与版本必须与抓包一致，否则取不到昵称
    check("使用个人页接口 mtop.idle.web.user.page.nav",
          mod.PROFILE_API == "mtop.idle.web.user.page.nav")
    check("接口版本为 1.0", mod.PROFILE_VERSION == "1.0")

    # 成功：从 data.module.base.displayName 解析昵称
    holder["response"] = {
        "success": True,
        "res": {"data": {"module": {"base": {
            "displayName": "明星周边奢侈品",
            "avatar": "http://img.alicdn.com/a.jpg",
            "soldCount": 222,
            "followers": "923",
        }}}},
    }
    profile = asyncio.run(mod.fetch_my_profile("2217257506103", "cookie2=x", owner_id=1))
    check("成功解析出昵称 displayName",
          bool(profile) and profile["nickname"] == "明星周边奢侈品",
          detail=str(profile))
    check("同时带回头像/卖出数", bool(profile) and profile["avatar"].endswith("a.jpg")
          and profile["sold_count"] == 222)
    check("请求携带昵称接口与空 data", holder["calls"][-1]["api"] == mod.PROFILE_API
          and holder["calls"][-1]["data"] == {})

    # 失败：接口返回 success=False
    holder["response"] = {"success": False, "error": "FAIL_SYS_USER_VALIDATE"}
    check("接口失败返回 None", asyncio.run(mod.fetch_my_profile("2", "c", owner_id=1)) is None)

    # 成功但无 displayName（异常响应）也不能当昵称用
    holder["response"] = {"success": True, "res": {"data": {"module": {"base": {}}}}}
    check("无 displayName 返回 None", asyncio.run(mod.fetch_my_profile("3", "c", owner_id=1)) is None)

    # 空账号/空 Cookie 直接短路，不打接口
    before = len(holder["calls"])
    check("空 Cookie 不打接口", asyncio.run(mod.fetch_my_profile("4", "", owner_id=1)) is None
          and len(holder["calls"]) == before)

    # 缓存写入 / 读取
    holder["response"] = {"success": True, "res": {"data": {"module": {"base": {
        "displayName": "樱岛资源工坊"}}}}}
    account = _FakeAccount(metadata={"ai_reply_settings": {"enabled": True}})
    fresh = asyncio.run(mod.fetch_my_profile("2219497676740", "c", owner_id=1))
    check("首次无缓存，需要刷新", mod.needs_refresh(account) is True)
    changed = mod.store_profile(account, fresh)
    check("写入缓存返回有变化", changed is True)
    check("缓存写在 metadata.profile 下",
          (account.metadata_json or {}).get("profile", {}).get("nickname") == "樱岛资源工坊")
    check("不破坏 metadata 里已有配置",
          (account.metadata_json or {}).get("ai_reply_settings") == {"enabled": True})
    check("cached_nickname 读到昵称", mod.cached_nickname(account) == "樱岛资源工坊")
    check("刚写入的缓存不需要立刻刷新", mod.needs_refresh(account) is False)
    check("写入相同内容不重复提交", mod.store_profile(account, fresh) is False)

    # TTL：超过 6 小时才刷新
    stale = _FakeAccount(metadata={"profile": {
        "nickname": "旧昵称", "refreshed_at": int(time.time()) - mod.CACHE_TTL_SECONDS - 10}})
    check("缓存超过 TTL 后触发刷新", mod.needs_refresh(stale) is True)

    # 失败退避：失败后 10 分钟内不再撞接口
    failed = _FakeAccount(metadata={"profile": {"failed_at": int(time.time())}})
    check("失败后进入退避，不重复请求", mod.needs_refresh(failed) is False)
    old_failed = _FakeAccount(metadata={"profile": {"failed_at": int(time.time()) - 3600}})
    check("退避到期后允许重试", mod.needs_refresh(old_failed) is True)

    # 从未取到昵称（账号刚添加 / 刚换 Cookie）用短退避：
    # 否则第一次失败要等 10 分钟，界面上一直只有会员名
    fresh_fail = _FakeAccount(metadata={"profile": {"failed_at": int(time.time()) - 120}})
    check("从未取到昵称：短退避到期即重试", mod.needs_refresh(fresh_fail) is True)
    just_fail = _FakeAccount(metadata={"profile": {"failed_at": int(time.time()) - 5}})
    check("从未取到昵称：短退避期内不重复请求", mod.needs_refresh(just_fail) is False)
    has_nick_fail = _FakeAccount(metadata={"profile": {
        "nickname": "奶油泡芙",
        "refreshed_at": int(time.time()) - mod.CACHE_TTL_SECONDS - 10,
        "failed_at": int(time.time()) - 120}})
    check("已有昵称：仍按长退避，避免频繁打接口",
          mod.needs_refresh(has_nick_fail) is False)
    check("短退避常量小于长退避",
          mod.NO_NICKNAME_BACKOFF_SECONDS < mod.FAIL_BACKOFF_SECONDS)

    # 失败结果也会落缓存（记录 failed_at），避免每次列表都打接口
    probe = _FakeAccount(metadata={})
    mod.store_profile(probe, None)
    check("失败结果记录 failed_at",
          bool((probe.metadata_json or {}).get("profile", {}).get("failed_at")))

    # 失败不能抹掉已缓存的昵称：否则一次超时就让账号退回「只有会员名」，
    # 且退避期间无法恢复（用户反馈「有个号看不到昵称」的根因）
    keep = _FakeAccount(metadata={"profile": {
        "nickname": "奶油泡芙", "avatar": "http://a/b.jpg",
        "refreshed_at": int(time.time()) - 3600}})
    mod.store_profile(keep, None)
    kept_profile = (keep.metadata_json or {}).get("profile", {})
    check("刷新失败保留已有昵称", kept_profile.get("nickname") == "奶油泡芙",
          detail=str(kept_profile))
    check("刷新失败保留头像等字段", kept_profile.get("avatar") == "http://a/b.jpg")
    check("刷新失败同时记下 failed_at", bool(kept_profile.get("failed_at")))

    # 接口成功但没给昵称：同样不能覆盖掉旧昵称
    no_nick = _FakeAccount(metadata={"profile": {
        "nickname": "奶油泡芙", "refreshed_at": int(time.time()) - 3600}})
    mod.store_profile(no_nick, {"avatar": "http://a/new.jpg", "refreshed_at": int(time.time())})
    no_nick_profile = (no_nick.metadata_json or {}).get("profile", {})
    check("返回无昵称时保留旧昵称", no_nick_profile.get("nickname") == "奶油泡芙",
          detail=str(no_nick_profile))
    check("返回无昵称时头像仍可更新", no_nick_profile.get("avatar") == "http://a/new.jpg")
    check("返回无昵称时不刷新 refreshed_at（以便退避后重试）",
          no_nick_profile.get("refreshed_at") == int(time.time()) - 3600,
          detail=str(no_nick_profile.get("refreshed_at")))

    # 昵称过期 + 刚失败：退避期内不应再打接口（避免每次开页面都撞风控）
    stale_failed = _FakeAccount(metadata={"profile": {
        "nickname": "奶油泡芙",
        "refreshed_at": int(time.time()) - mod.CACHE_TTL_SECONDS - 10,
        "failed_at": int(time.time())}})
    check("昵称过期但刚失败过：退避期内不重复请求",
          mod.needs_refresh(stale_failed) is False)
    stale_retry = _FakeAccount(metadata={"profile": {
        "nickname": "奶油泡芙",
        "refreshed_at": int(time.time()) - mod.CACHE_TTL_SECONDS - 10,
        "failed_at": int(time.time()) - mod.FAIL_BACKOFF_SECONDS - 5}})
    check("退避到期后仍会刷新过期昵称", mod.needs_refresh(stale_retry) is True)

    # 并发刷新数量受限
    many = [_FakeAccount(account_id=str(i), metadata={}) for i in range(10)]
    targets = mod.pick_refresh_targets(many)
    check("单次刷新账号数受限（防触发风控）", len(targets) == mod.MAX_REFRESH_PER_REQUEST)

    # 缓存命中的账号不会被重复刷新
    cached = [_FakeAccount(account_id="2219497676740", metadata={"profile": {
        "nickname": "樱岛资源工坊", "refreshed_at": int(time.time())}})]
    check("已缓存账号不重复刷新", mod.pick_refresh_targets(cached) == [])


# ---------- 3. 后端契约 ----------

def test_backend_contract():
    print("\n[3] 契约：后端返回与纠错")

    src = read(COOKIES_PY)
    check("账号列表：引入会员名解析", "from common.utils.account_name import" in src)
    check("账号列表：引入昵称服务",
          "from common.services.xianyu_user_profile import" in src)
    check("账号列表：返回 member_name", '"member_name": member_name' in src)
    check("账号列表：返回 nickname", '"nickname": nickname' in src)
    check("账号列表：昵称优先取接口缓存", "cached_nickname(account)" in src)
    check("账号列表：昵称与会员名相同时去重（未设昵称的账号不重复展示）",
          "resolve_nickname(cached_nick, member_name)" in src)
    check("账号列表：刷新前按需挑账号（带缓存判断）", "pick_refresh_targets(accounts)" in src)
    check("账号列表：仍返回数字 id（详情/操作依赖）", '"id": account.account_id' in src)

    # 回归：写回昵称缓存后 update 会让 updated_at（onupdate=func.now()）过期，
    # 若不在异步上下文刷新，序列化读它就会抛 MissingGreenlet（线上实测 27 次报错）
    # 刷新逻辑与账号列表共用，实现放在 xianyu_user_profile 服务里
    profile_src = read(PROFILE_PY)
    check("账号资料服务：缓存写回后刷新 updated_at 列",
          'await session.refresh(account, ["updated_at"])' in profile_src)
    check("账号资料服务：只刷新本次真正改动的账号", "touched.append(account)" in profile_src)
    check("账号资料服务：commit 失败后不再刷过期对象",
          "缓存写回失败" in profile_src and "return" in profile_src.split("缓存写回失败")[1][:200])
    check("账号管理：改用共用的资料刷新函数",
          "refresh_account_profiles(session, pick_refresh_targets(accounts))" in src)
    check("账号列表：时间戳读取有兜底，不过期属性导致 500",
          "def _safe_timestamp(" in src and '_safe_timestamp(account, "updated_at")' in src)

    chat_src = read(CHAT_NEW_PY)
    check("聊天账号列表：打码值也会被会员名纠正",
          "is_masked_name(display_name)" in chat_src and "resolve_member_name(" in chat_src)
    check("聊天账号列表：返回昵称字段", '"nickname": resolve_nickname(cached_nickname(acc), display_name)' in chat_src)
    check("聊天账号列表：与账号管理共用昵称缓存刷新",
          "refresh_account_profiles(db, pick_refresh_targets(accounts))" in chat_src)
    check("聊天账号列表：昵称与会员名相同则不重复返回",
          "resolve_nickname(cached_nickname(acc)" in chat_src)

    svc_src = read(ACCOUNT_SERVICE_PY)
    check("账号筛选：支持会员名/备注（or_ 三选一）",
          "or_(" in svc_src and "XYAccount.display_name.ilike(" in svc_src
          and "XYAccount.remark.ilike(" in svc_src)
    # 昵称必须在「添加账号 / 换 Cookie / 扫码登录 / 密码登录」当场取，
    # 而不是等账号列表第一次打开（否则成员看不到昵称会以为没同步）
    warm_calls = svc_src.count("await self._warm_profile(")
    check("登录与添加账号：四条入口都当场取昵称", warm_calls == 4,
          detail=f"实际 {warm_calls} 处")
    check("登录后取昵称失败不阻断登录", "登录后刷新昵称失败" in svc_src)


# ---------- 4. 前端契约 ----------

def test_frontend_contract():
    print("\n[4] 契约：前端展示")

    src = read(ACCOUNTS_TSX)
    check("账号列：主行会员名优先，其次昵称",
          "{account.member_name || account.nickname || '—'}" in src)
    check("账号列：副行展示闲鱼昵称",
          "? [account.nickname, account.remark].filter(Boolean).join(' · ')" in src)
    check("账号列：不再展示数字账号ID",
          "ID ${account.id}" not in src)
    check("账号列：不再直接以数字ID为主展示",
          "{account.note ? `${account.id} (${account.note})` : account.id}" not in src)
    check("筛选文案：提示可用会员名搜索", "输入会员名 / 账号ID / 备注 模糊搜索" in src)
    check("表头：标注会员名与昵称", "账号（会员名 / 昵称）" in src)

    # 回归：接口封装对返回字段做了白名单映射，曾把 member_name / nickname 丢掉，
    # 导致后端有值而页面只显示数字ID
    api_src = read(API_ACCOUNTS_TS)
    check("接口封装：声明 member_name 字段", "member_name?: string" in api_src)
    check("接口封装：声明 nickname 字段", "nickname?: string" in api_src)
    check("接口封装：映射时透传 member_name", "member_name: item.member_name || ''" in api_src)
    check("接口封装：映射时透传 nickname", "nickname: item.nickname || ''" in api_src)

    types_src = read(TYPES_TS)
    check("类型：Account 增加 member_name", "member_name?: string" in types_src)
    check("类型：Account 增加 nickname", "nickname?: string" in types_src)

    # 在线聊天左侧账号列表：会员名 / 昵称 / 用户名 三行，不再显示数字ID
    chat_tsx = read(CHAT_NEW_TSX)
    check("在线聊天：副行展示昵称", "{acc.nickname || acc.remark}" in chat_tsx)
    check("在线聊天：副行不再回退数字账号ID",
          "acc.remark !== acc.display_name ? acc.remark : acc.account_id" not in chat_tsx)
    check("在线聊天：第三行仍展示所属用户名", "{acc.owner}" in chat_tsx)

    chat_api_src = read(CHAT_API_TS)
    check("在线聊天：ChatAccount 类型增加 nickname", "nickname?: string" in chat_api_src)
    check("在线聊天：账号列表接口不做字段白名单（直接透传）",
          "data: res.data || []" in chat_api_src)

    # 账号下拉（商品管理筛选 / 商品发布素材库 / 关键词 / 订单等）：会员名 + 昵称
    schema_src = read(ACCOUNT_SCHEMA_PY)
    option_svc_src = read(ACCOUNT_SERVICE_PY)
    check("账号下拉：接口模型含会员名", "member_name: str" in schema_src)
    check("账号下拉：接口模型含昵称", "nickname: str" in schema_src)
    check("账号下拉：服务层返回会员名与昵称",
          '"member_name": member_name' in option_svc_src and '"nickname": resolve_nickname(' in option_svc_src)
    check("账号下拉：服务层查询带 cookie 与 metadata（算名字要用）",
          "XYAccount.cookie," in option_svc_src and "XYAccount.metadata_json," in option_svc_src)

    label_src = read(ACCOUNT_LABEL_TS)
    check("账号下拉：统一文案函数存在", "export const getAccountOptionLabel" in label_src)
    check("账号下拉：文案为「会员名 · 昵称」", "${memberName} · ${extra}" in label_src)
    check("账号下拉：无会员名时回退原写法（数据源未升级也不变）",
          "return account.note ? `${account.id} (${account.note})` : account.id" in label_src)

    api_accounts_src = read(API_ACCOUNTS_TS)
    check("账号下拉：接口封装透传 member_name",
          "member_name: item.member_name" in api_accounts_src)
    check("账号下拉：接口封装透传 nickname", "nickname: item.nickname" in api_accounts_src)

    # 各页面下拉都改用统一文案（商品管理筛选、商品发布素材库、关键词、订单…）
    for page_path, page_name in ACCOUNT_LABEL_PAGES:
        page_src = read(page_path)
        check(f"账号下拉：{page_name} 使用统一文案",
              "getAccountOptionLabel(" in page_src)
    check("账号下拉：全站不再用「数字ID (备注)」手写文案",
          all("account.note ? `${account.id} (${account.note})` : account.id" not in read(p)
              for p, _ in ACCOUNT_LABEL_PAGES))

    # 表格列 / 详情展示：订单、商品、通知、风险日志、登录日志、采集任务、过滤规则…
    # 这些地方原先直接把 cookie_id 打印出来，用户同样认不出
    orders_src = read(os.path.join(REPO_ROOT, "frontend", "src", "pages", "orders", "Orders.tsx"))
    check("订单表格：账号列显示会员名（不再露数字ID）",
          "account ? getAccountOptionLabel(account) : order.cookie_id" in orders_src)
    check("订单表格：表头由「账号ID」改为「账号」",
          "label: '账号'," in orders_src and "label: '账号ID'" not in orders_src)
    check("订单详情：账号字段同样显示会员名",
          "account ? getAccountOptionLabel(account) : (orderDetail.cookie_id" in orders_src)

    check("全站不再出现「账号ID (备注)」的表格文案",
          all("account?.note ? `${" not in read(p) for p, _ in ACCOUNT_TABLE_PAGES))
    for page_path, page_name in ACCOUNT_TABLE_PAGES:
        check(f"账号列：{page_name} 使用统一文案",
              "getAccountOptionLabel(" in read(page_path))

    # 8 个批量日志详情页共用一个 renderAccountIdCell，改它一处即可全覆盖
    helpers_src = read(BATCH_LOG_HELPERS_TS)
    check("批量日志：账号单元格改为查会员名", "accountLabelLookup" in helpers_src)
    check("批量日志：取不到会员名时回退账号ID",
          "|| accountId" in helpers_src)
    check("批量日志：公共组件加载账号表并触发重渲染",
          "setAccountLabelLookup(" in read(BATCH_LOG_DETAIL_TSX))
    check("全站表头不再叫「账号ID」（值已是会员名）",
          all(">账号ID<" not in read(p) and "'账号ID'" not in read(p)
              for p, _ in ACCOUNT_TABLE_PAGES + ACCOUNT_LABEL_PAGES))
    check("批量日志详情页表头统一为「账号」",
          all("title: '账号ID'" not in read(p) for p in BATCH_DETAIL_PAGES))


def main():
    print("=" * 60)
    print("账号会员名 / 昵称显示测试")
    print("=" * 60)
    test_resolver_behavior()
    test_profile_service()
    test_backend_contract()
    test_frontend_contract()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
