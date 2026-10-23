"""单元测试：「从商品同步」与素材列表按账号筛选（account_pk）。

覆盖两层：
1. 行为层：AST 抽出 _missing_stmt / count_missing / preview / list_materials，
   注入假 SQLAlchemy 符号后真实执行，验证 account_pk 条件进出 WHERE 的时机、
   preview 的「by_account 全量分项 + missing 按选中账号收窄」语义，以及
   list_materials 的「count 与 list 同范围 + source_item_id/remark 两条关联路」。
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

WANT_METHODS = {
    "_missing_stmt",
    "count_missing",
    "preview",
    "_pooled_source_ids",
    # 平台状态筛选（在售/已下架/已售罄）由 _missing_stmt / count_missing 共用
    "_platform_status_condition",
}

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

    def is_(self, value):
        return ("is", self.table, self.name, value)

    def not_in(self, sub):
        return ("not_in", self.table, self.name, sub)

    def __ne__(self, other):
        return ("ne", self.table, self.name, other)

    def __eq__(self, other):
        return ("eq", self.table, self.name, other)

    def in_(self, sub):
        return ("in", self.table, self.name, sub)

    def like(self, pattern):
        return ("like", self.table, self.name, pattern)

    def ilike(self, pattern):
        return ("ilike", self.table, self.name, pattern)

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

    def offset(self, n):
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def has_cond(self, table, column, value):
        # or_ 包装的条件形如 ("or", cond_a, cond_b)，递归展开
        for c in self.conditions:
            if c[0] == "or":
                for sub in c[1:]:
                    if isinstance(sub, tuple) and sub and sub[0] == "eq" \
                            and sub[1] == table and sub[2] == column and sub[3] == value:
                        return True
            elif c[0] == "eq" and c[1] == table and c[2] == column and c[3] == value:
                return True
        return False


def fake_select(*args):
    return FakeStmt()


def fake_or(*conds):
    return ("or", *conds)


def fake_desc(*args):
    return ("desc", args)


class FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


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
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        self.seen.append(stmt)
        return self._script.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


class FakeCatalogItemMeta(type):
    """让 FakeCatalogItem.account_pk 这类类级别访问也能得到假列。"""

    def __getattr__(cls, attr):
        return FakeColumn("xy_catalog_items", attr)


class FakeCatalogItem(metaclass=FakeCatalogItemMeta):
    """假商品库行：记录构造参数，属性可改。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.title = kwargs.get("title")
        self.price = kwargs.get("price")
        self.ai_prompt = kwargs.get("ai_prompt")


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


