"""单元测试：素材价格/库存刷新（refresh_price_stock_batch）。

背景：早期「从商品同步」把列表接口的 price_text（买家小刀后的到手价）当售价、
库存写死 1，导致素材价格偏低、库存恒为 1。刷新功能用源商品详情接口
（editdetail）取卖家设置的原价与真实库存覆盖回去。

覆盖三层：
1. 行为层：AST 抽出 _price_stock_refresh_base / count_price_stock_refresh_needed /
   preview_price_stock_refresh，注入假 SQLAlchemy 符号后真实执行，验证刷新范围
   （带 source_item_id、未删除、本人）与计数/预览语义。
2. 行为层（主循环）：AST 抽出 refresh_price_stock_batch 与 _parse_source_ref，
   注入假 session / 假详情接口 / 假风控判定后真实执行，验证：
   - 成功路径：价格与库存按详情表单覆盖；
   - 详情无价无库存：保留原值记失败；
   - 命中风控：立即中断整批（aborted），后续条目不再处理；
   - 账号无 Cookie：记失败跳过；
   - limit 钳制到 MAX_BATCH_LIMIT；
   - 无可刷新素材时短路返回。
3. 契约层：路由两个端点、前端 API 两个函数、页面按钮与处理函数均已接通。

不依赖数据库与第三方库，仓库根直接 `python tests/test_material_price_stock_refresh.py` 可跑。
"""

import ast
import asyncio
import os
import re
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "backend-web", "app", "services", "material_sync_service.py")
ROUTES = os.path.join(REPO_ROOT, "backend-web", "app", "api", "routes", "product_publish.py")
API_TS = os.path.join(REPO_ROOT, "frontend", "src", "api", "productPublish.ts")
PAGE_TSX = os.path.join(
    REPO_ROOT, "frontend", "src", "pages", "product-publish", "ProductMaterials.tsx"
)

# 与 material_sync_service.py 保持一致的真实值（测试内独立一份，改源码时同步）
THROTTLE_SECONDS = 2.5
MAX_REPORTED_ERRORS = 20
DEFAULT_BATCH_LIMIT = 8
MAX_BATCH_LIMIT = 20

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


# ---------- 假 SQLAlchemy 符号 ----------

class FakeColumn:
    """假列：记录比较动作，返回可识别标记。"""

    def __init__(self, table, name):
        self.table = table
        self.name = name

    def is_not(self, value):
        return ("is_not", self.table, self.name, value)

    def is_(self, value):
        return ("is", self.table, self.name, value)

    def __ne__(self, other):
        return ("ne", self.table, self.name, other)

    def __eq__(self, other):
        return ("eq", self.table, self.name, other)

    __hash__ = None


class FakeTable:
    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return FakeColumn(self._name, attr)

    def __repr__(self):
        return f"<FakeTable {self._name}>"


class FakeFunc:
    def count(self):
        return "<func.count()>"


class FakeStmt:
    def __init__(self):
        self.conditions = []
        self.limit_n = None

    def where(self, *conds):
        self.conditions.extend(conds)
        return self

    def select_from(self, *args):
        return self

    def subquery(self):
        return self

    def order_by(self, *args):
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def has_cond(self, table, column, value):
        return any(
            c[0] in ("eq", "ne", "is", "is_not")
            and c[1] == table and c[2] == column and c[3] == value
            for c in self.conditions
        )


def fake_select(*args):
    return FakeStmt()


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return FakeScalars(self._rows)

    def scalar(self):
        return self._scalar


class FakeSession:
    """按调用顺序返回预设结果；记录收到的 stmt 与提交次数。"""

    def __init__(self, script):
        self._script = list(script)
        self.seen = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        self.seen.append(stmt)
        return self._script.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeMaterial:
    """假素材行：只保留刷新逻辑触及的属性。"""

    def __init__(self, id, remark, price=0.1, quantity=1):
        self.id = id
        self.remark = remark
        self.price = price
        self.quantity = quantity
        self.source_item_id = None  # 由 _parse_source_ref 从 remark 解析，不直接读


class FakeAccount:
    def __init__(self, pk, account_id, cookie, owner_id=7):
        self.id = pk
        self.account_id = account_id
        self.cookie = cookie
        self.owner_id = owner_id


