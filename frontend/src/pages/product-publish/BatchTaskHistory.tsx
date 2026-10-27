import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { cancelPublishBatch, getPublishBatches, type PublishBatchSummary } from '@/api/productPublish'
import { batchStateLabels, formatBeijingTime } from '@/utils/batchSchedule'

export function BatchTaskHistory({revision, onTrack, onCancelled}: {
  revision: number; onTrack: (id: string) => void; onCancelled: () => void
}) {
  const [page, setPage] = useState(1)
  const [items, setItems] = useState<PublishBatchSummary[]>([])
  const [total, setTotal] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async () => {
      setLoading(true)
      try {
        const res = await getPublishBatches(page)
        if (!active) return
        if (!res.success || !res.data) throw new Error()
        setItems(res.data.list); setTotal(res.data.total); setError('')
        if (res.data.list.some(j => !j.finished && j.status !== 'attention')) timer = setTimeout(load, 10000)
      } catch { if (active) setError('任务列表加载失败，请重试；已有任务不会因此取消') }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false; clearTimeout(timer) }
  }, [revision, refresh, page])
  const cancel = async (id: string) => {
    if (cancelling) return
    setCancelling(true)
    try {
      const res = await cancelPublishBatch(id)
      if (!res.success) { setError(res.message || '取消失败，请重新查询'); return }
      setConfirmId(null); setRefresh(v => v + 1); onCancelled()
    } catch { setError('未能确认取消结果，请刷新任务列表核查，勿假定已经停止') }
    finally { setCancelling(false) }
  }
  return <section className="vben-card"><div className="vben-card-header"><h2 className="vben-card-title">发布任务列表</h2><button className="btn-ios-secondary" disabled={loading} onClick={() => setRefresh(v => v + 1)}><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新任务</button></div>
    <div className="vben-card-body space-y-3"><p className="text-xs text-slate-500">任务保存在服务器，可随时回来查看。取消只停止尚未开始的商品，正在执行的请求返回后保留真实结果。</p>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p>}
      <div className="overflow-x-auto"><table className="table-ios w-full min-w-[850px]"><thead><tr><th>任务 / 发布时间（北京）</th><th>间隔</th><th>进度</th><th>状态</th><th>下一次执行</th><th>操作</th></tr></thead><tbody>
        {!items.length ? <tr><td colSpan={6} className="py-8 text-center text-slate-400">{error ? '加载未完成' : loading ? '正在加载任务…' : '暂无发布任务，选择素材并检查后可创建'}</td></tr> : items.map(job => <tr key={job.batch_id}>
          <td><p>{job.mode === 'scheduled' ? '定时发布' : '立即开始'} · {formatBeijingTime(job.start_at)}</p><p className="text-xs text-slate-400" title={job.batch_id}>请求号：{job.batch_id.slice(0,8)}</p></td>
          <td className="whitespace-nowrap">{(job.interval_seconds ?? 0) / 60} 分钟</td><td className="text-xs">共{job.total} · 成功{job.success} · 失败{job.failed}{!!job.cancelled && ` · 取消${job.cancelled}`}{!!job.unknown && ` · 待核查${job.unknown}`}</td>
          <td className="whitespace-nowrap">{batchStateLabels[job.status ?? ''] ?? '状态待核查'}</td><td className="whitespace-nowrap">{formatBeijingTime(job.next_run_at)}</td>
          <td><div className="flex flex-wrap gap-3 whitespace-nowrap text-sm"><button className="text-blue-600" onClick={() => onTrack(job.batch_id)}>查看进度</button>{!job.finished && !job.cancel_requested && <button className="text-red-600" disabled={cancelling} onClick={() => setConfirmId(job.batch_id)}>取消剩余</button>}</div>
            {confirmId === job.batch_id && <div className="mt-2 space-y-2 text-xs"><p>确认停止未开始的商品？已发布的商品保持不变。</p><div className="flex gap-3"><button className="text-red-600" disabled={cancelling} onClick={() => cancel(job.batch_id)}>{cancelling ? '取消中…' : '确认取消剩余'}</button><button disabled={cancelling} onClick={() => setConfirmId(null)}>保留任务</button></div></div>}
          </td>
        </tr>)}
      </tbody></table></div><div className="flex justify-end gap-3 text-sm text-slate-500"><span>共 {total} 个任务</span><button disabled={page <= 1 || loading} className="disabled:opacity-30" onClick={() => setPage(v => v - 1)}>上一页</button><span>{page} / {Math.max(1, Math.ceil(total/10))}</span><button disabled={page*10 >= total || loading} className="disabled:opacity-30" onClick={() => setPage(v => v + 1)}>下一页</button></div>
    </div>
  </section>
}
