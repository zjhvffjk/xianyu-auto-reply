"""验证退款专用策略之外仍保留原通知与日志，不向买家额外发送AI回复。"""
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
sys.path.insert(0, '/app/websocket')
from app.services.xianyu.auto_reply_service import AutoReplyService


class RefundNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def run_card(self, filters):
        sender = NS(myid='test-seller', send_msg=AsyncMock())
        service = AutoReplyService('test-refund-notification', sender)
        service.get_filter_keywords = AsyncMock(return_value=filters)
        service._send_notification = AsyncMock()
        service._record_auto_reply_log = AsyncMock(return_value=None)
        await service.handle_chat_message(dict(send_user_id='test-buyer', send_user_name='测试',
            send_message='[我发起了退款申请]', chat_id='test-chat', item_id='test-item',
            msg_time='2026-10-26 01:00:00', raw_message={}), object())
        sender.send_msg.assert_not_awaited()
        self.assertEqual(service._record_auto_reply_log.call_args.args[0]['decision_reason'], 'system_message')
        return service

    async def test_refund_card_keeps_notification_and_log(self):
        service = await self.run_card([])
        service._send_notification.assert_awaited_once()

    async def test_existing_notification_filter_is_respected(self):
        service = await self.run_card(['退款'])
        service._send_notification.assert_not_awaited()


if __name__ == '__main__': unittest.main()
