import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
sys.path.insert(0, '/app/backend-web')
from common.models.product_material import ProductMaterial
from app.services.product_publish_service import ProductMaterialService


def result_rows(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.all.return_value = rows
    return result


class MaterialSourceSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_source_identity_is_batched_and_never_serializes_cookie(self):
        materials = [ProductMaterial(id=i, user_id=7, title='测试', description='完整', price=1,
                      catalog_account_pk=3, catalog_item_id=str(i), quantity=0) for i in (1, 2)]
        account = SimpleNamespace(id=3, account_id='123', cookie='tracknick=xy_store;', display_name=None, metadata_json={})
        count = MagicMock(); count.scalar.return_value = 2
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[count, result_rows(materials), result_rows([account])])
        response = await ProductMaterialService(session).list_materials(user_id=7)
        self.assertEqual(session.execute.await_count, 3)
        for material in response['list']:
            self.assertEqual(material['catalog_account']['member_name'], 'xy_store')
            self.assertEqual(set(material['catalog_account']), {'account_id', 'member_name', 'nickname'})
            self.assertEqual(material['quantity'], 0)
            self.assertNotIn('cookie', material)

    async def test_unlinked_materials_do_not_query_or_invent_shop_identity(self):
        material = ProductMaterial(id=1, user_id=7, title='测试', description='完整', price=1)
        count = MagicMock(); count.scalar.return_value = 1
        session = MagicMock()
        session.execute = AsyncMock(side_effect=[count, result_rows([material])])
        response = await ProductMaterialService(session).list_materials(user_id=7)
        self.assertEqual(session.execute.await_count, 2)
        self.assertIsNone(response['list'][0]['catalog_account'])
        self.assertIsNone(response['list'][0]['catalog_item_id'])


if __name__ == '__main__':
    unittest.main()
