/** 仅当前官方验证框的成功回调可推进退款；其他页面不能代替买家/店主验证。 */
export function isVerifiedRefundCallback(
  event: Pick<MessageEvent, 'origin' | 'source' | 'data'>,
  expectedSource: MessageEventSource | null,
  verificationUrl: string,
): boolean {
  if (!expectedSource || event.source !== expectedSource) return false
  let url: URL
  try { url = new URL(verificationUrl) } catch { return false }
  if (url.protocol !== 'https:' || url.hostname !== 'pcauth-site.alipay.com'
    || url.username || url.password || url.port || url.pathname !== '/home'
    || event.origin !== url.origin) return false
  let data
  try { data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data } catch { return false }
  return data?.type === 'verify' && String(data?.result?.code) === '1000'
}
