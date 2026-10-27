"""店铺筛选与权限必须同时生效，不能因全选而跨店。"""
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, '/app/backend-web')
from app.services.selectable_item_service import SelectableItemService


class ShopItemScopeTests(unittest.IsolatedAsyncioTestCase):
    def test_existing_associations_keep_all_shop_owners(self):
        rows = [('item-1', '商品', '1.00', 'shop-a'), ('item-1', '商品', '1.00', 'shop-b')]
        result = SelectableItemService._aggregate_rows(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['account_ids'], ['shop-a', 'shop-b'])

    async def test_select_all_keeps_owner_and_account_filters(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock())
        session.execute.return_value.all.return_value = []
        await SelectableItemService(session).get_all_selectable_item_keys(
            owner_id=7, account_id='shop-a', search='商品')
        statement = session.execute.call_args.args[0]
        compiled = statement.compile()
        self.assertIn(7, compiled.params.values())
        self.assertIn('shop-a', compiled.params.values())
        self.assertIn('xy_accounts', str(compiled))
        self.assertIn('xy_catalog_items.owner_id', str(compiled))


if __name__ == '__main__':
    unittest.main()
