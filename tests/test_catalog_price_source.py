"""商品标价不能被买家列表的优惠展示价覆盖。"""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from common.models.xy_catalog_item import XYCatalogItem
from common.services.item_service import ItemService


class CatalogPriceSourceTests(unittest.IsolatedAsyncioTestCase):
    def setup_service(self):
        item = XYCatalogItem(owner_id=7, account_pk=1, item_id='12345', title='商品', price='1.00',
            metadata_json={'category': '', 'detail': json.dumps({'source': 'seller', 'price_text': '1.00'})})
        result = MagicMock()
        result.scalars.return_value.first.return_value = item
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        account = SimpleNamespace(id=1, owner_id=7)
        return ItemService(session), item, account

    async def test_buyer_discount_does_not_replace_listing_price(self):
        service, item, account = self.setup_service()
        await service._apply_single_item(account, '12345', {'id': '12345', 'title': '商品', 'price_text': '¥0.10', 'source': 'personal'})
        self.assertEqual(item.price, '1.00')
        self.assertEqual(item.metadata_json['buyer_display_price'], '¥0.10')
        self.assertEqual(item.metadata_json['listing_price'], '1.00')

    async def test_new_seller_price_updates_and_survives_later_buyer_sync(self):
        service, item, account = self.setup_service()
        await service._apply_single_item(account, '12345', {'id': '12345', 'title': '商品', 'price_text': '2.00', 'source': 'seller'})
        self.assertEqual(item.price, '2.00')
        await service._apply_single_item(account, '12345', {'id': '12345', 'title': '商品', 'price_text': '¥0.20'})
        self.assertEqual(item.price, '2.00')

    async def test_accounts_without_seller_data_still_use_available_display_price(self):
        service, item, account = self.setup_service()
        item.metadata_json = {}
        await service._apply_single_item(account, '12345', {'id': '12345', 'title': '商品', 'price_text': '¥0.10'})
        self.assertEqual(item.price, '¥0.10')

    async def test_confirmed_platform_price_change_updates_the_listing_cache(self):
        service, item, account = self.setup_service()
        service.session.commit = AsyncMock()
        item.metadata_json['listing_price'] = '1.00'
        await service._apply_local_price_change(account, '12345', single_payload={'price': 3, 'quantity': 2}, sku_payload=None)
        self.assertEqual(item.metadata_json['listing_price'], '3.00')
        await service._apply_single_item(account, '12345', {'id': '12345', 'title': '商品', 'price_text': '¥0.10'})
        self.assertEqual(item.price, '3.00')


if __name__ == '__main__':
    unittest.main()
