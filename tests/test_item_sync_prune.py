"""商品同步按平台状态清理 · 测试

背景：
1. 用户要求「获取商品」后，本地商品数量要与账号实际在售数量一致（实测芋圆奶茶：
   账号在售 4 个，本地 5 个）。
2. 但用户同时说明「大量下架囤货、以后再上架」是常态用法——下架商品如果直接删除，
   会连卡券关联、默认回复、AI 提示词一起丢掉。

实测鱼小铺卖家接口 mtop.alibaba.idle.seller.pc.common.item.search 在不传 itemStatus
时返回全部状态（芋圆奶茶实测 227 条）：
    itemStatus=-12 下架、-2 下架、-1 用户删除、0 在卖、1 售出
据此可以精确区分「下架囤货」与「用户真的删了」。

实现要点（本测试重点锁住）：
1. 抓取器不再写死 itemStatus="0"，默认拉全量，才能拿到状态
2. 只有「用户删除」和「全量列表里彻底没有」才从本地删除（连同卡券关联）
3. 下架 / 售出 / 在卖 一律保留，避免囤货商品丢配置
4. 个人版账号（只能拿到在售列表）无法区分状态，一律不清理，避免误删
5. 商品列表默认只显示在售，可切已下架/已售出/全部

仓库根直接 `python tests/test_item_sync_prune.py` 可跑。
"""

import ast
import os
import sys
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEM_SERVICE = os.path.join(REPO_ROOT, "common", "services", "item_service.py")
SELLER_CLIENT = os.path.join(REPO_ROOT, "common", "services", "xianyu_seller_item_client.py")
ITEM_INFO_MANAGER = os.path.join(REPO_ROOT, "common", "utils", "item_info_manager.py")
SELECTABLE_SERVICE = os.path.join(REPO_ROOT, "backend-web", "app", "services", "selectable_item_service.py")
ITEMS_ROUTE = os.path.join(REPO_ROOT, "backend-web", "app", "api", "routes", "items.py")
FRONTEND_SRC = os.path.join(REPO_ROOT, "frontend", "src")
ITEMS_TSX = os.path.join(FRONTEND_SRC, "pages", "items", "Items.tsx")
ITEMS_API_TS = os.path.join(FRONTEND_SRC, "api", "items.ts")

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


