import { useEffect, useRef, useState } from 'react'
import { X, Loader2 } from 'lucide-react'
import { getItemsPaginated } from '@/api/items'
import { importCatalogMaterials, type CatalogImportResult } from '@/api/catalogMaterials'
import { Pager } from '@/components/common/Pager'
import { ItemSummary } from '@/pages/items/ItemSummary'
import type { Item } from '@/types'
import { ITEM_STATUS_OPTIONS, type ItemPlatformStatus } from '@/utils/itemStatusOptions'
import { getMaterial, type ProductMaterial } from '@/api/productPublish'
import { newlyImportedMaterialIds, loadImportedMaterials } from '@/utils/materialImportContinuation'
import { getCatalogDetailSync, isDetailSyncRunning, startCatalogDetailSync } from '@/api/catalogDetails'
import { getApiErrorMessage } from '@/utils/apiError'

export function CatalogMaterialImportModal({accountId, accountLabel, onClose, onImported, onConfigureCategories}: {
  accountId: string; accountLabel: string; onClose: () => void; onImported: () => void
  onConfigureCategories: (materials: ProductMaterial[]) => void
}) {
  const [items, setItems] = useState<Item[]>([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [keyword, setKeyword] = useState('')
  const [platformStatus, setPlatformStatus] = useState<ItemPlatformStatus>('on_sale')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const attemptVersion = useRef(0)
  const [configuring, setConfiguring] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [results, setResults] = useState<CatalogImportResult[]>([])
  const submitting = useRef(false)
  const configuringRef = useRef(false)
  const busy = saving || configuring || preparing
  const importedIds = newlyImportedMaterialIds(results)
  useEffect(() => () => { attemptVersion.current++ }, [accountId])
  const close = () => { attemptVersion.current++; onClose() }
  useEffect(() => {
    let active = true
    setLoading(true); setError(''); setSelected(new Set()); setItems([])
    getItemsPaginated(page, pageSize, accountId, {keyword, platform_status: platformStatus})
      .then(res => {
        if (!active) return
        if (!res.success) throw new Error('商品列表加载失败')
        setItems(res.data); setTotal(res.total)
      })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : '商品列表加载失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [accountId, page, pageSize, keyword, platformStatus, retry])
  const save = async () => {
    if (submitting.current || configuringRef.current || !selected.size || loading) return
    const version = ++attemptVersion.current
    const itemIds = [...selected]
    submitting.current = true; setError(''); setResults([])
    try {
      setPreparing(true)
      const started = await startCatalogDetailSync(accountId, itemIds)
      if (version !== attemptVersion.current) return
      if (!started.success || !started.data) throw new Error(started.message || '商品资料暂不可用，请稍后重试')
      let job = started.data
      // 所选商品已处理即可导入，其余商品继续后台补全。
      while (isDetailSyncRunning(job) && !itemIds.every(id => job.checked_item_ids?.includes(id))) {
        await new Promise(resolve => setTimeout(resolve, 1500))
        if (version !== attemptVersion.current) return
        const progress = await getCatalogDetailSync(accountId, job.job_id)
        if (version !== attemptVersion.current) return
        if (!progress.success || !progress.data) throw new Error(progress.message || '商品资料暂不可用，请稍后重试')
        job = progress.data
      }
      const selectedChecked = itemIds.every(id => job.checked_item_ids?.includes(id))
      if (!selectedChecked && (job.state === 'failed' || job.state === 'interrupted')) throw new Error(job.message)
      if (version !== attemptVersion.current) return
      setPreparing(false); setSaving(true)
      const response = await importCatalogMaterials(accountId, itemIds)
      if (version !== attemptVersion.current) return
      if (!response.success) throw new Error(response.message || '导入失败')
      setResults(response.data.results); setSelected(new Set(response.data.results.filter(row => row.status === 'failed').map(row => row.item_id)))
      if (response.data.results.some(row => row.status === 'created')) onImported()
    } catch (e) { if (version === attemptVersion.current) setError(getApiErrorMessage(e, '导入请求失败，请重试')) }
    finally { if (version === attemptVersion.current) {submitting.current = false; setPreparing(false); setSaving(false)} }
  }
  const configure = async () => {
    if (configuringRef.current || submitting.current || !importedIds.length) return
    configuringRef.current = true; setConfiguring(true); setError('')
    try {
      const materials = await loadImportedMaterials(importedIds, getMaterial)
      onConfigureCategories(materials)
    } catch (e) {setError(`导入已经完成，${e instanceof Error ? e.message : '读取素材失败'}。可再次点击类目设置重试。`)}
    finally {configuringRef.current = false; setConfiguring(false)}
  }
  return (
    <div className="modal-overlay" style={{zIndex: 80}}>
      <div className="modal-content max-w-3xl">
        <div className="modal-header flex items-center justify-between gap-3">
          <div><h2 className="text-lg font-semibold">从商品管理导入</h2><p className="mt-1 text-sm text-slate-500">{accountLabel}</p></div>
          <button type="button" aria-label="关闭导入" disabled={saving || configuring} onClick={close}><X className="h-5 w-5" /></button>
        </div>
        <div className="modal-body space-y-3">
          <p className="text-xs leading-5 text-slate-500">复用商品管理已有商品及状态，支持下架、售出等历史记录。重复导入会跳过，不覆盖手动修改，也不会恢复已移出素材库的素材。</p>
          <form className="flex gap-2" onSubmit={event => {event.preventDefault(); setPage(1); setKeyword(search.trim())}}>
            <select aria-label="导入商品状态" className="input-ios w-32 shrink-0" disabled={busy} value={platformStatus} onChange={event => {setPlatformStatus(event.target.value as ItemPlatformStatus); setPage(1); setSelected(new Set()); setResults([])}}>
              {ITEM_STATUS_OPTIONS.map(option => <option value={option.value} key={option.value}>{option.label}</option>)}
            </select>
            <input className="input-ios flex-1" placeholder="搜索商品标题 / ID" value={search} onChange={e => setSearch(e.target.value)} disabled={busy} />
            <button className="btn-ios-secondary" disabled={busy || loading}>查询</button>
          </form>
          {error && <div role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error} {!importedIds.length && <button type="button" className="underline" disabled={busy} onClick={() => setRetry(value => value + 1)}>重新加载</button>}</div>}
          <div className="max-h-72 overflow-auto rounded-lg border border-slate-200 dark:border-slate-700">
            {loading ? <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin" /></div> : items.length === 0 ? <p className="p-8 text-center text-sm text-slate-500">当前状态下没有匹配商品，可切换状态或搜索条件。</p> : (
              <table className="table-ios w-full"><thead><tr>
                <th className="w-10"><input type="checkbox" aria-label="选择本页商品" disabled={busy} checked={items.length > 0 && items.every(item => selected.has(item.item_id))} onChange={e => setSelected(e.target.checked ? new Set(items.map(item => item.item_id)) : new Set())} /></th>
                <th>商品信息</th><th>售价</th><th>状态</th>
              </tr></thead><tbody>{items.map(item => <tr key={item.item_id}>
                <td><input type="checkbox" aria-label={`选择商品 ${item.item_id}`} disabled={busy} checked={selected.has(item.item_id)} onChange={e => setSelected(previous => {const next = new Set(previous); if (e.target.checked) next.add(item.item_id); else next.delete(item.item_id); return next})} /></td>
                <td className="max-w-[380px]"><ItemSummary item={item} /></td><td className="whitespace-nowrap">{item.item_price || item.price || '-'}</td><td className="whitespace-nowrap text-xs text-slate-500">{item.platform_status || item.item_status_desc || '状态未知'}</td>
              </tr>)}</tbody></table>
            )}
          </div>
          <Pager page={page} pageSize={pageSize} total={total} loading={busy || loading} onPageChange={setPage}
            onPageSizeChange={size => { setPageSize(size); setPage(1) }} />
          {results.length > 0 && <div role="status" className="max-h-48 space-y-2 overflow-auto rounded-md border border-slate-200 p-3 text-xs dark:border-slate-700">
            {results.map(row => <p key={row.item_id} className={row.status === 'failed' ? 'text-red-600' : row.status === 'created' ? 'text-green-700' : 'text-amber-700'}>
              商品 {row.item_id} · {row.status === 'created' ? '已导入' : row.status === 'exists' ? '已跳过' : '未导入'}：{row.message}
            </p>)}
          </div>}
          {!!importedIds.length && <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">本次新导入 {importedIds.length} 件素材，已保留原商品资料。可以继续设置类目，也可以稍后在素材库操作；跳过的旧素材不会被修改。</p>}
        </div>
        <div className="modal-footer flex flex-wrap justify-end gap-2 [&>button]:whitespace-nowrap">
          <button className="btn-ios-secondary" disabled={saving || configuring} onClick={close}>{importedIds.length ? '完成，暂不设置' : '关闭'}</button>
          {!!importedIds.length && <button className="btn-ios-primary" disabled={busy} onClick={configure}>{configuring ? '正在读取素材…' : '设置本次导入素材的类目'}</button>}
          {(!importedIds.length || !!selected.size) && <button className="btn-ios-primary" disabled={busy || loading || !selected.size} onClick={save}>{saving || preparing ? '导入中…' : `导入所选（${selected.size}）`}</button>}
        </div>
      </div>
    </div>
  )
}
