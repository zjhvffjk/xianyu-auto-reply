"""手动读取和后台补全共用的商品完整资料快照。"""
from copy import deepcopy
import json


def has_complete_catalog_form(item) -> bool:
    metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
    form = metadata.get('material_form')
    if not isinstance(form, dict):
        return False
    return bool(
        form.get('title') and form.get('description') and form.get('images')
        and form.get('shipping_method') and form.get('price') is not None
        and type(form.get('quantity')) is int and form['quantity'] >= 0
    )


def cache_catalog_form(catalog, form: dict) -> None:
    """保留发货关联等已有元数据，原样缓存平台表单和最新卖家库存。"""
    metadata = dict(catalog.metadata_json or {})
    metadata['material_form'] = deepcopy(form)
    if form.get('price') is not None:
        metadata['listing_price'] = str(form['price'])
    if not form.get('sku_rows') and type(form.get('quantity')) is int:
        seller_detail = dict(metadata.get('seller_detail') or {})
        seller_detail['quantity'] = form['quantity']
        metadata['seller_detail'] = seller_detail
        detail = metadata.get('detail') or {}
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (ValueError, TypeError):
                detail = {}
        if isinstance(detail, dict):
            detail = dict(detail, quantity=form['quantity'])
            metadata['detail'] = json.dumps(detail, ensure_ascii=False)
    catalog.metadata_json = metadata
