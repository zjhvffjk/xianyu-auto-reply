"""持久化批量发布队列（北京时间DATETIME，素材快照不含凭据）。"""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from common.db.base_class import Base, TimestampMixin


class PublishBatch(TimestampMixin, Base):
    __tablename__ = 'xy_publish_batches'
    __table_args__ = (Index('idx_pb_due', 'status', 'next_run_at'), Index('idx_pb_user_created', 'user_id', 'created_at'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default='waiting', nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    account_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    materials: Mapped[list] = mapped_column(JSON, nullable=False)
    sync_results: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    current_log_id: Mapped[int | None] = mapped_column(BigInteger)
    last_error: Mapped[str | None] = mapped_column(String(500))
