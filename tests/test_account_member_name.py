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

    # 失败结果也会落缓存（记录 failed_at），避免每次列表都打接口
    probe = _FakeAccount(metadata={})
    mod.store_profile(probe, None)
    check("失败结果记录 failed_at",
          bool((probe.metadata_json or {}).get("profile", {}).get("failed_at")))

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
    check("账号列表：缓存写回后刷新 updated_at 列",
          'await session.refresh(account, ["updated_at"])' in src)
    check("账号列表：只刷新本次真正改动的账号", "touched.append(account)" in src)
    check("账号列表：时间戳读取有兜底，不过期属性导致 500",
          "def _safe_timestamp(" in src and '_safe_timestamp(account, "updated_at")' in src)
    check("账号列表：commit 失败后不再刷过期对象", "缓存写回失败" in src and "return" in src.split("缓存写回失败")[1][:200])

    chat_src = read(CHAT_NEW_PY)
    check("聊天账号列表：打码值也会被会员名纠正",
          "is_masked_name(display_name)" in chat_src and "resolve_member_name(" in chat_src)

    svc_src = read(ACCOUNT_SERVICE_PY)
    check("账号筛选：支持会员名/备注（or_ 三选一）",
          "or_(" in svc_src and "XYAccount.display_name.ilike(" in svc_src
          and "XYAccount.remark.ilike(" in svc_src)


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
