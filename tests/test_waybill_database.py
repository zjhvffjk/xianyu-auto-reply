"""真实MySQL事务验证。仅使用连接私有临时表，绝不修改业务表或访问平台。"""
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.mysql import dialect

sys.path.insert(0, '/app/backend-web')
from common.db.session import async_engine
from common.db.waybill_schema import WAYBILL_DDL
from common.models.xy_order import XYOrder
from common.models.xy_catalog_item import XYCatalogItem
from common.models.waybill import WaybillConnection, WaybillRecord
from common.services.waybill_client import WaybillRemoteError
from app.api.routes.waybills import ConnectionInput
from app.services.waybill_service import WaybillService


class WaybillDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await async_engine.connect()
        self.names = ['xy_waybill_authorizations', 'xy_waybill_platform', 'xy_waybill_connections', 'xy_waybill_records', 'xy_orders', 'xy_catalog_items']
        for name in self.names:
            await self.conn.execute(text(f'DROP TEMPORARY TABLE IF EXISTS {name}'))
        for ddl in WAYBILL_DDL.values():
            await self.conn.execute(text(ddl.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TEMPORARY TABLE')))
        for table in [XYOrder.__table__, XYCatalogItem.__table__]:
            ddl = str(CreateTable(table).compile(dialect=dialect()))
            await self.conn.execute(text(ddl.replace('CREATE TABLE', 'CREATE TEMPORARY TABLE', 1)))
        await self.conn.commit()
        self.db = AsyncSession(bind=self.conn, expire_on_commit=False)
        self.secret_patch = patch('app.services.waybill_service.get_settings', return_value=SimpleNamespace(jwt_secret_key='only-for-unit-test-32-char-secret'))
        self.secret_patch.start()
        self.account = SimpleNamespace(id=990001, owner_id=990001, account_id='waybill-unit-shop', display_name='隔离测试店', status='active')
        self.service = WaybillService(self.db, self.account, legacy_allowed=True)
        await self.service.save_settings(ConnectionInput(app_key='unit-test-app', app_secret='unit-app-secret'))
        config = await self.service.connection()
        config.verified_at = datetime.now()
        self.db.add(XYOrder(id=990001, owner_id=990001, account_id=self.account.account_id, order_no='unit-order-1',
                            item_id='unit-item-1', quantity=1, amount='1.00', status='pending_ship',
                            receiver_name='', receiver_phone='', receiver_address=''))
        self.db.add(XYCatalogItem(id=990001, owner_id=990001, account_pk=990001, item_id='unit-item-1',
                                  title='隔离测试商品', created_at=datetime.now(), metadata_json={
                                      'material_form': {'images': ['https://example.com/unit.jpg']}}))
        await self.db.commit()
        self.client = SimpleNamespace(call=AsyncMock(return_value={'success': True}))
        self.service.client = lambda config: self.client
        self.recipient = dict(name='测试收件人', phone='13800138000', province='浙江省', city='杭州市', county='西湖区', address='单元测试路1号')

    async def asyncTearDown(self):
        self.secret_patch.stop()
        await self.db.rollback()
        await self.db.close()
        for name in self.names:
            await self.conn.execute(text(f'DROP TEMPORARY TABLE IF EXISTS {name}'))
        await self.conn.commit()
        await self.conn.close()
        await async_engine.dispose()

    async def test_sync_commit_and_reopen_preserves_encrypted_recipient(self):
        result = await self.service.sync('unit-order-1', self.recipient)
        self.assertEqual(result['status'], 'synced')
        self.assertIsNotNone(result['updated_at'])
        preview = (await self.service.preview(['unit-order-1']))[0]
        self.assertEqual(preview['recipient'], self.recipient)
        self.assertEqual(preview['record']['status'], 'synced')
        record = (await self.db.execute(select(WaybillRecord))).scalars().one()
        self.assertNotIn('测试收件人', record.recipient_ciphertext)
        self.assertNotIn('13800138000', record.recipient_ciphertext)
        config = await self.service.connection()
        self.assertNotIn('unit-app-secret', config.credentials_ciphertext)
        settings = await self.service.settings()
        self.assertNotIn('credentials_ciphertext', settings)
        self.assertNotIn('unit-app-secret', str(settings))

    async def test_number_commit_returns_original_and_does_not_mark_shipped(self):
        await self.service.sync('unit-order-1', self.recipient)
        self.client.call.reset_mock()
        self.client.call.side_effect = [
            {'success': True, 'data': [{'modeListShows': [{'modeListshowId': 'template1', 'excodeName': '圆通', 'enableStatus': True}]}]},
            {'success': True, 'data': [{'tid': 'xy_990001_unit-order-1', 'success': True, 'waybillNo': 'YT123456789'}]},
        ]
        result = await self.service.number('unit-order-1', 'template1')
        self.assertEqual(result['status'], 'waybill_ready')
        self.assertEqual(result['platform_status'], 'pending_ship')
        self.assertEqual(result['waybill_no'], 'YT123456789')
        repeated = await self.service.number('unit-order-1', 'template-other')
        self.assertEqual(repeated['waybill_no'], 'YT123456789')
        self.assertEqual(self.client.call.await_count, 2)
        order = await self.service._order('unit-order-1')
        self.assertIsNone(order.delivery_content)
        self.assertEqual(order.status, 'pending_ship')

    async def test_uncertain_number_persists_and_cannot_retry(self):
        await self.service.sync('unit-order-1', self.recipient)
        self.client.call.side_effect = [
            {'success': True, 'data': [{'modeListShows': [{'modeListshowId': 'template1', 'enableStatus': True}]}]},
            WaybillRemoteError('未确认', uncertain=True),
        ]
        result = await self.service.number('unit-order-1', 'template1')
        self.assertEqual(result['status'], 'number_unknown')
        count = self.client.call.await_count
        await self.service.number('unit-order-1', 'template1')
        self.assertEqual(self.client.call.await_count, count)

    async def test_cannot_rebind_existing_record_or_share_remote_shop(self):
        await self.service.sync('unit-order-1', self.recipient)
        with self.assertRaises(HTTPException) as caught:
            await self.service.save_settings(ConnectionInput(app_key='another-app', app_secret='another-secret'))
        self.assertEqual(caught.exception.status_code, 409)
        other = WaybillService(self.db, SimpleNamespace(id=990002, owner_id=990002), legacy_allowed=True)
        with self.assertRaises(HTTPException) as caught:
            await other.save_settings(ConnectionInput(app_key='unit-test-app', app_secret='unit-app-secret'))
        self.assertEqual(caught.exception.status_code, 409)

    async def test_live_order_change_blocks_number_before_any_provider_request(self):
        await self.service.sync('unit-order-1', self.recipient)
        self.client.call.reset_mock()
        order = await self.service._order('unit-order-1')
        order.status = 'refunding'
        await self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            await self.service.number('unit-order-1', 'template1')
        self.assertEqual(caught.exception.status_code, 409)
        self.client.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