class FakeCooldown:
    """假风控判定：消息里带「风控」二字即视为命中。"""

    @staticmethod
    def is_risk_control_error(message):
        return "风控" in str(message or "")


class FakeLogger:
    def __init__(self):
        self.warnings = []
        self.infos = []

    def warning(self, msg, *args):
        self.warnings.append(str(msg))

    def info(self, msg, *args):
        self.infos.append(str(msg))


async def _immediate(_seconds=0):
    return None


FAKE_ASYNCIO = types.SimpleNamespace(sleep=_immediate)


# ---------- AST 抽取 ----------

def _extract(path, picks, class_name=None):
    """从源文件抽出指定函数/方法，返回 {名字: ast 节点}。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    scope = tree.body
    if class_name:
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name]
        assert classes, f"{os.path.basename(path)} 缺少类 {class_name}"
        scope = classes[0].body
    found = {}
    for node in scope:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in picks:
            found[node.name] = node
    missing = set(picks) - set(found)
    assert not missing, f"{os.path.basename(path)} 缺少: {missing}"
    return found


def _compile(nodes, ns):
    """把抽出的函数/赋值编译进给定命名空间（注解不求值）。"""
    mod = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *nodes,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试


def _extract_assignments(path, names):
    """抽出模块级赋值语句（如 _REMARK_REF_RE = re.compile(...)）。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    picked = []
    found = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in names for t in targets):
                picked.append(node)
                found.update(targets)
    missing = set(names) - found
    assert not missing, f"{os.path.basename(path)} 缺少赋值: {missing}"
    return picked


def load_refresh_service():
    """抽出刷新相关方法 + _parse_source_ref，注入假符号，返回 (服务类, 命名空间)。

    命名空间里同时放一份假 fetch_seller_item_edit_detail（可脚本化）与假
    AccountCooldownManager，供主循环测试替换。
    """
    methods = _extract(
        SRC,
        {
            "_price_stock_refresh_base",
            "count_price_stock_refresh_needed",
            "preview_price_stock_refresh",
            "refresh_price_stock_batch",
        },
        class_name="MaterialSyncService",
    )
    parse_ref = _extract(SRC, {"_parse_source_ref"})
    # _parse_source_ref 依赖模块级正则，一并抽出保持与生产同一份
    ref_assigns = _extract_assignments(SRC, {"_REMARK_REF_RE"})

    ns = {
        "select": fake_select,
        "func": FakeFunc(),
        "ProductMaterial": FakeTable("xy_product_materials"),
        "asyncio": FAKE_ASYNCIO,
        "logger": FakeLogger(),
        "AccountCooldownManager": FakeCooldown,
        "re": re,
        "THROTTLE_SECONDS": THROTTLE_SECONDS,
        "MAX_REPORTED_ERRORS": MAX_REPORTED_ERRORS,
        "DEFAULT_BATCH_LIMIT": DEFAULT_BATCH_LIMIT,
        "MAX_BATCH_LIMIT": MAX_BATCH_LIMIT,
        "Any": object,
        # 默认假详情接口：测试里可整体替换（函数运行时按名字查全局，替换即生效）
        "fetch_seller_item_edit_detail": None,
        # 真实的价格/库存提取函数（单独抽出，保证与生产同一份逻辑）
        "extract_detail_price_quantity": None,
    }
    _compile(
        list(methods.values()) + list(parse_ref.values()) + ref_assigns, ns
    )

    # 单独抽出真实的 extract_detail_price_quantity 并挂进命名空间
    extract_fn = _extract(SRC, {"extract_detail_price_quantity"})
    extract_ns = {"Any": object}
    _compile(list(extract_fn.values()), extract_ns)
    ns["extract_detail_price_quantity"] = extract_ns["extract_detail_price_quantity"]

    class FakeService:
        def __init__(self, session, accounts=None):
            self.session = session
            self._accounts = accounts or {}

        async def _load_accounts(self, account_pks):
            return {pk: self._accounts[pk] for pk in account_pks if pk in self._accounts}

    for name in methods:
        setattr(FakeService, name, ns[name])
    return FakeService, ns


def make_detail_ok(form, cookies_str=""):
    return {"success": True, "data": {"form": form}, "cookies_str": cookies_str}


def make_detail_fail(message):
    return {"success": False, "message": message}


