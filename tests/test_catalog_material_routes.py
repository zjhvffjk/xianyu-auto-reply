import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
sys.path.insert(0, '/app/backend-web')
from app.api.routes import product_publish as materials
from app.api.routes import items


class CatalogMaterialRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_denies_invisible_shop_before_creating_material(self):
        service = MagicMock()
        service.get_account_for_user = AsyncMock(return_value=None)
        with patch.object(materials, 'AccountService', return_value=service):
            response = await materials.import_catalog_materials(
                materials.CatalogMaterialImportRequest(account_id='other', item_ids=['123']),
                SimpleNamespace(id=7, role='USER'), MagicMock())
        self.assertFalse(response.success)
        service.get_account_for_user.assert_awaited_once_with(7, 'other')

    async def test_import_uses_current_actor_and_authorized_account(self):
        account = SimpleNamespace(id=3, owner_id=7)
        account_service = MagicMock()
        account_service.get_account_for_user = AsyncMock(return_value=account)
        importer = MagicMock()
        importer.import_items = AsyncMock(return_value=[{'item_id': '123', 'status': 'created', 'message': '导入成功'}])
        with patch.object(materials, 'AccountService', return_value=account_service), patch('app.services.catalog_material_service.CatalogMaterialService', return_value=importer):
            response = await materials.import_catalog_materials(
                materials.CatalogMaterialImportRequest(account_id='shop', item_ids=['123']),
                SimpleNamespace(id=7, role='USER'), MagicMock())
        self.assertTrue(response.success)
        importer.import_items.assert_awaited_once_with(7, account, ['123'])

    async def test_product_detail_caches_same_form_and_current_stock(self):
        from common.models.xy_catalog_item import XYCatalogItem
        catalog = XYCatalogItem(owner_id=7, account_pk=3, item_id='123', title='测试', price='1',
                                metadata_json={'detail': json.dumps({'quantity': 9}), 'seller_detail': {'quantity': 9}})
        service = MagicMock()
        service.get_account_for_user = AsyncMock(return_value=SimpleNamespace(id=3, owner_id=7, account_id='shop', cookie='test-only'))
        result = MagicMock(); result.scalars.return_value.first.return_value = catalog
        service.session.execute = AsyncMock(return_value=result)
        service.session.commit = AsyncMock()
        form = {'price': 1, 'quantity': 0, 'description': '完整描述'}
        with patch.object(items, 'fetch_seller_item_edit_detail', new=AsyncMock(return_value={'success': True, 'data': {'form': form}})):
            response = await items.get_seller_item_edit_detail('shop', '123', SimpleNamespace(id=7, role='USER'), service)
        self.assertTrue(response.success)
        self.assertEqual(catalog.metadata_json['material_form'], form)
        self.assertEqual(catalog.metadata_json['seller_detail']['quantity'], 0)
        self.assertEqual(json.loads(catalog.metadata_json['detail'])['quantity'], 0)
        service.session.commit.assert_awaited_once()

    def test_material_draft_accepts_platform_description_and_zero_stock(self):
        request = materials.MaterialUpdateRequest(description='测' * 1500, quantity=0)
        self.assertEqual(request.quantity, 0)
        from pydantic import ValidationError
        for model, fields in [
            (materials.MaterialCreateRequest, dict(title='测试', price=1, images=['/static/test.png'])),
            (materials.MaterialUpdateRequest, {}),
            (materials.PublishSingleRequest, dict(account_id='shop', title='测试', price=1, images=['/static/test.png'])),
        ]:
            with self.subTest(model=model.__name__):
                self.assertEqual(len(model(description='测' * 1500, **fields).description), 1500)
                with self.assertRaises(ValidationError):
                    model(description='测' * 1501, **fields)


if __name__ == '__main__':
    unittest.main()
