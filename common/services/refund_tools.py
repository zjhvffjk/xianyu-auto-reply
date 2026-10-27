"""退款规则与官方列表解析。不执行退款，不把订单金额当申请金额。"""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


def message_content_for(config, order, event_at: datetime | None, now: datetime):
    if not config or not config.enabled or not config.enabled_at or not event_at:
        return None
    if event_at < config.enabled_at or not timedelta(seconds=-30) <= now-event_at <= timedelta(minutes=5):
        return None
    if not order or order.status not in {'refunding', 'pending_ship', 'shipped', 'processing', 'processed'}:
        return None
    shipped = bool(order.delivery_content or order.card_only_delivered or order.status == 'shipped')
    prefix = 'shipped' if shipped else 'unshipped'
    if not getattr(config, prefix+'_enabled'):
        return None
    return (getattr(config, prefix+'_content') or '').strip() or None


def parse_refund_application(item: dict) -> dict:
    common = item.get('commonData') or {}
    info = item.get('refundInfoVO') or {}
    price = item.get('priceVO') or {}
    amount = None
    try:
        value = Decimal(str(price.get('refundFee')))
        if value.is_finite() and 0 < value <= Decimal('9999999999.99') and value == value.quantize(Decimal('.01')):
            amount = format(value, '.2f')
    except (InvalidOperation, ValueError, TypeError):
        pass
    refund_id = str(info.get('refundId') or '')
    action_found = False
    # 只接受实际观察过的官方查询操作，不执行响应中任意接口/URL。
    for button in (item.get('rightVO') or {}).get('btnList') or []:
        if button.get('code') != 'agreeRefundApply':
            continue
        buttons = (((button.get('clickEvent') or {}).get('data') or {}).get('doubleCheck') or {}).get('doubleCheckVO') or {}
        for confirm in buttons.get('buttonList') or []:
            api = (((confirm.get('clickEvent') or {}).get('data') or {}).get('mtop') or {})
            if (confirm.get('code') == 'agreeRefundApply'
                    and api.get('apiName') == 'mtop.taobao.idle.merchant.refund.agree.url.query'
                    and api.get('apiVersion') == '1.0'
                    and str((api.get('params') or {}).get('refundId') or '') == refund_id):
                action_found = True
    reason = ''
    if str(info.get('refundType')) != '1' or str(info.get('goodsNeeds')) != '0':
        reason = '不是可确认的仅退款申请'
    elif str(common.get('refundStatus')) != '1':
        reason = '不在等待卖家处理状态'
    elif not common.get('orderId') or not refund_id:
        reason = '缺少订单号或退款申请号'
    elif amount is None:
        reason = '无法核实实际申请金额'
    elif not action_found:
        reason = '平台未提供已验证的同意退款入口'
    return dict(order_no=str(common.get('orderId') or ''), refund_id=refund_id,
                title=(item.get('itemVO') or {}).get('title') or '',
                refund_amount=amount, refund_type='仅退款' if str(info.get('refundType')) == '1' else '其他/未知',
                status=info.get('refundStatus') or common.get('orderStatus') or '未知',
                reason=info.get('reason') or '', eligible=not reason, blocked_reason=reason,
                requires_verification=True)
