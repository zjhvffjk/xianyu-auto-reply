import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace as NS

from common.services.refund_tools import message_content_for, parse_refund_application


class RefundPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 25, 22)
        self.config = NS(enabled=True, enabled_at=self.now-timedelta(minutes=1),
                         unshipped_enabled=True, shipped_enabled=True,
                         unshipped_content='未发货回复', shipped_content='已发货回复')
        self.order = NS(status='refunding', delivery_content='', delivery_method='',
                        card_only_delivered=False, buyer_id='buyer', chat_id='chat')

    def content(self, event=None):
        return message_content_for(self.config, self.order, event or self.now, self.now)

    def test_message_branch_and_disabled(self):
        self.assertEqual(self.content(), '未发货回复')
        self.order.delivery_content = '已取卡'
        self.assertEqual(self.content(), '已发货回复')
        self.config.shipped_enabled = False
        self.assertIsNone(self.content())
        self.config.enabled = False
        self.assertIsNone(self.content())

    def test_replayed_future_terminal_and_unknown_events_do_not_send(self):
        self.assertIsNone(self.content(self.now-timedelta(hours=1)))
        self.assertIsNone(self.content(self.now+timedelta(minutes=3)))
        self.order.status = 'refunded'
        self.assertIsNone(self.content())
        self.assertIsNone(message_content_for(self.config, self.order, None, self.now))

    def test_order_refund_amount_is_not_order_amount(self):
        item = self.fixture()
        row = parse_refund_application(item)
        self.assertEqual(row['refund_amount'], '0.10')
        self.assertTrue(row['eligible'])
        self.assertEqual(row['refund_id'], 'refund-1')

    def fixture(self):
        mtop = dict(apiName='mtop.taobao.idle.merchant.refund.agree.url.query',
                    apiVersion='1.0', params=dict(refundId='refund-1'))
        button = dict(code='agreeRefundApply', clickEvent=dict(data=dict(mtop=mtop)))
        outer = dict(code='agreeRefundApply', clickEvent=dict(data=dict(
            doubleCheck=dict(doubleCheckVO=dict(buttonList=[button])))))
        return dict(commonData=dict(orderId='order-1', refundStatus='1'),
                    refundInfoVO=dict(refundId='refund-1', refundType='1', goodsNeeds='0'),
                    priceVO=dict(auctionPrice='1.01', refundFee='0.10'),
                    itemVO=dict(title='测试商品'),
                    rightVO=dict(btnList=[outer]))

    def test_invalid_type_amount_action_and_state_are_blocked(self):
        for section, key, value in [('refundInfoVO','refundType','2'),
                ('refundInfoVO','goodsNeeds','1'), ('commonData','refundStatus','5'),
                ('priceVO','refundFee','NaN'), ('priceVO','refundFee','-1'),
                ('priceVO','refundFee','0.101'), ('priceVO','refundFee',None)]:
            with self.subTest(key=key, value=value):
                item = self.fixture(); item[section][key] = value
                self.assertFalse(parse_refund_application(item)['eligible'])
        item = self.fixture(); item['rightVO'] = {}
        self.assertFalse(parse_refund_application(item)['eligible'])

    def test_untrusted_action_api_and_refund_id_are_blocked(self):
        item = self.fixture()
        action = item['rightVO']['btnList'][0]['clickEvent']['data']['doubleCheck']['doubleCheckVO']['buttonList'][0]['clickEvent']['data']['mtop']
        action['params']['refundId'] = 'other'
        self.assertFalse(parse_refund_application(item)['eligible'])


if __name__ == '__main__':
    unittest.main()
