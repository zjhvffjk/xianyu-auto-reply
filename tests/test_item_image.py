import unittest
from common.utils.item_image import resolve_item_image


class ItemImageTests(unittest.TestCase):
    def test_both_catalog_sources_are_supported(self):
        self.assertEqual(resolve_item_image({'image_url': 'https://example.test/a.jpg'}), 'https://example.test/a.jpg')
        self.assertEqual(resolve_item_image({'pic_info': {'picUrl': '//example.test/b.jpg'}}), 'https://example.test/b.jpg')
        self.assertEqual(resolve_item_image({'pic_info': {'url': 'https://example.test/c.jpg'}}), 'https://example.test/c.jpg')

    def test_edit_snapshot_uses_primary_image_not_video(self):
        detail = {'imageInfoDOList': [
            {'type': '1', 'major': True, 'url': 'https://example.test/video'},
            {'type': '0', 'major': False, 'url': 'https://example.test/second.jpg'},
            {'type': '0', 'major': 'true', 'url': 'https://example.test/main.jpg'},
        ]}
        self.assertEqual(resolve_item_image(detail), 'https://example.test/main.jpg')

    def test_missing_or_invalid_image_falls_back_safely(self):
        for detail in [{}, {'pic_info': None}, {'image_url': 'javascript:alert(1)'}, {'image_url': 'broken'}]:
            self.assertEqual(resolve_item_image(detail), '')


if __name__ == '__main__':
    unittest.main()
