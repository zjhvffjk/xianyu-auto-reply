/**
 * 商品素材库页面
 *
 * 功能：
 * 1. 分页展示所有商品素材
 * 2. 新建/编辑/删除素材
 * 3. 筛选（标题、分类、成色）
 * 4. 勾选批量删除
 * 5. 素材用于单品发布和批量发布
 * 6. AI 铺货：批量生成素材（弹窗内配置与进度，进度由后端落库，刷新页面可恢复）
 */
import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Pencil, Trash2, RefreshCw, Image, ChevronLeft, ChevronRight, Search, Sparkles, X, Repeat2, Download, Tags } from 'lucide-react'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import {
  getMaterials,
  getMaterialCategories,
  deleteMaterial,
  batchDeleteMaterials,
  getMaterialSyncPreview,
  syncMaterialsFromItems,
  getMaterialCategoryBackfillPreview,
  backfillMaterialCategories,
  type ProductMaterial,
} from '@/api/productPublish'
import { getAccountDetails } from '@/api/accounts'
import { getAccountOptionLabel } from '@/utils/accountLabel'
import type { Account } from '@/types'
import { PageLoading } from '@/components/common/Loading'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { MaterialFormModal } from './MaterialFormModal'
import { AiListingModal } from './ai-listing/AiListingModal'
import { AutoRelistModal } from './AutoRelistModal'
import { useAiListingTask } from './ai-listing/useAiListingTask'

const CONDITIONS = ['全新', '99新', '95新', '9成新', '8成新', '7成新以下']

function getPlatformSummary(material: ProductMaterial): string[] {
  return [
    material.platform_category_path?.length ? `路径：${material.platform_category_path.map(item => item.name).filter(Boolean).join(' / ')}` : '',
    material.platform_category_name && `分类：${material.platform_category_name}`,
    material.platform_channel_category_name && `频道：${material.platform_channel_category_name}`,
    material.platform_leaf_id && `叶子ID：${material.platform_leaf_id}`,
    material.platform_tb_category_id && `淘宝ID：${material.platform_tb_category_id}`,
  ].filter((value): value is string => Boolean(value))
}

