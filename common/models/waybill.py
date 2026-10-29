"""实物打单与卡券流程分别保存；取号不代表平台发货。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from common.db.base_class import Base, TimestampMixin


class WaybillPlatform(TimestampMixin, Base):
    """统一服务商应用；独立于商家店铺和旧连接测试。"""
    __tablename__ = 'xy_waybill_platform'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_key: Mapped[str] = mapped_column(String(120))
    credentials_ciphertext: Mapped[str] = mapped_column(Text)


class WaybillConnection(TimestampMixin, Base):
    __tablename__ = 'xy_waybill_connections'
    __table_args__ = (UniqueConstraint('app_key', 'mall_user_id', name='uk_waybill_remote_shop'),)
    account_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    app_key: Mapped[str] = mapped_column(String(120), default='')
    credentials_ciphertext: Mapped[str] = mapped_column(Text, default='')
    login_user: Mapped[str] = mapped_column(String(200), default='')
    mall_user_id: Mapped[str] = mapped_column(String(40), default='')
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WaybillAuthorization(TimestampMixin, Base):
    """店铺登录确认记录；独立于开发者密钥与面单权限。"""
    __tablename__ = 'xy_waybill_authorizations'
    __table_args__ = (UniqueConstraint('app_key', 'mall_user_id', name='uk_waybill_authorized_shop'),)
    account_pk: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    app_key: Mapped[str] = mapped_column(String(120))
    platform_fingerprint: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_ciphertext: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default='pending')
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    mall_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    shop_name: Mapped[str] = mapped_column(String(200), default='')
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WaybillRecord(TimestampMixin, Base):
    __tablename__ = 'xy_waybill_records'
    __table_args__ = (UniqueConstraint('account_pk', 'order_no', name='uk_waybill_account_order'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    account_pk: Mapped[int] = mapped_column(BigInteger, index=True)
    order_no: Mapped[str] = mapped_column(String(64))
    remote_tid: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(String(300), default='')
    recipient_ciphertext: Mapped[str] = mapped_column(Text, default='')
    source_hash: Mapped[str] = mapped_column(String(64))
    template_id: Mapped[str] = mapped_column(String(80), default='')
    carrier: Mapped[str] = mapped_column(String(120), default='')
    waybill_no: Mapped[str] = mapped_column(String(80), default='')
