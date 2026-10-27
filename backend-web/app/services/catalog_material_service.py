"""从商品管理的已获取资料生成素材；此模块不请求闲鱼或外部接口。"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from common.models.product_material import ProductMaterial
from common.models.xy_account import XYAccount
from common.models.xy_catalog_item import XYCatalogItem


def material_data_from_catalog(item: XYCatalogItem) -> tuple[dict, list[str]]:
    metadata = item.metadata_json or {}
    form = deepcopy(metadata.get('material_form') or {})
    if not form:
        raise ValueError('商品管理尚未保存完整描述、全部图片和发货设置；请先在商品管理打开该商品的编辑页面获取完整资料，再导入')
    # 标价和单规格库存随商品管理的列表同步更新；不要退回买家优惠展示价。
    if form:
        if metadata.get('listing_price') is not None:
            form['price'] = str(metadata['listing_price']).replace('¥', '').replace('￥', '').strip()
        seller = metadata.get('seller_detail') or {}
        if not form.get('sku_rows') and isinstance(seller.get('quantity'), int):
            form['quantity'] = seller['quantity']
    missing = []
    for key, label in [('title', '标题'), ('description', '完整描述'), ('images', '商品图片'), ('shipping_method', '发货方式')]:
        if not form.get(key):
            missing.append(label)
    try:
        price = Decimal(str(form.get('price')))
        if not price.is_finite() or price <= 0:
            missing.append('有效售价')
    except (InvalidOperation, ValueError):
        missing.append('有效售价')
    quantity = form.get('quantity')
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
        missing.append('库存')
    if missing:
        raise ValueError('缺少' + '、'.join(missing) + '；请先在商品管理打开该商品的编辑页面获取完整资料，再导入')
    if len(form['description']) > 1500:
        raise ValueError('商品描述超过素材库1500字限制，本次未导入；原商品资料已保留，请精简描述后新建素材')
    # 显式字段白名单，不把账号凭据或无关元数据复制进素材。
    fields = ['title', 'description', 'price', 'original_price', 'category', 'platform_category_id',
              'platform_category_name', 'platform_channel_category_id', 'platform_channel_category_name',
              'platform_leaf_id', 'platform_tb_category_id', 'platform_category_path', 'platform_attributes',
              'images', 'videos', 'specifications', 'sku_rows', 'shipping_method', 'support_pickup',
              'postage', 'address', 'address_expected_text', 'brand', 'condition']
    data = {key: form.get(key) for key in fields}
    data.update(quantity=quantity, delivery_method='pickup' if form['shipping_method'] == 'none' else 'express',
                category_source='manual', condition=form.get('condition') or '')
    warnings = []
    if not form.get('condition'):
        warnings.append('成色未获取，请在素材编辑中补全')
    if not form.get('platform_category_id') or not form.get('platform_channel_category_id'):
        warnings.append('平台类目不完整，请在发布前补全')
    return data, warnings


class CatalogMaterialService:
    def __init__(self, session):
        self.session = session

    async def import_items(self, user_id: int, account: XYAccount, item_ids: list[str]) -> list[dict]:
        account_pk, account_owner = account.id, account.owner_id
        results = []
        for item_id in dict.fromkeys(item_ids):
            try:
                # 同一店铺的导入串行化；唯一索引额外保护重复点击和多进程请求。
                await self.session.execute(select(XYAccount.id).where(XYAccount.id == account_pk).with_for_update())
                existing = (await self.session.execute(select(ProductMaterial).where(
                    ProductMaterial.user_id == user_id, ProductMaterial.catalog_account_pk == account_pk,
                    ProductMaterial.catalog_item_id == item_id,
                ))).scalars().first()
                if existing:
                    results.append({'item_id': item_id, 'status': 'exists', 'material_id': existing.id,
                                    'message': '此前已导入，不覆盖修改或恢复已删除素材'})
                    await self.session.rollback()
                    continue
                item = (await self.session.execute(select(XYCatalogItem).where(
                    XYCatalogItem.account_pk == account_pk, XYCatalogItem.owner_id == account_owner,
                    XYCatalogItem.item_id == item_id,
                ))).scalars().first()
                if not item:
                    raise ValueError('该商品不属于当前店铺或已从商品管理移除')
                data, warnings = material_data_from_catalog(item)
                material = ProductMaterial(user_id=user_id, catalog_account_pk=account_pk,
                                           catalog_item_id=item_id, **data)
                self.session.add(material)
                await self.session.commit()
                results.append({'item_id': item_id, 'status': 'created', 'material_id': material.id,
                                'message': '；'.join(warnings) or '导入成功'})
            except IntegrityError:
                await self.session.rollback()
                results.append({'item_id': item_id, 'status': 'exists', 'message': '此前已导入，不重复创建'})
            except ValueError as exc:
                await self.session.rollback()
                results.append({'item_id': item_id, 'status': 'failed', 'message': str(exc)})
        return results
