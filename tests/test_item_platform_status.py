import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from common.services.item_service import ItemService
from common.services.xianyu_seller_item_client import SellerItemInfoManager


class ItemPlatformStatusTests(unittest.TestCase):
    def serialize(self, detail):
        item = SimpleNamespace(id=1, item_id='12345', title='商品', price='1.00',
            metadata_json={'detail': detail}, ai_prompt='', is_polished=False,
            created_at=None, updated_at=None)
        return ItemService(None)._serialize_item(item, 'shop-a')

    def test_historical_snapshots_resolve_numeric_status_without_writing(self):
        for code, expected in [(0, '在卖'), ('1', '售出'), (-2, '下架'),
                               (-12, '下架'), (-1, '用户删除'), (-4, '违规')]:
            with self.subTest(code=code):
                result = self.serialize(json.dumps({'item_status': code}))
                self.assertEqual(result['platform_status'], expected)
                self.assertEqual(result['item_status_desc'], expected)

    def test_missing_or_malformed_status_stays_unknown(self):
        for detail in ['invalid', '{}', '[]', {'item_status': None}, {'item_status': 42}]:
            with self.subTest(detail=detail):
                self.assertEqual(self.serialize(detail)['platform_status'], '')

    def test_platform_description_is_preserved_and_dict_snapshot_is_supported(self):
        result = self.serialize({'item_status': 0, 'item_status_desc': '违规下架', 'quantity': 0})
        self.assertEqual(result['platform_status'], '违规下架')
        self.assertEqual(result['item_quantity'], 0)


class SellerStatusFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_filter_retains_owner_account_and_count_scope(self):
        session = MagicMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 4
        rows = MagicMock()
        rows.all.return_value = []
        session.execute = AsyncMock(side_effect=[count_result, rows])
        service = ItemService(session)
        service._backfill_platform_status = AsyncMock()
        service._get_default_reply_status_batch = AsyncMock(return_value={})
        service._get_card_status_batch = AsyncMock(return_value=set())
        items, total = await service.list_items_paginated(7, 'shop-a', platform_status='on_sale')
        self.assertEqual((items, total), ([], 4))
        for call in session.execute.call_args_list:
            compiled = call.args[0].compile()
            values = list(compiled.params.values())
            self.assertIn(7, values)
            self.assertIn('shop-a', values)
            self.assertIn(['在卖', '在售'], values)

    async def test_backfill_only_updates_status_and_keeps_delivery_configuration(self):
        from common.models.xy_catalog_item import XYCatalogItem
        item = XYCatalogItem(metadata_json={'detail': json.dumps({'item_status': -2}), 'is_multi_spec': True, 'custom': {'saved': True}})
        session = MagicMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [item]
        session.execute = AsyncMock(return_value=result)
        session.commit = AsyncMock()
        await ItemService(session)._backfill_platform_status(7)
        self.assertEqual(item.metadata_json['platform_status'], '下架')
        self.assertTrue(item.metadata_json['is_multi_spec'])
        self.assertEqual(item.metadata_json['custom'], {'saved': True})
        self.assertIn(7, session.execute.call_args.args[0].compile().params.values())

    async def test_sync_reads_all_states_and_explicit_filter_remains_available(self):
        response = {'success': True, 'res': {'data': {'data': {}}}}
        with patch('common.services.xianyu_seller_item_client.mtop_call', new=AsyncMock(return_value=response)) as call:
            manager = SellerItemInfoManager('shop-a', 'test-cookie')
            await manager.get_item_list_info(1, 20)
            self.assertNotIn('itemStatus', call.call_args.kwargs['data'])
            await manager.get_item_list_info(1, 20, item_status='0')
            self.assertEqual(call.call_args.kwargs['data']['itemStatus'], '0')

    def test_absent_status_is_not_invented_as_on_sale(self):
        self.assertIsNone(SellerItemInfoManager._map_item({'itemId': '12345'})['item_status'])


if __name__ == '__main__':
    unittest.main()
