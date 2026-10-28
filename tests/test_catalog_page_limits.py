"""100条页面的批量操作契约；通过真实路由验证校验和权限，数据库使用隔离替身。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI

sys.path.insert(0, '/app/backend-web')
from app.api.routes import catalog_details, product_publish
from app.services.catalog_material_service import CatalogMaterialService


class CatalogPageLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(catalog_details.router, prefix='/items')
        self.app.include_router(product_publish.router)
        empty = MagicMock()
        empty.scalars.return_value.first.return_value = None
        self.session = MagicMock()
        self.session.execute = AsyncMock(return_value=empty)
        self.session.rollback = AsyncMock()
        account_service = MagicMock()
        account_service.get_account_for_user = AsyncMock(return_value=None)
        self.app.dependency_overrides[catalog_details.deps.get_current_active_user] = lambda: SimpleNamespace(id=7, role='USER')
        self.app.dependency_overrides[catalog_details.deps.get_account_service] = lambda: account_service
        self.app.dependency_overrides[product_publish.get_db_session] = lambda: self.session
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()

    def requests(self, count):
        ids = [str(i) for i in range(1, count + 1)]
        entries = [{'id': int(i), 'candidate': {'cat_id': '1', 'channel_cat_id': '2', 'cat_name': '测试'}} for i in ids]
        return [
            ('/items/detail-sync/other', {'item_ids': ids}),
            ('/product-publish/materials/from-catalog', {'account_id': 'other', 'item_ids': ids}),
            ('/product-publish/materials/category-preview', {'ids': [int(i) for i in ids]}),
            ('/product-publish/materials/category-confirm', {'entries': entries}),
        ]

    async def test_full_page_sizes_reach_permission_checks_without_validation_error(self):
        for count in (50, 51, 100):
            for path, payload in self.requests(count):
                with self.subTest(count=count, path=path):
                    response = await self.client.post(path, json=payload)
                    if path.startswith('/items/'):
                        self.assertEqual(response.status_code, 404)
                    else:
                        self.assertEqual(response.status_code, 200)
                        body = response.json()
                        if path.endswith('from-catalog'):
                            self.assertFalse(body['success'])
                        else:
                            results = body['data']['results']
                            self.assertEqual(len(results), count)
                            self.assertTrue(all(row['status'] == 'failed' for row in results))

    async def test_more_than_a_full_page_is_rejected_on_every_endpoint(self):
        for path, payload in self.requests(101):
            with self.subTest(path=path):
                self.assertEqual((await self.client.post(path, json=payload)).status_code, 422)

    async def test_import_handles_every_item_on_a_hundred_item_page(self):
        session = MagicMock()
        results = []
        for i in range(1, 101):
            lock, existing, catalog = MagicMock(), MagicMock(), MagicMock()
            existing.scalars.return_value.first.return_value = None
            catalog.scalars.return_value.first.return_value = SimpleNamespace(metadata_json={
                'material_form': {'title': f'商品{i}', 'description': '完整原文', 'images': ['https://example.com/image.jpg'],
                                  'shipping_method': 'free', 'price': '1.00', 'quantity': 0},
            })
            results.extend([lock, existing, catalog])
        session.execute = AsyncMock(side_effect=results)
        session.commit = AsyncMock()
        inserted = []

        def add(material):
            material.id = len(inserted) + 1
            inserted.append(material)

        session.add.side_effect = add
        ids = [str(i) for i in range(1, 101)]
        output = await CatalogMaterialService(session).import_items(7, SimpleNamespace(id=3, owner_id=7), ids)
        self.assertEqual([row['item_id'] for row in output], ids)
        self.assertTrue(all(row['status'] == 'created' for row in output))
        self.assertEqual([material.catalog_item_id for material in inserted], ids)


if __name__ == '__main__':
    unittest.main()
