import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI

sys.path.insert(0, '/app/backend-web')
from app.api.routes import waybills
from app.services.waybill_service import WaybillService, source_hash, recipient_from_order, order_problems


class WaybillRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_remote_shop_id_is_canonical_positive_long(self):
        from pydantic import ValidationError
        self.assertEqual(waybills.ConnectionInput(app_key='test', mall_user_id='00123').mall_user_id, '123')
        self.assertEqual(waybills.ConnectionInput(app_key='test').mall_user_id, '')
        for value in ['0', '-1', '9223372036854775808']:
            with self.assertRaises(ValidationError):
                waybills.ConnectionInput(app_key='test', mall_user_id=value)

    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(waybills.router)
        empty = MagicMock()
        empty.scalars.return_value.first.return_value = None
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=empty)
        self.app.dependency_overrides[waybills.get_current_active_user] = lambda: SimpleNamespace(id=7, role='USER')
        self.app.dependency_overrides[waybills.get_db_session] = lambda: self.db
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.http.aclose()

    async def test_other_users_account_cannot_read_or_mutate(self):
        for method, suffix, data in [('get','settings',None), ('put','settings',{'app_key':'test'}),
                                     ('post','templates',None), ('post','preview',{'order_nos':['1']}),
                                     ('post','number',{'order_no':'1','template_id':'2'}),
                                     ('post','workbench',None), ('get','records',None)]:
            response = await self.http.request(method, f'/waybills/other/{suffix}', json=data)
            self.assertEqual(response.status_code, 404, (method, suffix))
        query = str(self.db.execute.call_args.args[0].compile(compile_kwargs={'literal_binds': True}))
        self.assertIn('owner_id = 7', query)

    async def test_batch_request_is_bounded_and_unique(self):
        self.app.dependency_overrides[waybills.service_for] = lambda: SimpleNamespace(preview=AsyncMock(return_value=[]))
        for values in [[], ['1'] * 2, [str(i) for i in range(101)], ['a'*65]]:
            self.assertEqual((await self.http.post('/waybills/shop/preview', json={'order_nos':values})).status_code, 422)
        self.assertEqual((await self.http.post('/waybills/shop/preview', json={'order_nos':[str(i) for i in range(100)]})).status_code, 200)

    async def test_unconfigured_connection_does_not_call_provider(self):
        service = WaybillService(self.db, SimpleNamespace(id=1, owner_id=7), legacy_allowed=True)
        self.app.dependency_overrides[waybills.service_for] = lambda: service
        response = await self.http.post('/waybills/shop/templates')
        self.assertEqual(response.status_code, 409)
        self.assertIn('尚未配置', response.json()['detail'])

    async def test_repeat_number_returns_original_without_request(self):
        order = SimpleNamespace(status='pending_ship')
        record = SimpleNamespace(id='r1', order_no='1', status='waybill_ready', detail='',
                                 waybill_no='YT123456789', carrier='圆通', template_id='t1', updated_at=None)
        service = WaybillService(self.db, SimpleNamespace(id=1, owner_id=7), legacy_allowed=True)
        service.connection = AsyncMock(return_value=SimpleNamespace(verified_at=True))
        service._record = AsyncMock(return_value=record)
        service._order = AsyncMock(return_value=order)
        self.db.rollback = AsyncMock()
        result = await service.number('1', 'different-template')
        self.assertEqual(result['waybill_no'], 'YT123456789')
        self.assertEqual(result['template_id'], 't1')

    async def test_pending_unknown_number_never_retries(self):
        record = SimpleNamespace(id='r1', order_no='1', status='number_unknown', detail='待核对',
                                 waybill_no='', carrier='', template_id='t1', updated_at=None)
        service = WaybillService(self.db, SimpleNamespace(id=1, owner_id=7), legacy_allowed=True)
        service.connection = AsyncMock(return_value=SimpleNamespace(verified_at=True))
        service._record = AsyncMock(return_value=record)
        service._order = AsyncMock(return_value=SimpleNamespace(status='pending_ship'))
        self.db.rollback = AsyncMock()
        self.assertEqual((await service.number('1','t1'))['status'], 'number_unknown')

    def test_recipient_parsing_and_state_gate(self):
        order = SimpleNamespace(receiver_name='测试', receiver_phone='13800138000',
                                receiver_address='浙江省杭州市西湖区测试路1号', status='refunding',
                                card_only_delivered=False, item_id='1', quantity=1, amount='1.00')
        self.assertEqual(recipient_from_order(order)['address'], '测试路1号')
        self.assertEqual(recipient_from_order(order)['county'], '西湖区')
        order.receiver_address='北京市朝阳区测试路1号'
        self.assertEqual(recipient_from_order(order)['city'], '北京市')
        self.assertTrue(order_problems(order))
        order.status='pending_ship'
        self.assertEqual(order_problems(order), [])
        order.card_only_delivered=True
        self.assertTrue(order_problems(order))


if __name__ == '__main__':
    unittest.main()
