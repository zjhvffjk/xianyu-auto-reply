import type { ManualDeliveryResponse } from '@/api/orders'

export interface DeliveryNotice {
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
}

/** 请求成功与每条卡券送达、平台发货完成是不同结果。 */
export function getDeliveryNotice(result: ManualDeliveryResponse): DeliveryNotice {
  const data = result.data
  if (!result.success) return {type: 'error', message: result.message || '发货失败，请核对订单详情'}
  const message = result.message || `发货处理完成${data?.card_name ? `：${data.card_name}` : ''}`
  if (data?.send_intercepted || (data?.send_failed_count ?? 0) > 0) {
    return {type: 'error', message}
  }
  const partial = data?.quantity_requested !== undefined && data.quantity_sent !== undefined
    && data.quantity_sent < data.quantity_requested && !data.quantity_degraded_for_disabled_switch
  if (data?.skipped_due_to_dock_card || data?.is_card_only || data?.early_break_reason
    || data?.quantity_degraded_for_dock_card || data?.quantity_degraded_for_fixed_content || partial) {
    return {type: 'warning', message}
  }
  return {type: data?.only_send_card ? 'info' : 'success', message}
}
