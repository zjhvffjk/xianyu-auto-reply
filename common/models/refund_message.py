"""独立退款消息配置和持久化占位；不存储支付宝验证凭据。"""
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from common.db.base_class import Base


class RefundMessageConfig(Base):
    __tablename__ = 'xy_refund_message_configs'
    account_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unshipped_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shipped_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unshipped_content: Mapped[str] = mapped_column(Text, default='', nullable=False)
    shipped_content: Mapped[str] = mapped_column(Text, default='', nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class RefundMessageRecord(Base):
    __tablename__ = 'xy_refund_message_records'
    __table_args__ = (UniqueConstraint('account_id', 'order_no', name='uk_refund_message_order'),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='processing', nullable=False)
    detail: Mapped[str] = mapped_column(String(300), default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
