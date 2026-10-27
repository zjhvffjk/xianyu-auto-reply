import { useEffect, useRef, useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import { recommendPlatformCategory, type PlatformCategoryCandidate, type PlatformCategoryCardData, type ProductMaterial } from '@/api/productPublish'
import { previewMaterialCategories, confirmMaterialCategories, type CategoryResult } from '@/api/materialCategories'
import { categoryPathLabel } from '@/utils/materialCategory'
import { buildCategorySelection } from './PlatformCategoryRecommender'

export function MaterialCategoryReplaceModal({materials, accountId, onClose, onSaved, onBack}: {
  materials: ProductMaterial[]; accountId: string | null; onClose: () => void; onSaved: () => void
  onBack?: () => void
}) {
  const [preview, setPreview] = useState<CategoryResult[]>([])
  const [candidates, setCandidates] = useState<PlatformCategoryCandidate[]>([])
  const [cards, setCards] = useState<PlatformCategoryCardData[]>([])
  const [choice, setChoice] = useState('')
  const [target, setTarget] = useState<PlatformCategoryCandidate | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [results, setResults] = useState<CategoryResult[] | null>(null)
  const running = useRef(false)
  useEffect(() => {
    let active = true
    previewMaterialCategories(materials.map(m => m.id), 'replace').then(r => {
      if (!active) return
      if (!r.success) throw new Error(r.message || '读取原类目失败')
      setPreview(r.data.results)
    }).catch(e => {if (active) setError(e instanceof Error ? e.message : '读取原类目失败')})
      .finally(() => {if (active) setBusy(false)})
    return () => {active = false}
  }, [materials])
  const recommend = async () => {
    if (running.current || !accountId) return
    running.current = true; setBusy(true); setError(''); setTarget(null); setChoice(''); setConfirmed(false); setCandidates([])
    try {
      const r = await recommendPlatformCategory({account_id: accountId, title: materials[0].title, description: materials[0].description})
      if (!r.success || !r.data?.candidates?.length) throw new Error(r.message || '未获取到官方类目')
      setCandidates(r.data.candidates); setCards(r.data.card_list || [])
    } catch (e) {setError(e instanceof Error ? e.message : '获取类目失败')}
    finally {running.current = false; setBusy(false)}
  }
  const choose = async (index: string) => {
    if (running.current) return
    setChoice(index); setTarget(null); setConfirmed(false); setError('')
    if (!index || !accountId) return
    running.current = true; setBusy(true)
    try {
      const candidate = candidates[Number(index)]
      const selection = buildCategorySelection(cards, candidate)
      if (!selection.selected_list.length) throw new Error('类目数据已失效，请重新获取')
      const r = await recommendPlatformCategory({account_id: accountId, title: materials[0].title, description: materials[0].description, ...selection})
      if (!r.success) throw new Error(r.message || '确认官方类目失败')
      const resolved = r.data?.candidates.find(c => c.is_selected && c.channel_cat_id === candidate.channel_cat_id)
      if (!resolved?.cat_id || !resolved.channel_cat_id || !resolved.cat_name) throw new Error('官方未返回完整的所选类目，请在素材编辑中选择')
      setTarget(resolved)
    } catch (e) {setError(e instanceof Error ? e.message : '确认类目失败')}
    finally {running.current = false; setBusy(false)}
  }
  const ready = preview.filter(r => r.status === 'ready' && r.category_token)
  const save = async () => {
    if (running.current || !target || !confirmed || !ready.length) return
    running.current = true; setBusy(true); setError('')
    try {
      const r = await confirmMaterialCategories(ready.map(r => ({id: r.id, candidate: target, expected_category_token: r.category_token})), 'replace')
      if (!r.success) throw new Error(r.message || '保存失败')
      setResults(r.data.results); setConfirmed(false); setTarget(null); onSaved()
    } catch (e) {setError(e instanceof Error ? e.message : '保存失败，请重试')}
    finally {running.current = false; setBusy(false)}
  }
  return <div className="modal-overlay" style={{zIndex: 80}}><div className="modal-content max-w-3xl">
    <div className="modal-header flex items-center justify-between"><h2 className="text-lg font-semibold">批量修改平台类目</h2><button aria-label="关闭批量修改类目" disabled={busy} onClick={onClose}><X className="h-5 w-5" /></button></div>
    <div className="modal-body space-y-4">
      <p className="text-sm text-slate-500">为所选素材统一选择新类目，仅修改本地素材。建议来自第一件素材，请核对其余商品是否适用。已有定时任务使用原快照，不会随之改变。</p>
      {!results && <><div className="flex flex-wrap items-center gap-3"><button className="btn-ios-secondary" disabled={busy || !accountId || !ready.length} onClick={recommend}>获取官方类目</button>{busy && <span className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />处理中…</span>}{!accountId && <span className="text-sm text-amber-700">请先选择店铺</span>}</div>
      {!!candidates.length && <label className="block space-y-2 text-sm"><span>统一修改为</span><select aria-label="批量修改的目标类目" className="input-ios w-full" value={choice} disabled={busy} onChange={e => void choose(e.target.value)}><option value="">请选择新类目</option>{candidates.map((c, i) => <option value={i} key={`${c.channel_cat_id}-${i}`}>{categoryPathLabel(c)}</option>)}</select></label>}</>}
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="max-h-72 space-y-3 overflow-y-auto rounded-lg border border-slate-200 p-3 dark:border-slate-700">{materials.map(m => {
        const row = preview.find(r => r.id === m.id); const result = results?.find(r => r.id === m.id)
        return <div key={m.id} className="border-b border-slate-100 pb-3 last:border-0 last:pb-0 dark:border-slate-700"><p className="truncate text-sm font-medium" title={m.title}>{m.title}</p><p className="mt-1 break-words text-xs text-slate-500">{row?.current ? categoryPathLabel(row.current) : m.platform_category_name || '未设置'} → <span className="text-blue-600">{target ? categoryPathLabel(target) : results ? '按下方结果处理' : '待选择新类目'}</span></p>{result ? <p className={`mt-1 text-xs ${result.status === 'saved' ? 'text-emerald-700' : 'text-amber-700'}`}>{result.message}</p> : row?.status === 'failed' && <p className="text-xs text-red-600">{row.message}</p>}</div>
      })}</div>
      {!results && target && <label className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800"><input type="checkbox" className="mt-1" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} /><span>我已核对以上 {ready.length} 件素材的新类目；类目发生变化时清空旧类目专属属性，保存后需在素材编辑中核对新类目的属性。</span></label>}
    </div>
    <div className="modal-footer flex flex-wrap justify-end gap-2">{onBack && !results && <button className="btn-ios-secondary mr-auto" disabled={busy} onClick={onBack}>返回设置方式</button>}<button className="btn-ios-secondary" disabled={busy} onClick={onClose}>{results ? '完成' : '取消'}</button>{!results && <button className="btn-ios-primary" disabled={busy || !target || !confirmed || !ready.length} onClick={save}>确认修改 {ready.length} 件素材</button>}</div>
  </div></div>
}
