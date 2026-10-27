import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { useBatchTracking } from './useBatchTracking'
import { batchStateLabels, formatBeijingTime } from '@/utils/batchSchedule'

const labels: Record<string, string> = {pending: '等待发布', publishing: '发布中', success: '发布成功', failed: '发布失败', unknown: '结果待核查', cancelled: '已取消'}
export function BatchPublishResults({track, accountName, onClear, submitting}: {
  track: ReturnType<typeof useBatchTracking>; accountName: (id: string) => string
  onClear: () => void; submitting: boolean
}) {
  const [acknowledged, setAcknowledged] = useState(false)
  if (!track.batchId) return null
  return <section className="vben-card"><div className="vben-card-header"><h2 className="vben-card-title">发布任务与逐项结果</h2><button className="btn-ios-secondary" disabled={track.checking || submitting} onClick={track.refresh}><RefreshCw className={`h-4 w-4 ${track.checking ? 'animate-spin' : ''}`} />恢复查询</button></div><div className="vben-card-body space-y-3">
    <p className="break-all text-xs text-slate-400">请求号：{track.batchId}</p>
    {track.error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">{track.error}</p>}
    {track.progress?.tracking_lost && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-700">{track.progress.message}</p>}
    {track.progress && <>
      {track.progress.mode && <p className="text-sm">{track.progress.mode === 'scheduled' ? '定时发布' : '立即开始'} · 北京时间 {formatBeijingTime(track.progress.start_at)} · 每件间隔 {(track.progress.interval_seconds ?? 0)/60} 分钟{track.progress.next_run_at && ` · 下一次 ${formatBeijingTime(track.progress.next_run_at)}`}</p>}
      <p className="text-sm">总计 {track.progress.total} · 成功 {track.progress.success} · 失败 {track.progress.failed} · 等待 {track.progress.pending} · 发布中 {track.progress.publishing}{!!track.progress.cancelled && ` · 已取消 ${track.progress.cancelled}`}{!!track.progress.unknown && ` · 待核查 ${track.progress.unknown}`} <strong className="ml-2 text-blue-600">{track.progress.status ? batchStateLabels[track.progress.status] ?? track.progress.status : track.progress.finished ? '本批执行结束' : '任务尚未确认结束'}</strong></p>
      <div className="overflow-x-auto"><table className="table-ios w-full min-w-[650px]"><thead><tr><th>店铺 / 素材</th><th>状态</th><th>结果与原因</th></tr></thead><tbody>{track.progress.items?.map(item => <tr key={item.id}><td><p className="max-w-96 truncate" title={item.title}>{item.title}</p><p className="text-xs text-slate-400">{accountName(item.account_id)} · 素材 {item.material_id}</p></td><td className="whitespace-nowrap">{track.progress?.tracking_lost && ['pending', 'publishing'].includes(item.status) ? '状态待核查' : labels[item.status] ?? item.status}</td><td className="max-w-md break-words">{item.status === 'success' && item.item_id ? <a className="text-blue-600" href={`https://www.goofish.com/item?id=${encodeURIComponent(item.item_id)}`} target="_blank" rel="noopener noreferrer">查看已发布商品</a> : item.error_message || '—'}</td></tr>)}</tbody></table></div>
      {track.progress.account_statuses.map(a => <p key={a.account_id} className="text-xs text-slate-500">{accountName(a.account_id)}：{a.sync_message}</p>)}
    </>}
    <div className="flex flex-wrap items-center gap-4"><Link className="text-sm text-blue-600" to="/product-publish/logs">查看发布日志</Link>{(track.error || track.progress?.tracking_lost) && <label className="flex items-center gap-2 text-xs text-slate-500"><input type="checkbox" checked={acknowledged} onChange={e => setAcknowledged(e.target.checked)} />我已核查发布日志和闲鱼商品，并确认后台已停止</label>}
      {(track.progress?.finished || acknowledged) && <button className="text-sm text-slate-500" disabled={submitting} onClick={() => { track.forget(); setAcknowledged(false); onClear() }}>结束本页跟踪</button>}
    </div>
  </div></section>
}
