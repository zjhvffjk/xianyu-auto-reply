"""素材类目预览及确认保存，仅操作本地素材，不发布商品。"""
from sqlalchemy import select
import hashlib
import json
from common.models.product_material import ProductMaterial
from common.models.xy_catalog_item import XYCatalogItem


def has_category(material):
    return bool(material.platform_category_id and material.platform_channel_category_id)


def category_candidate(form):
    if not form.get('platform_category_id') or not form.get('platform_channel_category_id') or not (form.get('platform_category_name') or form.get('category')):
        return None
    return dict(cat_id=form['platform_category_id'], channel_cat_id=form['platform_channel_category_id'],
                cat_name=form.get('platform_category_name') or form.get('category'),
                channel_cat_name=form.get('platform_channel_category_name'), leaf_id=form.get('platform_leaf_id'),
                tb_cat_id=form.get('platform_tb_category_id'), path=form.get('platform_category_path') or [])


def category_token(material):
    fields = ('category', 'platform_category_id', 'platform_category_name', 'platform_channel_category_id',
              'platform_channel_category_name', 'platform_tb_category_id', 'platform_leaf_id',
              'platform_category_path', 'platform_attributes')
    return hashlib.sha256(json.dumps({k: getattr(material, k) for k in fields},
        sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class MaterialCategoryService:
    def __init__(self, session):
        self.session = session

    async def _get(self, material_id, owner_id, lock=False):
        stmt = select(ProductMaterial).where(ProductMaterial.id == material_id, ProductMaterial.is_deleted.is_(False))
        if owner_id is not None:
            stmt = stmt.where(ProductMaterial.user_id == owner_id)
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt.execution_options(populate_existing=True))).scalars().first()

    async def preview(self, ids, owner_id, mode='fill'):
        results = []
        for material_id in dict.fromkeys(ids):
            material = await self._get(material_id, owner_id)
            if not material:
                results.append(dict(id=material_id, status='failed', message='素材不存在或无权访问'))
                continue
            if mode == 'replace':
                current = category_candidate({k: getattr(material, k) for k in (
                    'category', 'platform_category_id', 'platform_category_name', 'platform_channel_category_id',
                    'platform_channel_category_name', 'platform_tb_category_id', 'platform_leaf_id', 'platform_category_path')})
                results.append(dict(id=material_id, status='ready', current=current,
                    category_token=category_token(material)))
                continue
            if has_category(material):
                results.append(dict(id=material_id, status='skipped', message='已有完整平台类目，已跳过'))
                continue
            candidate = None
            if material.catalog_account_pk and material.catalog_item_id:
                item = (await self.session.execute(select(XYCatalogItem).where(
                    XYCatalogItem.account_pk == material.catalog_account_pk,
                    XYCatalogItem.item_id == material.catalog_item_id,
                ))).scalars().first()
                if item:
                    candidate = category_candidate((item.metadata_json or {}).get('material_form') or {})
            results.append(dict(id=material_id, status='ready', candidate=candidate))
        return results

    async def save(self, entries, owner_id, mode='fill'):
        results = []
        seen = set()
        for entry in entries:
            material_id = entry['id']
            if material_id in seen:
                continue
            seen.add(material_id)
            material = await self._get(material_id, owner_id, lock=True)
            if not material:
                results.append(dict(id=material_id, status='failed', message='素材不存在或无权访问'))
                await self.session.rollback()
                continue
            if mode == 'replace' and entry.get('expected_category_token') != category_token(material):
                results.append(dict(id=material_id, status='conflict', message='类目或属性已变化，请重新预览后确认'))
                await self.session.rollback()
                continue
            if mode != 'replace' and has_category(material):
                results.append(dict(id=material_id, status='skipped', message='类目已完整，未覆盖'))
                await self.session.rollback()
                continue
            candidate = entry['candidate']
            if not candidate.get('cat_id') or not candidate.get('channel_cat_id') or not candidate.get('cat_name'):
                results.append(dict(id=material_id, status='failed', message='类目资料不完整，请重新选择'))
                await self.session.rollback()
                continue
            before = tuple(str(getattr(material, field) or '') for field in (
                'platform_category_id', 'platform_channel_category_id', 'platform_tb_category_id', 'platform_leaf_id'))
            after = tuple(str(candidate.get(field) or '') for field in ('cat_id', 'channel_cat_id', 'tb_cat_id', 'leaf_id'))
            if before != after:
                material.platform_attributes = []
            material.category = str(candidate['cat_name'])
            material.platform_category_id = str(candidate['cat_id'])
            material.platform_category_name = str(candidate['cat_name'])
            material.platform_channel_category_id = str(candidate['channel_cat_id'])
            material.platform_channel_category_name = candidate.get('channel_cat_name')
            material.platform_leaf_id = candidate.get('leaf_id')
            material.platform_tb_category_id = candidate.get('tb_cat_id')
            material.platform_category_path = candidate.get('path') or []
            material.category_source = 'manual'
            material.category_confidence = None
            await self.session.commit()
            results.append(dict(id=material_id, status='saved', message='类目已保存'))
        return results
