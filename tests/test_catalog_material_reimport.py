"""在连接私有 MySQL 临时表验证删除后重导入，不接触真实素材。"""
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.mysql import dialect

sys.path.insert(0, '/app/backend-web')
from common.db.session import async_engine
from common.models.product_material import ProductMaterial
from common.models.xy_catalog_item import XYCatalogItem
from common.models.xy_account import XYAccount
from app.services.catalog_material_service import CatalogMaterialService


class CatalogMaterialReimportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await async_engine.connect()
        self.tables = [ProductMaterial.__table__, XYCatalogItem.__table__, XYAccount.__table__]
        for table in self.tables:
            ddl = str(CreateTable(table).compile(dialect=dialect()))
            await self.conn.execute(text(ddl.replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', 1)))
        # CreateTable does not include the separately declared source uniqueness index.
        await self.conn.execute(text('CREATE UNIQUE INDEX uq_pm_catalog_source ON xy_product_materials (user_id, catalog_account_pk, catalog_item_id)'))
        await self.conn.commit()
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)
        self.account = SimpleNamespace(id=3, owner_id=7)
        self.db.add(XYCatalogItem(owner_id=7, account_pk=3, item_id='123', title='来源商品', created_at=datetime.now(), metadata_json={
            'material_form': dict(title='来源商品', description='完整描述', price='12.00',
                                  quantity=1, images=['https://example.com/item.jpg'], shipping_method='free')
        }))
        await self.db.commit()
        self.service = CatalogMaterialService(self.db)

    async def asyncTearDown(self):
        await self.db.rollback()
        await self.db.close()
        for table in self.tables:
            await self.conn.execute(text(f'DROP TEMPORARY TABLE {table.name}'))
        await self.conn.commit()
        await self.conn.close()
        await async_engine.dispose()

    async def imported(self):
        result = (await self.service.import_items(7, self.account, ['123']))[0]
        return result, await self.db.get(ProductMaterial, result['material_id'])

    async def test_deleted_material_can_be_reimported_without_reusing_old_record(self):
        _, old = await self.imported()
        old_id = old.id
        old.is_deleted = True
        old.title = '删除前的修改'
        await self.db.commit()
        result, new = await self.imported()
        self.assertEqual(result['status'], 'created')
        self.assertNotEqual(new.id, old_id)
        self.assertFalse(new.is_deleted)
        self.assertEqual(new.title, '来源商品')
        await self.db.refresh(old)
        self.assertTrue(old.is_deleted)
        self.assertEqual(old.title, '删除前的修改')
        self.assertIsNone(old.catalog_item_id)
        new_id = new.id
        again = (await self.service.import_items(7, self.account, ['123', '123']))
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]['status'], 'exists')
        self.assertEqual(again[0]['material_id'], new_id)

    async def test_existing_material_keeps_user_edits(self):
        _, material = await self.imported()
        material.title = '用户修改'
        await self.db.commit()
        result = (await self.service.import_items(7, self.account, ['123']))[0]
        self.assertEqual(result['status'], 'exists')
        await self.db.refresh(material)
        self.assertEqual(material.title, '用户修改')

    async def test_invalid_source_does_not_release_deleted_record(self):
        _, old = await self.imported()
        old.is_deleted = True
        item = (await self.db.execute(select(XYCatalogItem))).scalar_one()
        item.metadata_json = {}
        await self.db.commit()
        result = (await self.service.import_items(7, self.account, ['123']))[0]
        self.assertEqual(result['status'], 'failed')
        await self.db.refresh(old)
        self.assertEqual(old.catalog_item_id, '123')
        self.assertTrue(old.is_deleted)


if __name__ == '__main__':
    unittest.main()
