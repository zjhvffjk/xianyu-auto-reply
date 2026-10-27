"""平台详情回填后构造编辑载荷，不调用平台保存或媒体上传。"""
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, '/app/backend-web')
from app.services.xianyu_item_edit_mapper import map_edit_detail_to_form
from app.services.xianyu_item_payload_builder import build_item_payload


class ItemEditRoundtripTests(unittest.IsolatedAsyncioTestCase):
    def snapshot(self):
        return {
            'itemId': '12345', 'quantity': '0',
            'itemTextDTO': {'title': '测试商品', 'desc': '第一行\n第二行'},
            'itemPriceDTO': {'priceInCent': '1234', 'origPriceInCent': '2000'},
            'itemCatDTO': {'catId': '1', 'catName': '测试类目', 'channelCatId': '2'},
            'imageInfoDOList': [
                {'type': '0', 'url': 'https://example.test/second.jpg', 'major': 'false', 'widthSize': '600', 'heightSize': '800'},
                {'type': '0', 'url': 'https://example.test/main.jpg', 'major': 'true', 'widthSize': '900', 'heightSize': '1200'},
                {'type': '1', 'url': 'https://example.test/cover.jpg', 'videoUrl': 'https://example.test/video.mp4', 'mediaCloudFileId': 'video-1', 'major': 'true'},
            ],
            'itemAddrDTO': {'poiName': '测试地点', 'poiId': 'poi-1', 'divisionId': '440300', 'gps': '114,22'},
            'itemPostFeeDTO': {'canFreeShipping': 'false', 'supportFreight': 'true', 'onlyTakeSelf': 'true', 'postPriceInCent': '650', 'templateId': '0'},
            'userRightsProtocols': [{'serviceCode': 'test-service', 'enable': 'true'}],
        }

    async def test_unchanged_edit_keeps_media_zero_stock_address_shipping_and_rights(self):
        snapshot = self.snapshot()
        form = map_edit_detail_to_form(snapshot)
        self.assertEqual(form['quantity'], 0)
        self.assertEqual(form['condition'], '')
        with patch('app.services.xianyu_item_payload_builder.upload_publish_image', new=AsyncMock()) as image_upload, \
             patch('app.services.xianyu_item_payload_builder.upload_publish_videos', new=AsyncMock()) as video_upload, \
             patch('app.services.xianyu_item_payload_builder.AmapInputTipsService.search', new=AsyncMock()) as address_lookup:
            payload, _ = await build_item_payload(form, 'test-cookie', 'shop-a', 1, snapshot=snapshot)
            image_upload.assert_not_awaited()
            video_upload.assert_not_awaited()
            address_lookup.assert_not_awaited()
        self.assertEqual(int(payload['quantity']), 0)
        self.assertEqual(payload['itemTextDTO']['desc'], '第一行\n第二行')
        self.assertEqual(int(payload['itemPriceDTO']['priceInCent']), 1234)
        images = [item for item in payload['imageInfoDOList'] if item['type'] == 0]
        self.assertEqual(images[0]['url'], 'https://example.test/main.jpg')
        self.assertEqual(images[0]['widthSize'], 900)
        self.assertEqual(payload['imageInfoDOList'][0]['mediaCloudFileId'], 'video-1')
        self.assertEqual(payload['itemAddrDTO']['poiId'], 'poi-1')
        self.assertEqual(str(payload['itemPostFeeDTO']['postPriceInCent']), '650')
        self.assertTrue(payload['itemPostFeeDTO']['onlyTakeSelf'])
        self.assertTrue(payload['userRightsProtocols'][0]['enable'])

    def test_sku_mapping_retains_sold_out_variants_and_specification_order(self):
        snapshot = self.snapshot()
        snapshot['itemSkuList'] = [
            {'priceInCent': '1234', 'quantity': '0', 'propertyList': [{'propertyText': '颜色', 'valueText': '蓝色', 'propertySortOrder': '1', 'valueSortOrder': '2'}]},
            {'priceInCent': '1500', 'quantity': '5', 'propertyList': [{'propertyText': '颜色', 'valueText': '白色', 'propertySortOrder': '1', 'valueSortOrder': '1'}]},
        ]
        form = map_edit_detail_to_form(snapshot)
        self.assertEqual(form['specifications'][0]['values'][0]['name'], '白色')
        self.assertEqual(form['sku_rows'][0]['stock'], 0)
        self.assertEqual(form['sku_rows'][1]['stock'], 5)


if __name__ == '__main__':
    unittest.main()
