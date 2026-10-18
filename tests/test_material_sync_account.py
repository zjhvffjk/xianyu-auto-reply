"""单元测试：「从商品同步」按账号筛选（account_pk）。

覆盖两层：
1. 行为层：AST 抽出 _missing_stmt / count_missing / preview，注入假 SQLAlchemy 符号后
   真实执行，验证 account_pk 条件进出 WHERE 的时机、以及 preview 的
   「by_account 全量分项 + missing 按选中账号收窄」语义。
2. 契约层：AST 断言 sync_batch 内部每个 count_missing / _missing_stmt 调用都带
   account_pk（remaining 必须与筛选同范围，否则前端循环永远等不到归零），
   并断言路由 / 前端两层参数已接通。

不依赖数据库与第三方库，仓库根直接 `python tests/test_material_sync_account.py` 可跑。
"""

import ast
import asyncio
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(
    REPO_ROOT, "backend-web", "app", "services", "material_sync_service.py"
)
ROUTES = os.path.join(REPO_ROOT, "backend-web", "app", "api", "routes", "product_publish.py")
API_TS = os.path.join(REPO_ROOT, "frontend", "src", "api", "productPublish.ts")
PAGE_TSX = os.path.join(
    REPO_ROOT, "frontend", "src", "pages", "product-publish", "ProductMaterials.tsx"
)

WANT_METHODS = {"_missing_stmt", "count_missing", "preview", "_pooled_source_ids"}

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


# ---------- 假 SQLAlchemy 符号 ----------

class FakeColumn:
    """假列：记录比较动作，返回可识别标记。"""

    def __init__(self, table, name):
        self.table = table
        self.name = name

    def is_not(self, value):
        return ("is_not", self.table, self.name, value)

    def not_in(self, sub):
        return ("not_in", self.table, self.name, sub)

    def __ne__(self, other):
        return ("ne", self.table, self.name, other)

    def __eq__(self, other):
        return ("eq", self.table, self.name, other)

    __hash__ = None  # 比较语义优先，禁用默认哈希


class FakeTable:
    def __init__(self, name):
        self._name = name

    def __getattr__(self, attr):
        return FakeColumn(self._name, attr)

    def __repr__(self):
        return f"<FakeTable {self._name}>"


class FakeFuncCount:
    def __repr__(self):
        return "<func.count()>"


class FakeFunc:
    def count(self):
        return FakeFuncCount()