# ---------- 1. 刷新范围与计数 ----------

def test_refresh_scope():
    print("\n[1] _price_stock_refresh_base / 计数 / 预览")
    service_cls, _ = load_refresh_service()

    # 范围：本人 + 未删除 + source_item_id 非空
    svc = service_cls(FakeSession([]))
    stmt = svc._price_stock_refresh_base(user_id=42)
    check("范围含 user_id=42", stmt.has_cond("xy_product_materials", "user_id", 42))
    check("范围含 is_deleted=False", stmt.has_cond("xy_product_materials", "is_deleted", False))
    check(
        "范围含 source_item_id IS NOT NULL",
        stmt.has_cond("xy_product_materials", "source_item_id", None),
    )
    check(
        "范围含 source_item_id != ''",
        stmt.has_cond("xy_product_materials", "source_item_id", ""),
    )

    # 计数：走 count + select_from，返回标量
    svc = service_cls(FakeSession([FakeResult(scalar=17)]))
    count = asyncio.run(svc.count_price_stock_refresh_needed(user_id=42))
    check("计数返回 17", count == 17, f"got {count}")

    # 计数为 None → 0
    svc = service_cls(FakeSession([FakeResult(scalar=None)]))
    count = asyncio.run(svc.count_price_stock_refresh_needed(user_id=42))
    check("计数为 None → 0", count == 0, f"got {count}")

    # 预览：{"missing": N}
    svc = service_cls(FakeSession([FakeResult(scalar=5)]))
    preview = asyncio.run(svc.preview_price_stock_refresh(user_id=42))
    check("预览返回 {'missing': 5}", preview == {"missing": 5}, f"got {preview}")


# ---------- 2. 刷新主循环 ----------

def _run_refresh(script, materials, accounts, detail_fn, limit=None):
    """跑一次 refresh_price_stock_batch，返回 (结果, session, service)。"""
    service_cls, ns = load_refresh_service()
    ns["fetch_seller_item_edit_detail"] = detail_fn
    # 重新编译进替换后的 fetch（命名空间已编译过，直接改字典即可——函数体在运行时查名字）
    svc = service_cls(FakeSession(script), accounts=accounts)
    kwargs = {"user_id": 42, "owner_scope": None}
    if limit is not None:
        kwargs["limit"] = limit
    result = asyncio.run(svc.refresh_price_stock_batch(**kwargs))
    return result, svc.session, svc, ns


def test_refresh_success():
    print("\n[2] 刷新主循环：成功路径")
    materials = [
        FakeMaterial(1, "源闲鱼 item_id=1001 acc=4", price=0.1, quantity=1),
        FakeMaterial(2, "源闲鱼 item_id=1002 acc=4", price=0.5, quantity=1),
    ]
    accounts = {4: FakeAccount(4, "accA", "cookie-A")}

    calls = []

    async def detail_ok(*, account_id, cookie, item_id, owner_id):
        calls.append(item_id)
        # 第一条：单规格原价 1 元、库存 9996；第二条：多规格库存取 SKU 之和
        if item_id == "1001":
            return make_detail_ok({"price": 1.0, "quantity": 9996})
        return make_detail_ok({
            "price": 9.9,
            "quantity": 1,
            "sku_rows": [{"stock": 10}, {"stock": 5}],
        })

    # 脚本：总数 2 → 行 2 条 → 剩余 0
    script = [FakeResult(scalar=2), FakeResult(rows=materials), FakeResult(scalar=0)]
    result, session, _, _ = _run_refresh(script, materials, accounts, detail_ok)

    check("两条都刷新成功", result["updated"] == 2 and result["failed"] == 0, f"got {result}")
    check("remaining 归零", result["remaining"] == 0)
    check("未中风控中断", result["aborted"] is False)
    check("逐条调了详情接口", calls == ["1001", "1002"], f"got {calls}")
    check("价格覆盖为卖家原价 1.0", materials[0].price == 1.0, f"got {materials[0].price}")
    check("库存覆盖为真实值 9996", materials[0].quantity == 9996, f"got {materials[0].quantity}")
    check("多规格库存=SKU之和(15)", materials[1].quantity == 15, f"got {materials[1].quantity}")
    check("多规格价格取表单价 9.9", materials[1].price == 9.9, f"got {materials[1].price}")
    check("每条提交一次（共 2 次）", session.commits == 2, f"got {session.commits}")


