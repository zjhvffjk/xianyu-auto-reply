"""卡券关联商品弹窗按店铺过滤测试

背景：卡券管理页顶部「选择店铺」此前只是个摆设——切换后「关联商品」弹窗仍把
所有店铺的商品都列出来，用户无法只在本店范围内挑商品。本次让店铺选择成为
弹窗的筛选上下文（左侧待选、搜索、滚动加载、全选、右侧已选都限定本店）。

关键约束（本测试重点锁住）：
1. 未选择店铺时不做任何过滤 —— 行为与改造前完全一致
2. 保存接口是「全量覆盖」语义 —— 选中集合必须保留其他店铺的 ID，
   否则在本店保存一次会把别店的关联全部删掉
3. 归属未知的已选（商品记录已删除的孤儿关联）必须保留展示，否则看不到也移除不掉

覆盖三层：
1. 纯函数行为：直接执行后端源码里的 _aggregate_rows（ast 提取 + exec，
   不依赖 sqlalchemy 安装），验证同商品多店铺的账号合并与去重
2. 后端契约：selectable/all 的可选 cookie_id 参数、按账号过滤条件、
   by-card 返回 account_ids
3. 前端契约：页面把当前店铺传入弹窗；三处请求都带店铺；右侧过滤保留孤儿项；
   保存仍写全量集合

仓库根直接 `python tests/test_card_item_shop_filter.py` 可跑。
"""

import ast
import os
import sys
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(REPO_ROOT, "backend-web", "app")
ITEMS_ROUTE = os.path.join(BACKEND, "api", "routes", "items.py")
SELECTABLE_SERVICE = os.path.join(BACKEND, "services", "selectable_item_service.py")
FRONTEND_SRC = os.path.join(REPO_ROOT, "frontend", "src")
CARDS_TSX = os.path.join(FRONTEND_SRC, "pages", "cards", "Cards.tsx")
RELATION_MODAL_TSX = os.path.join(FRONTEND_SRC, "pages", "cards", "CardItemRelationModal.tsx")
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
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_pure_aggregate():
    """从后端源码里取出 _aggregate_rows 静态方法并编译执行

    该方法只做纯数据聚合（不碰 session / 模型），因此可在无 sqlalchemy 的环境
    下直接测行为。源码文件使用 `from __future__ import annotations`，注解不在
    运行期求值；单独编译该函数时需补同样的 future 声明，否则注解里的
    List/Dict/Any 会被立即求值。
    """
    source = read(SELECTABLE_SERVICE)
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "SelectableItemService":
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "_aggregate_rows":
                segment = textwrap.dedent(ast.get_source_segment(source, item) or "")
                code = "from __future__ import annotations\n" + segment
                namespace = {}
                exec(compile(code, "<selectable_item_service>", "exec"), namespace)
                func = namespace["_aggregate_rows"]
                return func.__func__ if isinstance(func, staticmethod) else func
    raise AssertionError("未找到 _aggregate_rows")


# ---------- 1. 纯函数行为 ----------

def test_aggregate_behavior():
    print("\n[1] 行为：已关联商品按账号聚合")
    aggregate = load_pure_aggregate()

    # 两个店铺各一个商品
    rows = [
        ("111", "商品A", "10.00", "shopA"),
        ("222", "商品B", "20.00", "shopB"),
    ]
    result = {item["item_id"]: item for item in aggregate(rows)}
    check("不同商品各自保留", set(result) == {"111", "222"})
    check("商品归属账号正确", result["111"]["account_ids"] == ["shopA"])
    check("另一个商品归属账号正确", result["222"]["account_ids"] == ["shopB"])

    # 同一商品挂两个店铺（历史重复记录）
    rows = [
        ("333", "商品C", "30.00", "shopA"),
        ("333", "商品C", "30.00", "shopB"),
    ]
    result = aggregate(rows)
    check("同一商品多店铺合并为一条", len(result) == 1)
    check("合并后账号取并集", result[0]["account_ids"] == ["shopA", "shopB"])

    # 同一店铺重复行
    rows = [("444", "商品D", None, "shopA"), ("444", "商品D", None, "shopA")]
    result = aggregate(rows)
    check("同店铺重复行账号去重", result[0]["account_ids"] == ["shopA"])

    # 账号缺失（商品记录的账号已删除）
    rows = [("555", "商品E", "50.00", None)]
    result = aggregate(rows)
    check("账号缺失时 account_ids 为空", result[0]["account_ids"] == [])

    # 脏数据：item_id 为空
    rows = [(None, "脏数据", "0", "shopA"), ("666", "商品F", "60.00", "shopA")]
    result = aggregate(rows)
    check("item_id 为空的行被跳过", [item["item_id"] for item in result] == ["666"])

    check("空输入返回空列表", aggregate([]) == [])


