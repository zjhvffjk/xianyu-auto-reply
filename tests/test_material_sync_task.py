"""素材库批量任务（model 纯函数 + 表结构注册）测试

覆盖：
1. task_to_dict 的进度百分比 / finished 判定 / 空值兜底（前端轮询契约）
2. is_task_active 对各状态的判定
3. truncate_error_message 的长度裁剪
4. 新表 xy_material_sync_tasks 已在建表 DDL 与模型导出中注册
   （漏注册会导致线上建不出表、任务接口直接 500）
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_SRC = REPO_ROOT / "common" / "models" / "material_sync_task.py"
EXPORTS_SRC = REPO_ROOT / "common" / "models" / "_exports.py"
INIT_DB_SRC = REPO_ROOT / "common" / "db" / "init_database.py"


def _extract_functions(src: Path, names: list[str]) -> dict:
    """从源文件中提取指定的模块级函数/常量，编译成可调用对象。

    与仓库既有测试一致：被extract的文件带 BOM，读取须用 utf-8-sig。
    """
    tree = ast.parse(src.read_text(encoding="utf-8-sig"))
    wanted = set(names)
    picked = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            picked.append(node)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if wanted & set(targets):
                picked.append(node)
    assert picked, f"未找到 {names} in {src}"
    module = ast.Module(body=picked, type_ignores=[])
    namespace: dict = {}
    exec(compile(module, str(src), "exec"), namespace)  # noqa: S102 - 测试内可信源码
    return namespace


class _FakeTask:
    """任务行桩对象（只带 task_to_dict 需要的属性）"""

    def __init__(self, **kwargs):
        self.task_id = kwargs.get("task_id", "t-1")
        self.task_type = kwargs.get("task_type", "sync")
        self.status = kwargs.get("status", "running")
        self.account_pk = kwargs.get("account_pk")
        self.total_missing = kwargs.get("total_missing", 0)
        self.processed = kwargs.get("processed", 0)
        self.created = kwargs.get("created", 0)
        self.revived = kwargs.get("revived", 0)
        self.updated = kwargs.get("updated", 0)
        self.failed = kwargs.get("failed", 0)
        self.skipped = kwargs.get("skipped", 0)
        self.remaining = kwargs.get("remaining", 0)
        self.error_message = kwargs.get("error_message")
        self.started_at = kwargs.get("started_at")
        self.finished_at = kwargs.get("finished_at")
        self.created_at = kwargs.get("created_at")


NS = _extract_functions(
    MODEL_SRC,
    [
        "task_to_dict",
        "is_task_active",
        "truncate_error_message",
        "TASK_ACTIVE_STATUSES",
        "TASK_STATUS_PENDING",
        "TASK_STATUS_RUNNING",
        "TASK_STATUS_SUCCESS",
        "TASK_STATUS_PARTIAL",
        "TASK_STATUS_FAILED",
        "TASK_STATUS_CANCELED",
        "ERROR_MESSAGE_MAX_LENGTH",
    ],
)
task_to_dict = NS["task_to_dict"]
is_task_active = NS["is_task_active"]
truncate_error_message = NS["truncate_error_message"]


class TestIsTaskActive:
    def test_running_and_pending_are_active(self):
        assert is_task_active("running") is True
        assert is_task_active("pending") is True

    def test_finished_statuses_are_not_active(self):
        for status in ("success", "partial", "failed", "canceled", "", None):
            assert is_task_active(status) is False, status


class TestTruncateErrorMessage:
    def test_short_message_unchanged(self):
        assert truncate_error_message("任务已取消任务") == "任务已取消任务"

    def test_none_becomes_empty(self):
        assert truncate_error_message(None) == ""

    def test_over_limit_truncated(self):
        assert truncate_error_message("x" * 1500) == "x" * 1000


class TestTaskToDict:
    def test_progress_percent(self):
        d = task_to_dict(_FakeTask(total_missing=147, processed=45))
        assert d["progress_percent"] == 30

    def test_progress_percent_zero_total(self):
        d = task_to_dict(_FakeTask(total_missing=0, processed=0))
        assert d["progress_percent"] == 0

    def test_running_task_not_finished(self):
        d = task_to_dict(_FakeTask(status="running"))
        assert d["finished"] is False

    def test_finished_statuses(self):
        for status in ("success", "partial", "failed", "canceled"):
            d = task_to_dict(_FakeTask(status=status))
            assert d["finished"] is True, status

    def test_counts_passthrough(self):
        d = task_to_dict(
            _FakeTask(
                created=10, revived=5, updated=3, failed=2, skipped=1, remaining=100
            )
        )
        assert d["created"] == 10
        assert d["revived"] == 5
        assert d["updated"] == 3
        assert d["failed"] == 2
        assert d["skipped"] == 1
        assert d["remaining"] == 100

    def test_null_fields_have_safe_defaults(self):
        d = task_to_dict(_FakeTask())
        assert d["error_message"] == ""
        assert d["started_at"] is None
        assert d["finished_at"] is None
        assert d["created_at"] is None
        assert d["account_pk"] is None


class TestTableRegistration:
    """新表必须同时注册到建表 DDL 与模型导出，否则线上建不出表。"""

    def test_model_exported(self):
        text = EXPORTS_SRC.read_text(encoding="utf-8-sig")
        assert "from common.models.material_sync_task import" in text
        assert "MaterialSyncTask" in text

    def test_ddl_registered(self):
        text = INIT_DB_SRC.read_text(encoding="utf-8-sig")
        assert '"xy_material_sync_tasks"' in text
        assert "CREATE TABLE IF NOT EXISTS xy_material_sync_tasks" in text

    def test_ddl_has_unique_task_id(self):
        text = INIT_DB_SRC.read_text(encoding="utf-8-sig")
        assert "uq_xy_material_sync_tasks_task_id" in text
