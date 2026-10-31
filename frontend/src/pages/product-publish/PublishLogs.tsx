import { getAccountName } from '@/utils/accountLabel'
﻿/**
 * 发布日志页面
 *
 * 功能：
 * 1. 分页展示商品发布历史记录
 * 2. 按账号/状态过滤
 * 3. 显示发布结果
 * 4. 成功的记录可直接跳转查看商品
 */
import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { ScrollText, RefreshCw, ExternalLink, ChevronLeft, ChevronRight, Loader2, Trash2 } from 'lucide-react'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { clearPublishLogs, getPublishLogs, reconcilePublishLog, type PublishLog } from '@/api/productPublish'
import { getAccountDetails } from '@/api/accounts'
import { PageLoading } from '@/components/common/Loading'

const STATUS_CONFIG: Record<string, { label: string; cls: string }> = {
  pending:    { label: '待处理', cls: 'badge-gray' },
  publishing: { label: '发布中', cls: 'badge-warning' },
  success:    { label: '成功',   cls: 'badge-success' },
  failed:     { label: '失败',   cls: 'badge-danger' },
  unknown:    { label: '待核查', cls: 'badge-warning' },
  cancelled:  { label: '已取消', cls: 'badge-gray' },
}

const ADDRESS_SOURCE_CONFIG: Record<string, { label: string; cls: string }> = {
  material: { label: '素材地址', cls: 'badge-primary' },
  account_pool: { label: '账号随机', cls: 'badge-warning' },
  global_pool: { label: '全局随机', cls: 'badge-gray' },
  personal_pool: { label: '个人随机', cls: 'badge-primary' },
}

