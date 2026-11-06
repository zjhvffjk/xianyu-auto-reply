"""验证实际上传字节、MIME和尺寸；所有上传请求均被替换，不接触闲鱼。"""
import asyncio
from io import BytesIO
import json
import random
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageCms
from common.services import xianyu_publish_media as media


def image_bytes(image, fmt='PNG', **options):
    output = BytesIO(); image.save(output, fmt, **options); return output.getvalue()


class PublishImageUploadTests(unittest.IsolatedAsyncioTestCase):
    async def upload(self, content, name='photo.png', content_type='image/png', *, timeout=False):
        self.sent = {}
        test = self
        class Form:
            def add_field(self, field, value, **kwargs): test.sent.update(content=value, **kwargs)
        class Response:
            status = 200
            async def __aenter__(self):
                if timeout: raise asyncio.TimeoutError()
                return self
            async def __aexit__(self, *args): pass
            async def text(self): return json.dumps({'success': True, 'object': {'url': 'https://img.example/test.jpg'}})
            async def json(self, **kwargs): return {'success': True, 'object': {'url': 'https://img.example/test.jpg'}}
        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def post(self, *args, **kwargs): return Response()
        with patch.object(media.aiohttp, 'FormData', side_effect=Form), patch.object(media.aiohttp, 'ClientSession', return_value=Session()):
            return await media.upload_publish_image_content(content, name, 'test-only', content_type=content_type)

    async def test_large_png_is_uploaded_as_a_small_consistent_jpeg(self):
        original = image_bytes(Image.frombytes('RGB', (1280, 960), random.Random(7).randbytes(1280 * 960 * 3)))
        self.assertGreater(len(original), 1024 * 1024)
        result = await self.upload(original)
        self.assertLess(len(self.sent['content']), 1024 * 1024)
        self.assertEqual(self.sent['content_type'], 'image/jpeg')
        self.assertTrue(self.sent['filename'].endswith('.jpg'))
        with Image.open(BytesIO(self.sent['content'])) as image:
            self.assertEqual(image.format, 'JPEG'); self.assertEqual(image.size, (1280, 960))
        self.assertEqual((result['widthSize'], result['heightSize']), (1280, 960))

    async def test_large_dimensions_are_limited_and_published_dimensions_match_bytes(self):
        original = image_bytes(Image.new('RGB', (3000, 1500), '#426789'))
        result = await self.upload(original)
        with Image.open(BytesIO(self.sent['content'])) as image:
            self.assertEqual(image.size, (1920, 960))
            self.assertEqual((result['widthSize'], result['heightSize']), image.size)

    async def test_small_images_are_not_reencoded(self):
        original = image_bytes(Image.new('RGB', (80, 40), 'red'))
        result = await self.upload(original)
        self.assertEqual(self.sent['content'], original)
        self.assertEqual(self.sent['content_type'], 'image/png')
        self.assertEqual((result['widthSize'], result['heightSize']), (80, 40))

    async def test_rgb_color_profile_is_preserved_in_the_upload_copy(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        original = image_bytes(Image.new('RGB', (3000, 1500), (200, 70, 40)), icc_profile=profile)
        await self.upload(original)
        with Image.open(BytesIO(self.sent['content'])) as actual:
            self.assertEqual(actual.info.get('icc_profile'), profile)
            self.assertEqual(actual.mode, 'RGB')

    async def test_transparent_png_keeps_alpha_when_resized(self):
        original = image_bytes(Image.new('RGBA', (3000, 1500), (20, 50, 90, 100)))
        await self.upload(original)
        self.assertEqual(self.sent['content_type'], 'image/png')
        with Image.open(BytesIO(self.sent['content'])) as image:
            self.assertEqual(image.size, (1920, 960)); self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(image.getpixel((0, 0))[3], 100)

    async def test_exif_orientation_is_applied_before_resizing(self):
        image = Image.new('RGB', (2400, 1200), 'green'); exif = image.getexif(); exif[274] = 6
        original = image_bytes(image, 'JPEG', exif=exif)
        result = await self.upload(original, 'photo.jpg', 'image/jpeg')
        with Image.open(BytesIO(self.sent['content'])) as actual:
            self.assertEqual(actual.size, (960, 1920)); self.assertIn(actual.getexif().get(274), (None, 1))
        self.assertEqual((result['widthSize'], result['heightSize']), (960, 1920))

    async def test_animated_gif_is_not_flattened_to_one_frame(self):
        original = image_bytes(Image.new('RGB', (2100, 20), 'red'), 'GIF', save_all=True,
            append_images=[Image.new('RGB', (2100, 20), 'blue')], duration=100, loop=0)
        await self.upload(original, 'motion.gif', 'image/gif')
        self.assertEqual(self.sent['content'], original)
        with Image.open(BytesIO(self.sent['content'])) as actual: self.assertEqual(actual.n_frames, 2)

    async def test_invalid_image_fails_before_any_upload(self):
        with patch.object(media.aiohttp, 'ClientSession') as http:
            with self.assertRaises(media.PublishMediaError): await media.upload_publish_image_content(b'not-an-image', 'bad.png', 'test-only')
            http.assert_not_called()

    async def test_timeout_has_a_safe_actionable_message(self):
        with self.assertRaises(media.PublishMediaError) as error:
            await self.upload(image_bytes(Image.new('RGB', (30, 30), 'red')), timeout=True)
        self.assertIn('图片上传超时', str(error.exception))

    async def test_batch_timeout_is_identified_without_exposing_exception_data(self):
        from common.services import batch_publish_item
        from app.services.xianyu_direct_payload import DirectPublishError
        context = {'material': {}, 'cookie': 'test-only', 'account_id': 'test-only', 'user_id': 9, 'static_root': None, 'is_fish_shop': True}
        with patch.object(batch_publish_item, 'publish_single_item', new=AsyncMock(side_effect=DirectPublishError('第2张图片上传失败：图片上传超时 secret-test-value'))):
            result = await batch_publish_item.publish_prepared_batch_item(context)
        self.assertFalse(result['success']); self.assertFalse(result.get('unknown', False))
        self.assertIn('商品图片上传超时', result['message']); self.assertNotIn('secret-test-value', result['message'])


if __name__ == '__main__': unittest.main()
