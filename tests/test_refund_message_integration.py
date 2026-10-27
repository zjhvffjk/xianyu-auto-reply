"""真实隔离MySQL验证：负数owner、唯一测试店铺；IM只有mock，无外部请求。"""
import asyncio
import sys
import unittest
from datetime import timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

sys.path.insert(0, '/app/backend-web')
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, delete
from common.db.session import async_session_maker, async_engine
from common.models.xy_account import XYAccount
from common.models.xy_order import XYOrder
from common.models.refund_message import RefundMessageConfig, RefundMessageRecord
from common.services.refund_message_service import send_refund_message, refund_event_at
from common.utils.time_utils import get_beijing_now_naive, BEIJING_TZ
from app.api.routes.refund_tools import MessageSettings, scoped_account, save_message_settings, message_settings

OWNER = -2026102506


class RefundMessageIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.account_id = 'test-refund-' + uuid4().hex[:18]
        self.order_no = 'test-' + uuid4().hex
        self.now = get_beijing_now_naive()
        self.send = AsyncMock(return_value='submitted')
        self.user = NS(id=OWNER, role='USER')
        async with async_session_maker() as s:
            s.add(XYAccount(owner_id=OWNER, account_id=self.account_id, cookie='', login_method='cookie', status='active'))
            s.add(XYOrder(owner_id=OWNER, account_id=self.account_id, order_no=self.order_no,
                          status='pending_ship', buyer_id='test-buyer', chat_id='test-chat'))
            s.add(RefundMessageConfig(owner_id=OWNER, account_id=self.account_id, enabled=True,
                  enabled_at=self.now-timedelta(minutes=1), unshipped_enabled=True,
                  shipped_enabled=True, unshipped_content='未发货', shipped_content='已发货'))
            await s.commit()

    async def asyncTearDown(self):
        async with async_session_maker() as s:
            for cls in (RefundMessageRecord, RefundMessageConfig, XYOrder, XYAccount):
                await s.execute(delete(cls).where(cls.account_id == self.account_id, cls.owner_id == OWNER))
            await s.commit()
        await async_engine.dispose()

    async def deliver(self, **kw):
        return await send_refund_message(async_session_maker, self.account_id, self.order_no,
            kw.get('chat', 'test-chat'), kw.get('event', self.now), self.send)

    async def test_persistent_concurrent_dedup_sends_once(self):
        results = await asyncio.gather(self.deliver(), self.deliver())
        self.assertEqual(sorted(results), ['duplicate', 'submitted'])
        self.send.assert_awaited_once_with('test-chat', 'test-buyer', '未发货')
        self.assertEqual(await self.deliver(), 'duplicate')

    async def test_failure_or_unknown_is_not_retried(self):
        self.send.side_effect = TimeoutError()
        self.assertEqual(await self.deliver(), 'unknown')
        self.assertEqual(await self.deliver(), 'duplicate')
        async with async_session_maker() as s:
            record = (await s.execute(select(RefundMessageRecord).where(RefundMessageRecord.account_id == self.account_id))).scalar_one()
            self.assertEqual(record.status, 'unknown')

    async def test_replay_and_chat_conflict_do_not_send(self):
        self.assertEqual(await self.deliver(event=self.now-timedelta(days=1)), 'skipped')
        self.assertEqual(await self.deliver(chat='wrong-chat'), 'missing_recipient')
        self.send.assert_not_awaited()

    async def test_shipped_status_uses_shipped_message_without_card_content(self):
        async with async_session_maker() as s:
            o = (await s.execute(select(XYOrder).where(XYOrder.order_no == self.order_no))).scalar_one()
            o.status = 'shipped'; await s.commit()
        self.assertEqual(await self.deliver(), 'submitted')
        self.assertEqual(self.send.call_args.args[-1], '已发货')

    async def test_scope_blocks_other_owner_even_with_known_account_id(self):
        async with async_session_maker() as s:
            with self.assertRaises(HTTPException) as exc:
                await scoped_account(s, NS(id=OWNER-1, role='USER'), self.account_id)
            self.assertEqual(exc.exception.status_code, 404)

    async def test_config_enable_time_and_persisted_roundtrip(self):
        async with async_session_maker() as s:
            await save_message_settings(self.account_id, MessageSettings(), s, self.user)
        async with async_session_maker() as s:
            await save_message_settings(self.account_id, MessageSettings(enabled=True,
                unshipped_enabled=True, unshipped_content='新的回复'), s, self.user)
        async with async_session_maker() as s:
            data = await message_settings(self.account_id, s, self.user)
            config = await s.get(RefundMessageConfig, self.account_id)
            self.assertTrue(data['data']['enabled'])
            self.assertEqual(data['data']['unshipped_content'], '新的回复')
            self.assertGreaterEqual(config.enabled_at, self.now.replace(microsecond=0))

    async def test_blank_enabled_template_rejected(self):
        with self.assertRaises(ValidationError):
            MessageSettings(enabled=True, unshipped_enabled=True, unshipped_content=' ')
        with self.assertRaises(ValidationError):
            MessageSettings(enabled=True)

    async def test_missing_event_timestamp_does_not_become_now(self):
        self.assertIsNone(refund_event_at({'1': {}}))
        self.assertIsNone(refund_event_at({'1': {'5': 'bad'}}))
        stamp = self.now.replace(tzinfo=BEIJING_TZ).timestamp()*1000
        self.assertLess(abs((refund_event_at({'1': {'5': stamp}})-self.now).total_seconds()), .01)


if __name__ == '__main__':
    unittest.main()