def test_refresh_detail_empty_keeps_original():
    print("\n[2] 刷新主循环：详情无价无库存 → 保留原值记失败")
    materials = [FakeMaterial(1, "源闲鱼 item_id=1001 acc=4", price=0.1, quantity=1)]
    accounts = {4: FakeAccount(4, "accA", "cookie-A")}

    async def detail_empty(*, account_id, cookie, item_id, owner_id):
        return make_detail_ok({})  # 空表单：无 price 无 quantity

    script = [FakeResult(scalar=1), FakeResult(rows=materials), FakeResult(scalar=1)]
    result, session, _, _ = _run_refresh(script, materials, accounts, detail_empty)

    check("记为失败", result["failed"] == 1 and result["updated"] == 0, f"got {result}")
    check("价格保留原值 0.1", materials[0].price == 0.1, f"got {materials[0].price}")
    check("库存保留原值 1", materials[0].quantity == 1, f"got {materials[0].quantity}")
    check("没有提交", session.commits == 0, f"got {session.commits}")
    check("失败原因说明保留原值", "保留原值" in result["errors"][0]["reason"])


def test_refresh_risk_control_aborts():
    print("\n[2] 刷新主循环：命中风控 → 立即中断")
    materials = [
        FakeMaterial(1, "源闲鱼 item_id=1001 acc=4"),
        FakeMaterial(2, "源闲鱼 item_id=1002 acc=4"),
    ]
    accounts = {4: FakeAccount(4, "accA", "cookie-A")}
    calls = []

    async def detail_risk(*, account_id, cookie, item_id, owner_id):
        calls.append(item_id)
        return make_detail_fail("账号存在风控，请稍后再试")

    script = [FakeResult(scalar=2), FakeResult(rows=materials), FakeResult(scalar=2)]
    result, _, _, _ = _run_refresh(script, materials, accounts, detail_risk)

    check("aborted=True", result["aborted"] is True, f"got {result}")
    check("第一条即中断，第二条不再处理", calls == ["1001"], f"got {calls}")
    # 与 sync_batch 一致：风控中断的那条不计入 failed，由 aborted 标记 + errors 体现
    check("中断条不计 failed（走 aborted + errors）",
          result["failed"] == 0 and len(result["errors"]) == 1, f"got {result}")
    check("remaining 仍为 2（留待下次）", result["remaining"] == 2)


def test_refresh_no_cookie_account():
    print("\n[2] 刷新主循环：账号无 Cookie → 记失败跳过")
    materials = [FakeMaterial(1, "源闲鱼 item_id=1001 acc=4")]
    accounts = {4: FakeAccount(4, "accA", "")}  # 空 Cookie
    calls = []

    async def detail_never(*, account_id, cookie, item_id, owner_id):
        calls.append(item_id)
        return make_detail_ok({"price": 1.0, "quantity": 5})

    script = [FakeResult(scalar=1), FakeResult(rows=materials), FakeResult(scalar=1)]
    result, _, _, _ = _run_refresh(script, materials, accounts, detail_never)

    check("没有调详情接口", calls == [], f"got {calls}")
    check("记为失败", result["failed"] == 1 and result["updated"] == 0, f"got {result}")
    check("原因指明账号不可用", "Cookie" in result["errors"][0]["reason"])


def test_refresh_limit_clamped():
    print("\n[2] 刷新主循环：limit 钳制到 MAX_BATCH_LIMIT")
    materials = [FakeMaterial(1, "源闲鱼 item_id=1001 acc=4")]
    accounts = {4: FakeAccount(4, "accA", "cookie-A")}

    async def detail_ok(*, account_id, cookie, item_id, owner_id):
        return make_detail_ok({"price": 1.0, "quantity": 5})

    script = [FakeResult(scalar=99), FakeResult(rows=materials), FakeResult(scalar=98)]
    _, session, _, _ = _run_refresh(script, materials, accounts, detail_ok, limit=100)

    # 第二次 execute 是取行的 stmt，其 limit 应被钳到 20
    row_stmt = session.seen[1]
    check("limit=100 钳到 20", row_stmt.limit_n == MAX_BATCH_LIMIT, f"got {row_stmt.limit_n}")


