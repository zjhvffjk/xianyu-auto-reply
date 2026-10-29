import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Copy, ExternalLink, Loader2, Printer, RefreshCw, Truck, X } from 'lucide-react'
import { getAccountOptionLabel } from '@/utils/accountLabel'
import { getApiErrorMessage } from '@/utils/request'
import { getOrders, getOrderDetail } from '@/api/orders'
import { Pager } from '@/components/common/Pager'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { WaybillPlatformSettings } from './WaybillPlatformSettings'
import { WaybillShopAuthorization } from './WaybillShopAuthorization'
import type { Account, Order } from '@/types'
import {
  getWaybillSettings, saveWaybillSettings, getWaybillTemplates, previewWaybills,
  syncWaybill, numberWaybill, getWaybillWorkbench, getWaybillRecords,
  type WaybillSettings, type WaybillPreview, type WaybillRecord, type WaybillTemplate, type WaybillRecipient,
} from '@/api/waybills'

const emptySettings: WaybillSettings = { configured: false, app_key: '', has_secret: false, login_user: '', mall_user_id: '', verified_at: null,
  platform_configured: false, legacy_allowed: false, authorization_available: false, embedded_print_available: false }
const stateNames: Record<string, string> = {
  syncing: '同步结果待核对', synced: '已同步', sync_failed: '同步失败', sync_unknown: '同步结果待核对',
  numbering: '取号结果待核对', number_unknown: '取号结果待核对', number_failed: '取号失败', waybill_ready: '已取号',
}
const platformNames: Record<string, string> = { pending_ship: '待发货', shipped: '已发货', completed: '已完成', refunding: '退款中', refunded: '已退款', cancelled: '已关闭' }
function recipientReady(value: WaybillRecipient) {
  return Object.values(value).every(v => v.trim() && !/[*＊●•]/.test(v)) && /^[+\d][\d\s()\-]{5,30}$/.test(value.phone)
}

