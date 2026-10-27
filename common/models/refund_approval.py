from datetime import datetime
from decimal import Decimal
from sqlalchemy import BigInteger, DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from common.db.base_class import Base


class RefundApproval(Base):
    __tablename__ = 'xy_refund_approvals'
    __table_args__ = (UniqueConstraint('account_id', 'refund_id', name='uk_refund_approval'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    account_id: Mapped[str] = mapped_column(String(80), nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    refund_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(String(300), default='', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
