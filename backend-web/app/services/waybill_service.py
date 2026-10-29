"""实物打单；已取号与闲鱼发货状态分别记录，不调用卡券/免物流流程。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from decimal import Decimal
from uuid import uuid4
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.services.waybill_platform_service import WaybillPlatformService
from common.models.waybill import WaybillConnection, WaybillRecord
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem
from common.models.xy_order import XYOrder
from common.services.waybill_client import KdzsClient, WaybillRemoteError, safe_print_url, validate_recipient
from common.utils.auth_scope import resolve_owner_scope
from common.utils.time_utils import get_beijing_now_naive, safe_isoformat


async def scoped_account(db, user, account_id):
    owner, _ = resolve_owner_scope(user)
    stmt = select(XYAccount).where(XYAccount.account_id == account_id)
    if owner is not None:
        stmt = stmt.where(XYAccount.owner_id == owner)
    account = (await db.execute(stmt)).scalars().first()
    if not account:
        raise HTTPException(404, '店铺不存在或无权访问')
    return account


def recipient_from_order(order):
    address = str(order.receiver_address or '').strip()
    province = city = county = ''
    match = re.match(r'^(北京市|上海市|天津市|重庆市|.+?自治区|.+?省)\s*', address)
    if match:
        province, address = match.group(1), address[match.end():]
        if province in ('北京市', '上海市', '天津市', '重庆市'):
            city = province
        else:
            match = re.match(r'^(.+?(?:自治州|地区|市|盟))\s*', address)
            if match:
                city, address = match.group(1), address[match.end():]
        match = re.match(r'^(.+?(?:自治县|自治旗|区|县|旗|市))\s*', address)
        if match:
            county, address = match.group(1), address[match.end():]
    return dict(name=order.receiver_name or '', phone=order.receiver_phone or '', province=province,
                city=city, county=county, address=address)


def source_hash(order):
    values = [order.order_no, order.receiver_name, order.receiver_phone, order.receiver_address,
              order.item_id, order.quantity, str(order.amount)]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def order_problems(order):
    errors = []
    if order.status != 'pending_ship':
        errors.append('仅支持待发货订单，请先核对平台状态')
    if order.card_only_delivered:
        errors.append('此订单已经发出卡券，请核对后再处理实物发货')
    if not order.item_id or not order.quantity or order.quantity < 1:
        errors.append('商品或数量信息不完整')
    if order.amount is None or Decimal(str(order.amount)) < 0:
        errors.append('订单金额不完整')
    return errors


def item_info(order, item):
    meta = (item.metadata_json or {}) if item else {}
    form = meta.get('material_form') or {}
    images = form.get('images') or []
    snapshot = order.item_snapshot or {}
    image = images[0] if images and isinstance(images[0], str) else snapshot.get('picUrl', '')
    if isinstance(image, str):
        parsed = urlsplit(image)
        if parsed.scheme == 'http' and (parsed.hostname or '').endswith('.alicdn.com'):
            image = 'https://' + image[len('http://'):]
    title = (item.title if item else '') or snapshot.get('title') or ''
    return str(title), image if isinstance(image, str) and image.startswith('https://') else ''


def serialize_record(record, platform_status=None):
    return dict(id=record.id, order_no=record.order_no, status=record.status, detail=record.detail,
                waybill_no=record.waybill_no, carrier=record.carrier, template_id=record.template_id,
                platform_status=platform_status, updated_at=safe_isoformat(record.updated_at))


def template_rows(response):
    groups = response.get('data')
    if not isinstance(groups, list):
        raise WaybillRemoteError('模板返回格式异常，请联系服务商核对')
    result = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get('modeListShows'), list):
            raise WaybillRemoteError('模板返回格式异常，请联系服务商核对')
        result.extend(row for row in group['modeListShows'] if isinstance(row, dict)
                      and row.get('modeListshowId') and row.get('enableStatus') is True)
    return result


class WaybillService:
    def __init__(self, db, account, *, legacy_allowed=False):
        self.db, self.account = db, account
        self.legacy_allowed = legacy_allowed

    def _fernet(self):
        secret = get_settings().jwt_secret_key
        if not secret or len(secret) < 16 or secret == 'change-me-in-production-please':
            raise HTTPException(503, '服务密钥尚未初始化，请重启后再保存连接')
        scope = f'waybill:{self.account.owner_id}:{self.account.id}'.encode()
        return Fernet(base64.urlsafe_b64encode(hmac.new(secret.encode(), scope, hashlib.sha256).digest()))

    async def connection(self, *, required=False, lock=False):
        if required and not self.legacy_allowed:
            raise HTTPException(409, '服务商店铺授权尚未接通，请等待平台开放授权后再打单')
        stmt = select(WaybillConnection).where(WaybillConnection.account_pk == self.account.id,
                                               WaybillConnection.owner_id == self.account.owner_id)
        if lock:
            stmt = stmt.with_for_update()
        config = (await self.db.execute(stmt)).scalars().first()
        if required and not config:
            raise HTTPException(409, '尚未配置快递助手开放平台应用，请先在接入配置中填写')
        return config

    def _secret(self, config):
        try:
            return self._fernet().decrypt(config.credentials_ciphertext.encode()).decode()
        except (InvalidToken, UnicodeError, AttributeError):
            raise HTTPException(409, '连接密钥无法读取，请重新填写AppSecret') from None

    async def settings(self):
        platform = await WaybillPlatformService(self.db).settings()
        config = await self.connection() if self.legacy_allowed else None
        return dict(configured=bool(config), app_key=config.app_key if config else '',
                    has_secret=bool(config and config.credentials_ciphertext),
                    login_user=config.login_user if config else '', mall_user_id=config.mall_user_id if config else '',
                    verified_at=safe_isoformat(config.verified_at) if config else None,
                    platform_configured=platform['configured'], legacy_allowed=self.legacy_allowed,
                    authorization_available=platform['authorization_available'], embedded_print_available=False)

    async def save_settings(self, data):
        if not self.legacy_allowed:
            raise HTTPException(403, '平台应用由管理员统一配置，用户无需填写开发密钥')
        config = await self.connection(lock=True)
        if not data.app_secret and (not config or data.app_key != config.app_key):
            raise HTTPException(422, '新增或更换AppKey时请填写对应AppSecret')
        scope_changed = bool(config and (data.app_key, data.login_user, data.mall_user_id) != (
            config.app_key, config.login_user, config.mall_user_id))
        if scope_changed and (await self.db.execute(select(WaybillRecord.id).where(
                WaybillRecord.account_pk == self.account.id).limit(1))).scalars().first():
            raise HTTPException(409, '店铺已有打单记录，不能直接改绑应用或远端店铺；请先核对现有单号')
        occupied = (await self.db.execute(select(WaybillConnection.account_pk).where(
            WaybillConnection.app_key == data.app_key, WaybillConnection.mall_user_id == data.mall_user_id,
            WaybillConnection.account_pk != self.account.id).limit(1))).scalars().first()
        if occupied is not None:
            raise HTTPException(409, '该应用及远端店铺已绑定其他闲鱼店铺；多店铺应用请填写独立的mallUserId')
        if data.mall_user_id and not data.login_user:
            raise HTTPException(422, '多店铺应用请填写服务商提供的工作台用户名')
        if not config:
            config = WaybillConnection(account_pk=self.account.id, owner_id=self.account.owner_id)
            self.db.add(config)
        if data.app_secret:
            config.credentials_ciphertext = self._fernet().encrypt(data.app_secret.get_secret_value().encode()).decode()
        config.app_key, config.login_user, config.mall_user_id = data.app_key, data.login_user, data.mall_user_id
        config.verified_at = None
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(409, '连接绑定已发生变化，请刷新后检查，不能重复绑定同一远端店铺') from None
        return await self.settings()

    def client(self, config):
        return KdzsClient(config.app_key, self._secret(config))

    @staticmethod
    def business(config, **kwargs):
        if config.mall_user_id:
            kwargs['mallUserId'] = config.mall_user_id
        return kwargs

    async def templates(self):
        config = await self.connection(required=True, lock=True)
        result = await self.client(config).call('kdzs.print.template.get', self.business(config, data={}))
        templates = [dict(id=str(row['modeListshowId']), carrier=str(row.get('excodeName') or ''),
                          code=str(row.get('excode') or ''), type=str(row.get('kddType') or ''))
                     for row in template_rows(result)]
        config.verified_at = get_beijing_now_naive()
        await self.db.commit()
        return templates

    async def _order(self, order_no, *, lock=False):
        stmt = select(XYOrder).where(XYOrder.owner_id == self.account.owner_id,
                                     XYOrder.account_id == self.account.account_id, XYOrder.order_no == order_no)
        if lock:
            stmt = stmt.with_for_update()
        order = (await self.db.execute(stmt)).scalars().first()
        if not order:
            raise HTTPException(404, '当前店铺中未找到订单')
        return order

    async def _item(self, order):
        return (await self.db.execute(select(XYCatalogItem).where(
            XYCatalogItem.account_pk == self.account.id, XYCatalogItem.owner_id == self.account.owner_id,
            XYCatalogItem.item_id == order.item_id))).scalars().first()

    async def preview(self, order_nos):
        # 先核对全部订单权限，任何越权项均不返回其他订单的收件信息。
        orders = [await self._order(no) for no in order_nos]
        result = []
        for order in orders:
            title, image = item_info(order, await self._item(order))
            recipient = recipient_from_order(order)
            errors = order_problems(order)
            if not title or not image:
                errors.append('商品标题或图片不完整，请先刷新商品资料')
            record = await self._record(order.order_no)
            if record and record.recipient_ciphertext:
                try:
                    recipient = json.loads(self._fernet().decrypt(record.recipient_ciphertext.encode()).decode())
                except (InvalidToken, ValueError, UnicodeError):
                    errors.append('已同步收件快照无法读取，请先到工作台核对')
            result.append(dict(order_no=order.order_no, title=title, amount=str(order.amount or ''),
                               quantity=order.quantity, recipient=recipient, errors=errors,
                               recipient_errors=validate_recipient(recipient),
                               record=serialize_record(record, order.status) if record else None))
        return result

    async def _record(self, order_no, *, lock=False):
        stmt = select(WaybillRecord).where(WaybillRecord.account_pk == self.account.id,
                                           WaybillRecord.owner_id == self.account.owner_id,
                                           WaybillRecord.order_no == order_no)
        return (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalars().first()

    async def sync(self, order_no, recipient):
        if self.account.status in ('inactive', 'disabled', 'suspended', 'deleted'):
            raise HTTPException(409, '店铺已停用，请先恢复登录')
        config = await self.connection(required=True, lock=True)
        if not config.verified_at:
            raise HTTPException(409, '请先检测开放平台连接并读取已授权面单模板')
        order = await self._order(order_no, lock=True)
        problems = order_problems(order) + validate_recipient(recipient)
        title, image = item_info(order, await self._item(order))
        if not title or not image:
            problems.append('缺少商品标题或图片，请先刷新商品资料')
        if problems:
            raise HTTPException(409, '；'.join(problems))
        record = await self._record(order_no, lock=True)
        if record and record.status not in ('sync_failed',):
            result = serialize_record(record, order.status)
            await self.db.rollback()
            return result
        if not record:
            record = WaybillRecord(id=str(uuid4()), account_pk=self.account.id, owner_id=self.account.owner_id,
                                   order_no=order_no, remote_tid=f'xy_{self.account.id}_{order_no}')
            self.db.add(record)
        client = self.client(config)
        amount = format(Decimal(str(order.amount)), '.2f')
        quantity = order.quantity
        now = get_beijing_now_naive().strftime('%Y-%m-%d %H:%M:%S')
        placed = order.placed_at.strftime('%Y-%m-%d %H:%M:%S') if order.placed_at else now
        payload = dict(tid=record.remote_tid, outerTid=order_no, tradeSource='OTHERS',
                       outerUid=self.account.account_id, outerUserName=self.account.display_name or self.account.account_id,
                       receiverName=recipient['name'], receiverMobile=recipient['phone'],
                       receiverProvince=recipient['province'], receiverCity=recipient['city'],
                       receiverCounty=recipient['county'], receiverAddress=recipient['address'],
                       status='ORDER_PAID', totalFee=amount, payment=amount, postFee='0.00',
                       created=placed, payTime=placed, modified=now, totalNum=quantity,
                       orders=[dict(orderId=record.remote_tid, itemId=order.item_id, title=title,
                                    picPath=image, outerId=order.item_id, skuId='0', outerSkuId=order.item_id,
                                    number=quantity, price=format(Decimal(amount) / quantity, '.2f'),
                                    totalFee=amount, payment=amount, status='ORDER_PAID', saleProps=[])])
        business = self.business(config, data=payload)
        record.status, record.detail, record.source_hash = 'syncing', '已提交同步请求，等待服务商确认', source_hash(order)
        record.recipient_ciphertext = self._fernet().encrypt(json.dumps(recipient, ensure_ascii=False).encode()).decode()
        await self.db.commit()  # 先落地，再访问第三方。进程退出后不可盲目重发。
        try:
            await client.call('kdzs.print.trade.create', business)
            record.status, record.detail = 'synced', '已同步，可选择已授权模板取号并前往工作台打印'
        except WaybillRemoteError as exc:
            record.status = 'sync_unknown' if exc.uncertain else 'sync_failed'
            record.detail = str(exc)
        await self.db.commit()
        await self.db.refresh(record)
        return serialize_record(record, order.status)

    async def number(self, order_no, template_id):
        config = await self.connection(required=True, lock=True)
        if not config.verified_at:
            raise HTTPException(409, '连接配置尚未验证，请先检测连接')
        record = await self._record(order_no, lock=True)
        if not record:
            raise HTTPException(404, '请先同步当前店铺订单')
        order = await self._order(order_no, lock=True)
        if record.waybill_no or record.status != 'synced':
            result = serialize_record(record, order.status)
            await self.db.rollback()
            return result
        if order_problems(order) or record.source_hash != source_hash(order):
            raise HTTPException(409, '订单状态或收件资料已变化，请先在工作台核对，不继续取号')
        client = self.client(config)
        # 使用相同授权读取实时模板，拒绝客户端自造或其他店铺的模板。
        response = await client.call('kdzs.print.template.get', self.business(config, data={}))
        template = next((row for row in template_rows(response)
                         if str(row['modeListshowId']) == template_id), None)
        if not template:
            raise HTTPException(409, '面单模板未授权或已停用，请刷新模板')
        record.template_id, record.carrier = template_id, str(template.get('excodeName') or '')
        record.status, record.detail = 'numbering', '取号请求已提交，等待服务商确认'
        business = self.business(config, tids=[record.remote_tid], modeListShowId=template_id)
        await self.db.commit()
        try:
            response = await client.call('kdzs.print.elecno.batch.get', business)
            data = response.get('data')
            rows = [r for r in data if isinstance(r, dict) and str(r.get('tid')) == record.remote_tid] if isinstance(data, list) else []
            if len(rows) != 1:
                raise WaybillRemoteError('取号返回未包含当前订单，请在工作台核对，勿重复取号', uncertain=True)
            row = rows[0]
            if row.get('success') is not True:
                # 即便顶层成功，也不能把缺失/错误的逐单结果当成已取号。
                raise WaybillRemoteError('当前订单取号未确认，请在工作台核对', uncertain=True)
            waybill = str(row.get('waybillNo') or '')
            if not re.fullmatch(r'[A-Za-z0-9-]{6,80}', waybill):
                raise WaybillRemoteError('返回的快递单号格式异常，请在工作台核对', uncertain=True)
            record.waybill_no, record.status = waybill, 'waybill_ready'
            record.detail = '已取号；打印请使用原单号。取号不代表闲鱼已经发货'
        except WaybillRemoteError as exc:
            record.status, record.detail = 'number_unknown' if exc.uncertain else 'number_failed', str(exc)
        await self.db.commit()
        await self.db.refresh(record)
        return serialize_record(record, order.status)

    async def print_url(self):
        config = await self.connection(required=True)
        if not config.verified_at:
            raise HTTPException(409, '请先检测连接')
        result = await self.client(config).call('kdzs.print.loginurl.get', dict(
            userName=config.login_user or config.app_key, secret=self._secret(config)))
        return safe_print_url(result.get('url') or '')

    async def records(self, page, page_size):
        where = (WaybillRecord.account_pk == self.account.id, WaybillRecord.owner_id == self.account.owner_id)
        total = (await self.db.execute(select(func.count()).select_from(WaybillRecord).where(*where))).scalar_one()
        records = (await self.db.execute(select(WaybillRecord).where(*where).order_by(
            WaybillRecord.updated_at.desc(), WaybillRecord.id).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        statuses = dict((await self.db.execute(select(XYOrder.order_no, XYOrder.status).where(
            XYOrder.owner_id == self.account.owner_id, XYOrder.account_id == self.account.account_id,
            XYOrder.order_no.in_([r.order_no for r in records])))).all()) if records else {}
        return dict(items=[serialize_record(r, statuses.get(r.order_no)) for r in records], total=total,
                    page=page, page_size=page_size)
