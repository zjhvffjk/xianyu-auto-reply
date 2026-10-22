"""
素材库批量任务模型（从商品同步 / 刷新价格库存）

功能：
1. 定义素材批量任务主表结构（xy_material_sync_tasks），进度与结果落库，
   页面刷新、关闭标签页、服务重启都不丢，随时可查当前进度
2. 状态常量与序列化工具，供 service、runner 与路由复用
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin


# ==================== 任务类型 ====================

# 从商品库同步素材（补缺口，含恢复用户删过的素材）
TASK_TYPE_SYNC = "sync"
# 从平台刷新素材的价格与库存
TASK_TYPE_PRICE_STOCK = "price_stock"

# 全部任务类型（供校验）
TASK_TYPES = (TASK_TYPE_SYNC, TASK_TYPE_PRICE_STOCK)


# ==================== 状态常量 ====================

# 任务状态：等待中 / 执行中 / 全部成功 / 部分成功 / 全部失败 / 已取消
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_PARTIAL = "partial"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELED = "canceled"

# 未结束状态集合（用于并发闸门与残留清理）
TASK_ACTIVE_STATUSES = (TASK_STATUS_PENDING, TASK_STATUS_RUNNING)

# 失败原因入库长度上限，与 xy_publish_logs.error_message 保持一致
ERROR_MESSAGE_MAX_LENGTH = 1000

# running 状态超过该分钟数没有进度更新，视为服务重启后残留的僵死任务
STALE_RUNNING_MINUTES = 60


def truncate_error_message(message: object) -> str:
    """把任意异常/文本裁剪成可入库的失败原因（最多 1000 字符）"""
    return str(message or "")[:ERROR_MESSAGE_MAX_LENGTH]


def is_task_active(status: str | None) -> bool:
    """任务是否仍在进行中（pending/running）"""
    return (status or "") in TASK_ACTIVE_STATUSES


def task_to_dict(task: MaterialSyncTask) -> dict:
    """任务行 → 前端消费的字典（前端只认这些字段，加字段要同步前端类型）"""
    total = task.total_missing or 0
    done = task.processed or 0
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "account_pk": task.account_pk,
        "total_missing": total,
        "processed": done,
        "created": task.created or 0,
        "revived": task.revived or 0,
        "updated": task.updated or 0,
        "failed": task.failed or 0,
        "skipped": task.skipped or 0,
        "remaining": task.remaining or 0,
        "progress_percent": int(done * 100 / total) if total else 0,
        "error_message": task.error_message or "",
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished": not is_task_active(task.status),
    }


class MaterialSyncTask(TimestampMixin, Base):
    """素材库批量任务主表 - 记录一次同步/刷新的整体进度"""

    __tablename__ = "xy_material_sync_tasks"
    __table_args__ = (
        Index("idx_mst_owner_type_created", "owner_id", "task_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="主键ID")
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="归属用户（本系统用户ID）")
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, comment="任务ID（UUID）")
    task_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="任务类型：sync-从商品同步，price_stock-刷新价格库存"
    )
    account_pk: Mapped[int | None] = mapped_column(
        BigInteger, comment="限定的账号主键（XYAccount.id）；NULL 表示不限账号"
    )
    owner_scope: Mapped[int | None] = mapped_column(
        BigInteger, comment="提交时的账号归属范围（管理员为 NULL，即不限）"
    )
    total_missing: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="启动时的总缺口")
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已处理条数")
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="同步：新增素材条数")
    revived: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="同步：恢复（软删复活）条数")
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="价格刷新：已刷新条数")
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="失败条数")
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="跳过条数")
    remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="范围内还剩多少条")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TASK_STATUS_PENDING,
        comment="状态：pending/running/success/partial/failed/canceled",
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), comment="整体失败/中止原因")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, comment="开始执行时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, comment="执行结束时间")
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否已删除（软删除）"
    )