def load_material_list_service():
    """抽出 ProductMaterialService.list_materials，注入假符号后真实执行。"""
    path = os.path.join(
        REPO_ROOT, "backend-web", "app", "services", "product_publish_service.py"
    )
    tree = ast.parse(open(path, encoding="utf-8").read())
    picked = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProductMaterialService"
    ]
    assert picked, "没找到 ProductMaterialService 类"
    methods = [
        node for node in picked[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "list_materials"
    ]
    assert len(methods) == 1, "应抽出 list_materials 一个方法"
    ns = {
        "select": fake_select,
        "func": FakeFunc(),
        "desc": fake_desc,
        "or_": fake_or,
        "ProductMaterial": FakeTable("xy_product_materials"),
        "XYCatalogItem": FakeTable("xy_catalog_items"),
        "_material_to_dict": lambda row: {"id": 1, "title": "x"},
    }
    mod = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *methods,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试

    class FakeService:
        pass

    FakeService.list_materials = ns["list_materials"]
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


def _account_conds(stmt):
    """挑出账号筛选相关的条件：or_ 包装的子查询 / like 两种。"""
    found = []
    for c in stmt.conditions:
        if c[0] == "or":
            for sub in c[1:]:
                if sub[0] in ("in", "like") and sub[2] in ("source_item_id", "remark"):
                    found.append(sub)
        elif c[0] in ("in", "like") and c[2] in ("source_item_id", "remark"):
            found.append(c)
    return found


def test_list_materials_account_filter():
    print("[3.5] list_materials：素材列表按账号筛选，count 与 list 同范围")
    # 第一次 execute 是 count，第二次是分页 list
    session = FakeSession(script=[FakeResult(scalar=2), FakeResult(rows=[FakeRow(7)])])
    service = load_material_list_service()()
    service.session = session

    data = asyncio.run(service.list_materials(user_id=1, account_pk=7))
    check("account_pk=7 时返回结构完整", data["total"] == 2 and len(data["list"]) == 1)

    count_stmt, list_stmt = session.seen[0], session.seen[1]
    count_conds = _account_conds(count_stmt)
    list_conds = _account_conds(list_stmt)
    check("count 语句带账号筛选条件（total 与列表同范围）", len(count_conds) >= 1, f"got {count_stmt.conditions}")
    check("list 语句带账号筛选条件", len(list_conds) >= 1, f"got {list_stmt.conditions}")
    check(
        "账号条件走 source_item_id 子查询 + remark 兜底两条路",
        any(c[0] == "in" and c[2] == "source_item_id" for c in list_conds)
        and any(c[0] == "like" and c[2] == "remark" for c in list_conds),
        f"got {list_conds}",
    )
    like_conds = [c for c in list_conds if c[0] == "like"]
    check(
        "remark 兜底 LIKE 片段以 int() 后的账号主键拼接（杜绝注入）",
        like_conds and like_conds[0][3] == "% acc=7",
        f"got {like_conds}",
    )

    session_all = FakeSession(script=[FakeResult(scalar=9), FakeResult(rows=[])])
    service_all = load_material_list_service()()
    service_all.session = session_all
    asyncio.run(service_all.list_materials(user_id=1))
    check(
        "不传 account_pk 时无任何账号条件（默认行为不变）",
        not _account_conds(session_all.seen[0]) and not _account_conds(session_all.seen[1]),
    )


def load_import_catalog_method(rows=None):
    """抽出 account_import_service 的 _import_catalog_items 与 _parse_str，
    以及 material_sync_service 的 clean_platform_title（真函数），注入假符号。

    rows: 自定义「商品目录」sheet 行；默认用线上实测样例。
    """
    import_path = os.path.join(
        REPO_ROOT, "backend-web", "app", "services", "account_import_service.py"
    )
    tree = ast.parse(open(import_path, encoding="utf-8").read())

    def pick(*names):
        out = []
        # _import_catalog_items 是类内方法，_parse_str 是模块级函数，都要递归找
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                out.append(node)
        return out

    methods = pick("_import_catalog_items", "_parse_str")
    assert len(methods) == 2, f"应抽出 2 个函数，实得 {[m.name for m in methods]}"

    # clean_platform_title 用真身（纯函数，只依赖 str）
    sync_tree = ast.parse(open(SRC, encoding="utf-8").read())
    clean_fn = next(
        n for n in sync_tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "clean_platform_title"
    )

    default_rows = [
        # 带 ||| 截断标记的标题（线上实测样式）
        {"账号ID": "A1", "商品ID": "1001", "标题": "雷神加速器99小时兑换码兑换，拍下自动发您兑换吗|||", "价格": "9.9", "AI提示词": ""},
        # 干净标题原样保留
        {"账号ID": "A1", "商品ID": "1002", "标题": "全季酒店优惠券100元", "价格": "50", "AI提示词": ""},
        # 账号不在映射里，整行跳过
        {"账号ID": "NOPE", "商品ID": "1003", "标题": "x|||", "价格": "1", "AI提示词": ""},
    ]

    def fake_read_sheet_rows(wb, sheet):
        assert sheet == "商品目录"
        return default_rows if rows is None else rows

    ns = {
        "select": fake_select,
        "XYCatalogItem": FakeCatalogItem,
        "_read_sheet_rows": fake_read_sheet_rows,
        "get_beijing_now_naive": lambda: "2026-10-18 12:00:00",
        "Any": object,  # 注解不求值，占位即可
    }
    mod = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *methods,
            clean_fn,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(mod)
    exec(compile(mod, "<extract>", "exec"), ns)  # noqa: S102 - 仅本地测试

    class FakeImportService:
        pass

    FakeImportService._import_catalog_items = ns["_import_catalog_items"]
    return FakeImportService


def test_import_catalog_title_cleaning():
    print("[6] 账号导入：商品库标题入库前剥掉 |||（治本，两条链路口径一致）")
    service = load_import_catalog_method()()
    service.owner_id = 1
    service._account_id_to_pk = {"A1": 7}
    session = FakeSession(script=[FakeResult(rows=[])] * 3)
    service.session = session

    asyncio.run(service._import_catalog_items(wb=None))

    added = session.added
    check("只导入账号映射命中的 2 行", len(added) == 2, f"got {len(added)}")
    by_item = {i.kwargs["item_id"]: i for i in added}
    check(
        "带 ||| 的标题入库时被剥掉（线上实测样例）",
        by_item["1001"].title == "雷神加速器99小时兑换码兑换，拍下自动发您兑换吗",
        f"got {by_item['1001'].title!r}",
    )
    check(
        "干净标题原样入库，不做任何改动",
        by_item["1002"].title == "全季酒店优惠券100元",
        f"got {by_item['1002'].title!r}",
    )
    check("一次 commit 收尾", session.commits == 1)

    # 更新路径：已有行的 title 被新导入的干净标题覆盖
    existing = FakeCatalogItem(title="旧标题|||尾巴", price="1", ai_prompt="p")
    session2 = FakeSession(script=[FakeResult(rows=[existing]), FakeResult(rows=[])])
    service2 = load_import_catalog_method()()
    service2.owner_id = 1
    service2._account_id_to_pk = {"A1": 7}
    service2.session = session2
    asyncio.run(service2._import_catalog_items(wb=None))
    check(
        "更新路径同样清洗（旧脏标题被覆盖为干净标题）",
        existing.title == "雷神加速器99小时兑换码兑换，拍下自动发您兑换吗",
        f"got {existing.title!r}",
    )

    # 更新路径：新标题只有 ||| 尾巴 → 清洗后为空 → 保留旧值，不用空串覆盖
    existing2 = FakeCatalogItem(title="旧标题", price="1", ai_prompt="p")
    session3 = FakeSession(script=[FakeResult(rows=[existing2])] * 2)
    service3 = load_import_catalog_method(
        rows=[{"账号ID": "A1", "商品ID": "1001", "标题": "|||", "价格": "1", "AI提示词": ""}]
    )()
    service3.owner_id = 1
    service3._account_id_to_pk = {"A1": 7}
    service3.session = session3
    asyncio.run(service3._import_catalog_items(wb=None))
    check(
        "清洗后为空的标题保留旧值（不把商品标题抹成空）",
        existing2.title == "旧标题",
        f"got {existing2.title!r}",
    )

    # 契约：导入服务确实引用了同一个清洗函数
    import_src = open(
        os.path.join(REPO_ROOT, "backend-web", "app", "services", "account_import_service.py"),
        encoding="utf-8",
    ).read()
    check(
        "account_import_service 从 material_sync_service 导入 clean_platform_title",
        "from app.services.material_sync_service import clean_platform_title" in import_src,
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

    list_route = next(
        n for n in ast.walk(route_tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "list_materials"
    )
    list_args = [a.arg for a in list_route.args.args + list_route.args.kwonlyargs]
    check("素材列表路由签名有 account_pk", "account_pk" in list_args, f"got {list_args}")
    list_src = ast.get_source_segment(route_src, list_route) or ""
    check(
        "素材列表路由把 account_pk 透传给 service",
        "account_pk=account_pk" in list_src,
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
    get_materials_sig = api_src.split("export const getMaterials")[1].split("): Promise")[0]
    check(
        "前端 api：getMaterials 的 filters 支持 account_pk",
        "account_pk?: number" in get_materials_sig,
        f"got {get_materials_sig}",
    )

    page_src = open(PAGE_TSX, encoding="utf-8").read()
    check("前端页面：有 accountPk 状态", "const [accountPk, setAccountPk]" in page_src)
    check(
        "前端页面：列表筛选带上 account_pk",
        "filters.account_pk = accountPk" in page_src,
    )
    check(
        "前端页面：账号变化触发重新拉列表（依赖数组含 accountPk）",
        "[page, pageSize, accountPk]" in page_src,
    )
    check(
        "前端页面：下拉选中即回到第 1 页（不等「查询」按钮）",
        "setPage(1)" in page_src.split("value={accountPk == null")[1].split("</select>")[0],
    )
    # 同步已改为服务端任务制（旧的「前端预览 + 分批循环」调用已移除），
    # 账号与平台状态都随任务创建请求一起提交
    check(
        "前端页面：同步任务带上账号参数",
        "startMaterialSyncTask(accountPk ?? undefined" in page_src,
    )
    check(
        "前端页面：同步任务带上所选平台状态（在售/已下架/已售罄）",
        "startMaterialSyncTask(accountPk ?? undefined, syncPlatformStatus)" in page_src,
    )
    check(
        "前端 api：同步任务请求体带 account_pk 与 platform_status",
        "account_pk: accountPk ?? null" in api_src
        and "platform_status: platformStatus" in api_src,
    )
    check("前端页面：账号下拉有「所有账号」选项", "<option value=\"\">所有账号</option>" in page_src)
    check(
        "前端页面：重置筛选会清空账号",
        "setAccountPk(null)" in page_src,
    )


def main():
    test_missing_stmt_account_filter()
    test_count_missing_account_filter()
    test_preview_scope_semantics()
    test_list_materials_account_filter()
    test_import_catalog_title_cleaning()
    test_sync_batch_passes_account_pk()
    test_route_and_frontend_wired()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
