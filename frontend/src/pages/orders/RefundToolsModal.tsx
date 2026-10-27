import { useEffect, useRef, useState } from 'react'
import { X, RefreshCw } from 'lucide-react'
import { getAccountOptionLabel } from '@/utils/accountLabel'
import { getApiErrorMessage } from '@/utils/request'
import { useUIStore } from '@/store/uiStore'
import type { Account } from '@/types'
import { getRefundSettings, saveRefundSettings, getRefundApplications, prepareRefundApprovals,
  type RefundMessageSettings, type RefundMessageRecord, type RefundApplicationsResponse, type RefundApprovalResult } from '@/api/refundTools'
import { RefundApprovalQueue, refundApprovalStatusNames } from './RefundApprovalQueue'

const initial: RefundMessageSettings = { enabled: false, unshipped_enabled: false,
  shipped_enabled: false, unshipped_content: '', shipped_content: '' }
const defaults = {
  unshipped: '已收到你的退款申请，我会尽快核实处理。如有其他问题，可以在这里留言。',
  shipped: '已收到你的退款申请，我会核实已发送的商品内容和订单情况，尽快与你沟通处理。',
}
const statusNames: Record<string, string> = { processing: '处理结果待核实', submitted: '已提交消息',
  failed: '发送失败', unknown: '结果未知' }