# ---------- 2. 后端契约 ----------

def test_backend_contract():
    print("\n[2] 后端：可选商品接口支持店铺维度")
    route_src = read(ITEMS_ROUTE)
    service_src = read(SELECTABLE_SERVICE)

    check("selectable/all 声明可选 cookie_id 参数",
          'cookie_id: str | None = Query(default=None' in route_src)
    check("selectable/all 把 cookie_id 传入服务",
          "cookie_id=cookie_id," in route_src)
    check("服务按账号ID过滤商品",
          "XYAccount.account_id == cookie_id" in service_src)
    check("过滤仅在传了账号时生效（不传=全部，保持原行为）",
          "if cookie_id:" in service_src)
    check("服务关联账号表取所属店铺",
          "XYAccount.account_id," in service_src
          and "outerjoin(XYAccount" in service_src)
    check("by-card 返回 account_ids",
          '"account_ids": []' in service_src)
    check("账号列表与商品去重后账号取并集",
          'if account_id and account_id not in entry["account_ids"]' in service_src)


# ---------- 3. 前端契约 ----------

def test_frontend_contract():
    print("\n[3] 前端：弹窗按当前店铺过滤")
    modal = read(RELATION_MODAL_TSX)
    cards = read(CARDS_TSX)
    api = read(ITEMS_API_TS)

    # 页面 → 弹窗
    check("卡券页读取当前店铺", "useShopStore()" in cards)
    check("卡券页把店铺ID传给弹窗", "accountId={currentAccountId}" in cards)
    check("卡券页把店铺名传给弹窗", "accountLabel={currentAccountLabel}" in cards)

    # 弹窗 → 接口
    check("弹窗接收店铺参数", "accountId?: string | null" in modal)
    check("左侧第一页按店铺拉取",
          "getItemsPaginated(1, REQUEST_PAGE_SIZE, accountId || undefined" in modal)
    check("滚动加载更多按店铺拉取",
          "getItemsPaginated(nextPage, REQUEST_PAGE_SIZE, accountId || undefined" in modal)
    check("全选按店铺拉取",
          "getAllSelectableItemKeys(appliedSearch, accountId || undefined)" in modal)
    check("未选店铺时不加店铺条件（undefined 即全量）",
          modal.count("accountId || undefined") == 3)

    # 右侧已选过滤
    check("右侧按店铺过滤已选",
          "item.accountIds.length === 0 || item.accountIds.includes(accountId)" in modal)
    check("未选店铺时右侧不过滤",
          "if (!accountId) return allSelectedItems" in modal)
    check("右侧计数用本店口径", "{shopSelectedItems.length} 个" in modal)

    # 数据安全：保存仍是全量集合
    check("保存写全量选中集合（不因过滤丢别店关联）",
          "updateCardItems(cardId, Array.from(selectedItemIds))" in modal)
    check("别店已选计数独立展示",
          "otherShopSelectedCount" in modal)

    # 接口层
    check("可选商品接口支持 cookie_id",
          "params.append('cookie_id', cookieId)" in api)


def main():
    print("=" * 60)
    print("卡券关联商品 · 按店铺过滤测试")
    print("=" * 60)
    test_aggregate_behavior()
    test_backend_contract()
    test_frontend_contract()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
