"""素材同步「恢复用户删过的素材」· 测试

背景：
1. 用户反馈：商品管理页某账号显示 255 个在售，素材库同一账号只有 208 个。
2. 查库实证：该账号商品库 256 条全部进过素材池（缺口为 0），差的 47~48 条是
   历史上被用户从素材库删掉的（软删除）。旧设计「软删也算已存在，删过的不复活」，
   所以同步按钮永远补不回来。
3. 用户决定改设计（2026-10-22）：同步时把删过的素材恢复（is_deleted 置回 False），
   内容刷新为最新商品数据；未删除的已存在素材仍然不重建、不覆盖。

实现要点（本测试重点锁住）：
1. _pooled_source_ids 只算未删除的素材——软删的重新进入「缺失」差集
2. _revive_from 把新构造的内容整列搬到旧行：跳过主键/创建时间/更新时间，
   is_deleted 显式置回 False（等同删后重建，不产生同源重复行）
3. sync_batch 接线：构造前查软删行、写入前搬运、revived 计数进响应
4. _find_revive_target 的查询条件：同用户 + 同 source_item_id + is_deleted=True，
   取最新一行（同一源商品可能有多行软删记录）

仓库根直接 `python tests/test_material_sync_revive.py` 可跑。
"""

import ast
import asyncio
import os
import sys
import textwrap
from types import SimpleNamespace

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATERIAL_SYNC = os.path.join(
    REPO_ROOT, "backend-web", "app", "services", "material_sync_service.py"
)

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


# ---------- 桩对象：让 ORM 查询构造代码在无 sqlalchemy 环境下也能跑 ----------

class _Column:
    """列桩：把比较运算记录成元组，供断言查询条件。"""

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return ("eq", self.name, other)

    def is_not(self, value):
        return ("is_not", self.name, value)

    def is_(self, value):
        return ("is_", self.name, value)

    def desc(self):
        return ("desc", self.name)


class _SelectStub:
    """select 桩：记录 where/order_by/limit 调用。"""

    def __init__(self, *columns):
        self.columns = columns
        self.conditions = []
        self.order = None
        self.limit_value = None

    def where(self, condition):
        self.conditions.append(condition)
        return self

    def order_by(self, clause):
        self.order = clause
        return self

    def limit(self, count):
        self.limit_value = count
        return self


class _ResultStub:
    """execute 返回桩：scalars().first() 给出预定行。"""

    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _SessionStub:
    def __init__(self, row=None):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _ResultStub(self.row)


class _MaterialStub:
    """ProductMaterial 桩：列比较 + __table__.columns（供 _revive_from 遍历）。"""

    user_id = _Column("user_id")
    source_item_id = _Column("source_item_id")
    is_deleted = _Column("is_deleted")
    id = _Column("id")

    class __table__:  # noqa: N801 - 刻意模仿 SQLAlchemy 的表元数据属性名
        columns = [
            SimpleNamespace(name=name)
            for name in (
                "id", "user_id", "title", "description", "price", "images",
                "remark", "source_item_id", "is_deleted", "created_at", "updated_at",
            )
        ]


class _RowStub:
    """素材行桩：普通属性容器。"""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def load_method(name, extra=None):
    """从 material_sync_service 里取出指定方法并编译执行（不依赖 sqlalchemy）"""
    source = read(MATERIAL_SYNC)
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "MaterialSyncService":
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
                segment = textwrap.dedent(ast.get_source_segment(source, item) or "")
                # 源码使用 `from __future__ import annotations`，单独编译需补同样声明
                code = "from __future__ import annotations\n" + segment
                namespace = {"ProductMaterial": _MaterialStub, "select": _SelectStub}
                if extra:
                    namespace.update(extra)
                exec(compile(code, "<material_sync_service>", "exec"), namespace)
                return namespace[name]
    raise AssertionError(f"未找到 {name}")


# ---------- 1. 判重：软删不再算「已存在」 ----------

def test_pooled_source_ids_excludes_soft_deleted():
    print("\n[1] 行为：素材池判重子查询的条件")
    pooled = load_method("_pooled_source_ids")

    stmt = pooled(None, 42)
    conditions = stmt.conditions

    check("仍按用户过滤", ("eq", "user_id", 42) in conditions)
    check("仍要求 source_item_id 非空", ("is_not", "source_item_id", None) in conditions)
    check("软删素材不再算已存在（is_deleted = False）",
          ("is_", "is_deleted", False) in conditions,
          f"实际条件: {conditions}")