export function WaybillToolsModal({ accounts, accountId, selectedOrders, onClose }: {
  accounts: Account[]; accountId: string; selectedOrders: Order[]; onClose: () => void
}) {
  const uniqueShops = [...new Set(selectedOrders.map(o => o.cookie_id))]
  const [shop, setShop] = useState(accountId || (uniqueShops.length === 1 ? uniqueShops[0] : accounts[0]?.id || ''))
  const [tab, setTab] = useState<'orders' | 'records' | 'settings'>('orders')
  const [settings, setSettings] = useState<WaybillSettings>(emptySettings)
  const [savedSettings, setSavedSettings] = useState<WaybillSettings>(emptySettings)
  const [appSecret, setAppSecret] = useState('')
  const [templates, setTemplates] = useState<WaybillTemplate[]>([])
  const [templateId, setTemplateId] = useState('')
  const [rows, setRows] = useState<WaybillPreview[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [recordMap, setRecordMap] = useState<Record<string, WaybillRecord>>({})
  const [records, setRecords] = useState<WaybillRecord[]>([])
  const [recordTotal, setRecordTotal] = useState(0)
  const [recordPage, setRecordPage] = useState(1)
  const [recordSize, setRecordSize] = useState(20)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [action, setAction] = useState('')
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [workbenchUrl, setWorkbenchUrl] = useState('')
  const [progress, setProgress] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const epoch = useRef(0)
  const stop = useRef(false)
  const busy = useRef(false)
  const { addToast } = useUIStore()
  const isAdmin = useAuthStore(state => !!state.user?.is_admin)
  const canLegacyTest = isAdmin && savedSettings.legacy_allowed
  const settingsDirty = !!appSecret || settings.app_key !== savedSettings.app_key || settings.login_user !== savedSettings.login_user || settings.mall_user_id !== savedSettings.mall_user_id
  const connected = canLegacyTest && !!savedSettings.verified_at && !settingsDirty
  const chosen = rows.filter(row => selected.has(row.order_no))
  const syncable = chosen.filter(row => !recordMap[row.order_no] || recordMap[row.order_no].status === 'sync_failed')
  const numberable = chosen.filter(row => recordMap[row.order_no]?.status === 'synced')
  const readyRows = rows.filter(row => !row.errors.length && recipientReady(row.recipient))
  const useMainSelection = selectedOrders.length > 0
  const currentMainSelection = selectedOrders.filter(o => o.cookie_id === shop)

  const remember = (items: WaybillRecord[]) => setRecordMap(current => ({ ...current, ...Object.fromEntries(items.map(r => [r.order_no, r])) }))
  const loadRecords = async (targetPage = recordPage, size = recordSize, generation = epoch.current) => {
    const result = await getWaybillRecords(shop, targetPage, size)
    if (generation !== epoch.current) return
    setRecords(result.data.items); setRecordTotal(result.data.total); setRecordPage(targetPage)
    remember(result.data.items)
  }
  const load = async () => {
    if (!shop || busy.current) return
    const generation = ++epoch.current
    setLoading(true); setError(''); setRows([]); setSelected(new Set()); setConfirmed(false)
    try {
      const [configuration, history] = await Promise.all([getWaybillSettings(shop), getWaybillRecords(shop, 1, recordSize)])
      if (generation !== epoch.current) return
      setSettings(configuration.data); setSavedSettings(configuration.data); setRecords(history.data.items); setRecordTotal(history.data.total); setRecordPage(1)
      setRecordMap(Object.fromEntries(history.data.items.map(r => [r.order_no, r])))
      let orderNos: string[]
      if (useMainSelection) {
        orderNos = currentMainSelection.map(o => o.order_id)
        setTotal(orderNos.length)
      } else {
        const list = await getOrders(shop, 'pending_ship', page, pageSize)
        if (generation !== epoch.current) return
        orderNos = list.data.map(o => o.order_id); setTotal(list.total)
      }
      const result = orderNos.length ? await previewWaybills(shop, orderNos) : { data: [] }
      if (generation !== epoch.current) return
      setRows(result.data)
      remember(result.data.flatMap(row => row.record ? [row.record] : []))
      if (useMainSelection) setSelected(new Set(result.data.filter(r => !r.errors.length && recipientReady(r.recipient)).map(r => r.order_no)))
    } catch (e) {
      if (generation === epoch.current) setError(getApiErrorMessage(e, '读取打单信息失败，请重试'))
    } finally { if (generation === epoch.current) setLoading(false) }
  }
  useEffect(() => {
    stop.current = false
    void load()
    return () => { stop.current = true; epoch.current += 1 }
  }, [shop, page, pageSize])

  const doAction = async (name: string, fn: (generation: number) => Promise<void>) => {
    if (busy.current || !shop) return
    const generation = epoch.current
    busy.current = true; setAction(name); setError('')
    try { await fn(generation) }
    catch (e) { if (generation === epoch.current) setError(getApiErrorMessage(e, '操作未完成，请检查后重试')) }
    finally {
      busy.current = false
      if (generation === epoch.current) setAction('')
    }
  }
  const testConnection = () => doAction('检测连接', async generation => {
    const result = await getWaybillTemplates(shop)
    if (generation !== epoch.current) return
    setTemplates(result.data); setTemplateId(result.data[0]?.id || '')
    setConfirmed(false)
    const configuration = await getWaybillSettings(shop)
    if (generation !== epoch.current) return
    setSettings(configuration.data); setSavedSettings(configuration.data)
    addToast({ type: 'success', message: result.data.length ? '连接成功，已读取面单模板' : '连接成功，尚无可用面单模板，请在工作台完成授权' })
  })
  const save = () => doAction('保存连接', async generation => {
    const result = await saveWaybillSettings(shop, { app_key: settings.app_key.trim(),
      ...(appSecret ? { app_secret: appSecret } : {}), login_user: settings.login_user.trim(), mall_user_id: settings.mall_user_id.trim() })
    if (generation !== epoch.current) return
    setSettings(result.data); setSavedSettings(result.data); setAppSecret(''); setTemplates([]); setTemplateId(''); setWorkbenchUrl('')
    addToast({ type: 'success', message: '已保存，请检测连接' })
  })
  const runBatch = (kind: 'sync' | 'number') => doAction(kind === 'sync' ? '同步订单' : '申请单号', async generation => {
    if (!confirmed) return
    stop.current = false
    const targets = kind === 'sync' ? syncable : numberable
    let count = 0
    for (const row of targets) {
      if (stop.current || generation !== epoch.current) break
      setProgress(`正在${kind === 'sync' ? '同步' : '取号'} ${count + 1}/${targets.length}：${row.order_no}`)
      const result = kind === 'sync' ? await syncWaybill(shop, row.order_no, row.recipient) : await numberWaybill(shop, row.order_no, templateId)
      if (generation !== epoch.current) break
      remember([result.data]); count += 1
      if (result.data.status.includes('unknown') || result.data.status.endsWith('ing')) {
        setError('本笔结果待核对，已暂停后续操作。请在工作台核对，勿重复取号。'); break
      }
    }
    if (generation !== epoch.current) return
    setProgress(`${stop.current ? '已暂停' : '本次处理结束'}，已处理 ${count}/${targets.length} 笔；逐笔结果见订单状态。`)
    setConfirmed(false)
    await loadRecords(1, recordSize, generation)
  })
  const openWorkbench = () => doAction('准备打印工作台', async generation => {
    const result = await getWaybillWorkbench(shop)
    if (generation !== epoch.current) return
    const url = new URL(result.data.url)
    if (url.protocol !== 'https:' || !['kuaidizs.cn', 'kdzs.com', 'superboss.cc'].some(domain => url.hostname === domain || url.hostname.endsWith('.' + domain))) throw new Error('打印工作台地址无效')
    setWorkbenchUrl(url.href)
  })
  const editRecipient = (orderNo: string, key: keyof WaybillRecipient, value: string) => {
    setRows(current => current.map(row => row.order_no === orderNo ? { ...row, recipient: { ...row.recipient, [key]: value } } : row))
    setSelected(current => { const next = new Set(current); next.delete(orderNo); return next })
    setConfirmed(false)
  }
  const refreshRecipient = (orderNo: string) => doAction('刷新订单详情', async generation => {
    await getOrderDetail(orderNo, true)
    if (generation !== epoch.current) return
    const result = await previewWaybills(shop, [orderNo])
    if (generation !== epoch.current) return
    setRows(current => current.map(row => row.order_no === orderNo ? result.data[0] : row)); setConfirmed(false)
    setSelected(current => { const next = new Set(current); next.delete(orderNo); return next })
  })
  const close = () => { stop.current = true; epoch.current += 1; setAppSecret(''); onClose() }
  const selectShop = (value: string) => {
    setAppSecret(''); setSettings(emptySettings); setSavedSettings(emptySettings); setTemplates([]); setTemplateId(''); setWorkbenchUrl(''); setProgress('');
    setRecordMap({}); setRecords([]); setRows([]); setSelected(new Set()); setPage(1); setShop(value)
  }
  const copy = async (value: string) => {
    try { await navigator.clipboard.writeText(value); addToast({ type: 'success', message: '单号已复制' }) }
    catch { addToast({ type: 'error', message: '复制失败，请手动选择单号复制' }) }
  }

  return <div className="modal-overlay" role="presentation">
    <div className="modal-content max-w-6xl flex flex-col max-h-[92vh]" role="dialog" aria-modal="true" aria-labelledby="waybill-title">
      <div className="modal-header"><h3 id="waybill-title" className="modal-title flex items-center gap-2"><Printer className="w-5 h-5 text-blue-500" />快递打单</h3>
        <button className="modal-close" aria-label="关闭快递打单" onClick={close}><X className="w-5 h-5" /></button></div>
      <div className="px-5 pt-4 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-3 text-sm">店铺<select aria-label="打单店铺" className="input-ios max-w-sm" disabled={!!action || loading} value={shop} onChange={e => selectShop(e.target.value)}>
            {accounts.map(account => <option key={account.id} value={account.id}>{getAccountOptionLabel(account)}</option>)}
          </select></label>
          <span className={`text-xs px-2.5 py-1 rounded-full ${settings.verified_at ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
            {canLegacyTest && settings.configured ? (settingsDirty ? '测试配置有修改 · 请先保存' : settings.verified_at ? '管理员测试连接已验证' : '测试连接待检测') : settings.platform_configured ? '平台应用已配置' : '平台接入准备中'}</span>
        </div>
        <div role="tablist" aria-label="快递打单功能" className="flex gap-6 border-b border-slate-200">
          {([['orders', '订单打单'], ['records', '打单记录'], ['settings', isAdmin ? '平台接入' : '接入状态']] as const).map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} disabled={!!action || loading}
            className={`pb-3 text-sm border-b-2 ${tab === key ? 'border-blue-500 text-blue-600 font-medium' : 'border-transparent text-slate-500'}`}
            onClick={() => { setTab(key); setAppSecret(''); setError(''); if (key === 'records') void doAction('读取记录', g => loadRecords(1, recordSize, g)) }}>{label}</button>)}
        </div>
      </div>
      <div className="modal-body flex-1 overflow-y-auto space-y-4">
        {error && <p role="alert" className="rounded-lg p-3 bg-red-50 text-red-600 text-sm">{error}</p>}
        {!shop ? <>{isAdmin && <WaybillPlatformSettings onSaved={() => void load()} />}<p className="text-sm text-slate-500 py-10 text-center">添加闲鱼店铺后可核对订单和查看店铺接入状态。</p></> : loading ? <p className="flex gap-2 items-center text-sm text-slate-500 py-8 justify-center"><Loader2 className="w-4 h-4 animate-spin" />正在读取打单信息…</p> : tab === 'settings' ? <>
          <section className="rounded-lg bg-blue-50 p-4 text-sm text-blue-800 space-y-2">
            <p className="font-medium">每位用户使用自己的店铺、电子面单和发件信息</p>
            <p>平台统一保管应用配置，你可在下方准备自己的店铺登录授权。电子面单、发件人和系统内打印后续分别联调。</p>
            <ol className="space-y-1 list-decimal pl-5">
              <li>{settings.platform_configured ? '平台应用凭据已保存' : '平台应用接入准备中'}</li>
              <li>店铺登录授权：见下方状态；电子面单权限待联调</li>
              <li>发件信息与系统内打印：待联调</li>
            </ol>
            <p className="text-xs">目前可以核对订单、查看已有打单记录，并通过下方入口准备店铺授权。真实面单和打印仍需服务商联调。</p>
          </section>
          {isAdmin && <WaybillPlatformSettings onSaved={() => void load()} />}
          <WaybillShopAuthorization key={shop} accountId={shop} />
          {canLegacyTest && <details className="rounded-lg border border-slate-200 p-4 space-y-4">
          <summary className="cursor-pointer text-sm text-slate-600">管理员接口测试 · 旧连接</summary>
          <p className="text-xs text-slate-500">仅用于核验已有打印接口。测试连接与上方平台应用分别保存，不代表用户店铺已授权；工作台会在新页面打开。</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="input-group"><span className="input-label">开放平台 AppKey</span><input className="input-ios" autoComplete="off" value={settings.app_key} disabled={!!action} onChange={e => setSettings({ ...settings, app_key: e.target.value })} placeholder="填写自研应用的 AppKey" /></label>
            <label className="input-group"><span className="input-label">AppSecret</span><input type="password" className="input-ios" autoComplete="new-password" value={appSecret} disabled={!!action} onChange={e => setAppSecret(e.target.value)} placeholder={settings.has_secret ? '已加密保存；留空保留原密钥' : '仅在本机填写，保存后不显示原文'} /></label>
          </div>
          <button className="text-sm text-blue-600" onClick={() => setAdvanced(v => !v)}>{advanced ? '收起' : '展开'}多店铺配置</button>
          {advanced && <div className="grid sm:grid-cols-2 gap-4">
            <label className="input-group"><span className="input-label">工作台用户名（服务商提供）</span><input className="input-ios" value={settings.login_user} disabled={!!action} onChange={e => setSettings({ ...settings, login_user: e.target.value })} placeholder="单店铺可留空，默认使用AppKey" /></label>
            <label className="input-group"><span className="input-label">mallUserId（服务商提供）</span><input className="input-ios" inputMode="numeric" value={settings.mall_user_id} disabled={!!action} onChange={e => setSettings({ ...settings, mall_user_id: e.target.value })} placeholder="单店铺可留空" /></label>
          </div>}
          <div className="flex flex-wrap gap-3"><button className="btn-ios-primary" disabled={!!action || !settings.app_key.trim() || (!settings.has_secret && !appSecret)} onClick={() => void save()}>保存连接</button>
            <button className="btn-ios-secondary" disabled={!!action || settingsDirty || !settings.configured} onClick={() => void testConnection()}>检测连接并读取模板</button></div>
          </details>}
        </> : tab === 'records' ? <>
          <div className="flex items-center justify-between gap-3"><p className="text-sm text-slate-500">已取号不代表已打印或已在闲鱼发货。结果待核对的订单请先到工作台检查。</p>
            <button className="btn-ios-secondary btn-sm shrink-0" disabled={!!action} onClick={() => void doAction('读取记录', g => loadRecords(recordPage, recordSize, g))}><RefreshCw className="w-3.5 h-3.5" />刷新记录</button></div>
          <div className="overflow-x-auto border rounded-lg"><table className="w-full text-sm"><thead className="bg-slate-50 dark:bg-slate-800 text-slate-500"><tr>{['订单号', '打单状态', '快递 / 单号', '闲鱼订单状态', '更新时间'].map(t => <th key={t} className="text-left p-3 font-medium">{t}</th>)}</tr></thead>
            <tbody>{records.map(record => <tr key={record.id} className="border-t"><td className="p-3 whitespace-nowrap">{record.order_no}</td><td className="p-3"><span className={record.status === 'waybill_ready' ? 'text-green-600' : 'text-slate-600'}>{stateNames[record.status] || record.status}</span><p className="mt-1 text-xs text-slate-400 max-w-sm">{record.detail}</p></td>
              <td className="p-3"><p>{record.carrier || '—'}</p>{record.waybill_no && <button className="inline-flex gap-1 items-center text-blue-600 mt-1" onClick={() => void copy(record.waybill_no)}>{record.waybill_no}<Copy className="w-3 h-3" /></button>}</td>
              <td className="p-3 whitespace-nowrap">{platformNames[record.platform_status || ''] || '待核对'}</td><td className="p-3 text-xs text-slate-500 whitespace-nowrap">{record.updated_at?.replace('T', ' ').slice(0, 19) || '—'}</td></tr>)}</tbody></table>
            {!records.length && <p className="py-12 text-center text-slate-400 text-sm">暂无打单记录，完成订单同步后会在这里显示。</p>}</div>
          <Pager page={recordPage} pageSize={recordSize} total={recordTotal} loading={!!action} onPageChange={p => void doAction('读取记录', g => loadRecords(p, recordSize, g))} onPageSizeChange={size => { setRecordSize(size); void doAction('读取记录', g => loadRecords(1, size, g)) }} />
        </> : <>
          {!connected && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><span>可先完成店铺登录授权、核对订单；电子面单和系统内打印仍需联调。</span><button className="underline shrink-0" onClick={() => setTab('settings')}>查看接入状态</button></div>}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-500">{useMainSelection ? `显示当前店铺已勾选的 ${currentMainSelection.length} 笔订单` : '显示当前店铺待发货订单'}{useMainSelection && uniqueShops.length > 1 ? '，其他店铺的订单请切换店铺处理' : ''}</p>
            <button className="btn-ios-secondary btn-sm" disabled={!!action} onClick={() => void load()}><RefreshCw className="w-3.5 h-3.5" />重新读取</button>
          </div>
          <div className="overflow-x-auto border rounded-lg"><table className="w-full text-sm min-w-[720px]">
            <thead className="bg-slate-50 dark:bg-slate-800 text-slate-500"><tr><th className="p-3 w-10"><input type="checkbox" aria-label="选择本页可打单订单" disabled={!!action || !readyRows.length} checked={!!readyRows.length && readyRows.every(row => selected.has(row.order_no))} onChange={e => { setSelected(e.target.checked ? new Set(readyRows.map(r => r.order_no)) : new Set()); setConfirmed(false) }} /></th><th className="p-3 text-left w-[25%] font-medium">订单与商品</th><th className="p-3 text-left font-medium">收件信息 · 可核对修改</th><th className="p-3 text-left w-[20%] font-medium">打单状态</th></tr></thead>
            <tbody>{rows.map(row => <tr key={row.order_no} className={`border-t align-top ${selected.has(row.order_no) ? 'bg-blue-50/40' : ''}`}>
              <td className="p-3"><input type="checkbox" aria-label={`选择订单${row.order_no}`} disabled={!!action || !!row.errors.length || !recipientReady(row.recipient)} checked={selected.has(row.order_no)} onChange={e => { setSelected(current => { const next = new Set(current); e.target.checked ? next.add(row.order_no) : next.delete(row.order_no); return next }); setConfirmed(false) }} /></td>
              <td className="p-3"><p className="font-medium break-all">{row.order_no}</p><p className="text-xs mt-2 text-slate-600 line-clamp-2">{row.title || '商品资料待补充'}</p><p className="text-xs mt-2 text-slate-400">¥{row.amount || '—'} · {row.quantity}件</p><button className="text-xs text-blue-600 mt-3" disabled={!!action} onClick={() => void refreshRecipient(row.order_no)}>刷新订单详情</button></td>
              <td className="p-3 space-y-2"><div className="grid grid-cols-2 gap-2">{(['name', 'phone'] as const).map((key, index) => <input key={key} aria-label={`订单${row.order_no}${index ? '电话' : '姓名'}`} className="input-ios !text-xs" disabled={!!action || (!!recordMap[row.order_no] && recordMap[row.order_no].status !== 'sync_failed')} value={row.recipient[key]} onChange={e => editRecipient(row.order_no, key, e.target.value)} placeholder={index ? '电话' : '收件人姓名'} />)}</div>
                <div className="grid grid-cols-3 gap-2">{(['province', 'city', 'county'] as const).map((key, index) => <input key={key} aria-label={`订单${row.order_no}${['省份', '城市', '区县'][index]}`} className="input-ios !text-xs" disabled={!!action || (!!recordMap[row.order_no] && recordMap[row.order_no].status !== 'sync_failed')} value={row.recipient[key]} onChange={e => editRecipient(row.order_no, key, e.target.value)} placeholder={['省份', '城市', '区县'][index]} />)}</div>
                <input aria-label={`订单${row.order_no}详细地址`} className="input-ios !text-xs" disabled={!!action || (!!recordMap[row.order_no] && recordMap[row.order_no].status !== 'sync_failed')} value={row.recipient.address} onChange={e => editRecipient(row.order_no, 'address', e.target.value)} placeholder="详细地址" />
                {!!row.errors.length && <p className="text-xs text-red-500">{row.errors.join('；')}</p>}{!recipientReady(row.recipient) && <p className="text-xs text-amber-600">请补齐完整收件信息，脱敏内容不能用于取号。</p>}</td>
              <td className="p-3 text-xs"><span className={recordMap[row.order_no]?.waybill_no ? 'text-green-600' : 'text-slate-500'}>{recordMap[row.order_no] ? stateNames[recordMap[row.order_no].status] || recordMap[row.order_no].status : '待核对同步'}</span>
                {recordMap[row.order_no]?.waybill_no && <button className="block mt-2 text-blue-600 break-all text-left" onClick={() => void copy(recordMap[row.order_no].waybill_no)}>{recordMap[row.order_no].waybill_no}<Copy className="inline w-3 h-3 ml-1" /></button>}
                {recordMap[row.order_no] && <p className="mt-2 text-slate-400">{recordMap[row.order_no].detail}</p>}</td>
            </tr>)}</tbody></table>{!rows.length && <p className="py-12 text-center text-sm text-slate-400">{useMainSelection ? '当前店铺没有勾选的订单，请切换店铺或返回列表选择。' : '当前店铺暂无待发货订单。'}</p>}</div>
          {!useMainSelection && <Pager page={page} pageSize={pageSize} total={total} loading={!!action || loading} onPageChange={setPage} onPageSizeChange={size => { setPageSize(size); setPage(1) }} />}
          {canLegacyTest && <div className="flex flex-wrap items-center gap-3"><label className="text-sm text-slate-600">测试面单模板</label><select aria-label="面单模板" className="input-ios max-w-xs" value={templateId} disabled={!!action} onChange={e => { setTemplateId(e.target.value); setConfirmed(false) }}><option value="">{templates.length ? '请选择测试模板' : '先检测连接并读取模板'}</option>{templates.map(template => <option key={template.id} value={template.id}>{template.carrier || template.code} · {template.id}</option>)}</select><button className="btn-ios-secondary btn-sm" disabled={!!action || settingsDirty || !settings.configured} onClick={() => void testConnection()}>读取模板</button></div>}
          <label className="flex items-start gap-2 text-xs leading-5 text-slate-600"><input type="checkbox" className="mt-1" checked={confirmed} disabled={!!action || !chosen.length} onChange={e => setConfirmed(e.target.checked)} /><span>已核对所选 {chosen.length} 笔订单及收件信息，同意发送给快递助手用于打单。申请单号会使用面单额度；重打请复用已有单号。</span></label>
          {progress && <p role="status" className="text-xs text-blue-600">{progress}</p>}
        </>}
        {workbenchUrl && <a className="flex items-center justify-center gap-2 rounded-lg bg-blue-50 p-3 text-blue-600 text-sm font-medium" href={workbenchUrl} target="_blank" rel="noopener noreferrer">打开官方打印工作台<ExternalLink className="w-4 h-4" /></a>}
      </div>
      <div className="modal-footer flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-slate-400 max-w-md">{action ? `${action}中；关闭会暂停后续订单，已提交结果保存在记录中。` : connected ? '管理员接口测试：使用官方工作台打印。取号不会改变闲鱼订单状态。' : '店铺登录可在接入状态中确认，电子面单与打印待联调。取号、打印与闲鱼发货状态分别记录。'}</p>
        <div className="flex flex-wrap gap-2">
          {action ? <button className="btn-ios-secondary" onClick={() => { stop.current = true; setProgress('已请求暂停，当前已提交订单完成后停止。') }}>暂停后续</button> : <>
            {tab === 'orders' && <><button className="btn-ios-secondary" disabled={loading || !connected || !confirmed || !syncable.length} onClick={() => void runBatch('sync')}><CheckCircle2 className="w-4 h-4" />同步订单{syncable.length ? `（${syncable.length}）` : ''}</button>
              <button className="btn-ios-primary" disabled={loading || !connected || !confirmed || !templateId || !numberable.length} onClick={() => void runBatch('number')}><Truck className="w-4 h-4" />申请单号{numberable.length ? `（${numberable.length}）` : ''}</button></>}
            {canLegacyTest && <button className="btn-ios-secondary" disabled={loading || !connected} onClick={() => void openWorkbench()}><Printer className="w-4 h-4" />测试打印工作台</button>}
          </>}
          <button className="btn-ios-secondary" onClick={close}>关闭</button>
        </div>
      </div>
    </div>
  </div>
}
