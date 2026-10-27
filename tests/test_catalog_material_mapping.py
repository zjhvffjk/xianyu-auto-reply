import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, '/app/backend-web')
from app.services.catalog_material_service import material_data_from_catalog


def form():
    return dict(title='测试商品', description='完整测试描述', images=['https://example.com/item.png'],
                price=1, quantity=3, shipping_method='free', condition='', sku_rows=[], specifications=[],
                platform_category_id='123', platform_channel_category_id='456')


class CatalogMaterialMappingTests(unittest.TestCase):
    def test_long_description_is_not_truncated_or_imported(self):
        cached = form()
        cached['description'] = '测' * 1500
        data, _ = material_data_from_catalog(SimpleNamespace(metadata_json={'material_form': cached}))
        self.assertEqual(len(data['description']), 1500)
        cached['description'] += '测'
        with self.assertRaisesRegex(ValueError, '1500'):
            material_data_from_catalog(SimpleNamespace(metadata_json={'material_form': cached}))
        self.assertEqual(len(cached['description']), 1501)

    def test_missing_detail_does_not_manufacture_description(self):
        with self.assertRaisesRegex(ValueError, '完整描述'):
            material_data_from_catalog(SimpleNamespace(metadata_json={'description': '', 'title': '测试商品'}))

    def test_current_listing_price_and_zero_stock_override_older_form(self):
        metadata = {'material_form': form(), 'listing_price': '¥1.00', 'buyer_display_price': '¥0.10',
                    'seller_detail': {'quantity': 0}}
        data, warnings = material_data_from_catalog(SimpleNamespace(metadata_json=metadata))
        self.assertEqual(data['price'], '1.00')
        self.assertEqual(data['quantity'], 0)
        self.assertEqual(data['condition'], '')
        self.assertTrue(any('成色' in warning for warning in warnings))
        data['images'].append('changed')
        self.assertEqual(len(metadata['material_form']['images']), 1)

    def test_specs_and_video_are_retained(self):
        cached = form()
        cached.update(sku_rows=[{'specs': {'颜色': '蓝'}, 'price': 1, 'stock': 2}],
                      specifications=[{'name': '颜色', 'values': [{'name': '蓝'}]}],
                      videos=[{'url': 'https://example.com/video.mp4'}])
        data, _ = material_data_from_catalog(SimpleNamespace(metadata_json={'material_form': cached}))
        for key in ['sku_rows', 'specifications', 'videos']:
            self.assertEqual(data[key], cached[key])

    def test_invalid_money_and_unknown_stock_rejected(self):
        for value in [None, 'NaN', -1]:
            cached = form(); cached['price'] = value
            with self.assertRaises(ValueError):
                material_data_from_catalog(SimpleNamespace(metadata_json={'material_form': cached}))
        cached = form(); cached['quantity'] = None
        with self.assertRaisesRegex(ValueError, '库存'):
            material_data_from_catalog(SimpleNamespace(metadata_json={'material_form': cached}))


if __name__ == '__main__':
    unittest.main()