# ---------- 2. 恢复目标查询 ----------

def test_find_revive_target_query():
    print("\n[2] 行为：软删行查询条件")
    find_target = load_method("_find_revive_target")

    row = _RowStub(id=451, is_deleted=True)
    session = _SessionStub(row=row)
    owner = SimpleNamespace(session=session)

    found = asyncio.run(find_target(owner, user_id=3, item_id="1071737415889"))
    stmt = session.statements[-1]

    check("命中软删行时返回该行", found is row)
    check("按用户过滤", ("eq", "user_id", 3) in stmt.conditions)
    check("按源商品ID精确匹配", ("eq", "source_item_id", "1071737415889") in stmt.conditions)
    check("只找软删行", ("is_", "is_deleted", True) in stmt.conditions)
    check("多行软删取最新（id 倒序）", stmt.order == ("desc", "id"))
    check("只取一行", stmt.limit_value == 1)

    # 没有软删行时返回 None（走正常新建分支）
    empty_session = _SessionStub(row=None)
    none_owner = SimpleNamespace(session=empty_session)
    check("无软删行时返回 None",
          asyncio.run(find_target(none_owner, user_id=3, item_id="999")) is None)


# ---------- 3. 复活搬运：内容刷新、主键/时间保留 ----------

def test_revive_from_copies_fresh_content():
    print("\n[3] 行为：软删行内容刷新语义")
    revive = load_method("_revive_from")

    target = _RowStub(
        id=451, user_id=3, title="旧标题", description="旧描述", price=1.0,
        images=["old.jpg"], remark="旧备注", source_item_id="1071737415889",
        is_deleted=True, created_at="2026-10-01T00:00:00", updated_at="2026-10-01T00:00:00",
    )
    fresh = _RowStub(
        id=None, user_id=3, title="新标题", description="新描述", price=9.9,
        images=["new.jpg"], remark="新备注", source_item_id="1071737415889",
        is_deleted=None, created_at=None, updated_at=None,
    )

    revive(target, fresh)

    check("标题刷新为最新", target.title == "新标题")
    check("描述刷新为最新", target.description == "新描述")
    check("价格刷新为最新", target.price == 9.9)
    check("图片刷新为最新", target.images == ["new.jpg"])
    check("备注刷新为最新", target.remark == "新备注")
    check("主键保留旧行（不新建行）", target.id == 451)
    check("创建时间保留旧行", target.created_at == "2026-10-01T00:00:00")
    check("更新时间不被临时对象的 None 覆盖（非空列保护）",
          target.updated_at == "2026-10-01T00:00:00")
    check("软删除标记置回未删除", target.is_deleted is False)


# ---------- 4. sync_batch 接线 ----------

def test_sync_batch_wires_revival():
    print("\n[4] 行为：sync_batch 的恢复接线")
    source = read(MATERIAL_SYNC)
    tree = ast.parse(source)
    segment = ""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MaterialSyncService":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "sync_batch":
                    segment = ast.get_source_segment(source, item) or ""
    check("找到 sync_batch", bool(segment))

    check("写入前查询软删旧行", "_find_revive_target(" in segment)
    check("命中旧行时搬运内容", "_revive_from(" in segment)
    check("恢复计数 revived += 1", "revived += 1" in segment)
    check("响应体返回 revived", '"revived": revived' in segment)
    check("空缺口时 revived 也为 0", '"revived": 0' in segment)
    check("日志区分入库/恢复", "已恢复（删过的素材重新入池）" in segment)


# ---------- 5. 预览口径 ----------

def test_preview_pooled_counts_active_only():
    print("\n[5] 行为：预览接口的素材池口径")
    source = read(MATERIAL_SYNC)
    tree = ast.parse(source)
    segment = ""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MaterialSyncService":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "preview":
                    segment = ast.get_source_segment(source, item) or ""
    check("找到 preview", bool(segment))
    check("pooled 只算未删除（软删不算在池内）", "is_deleted.is_(False)" in segment)


def main():
    print("=" * 60)
    print("素材同步「恢复用户删过的素材」· 测试")
    print("=" * 60)
    test_pooled_source_ids_excludes_soft_deleted()
    test_find_revive_target_query()
    test_revive_from_copies_fresh_content()
    test_sync_batch_wires_revival()
    test_preview_pooled_counts_active_only()
    print(f"\n结果：{PASS} 通过，{FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
