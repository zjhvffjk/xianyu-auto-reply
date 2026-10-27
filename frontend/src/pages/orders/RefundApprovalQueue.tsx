import { useEffect, useRef, useState } from 'react'
import { confirmRefundApproval, getRefundVerification, type RefundApprovalResult } from '@/api/refundTools'
import { getApiErrorMessage } from '@/utils/request'
import { isVerifiedRefundCallback } from '@/utils/refundVerification'

export const refundApprovalStatusNames: Record<string, string> = { queued: '等待处理', preparing: '准备验证中',
  awaiting_verification: '等待支付宝验证', submitting: '正在提交', success: '退款成功',
  submitted: '已受理，待确认',
  failed: '未完成', verification_failed: '验证页未就绪', conflict: '申请已变化', unknown: '结果未知', expired: '验证已过期' }

export function RefundApprovalQueue({ accountId, initial, onBusyChange }: {
  accountId: string; initial: RefundApprovalResult[]; onBusyChange: (busy: boolean) => void
}) {
  const [operations, setOperations] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [height, setHeight] = useState(340)
  const frame = useRef<HTMLIFrameElement>(null)
  const inFlight = useRef(false)
  const mounted = useRef(true)
  const started = useRef(new Set<string>())
  const active = operations.find(op => ['queued', 'awaiting_verification', 'expired', 'verification_failed'].includes(op.status))
  const replace = (result: RefundApprovalResult) => setOperations(previous =>
    previous.map(op => op.id === result.id ? result : op))
  const changeBusy = (value: boolean) => { setBusy(value); onBusyChange(value) }

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const loadVerification = async (id: string, refresh = false) => {
    if (inFlight.current) return
    inFlight.current = true; changeBusy(true); setError('')
    try {
      const result = await getRefundVerification(accountId, id, refresh)
      if (mounted.current) replace(result.data)
    } catch (e) { if (mounted.current) setError(getApiErrorMessage(e, '验证页读取失败，可以重试读取')) }
    finally { inFlight.current = false; if (mounted.current) changeBusy(false) }
  }
  useEffect(() => {
    if (active && !active.verification_url && !started.current.has(active.id)) {
      started.current.add(active.id)
      void loadVerification(active.id)
    }
  }, [active?.id, active?.verification_url])

  useEffect(() => {
    if (!active?.verification_url) return
    const origin = new URL(active.verification_url).origin
    const handle = async (event: MessageEvent) => {
      // 仅接受当前官方支付宝iframe的回调，不能信任其他标签或页面发来的消息。
      if (event.origin !== origin || event.source !== frame.current?.contentWindow || inFlight.current) return
      let data
      try { data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data } catch { return }
      if (data?.type === 'UPDATE_HEIGHT') {
        const next = Number(data.msg)
        if (Number.isFinite(next)) setHeight(Math.min(600, Math.max(180, next)))
      }
      if (!isVerifiedRefundCallback(event, frame.current?.contentWindow || null, active.verification_url!)) return
      inFlight.current = true; changeBusy(true); setError('')
      try {
        const result = await confirmRefundApproval(accountId, active.id)
        if (mounted.current) replace(result.data)
      } catch (e) {
        if (mounted.current) {
          setError(getApiErrorMessage(e, '提交结果暂未返回，请刷新处理记录核实；不要重复退款'))
          // 请求可能已触达平台，停止本轮，不因新回调自动再提交。
          replace({ ...active, status: 'unknown', verification_url: null, detail: '结果待核实，请刷新处理记录' })
        }
      } finally { inFlight.current = false; if (mounted.current) changeBusy(false) }
    }
    window.addEventListener('message', handle)
    return () => window.removeEventListener('message', handle)
  }, [active?.id, active?.verification_url])

  return <section className="space-y-4">
    <p className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">所选申请逐笔处理。关闭窗口会暂停后续操作，已提交的退款仍以平台结果为准。</p>
    <div className="space-y-2">{operations.map(op => <div key={op.id || op.refund_id} className="border rounded-lg p-3 text-sm">
      <div className="flex justify-between gap-3"><span>订单 {op.order_no} · ¥{op.refund_amount}</span>
        <strong className={op.status === 'success' ? 'text-green-600' : op.status === 'awaiting_verification' ? 'text-blue-600' : 'text-gray-600'}>{refundApprovalStatusNames[op.status] || op.status}</strong></div>
      <p className="text-xs text-gray-500 mt-1">{op.detail}</p>
    </div>)}</div>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    {busy ? <p className="text-sm text-blue-600">正在核对并处理当前申请，请稍候…</p> : active && <>
      <p className="text-sm font-medium">当前验证：订单 {active.order_no}，退款 ¥{active.refund_amount}。验证通过后将立即提交该笔退款。</p>
      {active.verification_url ? <>
        <p className="text-xs text-gray-500">请在下方支付宝官方页面完成验证，密码直接交给支付宝，本系统不收集或保存。</p>
        <iframe key={active.verification_url} ref={frame} src={active.verification_url} title="支付宝官方退款验证" className="w-full border rounded-lg bg-white" style={{ height }} />
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-ios-secondary btn-sm" onClick={() => void loadVerification(active.id, true)}>重新生成验证页</button>
          <p className="text-xs text-gray-500">验证页提示系统繁忙或失效时可重新生成；此操作不会提交退款。</p>
        </div>
      </> : <button className="btn-ios-secondary" onClick={() => void loadVerification(active.id)}>重新读取验证页</button>}
      <a className="text-sm text-blue-600" href={`https://seller.goofish.com/?site=COMMONPRO#/seller-trade/refund-manage/refund-detail?orderId=${encodeURIComponent(active.order_no)}&refundId=${encodeURIComponent(active.refund_id)}`}
        target="_blank" rel="noopener noreferrer">验证页无法使用？前往闲鱼官方核实处理</a>
    </>}
    {!active && !busy && <p className="text-sm text-gray-500">本轮处理已结束，请核对逐笔结果；未完成或结果未知的申请请到官方后台核实。</p>}
  </section>
}
