import { useEffect, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { cancelPublishBatch, deletePublishBatchHistory, getPublishBatches, type PublishBatchSummary } from '@/api/productPublish'
import { batchStateLabels, formatBeijingTime } from '@/utils/batchSchedule'
import { useAuthStore } from '@/store/authStore'
import { notifyPublishHistoryCleared, subscribePublishHistoryCleared } from '@/utils/publishHistoryEvents'
import { Pager } from '@/components/common/Pager'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { useUIStore } from '@/store/uiStore'

export function BatchTaskHistory({revision, onTrack, onCancelled}: {
  revision: number; onTrack: (id: string) => void; onCancelled: () => void
}) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [items, setItems] = useState<PublishBatchSummary[]>([])
  const [total, setTotal] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const addToast = useUIStore(state => state.addToast)
  const userId = useAuthStore(state => state.user?.user_id)
  useEffect(() => subscribePublishHistoryCleared(userId, () => {
    setSelectedIds(new Set()); setPage(1); setRefresh(value => value + 1)
  }), [userId])
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      setLoading(true)
      try {
        const res = await getPublishBatches(page, pageSize)
        if (!active) return
        if (!res.success || !res.data) throw new Error()
        setItems(res.data.list); setTotal(res.data.total); setError('')
        const deletableIds = new Set(res.data.list.filter(job => job.can_delete_history).map(job => job.batch_id))
        setSelectedIds(previous => new Set([...previous].filter(id => deletableIds.has(id))))
        const lastPage = Math.max(1, Math.ceil(res.data.total / pageSize))
        if (page > lastPage) setPage(lastPage)
        else if (res.data.list.some(j => !j.finished && j.status !== 'attention')) timer = setTimeout(load, 10000)
      } catch {
        if (active) {
          setError('任务列表加载失败，将自动恢复查询；已有任务继续执行')
          timer = setTimeout(load, 10000)
        }
      }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false; clearTimeout(timer) }
  }, [revision, refresh, page, pageSize])
  const cancel = async (id: string) => {
    if (cancelling || deleting) return
    setCancelling(true)
    try {
      const res = await cancelPublishBatch(id)
      if (!res.success) { setError(res.message || '取消失败，请重新查询'); return }
      setConfirmId(null); setRefresh(v => v + 1); onCancelled()
    } catch { setError('未能确认取消结果，请刷新任务列表核查，勿假定已经停止') }
    finally { setCancelling(false) }
  }
  const deleteSelected = async () => {
    if (deleting || cancelling || !selectedIds.size) return
    setDeleting(true)
    try {
      const res = await deletePublishBatchHistory([...selectedIds])
      if (!res.success) {
        addToast({type: 'error', message: res.message || '删除任务历史失败，请重试'})
        return
      }
      setShowDeleteConfirm(false)
      addToast({type: 'success', message: res.message || '所选任务历史已删除'})
      notifyPublishHistoryCleared(userId)
    } catch {
      addToast({type: 'error', message: '删除结果未确认，请刷新任务列表核查；未取消任何发布任务'})
    } finally { setDeleting(false) }
  }
  const selectableItems = items.filter(job => job.can_delete_history)
  const allSelected = selectableItems.length > 0 && selectableItems.every(job => selectedIds.has(job.batch_id))
  const busy = loading || cancelling || deleting
  return <section className="vben-card"><div className="vben-card-header"><h2 className="vben-card-title">发布任务列表</h2><button className="btn-ios-secondary" disabled={busy} onClick={() => setRefresh(v => v + 1)}><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新任务</button></div>
    <div className="vben-card-body space-y-3"><p className="text-xs text-slate-500">可勾选删除已结束的任务历史，商品和发布日志保留。未完成或待核查的任务无法删除。取消只停止尚未开始的商品，正在执行的请求返回后保留真实结果。</p>
      <div className="flex flex-wrap items-center gap-3"><span className="text-sm text-slate-500">已选 {selectedIds.size} 个任务</span><button className="btn-ios-secondary text-red-600" disabled={busy || !selectedIds.size} onClick={() => setShowDeleteConfirm(true)}><Trash2 className="h-4 w-4" />删除所选（{selectedIds.size}）</button>{selectedIds.size > 0 && <button className="text-sm text-slate-500" disabled={deleting} onClick={() => setSelectedIds(new Set())}>取消选择</button>}</div>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto"><table className="table-ios w-full min-w-[850px]"><thead><tr><th className="w-10"><input type="checkbox" className="checkbox-ios" aria-label="选择本页可删除任务" checked={allSelected} disabled={busy || !selectableItems.length} onChange={() => setSelectedIds(allSelected ? new Set() : new Set(selectableItems.map(job => job.batch_id)))} /></th><th>任务 / 发布时间（北京）</th><th>间隔</th><th>进度</th><th>状态</th><th>下一次执行</th><th>操作</th></tr></thead><tbody>
        {!items.length ? <tr><td colSpan={7} className="py-8 text-center text-slate-400">{error ? '加载未完成' : loading ? '正在加载任务…' : '暂无发布任务，选择素材并检查后可创建'}</td></tr> : items.map(job => <tr key={job.batch_id}>
          <td><input type="checkbox" className="checkbox-ios" aria-label={`选择任务历史 ${job.batch_id}`} title={job.can_delete_history ? '选择此任务历史' : '未完成或待核查的任务不可删除'} checked={selectedIds.has(job.batch_id)} disabled={busy || !job.can_delete_history} onChange={() => setSelectedIds(previous => { const next = new Set(previous); if (next.has(job.batch_id)) next.delete(job.batch_id); else next.add(job.batch_id); return next })} /></td>
          <td><p>{job.mode === 'scheduled' ? '定时发布' : '立即开始'} · {formatBeijingTime(job.start_at)}</p><p className="text-xs text-slate-400" title={job.batch_id}>请求号：{job.batch_id.slice(0,8)}</p></td>
          <td className="whitespace-nowrap">{(job.interval_seconds ?? 0) / 60} 分钟</td><td className="text-xs">共{job.total} · 成功{job.success} · 失败{job.failed}{!!job.cancelled && ` · 取消${job.cancelled}`}{!!job.unknown && ` · 待核查${job.unknown}`}</td>
          <td className="whitespace-nowrap">{batchStateLabels[job.status ?? ''] ?? '状态待核查'}</td><td className="whitespace-nowrap">{formatBeijingTime(job.next_run_at)}</td>
          <td><div className="flex flex-wrap gap-3 whitespace-nowrap text-sm"><button className="text-blue-600" onClick={() => onTrack(job.batch_id)}>查看进度</button>{!job.finished && !job.cancel_requested && <button className="text-red-600" disabled={cancelling || deleting} onClick={() => setConfirmId(job.batch_id)}>取消剩余</button>}</div>
            {confirmId === job.batch_id && <div className="mt-2 space-y-2 text-xs"><p>确认停止未开始的商品？已发布的商品保持不变。</p><div className="flex gap-3"><button className="text-red-600" disabled={cancelling} onClick={() => cancel(job.batch_id)}>{cancelling ? '取消中…' : '确认取消剩余'}</button><button disabled={cancelling} onClick={() => setConfirmId(null)}>保留任务</button></div></div>}
          </td>
        </tr>)}
      </tbody></table></div><Pager page={page} pageSize={pageSize} total={total} loading={busy}
        onPageChange={next => { setSelectedIds(new Set()); setPage(next) }} onPageSizeChange={size => { setSelectedIds(new Set()); setPageSize(size); setPage(1) }} />
    </div>
    <ConfirmModal isOpen={showDeleteConfirm} ariaLabel="删除所选任务历史" title="删除所选任务历史" type="danger"
      message={<><p>确认删除选中的 {selectedIds.size} 个任务历史？</p><p className="mt-2 text-sm">商品和发布日志保留，未完成或待核查的任务会自动跳过。</p></>}
      confirmText="确认删除" loading={deleting} onConfirm={deleteSelected} onCancel={() => { if (!deleting) setShowDeleteConfirm(false) }} />
  </section>
}
