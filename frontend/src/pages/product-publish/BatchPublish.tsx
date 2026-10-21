/**
 * 批量发布页面
 *
 * 功能：
 * 1. 选择多个闲鱼账号
 * 2. 从素材库选择多条素材
 * 3. 提交批量发布任务（后台异步执行）
 * 4. 轮询任务进度，展示完成状态
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Layers, CheckCircle, XCircle, Clock, Play, Loader2, Timer, CalendarClock, Ban } from 'lucide-react'
import { useUIStore } from '@/store/uiStore'
import { checkContentRisk, publishBatch, getBatchStatus, getMaterials, createScheduledPublish, listScheduledPublish, cancelScheduledPublish, type ContentRiskResult, type MaterialRiskItem, type ProductMaterial, type BatchAccountStatus, type ScheduledPublishTask, type ScheduledPublishStatus } from '@/api/productPublish'
import { getAccountDetails } from '@/api/accounts'
import { getAccountOptionLabel } from '@/utils/accountLabel'
import { ContentRiskModal } from '@/components/common/ContentRiskModal'

/** 发布模式：立即发布 / 定时发布 */
type PublishMode = 'immediate' | 'scheduled'

/** 定时发布间隔技术下限（分钟）：scheduler 每 30 秒扫一轮，低于此值无意义，与后端一致 */
const MIN_INTERVAL_MINUTES = 0.5
/** 默认间隔（分钟）：5 分钟，防平台风控的保守默认值 */
const DEFAULT_INTERVAL_MINUTES = 5
/** 风控提醒阈值（分钟）：低于该值前端给出警告但不拦截，发布节奏由用户自定 */
const RISK_WARNING_MINUTES = 5

/** 把 Date 格式化成 datetime-local 输入框需要的值（本地时区） */
function toDatetimeLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const SCHEDULED_STATUS_LABEL: Record<ScheduledPublishStatus, string> = {
  pending: '等待中',
  running: '执行中',
  completed: '已完成',
  cancelled: '已取消',
  failed: '已失败',
}

const SCHEDULED_STATUS_CLASS: Record<ScheduledPublishStatus, string> = {
  pending: 'badge-info',
  running: 'badge-primary',
  completed: 'badge-success',
  cancelled: 'badge-secondary',
  failed: 'badge-danger',
}

interface BatchProgress {
  batch_id: string
  total: number
  success: number
  failed: number
  publishing: number
  pending: number
  finished: boolean
  account_statuses: BatchAccountStatus[]
}

// sessionStorage 键名：保存进行中的 batch_id
const BATCH_ID_STORAGE_KEY = 'batch_publish_active_batch_id'

