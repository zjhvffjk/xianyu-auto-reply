"""批量发布只读检查与整批日志登记；不访问闲鱼、不改写素材。"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from sqlalchemy import select

from common.models.product_material import ProductMaterial
from common.models.publish_log import PublishLog
from common.models.xy_account import XYAccount
from common.services.publish_address_service import PublishAddressService
from app.services.product_publish_service import _material_to_dict


def utf16_length(value: str) -> int:
    return len(value.encode('utf-16-le')) // 2


def material_publish_errors(material: dict) -> list[str]:
    errors = []
    title = str(material.get('title') or '')
    body = str(material.get('description') or '')
    if not title.strip() or utf16_length(title) > 30 or '\n' in title or '\r' in title:
        errors.append('标题须为1～30字，且不能换行')
    if not body.strip() or utf16_length(body) > 1500:
        errors.append('描述须为1～1500字')
    images = material.get('images') or []
    if not images or len(images) > 9 or any(not isinstance(url, str) or not re.match(r'^(https?://|//|/static/)', url.strip()) for url in images):
        errors.append('商品图片须为1～9张有效图片')
    if not material.get('platform_category_id') or not material.get('platform_channel_category_id'):
        errors.append('请补全平台类目')
    def positive(value):
        try:
            return math.isfinite(float(value)) and float(value) > 0
        except (TypeError, ValueError):
            return False
    def stock_valid(value):
        return positive(value) and float(value).is_integer()
    specs = material.get('specifications') or []
    rows = material.get('sku_rows') or []
    if specs:
        names = [s.get('name') for s in specs]
        values = [[v.get('name') for v in s.get('values', [])] for s in specs]
        if len(specs) > 2 or not all(names) or len(set(names)) != len(names) or any(not v or not all(v) or len(set(v)) != len(v) for v in values):
            errors.append('规格名称或规格值不完整、重复')
        else:
            expected = set(itertools.product(*values))
            actual = [tuple((r.get('specs') or {}).get(n) for n in names) for r in rows]
            if len(actual) != len(set(actual)) or set(actual) != expected:
                errors.append('规格组合不完整或重复')
        if not rows or any(not positive(r.get('price')) or not isinstance(r.get('stock'), (int, float)) or not math.isfinite(r['stock']) or r['stock'] < 0 or not float(r['stock']).is_integer() for r in rows):
            errors.append('规格价格或库存无效')
        elif not any(r['stock'] > 0 for r in rows):
            errors.append('所有规格库存为0，请补充库存')
    else:
        if rows:
            errors.append('存在SKU但缺少规格定义')
        if not positive(material.get('price')):
            errors.append('售价须大于0')
        if not stock_valid(material.get('quantity')):
            errors.append('库存须为大于0的整数')
    return errors


class BatchPublishService:
    def __init__(self, session):
        self.session = session

    async def inspect(self, user_id: int, account_ids: list[str], material_ids: list[int], *, lock: bool = False):
        account_ids = list(dict.fromkeys(account_ids))
        material_ids = list(dict.fromkeys(material_ids))
        if len(account_ids) * len(material_ids) > 500:
            raise ValueError('每批最多500次发布，请缩小选择范围')
        account_query = select(XYAccount).where(
            XYAccount.owner_id == user_id, XYAccount.account_id.in_(account_ids),
        )
        material_query = select(ProductMaterial).where(
            ProductMaterial.user_id == user_id, ProductMaterial.is_deleted.is_(False),
            ProductMaterial.id.in_(material_ids),
        )
        accounts = (await self.session.execute(account_query.with_for_update() if lock else account_query)).scalars().all()
        rows = (await self.session.execute(material_query.with_for_update() if lock else material_query)).scalars().all()
        account_map = {a.account_id: a for a in accounts}
        material_map = {m.id: {**_material_to_dict(m), 'quantity': m.quantity} for m in rows}
        if set(account_map) != set(account_ids) or set(material_map) != set(material_ids):
            raise ValueError('部分账号或素材已移除，或不属于当前用户，请重新选择')
        materials = [material_map[mid] for mid in material_ids]
        log_query = select(PublishLog).where(
            PublishLog.user_id == user_id, PublishLog.account_id.in_(account_ids),
            PublishLog.material_id.in_(material_ids),
            PublishLog.status.in_(['success', 'pending', 'publishing', 'unknown']),
        ).order_by(PublishLog.id.desc())
        # 提交串行锁内必须用当前读，避免MySQL一致性快照漏看刚提交的另一批次。
        logs = (await self.session.execute(log_query.with_for_update() if lock else log_query)).scalars().all()
        history = {}
        for log in logs:
            pair = (log.account_id, log.material_id)
            info = history.setdefault(pair, {'success_count': 0, 'uncertain': False})
            if log.status == 'success':
                info['success_count'] += 1
            else:
                info['uncertain'] = True
        issues = []
        address_service = PublishAddressService(self.session)
        for aid in account_ids:
            account = account_map[aid]
            account_errors = [] if (account.cookie or '').strip() else ['账号缺少登录信息，请重新登录']
            needs_pool = any(not str(m.get('address') or '').strip() for m in materials)
            if needs_pool and not (await address_service.build_queue_state(aid)).addresses:
                account_errors.append('部分素材未填所在地，且地址库没有可用地址')
            for m in materials:
                past = history.get((aid, m['id']), {'success_count': 0, 'uncertain': False})
                errors = account_errors + material_publish_errors(m)
                if past['uncertain']:
                    errors.append('已有等待中或结果未确定的发布记录；请到发布日志，使用“记录核查结果”处理待核查记录')
                issues.append({'account_id': aid, 'material_id': m['id'], 'title': m['title'],
                               'source_item_id': m.get('catalog_item_id') if m.get('catalog_account_pk') == getattr(account, 'id', None) else None,
                               'errors': errors, **past})
        # 包括原始字段与历史状态；提交时重查，防止检查后修改或另一批次已提交。
        digest = hashlib.sha256(json.dumps({'accounts': account_ids, 'materials': materials,
            'issues': issues}, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        return {'fingerprint': digest, 'total': len(issues), 'ready': all(not i['errors'] for i in issues),
                'duplicate_count': sum(i['success_count'] > 0 or bool(i['source_item_id']) for i in issues), 'items': issues}, materials

    async def existing(self, user_id: int, batch_id: str, account_ids, material_ids):
        rows = (await self.session.execute(select(PublishLog).where(PublishLog.batch_id == batch_id))).scalars().all()
        if not rows:
            return None
        expected = {(a, m) for a in account_ids for m in material_ids}
        if any(r.user_id != user_id for r in rows) or {(r.account_id, r.material_id) for r in rows} != expected:
            raise ValueError('该请求号已用于其他选择，请重新检查')
        return {'batch_id': batch_id, 'total': len(rows), 'reused': True}

    async def register(self, user_id: int, batch_id: str, account_ids, materials, *, start_at=None, interval_seconds=None, mode="immediate"):
        for aid in account_ids:
            for m in materials:
                request_id = hashlib.sha256(f'{batch_id}:{aid}:{m["id"]}'.encode()).hexdigest()
                self.session.add(PublishLog(user_id=user_id, account_id=aid, material_id=m['id'],
                    batch_id=batch_id, publish_request_id=f'batch:{request_id}', status='pending',
                    title=m['title'], description=m['description'], price=str(m['price'])))
        if start_at is not None and interval_seconds is not None:
            from common.models.publish_batch import PublishBatch
            self.session.add(PublishBatch(id=batch_id, user_id=user_id, mode=mode,
                status='waiting', start_at=start_at, next_run_at=start_at, interval_seconds=interval_seconds,
                account_ids=account_ids, materials=json.loads(json.dumps(materials, default=str)),
                sync_results={}, cancel_requested=False))
        # 一次提交全部待执行项；唯一键保证相同请求只登记一次。
        await self.session.commit()