export function RefundToolsModal({ accounts, accountId, onClose }: {
  accounts: Account[]; accountId: string; onClose: () => void
}) {
  const { addToast } = useUIStore()
  const [shop, setShop] = useState(accountId || accounts[0]?.id || '')
  const [tab, setTab] = useState<'messages' | 'refunds'>('messages')
  const [settings, setSettings] = useState(initial)
  const [saved, setSaved] = useState(initial)
  const [records, setRecords] = useState<RefundMessageRecord[]>([])
  const [applications, setApplications] = useState<RefundApplicationsResponse | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmed, setConfirmed] = useState(false)
  const [preview, setPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [approvals, setApprovals] = useState<RefundApprovalResult[]>([])
  const [approvalBusy, setApprovalBusy] = useState(false)
  const preparing = useRef(false)
  const epoch = useRef(0)

  const load = async () => {
    const version = ++epoch.current
    setBusy(true); setError(''); setSelected(new Set()); setConfirmed(false)
    setLoaded(false)
    setApplications(null); setRecords([])
    try {
      if (!shop) return
      if (tab === 'messages') {
        const result = await getRefundSettings(shop)
        if (version !== epoch.current) return
        setSettings(result.data); setSaved(result.data); setRecords(result.records)
      } else {
        const result = await getRefundApplications(shop)
        if (version !== epoch.current) return
        setApplications(result)
      }
      setLoaded(true)
    } catch (e) {
      if (version === epoch.current) setError(getApiErrorMessage(e, '读取失败，请重试'))
    } finally { if (version === epoch.current) setBusy(false) }
  }
  useEffect(() => { void load(); return () => { epoch.current++ } }, [shop, tab])
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving && !approvalBusy) onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [saving, approvalBusy, onClose])

  const save = async () => {
    setSaving(true); setError('')
    try {
      await saveRefundSettings(shop, settings)
      setSaved(settings); addToast({ type: 'success', message: '退款消息配置已保存' })
    } catch (e) { setError(getApiErrorMessage(e, '保存失败，当前修改仍保留')) }
    finally { setSaving(false) }
  }
  const chosen = applications?.data.filter(row => selected.has(row.refund_id)) || []
  const totalCents = chosen.reduce((sum, row) => sum + Math.round(Number(row.refund_amount) * 100), 0)
  const selectable = applications?.data.filter(row => row.eligible) || []
  const prepare = async () => {
    if (preparing.current || !confirmed || !chosen.length) return
    preparing.current = true; setApprovalBusy(true); setError('')
    try {
      const result = await prepareRefundApprovals(shop, chosen.map(row => ({
        order_no: row.order_no, refund_id: row.refund_id, refund_amount: row.refund_amount!,
      })))
      setApprovals(result.data)
    } catch (e) { setError(getApiErrorMessage(e, '准备失败，请刷新处理记录后核实')) }
    finally { preparing.current = false; setApprovalBusy(false) }
  }

  return <div className="modal-overlay" role="presentation">
    <div className="modal-content max-w-4xl flex flex-col max-h-[90vh]" role="dialog" aria-modal="true" aria-labelledby="refund-tools-title">
      <div className="modal-header"><h3 id="refund-tools-title" className="modal-title">退款处理</h3>
        <button className="modal-close" aria-label="关闭退款处理" disabled={saving || approvalBusy} onClick={onClose}><X className="w-5 h-5" /></button></div>
      <div className="px-5 pt-4 space-y-3">
        <label className="flex items-center gap-3 text-sm">店铺
          <select className="input-ios max-w-sm" value={shop} disabled={saving || approvalBusy || !!approvals.length} onChange={e => setShop(e.target.value)}>
            {accounts.map(account => <option key={account.id} value={account.id}>{getAccountOptionLabel(account)}</option>)}
          </select>
        </label>
        <div className="flex gap-5 border-b" role="tablist" aria-label="退款处理功能">
          {([['messages', '退款发消息'], ['refunds', '批量同意退款']] as const).map(([key, title]) =>
            <button key={key} role="tab" aria-selected={tab === key} disabled={saving || approvalBusy || !!approvals.length}
              className={`pb-3 text-sm border-b-2 ${tab === key ? 'border-blue-500 text-blue-600' : 'border-transparent text-gray-500'}`}
              onClick={() => { setTab(key); setPreview(null) }}>{title}</button>)}
        </div>
      </div>
      <div className="modal-body overflow-y-auto flex-1 space-y-4">
        {error && <p role="alert" className="rounded-lg p-3 text-sm bg-red-50 text-red-600">{error}</p>}
        {!shop ? <p>请先添加店铺。</p> : busy ? <p className="text-sm text-gray-500">正在读取…</p> : !loaded ?
          <button className="btn-ios-secondary" onClick={() => void load()}>重新读取</button> : tab === 'messages' ? <>
          <p className="text-sm text-gray-500">买家申请退款时发送。仅处理启用后收到的新申请；同一订单最多自动发送一次。</p>
          <label className="flex gap-2 items-center font-medium text-sm"><input type="checkbox" checked={settings.enabled}
            onChange={e => setSettings({ ...settings, enabled: e.target.checked })} />启用买家申请退款发消息</label>
          {(['unshipped', 'shipped'] as const).map(kind => <section key={kind} className="border rounded-lg p-4 space-y-3">
            <label className="flex items-center gap-2 text-sm font-medium"><input type="checkbox" checked={settings[`${kind}_enabled`]}
              onChange={e => setSettings({ ...settings, [`${kind}_enabled`]: e.target.checked })} />
              {kind === 'unshipped' ? '未发货订单' : '已发货订单'}</label>
            <p className="text-xs text-gray-500">{kind === 'unshipped' ? '没有已发货或已取卡记录的关联订单。' : '有已发货或已取卡记录的关联订单。'}</p>
            <textarea aria-label={kind === 'unshipped' ? '未发货退款消息' : '已发货退款消息'} className="input-ios w-full h-28 resize-none"
              value={settings[`${kind}_content`]} maxLength={1500} placeholder="输入买家申请退款后发送的消息"
              onChange={e => setSettings({ ...settings, [`${kind}_content`]: e.target.value })} />
            <div className="flex gap-3 text-xs items-center flex-wrap">
              <button className="text-blue-600" disabled={!settings[`${kind}_content`].trim()} onClick={() => setPreview(settings[`${kind}_content`])}>消息预览</button>
              <button className="text-blue-600" onClick={() => setSettings({ ...settings, [`${kind}_content`]: defaults[kind] })}>填充默认文案</button>
              <button className="text-gray-500" onClick={() => setSettings({ ...settings, [`${kind}_content`]: saved[`${kind}_content`] })}>撤销文案修改</button>
              <span className="ml-auto text-gray-400">{settings[`${kind}_content`].length}/1500</span>
            </div>
          </section>)}
          {preview !== null && <div className="rounded-lg bg-slate-50 dark:bg-slate-800 p-4 space-y-2" role="status">
            <div className="flex justify-between text-sm font-medium">消息预览<button onClick={() => setPreview(null)} className="text-gray-500">收起</button></div>
            <p className="whitespace-pre-wrap text-sm">{preview}</p></div>}
          <section className="space-y-2"><h4 className="text-sm font-medium">最近消息处理记录</h4>
            {records.length ? records.map(record => <div key={record.id} className="text-xs border-b py-2 space-y-1">
              <p>{record.order_no} · {statusNames[record.status] || record.status} · {record.created_at.replace('T', ' ')}</p>
              <p className="text-gray-500">{record.detail}</p></div>) : <p className="text-xs text-gray-400">暂无处理记录</p>}
          </section>
        </> : approvals.length ? <RefundApprovalQueue accountId={shop} initial={approvals} onBusyChange={setApprovalBusy} /> : <>
          <p className="rounded-lg bg-amber-50 text-amber-800 p-3 text-sm">{applications?.capability_message}</p>
          <div className="flex justify-between items-center gap-3 text-sm"><span>仅核对等待卖家处理的已有“仅退款”申请</span>
            <button className="btn-ios-secondary btn-sm flex gap-1 items-center" onClick={() => void load()}><RefreshCw className="w-3 h-3" />重新核对</button></div>
          <div className="overflow-x-auto border rounded-lg"><table className="table-ios w-full"><thead><tr>
            <th><input type="checkbox" aria-label="选择全部可核对申请" disabled={!selectable.length}
              checked={!!selectable.length && selectable.every(row => selected.has(row.refund_id))}
              onChange={e => { setSelected(new Set(e.target.checked ? selectable.map(row => row.refund_id) : [])); setConfirmed(false) }} /></th>
            <th>商品 / 订单号</th><th>申请退款金额</th><th>类型 / 状态</th>
          </tr></thead><tbody>
            {applications?.data.map(row => <tr key={`${row.refund_id}-${row.order_no}`}>
              <td><input type="checkbox" aria-label={`选择退款申请 ${row.order_no}`} disabled={!row.eligible} checked={selected.has(row.refund_id)}
                onChange={e => { setSelected(prev => { const next = new Set(prev); if (e.target.checked) next.add(row.refund_id); else next.delete(row.refund_id); return next }); setConfirmed(false) }} /></td>
              <td><p className="max-w-xs truncate" title={row.title}>{row.title}</p><p className="text-xs text-gray-400">{row.order_no}</p>
                <p className="text-xs text-gray-400">申请号：{row.refund_id}</p><p className="text-xs text-gray-500">{row.reason}</p></td>
              <td className="whitespace-nowrap">{row.refund_amount === null ? '无法核实' : `¥${row.refund_amount}`}</td>
              <td><p>{row.refund_type}</p><p className="text-xs text-gray-500">{row.status}</p>
                {row.blocked_reason && <p className="text-xs text-red-500">{row.blocked_reason}</p>}</td>
            </tr>)}
            {!applications?.data.length && <tr><td colSpan={4} className="text-center text-gray-400 py-8">暂无待处理申请</td></tr>}
          </tbody></table></div>
          {applications?.limited && <p className="text-xs text-amber-700">当前仅展示平台返回的前20条，请到官方后台查看其余申请。</p>}
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/30 p-3 text-sm">已选 {chosen.length} 笔，实际申请退款合计 <strong>¥{(totalCents / 100).toFixed(2)}</strong></div>
          {!!chosen.length && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我已核对所选申请和实际退款金额，同意在逐笔验证后执行退款</label>}
          <p className="text-xs text-gray-500">核对时间：{applications?.checked_at.replace('T', ' ')}（北京时间）。准备和核对不会退款，官方验证完成后才提交。</p>
          {!!applications?.history.length && <section className="space-y-2"><h4 className="text-sm font-medium">最近退款处理记录</h4>
            {applications.history.map(op => <div className="text-xs border-b py-2" key={op.id}>
              <p>{op.order_no} · ¥{op.refund_amount} · <strong className={op.status === 'success' ? 'text-green-600' : ''}>{refundApprovalStatusNames[op.status] || op.status}</strong></p>
              <p className="text-gray-500 mt-1">{op.detail}</p>
              {['queued', 'awaiting_verification', 'expired', 'verification_failed'].includes(op.status) && <button className="text-blue-600 mt-1" onClick={() => setApprovals([op])}>继续该笔处理</button>}
            </div>)}
          </section>}
        </>}
      </div>
      <div className="modal-footer flex items-center justify-between gap-3">
        <button className="btn-ios-secondary" disabled={saving || approvalBusy} onClick={onClose}>关闭</button>
        {tab === 'messages' ? <button className="btn-ios-primary" disabled={!shop || busy || saving || !loaded} onClick={() => void save()}>{saving ? '保存中…' : '保存消息配置'}</button> :
          approvals.length ? <button className="btn-ios-secondary" disabled={approvalBusy} onClick={() => { setApprovals([]); void load() }}>返回申请列表</button> :
          <button className="btn-ios-primary" disabled={!confirmed || !chosen.length || approvalBusy || busy} onClick={() => void prepare()}>{approvalBusy ? '核对中…' : `同意所选退款（${chosen.length}笔）`}</button>}
      </div>
    </div>
  </div>
}
