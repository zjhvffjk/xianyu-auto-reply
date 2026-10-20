/**
 * 添加商品弹窗（店铺管理 - 宝贝设置）
 *
 * 功能：
 * 1. 列出当前店铺已同步的商品（来自商品目录），勾选后进入「单独设置」
 * 2. 支持粘贴闲鱼商品链接 / 商品ID：自动解析并匹配本地商品，匹配到则
 *    自动勾选；未匹配到提示先「从平台刷新」同步本店商品
 *
 * 说明：本系统发货配置直接绑定「商品↔卡券」，无需额外登记表；
 * 添加商品即从本店商品中选定要配置发货的对象。
 */
import { useMemo, useState } from 'react'
import { Link2, Search, Loader2, RefreshCw, CheckSquare, Square, X, AlertTriangle } from 'lucide-react'
import { parseShopItemId, toShopItemRow } from '@/utils/shopItem'
import type { Item } from '@/types'

interface AddShopItemModalProps {
  accountId: string
  /** 本店全部商品（父页面已加载） */
  items: Item[]
  onClose: () => void
  /** 确认配置：父页面打开第一个勾选商品的单独设置弹窗 */
  onConfigure: (item: Item) => void
  /** 从平台刷新（链接匹配不到商品时引导使用） */
  onSyncFromPlatform: () => void
}

export function AddShopItemModal({
  items,
  onClose,
  onConfigure,
  onSyncFromPlatform,
}: AddShopItemModalProps) {
  const [linkInput, setLinkInput] = useState('')
  const [linkError, setLinkError] = useState('')
  const [keyword, setKeyword] = useState('')
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const [syncing, setSyncing] = useState(false)

  const rows = useMemo(() => items.map(toShopItemRow), [items])

  const filteredRows = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    if (!kw) return rows
    return rows.filter((row) => row.title.toLowerCase().includes(kw) || row.itemId.includes(kw))
  }, [rows, keyword])

  /** 粘贴链接 → 解析商品ID → 匹配本地商品并勾选 */
  const handleParseLink = () => {
    setLinkError('')
    const itemId = parseShopItemId(linkInput)
    if (!itemId) {
      setLinkError('无法识别商品链接，请检查后重试（支持 goofish.com 商品链接或商品ID）')
      return
    }
    const matched = items.find((item) => String(item.item_id ?? '') === itemId)
    if (!matched) {
      setLinkError('本地未找到该商品，请先「从平台刷新」同步本店商品后再试')
      return
    }
    setCheckedIds((prev) => new Set(prev).add(itemId))
    setKeyword('')
    setLinkInput('')
    // 提示匹配成功（勾选态即反馈）
  }

  const toggle = (itemId: string) => {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(itemId)) next.delete(itemId)
      else next.add(itemId)
      return next
    })
  }

  const handleConfirm = () => {
    const firstId = Array.from(checkedIds)[0]
    const firstItem = items.find((item) => String(item.item_id ?? '') === firstId)
    if (firstItem) onConfigure(firstItem)
    else onClose()
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      await onSyncFromPlatform()
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 60 }}>
      <div className="modal-content max-w-2xl max-h-[85vh] overflow-hidden flex flex-col">
        <div className="modal-header flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-lg font-semibold">添加商品</h2>
            <p className="mt-1 text-sm text-gray-500">从本店商品中选择要设置发货的对象，或粘贴商品链接快速匹配</p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        <div className="flex-1 overflow-hidden flex flex-col p-4 space-y-3">
          {/* 粘贴商品链接 */}
          <div>
            <label className="input-label">商品链接 / 商品ID</label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Link2 className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={linkInput}
                  onChange={(e) => setLinkInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleParseLink()
                  }}
                  placeholder="粘贴闲鱼商品链接，如 https://www.goofish.com/item?id=123456"
                  className="input-ios pl-8"
                />
              </div>
              <button
                type="button"
                onClick={handleParseLink}
                disabled={!linkInput.trim()}
                className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
              >
                匹配
              </button>
            </div>
            {linkError && (
              <p className="mt-1.5 flex items-center gap-1 text-xs text-red-500">
                <AlertTriangle className="h-3.5 w-3.5" />
                {linkError}
              </p>
            )}
          </div>

          {/* 商品列表 */}
          <div className="flex-1 overflow-hidden flex flex-col rounded-md border border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2 border-b border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800">
              <Search className="h-4 w-4 text-gray-400" />
              <input
                type="text"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索本店商品"
                className="w-full bg-transparent text-sm focus:outline-none dark:text-slate-100"
              />
            </div>
            <div className="flex-1 overflow-y-auto" style={{ maxHeight: '40vh' }}>
              {filteredRows.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-gray-400">
                  {rows.length === 0 ? '本店暂无商品' : '没有匹配的商品'}
                </div>
              ) : (
                filteredRows.map((row) => {
                  const checked = checkedIds.has(row.itemId)
                  return (
                    <label
                      key={row.itemId}
                      className="flex cursor-pointer items-center gap-2.5 border-b border-gray-100 px-3 py-2 last:border-0 hover:bg-blue-50/50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                    >
                      <button
                        type="button"
                        onClick={() => toggle(row.itemId)}
                        className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border border-gray-300 text-blue-600 dark:border-gray-500"
                      >
                        {checked ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                      </button>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm text-slate-700 dark:text-slate-200">{row.title || row.itemId}</div>
                        <div className="text-xs text-gray-400">ID: {row.itemId}</div>
                      </div>
                      <div className="flex-shrink-0 text-xs text-gray-400">
                        {row.price ? `¥${row.price}` : ''}
                      </div>
                    </label>
                  )
                })
              )}
            </div>
          </div>
        </div>

        <div className="modal-footer flex items-center justify-between flex-shrink-0">
          <button
            type="button"
            onClick={handleSync}
            disabled={syncing}
            className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-blue-600 disabled:opacity-50"
          >
            {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            从平台刷新商品
          </button>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">已选 {checkedIds.size} 个</span>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:text-slate-300"
            >
              取消
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={checkedIds.size === 0}
              className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
            >
              去设置发货
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AddShopItemModal
