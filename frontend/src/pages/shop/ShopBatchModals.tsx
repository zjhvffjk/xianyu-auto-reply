/**
 * 批量操作弹窗组（店铺管理 - 宝贝设置）
 *
 * 功能：对勾选的多个商品批量执行
 * 1. 批量设置使用说明：批量默认回复接口（单次请求）
 * 2. 批量关联卡券：为每个商品关联同一个卡券（逐条保存，带进度）
 * 3. 批量改价：为鱼小铺商品设置同一价格（逐条保存，非鱼小铺商品跳过并提示）
 *
 * 保存成功后回调父页面刷新列表。
 */
import { useEffect, useMemo, useState } from 'react'
import { X, Loader2, Ticket, Tag, MessageSquare, Search, Check } from 'lucide-react'
import {
  getSelectableCards, updateItemCards,
  type CardRelationItem, type SelectableCard,
} from '@/api/cards'
import { batchSaveItemDefaultReply, updateItemPrice } from '@/api/items'
import { useUIStore } from '@/store/uiStore'
import type { Item } from '@/types'

export type ShopBatchKind = 'reply' | 'card' | 'price'

export interface ShopBatchModalsProps {
  accountId: string
  selectedItems: Item[]
  /** 鱼小铺商品数量（改价仅支持鱼小铺） */
  sellerSelectedCount: number
  open: ShopBatchKind | null
  onClose: () => void
  onSuccess: () => void | Promise<void>
}

const CARD_PAGE_SIZE = 50

export function ShopBatchModals({
  accountId,
  selectedItems,
  sellerSelectedCount,
  open,
  onClose,
  onSuccess,
}: ShopBatchModalsProps) {
  if (!open) return null
  if (open === 'reply') {
    return (
      <BatchReplyModal
        accountId={accountId}
        selectedItems={selectedItems}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    )
  }
  if (open === 'card') {
    return (
      <BatchCardModal
        selectedItems={selectedItems}
        onClose={onClose}
        onSuccess={onSuccess}
      />
    )
  }
  return (
    <BatchPriceModal
      accountId={accountId}
      selectedItems={selectedItems}
      sellerSelectedCount={sellerSelectedCount}
      onClose={onClose}
      onSuccess={onSuccess}
    />
  )
}

function ModalShell({
  title,
  subtitle,
  icon,
  onClose,
  children,
  footer,
}: {
  title: string
  subtitle: string
  icon: React.ReactNode
  onClose: () => void
  children: React.ReactNode
  footer: React.ReactNode
}) {
  return (
    <div className="modal-overlay" style={{ zIndex: 80 }}>
      <div className="modal-content max-w-lg">
        <div className="modal-header flex items-center justify-between">
          <div className="flex items-center gap-2">
            {icon}
            <div>
              <h2 className="text-lg font-semibold">{title}</h2>
              <p className="mt-0.5 text-sm text-gray-500">{subtitle}</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>
        {children}
        <div className="modal-footer flex justify-end gap-2">
          <button onClick={onClose} className="btn-ios-secondary">
            取消
          </button>
          {footer}
        </div>
      </div>
    </div>
  )
}

