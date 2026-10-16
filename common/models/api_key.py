"""
对外 API 秘钥模型

功能：
1. 定义对外能力网关的秘钥表结构（xy_api_keys）
2. 存储秘钥值、备注、状态、每日配额与用量信息
3. 供 POST /api/v1/external/invoke 统一调用入口做身份校验

说明：
- 与 users.secret_key（个人设置-分销管理中的分销秘钥）相互独立：
  对外发秘钥的对象不是本系统的用户，混用会让公开接口的鉴权语义变模糊。
- daily_quota / last_used_at / total_calls 为 M2 的限流与计量预留，
  M1 只读取 key_value / status / expire_at 三个字段。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin


class XYApiKey(TimestampMixin, Base):
    """对外 API 秘钥表"""

    __tablename__ = "xy_api_keys"
    __table_args__ = (
        # key_value 全局唯一：请求头 X-API-Key 直接按该字段定位调用方
        Index("uk_api_key_value", "key_value", unique=True),
        Index("idx_api_key_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True, comment="秘钥ID")
    key_value: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="对外秘钥（明文，需可查看以便发放）",
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="",
        comment="备注：发给谁 / 用途",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        comment="active / disabled",
    )
    daily_quota: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="每日调用上限，0=不限（M2 生效）",
    )
    expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="过期时间，NULL=永不过期",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="最后调用时间",
    )
    total_calls: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="累计调用次数",
    )
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        comment="发放人（本系统用户ID，0=系统）",
    )


__all__ = ["XYApiKey"]