def test_refresh_empty_short_circuit():
    print("\n[2] 刷新主循环：无可刷新素材 → 短路")
    service_cls, _ = load_refresh_service()
    svc = service_cls(FakeSession([FakeResult(scalar=0)]))
    result = asyncio.run(svc.refresh_price_stock_batch(user_id=42, owner_scope=None))

    check("全零返回", result == {
        "total_missing": 0, "processed": 0, "updated": 0, "failed": 0,
        "remaining": 0, "aborted": False, "errors": [],
    }, f"got {result}")
    check("没有取行（只跑了计数）", len(svc.session.seen) == 1, f"got {len(svc.session.seen)}")


def test_refresh_cookie_writeback():
    print("\n[2] 刷新主循环：平台刷新 Cookie 时回写账号")
    materials = [FakeMaterial(1, "源闲鱼 item_id=1001 acc=4")]
    account = FakeAccount(4, "accA", "cookie-old")
    accounts = {4: account}

    async def detail_new_cookie(*, account_id, cookie, item_id, owner_id):
        return make_detail_ok({"price": 1.0, "quantity": 5}, cookies_str="cookie-new")

    script = [FakeResult(scalar=1), FakeResult(rows=materials), FakeResult(scalar=0)]
    _run_refresh(script, materials, accounts, detail_new_cookie)

    check("账号 Cookie 已回写新值", account.cookie == "cookie-new", f"got {account.cookie}")


# ---------- 3. 契约层 ----------

def test_contracts():
    print("\n[3] 契约：路由 / 前端 API / 页面按钮均已接通")

    route_src = open(ROUTES, encoding="utf-8").read()
    check("路由：预览端点已注册", '"/materials/price-stock-refresh-preview"' in route_src)
    check("路由：执行端点已注册", '"/materials/refresh-price-stock"' in route_src)
    check("路由：预览处理函数存在", "async def preview_material_price_stock_refresh" in route_src)
    check("路由：执行处理函数存在", "async def refresh_material_price_stock" in route_src)
    check("路由：执行端点复用 MaterialSyncRequest（带 limit）",
          "req: MaterialSyncRequest" in route_src)

    api_src = open(API_TS, encoding="utf-8").read()
    check("前端 api：getMaterialPriceStockRefreshPreview 已定义",
          "export const getMaterialPriceStockRefreshPreview" in api_src)
    check("前端 api：refreshMaterialPriceStock 已定义",
          "export const refreshMaterialPriceStock" in api_src)
    check("前端 api：结果类型含 aborted 字段",
          "MaterialPriceStockRefreshResultData" in api_src and "aborted: boolean" in api_src)

    page_src = open(PAGE_TSX, encoding="utf-8").read()
    check("前端页面：导入了两个刷新 API",
          "getMaterialPriceStockRefreshPreview" in page_src
          and "refreshMaterialPriceStock" in page_src)
    check("前端页面：刷新处理函数存在", "handleRefreshPriceStock" in page_src)
    check("前端页面：按钮文案「刷新价格库存」", "刷新价格库存" in page_src)
    check("前端页面：按钮绑到处理函数", "onClick={handleRefreshPriceStock}" in page_src)
    check("前端页面：提示写明会覆盖手动改过的值", "会覆盖手动改过的值" in page_src)
    check("前端页面：风控中断时停止循环", "data.aborted" in page_src)

    sync_src = open(SRC, encoding="utf-8").read()
    check("服务：刷新范围限定 source_item_id",
          "_price_stock_refresh_base" in sync_src
          and "source_item_id.is_not(None)" in sync_src)
    check("服务：价格/库存取详情表单（extract_detail_price_quantity）",
          "detail_price, detail_quantity = extract_detail_price_quantity(form)" in sync_src)
    check("服务：命中风控立即中断", "AccountCooldownManager.is_risk_control_error" in sync_src)
    check("服务：逐条限速", "await asyncio.sleep(THROTTLE_SECONDS)" in sync_src)


def main():
    test_refresh_scope()
    test_refresh_success()
    test_refresh_detail_empty_keeps_original()
    test_refresh_risk_control_aborts()
    test_refresh_no_cookie_account()
    test_refresh_limit_clamped()
    test_refresh_empty_short_circuit()
    test_refresh_cookie_writeback()
    test_contracts()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
