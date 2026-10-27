import { useEffect, useState } from 'react'
import { Pencil, RefreshCw, Search } from 'lucide-react'
import { getMaterials, type ProductMaterial } from '@/api/productPublish'
import type { AccountDetail } from '@/types'
import { getAccountName } from '@/utils/accountLabel'
import { materialCategoryLabel } from '@/utils/materialCategory'
import { MaterialSummary } from './MaterialSummary'

interface Props {
  accounts: AccountDetail[]; defaultSource: string | null; revision: number; busy: boolean
  selected: Map<number, ProductMaterial>
  onSelect: (materials: ProductMaterial[], remove: boolean) => void
  onClear: () => void; onEdit: (id: number) => void
}

/** 与素材库共享分页接口、来源身份与素材摘要；筛选不改变选择。 */
export function BatchMaterialPicker({accounts, defaultSource, revision, busy, selected, onSelect, onClear, onEdit}: Props) {
  const [source, setSource] = useState(defaultSource ?? '')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [condition, setCondition] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [total, setTotal] = useState(0)
  const [materials, setMaterials] = useState<ProductMaterial[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [selectedOnly, setSelectedOnly] = useState(false)
  useEffect(() => { setSource(defaultSource ?? ''); setPage(1) }, [defaultSource])
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    getMaterials(page, pageSize, {title: query, category, condition, source_account_id: source, own_only: true, include_unlinked: !!source && source !== "__unlinked__"})
      .then(res => {
        if (!active) return
        if (!res.success) throw new Error()
        setMaterials(res.data.list); setTotal(res.data.total)
      }).catch(() => { if (active) { setMaterials([]); setError('素材加载失败，请重试；已选素材仍然保留') } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [page, pageSize, query, category, condition, source, revision, refresh])
  const rows = selectedOnly ? [...selected.values()] : materials
  const allSelected = rows.length > 0 && rows.every(m => selected.has(m.id))
  return <section className="vben-card">
    <div className="vben-card-header"><h2 className="vben-card-title">选择素材</h2><span className="text-xs text-slate-500">沿用素材库资料，不修改标题和描述</span></div>
    <div className="vben-card-body space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-0 flex-col gap-1"><span className="text-xs text-slate-500">素材来源店铺</span><select aria-label="素材来源店铺" className="input-ios max-w-72" value={source} onChange={e => {setSource(e.target.value); setPage(1)}}>
          <option value="">全部来源（跨店共享）</option>{accounts.map(a => <option key={a.id} value={a.id}>{getAccountName(a)}＋自建素材</option>)}<option value="__unlinked__">自建／未关联来源素材</option>
        </select></label>
        <form className="flex items-end gap-2" onSubmit={e => { e.preventDefault(); setQuery(search.trim()); setPage(1); setRefresh(r => r + 1) }}>
          <label className="flex min-w-0 flex-col gap-1"><span className="text-xs text-slate-500">搜索素材</span><input aria-label="搜索素材" className="input-ios" placeholder="输入素材标题" value={search} onChange={e => setSearch(e.target.value)} /></label>
          <button className="btn-ios-secondary" type="submit"><Search className="h-4 w-4" />查询</button>
        </form>
        <label className="flex min-w-0 flex-col gap-1"><span className="text-xs text-slate-500">平台分类</span><input aria-label="筛选平台分类" className="input-ios w-36" placeholder="输入分类名称" value={category} onChange={e => { setCategory(e.target.value); setPage(1) }} /></label>
        <label className="flex min-w-0 flex-col gap-1"><span className="text-xs text-slate-500">成色</span><select aria-label="筛选成色" className="input-ios" value={condition} onChange={e => { setCondition(e.target.value); setPage(1) }}><option value="">全部成色</option>{['全新', '99新', '95新', '9成新', '8成新', '7成新以下'].map(c => <option key={c}>{c}</option>)}</select></label>
        <button className="btn-ios-secondary" onClick={() => setRefresh(r => r + 1)}><RefreshCw className="h-4 w-4" />刷新</button>
      </div>
      <p className="text-xs text-slate-500">可选择从在售、已下架等商品导入的素材，也可选择自己新建的素材；发布目标店铺单独选择。</p>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800">
        <span>已选 <strong className="text-blue-600">{selected.size}</strong> 条素材 · 筛选和翻页保留勾选</span>
        <div className="flex gap-3"><button className="text-blue-600" onClick={() => setSelectedOnly(v => !v)}>{selectedOnly ? '返回素材列表' : '仅看已选'}</button><button disabled={busy || !selected.size} className="text-slate-500 disabled:opacity-40" onClick={onClear}>清空已选</button></div>
      </div>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error} <button onClick={() => setRefresh(r => r + 1)} className="underline">重新加载</button></p>}
      <div className="overflow-x-auto"><table className="table-ios w-full min-w-[700px] table-fixed">
        <thead><tr><th className="w-12"><input aria-label="选择当前页素材" type="checkbox" checked={allSelected} disabled={busy || !rows.length || (!selectedOnly && (loading || !!error))} onChange={() => onSelect(rows, allSelected)} /></th><th>素材信息</th><th className="w-24 text-center">售价</th><th className="w-36">平台分类</th><th className="w-24 text-center">库存</th><th className="w-20 text-center">操作</th></tr></thead>
        <tbody>{!selectedOnly && loading ? <tr><td colSpan={6} className="py-12 text-center text-slate-400">正在加载素材…</td></tr> : !rows.length ? <tr><td colSpan={6} className="py-12 text-center text-slate-400">{error ? '素材加载未完成' : selectedOnly ? '尚未选择素材' : '当前筛选下没有素材，可切换来源店铺或前往素材库导入'}</td></tr> : rows.map(m => <tr key={m.id}>
          <td><input type="checkbox" aria-label={`选择素材 ${m.id}`} checked={selected.has(m.id)} disabled={busy} onChange={() => onSelect([m], selected.has(m.id))} /></td>
          <td><MaterialSummary material={m} /></td><td className="text-center tabular-nums text-amber-600">¥{Number(m.price).toFixed(2)}</td>
          <td><p className="truncate" title={materialCategoryLabel(m)}>{materialCategoryLabel(m) === '未命名类目' ? '未获取分类' : materialCategoryLabel(m)}</p></td><td className="text-center tabular-nums">{m.quantity ?? '未获取'}</td>
          <td className="text-center"><button aria-label={`编辑素材 ${m.id}`} className="inline-flex text-blue-600" disabled={busy} onClick={() => onEdit(m.id)}><Pencil className="h-4 w-4" /></button></td>
        </tr>)}</tbody>
      </table></div>
      {!selectedOnly && <div className="flex items-center justify-between gap-2 text-sm text-slate-500"><label>每页 <select aria-label="素材每页条数" className="input-ios !w-auto !py-1" value={pageSize} onChange={e => {setPageSize(Number(e.target.value)); setPage(1)}}>{[10,20,50].map(n => <option key={n}>{n}</option>)}</select> 条 · 共 {total} 条</label><div className="flex items-center gap-3"><button disabled={page <= 1 || loading} className="disabled:opacity-30" onClick={() => setPage(p => p - 1)}>上一页</button><span>{page} / {Math.max(1, Math.ceil(total/pageSize))}</span><button disabled={page * pageSize >= total || loading} className="disabled:opacity-30" onClick={() => setPage(p => p + 1)}>下一页</button></div></div>}
    </div>
  </section>
}
