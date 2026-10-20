/**
 * 宝贝设置页（店铺管理 - 发货设置）
 *
 * 功能：
 * 1. 展示当前店铺的全部商品（来自商品目录，平台同步），支持 tab 过滤：
 *    全部 / 已设置（有卡券或使用说明）/ 未设置
 * 2. 关键字搜索、客户端分页（店铺维度商品量可控，一次拉全量后本地过滤）
 * 3. 「添加商品」：弹窗勾选本店商品快速进入配置；支持粘贴闲鱼商品链接匹配
 * 4. 「单独设置」：弹窗两页签——发货内容（关联卡券）+ 使用说明（默认回复）
 * 5. 批量操作：批量设置使用说明 / 批量关联卡券 / 批量改价 / 取消发货关联
 * 6. 「从平台刷新」：拉取闲鱼最新商品列表（整店同步）
 *
 * 数据：商品 GET /api/v1/items/cookie/{id}（后端带 owner 校验）；
 *       卡券关联 / 默认回复 / 改价全部复用商品管理现有接口。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Plus, RefreshCw, Loader2, Search, Package, Ticket, MessageSquare, Tag,
  ExternalLink, Unlink, Settings2, CheckSquare, Square, X,
} from 'lucide-react'
import { getItems, fetchAllItemsFromAccount, type FetchItemsSummaryResponse } from '@/api/items'
import { batchClearItemRelations } from '@/api/cards'
import { Pager } from '@/components/common/Pager'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { AddShopItemModal } from './AddShopItemModal'
import { ShopItemSettingModal } from './ShopItemSettingModal'
import { ShopBatchModals, type ShopBatchModalsProps } from './ShopBatchModals'
import { matchShopItemTab, toShopItemRow, type ShopItemTab } from '@/utils/shopItem'
import { useUIStore } from '@/store/uiStore'
import type { Item } from '@/types'

type BatchKind = 'reply' | 'card' | 'price' | null

const TAB_LABELS: Array<{ key: ShopItemTab; label: string }> = [
  { key: 'all', label: '全部' },
  { key: 'configured', label: '已设置' },
  { key: 'unconfigured', label: '未设置' },
]

const PAGE_SIZE = 20

export function ShopItemSettings({ accountId, accountLabel }: { accountId: string; accountLabel: string }) {
  const { addToast } = useUIStore()

  // 商品列表（全量拉取后本地过滤）
  const [allItems, setAllItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [tab, setTab] = useState<ShopItemTab>('all')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)

  // 勾选与弹窗状态
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [settingItem, setSettingItem] = useState<Item | null>(null)
  const [batchKind, setBatchKind] = useState<BatchKind>(null)
  const [clearRelationsConfirm, setClearRelationsConfirm] = useState(false)

  /** 加载店铺商品 */
  const loadItems = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getItems(accountId)
      setAllItems(Array.isArray(res.data) ? res.data : [])
    } catch {
      addToast({ type: 'error', message: '商品列表加载失败' })
    } finally {
      setLoading(false)
    }
  }, [accountId, addToast])

  useEffect(() => {
    loadItems()
  }, [loadItems])

  // tab / 搜索 / 店铺切换时回到第一页
  useEffect(() => {
    setPage(1)
  }, [tab, keyword, accountId])

  // 行数据 + 过滤 + 分页
  const rows = useMemo(() => allItems.map(toShopItemRow), [allItems])
  const filteredRows = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return rows.filter((row) => {
      if (!matchShopItemTab(row, tab)) return false
      if (!kw) return true
      return (
        row.title.toLowerCase().includes(kw) ||
        row.itemId.includes(kw)
      )
    })
  }, [rows, tab, keyword])

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pageRows = filteredRows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  const tabCounts = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    const base = kw
      ? rows.filter((row) => row.title.toLowerCase().includes(kw) || row.itemId.includes(kw))
      : rows
    return {
      all: base.length,
      configured: base.filter((row) => matchShopItemTab(row, 'configured')).length,
      unconfigured: base.filter((row) => matchShopItemTab(row, 'unconfigured')).length,
    }
  }, [rows, keyword])

  // 当前页全选态（仅操作当前页，跨页选择保留在 selectedIds 中）
  const pageAllSelected = pageRows.length > 0 && pageRows.every((row) => selectedIds.has(row.itemId))
  const toggleSelectAllOnPage = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (pageAllSelected) {
        pageRows.forEach((row) => next.delete(row.itemId))
      } else {
        pageRows.forEach((row) => next.add(row.itemId))
      }
      return next
    })
  }
  const toggleRow = (itemId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  const selectedItems = useMemo(
    () => allItems.filter((item) => selectedIds.has(String(item.item_id ?? ''))),
    [allItems, selectedIds]
  )
  const sellerSelectedCount = selectedItems.filter((item) => item.is_seller_item).length

  /** 从平台刷新本店商品 */
  const handleSyncFromPlatform = async () => {
    setSyncing(true)
    try {
      const res = await fetchAllItemsFromAccount(accountId) as FetchItemsSummaryResponse
      if (res.success) {
        addToast({ type: 'success', message: res.message || `已同步 ${res.saved_count ?? 0} 个商品` })
        await loadItems()
      } else {
        addToast({ type: 'error', message: res.message || '同步失败' })
      }
    } catch {
      addToast({ type: 'error', message: '同步失败' })
    } finally {
      setSyncing(false)
    }
  }

  const batchModalProps: Omit<ShopBatchModalsProps, 'sellerSelectedCount'> = {
    accountId,
    selectedItems,
    open: batchKind,
    onClose: () => setBatchKind(null),
    onSuccess: async () => {
      setBatchKind(null)
      setSelectedIds(new Set())
      await loadItems()
    },
  }

  return (
    <div className="space-y-4">
      {/* 头部：店铺名 + 操作 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-medium text-slate-800 dark:text-slate-100">
            宝贝设置 · {accountLabel}
          </h2>
          <p className="mt-0.5 text-xs text-slate-400">
            为每个商品单独设置发货内容（关联卡券）与使用说明，来单即自动发货
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAddModalOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            添加商品
          </button>
          <button
            type="button"
            onClick={handleSyncFromPlatform}
            disabled={syncing}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-600 transition-colors hover:border-blue-400 hover:text-blue-600 disabled:opacity-50 dark:border-slate-600 dark:text-slate-300"
          >
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            从平台刷新
          </button>
        </div>
      </div>

      {/* tab + 搜索 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex border-b border-slate-200 dark:border-slate-700">
          {TAB_LABELS.map((item) => (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === item.key
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {item.label}
              <span className="ml-1 text-xs text-slate-400">{tabCounts[item.key]}</span>
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索商品标题 / 商品ID"
            className="h-9 w-64 rounded-md border border-slate-300 pl-8 pr-3 text-sm focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-700 dark:text-slate-100"
          />
        </div>
      </div>

      {/* 批量操作栏 */}
      {selectedIds.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm dark:border-blue-800 dark:bg-blue-900/20">
          <span className="text-blue-700 dark:text-blue-300">已选 {selectedIds.size} 个商品</span>
          <button
            type="button"
            onClick={() => setBatchKind('reply')}
            className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:text-blue-600 dark:bg-slate-700 dark:text-slate-200"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            批量使用说明
          </button>
          <button
            type="button"
            onClick={() => setBatchKind('card')}
            className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:text-blue-600 dark:bg-slate-700 dark:text-slate-200"
          >
            <Ticket className="h-3.5 w-3.5" />
            批量关联卡券
          </button>
          <button
            type="button"
            onClick={() => setBatchKind('price')}
            className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:text-blue-600 dark:bg-slate-700 dark:text-slate-200"
          >
            <Tag className="h-3.5 w-3.5" />
            批量改价
          </button>
          <button
            type="button"
            onClick={() => setClearRelationsConfirm(true)}
            className="inline-flex items-center gap-1 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm hover:text-red-600 dark:bg-slate-700 dark:text-slate-200"
          >
            <Unlink className="h-3.5 w-3.5" />
            取消发货关联
          </button>
          <button
            type="button"
            onClick={() => setSelectedIds(new Set())}
            className="ml-auto inline-flex items-center gap-1 px-2 py-1 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          >
            <X className="h-3.5 w-3.5" />
            取消选择
          </button>
        </div>
      )}

      {/* 商品表格 */}
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
        {loading ? (
          <div className="flex h-48 items-center justify-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载商品...
          </div>
        ) : filteredRows.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-2 text-sm text-slate-400">
            <Package className="h-8 w-8 text-slate-300" />
            {rows.length === 0
              ? '本店暂无商品，点「从平台刷新」同步闲鱼在售商品'
              : '当前筛选条件下没有商品'}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900/50">
                <th className="w-10 px-3 py-2.5">
                  <button
                    type="button"
                    onClick={toggleSelectAllOnPage}
                    className="flex h-4 w-4 items-center justify-center rounded border border-slate-300 text-blue-600 dark:border-slate-500"
                    title={pageAllSelected ? '取消本页全选' : '本页全选'}
                  >
                    {pageAllSelected ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                  </button>
                </th>
                <th className="px-3 py-2.5 text-left">商品</th>
                <th className="w-20 px-3 py-2.5 text-left">价格</th>
                <th className="w-24 px-3 py-2.5 text-left">状态</th>
                <th className="w-40 px-3 py-2.5 text-left">发货设置</th>
                <th className="w-24 px-3 py-2.5 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row) => (
                <tr
                  key={`${row.itemId}`}
                  className="border-b border-slate-100 last:border-0 hover:bg-slate-50/60 dark:border-slate-700/50 dark:hover:bg-slate-700/30"
                >
                  <td className="px-3 py-2.5">
                    <button
                      type="button"
                      onClick={() => toggleRow(row.itemId)}
                      className="flex h-4 w-4 items-center justify-center rounded border border-slate-300 text-blue-600 dark:border-slate-500"
                    >
                      {selectedIds.has(row.itemId) ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                    </button>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="max-w-[22rem] truncate font-medium text-slate-700 dark:text-slate-200" title={row.title}>
                        {row.title || row.itemId}
                      </span>
                      <a
                        href={`https://www.goofish.com/item?id=${row.itemId}`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-slate-300 hover:text-blue-500"
                        title="查看商品链接"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-400">ID: {row.itemId}</div>
                  </td>
                  <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300">
                    {row.price ? `¥${row.price}` : '-'}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {row.statusDesc || '在售'}
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${
                          row.hasCard
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500'
                        }`}
                      >
                        卡券{row.hasCard ? '已关联' : '未关联'}
                      </span>
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${
                          row.hasDefaultReply
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                            : 'bg-slate-100 text-slate-400 dark:bg-slate-700 dark:text-slate-500'
                        }`}
                      >
                        使用说明{row.hasDefaultReply ? '已设置' : '未设置'}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <button
                      type="button"
                      onClick={() => setSettingItem(allItems.find((item) => String(item.item_id ?? '') === row.itemId) || null)}
                      className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-2 py-1 text-xs font-medium text-slate-600 transition-colors hover:border-blue-400 hover:text-blue-600 dark:border-slate-600 dark:text-slate-300"
                    >
                      <Settings2 className="h-3.5 w-3.5" />
                      单独设置
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 分页 */}
      {!loading && filteredRows.length > 0 && (
        <Pager
          page={safePage}
          pageSize={PAGE_SIZE}
          total={filteredRows.length}
          loading={loading}
          onPageChange={setPage}
        />
      )}

      {/* 添加商品弹窗 */}
      {addModalOpen && (
        <AddShopItemModal
          accountId={accountId}
          items={allItems}
          onClose={() => setAddModalOpen(false)}
          onConfigure={(item) => {
            setAddModalOpen(false)
            setSettingItem(item)
          }}
          onSyncFromPlatform={handleSyncFromPlatform}
        />
      )}

      {/* 单独设置弹窗 */}
      {settingItem && (
        <ShopItemSettingModal
          cookieId={accountId}
          item={settingItem}
          onClose={() => setSettingItem(null)}
          onSaved={loadItems}
        />
      )}

      {/* 批量操作弹窗组 */}
      {batchKind && (
        <ShopBatchModals
          {...batchModalProps}
          sellerSelectedCount={sellerSelectedCount}
        />
      )}

      {/* 取消发货关联确认 */}
      <ConfirmModal
        isOpen={clearRelationsConfirm}
        title="取消发货关联"
        message={`将清空所选 ${selectedIds.size} 个商品的卡券关联（不删除卡券本身），来单后将不再自动发送卡券。确定继续？`}
        confirmText="确定清空"
        cancelText="取消"
        onConfirm={async () => {
          setClearRelationsConfirm(false)
          try {
            const res = await batchClearItemRelations(Array.from(selectedIds))
            if (res.success) {
              addToast({ type: 'success', message: res.message || '已清空关联' })
              setSelectedIds(new Set())
              await loadItems()
            } else {
              addToast({ type: 'error', message: res.message || '操作失败' })
            }
          } catch {
            addToast({ type: 'error', message: '操作失败' })
          }
        }}
        onCancel={() => setClearRelationsConfirm(false)}
      />
    </div>
  )
}

export default ShopItemSettings
