import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle, ClipboardCheck, Loader2, Send, Store, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { checkBatchPublish, getMaterial, publishBatch, type BatchCheckReport, type ProductMaterial } from '@/api/productPublish'
import { getAccountDetails } from '@/api/accounts'
import type { AccountDetail } from '@/types'
import { getAccountName } from '@/utils/accountLabel'
import { useAuthStore } from '@/store/authStore'
import { useShopStore } from '@/store/shopStore'
import { useUIStore } from '@/store/uiStore'
import { MaterialFormModal } from './MaterialFormModal'
import { BatchMaterialPicker } from './BatchMaterialPicker'
import { BatchPublishResults } from './BatchPublishResults'
import { useBatchTracking } from './useBatchTracking'
import { BatchScheduleControls } from './BatchScheduleControls'
import { BatchTaskHistory } from './BatchTaskHistory'
import { batchSchedulePayload, defaultBeijingStart, type BatchMode } from '@/utils/batchSchedule'

export function BatchPublish() {
  const userId = useAuthStore(s => s.user?.user_id)
  const { currentAccountId } = useShopStore()
  const { addToast } = useUIStore()
  const [accounts, setAccounts] = useState<AccountDetail[]>([])
  const [accountsError, setAccountsError] = useState('')
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [accountRevision, setAccountRevision] = useState(0)
  const [targets, setTargets] = useState<Set<string>>(new Set())
  const defaultTargetSet = useRef(false)
  const [revision, setRevision] = useState(0)
  const [historyRevision, setHistoryRevision] = useState(0)
  const [mode, setMode] = useState<BatchMode>('immediate')
  const [start, setStart] = useState(() => defaultBeijingStart())
  const [minutes, setMinutes] = useState(5)
  const [selected, setSelected] = useState<Map<number, ProductMaterial>>(new Map())
  const [report, setReport] = useState<BatchCheckReport | null>(null)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [allowDuplicates, setAllowDuplicates] = useState(false)
  const [editTarget, setEditTarget] = useState<ProductMaterial | null>(null)
  const actionLock = useRef(false)
  const checkVersion = useRef(0)
  const track = useBatchTracking(userId)
  const count = targets.size * selected.size
  const busy = submitting || checking
  const name = (id: string) => {
    const account = accounts.find(a => a.id === id)
    return account ? getAccountName(account) : id
  }
  const invalidate = useCallback(() => {
    checkVersion.current++; setReport(null); setAllowDuplicates(false); setError('')
  }, [])
  useEffect(() => {
    let active = true
    setAccountsLoading(true); setAccountsError('')
    getAccountDetails().then(list => {
      if (!active) return
      setAccounts(list); invalidate()
      setTargets(prev => new Set([...prev].filter(id => list.some(a => a.id === id))))
      if (!defaultTargetSet.current && currentAccountId && list.some(a => a.id === currentAccountId)) {
        setTargets(new Set([currentAccountId])); defaultTargetSet.current = true
      }
    }).catch(() => { if (active) setAccountsError('发布店铺加载失败，请重试') })
      .finally(() => { if (active) setAccountsLoading(false) })
    return () => { active = false }
  }, [accountRevision, userId, currentAccountId, invalidate])
  const runCheck = async () => {
    if (actionLock.current || !count || count > 500 || track.locked || accountsError) return
    try { batchSchedulePayload(mode, start, minutes) }
    catch (err) { setError(err instanceof Error ? err.message : '时间设置无效'); return }
    actionLock.current = true; setChecking(true); invalidate()
    const version = checkVersion.current
    try {
      const res = await checkBatchPublish({account_ids: [...targets], material_ids: [...selected.keys()]})
      if (version !== checkVersion.current) return
      if (!res.success || !res.data) setError(res.message || '检查失败，请重试')
      else setReport(res.data)
    } catch { setError('检查请求失败，请重试；没有提交发布任务') }
    finally { actionLock.current = false; setChecking(false) }
  }
  const submit = async () => {
    if (actionLock.current || !report?.ready || track.locked || (report.duplicate_count > 0 && !allowDuplicates)) return
    actionLock.current = true; setSubmitting(true)
    let remembered = false
    try {
      const schedule = batchSchedulePayload(mode, start, minutes)
      const id = crypto.randomUUID()
      track.remember(id); remembered = true
      const res = await publishBatch({account_ids: [...targets], material_ids: [...selected.keys()],
        request_id: id, fingerprint: report.fingerprint, allow_duplicates: allowDuplicates, ...schedule})
      if (!res.success) { track.forget(); invalidate(); setError(res.message || '提交被拒绝，请重新检查') }
      else { invalidate(); track.refresh(); setHistoryRevision(v => v + 1); addToast({type: 'success', message: res.message || '任务已提交'}) }
    } catch (err) {
      setError(remembered ? '未能确认提交结果。已保留请求号，请恢复查询并核查发布日志，勿重复提交。' : err instanceof Error ? err.message : '本次未提交，请检查时间设置及浏览器会话存储。'); if (remembered) track.refresh()
    } finally { actionLock.current = false; setSubmitting(false) }
  }
  const openEdit = async (id: number) => {
    try {
      const res = await getMaterial(id)
      if (!res.success || !res.data) throw new Error()
      invalidate(); setEditTarget(res.data)
    } catch { addToast({type: 'error', message: '素材详情加载失败，请重试'}) }
  }
  const saved = async () => {
    const id = editTarget?.id
    setEditTarget(null); invalidate(); setRevision(r => r + 1)
    if (id) {
      try {
        const res = await getMaterial(id)
        const material = res.data
        if (res.success && material) setSelected(prev => {
          if (!prev.has(id)) return prev
          const next = new Map(prev); next.set(id, material); return next
        })
      } catch { /* 提交前后端重新读取并检查 */ }
    }
  }
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h1 className="page-title">批量发布</h1><p className="page-description">从素材库选择商品，检查后发布到指定店铺</p></div><Link to="/product-publish/materials" className="btn-ios-secondary">管理素材库</Link></div>
    <section className="vben-card"><div className="vben-card-header"><h2 className="vben-card-title"><Store className="h-4 w-4" />发布目标店铺</h2><span className="text-xs text-slate-500">每个目标店铺分别发布全部已选素材</span></div>
      <div className="vben-card-body space-y-3">{accountsLoading ? <p className="text-sm text-slate-500">正在加载店铺…</p> : accountsError ? <p role="alert" className="text-sm text-red-600">{accountsError} <button onClick={() => setAccountRevision(r => r + 1)} className="text-blue-600">重新加载</button></p> : accounts.length === 0 ? <p className="text-sm text-slate-500">暂无可用店铺，请先添加账号</p> :
        <div className="flex flex-wrap gap-2">{accounts.map(a => <label key={a.id} className={`flex max-w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${targets.has(a.id) ? 'border-blue-300 bg-blue-50 dark:bg-blue-950' : 'border-slate-200 dark:border-slate-700'}`}>
          <input type="checkbox" aria-label={`发布到 ${getAccountName(a)}`} checked={targets.has(a.id)} disabled={busy} onChange={() => { invalidate(); defaultTargetSet.current = true; setTargets(prev => { const next = new Set(prev); next.has(a.id) ? next.delete(a.id) : next.add(a.id); return next }) }} />
          <span className="truncate">{getAccountName(a)}</span><span className="shrink-0 text-xs text-slate-400">{a.online === true ? '在线' : a.online === false ? '离线' : '状态待检查'}</span>
        </label>)}</div>}<p className="text-xs text-slate-500">手动发布不受自动任务启用开关限制；登录有效性与发布能力在执行时由平台确认。</p></div>
    </section>
    <BatchMaterialPicker accounts={accounts} defaultSource={currentAccountId} revision={revision} busy={busy} selected={selected}
      onClear={() => {setSelected(new Map()); invalidate()}} onEdit={openEdit} onSelect={(items, remove) => {
        invalidate(); setSelected(prev => { const next = new Map(prev); items.forEach(m => remove ? next.delete(m.id) : next.set(m.id, m)); return next })
      }} />
    <BatchScheduleControls mode={mode} start={start} minutes={minutes} disabled={busy}
      onMode={value => {setMode(value); invalidate()}} onStart={value => {setStart(value); invalidate()}} onMinutes={value => {setMinutes(value); invalidate()}} />
    <section className="vben-card"><div className="vben-card-body space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-medium">{targets.size} 个目标店铺 × {selected.size} 条素材 = <span className="text-blue-600">{count} 次发布</span></p><p className="mt-1 text-xs text-slate-500">优先沿用素材所在地，未填写时使用地址库。每批最多100条素材、500次发布。</p></div>
        <button className="btn-ios-primary" disabled={busy || !count || count > 500 || selected.size > 100 || track.locked || !!accountsError || accountsLoading || !!track.storageError} onClick={runCheck}>{checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <ClipboardCheck className="h-4 w-4" />}检查并预览发布</button></div>
      {(error || track.storageError) && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error || track.storageError}</p>}
      {report && <div className="space-y-3 border-t border-slate-100 pt-3 dark:border-slate-700">
        <div className="flex items-center gap-2 font-medium">{report.ready ? <CheckCircle className="h-4 w-4 text-green-600" /> : <X className="h-4 w-4 text-amber-600" />}{report.ready ? '基础检查通过，请核对下列发布清单' : '检查发现问题，请修正后重新检查'}</div>
        <p className="text-xs text-slate-500">仅检查已保存字段、账号登录信息和地址配置；账号能力及平台限制由正式执行时确认。</p>
        <div className="max-h-80 overflow-auto rounded-lg border border-slate-200 dark:border-slate-700"><table className="table-ios w-full min-w-[600px]"><thead><tr><th>发布店铺</th><th>素材</th><th>检查结果</th><th>操作</th></tr></thead><tbody>{report.items.map(item => <tr key={`${item.account_id}:${item.material_id}`}><td>{name(item.account_id)}</td><td><p className="max-w-64 truncate" title={item.title}>{item.title}</p><span className="text-xs text-slate-400">素材ID：{item.material_id}</span></td><td>{item.errors.map(issue => <p key={issue} className="text-xs text-red-600">{issue}</p>)}{item.success_count > 0 && <p className="text-xs text-amber-600">该店铺已有 {item.success_count} 次成功发布记录</p>}{item.source_item_id && <p className="text-xs text-amber-600">素材来源于目标店铺商品 {item.source_item_id}，请核查是否需要再次发布</p>}{!item.errors.length && !item.success_count && !item.source_item_id && <span className="text-xs text-green-600">可以提交</span>}</td><td><button disabled={busy} className="whitespace-nowrap text-blue-600" onClick={() => openEdit(item.material_id)}>编辑素材</button></td></tr>)}</tbody></table></div>
        {report.duplicate_count > 0 && <label className="flex items-center gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-700"><input type="checkbox" checked={allowDuplicates} onChange={e => setAllowDuplicates(e.target.checked)} />我已核对来源商品和已有发布记录，确认再次发布这 {report.duplicate_count} 项</label>}
        <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">{mode === 'scheduled' ? `确认后按北京时间 ${start.replace('T',' ')} 开始发布，每件间隔${minutes}分钟。` : `确认后进入发布队列，每件处理完再等待${minutes}分钟。`}</p><button className="btn-ios-primary" disabled={!report.ready || busy || track.locked || (report.duplicate_count > 0 && !allowDuplicates)} onClick={submit}>{submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}{mode === 'scheduled' ? '确认创建定时任务' : '确认发布'} {report.total} 件商品</button></div>
      </div>}
    </div></section>
    <BatchPublishResults track={track} accountName={name} onClear={invalidate} submitting={submitting} />
    <BatchTaskHistory revision={historyRevision} onTrack={id => {try {track.remember(id)} catch {setError('无法保存任务跟踪，请检查浏览器存储')}}} onCancelled={() => {track.refresh(); setHistoryRevision(v => v + 1)}} />
    {editTarget && <MaterialFormModal initial={editTarget} onClose={() => setEditTarget(null)} onSaved={saved} />}
  </div>
}
