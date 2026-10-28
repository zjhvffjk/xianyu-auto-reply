import { useEffect, useRef, useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import { recommendPlatformCategory, type PlatformCategoryCandidate, type PlatformCategoryCardData, type ProductMaterial } from '@/api/productPublish'
import { previewMaterialCategories, confirmMaterialCategories, type CategoryResult } from '@/api/materialCategories'
import { categoryPathLabel, savedMaterialCategoryChoices, categoryRecommendationInput } from '@/utils/materialCategory'
import { buildCategorySelection } from './PlatformCategoryRecommender'

export function MaterialCategoryReplaceModal({materials, referenceMaterials, accountId, onClose, onSaved, onBack}: {
  materials: ProductMaterial[]; accountId: string | null; onClose: () => void; onSaved: () => void
  onBack?: () => void; referenceMaterials: ProductMaterial[]
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
  const [keyword, setKeyword] = useState('')
  const [lookup, setLookup] = useState({title: '', description: ''})
  const [savedChoice, setSavedChoice] = useState('')
  const savedCategories = savedMaterialCategoryChoices(referenceMaterials)
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
  const recommend = async (useProduct = false) => {
    if (running.current || !accountId || !materials.length) return
    running.current = true; setBusy(true); setError(''); setTarget(null); setChoice(''); setConfirmed(false); setCandidates([])
    setSavedChoice(''); setCards([])
    const input = categoryRecommendationInput(materials[0], useProduct ? '' : keyword)
    setLookup(input)
    try {
      const r = await recommendPlatformCategory({account_id: accountId, ...input})
      if (!r.success || !r.data?.candidates?.length) throw new Error(r.message || '未获取到官方类目')
      setCandidates(r.data.candidates); setCards(r.data.card_list || [])
    } catch (e) {setError(e instanceof Error ? e.message : '获取类目失败')}
    finally {running.current = false; setBusy(false)}
  }
  const choose = async (index: string) => {
    if (running.current) return
    setChoice(index); setSavedChoice(''); setTarget(null); setConfirmed(false); setError('')
    if (!index || !accountId) return
    running.current = true; setBusy(true)
    try {
      const candidate = candidates[Number(index)]
      const selection = buildCategorySelection(cards, candidate)
      if (!selection.selected_list.length) throw new Error('类目数据已失效，请重新获取')
      const r = await recommendPlatformCategory({account_id: accountId, ...lookup, ...selection})
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
      setResults(r.data.results); setConfirmed(false); onSaved()
    } catch (e) {setError(e instanceof Error ? e.message : '保存失败，请重试')}
    finally {running.current = false; setBusy(false)}
  }
  return <div className="modal-overlay" style={{zIndex: 80}}><div className="modal-content max-w-3xl">
    <div className="modal-header flex items-center justify-between"><h2 className="text-lg font-semibold">批量修改平台类目</h2><button aria-label="关闭批量修改类目" disabled={busy} onClick={onClose}><X className="h-5 w-5" /></button></div>
    <div className="modal-body space-y-4">
      <p className="text-sm text-slate-500">已选 {materials.length} 件素材。选择一个目标类目，核对下方变化后保存；不会更改商品标题、描述、价格或自动发布。已有定时任务使用原快照，不会随之改变。</p>
      {!results && <>
      <div className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
        <label className="block space-y-2 text-sm"><span className="font-medium">使用本页已有素材的类目</span><select aria-label="本页已有素材类目" className="input-ios w-full" value={savedChoice} disabled={busy || !ready.length || !savedCategories.length} onChange={e => {const value = e.target.value; setSavedChoice(value); setChoice(''); setTarget(value === '' ? null : savedCategories[Number(value)]); setConfirmed(false); setError('')}}><option value="">{savedCategories.length ? '请选择已有类目' : '本页没有完整的平台类目'}</option>{savedCategories.map((c, i) => <option value={i} key={i}>{categoryPathLabel(c)}</option>)}</select></label>
        <p className="text-xs text-slate-500">直接复用已保存的完整类目，例如“其他闲置”；不会复制其他素材的内容或类目专属属性。</p>
      </div>
      <div className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
        <form className="space-y-2" onSubmit={e => {e.preventDefault(); if (keyword.trim()) void recommend()}}><label className="block text-sm font-medium" htmlFor="batch-category-keyword">按关键词查找平台类目</label><div className="flex flex-wrap gap-2"><input id="batch-category-keyword" className="input-ios min-w-0 flex-1" maxLength={200} disabled={busy} value={keyword} placeholder="输入类目关键词，如：其他闲置" onChange={e => {setKeyword(e.target.value); setCandidates([]); setCards([]); setChoice(''); setTarget(null); setSavedChoice(''); setConfirmed(false)}} /><button type="submit" className="btn-ios-secondary" disabled={busy || !accountId || !ready.length || !keyword.trim()}>查找类目</button></div></form>
        <div className="flex flex-wrap items-center gap-3"><button className="text-sm text-blue-600 disabled:opacity-50" disabled={busy || !accountId || !ready.length} onClick={() => void recommend(true)}>按第一件商品获取建议</button>{busy && <span className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />处理中…</span>}{!accountId && <span className="text-sm text-amber-700">查询平台类目请先选择店铺，仍可复用已有素材类目。</span>}</div>
        <p className="text-xs text-slate-500">关键词仅用于查询，不会改写素材。平台候选可能有限，请核对所选类目是否适合全部商品。</p>
      {!!candidates.length && <label className="block space-y-2 text-sm"><span>统一修改为</span><select aria-label="批量修改的目标类目" className="input-ios w-full" value={choice} disabled={busy} onChange={e => void choose(e.target.value)}><option value="">请选择新类目</option>{candidates.map((c, i) => <option value={i} key={`${c.channel_cat_id}-${i}`}>{categoryPathLabel(c)}</option>)}</select></label>}
      </div></>}
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