export function BatchPublish() {
  const { addToast } = useUIStore()
  const [accounts, setAccounts] = useState<any[]>([])
  const [materials, setMaterials] = useState<ProductMaterial[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(new Set())
  const [selectedMaterials, setSelectedMaterials] = useState<Set<number>>(new Set())
  const [loadingAccounts, setLoadingAccounts] = useState(true)
  const [loadingMaterials, setLoadingMaterials] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [pendingRisk, setPendingRisk] = useState<ContentRiskResult | null>(null)
  const [pendingMaterialRisks, setPendingMaterialRisks] = useState<MaterialRiskItem[]>([])
  const forcePublishRef = useRef(false)
  const [progress, setProgress] = useState<BatchProgress | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [materialSearch, setMaterialSearch] = useState('')
  // 发布模式与定时参数
  const [publishMode, setPublishMode] = useState<PublishMode>('immediate')
  const [startAt, setStartAt] = useState(() => toDatetimeLocal(new Date(Date.now() + 5 * 60 * 1000)))
  const [intervalMinutes, setIntervalMinutes] = useState(DEFAULT_INTERVAL_MINUTES)
  // 定时任务列表
  const [scheduledTasks, setScheduledTasks] = useState<ScheduledPublishTask[]>([])
  const scheduledPollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const accountNameMap = new Map(accounts.map((account: any) => [account.id, account.note || account.id]))

  const getSyncStatusLabel = (status: BatchAccountStatus['sync_status']) => {
    if (status === 'success') return '已成功'
    if (status === 'failed') return '失败'
    if (status === 'running') return '获取中'
    if (status === 'skipped') return '未触发'
    if (status === 'unknown') return '状态未知'
    return '待执行'
  }

  const getSyncStatusClassName = (status: BatchAccountStatus['sync_status']) => {
    if (status === 'success') return 'badge-success'
    if (status === 'failed') return 'badge-danger'
    if (status === 'running') return 'badge-info'
    if (status === 'skipped') return 'badge-warning'
    if (status === 'unknown') return 'badge-warning'
    return 'badge-secondary'
  }

  /** 清除 sessionStorage 中的 batch_id */
  const clearStoredBatchId = useCallback(() => {
    try { sessionStorage.removeItem(BATCH_ID_STORAGE_KEY) } catch { /* ignore */ }
  }, [])

  /** 保存 batch_id 到 sessionStorage */
  const storeBatchId = useCallback((batchId: string) => {
    try { sessionStorage.setItem(BATCH_ID_STORAGE_KEY, batchId) } catch { /* ignore */ }
  }, [])

  /** 启动轮询批量发布进度 */
  const startPolling = useCallback((batchId: string) => {
    // 避免重复启动
    if (pollingRef.current) clearInterval(pollingRef.current)
    pollingRef.current = setInterval(async () => {
      try {
        const res = await getBatchStatus(batchId)
        if (res.success) {
          setProgress(res.data)
          if (res.data.finished) {
            if (pollingRef.current) clearInterval(pollingRef.current)
            const syncFailedCount = res.data.account_statuses.filter(item => item.sync_status === 'failed').length
            const syncUnknownCount = res.data.account_statuses.filter(item => item.sync_status === 'unknown').length
            const syncProblemCount = syncFailedCount + syncUnknownCount
            addToast({
              type: res.data.failed === 0 && syncProblemCount === 0 ? 'success' : 'warning',
              message: syncFailedCount > 0
                ? `批量发布完成！成功 ${res.data.success} 条，失败 ${res.data.failed} 条，${syncFailedCount} 个账号自动获取商品失败`
                : syncUnknownCount > 0
                  ? `批量发布完成！成功 ${res.data.success} 条，失败 ${res.data.failed} 条，${syncUnknownCount} 个账号自动获取商品状态未知`
                  : `批量发布完成！成功 ${res.data.success} 条，失败 ${res.data.failed} 条`,
            })
          }
        } else {
          if (pollingRef.current) clearInterval(pollingRef.current)
          setProgress(null)
          addToast({ type: 'warning', message: res.message || '批量任务状态已失效，请重新提交任务' })
        }
      } catch { /* 静默处理轮询错误 */ }
    }, 3000)
  }, [addToast])

  useEffect(() => {
    getAccountDetails()
      .then(list => { setAccounts(list); setLoadingAccounts(false) })
      .catch(() => { setLoadingAccounts(false) })
    getMaterials(1, 1000)
      .then(res => { if (res.success) setMaterials(res.data.list); setLoadingMaterials(false) })
      .catch(() => { setLoadingMaterials(false) })

    // 恢复未完成的批量发布任务轮询
    try {
      const savedBatchId = sessionStorage.getItem(BATCH_ID_STORAGE_KEY)
      if (savedBatchId) {
        // 先查询一次状态，确认任务仍有效后再启动轮询
        getBatchStatus(savedBatchId).then(res => {
          if (res.success && !res.data.finished) {
            setProgress(res.data)
            startPolling(savedBatchId)
          } else if (res.success && res.data.finished) {
            // 任务已完成，显示最终状态
            setProgress(res.data)
          } else {
            // 任务已失效，清除缓存以便提交新任务
            clearStoredBatchId()
          }
        }).catch(() => { /* 查询失败，保留缓存下次再试 */ })
      }
    } catch { /* ignore */ }

    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [startPolling, clearStoredBatchId])

  /** 提交批量发布任务 */
  const handleSubmit = async () => {
    if (selectedAccounts.size === 0) { addToast({ type: 'warning', message: '请至少选择一个账号' }); return }
    if (selectedMaterials.size === 0) { addToast({ type: 'warning', message: '请至少选择一条素材' }); return }
    setSubmitting(true)
    try {
      // 发布前违禁内容预检：批量场景在提交前一次性检查所有选中素材
      if (!forcePublishRef.current) {
        const riskCheck = await checkContentRisk({ material_ids: Array.from(selectedMaterials) }).catch(() => null)
        const risk = riskCheck?.data?.risk
        if (risk?.blocked) {
          setPendingRisk(risk)
          setPendingMaterialRisks(riskCheck?.data?.material_risks || [])
          setSubmitting(false)
          return
        }
        if (risk?.level === 'warn') {
          const terms = (risk.hits || []).map((h) => h.term).slice(0, 5).join('、')
          addToast({ type: 'warning', message: `选中素材有风险提示（${terms}），仍继续发布` })
        }
      }

      // 定时发布：创建任务后由 scheduler 到点逐条执行
      if (publishMode === 'scheduled') {
        if (!startAt) { addToast({ type: 'warning', message: '请选择开始时间' }); setSubmitting(false); return }
        if (intervalMinutes < MIN_INTERVAL_MINUTES) {
          addToast({ type: 'warning', message: '发布间隔不能低于 30 秒（调度器每 30 秒扫描一轮，更低无意义）' })
          setSubmitting(false)
          return
        }
        const res = await createScheduledPublish({
          account_ids: Array.from(selectedAccounts),
          material_ids: Array.from(selectedMaterials),
          start_at: startAt,
          interval_seconds: Math.round(intervalMinutes * 60),
        })
        if (res.success) {
          addToast({ type: 'success', message: res.message || '定时发布任务已创建' })
          void loadScheduledTasks()
        } else {
          addToast({ type: 'error', message: res.message || '创建失败' })
        }
        return
      }

      const res = await publishBatch({
        force_publish: forcePublishRef.current,
        account_ids: Array.from(selectedAccounts),
        material_ids: Array.from(selectedMaterials),
      })
      if (res.success) {
        addToast({ type: 'success', message: res.message || '批量发布任务已提交' })
        const batchId = res.data?.batch_id
        const totalCount = res.data?.total ?? 0
        const accountCount = selectedAccounts.size
        const materialCountPerAccount = accountCount > 0 ? Math.floor(totalCount / accountCount) : 0
        if (batchId) {
          storeBatchId(batchId)
          setProgress({
            batch_id: batchId,
            total: totalCount,
            success: 0,
            failed: 0,
            publishing: 0,
            pending: totalCount,
            finished: false,
            account_statuses: Array.from(selectedAccounts).map(accountId => ({
              account_id: accountId,
              total: materialCountPerAccount,
              success: 0,
              failed: 0,
              publishing: 0,
              pending: materialCountPerAccount,
              sync_status: 'pending',
              sync_message: '等待该账号发布完成后自动获取商品',
              sync_total_count: 0,
              sync_saved_count: 0,
            })),
          })
          startPolling(batchId)
        }
      } else {
        addToast({ type: 'error', message: res.message || '提交失败' })
      }
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    } finally {
      setSubmitting(false)
      forcePublishRef.current = false
    }
  }

  /** 加载定时发布任务列表 */
  const loadScheduledTasks = useCallback(async () => {
    try {
      const res = await listScheduledPublish(1, 20)
      if (res.success) setScheduledTasks(res.data?.items || [])
    } catch { /* 静默：列表刷新失败不影响主流程 */ }
  }, [])

  /** 取消定时任务 */
  const handleCancelScheduled = async (taskId: number) => {
    try {
      const res = await cancelScheduledPublish(taskId)
      addToast({ type: res.success ? 'success' : 'error', message: res.message || (res.success ? '已取消' : '取消失败') })
      void loadScheduledTasks()
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    }
  }

  // 有待执行/执行中的任务时每 10 秒刷新一次列表
  useEffect(() => {
    void loadScheduledTasks()
    const hasActive = scheduledTasks.some(t => t.status === 'pending' || t.status === 'running')
    if (hasActive && !scheduledPollingRef.current) {
      scheduledPollingRef.current = setInterval(() => { void loadScheduledTasks() }, 10000)
    } else if (!hasActive && scheduledPollingRef.current) {
      clearInterval(scheduledPollingRef.current)
      scheduledPollingRef.current = null
    }
    return () => {
      if (scheduledPollingRef.current) {
        clearInterval(scheduledPollingRef.current)
        scheduledPollingRef.current = null
      }
    }
  }, [loadScheduledTasks, scheduledTasks])

  const toggleAccount = (id: string) => setSelectedAccounts(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleMaterial = (id: number) => setSelectedMaterials(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAllAccounts = () => selectedAccounts.size === accounts.length ? setSelectedAccounts(new Set()) : setSelectedAccounts(new Set(accounts.map((a: any) => a.id)))
  const toggleAllMaterials = () => {
    const ids = filteredMaterials.map(m => m.id)
    const allSelected = ids.length > 0 && ids.every(id => selectedMaterials.has(id))
    if (allSelected) {
      setSelectedMaterials(prev => { const n = new Set(prev); ids.forEach(id => n.delete(id)); return n })
    } else {
      setSelectedMaterials(prev => { const n = new Set(prev); ids.forEach(id => n.add(id)); return n })
    }
  }

  const filteredMaterials = materialSearch.trim()
    ? materials.filter(m => m.title.toLowerCase().includes(materialSearch.trim().toLowerCase()))
    : materials

  const total = selectedAccounts.size * selectedMaterials.size
  const isDisabled = submitting || total === 0 || (progress !== null && !progress.finished)

  return (
    <div className="space-y-3 sm:space-y-4">
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="page-title">批量发布</h1>
          <p className="page-description">多账号  多素材并发发布，提升发布效率</p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            批量发布时会忽略素材库中填写的宝贝所在地，统一从随机地址库自动分配地址。
          </p>
        </div>
        <div className="text-sm text-slate-500 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 rounded-lg">
          {selectedAccounts.size} 账号  {selectedMaterials.size} 素材 =&nbsp;
          <span className="font-semibold text-blue-600 dark:text-blue-400">{total} 次发布</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 账号选择 */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title">选择账号</h2>
            <button className="text-sm text-blue-500 hover:underline" onClick={toggleAllAccounts}>
              {selectedAccounts.size === accounts.length && accounts.length > 0 ? '取消全选' : '全选'}
            </button>
          </div>
          <div className="vben-card-body">
            {loadingAccounts ? (
              <div className="flex justify-center py-8"><Loader2 className="w-8 h-8 animate-spin text-blue-500" /></div>
            ) : accounts.length === 0 ? (
              <p className="text-center text-slate-400 py-8">暂无账号，请先添加账号</p>
            ) : (
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {accounts.map((a: any) => {
                  const checked = selectedAccounts.has(a.id)
                  const enabled = a.enabled !== false
                  return (
                    <label key={a.id} className={`flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-colors ${checked ? 'bg-blue-50 dark:bg-blue-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-700'}`}>
                      <input type="checkbox" className="w-4 h-4 text-blue-600 rounded accent-blue-500"
                        checked={checked} onChange={() => toggleAccount(a.id)} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate text-slate-800 dark:text-slate-100">
                          {getAccountOptionLabel(a)}
                        </p>
                      </div>
                      <span className={`${enabled ? 'badge-success' : 'badge-secondary'} flex-shrink-0`}>{enabled ? '已启动' : '未启动'}</span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>
        </motion.div>

        {/* 素材选择 */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title">选择素材</h2>
            <button className="text-sm text-blue-500 hover:underline" onClick={toggleAllMaterials}>
              {selectedMaterials.size === filteredMaterials.length && filteredMaterials.length > 0 ? '取消全选' : '全选'}
            </button>
          </div>
          <div className="vben-card-body">
            <input
              className="input-ios w-full mb-2"
              placeholder="搜索素材标题..."
              value={materialSearch}
              onChange={e => setMaterialSearch(e.target.value)}
            />
            {loadingMaterials ? (
              <div className="flex justify-center py-8"><Loader2 className="w-8 h-8 animate-spin text-blue-500" /></div>
            ) : filteredMaterials.length === 0 ? (
              <p className="text-center text-slate-400 py-8">{materials.length === 0 ? '素材库为空，请先在「素材库」页面添加素材' : '没有匹配的素材'}</p>
            ) : (
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {filteredMaterials.map(m => {
                  const checked = selectedMaterials.has(m.id)
                  const specificationCount = (m.specifications || []).length
                  const skuCount = (m.sku_rows || []).length
                  const isMultiSpec = specificationCount > 0 || skuCount > 0
                  return (
                    <label key={m.id} className={`flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-colors ${checked ? 'bg-blue-50 dark:bg-blue-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-700'}`}>
                      <input type="checkbox" className="w-4 h-4 text-blue-600 rounded accent-blue-500"
                        checked={checked} onChange={() => toggleMaterial(m.id)} />
                      {m.images?.[0] ? (
                        <img src={m.images[0]} alt={m.title} className="w-10 h-10 object-cover rounded-lg flex-shrink-0" />
                      ) : (
                        <div className="w-10 h-10 bg-slate-100 dark:bg-slate-700 rounded-lg flex items-center justify-center text-xs text-slate-400 flex-shrink-0">无图</div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate text-slate-800 dark:text-slate-100">{m.title}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">
                          <span className="text-xs text-amber-600">{m.price}</span>
                          {isMultiSpec ? (
                            <span className="badge-info flex-shrink-0">多规格 · {specificationCount}类 / {skuCount}组合</span>
                          ) : (
                            <span className="badge-secondary flex-shrink-0">单规格</span>
                          )}
                        </div>
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
          </div>
        </motion.div>
      </div>

      {/* 发布模式切换 */}
      <div className="flex justify-center">
        <div className="inline-flex rounded-xl bg-slate-100 dark:bg-slate-800 p-1">
          <button
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${publishMode === 'immediate' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-slate-500 dark:text-slate-400'}`}
            onClick={() => setPublishMode('immediate')}
          >
            <Play className="w-4 h-4 inline mr-1" />立即发布
          </button>
          <button
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${publishMode === 'scheduled' ? 'bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-slate-500 dark:text-slate-400'}`}
            onClick={() => setPublishMode('scheduled')}
          >
            <Timer className="w-4 h-4 inline mr-1" />定时发布
          </button>
        </div>
      </div>

      {/* 定时发布参数 */}
      {publishMode === 'scheduled' && (
        <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title"><CalendarClock className="w-4 h-4" />定时发布设置</h2>
          </div>
          <div className="vben-card-body grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">开始时间（北京时间）</label>
              <input
                type="datetime-local"
                className="input-ios w-full"
                value={startAt}
                onChange={e => setStartAt(e.target.value)}
              />
              <p className="text-xs text-slate-400 mt-1">到点后自动开始发布，每条按间隔依次执行</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">每条发布间隔（分钟）</label>
              <input
                type="number"
                className="input-ios w-full"
                min={MIN_INTERVAL_MINUTES}
                step={0.5}
                value={intervalMinutes}
                onChange={e => setIntervalMinutes(Math.max(MIN_INTERVAL_MINUTES, Number(e.target.value) || MIN_INTERVAL_MINUTES))}
              />
              <p className="text-xs text-slate-400 mt-1">
                {intervalMinutes < RISK_WARNING_MINUTES
                  ? <span className="text-amber-500">⚠ 间隔较短，频繁发布可能触发平台风控，请谨慎设置。</span>
                  : '最低 30 秒（调度器每 30 秒扫描一轮），默认 5 分钟防平台风控。'}
                {' '}共 {total} 次发布，预计耗时约 {Math.max(1, Math.round((total - 1) * intervalMinutes))} 分钟
              </p>
            </div>
          </div>
        </motion.div>
      )}

      {/* 提交按钮 */}
      <div className="flex justify-center">
        <button className="btn-ios-primary min-w-48" disabled={isDisabled} onClick={handleSubmit}>
          {submitting
            ? <><Loader2 className="w-4 h-4 animate-spin" />提交中...</>
            : publishMode === 'scheduled'
              ? <><Timer className="w-4 h-4" />创建定时发布（{total} 次）</>
              : <><Play className="w-4 h-4" />开始批量发布（{total} 次）</>}
        </button>
      </div>

      {/* 进度面板 */}
      {progress && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title"><Layers className="w-4 h-4" />发布进度</h2>
            {progress.finished
              ? <span className="badge-success">已完成</span>
              : <Loader2 className="w-4 h-4 animate-spin text-blue-500" />}
          </div>
          <div className="vben-card-body">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              {[
                { label: '总数', value: progress.total, icon: <Layers className="w-5 h-5" />, cls: 'stat-icon-primary' },
                { label: '成功', value: progress.success, icon: <CheckCircle className="w-5 h-5" />, cls: 'stat-icon-success' },
                { label: '失败', value: progress.failed, icon: <XCircle className="w-5 h-5" />, cls: 'stat-icon-warning' },
                { label: '进行中', value: progress.publishing + progress.pending, icon: <Clock className="w-5 h-5" />, cls: 'stat-icon-info' },
              ].map(item => (
                <div key={item.label} className="stat-card">
                  <div className={item.cls}>{item.icon}</div>
                  <div>
                    <div className="stat-value">{item.value}</div>
                    <div className="stat-label">{item.label}</div>
                  </div>
                </div>
              ))}
            </div>
            {progress.total > 0 && (
              <>
                <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 mb-1">
                  <div className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round((progress.success + progress.failed) / progress.total * 100)}%` }} />
                </div>
                <div className="flex justify-between text-xs text-slate-400">
                  <span>进度 {Math.round((progress.success + progress.failed) / progress.total * 100)}%</span>
                  <span>批次 ID：{progress.batch_id.slice(0, 8)}...</span>
                </div>
              </>
            )}
            {!progress.finished && <p className="text-xs text-slate-400 mt-2">每 3 秒自动刷新进度</p>}
            {progress.account_statuses.length > 0 && (
              <div className="mt-4 border-t border-slate-200 dark:border-slate-700 pt-4">
                <div className="flex items-center justify-between gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">账号自动获取商品状态</h3>
                  <span className="text-xs text-slate-400">按账号展示发布后商品同步结果</span>
                </div>
                <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                  {progress.account_statuses.map(accountStatus => (
                    <div key={accountStatus.account_id} className="rounded-xl border border-slate-200 dark:border-slate-700 p-3 bg-slate-50/80 dark:bg-slate-800/60">
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">
                            {accountNameMap.get(accountStatus.account_id) || accountStatus.account_id}
                          </div>
                          <div className="text-xs text-slate-400 truncate">账号ID：{accountStatus.account_id}</div>
                        </div>
                        <span className={getSyncStatusClassName(accountStatus.sync_status)}>{getSyncStatusLabel(accountStatus.sync_status)}</span>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3 text-xs">
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">发布总数</div>
                          <div className="mt-1 font-semibold text-slate-700 dark:text-slate-100">{accountStatus.total}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">发布成功</div>
                          <div className="mt-1 font-semibold text-emerald-600">{accountStatus.success}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">发布失败</div>
                          <div className="mt-1 font-semibold text-amber-600">{accountStatus.failed}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">待处理</div>
                          <div className="mt-1 font-semibold text-blue-600">{accountStatus.publishing + accountStatus.pending}</div>
                        </div>
                      </div>
                      <div className="mt-3 text-xs text-slate-500 dark:text-slate-300 break-all">{accountStatus.sync_message}</div>
                      {(accountStatus.sync_status === 'success' || accountStatus.sync_total_count > 0 || accountStatus.sync_saved_count > 0) && (
                        <div className="mt-2 text-xs text-slate-500 dark:text-slate-300">
                          已抓取 {accountStatus.sync_total_count} 件，入库 {accountStatus.sync_saved_count} 件
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}
      {/* 定时任务列表 */}
      {scheduledTasks.length > 0 && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title"><CalendarClock className="w-4 h-4" />定时发布任务</h2>
            <span className="text-xs text-slate-400">有待执行任务时每 10 秒自动刷新</span>
          </div>
          <div className="vben-card-body space-y-3">
            {scheduledTasks.map(task => {
              const done = task.success_count + task.failed_count
              const percent = task.total_count > 0 ? Math.round(done / task.total_count * 100) : 0
              const canCancel = task.status === 'pending' || task.status === 'running'
              return (
                <div key={task.id} className="rounded-xl border border-slate-200 dark:border-slate-700 p-3 bg-slate-50/80 dark:bg-slate-800/60">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-800 dark:text-slate-100">
                        任务 #{task.id} · {task.account_ids.length} 账号 × {task.material_ids.length} 素材
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5">
                        开始：{task.start_at ? task.start_at.replace('T', ' ').slice(0, 16) : '-'} ·
                        间隔 {Math.round(task.interval_seconds / 60)} 分钟 ·
                        进度 {done}/{task.total_count}（成功 {task.success_count} / 失败 {task.failed_count}）
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className={SCHEDULED_STATUS_CLASS[task.status]}>{SCHEDULED_STATUS_LABEL[task.status]}</span>
                      {canCancel && (
                        <button
                          className="text-xs text-red-500 hover:text-red-600 hover:underline flex items-center gap-1"
                          onClick={() => void handleCancelScheduled(task.id)}
                        >
                          <Ban className="w-3.5 h-3.5" />取消
                        </button>
                      )}
                    </div>
                  </div>
                  {task.total_count > 0 && (
                    <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5 mt-2">
                      <div className="bg-blue-500 h-1.5 rounded-full transition-all duration-500" style={{ width: `${percent}%` }} />
                    </div>
                  )}
                  {task.last_error && (
                    <div className="mt-2 text-xs text-amber-600 dark:text-amber-400 break-all">最近错误：{task.last_error}</div>
                  )}
                </div>
              )
            })}
          </div>
        </motion.div>
      )}
      <ContentRiskModal
        isOpen={Boolean(pendingRisk)}
        risk={pendingRisk}
        materialRisks={pendingMaterialRisks}
        onCancel={() => { setPendingRisk(null); setPendingMaterialRisks([]) }}
        onForcePublish={() => {
          forcePublishRef.current = true
          setPendingRisk(null)
          setPendingMaterialRisks([])
          void handleSubmit()
        }}
      />
    </div>
  )
}

export default BatchPublish