export function PublishLogs() {
  const { addToast } = useUIStore()
  const { user } = useAuthStore()
  const isAdmin = Boolean(user?.is_admin)
  const [loading, setLoading] = useState(true)
  const [tableLoading, setTableLoading] = useState(false)
  const [logs, setLogs] = useState<PublishLog[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [totalPages, setTotalPages] = useState(0)
  const [accounts, setAccounts] = useState<any[]>([])
  const [filterAccount, setFilterAccount] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [reviewLog, setReviewLog] = useState<PublishLog | null>(null)
  const [resolution, setResolution] = useState<'' | 'published' | 'not_published'>('')
  const [reviewItemId, setReviewItemId] = useState('')
  const [reviewConfirmed, setReviewConfirmed] = useState(false)
  const [reviewSaving, setReviewSaving] = useState(false)

  const saveReview = async () => {
    if (!reviewLog || !resolution || !reviewConfirmed || reviewSaving) return
    setReviewSaving(true)
    try {
      const result = await reconcilePublishLog(reviewLog.id, {
        resolution, confirmed: true,
        ...(resolution === 'published' ? { item_id: reviewItemId.trim() } : {}),
      })
      if (!result.success) {
        addToast({ type: 'error', message: result.message || '保存核查结果失败' })
        return
      }
      setReviewLog(null)
      addToast({ type: 'success', message: result.message })
      await load(page, pageSize)
    } catch {
      addToast({ type: 'error', message: '保存失败，请刷新记录确认状态后再操作' })
    } finally {
      setReviewSaving(false)
    }
  }

  const load = async (p = page, size = pageSize, account = filterAccount, status = filterStatus) => {
    setTableLoading(true)
    try {
      const res = await getPublishLogs(p, size, account || undefined, status || undefined)
      if (res.success) {
        setLogs(res.data.list)
        setTotal(res.data.total)
        setTotalPages(res.data.total_pages)
      } else {
        addToast({ type: 'error', message: res.message || '加载失败' })
      }
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    } finally {
      setLoading(false)
      setTableLoading(false)
    }
  }

  useEffect(() => {
    getAccountDetails().then(list => setAccounts(list)).catch(() => {})
  }, [])

  useEffect(() => { load(page, pageSize) }, [page, pageSize])

  // 点击「查询」：用当前筛选值从第一页加载
  const handleSearch = () => {
    if (page === 1) load(1, pageSize)
    else setPage(1)
  }

  // 点击「重置」：清空筛选条件并重新加载
  const handleReset = () => {
    setFilterAccount('')
    setFilterStatus('')
    if (page === 1) load(1, pageSize, '', '')
    else setPage(1)
  }

  const handlePageSizeChange = (size: number) => { setPageSize(size); setPage(1) }

  const handleClearLogs = async () => {
    try {
      setClearing(true)
      const result = await clearPublishLogs()
      if (result.success) {
        addToast({ type: 'success', message: result.message || '清空成功' })
        setShowClearConfirm(false)
        if (page === 1) {
          await load(1, pageSize)
        } else {
          setPage(1)
        }
      } else {
        addToast({ type: 'error', message: result.message || '清空失败' })
      }
    } catch (error: any) {
      addToast({ type: 'error', message: error?.message || '清空失败' })
    } finally {
      setClearing(false)
    }
  }

  const formatDate = (d: string) =>
    d ? new Date(d).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'

  if (loading) return <PageLoading />

  return (
    <div className="space-y-3 sm:space-y-4">
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="page-title">发布日志</h1>
          <p className="page-description">查看所有商品发布记录及结果</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowClearConfirm(true)}
            className="btn-ios-danger"
            title="清空10天前的日志"
            disabled={tableLoading || clearing}
          >
            <Trash2 className="w-4 h-4" />
            清空日志
          </button>
          <button className="btn-ios-secondary" onClick={() => load(page, pageSize)} disabled={tableLoading || clearing}>
            <RefreshCw className={`w-4 h-4 ${tableLoading ? 'animate-spin' : ''}`} />刷新
          </button>
        </div>
      </div>

      {/* 筛选栏 */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
        <div className="vben-card-body">
          <div className="flex flex-wrap items-end gap-4">
            <div className="input-group">
              <label className="input-label">筛选账号</label>
              <select className="input-ios" value={filterAccount}
                onChange={e => setFilterAccount(e.target.value)}>
                <option value="">所有账号</option>
                {accounts.map((a: any) => (
                  <option key={a.id} value={a.id}>{getAccountName(a)}</option>
                ))}
              </select>
            </div>
            <div className="input-group">
              <label className="input-label">发布状态</label>
              <select className="input-ios" value={filterStatus}
                onChange={e => setFilterStatus(e.target.value)}>
                <option value="">所有状态</option>
                {Object.entries(STATUS_CONFIG).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-end gap-2 ml-auto">
              <button className="btn-ios-primary" onClick={handleSearch} disabled={tableLoading}>
                查询
              </button>
              {(filterAccount || filterStatus) && (
                <button className="btn-ios-secondary text-red-500" onClick={handleReset} disabled={tableLoading}>
                  重置
                </button>
              )}
            </div>
          </div>
        </div>
      </motion.div>

      {/* 日志表格 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="vben-card flex flex-col"
        style={{ height: 'calc(100vh - 310px)', minHeight: '400px' }}
      >
        <div className="vben-card-header">
          <h2 className="vben-card-title"><ScrollText className="w-4 h-4" />发布记录</h2>
          <span className="badge-primary">共 {total} 条</span>
        </div>
        <div className="flex-1 overflow-x-auto overflow-y-auto">
          <table className="table-ios">
            <thead className="sticky top-0 bg-white dark:bg-slate-800 z-10">
              <tr>
                {isAdmin && <th>所属用户</th>}
                <th>账号</th>
                <th>商品标题</th>
                <th>价格</th>
                <th>所在地</th>
                <th>状态</th>
                <th>结果 / 错误</th>
                <th>发布时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {tableLoading ? (
                <tr><td colSpan={isAdmin ? 9 : 8} className="text-center py-12">
                  <Loader2 className="w-6 h-6 animate-spin text-blue-500 mx-auto" />
                </td></tr>
              ) : logs.length === 0 ? (
                <tr><td colSpan={isAdmin ? 9 : 8} className="text-center py-12 text-slate-400">
                  <div className="flex flex-col items-center gap-2">
                    <ScrollText className="w-12 h-12 text-slate-300" />
                    <p>暂无发布记录</p>
                  </div>
                </td></tr>
              ) : logs.map(log => {
                const s = STATUS_CONFIG[log.status] ?? { label: log.status, cls: 'badge-gray' }
                const addressSource = log.address_source ? (ADDRESS_SOURCE_CONFIG[log.address_source] ?? { label: log.address_source, cls: 'badge-gray' }) : null
                const account = accounts.find((a: any) => a.id === log.account_id)
                return (
                  <tr key={log.id}>
                    {isAdmin && (
                      <td className="text-sm text-slate-600 dark:text-slate-400 whitespace-nowrap">
                        {log.username || '-'}
                      </td>
                    )}
                    <td className="text-sm font-medium text-blue-600 dark:text-blue-400 whitespace-nowrap">
                      {account?.note || log.account_id}
                    </td>
                    <td className="max-w-[200px]">
                      <span className="truncate block text-slate-800 dark:text-slate-100" title={log.title}>
                        {log.title}
                      </span>
                    </td>
                    <td className="text-amber-600 whitespace-nowrap font-medium">
                      {log.price ? `¥${log.price}` : '-'}
                    </td>
                    <td className="max-w-[220px]">
                      {log.resolved_address_text ? (
                        <div className="space-y-1">
                          <span className="truncate block text-slate-800 dark:text-slate-100" title={log.resolved_address_text}>
                            {log.resolved_address_text}
                          </span>
                          {addressSource && <span className={addressSource.cls}>{addressSource.label}</span>}
                        </div>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td><span className={s.cls}>{s.label}</span></td>
                    <td className="max-w-[200px]">
                      {log.item_url ? (
                        <a href={log.item_url} target="_blank" rel="noopener noreferrer"
                          className="flex items-center gap-1 text-sm text-blue-500 hover:underline">
                          <ExternalLink className="w-3 h-3" />查看商品
                        </a>
                      ) : log.error_message ? (
                        <span className="text-xs text-red-500 truncate block" title={log.error_message}>
                          {log.error_message}
                        </span>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="text-sm text-slate-500 whitespace-nowrap">
                      {formatDate(log.created_at)}
                    </td>
                    <td>
                      {log.status === 'unknown' && !log.source_event_id ? (
                        <button className="btn-ios-secondary text-xs whitespace-nowrap" onClick={() => {
                          setReviewLog(log); setResolution(''); setReviewItemId(''); setReviewConfirmed(false)
                        }}>记录核查结果</button>
                      ) : <span className="text-slate-400">-</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {total > 0 && (
          <div className="flex-shrink-0 flex flex-col sm:flex-row items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-700 gap-3">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <span>每页</span>
              <select value={pageSize} onChange={e => handlePageSizeChange(Number(e.target.value))}
                className="px-2 py-1 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value={10}>10 条</option>
                <option value={20}>20 条</option>
                <option value={50}>50 条</option>
                <option value={100}>100 条</option>
              </select>
              <span>共 {total} 条</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">第 {page} / {totalPages} 页</span>
              <button onClick={() => setPage(p => p - 1)} disabled={page <= 1 || tableLoading}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages || tableLoading}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </motion.div>

      {reviewLog && (
        <div className="modal-overlay" onClick={() => { if (!reviewSaving) setReviewLog(null) }}>
          <div className="modal-content max-w-lg" role="dialog" aria-modal="true" aria-labelledby="publish-review-title" onClick={e => e.stopPropagation()}>
            <div className="modal-header"><h3 id="publish-review-title" className="modal-title">核查发布结果</h3></div>
            <div className="modal-body space-y-4">
              <div className="rounded-lg bg-slate-50 dark:bg-slate-800 p-3 text-sm space-y-1">
                <p className="font-medium">{reviewLog.title}</p>
                <p>目标店铺：{getAccountName(accounts.find((a: any) => a.id === reviewLog.account_id) || { id: reviewLog.account_id })}</p>
                <p>记录 #{reviewLog.id} · {formatDate(reviewLog.created_at)}</p>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-300">请先打开该店铺的闲鱼商品列表，检查在售、下架及审核中的商品，核对本次是否已发布。修改素材不会消除这条历史记录。</p>
              <label className="flex items-start gap-2 text-sm cursor-pointer"><input type="radio" name="publish-resolution" checked={resolution === 'not_published'} onChange={() => { setResolution('not_published'); setReviewConfirmed(false) }} disabled={reviewSaving} />确认未发布，解除本条记录的拦截</label>
              <label className="flex items-start gap-2 text-sm cursor-pointer"><input type="radio" name="publish-resolution" checked={resolution === 'published'} onChange={() => { setResolution('published'); setReviewConfirmed(false) }} disabled={reviewSaving} />确认已发布，补录商品ID</label>
              {resolution === 'published' && <div className="input-group">
                <label htmlFor="review-item-id" className="input-label">商品ID</label>
                <input id="review-item-id" className="input-ios" value={reviewItemId} onChange={e => setReviewItemId(e.target.value)} disabled={reviewSaving} placeholder="填写闲鱼商品链接中的数字ID" inputMode="numeric" />
                <p className="text-xs text-slate-500">请先在商品管理刷新该店铺，系统会校验商品属于同一店铺。</p>
              </div>}
              {resolution && <label className="flex items-start gap-2 text-sm cursor-pointer"><input type="checkbox" checked={reviewConfirmed} onChange={e => setReviewConfirmed(e.target.checked)} disabled={reviewSaving} />{resolution === 'not_published' ? '我已核查目标店铺，确认本次未发布，知道重新创建任务可能造成重复商品。' : '我已核对商品ID与目标店铺，确认这是本次发布的商品。'}</label>}
              <p className="text-xs text-slate-500">这里只保存核查结果，不会发布商品或自动恢复原批次。确认未发布后，请返回批量发布重新检查并创建任务。</p>
            </div>
            <div className="modal-footer">
              <button className="btn-ios-secondary" disabled={reviewSaving} onClick={() => setReviewLog(null)}>取消</button>
              <button className="btn-ios-primary" disabled={reviewSaving || !resolution || !reviewConfirmed || (resolution === 'published' && !/^\d{6,24}$/.test(reviewItemId.trim()))} onClick={saveReview}>{reviewSaving ? '保存中…' : '保存核查结果'}</button>
            </div>
          </div>
        </div>
      )}
      {showClearConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-slate-800 rounded-lg shadow-xl max-w-md w-full p-6">
            <h3 className="text-lg font-semibold mb-4">确认清空日志</h3>
            <p className="text-slate-600 dark:text-slate-400 mb-6">
              此操作将清空10天前的发布日志数据，最近10天的日志将被保留。确定要继续吗？
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowClearConfirm(false)}
                disabled={clearing}
                className="btn-ios-secondary"
              >
                取消
              </button>
              <button
                onClick={handleClearLogs}
                disabled={clearing}
                className="btn-ios-danger"
              >
                {clearing ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    清空中...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    确认清空
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default PublishLogs