class FakeStmt:
    def __init__(self):
        self.conditions = []

    def where(self, *conds):
        self.conditions.extend(conds)
        return self

    def select_from(self, *args):
        return self

    def order_by(self, *args):
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def has_cond(self, table, column, value):
        return any(
            c[0] == "eq" and c[1] == table and c[2] == column and c[3] == value
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


class FakeRow:
    """商品库一行：只要 account_pk / item_id 两个属性。"""

    def __init__(self, account_pk, item_id="1001"):
        self.account_pk = account_pk
        self.item_id = item_id


class FakeSession:
    """按调用顺序返回预设结果；同时记录收到的 stmt 供断言。"""

    def __init__(self, script):
        self._script = list(script)
        self.seen = []

    async def execute(self, stmt):
        self.seen.append(stmt)
        return self._script.pop(0)


def load_service_class():
    """抽出三个方法，挂到带假 session 的类上。"""
    tree = ast.parse(open(SRC, encoding="utf-8").read())
    picked = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "MaterialSyncService"
    ]
    assert picked, "没找到 MaterialSyncService 类"
    methods = [
        node for node in picked[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in WANT_METHODS
    ]
    assert len(methods) == len(WANT_METHODS), f"应抽出 {len(WANT_METHODS)} 个方法"
    ns = {
        "select": fake_select,
        "func": FakeFunc(),
        "XYCatalogItem": FakeTable("xy_catalog_items"),
        "ProductMaterial": FakeTable("xy_product_materials"),
    }
    mod = ast.Module(
        body=[
            # 与原模块一致：注解不求值，省去往命名空间塞 typing 对象
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *methods,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试

    class FakeService:
        pass

    for name in WANT_METHODS:
        setattr(FakeService, name, ns[name])

    async def _no_backfill(self, user_id):
        return 0

    FakeService.backfill_source_item_id = _no_backfill
    return FakeService


# ---------- 用例 ----------

def test_missing_stmt_account_filter():
    print("[1] _missing_stmt：account_pk 条件只在传入时出现")
    service = load_service_class()()

    stmt_all = service._missing_stmt(user_id=1, owner_scope=1)
    check(
        "不传 account_pk 时不含账号条件（默认行为不变）",
        not stmt_all.has_cond("xy_catalog_items", "account_pk", 7)
        and not any(c[2] == "account_pk" for c in stmt_all.conditions),
    )

    stmt_one = service._missing_stmt(user_id=1, owner_scope=1, account_pk=7)
    check(
        "传入 account_pk=7 时 WHERE 含 account_pk == 7",
        stmt_one.has_cond("xy_catalog_items", "account_pk", 7),
    )
    check(
        "owner 过滤仍在（账号筛选不越权）",
        stmt_one.has_cond("xy_catalog_items", "owner_id", 1),
    )


def test_count_missing_account_filter():
    print("[2] count_missing：account_pk 进入同一条统计语句")
    session = FakeSession(script=[FakeResult(scalar=3)])
    service = load_service_class()()
    service.session = session
    got = asyncio.run(service.count_missing(user_id=1, owner_scope=1, account_pk=7))
    stmt = session.seen[0]
    check("返回值取自查询结果", got == 3)
    check(
        "统计语句带 account_pk 条件（remaining 与筛选同范围的前提）",
        stmt.has_cond("xy_catalog_items", "account_pk", 7),
    )


def test_preview_scope_semantics():
    print("[3] preview：by_account 全量分项，missing 按选中账号收窄")
    rows = [
        FakeRow(account_pk=3), FakeRow(account_pk=3),
        FakeRow(account_pk=7),
        FakeRow(account_pk=9),
    ]
    session = FakeSession(script=[FakeResult(rows=rows), FakeResult(scalar=100)])
    service = load_service_class()()
    service.session = session

    data_all = asyncio.run(service.preview(user_id=1, owner_scope=1))
    check(
        "不传 account_pk：missing = 全部缺口",
        data_all["missing"] == 4,
        f"got {data_all['missing']}",
    )
    check(
        "by_account 按账号分项且为全量",
        data_all["by_account"] == {"3": 2, "7": 1, "9": 1},
        f"got {data_all['by_account']}",
    )
    check("pooled 仍统计素材池条数", data_all["pooled"] == 100)

    session2 = FakeSession(script=[FakeResult(rows=rows), FakeResult(scalar=100)])
    service2 = load_service_class()()
    service2.session = session2
    data_one = asyncio.run(service2.preview(user_id=1, owner_scope=1, account_pk=7))
    check(
        "传入 account_pk=7：missing 收窄为该账号缺口",
        data_one["missing"] == 1,
        f"got {data_one['missing']}",
    )
    check(
        "by_account 仍是全量（前端下拉要显示每个账号各差多少）",
        data_one["by_account"] == {"3": 2, "7": 1, "9": 1},
        f"got {data_one['by_account']}",
    )
    check(
        "预览第一条查询不带账号条件（全量拉回来再收窄）",
        not any(
            c[2] == "account_pk" for c in session2.seen[0].conditions
        ),
    )

    session3 = FakeSession(script=[FakeResult(rows=rows), FakeResult(scalar=100)])
    service3 = load_service_class()()
    service3.session = session3
    data_absent = asyncio.run(service3.preview(user_id=1, owner_scope=1, account_pk=999))
    check(
        "选中一个零缺口的账号：missing = 0（前端据此提示无需同步）",
        data_absent["missing"] == 0,
        f"got {data_absent['missing']}",
    )


def _calls_with_keyword(func_node, names, keyword, *, want):
    """检查函数体内对 names 方法的调用。

    want=True：返回**没带** keyword 的调用（用于断言"必须带"）；
    want=False：返回**带了** keyword 的调用（用于断言"必须不带"）。
    """
    bad = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr in names):
            continue
        has = any(k.arg == keyword for k in node.keywords)
        if has != want:
            bad.append((f.attr, node.lineno))
    return bad


def test_sync_batch_passes_account_pk():
    print("[4] 契约：sync_batch 内每个差集调用都带 account_pk")
    tree = ast.parse(open(SRC, encoding="utf-8").read())
    cls = next(
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "MaterialSyncService"
    )
    sync_batch = next(
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "sync_batch"
    )
    bad = _calls_with_keyword(
        sync_batch, {"count_missing", "_missing_stmt"}, "account_pk", want=True
    )
    check(
        "sync_batch 的 count_missing / _missing_stmt 全部带 account_pk"
        "（total_missing 与 remaining 必须与 rows 同范围，否则前端循环空转）",
        not bad,
        f"缺失调用: {bad}",
    )

    preview = next(
        n for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "preview"
    )
    bad_preview = _calls_with_keyword(
        preview, {"_missing_stmt"}, "account_pk", want=False
    )
    check(
        "preview 的 _missing_stmt 故意不带 account_pk（by_account 要全量）",
        not bad_preview,
        f"意外传参: {bad_preview}",
    )


def test_route_and_frontend_wired():
    print("[5] 契约：路由与前端参数已接通")
    route_src = open(ROUTES, encoding="utf-8").read()
    route_tree = ast.parse(route_src)

    req_cls = next(
        n for n in ast.walk(route_tree)
        if isinstance(n, ast.ClassDef) and n.name == "MaterialSyncRequest"
    )
    fields = [
        n.target.id for n in req_cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    ]
    check("MaterialSyncRequest 有 account_pk 字段", "account_pk" in fields, f"got {fields}")

    preview_route = next(
        n for n in ast.walk(route_tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "preview_material_sync"
    )
    args = [a.arg for a in preview_route.args.args + preview_route.args.kwonlyargs]
    check("sync-preview 路由签名有 account_pk", "account_pk" in args, f"got {args}")

    sync_route = next(
        n for n in ast.walk(route_tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "sync_materials_from_items"
    )
    src = ast.get_source_segment(route_src, sync_route) or ""
    check(
        "sync-from-items 路由把 req.account_pk 透传给 service",
        "account_pk=req.account_pk" in src,
    )

    api_src = open(API_TS, encoding="utf-8").read()
    check(
        "前端 api：getMaterialSyncPreview 支持 accountPk",
        "accountPk" in api_src.split("getMaterialSyncPreview")[1].split("*/")[0]
        or "getMaterialSyncPreview = (\n  accountPk?: number" in api_src,
    )
    check(
        "前端 api：syncMaterialsFromItems 支持 accountPk",
        "accountPk" in (api_src.split("export const syncMaterialsFromItems")[1].split(")")[0]),
    )

    page_src = open(PAGE_TSX, encoding="utf-8").read()
    check("前端页面：有 syncAccountPk 状态", "syncAccountPk" in page_src)
    check("前端页面：同步调用带上账号参数", "getMaterialSyncPreview(accountPk)" in page_src)
    check(
        "前端页面：分批同步带上账号参数",
        "syncMaterialsFromItems(undefined, accountPk)" in page_src,
    )
    check("前端页面：账号下拉有「所有账号」选项", "<option value=\"\">所有账号</option>" in page_src)


def main():
    test_missing_stmt_account_filter()
    test_count_missing_account_filter()
    test_preview_scope_semantics()
    test_sync_batch_passes_account_pk()
    test_route_and_frontend_wired()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