def read(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def _module_status_constants(source, tree):
    """取出 item_service 里 PLATFORM_STATUS_* 常量值，供纯函数执行时使用

    先收集纯字面量（如 PLATFORM_STATUS_ON_SALE），再解析引用它们的字典
    （如 PLATFORM_STATUS_CODE_MAP），保证抽取的纯函数能拿到完整命名空间。
    """
    constants = {}
    pending = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id.startswith("PLATFORM_STATUS_"):
            try:
                constants[target.id] = ast.literal_eval(node.value)
            except ValueError:
                pending.append((target.id, node.value))
    for name, value in pending:
        try:
            expression = compile(ast.Expression(value), "<const>", "eval")
            constants[name] = eval(expression, {}, dict(constants))
        except Exception:
            continue
    return constants


def load_pure_method(name, extra=None):
    """从后端源码里取出指定静态方法并编译执行（不依赖 sqlalchemy 安装）

    Args:
        name: 方法名
        extra: 额外注入的命名空间（如被测方法内部引用的其他方法）
    """
    source = read(ITEM_SERVICE)
    tree = ast.parse(source)
    constants = _module_status_constants(source, tree)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "ItemService":
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == name:
                segment = textwrap.dedent(ast.get_source_segment(source, item) or "")
                # 源码使用 `from __future__ import annotations`，单独编译需补同样声明
                code = "from __future__ import annotations\n" + segment
                namespace = dict(constants)
                if extra:
                    namespace.update(extra)
                exec(compile(code, "<item_service>", "exec"), namespace)
                func = namespace[name]
                return func.__func__ if isinstance(func, staticmethod) else func
    raise AssertionError(f"未找到 {name}")


def load_constants():
    source = read(ITEM_SERVICE)
    return _module_status_constants(source, ast.parse(source))


# ---------- 1. 平台状态归一 ----------

def test_resolve_status():
    print("\n[1] 行为：平台状态码 → 文案")
    resolve = load_pure_method("_resolve_platform_status")

    check("0 → 在卖", resolve(0, "") == "在卖")
    check("1 → 售出", resolve(1, "") == "售出")
    check("-1 → 用户删除", resolve(-1, "") == "用户删除")
    check("-2 → 下架", resolve(-2, "") == "下架")
    check("-12 → 下架", resolve(-12, "") == "下架")
    check("-4 → 违规", resolve(-4, "") == "违规")
    check("-9 等未知码不再被当成在售", resolve(-9, "") == "")
    check("平台给了文案时优先用文案", resolve(-2, "下架") == "下架")
    check("字符串状态码也能识别", resolve("1", None) == "售出")
    check("未知状态码返回空串", resolve(999, "") == "")
    check("缺字段不报错", resolve(None, None) == "")


# ---------- 2. 待删集合 ----------

def test_purge_behavior():
    print("\n[2] 行为：该删哪些商品（下架必须保留）")
    compute = load_pure_method("_compute_purge_item_ids")

    platform = {
        "ON_SALE": "在卖",
        "OFF_SHELF": "下架",
        "SOLD": "售出",
        "DELETED": "用户删除",
    }
    local = ["ON_SALE", "OFF_SHELF", "SOLD", "DELETED", "GONE"]

    result = compute(local, platform)
    check("用户删除的会被删掉", "DELETED" in result)
    check("平台彻底没有的会被删掉", "GONE" in result)
    check("下架商品不会被删（囤货配置要保留）", "OFF_SHELF" not in result)
    check("售出商品不会被删", "SOLD" not in result)
    check("在卖商品不会被删", "ON_SALE" not in result)
    check("只删这两个，其余全留", result == ["DELETED", "GONE"])
    check("保持本地原始顺序", compute(["DELETED", "GONE"], platform) == ["DELETED", "GONE"])

    check("全部下架时一个都不删",
          compute(["A", "B"], {"A": "下架", "B": "下架"}) == [])
    check("本地为空时不删任何东西", compute([], platform) == [])
    check("平台无数据时全部待删（调用方另有非空保护）",
          compute(["A", "B"], {}) == ["A", "B"])


# ---------- 3. 状态筛选值归一 ----------

def test_filter_normalize():
    print("\n[3] 行为：列表状态筛选值")
    normalize = load_pure_method("_normalize_platform_status_filter")

    check("on_sale → on_sale", normalize("on_sale") == "on_sale")
    check("off_shelf → off_shelf", normalize("off_shelf") == "off_shelf")
    check("sold → sold", normalize("sold") == "sold")
    check("all → all", normalize("all") == "all")
    check("空值 → all（不过滤）", normalize("") == "all")
    check("None → all", normalize(None) == "all")
    check("大小写不敏感", normalize("OFF_SHELF") == "off_shelf")
    check("未知值按在售处理（安全默认）", normalize("whatever") == "on_sale")


# ---------- 3.5 老数据状态兜底 ----------

def test_legacy_status_fallback():
    print("\n[3.5] 行为：老数据没有 platform_status 时从 detail 兜底")
    import json as _json

    resolve = load_pure_method("_resolve_platform_status")
    shim = type("ItemService", (), {"_resolve_platform_status": staticmethod(resolve)})
    from_detail = load_pure_method(
        "_resolve_status_from_detail", {"ItemService": shim, "json": _json}
    )

    check("有 platform_status 时优先用它",
          from_detail({"platform_status": "下架", "detail": '{"item_status": 0}'}) == "下架")
    check("detail 是字符串时能解析",
          from_detail({"detail": _json.dumps({"item_status": 0})}) == "在卖")
    check("detail 里 -4 识别为违规",
          from_detail({"detail": _json.dumps({"item_status": -4})}) == "违规")
    check("detail 里 -2 识别为下架",
          from_detail({"detail": _json.dumps({"item_status": -2})}) == "下架")
    check("detail 里 -9 之类未知码不当作在售",
          from_detail({"detail": _json.dumps({"item_status": -9})}) == "")
    check("detail 是 dict 时也能解析",
          from_detail({"detail": {"item_status": 1}}) == "售出")
    check("detail 缺失返回空串", from_detail({}) == "")
    check("detail 是坏 JSON 不报错", from_detail({"detail": "{oops"}) == "")
    check("metadata 为 None 不报错", from_detail(None) == "")

    service = read(ITEM_SERVICE)
    check("列表查询前会补齐历史状态", "await self._backfill_platform_status(owner_id)" in service)
    check("回填只处理缺失状态的老数据",
          'XYCatalogItem.metadata_json["platform_status"].as_string().is_(None)' in service)
    check("默认在售筛选是严格匹配（未知状态不算在售）",
          "return status_col == PLATFORM_STATUS_ON_SALE" in service)
    check("不再把空状态当作在售",
          "status_col.is_(None)" not in service.split("def _build_platform_status_condition")[1].split("def ")[0])


# ---------- 4. 抓取器契约 ----------

def test_fetcher_contract():
    print("\n[4] 抓取器：默认拉全量才能区分状态")
    seller = read(SELLER_CLIENT)
    personal = read(ITEM_INFO_MANAGER)

    check("卖家接口声明支持状态区分", "supports_status_filter = True" in seller)
    check("个人版声明不支持状态区分", "supports_status_filter = False" in personal)
    check("itemStatus 不再写死为在售",
          '"itemStatus": SELLER_ITEM_STATUS_ON_SALE,' not in seller)
    check("仅显式指定时才带 itemStatus", "if item_status is not None:" in seller)
    check("保留在售状态码常量", 'SELLER_ITEM_STATUS_ON_SALE = "0"' in seller)
    check("明确用户删除状态码", 'SELLER_ITEM_STATUS_USER_DELETED = "-1"' in seller)
    check("明确下架状态码（-2/-12）", 'SELLER_ITEM_STATUS_OFF_SHELF = ("-2", "-12")' in seller)
    check("个人版接口兼容同名参数", "item_status=None" in personal)


# ---------- 5. 后端契约 ----------

def test_backend_contract():
    print("\n[5] 后端：只删用户删除，下架保留")
    service = read(ITEM_SERVICE)
    route = read(ITEMS_ROUTE)
    selectable = read(SELECTABLE_SERVICE)

    check("同步后走状态感知清理",
          "removed_count = await self._purge_deleted_items(account, platform_status)" in service)
    check("个人版账号不清理（无法区分下架/删除）",
          "if can_detect_platform_status and list_walked_to_end and platform_status:" in service)
    check("删除前先清卡券关联",
          "matcher.batch_delete_relations_by_item_ids(purge_ids)" in service)
    check("使用数据库删除而非打标记",
          "delete(XYCatalogItem).where(" in service)
    check("删除范围限定本账号（多租户边界）",
          "XYCatalogItem.owner_id == account.owner_id" in service
          and "XYCatalogItem.account_pk == account.id" in service)
    check("只在完整翻完时清理", "list_walked_to_end = True" in service)
    check("清理失败不影响本次同步",
          "清理平台已删除商品失败（不影响本次同步）" in service)
    check("同步时记录平台状态", 'metadata_json["platform_status"] = platform_status' in service)
    check("用户删除的商品不写入本地库（避免每次写库再删）",
          "syncable_items = [" in service
          and "!= PLATFORM_STATUS_USER_DELETED" in service
          and "[entry for _, entry in syncable_items]" in service)
    check("序列化暴露平台状态（老数据从 detail 兜底）",
          '"platform_status": platform_status,' in service
          and "platform_status = self._resolve_status_from_detail(metadata)" in service)
    check("列表支持状态筛选参数", "platform_status=platform_status" in route)
    check("接口默认只看在售", 'default="on_sale"' in route)
    check("批量同步汇总删除数", '"removed_count": removed_count,' in service)
    check("批量同步汇总在售数", '"on_sale_count": on_sale_count,' in service)
    check("「全选」只选在售商品",
          'ItemService._build_platform_status_condition("on_sale")' in selectable)


# ---------- 6. 前端契约 ----------

def test_frontend_contract():
    print("\n[6] 前端：默认看在售，可切筛选")
    tsx = read(ITEMS_TSX)
    api = read(ITEMS_API_TS)

    check("默认筛选在售", "platform_status: 'on_sale'," in tsx)
    check("提供已下架选项", 'value="off_shelf"' in tsx)
    check("提供已售出选项", 'value="sold"' in tsx)
    check("提供全部选项", 'value="all"' in tsx)
    check("筛选状态列有颜色标签", "status === '在卖'" in tsx)
    check("重置回在售而不是清空",
          "platform_status: 'on_sale'," in tsx.split("handleResetFilters")[1])
    check("接口层传状态参数", "params.append('platform_status'" in api)
    check("获取提示用「在售」件数", "在售 ${onSaleCount} 件" in tsx)


def main():
    print("=" * 60)
    print("商品同步按平台状态清理 · 测试")
    print("=" * 60)
    test_resolve_status()
    test_purge_behavior()
    test_filter_normalize()
    test_legacy_status_fallback()
    test_fetcher_contract()
    test_backend_contract()
    test_frontend_contract()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
