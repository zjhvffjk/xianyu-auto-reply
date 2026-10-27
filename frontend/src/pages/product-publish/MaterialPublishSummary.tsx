import type { ProductMaterial } from '@/api/productPublish'
import { formatBeijingTime } from '@/utils/batchSchedule'

const states: Record<string, string> = {success: '发布成功', failed: '发布失败', pending: '等待发布', publishing: '发布中', unknown: '结果待核查', cancelled: '已取消'}

export function MaterialPublishSummary({material}: {material: ProductMaterial}) {
  const log = material.latest_publication
  if (!log) return <p className="mt-2 text-xs text-slate-400">暂无本系统发布记录</p>
  const color = log.status === 'success' ? 'text-emerald-700' : log.status === 'failed' || log.status === 'unknown' ? 'text-amber-700' : 'text-slate-500'
  return <div className="mt-2 space-y-1 text-xs">
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className={color}>最近：{states[log.status] || log.status}</span><time className="text-slate-400" title="北京时间">{formatBeijingTime(log.created_at)}</time>{log.item_url && <a href={log.item_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">查看商品</a>}</div>
    <p className="truncate text-slate-500" title={log.account_name}>发布店铺：{log.account_name}</p>
    {log.error_message && <details className="max-w-sm text-amber-700"><summary className="cursor-pointer">查看{log.status === 'unknown' ? '待核查' : '失败'}原因</summary><p className="mt-1 whitespace-normal break-words">{log.error_message}</p></details>}
  </div>
}