export function ProductMaterials() {
  const { addToast } = useUIStore()
  const { user } = useAuthStore()
  const isAdmin = Boolean(user?.is_admin)
  const [loading, setLoading] = useState(true)
  const [tableLoading, setTableLoading] = useState(false)
  const [materials, setMaterials] = useState<ProductMaterial[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [totalPages, setTotalPages] = useState(0)
  const [showModal, setShowModal] = useState(false)
  const [editTarget, setEditTarget] = useState<ProductMaterial | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; item: ProductMaterial | null }>({ open: false, item: null })
  const [deleting, setDeleting] = useState(false)

  // 筛选状态
  const [filterTitle, setFilterTitle] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterCondition, setFilterCondition] = useState('')
  const [filterPlatformCategoryId, setFilterPlatformCategoryId] = useState('')

  // 本地分类下拉选项：来自素材库里实际存在的分类名
  const [categoryOptions, setCategoryOptions] = useState<string[]>([])

  // 批量选择状态
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)

  // AI 铺货
  const [showAiModal, setShowAiModal] = useState(false)
  const [relistTarget, setRelistTarget] = useState<ProductMaterial | null>(null)

  // 从商品库同步素材
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState({ done: 0, total: 0 })
  // 账号筛选：null = 所有账号；选中后素材列表只看该账号，且「从商品同步」也只补该账号的缺口
  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountPk, setAccountPk] = useState<number | null>(null)

  // 补全素材平台类目（缺 channelCatId 会被闲鱼拒绝发布）
  const [backfilling, setBackfilling] = useState(false)
  const [backfillProgress, setBackfillProgress] = useState({ done: 0, total: 0 })

  /** 加载素材列表 */
  const load = async (p = page, size = pageSize) => {
    setTableLoading(true)
    try {
      const filters: { title?: string; category?: string; condition?: string; platform_category_id?: string; account_pk?: number } = {}
      if (filterTitle.trim()) filters.title = filterTitle.trim()
      if (filterCategory) filters.category = filterCategory
      if (filterCondition) filters.condition = filterCondition
      if (filterPlatformCategoryId.trim()) filters.platform_category_id = filterPlatformCategoryId.trim()
      if (accountPk != null) filters.account_pk = accountPk
      const res = await getMaterials(p, size, Object.keys(filters).length > 0 ? filters : undefined)
      if (res.success) {
        setMaterials(res.data.list)
        setTotal(res.data.total)
        setTotalPages(res.data.total_pages)
        // 清除不在当前页的选中项
        const currentIds = new Set(res.data.list.map(m => m.id))
        setSelectedIds(prev => prev.filter(id => currentIds.has(id)))
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

  // accountPk 变化时也要重新拉列表（切账号等于换了一套筛选，回到第 1 页）
  useEffect(() => { load(page, pageSize) }, [page, pageSize, accountPk])

  /** 加载「本地分类」下拉选项 */
  const loadCategories = async () => {
    try {
      const res = await getMaterialCategories()
      if (res.success) setCategoryOptions(res.data?.categories || [])
    } catch {
      // 下拉选项加载失败不影响筛选，静默忽略
    }
  }

  /** 素材数据可能变化后：刷新列表 + 刷新分类选项 */
  const reloadAll = async (p = page, size = pageSize) => {
    await load(p, size)
    loadCategories()
  }

  useEffect(() => { loadCategories() }, [])

  /** 加载账号列表（供「从商品同步」选择范围；口径同商品管理页） */
  useEffect(() => {
    getAccountDetails()
      .then(data => setAccounts(data || []))
      .catch(() => {
        // 账号列表拉不到不影响页面其他功能，只是同步范围退化用「所有账号」
      })
  }, [])

  // AI 铺货任务进度（轮询放在页面级，关闭弹窗后按钮徽章仍会更新）
  const aiTask = useAiListingTask({
    onFinished: (task) => {
      addToast({
        type: task.failed === 0 && task.success > 0 ? 'success' : 'warning',
        message: `AI 铺货结束：成功 ${task.success} 条，失败 ${task.failed} 条`,
      })
      reloadAll(page, pageSize)
    },
  })

  // 进入页面时恢复上次未结束的铺货任务
  useEffect(() => { void aiTask.restoreTracking() }, [aiTask.restoreTracking])

  const aiRunning = Boolean(aiTask.task && !aiTask.task.finished)

  /**
   * 从商品库同步素材：把账号在售、但素材库里还没有的商品补进来。
   * 选了账号就只同步该账号的缺口；后端按 limit 分批处理（每条都要调闲鱼详情接口取真实描述），
   * 这里循环调用直到补完（remaining 与所选账号同范围，归零即停）。
   */
  const handleSyncFromItems = async () => {
    if (syncing) return
    setSyncing(true)
    try {
      const preview = await getMaterialSyncPreview(accountPk ?? undefined)
      if (!preview.success) {
        addToast({ type: 'error', message: preview.message || '查询待同步数量失败' })
        return
      }
      const missing = preview.data?.missing ?? 0
      if (missing <= 0) {
        addToast({ type: 'success', message: '商品库与素材库已一致，无需同步' })
        return
      }

      setSyncProgress({ done: 0, total: missing })
      let created = 0
      let failed = 0
      let remaining = missing

      // 上限 200 轮，避免异常情况下无限循环
      for (let round = 0; round < 200; round++) {
        const res = await syncMaterialsFromItems(undefined, accountPk ?? undefined)
        if (!res.success) {
          addToast({ type: 'error', message: res.message || '同步失败' })
          break
        }
        const data = res.data
        if (!data) {
          addToast({ type: 'error', message: '同步返回数据异常，已停止' })
          break
        }
        created += data.created
        failed += data.failed
        remaining = data.remaining
        setSyncProgress({ done: Math.max(missing - remaining, 0), total: missing })

        if (data.aborted) {
          addToast({ type: 'warning', message: '检测到账号风控信号，已停止同步，稍后可再试' })
          break
        }
        if (remaining <= 0) break
        // 本批毫无进展（既不新增也不失败）说明剩余条目无法自动处理，停止避免空转
        if (data.created === 0 && data.failed === 0) {
          addToast({
            type: 'warning',
            message: `还有 ${remaining} 条商品无法自动同步（多为缺少图片或账号详情不可用）`,
          })
          break
        }
      }

      addToast({
        type: failed > 0 || remaining > 0 ? 'warning' : 'success',
        message: `同步完成：新增 ${created} 条素材${failed > 0 ? `，失败 ${failed} 条` : ''}${remaining > 0 ? `，剩余 ${remaining} 条` : ''}`,
      })
      setPage(1)
      setSelectedIds([])
      await reloadAll(1, pageSize)
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    } finally {
      setSyncing(false)
    }
  }

  /**
   * 补全素材平台类目：素材缺 channelCatId 时闲鱼发布会报
   * FAIL_BIZ_CHANNEL_CAT_ID_PATH_QUERY_ERROR，这里按已有的末级分类ID反查补上。
   * 后端按 limit 分批处理，这里循环调用直到补完。
   */
  const handleBackfillCategories = async () => {
    if (backfilling) return
    setBackfilling(true)
    try {
      const preview = await getMaterialCategoryBackfillPreview()
      if (!preview.success) {
        addToast({ type: 'error', message: preview.message || '查询待补类目数量失败' })
        return
      }
      const missing = preview.data?.missing ?? 0
      if (missing <= 0) {
        addToast({ type: 'success', message: '所有素材的类目都已完整，无需补全' })
        return
      }

      setBackfillProgress({ done: 0, total: missing })
      let updated = 0
      let failed = 0
      let remaining = missing

      // 上限 300 轮，避免异常情况下无限循环
      for (let round = 0; round < 300; round++) {
        const res = await backfillMaterialCategories()
        if (!res.success) {
          addToast({ type: 'error', message: res.message || '补全类目失败' })
          break
        }
        const data = res.data
        if (!data) {
          addToast({ type: 'error', message: '补全返回数据异常，已停止' })
          break
        }
        updated += data.updated
        failed += data.failed
        remaining = data.remaining
        setBackfillProgress({ done: Math.max(missing - remaining, 0), total: missing })

        if (remaining <= 0) break
        // 本批毫无进展说明剩余条目无法自动补全，停止避免空转
        if (data.updated === 0) {
          addToast({
            type: 'warning',
            message: `还有 ${remaining} 条素材无法自动补全类目，请在素材编辑里手动重新选择分类`,
          })
          break
        }
      }

      addToast({
        type: failed > 0 || remaining > 0 ? 'warning' : 'success',
        message: `类目补全完成：成功 ${updated} 条${failed > 0 ? `，失败 ${failed} 条` : ''}${remaining > 0 ? `，剩余 ${remaining} 条` : ''}`,
      })
      await reloadAll(page, pageSize)
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    } finally {
      setBackfilling(false)
    }
  }

  /** 执行筛选 */
  const handleFilter = () => {
    setPage(1)
    setSelectedIds([])
    load(1, pageSize)
  }

  /** 重置筛选 */
  const handleResetFilter = () => {
    setFilterTitle('')
    setFilterCategory('')
    setFilterCondition('')
    setFilterPlatformCategoryId('')
    setAccountPk(null)
    setPage(1)
    setSelectedIds([])
    // 直接用空筛选加载
    setTableLoading(true)
    getMaterials(1, pageSize).then(res => {
      if (res.success) {
        setMaterials(res.data.list)
        setTotal(res.data.total)
        setTotalPages(res.data.total_pages)
        setSelectedIds([])
      }
    }).catch(() => {
      addToast({ type: 'error', message: '加载失败' })
    }).finally(() => {
      setLoading(false)
      setTableLoading(false)
    })
  }

  /** 确认删除单条 */
  const handleConfirmDelete = async () => {
    if (!deleteConfirm.item) return
    setDeleting(true)
    try {
      const res = await deleteMaterial(deleteConfirm.item.id)
      if (res.success) {
        addToast({ type: 'success', message: '素材已移出素材库' })
        setDeleteConfirm({ open: false, item: null })
        setSelectedIds(prev => prev.filter(id => id !== deleteConfirm.item!.id))
        reloadAll(page, pageSize)
      } else {
        addToast({ type: 'error', message: res.message || '删除失败' })
      }
    } catch {
      addToast({ type: 'error', message: '删除失败，请重试' })
    } finally {
      setDeleting(false)
    }
  }

  /** 批量删除 */
  const handleBatchDelete = async () => {
    if (selectedIds.length === 0) return
    setBatchDeleting(true)
    try {
      const res = await batchDeleteMaterials(selectedIds)
      if (res.success) {
        addToast({ type: 'success', message: res.message || `已移出 ${selectedIds.length} 条素材` })
        setBatchDeleteConfirm(false)
        setSelectedIds([])
        reloadAll(page, pageSize)
      } else {
        addToast({ type: 'error', message: res.message || '批量删除失败' })
      }
    } catch {
      addToast({ type: 'error', message: '批量删除失败，请重试' })
    } finally {
      setBatchDeleting(false)
    }
  }

  /** 全选/取消全选当前页 */
  const handleSelectAll = () => {
    if (materials.length === 0) return
    const currentPageIds = materials.map(m => m.id)
    const allSelected = currentPageIds.every(id => selectedIds.includes(id))
    if (allSelected) {
      setSelectedIds(prev => prev.filter(id => !currentPageIds.includes(id)))
    } else {
      setSelectedIds(prev => [...new Set([...prev, ...currentPageIds])])
    }
  }

  /** 切换单条选中 */
  const toggleSelect = (id: number) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    )
  }

  const allCurrentSelected = materials.length > 0 && materials.every(m => selectedIds.includes(m.id))

  const handlePageSizeChange = (size: number) => { setPageSize(size); setPage(1) }

  // 保底：若当前选中的分类已不在素材库里，也保留在选项中，避免下拉显示空白
  const categorySelectOptions =
    filterCategory && !categoryOptions.includes(filterCategory)
      ? [filterCategory, ...categoryOptions]
      : categoryOptions

  if (loading) return <PageLoading />

  return (
    <div className="space-y-3 sm:space-y-4">
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="page-title">商品素材库</h1>
          <p className="page-description">管理商品素材，用于单品发布和批量发布</p>
        </div>
        <div className="flex gap-2">
          {selectedIds.length > 0 && (
            <button className="btn-ios-danger" onClick={() => setBatchDeleteConfirm(true)}>
              <Trash2 className="w-4 h-4" />批量删除 ({selectedIds.length})
            </button>
          )}
          <button className="btn-ios-secondary" onClick={() => reloadAll(page, pageSize)} disabled={tableLoading}>
            <RefreshCw className={`w-4 h-4 ${tableLoading ? 'animate-spin' : ''}`} />刷新
          </button>
          <select
            className="input-ios w-40 self-center"
            value={accountPk == null ? '' : String(accountPk)}
            onChange={e => {
              const pk = e.target.value ? Number(e.target.value) : null
              setAccountPk(pk)
              // 选中即生效：回到第 1 页重新拉列表，同时清掉跨页选中
              setPage(1)
              setSelectedIds([])
              load(1, pageSize)
            }}
            title="筛选账号：只看该账号同步来的素材，「从商品同步」也只补该账号的缺口；「所有账号」= 看全部（含手动新建）"
            disabled={syncing || tableLoading}
          >
            <option value="">所有账号</option>
            {accounts.filter(a => a.pk != null).map(account => (
              <option key={account.pk} value={account.pk}>
                {getAccountOptionLabel(account)}
              </option>
            ))}
          </select>
          <button
            className="btn-ios-secondary"
            onClick={handleSyncFromItems}
            disabled={syncing || tableLoading}
            title={
              accountPk == null
                ? '把各账号在售、但素材库里还没有的商品补进来（已存在的不重建、不覆盖；删过的会恢复）'
                : '把该账号在售、但素材库里还没有的商品补进来（已存在的不重建、不覆盖；删过的会恢复）'
            }
          >
            <Download className="w-4 h-4" />
            {syncing ? `同步中 ${syncProgress.done}/${syncProgress.total}` : '从商品同步'}
          </button>
          <button
            className="btn-ios-secondary"
            onClick={handleBackfillCategories}
            disabled={backfilling || tableLoading}
            title="给缺少平台分类的素材补全类目（缺类目的素材发布时会被闲鱼拒绝）"
          >
            <Tags className="w-4 h-4" />
            {backfilling ? `补类目中 ${backfillProgress.done}/${backfillProgress.total}` : '补全类目'}
          </button>
          <button className="btn-ios-secondary" onClick={() => setShowAiModal(true)}>
            <Sparkles className="w-4 h-4" />AI 铺货
            {aiRunning && aiTask.task && (
              <span className="badge-info ml-1">
                生成中 {aiTask.task.success + aiTask.task.failed}/{aiTask.task.total}
              </span>
            )}
          </button>
          <button className="btn-ios-primary" onClick={() => { setEditTarget(null); setShowModal(true) }}>
            <Plus className="w-4 h-4" />新建素材
          </button>
        </div>
      </div>

      {/* 筛选栏 */}
      <div className="vben-card">
        <div className="vben-card-body py-3 px-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <input
                className="input-ios w-48"
                placeholder="搜索标题..."
                value={filterTitle}
                onChange={e => setFilterTitle(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleFilter()}
              />
            </div>
            <select
              className="input-ios w-40"
              value={filterCategory}
              onChange={e => { setFilterCategory(e.target.value); }}
              title="按素材分类筛选，选项来自素材库里已有的分类名"
            >
              <option value="">全部分类</option>
              {categorySelectOptions.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <input className="input-ios w-40" placeholder="平台分类ID..." value={filterPlatformCategoryId} onChange={e => setFilterPlatformCategoryId(e.target.value)} />
            <select
              className="input-ios w-28"
              value={filterCondition}
              onChange={e => { setFilterCondition(e.target.value); }}
            >
              <option value="">全部成色</option>
              {CONDITIONS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <button className="btn-ios-primary btn-sm" onClick={handleFilter}>
              <Search className="w-3.5 h-3.5" />查询
            </button>
            {(filterTitle || filterCategory || filterCondition || filterPlatformCategoryId) && (
              <button className="btn-ios-secondary btn-sm" onClick={handleResetFilter}>
                <X className="w-3.5 h-3.5" />重置
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 表格卡片 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
        className="vben-card flex flex-col"
        style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}
      >
        <div className="vben-card-header">
          <h2 className="vben-card-title"><Image className="w-4 h-4" />素材列表</h2>
          <span className="badge-primary">共 {total} 条</span>
        </div>
        <div className="table-scroll flex-1">
          <table className="table-ios">
            <thead className="sticky top-0 bg-white dark:bg-slate-800 z-10">
              <tr>
                <th className="w-10">
                  <input
                    type="checkbox"
                    checked={allCurrentSelected}
                    onChange={handleSelectAll}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                </th>
                {isAdmin && <th>所属用户</th>}
                <th>标题</th>
                <th>价格</th>
                <th>分类</th>
                <th>平台分类</th>
                <th>成色</th>
                <th>媒体</th>
                <th>创建时间</th>
                <th>自动续售</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {tableLoading ? (
                <tr><td colSpan={isAdmin ? 11 : 10} className="text-center py-12">
                  <RefreshCw className="w-6 h-6 animate-spin text-blue-500 mx-auto" />
                </td></tr>
              ) : materials.length === 0 ? (
                <tr><td colSpan={isAdmin ? 11 : 10} className="text-center py-12 text-slate-400">
                  <div className="flex flex-col items-center gap-2">
                    <Image className="w-12 h-12 text-slate-300" />
                    <p>暂无素材，点击「新建素材」添加</p>
                  </div>
                </td></tr>
              ) : materials.map(m => (
                <tr key={m.id} className={selectedIds.includes(m.id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(m.id)}
                      onChange={() => toggleSelect(m.id)}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                  </td>
                  {isAdmin && (
                    <td className="text-sm text-slate-600 dark:text-slate-400 whitespace-nowrap">
                      {m.username || '-'}
                    </td>
                  )}
                  <td className="max-w-[200px]">
                    <span className="truncate block font-medium text-slate-800 dark:text-slate-100" title={m.title}>{m.title}</span>
                  </td>
                  <td>
                    <span className="text-amber-600 font-medium">{m.price}</span>
                    {m.original_price && (
                      <span className="text-xs text-slate-400 line-through ml-1">{m.original_price}</span>
                    )}
                  </td>
                  <td className="text-slate-500">{m.category || '-'}</td>
                  <td className="max-w-[180px]">
                    {getPlatformSummary(m).length > 0 ? getPlatformSummary(m).map((item) => <span key={item} className="block truncate text-slate-700 dark:text-slate-200" title={item}>{item}</span>) : <span className="text-slate-400">-</span>}
                    {m.platform_category_id && <span className="block text-xs text-slate-400 truncate" title={m.platform_category_id}>分类ID：{m.platform_category_id}</span>}
                  </td>
                  <td><span className="badge-gray">{m.condition}</span></td>
                  <td><span className="badge-info">{(m.images || []).length} 图 / {(m.videos || []).length} 视频</span></td>
                  <td className="text-sm text-slate-500 whitespace-nowrap">
                    {m.created_at ? new Date(m.created_at).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'}
                  </td>
                  <td>
                    <div className="flex items-center gap-1">
                      <span className={`badge-${m.auto_relist?.status === 'active' ? 'success' : m.auto_relist ? 'warning' : 'gray'}`}>
                        {m.auto_relist ? (m.auto_relist.status_text || m.auto_relist.status) : '未配置'}
                      </span>
                    </div>
                  </td>
                  <td>
                    <div className="table-actions">
                      <button className="table-action-btn" title={m.auto_relist_can_configure === false ? '管理员只读，查看自动续售' : '自动续售'}
                        onClick={() => setRelistTarget(m)}>
                        <Repeat2 className={`w-4 h-4 ${m.auto_relist_can_configure === false ? 'text-slate-300' : 'text-emerald-500'}`} />
                      </button>
                      <button className="table-action-btn" title="编辑"
                        onClick={() => { setEditTarget(m); setShowModal(true) }}>
                        <Pencil className="w-4 h-4 text-blue-500" />
                      </button>
                      <button className="table-action-btn" title="删除"
                        onClick={() => setDeleteConfirm({ open: true, item: m })}>
                        <Trash2 className="w-4 h-4 text-red-500" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
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

      {/* 新建/编辑弹窗 */}
      {showModal && (
        <MaterialFormModal
          initial={editTarget}
          onClose={() => setShowModal(false)}
          onSaved={() => { setShowModal(false); reloadAll(page, pageSize) }}
        />
      )}

      {/* AI 铺货弹窗 */}
      {showAiModal && (
        <AiListingModal
          task={aiTask.task}
          onStartTracking={aiTask.startTracking}
          onResetTask={aiTask.resetTask}
          onClose={() => setShowAiModal(false)}
        />
      )}

      {relistTarget && (
        <AutoRelistModal
          material={relistTarget}
          onClose={() => setRelistTarget(null)}
          onSaved={() => { setRelistTarget(null); load(page, pageSize) }}
        />
      )}

      {/* 删除确认弹窗 */}
      <ConfirmModal
        isOpen={deleteConfirm.open}
        title="确认删除"
        message={`确认将素材「${deleteConfirm.item?.title ?? ''}」移出素材库吗？历史发布日志不会受影响。`}
        confirmText="移出素材库"
        type="danger"
        loading={deleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteConfirm({ open: false, item: null })}
      />

      {/* 批量删除确认弹窗 */}
      <ConfirmModal
        isOpen={batchDeleteConfirm}
        title="确认批量移出"
        message={`确认将选中的 ${selectedIds.length} 条素材移出素材库吗？历史发布日志不会受影响。`}
        confirmText={`移出 ${selectedIds.length} 条`}
        type="danger"
        loading={batchDeleting}
        onConfirm={handleBatchDelete}
        onCancel={() => setBatchDeleteConfirm(false)}
      />
    </div>
  )
}

export default ProductMaterials
