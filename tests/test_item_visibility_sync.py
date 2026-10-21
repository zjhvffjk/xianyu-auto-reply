"""商品数量与账号在售一致（同步后标记失效）测试

背景：商品管理的「获取商品」只做新增/更新，从不清理平台已不可见的商品，
导致本地数量比账号实际在售多（实测芋圆奶茶：平台 4 个，本地 5 个，多出一条
重复发布的旧 item_id）。用户要求点击获取商品后，数量与账号发布的一致。

实现要点（本测试重点锁住）：
1. 平台接口只返回「在售」，所以「未出现」可能是删除也可能是临时下架，
   实现只打失效标记、不删数据 —— 重新上架时配置与卡券关联都还在
2. 只有完整翻到列表末尾才允许标记；提前停止（整页已存在 / 页数上限）
   时平台列表并不完整，据此标记会把没翻到的商品误判为已失效
3. 列表、总数、待选商品（含全选）默认排除已失效商品；商品管理保留
   「含已下架商品」开关，随时能看回来

覆盖三层：
1. 纯函数：直接执行后端源码里的 _compute_visibility_changes（ast 提取 + exec，
   不依赖 sqlalchemy 安装），验证隐藏/恢复的判定
2. 后端契约：全量同步的完整性判定、标记写入、查询过滤、接口参数
3. 前端契约：筛选开关默认关、true 才传参、提示文案

仓库根直接 `python tests/test_item_visibility_sync.py` 可跑。
"""

import ast
import os
import sys
import textwrap

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEM_SERVICE = os.path.join(REPO_ROOT, "common", "services", "item_service.py")
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
    # item_service.py 带 UTF-8 BOM（历史遗留），统一用 utf-8-sig 读取
    with open(path, "r", encoding="utf-8-sig") as handle:
        return handle.read()


def load_pure_visibility():
    """从后端源码里取出 _compute_visibility_changes 并编译执行

    该方法纯数据判定，不碰 session / ORM，可直接在无 sqlalchemy 环境下测行为。
    源码使用 `from __future__ import annotations`，单独编译时需补同样声明。
    """
    source = read(ITEM_SERVICE)
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "ItemService":
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "_compute_visibility_changes":
                segment = textwrap.dedent(ast.get_source_segment(source, item) or "")
                code = "from __future__ import annotations\n" + segment
                namespace = {}
                exec(compile(code, "<item_service>", "exec"), namespace)
                func = namespace["_compute_visibility_changes"]
                return func.__func__ if isinstance(func, staticmethod) else func
    raise AssertionError("未找到 _compute_visibility_changes")


# ---------- 1. 纯函数行为 ----------

def test_visibility_behavior():
    print("\n[1] 行为：失效标记的隐藏与恢复")
    compute = load_pure_visibility()

    # 平台在售 A、B；本地 A、B、C → C 应被隐藏
    result = compute([("A", False), ("B", False), ("C", False)], {"A", "B"})
    check("平台未返回的商品被隐藏", result["to_unlist"] == ["C"])
    check("平台仍在售的不动", result["to_restore"] == [])

    # 之前隐藏过的 C 重新出现 → 应恢复
    result = compute([("A", False), ("C", True)], {"A", "C"})
    check("重新上架的商品被恢复", result["to_restore"] == ["C"])
    check("恢复时不重复隐藏", result["to_unlist"] == [])

    # 已隐藏且仍未出现 → 不重复处理（避免每次同步都写库）
    result = compute([("C", True)], {"A"})
    check("已隐藏且仍未上架的不重复标记",
          result["to_unlist"] == [] and result["to_restore"] == [])

    # 全都在售 → 无变化
    result = compute([("A", False), ("B", False)], {"A", "B"})
    check("全部在售时无任何变更",
          result["to_unlist"] == [] and result["to_restore"] == [])

    # 本地为空 → 无变化（新建账号首次同步）
    result = compute([], {"A"})
    check("本地无记录时无变更",
          result["to_unlist"] == [] and result["to_restore"] == [])

    # 平台多出本地还没有的商品 → 不产生恢复（交给 upsert 新增）
    result = compute([("A", False)], {"A", "B"})
    check("平台新增商品不进入恢复列表", result["to_restore"] == [])


# ---------- 2. 后端契约 ----------

def test_backend_contract():
    print("\n[2] 后端：同步完整性与查询过滤")
    service = read(ITEM_SERVICE)
    route = read(ITEMS_ROUTE)
    selectable = read(SELECTABLE_SERVICE)

    check("失效标记存在 metadata（不加表字段）",
          'UNLISTED_META_KEY = "unlisted_at"' in service)
    check("完整翻到末尾才标记（无数据页）",
          "list_walked_to_end = True" in service)
    check("标记前置条件包含完整性判断",
          "if list_walked_to_end and fetched_item_ids:" in service)
    check("标记失败不影响本次同步结果",
          "商品失效标记更新失败（不影响本次同步）" in service)
    check("标记只处理本账号商品（多租户边界）",
          "XYCatalogItem.owner_id == account.owner_id" in service
          and "XYCatalogItem.account_pk == account.id" in service)
    check("商品重新出现时清除标记",
          "metadata_json.pop(UNLISTED_META_KEY, None)" in service)
    check("分页列表支持 include_unlisted", "include_unlisted: bool = False" in service)
    check("默认只返回在售（条件取反）",
          "if not include_unlisted:" in service)
    check("列表与总数共用同一条件",
          "conditions.append(self._not_unlisted_condition())" in service)
    check("接口暴露 include_unlisted 参数",
          "include_unlisted: bool = Query(default=False" in route)
    check("接口把参数传给服务", "include_unlisted=include_unlisted," in route)
    check("待选商品排除已失效（全选不会选中）",
          "XYCatalogItem.metadata_json[UNLISTED_META_KEY].is_(None)" in selectable)


# ---------- 3. 前端契约 ----------

def test_frontend_contract():
    print("\n[3] 前端：默认只看在售 + 可查看已下架")
    tsx = read(ITEMS_TSX)
    api = read(ITEMS_API_TS)

    check("筛选参数支持 include_unlisted", "include_unlisted?: boolean | null" in api)
    check("默认不传参（后端只返回在售）",
          "if (filters.include_unlisted) {" in api)
    check("筛选默认为空", "include_unlisted: null," in tsx)
    check("提供商品状态下拉", "商品状态" in tsx)
    check("下拉默认「在售（数量与账号一致）」",
          "在售（数量与账号一致）" in tsx)
    check("下拉可切换「含已下架商品」", "含已下架商品" in tsx)
    check("获取成功后提示隐藏数量",
          "隐藏 ${unlistedCount} 个平台已下架商品" in tsx)


def main():
    print("=" * 60)
    print("商品数量与账号在售一致 · 测试")
    print("=" * 60)
    test_visibility_behavior()
    test_backend_contract()
    test_frontend_contract()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
