import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from common.models.xy_catalog_item import XYCatalogItem
from common.services.item_service import ItemService
from common.services.xianyu_seller_item_client import SellerItemInfoManager


class CatalogInventorySourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_buyer_refresh_does_not_erase_seller_inventory_specs_or_shelf_time(self):
        item = XYCatalogItem(id=1, owner_id=7, account_pk=1, item_id='12345', title='商品', price='1.00',
            metadata_json={})
        result = MagicMock()
        result.scalars.return_value.first.return_value = item
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        service = ItemService(session)
        account = SimpleNamespace(id=1, owner_id=7)
        seller = {'id': '12345', 'source': 'seller', 'title': '商品', 'price_text': '1.00',
                  'quantity': 0, 'gmt_shelf': '2026-10-25', 'idle_item_sku_list': [{'sku_id': 'sku-1', 'quantity': 0}]}
        await service._apply_single_item(account, '12345', seller)
        await service._apply_single_item(account, '12345', {'id': '12345', 'title': '商品', 'price_text': '¥0.10'})
        output = service._serialize_item(item, 'shop-a')
        self.assertEqual(output['item_quantity'], 0)
        self.assertEqual(output['item_shelf_time'], '2026-10-25')
        self.assertEqual(output['item_sku_count'], 1)
        self.assertTrue(output['is_seller_item'])
        seller['quantity'] = 9
        await service._apply_single_item(account, '12345', seller)
        self.assertEqual(service._serialize_item(item, 'shop-a')['item_quantity'], 9)

    async def test_known_seller_catalog_does_not_depend_on_publish_capability_probe(self):
        result = MagicMock()
        result.scalar.return_value = 1
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        service = ItemService(session)
        service._detect_is_fish_shop = AsyncMock(return_value=False)
        account = SimpleNamespace(id=1, owner_id=7, account_id='shop-a', cookie='test-cookie')
        manager = await service._resolve_item_fetch_manager(account)
        self.assertIsInstance(manager, SellerItemInfoManager)
        service._detect_is_fish_shop.assert_not_awaited()
        params = session.execute.call_args.args[0].compile().params.values()
        self.assertIn(7, params)
        self.assertIn(1, params)


if __name__ == '__main__':
    unittest.main()
