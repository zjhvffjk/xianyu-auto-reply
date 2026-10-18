"""批量定时发布任务模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base

# 发布间隔技术下限（秒）：scheduler 每 30 秒扫一轮，间隔低于 30 秒的任务只会在
# 下一轮扫描时补发、实际节奏仍是 30 秒，所以 30 秒是有意义的最小值。
# 这是技术下限而非风控下限——风控节奏由用户自定，前端在低于 5 分钟时给出警告但不拦截。
MIN_PUBLISH_INTERVAL_SECONDS = 30
# 默认间隔（秒）：5 分钟，防平台风控的保守默认值，用户可自行调低
DEFAULT_PUBLISH_INTERVAL_SECONDS = 300


class ScheduledPublishTask(Base):
    """一份批量定时发布任务。

    执行队列 = 账号 × 素材 全组合（与立即发布语义一致），到点后按
    interval_seconds 逐条发布；next_index 指向队列下标，next_run_at
    是下一条的执行时间，扫描任务每次只发到期的那一条。
    """

    __tablename__ = "xy_scheduled_publish_tasks"
    __table_args__ = (
        Index("idx_sched_pub_user_status", "user_id", "status"),
        Index("idx_sched_pub_due", "status", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    material_ids: Mapped[list] = mapped_column(JSON, nullable=False, comment="待发布素材ID列表")
    account_ids: Mapped[list] = mapped_column(JSON, nullable=False, comment="发布账号ID（cookie_id）列表")
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="任务开始执行时间")
    interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_PUBLISH_INTERVAL_SECONDS,
        comment="每条发布间隔秒数（技术下限30，默认300，用户可自定）",
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending",
        comment="pending等待中/running执行中/completed已完成/cancelled已取消/failed已失败",
    )
    next_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="下一条要执行的下标")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="下一条执行时间")
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="队列总条数")
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