/** 批量设置使用说明 */
function BatchReplyModal({
  accountId,
  selectedItems,
  onClose,
  onSuccess,
}: {
  accountId: string
  selectedItems: Item[]
  onClose: () => void
  onSuccess: () => void | Promise<void>
}) {
  const { addToast } = useUIStore()
  const [content, setContent] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (enabled && !content.trim()) {
      addToast({ type: 'error', message: '请填写使用说明内容' })
      return
    }
    setSaving(true)
    try {
      const res = await batchSaveItemDefaultReply(accountId, {
        item_ids: selectedItems.map((item) => String(item.item_id ?? '')),
        reply_content: content,
        enabled,
        reply_once: false,
      })
      if (res.success) {
        addToast({ type: 'success', message: res.message || '批量设置成功' })
        await onSuccess()
      } else {
        addToast({ type: 'error', message: res.message || '批量设置失败' })
      }
    } catch {
      addToast({ type: 'error', message: '批量设置失败' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <ModalShell
      title="批量设置使用说明"
      subtitle={`将为所选 ${selectedItems.length} 个商品设置同一条默认回复`}
      icon={<MessageSquare className="w-5 h-5 text-blue-500" />}
      onClose={onClose}
      footer={
        <button onClick={handleSave} disabled={saving} className="btn-ios-primary">
          {saving ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              保存中...
            </span>
          ) : (
            '保存'
          )}
        </button>
      }
    >
      <div className="modal-body space-y-4">
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="batch-reply-enabled"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300"
          />
          <label htmlFor="batch-reply-enabled" className="font-medium text-gray-900 dark:text-white">
            启用使用说明
          </label>
        </div>
        <div className="input-group">
          <label className="input-label">回复内容</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="input-ios h-32 resize-none"
            placeholder="输入使用说明内容，多条消息用 ###### 分隔..."
            disabled={!enabled}
          />
          <p className="mt-1 text-xs text-gray-500">将覆盖所选商品已有的默认回复配置</p>
        </div>
      </div>
    </ModalShell>
  )
}

/** 批量关联卡券（单选一个卡券，逐条保存） */
function BatchCardModal({
  selectedItems,
  onClose,
  onSuccess,
}: {
  selectedItems: Item[]
  onClose: () => void
  onSuccess: () => void | Promise<void>
}) {
  const { addToast } = useUIStore()
  const [cards, setCards] = useState<SelectableCard[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [pickedCard, setPickedCard] = useState<SelectableCard | null>(null)
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })

  useEffect(() => {
    const t = setTimeout(() => setAppliedSearch(search.trim()), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const res = await getSelectableCards(selectedItems[0] ? String(selectedItems[0].item_id ?? '') : '', 1, CARD_PAGE_SIZE, appliedSearch)
        if (!cancelled) {
          setCards(res.list || [])
          setPickedCard(null)
        }
      } catch {
        if (!cancelled) addToast({ type: 'error', message: '加载卡券失败' })
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [appliedSearch, selectedItems, addToast])

  const filtered = useMemo(() => {
    if (!appliedSearch) return cards
    return cards
  }, [cards, appliedSearch])

  const handleSave = async () => {
    if (!pickedCard || pickedCard.id === undefined) {
      addToast({ type: 'error', message: '请先选择一个卡券' })
      return
    }
    const cardItem: CardRelationItem = {
      card_id: pickedCard.id,
      source: pickedCard.source,
      dock_record_id: pickedCard.dock_record_id ?? null,
    }
    setSaving(true)
    setProgress({ done: 0, total: selectedItems.length })
    let failCount = 0
    for (let i = 0; i < selectedItems.length; i++) {
      const itemId = String(selectedItems[i].item_id ?? '')
      try {
        const res = await updateItemCards(itemId, [cardItem])
        if (!res.success) failCount += 1
      } catch {
        failCount += 1
      }
      setProgress({ done: i + 1, total: selectedItems.length })
    }
    setSaving(false)
    if (failCount === 0) {
      addToast({ type: 'success', message: `已为 ${selectedItems.length} 个商品关联「${pickedCard.name}」` })
      await onSuccess()
    } else {
      addToast({ type: 'error', message: `${failCount} 个商品关联失败，请重试` })
    }
  }

  return (
    <ModalShell
      title="批量关联卡券"
      subtitle={`将所选 ${selectedItems.length} 个商品都关联到同一个卡券（覆盖各自原有关联）`}
      icon={<Ticket className="w-5 h-5 text-blue-500" />}
      onClose={onClose}
      footer={
        <button onClick={handleSave} disabled={saving || !pickedCard} className="btn-ios-primary">
          {saving ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              {progress.done}/{progress.total}
            </span>
          ) : (
            '关联'
          )}
        </button>
      }
    >
      <div className="modal-body space-y-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索卡券名称 / 类型"
            className="input-ios pl-8"
          />
        </div>
        <div className="max-h-72 overflow-y-auto rounded-md border border-gray-200 dark:border-gray-700">
          {loading ? (
            <div className="flex h-32 items-center justify-center text-sm text-gray-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载卡券...
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-sm text-gray-400">暂无可用卡券</div>
          ) : (
            filtered.map((card) => {
              const picked = pickedCard?.unique_key === card.unique_key
              return (
                <button
                  key={card.unique_key}
                  type="button"
                  onClick={() => setPickedCard(picked ? null : card)}
                  className={`flex w-full items-center gap-2 border-b border-gray-100 px-3 py-2 text-left last:border-0 transition-colors dark:border-gray-700/50 ${
                    picked ? 'bg-blue-50 dark:bg-slate-700' : 'hover:bg-gray-50 dark:hover:bg-slate-700/30'
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-slate-700 dark:text-slate-200">{card.name}</div>
                    <div className="text-xs text-gray-400">
                      {card.source === 'own' ? '自有' : card.source === 'dock_l1' ? '一级对接' : '二级对接'}
                      {' · '}
                      {card.type}
                    </div>
                  </div>
                  {picked && <Check className="h-4 w-4 flex-shrink-0 text-blue-500" />}
                </button>
              )
            })
          )}
        </div>
        <p className="text-xs text-amber-600 dark:text-amber-400">
          注意：批量关联会覆盖所选商品原有的卡券关联；如需追加请用「单独设置」逐个调整。
        </p>
      </div>
    </ModalShell>
  )
}

/** 批量改价（仅鱼小铺商品） */
function BatchPriceModal({
  accountId,
  selectedItems,
  sellerSelectedCount,
  onClose,
  onSuccess,
}: {
  accountId: string
  selectedItems: Item[]
  sellerSelectedCount: number
  onClose: () => void
  onSuccess: () => void | Promise<void>
}) {
  const { addToast } = useUIStore()
  const [price, setPrice] = useState('')
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const nonSellerCount = selectedItems.length - sellerSelectedCount

  const handleSave = async () => {
    const priceValue = Number(price)
    if (!price.trim() || Number.isNaN(priceValue) || priceValue <= 0) {
      addToast({ type: 'error', message: '请填写有效的价格' })
      return
    }
    const sellerItems = selectedItems.filter((item) => item.is_seller_item)
    setSaving(true)
    setProgress({ done: 0, total: sellerItems.length })
    let failCount = 0
    for (let i = 0; i < sellerItems.length; i++) {
      const itemId = String(sellerItems[i].item_id ?? '')
      try {
        const res = await updateItemPrice(accountId, itemId, { price: priceValue })
        if (!res.success) failCount += 1
      } catch {
        failCount += 1
      }
      setProgress({ done: i + 1, total: sellerItems.length })
    }
    setSaving(false)
    if (failCount === 0) {
      const skipTip = nonSellerCount > 0 ? `（${nonSellerCount} 个非鱼小铺商品已跳过）` : ''
      addToast({ type: 'success', message: `已将 ${sellerItems.length} 个商品价格改为 ¥${priceValue}${skipTip}` })
      await onSuccess()
    } else {
      addToast({ type: 'error', message: `${failCount} 个商品改价失败，请重试` })
    }
  }

  return (
    <ModalShell
      title="批量改价"
      subtitle={`将为 ${sellerSelectedCount} 个鱼小铺商品设置同一价格`}
      icon={<Tag className="w-5 h-5 text-blue-500" />}
      onClose={onClose}
      footer={
        <button onClick={handleSave} disabled={saving || sellerSelectedCount === 0} className="btn-ios-primary">
          {saving ? (
            <span className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              {progress.done}/{progress.total}
            </span>
          ) : (
            '改价'
          )}
        </button>
      }
    >
      <div className="modal-body space-y-4">
        <div className="input-group">
          <label className="input-label">新价格（元）</label>
          <input
            type="number"
            min={0.01}
            step={0.01}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className="input-ios"
            placeholder="如 9.9"
          />
        </div>
        {nonSellerCount > 0 && (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            所选商品中有 {nonSellerCount} 个不是鱼小铺商品，改价仅支持鱼小铺商品，这些商品将被跳过。
          </p>
        )}
        <p className="text-xs text-gray-500">改价将同步到闲鱼平台，请谨慎操作。</p>
      </div>
    </ModalShell>
  )
}
