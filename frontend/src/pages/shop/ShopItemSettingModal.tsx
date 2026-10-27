/**
 * 单独设置弹窗（店铺管理 - 宝贝设置）
 *
 * 功能：两个页签配置单个商品的发货
 * 1. 发货内容：关联卡券（自有 + 一级/二级对接），来单按商品ID自动发券
 *    ——复用卡券关联接口，选中态来自 getCardsByItemId，保存走 updateItemCards
 * 2. 使用说明：商品默认回复（买家咨询该商品时自动回复的内容）
 *    ——复用商品默认回复接口，支持 文本 / API接口 / 站外联系方式 三种类型
 *
 * 两个页签各自保存，保存成功后回调父页面刷新列表状态。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from 'react'
import { buildCardRelations } from '@/utils/cardRelations'
import { CardSelectionNotice } from '@/pages/cards/CardSelectionNotice'
import { getApiErrorMessage } from '@/utils/apiError'
import {
  X, Loader2, Search, Ticket, MessageSquare, ImagePlus, CheckSquare, Square, Save,
} from 'lucide-react'
import {
  getCardsByItemId, getSelectableCards, getAllSelectableCardKeys, updateItemCards,
  type CardData, type SelectableCard,
} from '@/api/cards'
import {
  getItemDefaultReply, saveItemDefaultReply, uploadItemDefaultReplyImage,
} from '@/api/items'
import LocationContactReplyFields, {
  DEFAULT_LOCATION_TITLE,
  type LocationContactReplyValue,
} from '@/pages/common/LocationContactReplyFields'
import { useUIStore } from '@/store/uiStore'
import { buildShopItemUrl } from '@/utils/shopItem'
import type { Item } from '@/types'

type SettingTab = 'delivery' | 'instruction'

const REPLY_TYPE_OPTIONS = [
  { value: 'text', label: '默认回复' },
  { value: 'api', label: 'API接口' },
  { value: 'external_contact', label: '站外联系方式' },
] as const

type ReplyType = (typeof REPLY_TYPE_OPTIONS)[number]['value']

const CARD_PAGE_SIZE = 50
const EMPTY_LOCATION: LocationContactReplyValue = {
  location_name: '',
  location_longitude: '',
  location_latitude: '',
  location_title: DEFAULT_LOCATION_TITLE,
  location_subtitle: '',
}

const cardTypeLabels: Record<string, string> = {
  api: 'API',
  text: '文本',
  data: '批量',
  image: '图片',
  yifan_api: '亦凡API',
}

interface ShopItemSettingModalProps {
  cookieId: string
  item: Item
  onClose: () => void
  onSaved: () => void | Promise<void>
}

export function ShopItemSettingModal({ cookieId, item, onClose, onSaved }: ShopItemSettingModalProps) {
  const { addToast } = useUIStore()
  const itemId = String(item.item_id ?? '')
  const itemName = item.title || item.item_title || itemId

  const [tab, setTab] = useState<SettingTab>('delivery')

  // ---------- 发货内容（卡券关联） ----------
  const [deliveryLoading, setDeliveryLoading] = useState(true)
  const [deliverySaving, setDeliverySaving] = useState(false)
  const [associatedReady, setAssociatedReady] = useState(false)
  const [associatedError, setAssociatedError] = useState('')
  const [cards, setCards] = useState<SelectableCard[]>([])
  const [cardPage, setCardPage] = useState(1)
  const [cardTotal, setCardTotal] = useState(0)
  const [cardLoadingMore, setCardLoadingMore] = useState(false)
  const loadingMoreRef = useRef(false)
  const [cardSearch, setCardSearch] = useState('')
  const [appliedCardSearch, setAppliedCardSearch] = useState('')
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set())
  const [cardCache, setCardCache] = useState<Map<string, SelectableCard>>(new Map())
  const [selectAllLoading, setSelectAllLoading] = useState(false)

  const mergeCache = useCallback((list: SelectableCard[]) => {
    if (list.length === 0) return
    setCardCache((prev) => {
      const next = new Map(prev)
      for (const c of list) next.set(c.unique_key, c)
      return next
    })
  }, [])

  /** 已关联卡券 → 初始选中态 */
  const loadAssociated = useCallback(async () => {
    setAssociatedReady(false)
    setAssociatedError('')
    try {
      const rel = await getCardsByItemId(itemId)
      const existing: CardData[] = rel?.data || []
      const keys = new Set<string>()
      const mapped: SelectableCard[] = []
      for (const ec of existing) {
        if (ec.id === undefined) continue
        let uniqueKey: string
        let source: SelectableCard['source']
        if (ec.card_source && ec.card_source !== 'own' && ec.dock_record_id) {
          uniqueKey = `dock_${ec.dock_record_id}`
          source = ec.card_source
        } else {
          uniqueKey = `own_${ec.id}`
          source = 'own'
        }
        keys.add(uniqueKey)
        mapped.push({
          id: ec.id,
          name: ec.name,
          type: ec.type,
          source,
          dock_name: null,
          dock_record_id: ec.dock_record_id ?? null,
          is_multi_spec: ec.is_multi_spec,
          spec_name: ec.spec_name,
          spec_value: ec.spec_value,
          enabled: ec.enabled,
          price: ec.price ?? null,
          unique_key: uniqueKey,
        })
      }
      mergeCache(mapped)
      setSelectedKeys(keys)
      setAssociatedReady(true)
    } catch {
      setAssociatedError('读取原有发货配置失败，重试成功后才能保存。')
      addToast({ type: 'error', message: '加载已关联卡券失败' })
    }
  }, [itemId, mergeCache, addToast])

  const loadFirstPage = useCallback(async (search: string) => {
    setDeliveryLoading(true)
    try {
      const res = await getSelectableCards(itemId, 1, CARD_PAGE_SIZE, search)
      setCards(res.list || [])
      setCardPage(1)
      setCardTotal(res.total || 0)
      mergeCache(res.list || [])
    } catch {
      addToast({ type: 'error', message: '加载卡券失败' })
    } finally {
      setDeliveryLoading(false)
    }
  }, [itemId, mergeCache, addToast])

  useEffect(() => {
    loadAssociated()
  }, [loadAssociated])

  useEffect(() => {
    const t = setTimeout(() => setAppliedCardSearch(cardSearch.trim()), 300)
    return () => clearTimeout(t)
  }, [cardSearch])

  useEffect(() => {
    loadFirstPage(appliedCardSearch)
  }, [loadFirstPage, appliedCardSearch])

  const loadMoreCards = async () => {
    if (loadingMoreRef.current || deliveryLoading) return
    if (cards.length >= cardTotal) return
    loadingMoreRef.current = true
    setCardLoadingMore(true)
    try {
      const nextPage = cardPage + 1
      const res = await getSelectableCards(itemId, nextPage, CARD_PAGE_SIZE, appliedCardSearch)
      setCards((prev) => [...prev, ...(res.list || [])])
      setCardPage(nextPage)
      setCardTotal(res.total || 0)
      mergeCache(res.list || [])
    } catch {
      addToast({ type: 'error', message: '加载更多失败' })
    } finally {
      loadingMoreRef.current = false
      setCardLoadingMore(false)
    }
  }

  const handleCardScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
      loadMoreCards()
    }
  }

  const toggleCard = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const handleSelectAllCards = async (select: boolean) => {
    setSelectAllLoading(true)
    try {
      const res = await getAllSelectableCardKeys(appliedCardSearch)
      mergeCache(res.list || [])
      setSelectedKeys((prev) => {
        const next = new Set(prev)
        res.list.forEach((c) => (select ? next.add(c.unique_key) : next.delete(c.unique_key)))
        return next
      })
    } catch {
      addToast({ type: 'error', message: '全选加载失败' })
    } finally {
      setSelectAllLoading(false)
    }
  }

  const allLoadedSelected = cards.length > 0 && cards.every((c) => selectedKeys.has(c.unique_key))

  const saveDelivery = async () => {
    if (!associatedReady || deliveryLoading || deliverySaving) return
    setDeliverySaving(true)
    try {
      const cardItems = buildCardRelations(selectedKeys, cardCache)
      const res = await updateItemCards(itemId, cardItems)
      if (res.success) {
        addToast({ type: 'success', message: res.message || '发货内容已保存' })
        await onSaved()
      } else {
        addToast({ type: 'error', message: res.message || '保存失败' })
      }
    } catch (error) {
      addToast({ type: 'error', message: getApiErrorMessage(error, '保存失败') })
    } finally {
      setDeliverySaving(false)
    }
  }

  // ---------- 使用说明（商品默认回复） ----------
  const [replyLoading, setReplyLoading] = useState(false)
  const [replySaving, setReplySaving] = useState(false)
  const [replyLoaded, setReplyLoaded] = useState(false)
  const [replyError, setReplyError] = useState('')
  const [replyEnabled, setReplyEnabled] = useState(false)
  const [replyType, setReplyType] = useState<ReplyType>('text')
  const [replyContent, setReplyContent] = useState('')
  const [replyImage, setReplyImage] = useState('')
  const [replyImageUploading, setReplyImageUploading] = useState(false)
  const [replyOnce, setReplyOnce] = useState(false)
  const [replyApiUrl, setReplyApiUrl] = useState('')
  const [replyApiTimeout, setReplyApiTimeout] = useState(80)
  const [replyLocation, setReplyLocation] = useState<LocationContactReplyValue>(EMPTY_LOCATION)
  const replyImageInputRef = useRef<HTMLInputElement>(null)

  const loadReply = useCallback(async () => {
    setReplyLoading(true)
    setReplyError('')
    try {
      const res = await getItemDefaultReply(cookieId, itemId)
      if (!res.success) throw new Error(res.message || '读取使用说明失败')
      if (res.success && res.data) {
        setReplyEnabled(Boolean(res.data.enabled))
        setReplyType((res.data.reply_type as ReplyType) || 'text')
        setReplyContent(res.data.reply_content || '')
        setReplyImage(res.data.reply_image || '')
        setReplyOnce(Boolean(res.data.reply_once))
        setReplyApiUrl(res.data.api_url || '')
        setReplyApiTimeout(res.data.api_timeout || 80)
        setReplyLocation({
          location_name: res.data.location_name || '',
          location_longitude: res.data.location_longitude || '',
          location_latitude: res.data.location_latitude || '',
          location_title: res.data.location_title || DEFAULT_LOCATION_TITLE,
          location_subtitle: res.data.location_subtitle || '',
        })
      }
      setReplyLoaded(true)
    } catch {
      setReplyError('读取使用说明失败，重试成功后才能保存。')
      addToast({ type: 'error', message: '加载使用说明失败' })
    } finally {
      setReplyLoading(false)
    }
  }, [cookieId, itemId, addToast])

  // 切到使用说明页签时按需加载
  useEffect(() => {
    if (tab === 'instruction' && !replyLoaded) {
      loadReply()
    }
  }, [tab, replyLoaded, loadReply])

  const handleReplyImageUpload = async (file: File) => {
    setReplyImageUploading(true)
    try {
      const res = await uploadItemDefaultReplyImage(cookieId, itemId, file)
      if (res.success && res.image_url) {
        setReplyImage(res.image_url)
      } else {
        addToast({ type: 'error', message: res.message || '图片上传失败' })
      }
    } catch {
      addToast({ type: 'error', message: '图片上传失败' })
    } finally {
      setReplyImageUploading(false)
    }
  }

  const saveReply = async () => {
    if (!replyLoaded || replyLoading || replySaving || replyError) return
    if (replyEnabled && replyType === 'text' && !replyContent.trim() && !replyImage) {
      addToast({ type: 'error', message: '请填写回复内容或上传回复图片' })
      return
    }
    if (replyEnabled && replyType === 'api' && !replyApiUrl.trim()) {
      addToast({ type: 'error', message: '请填写 API 地址' })
      return
    }
    setReplySaving(true)
    try {
      const res = await saveItemDefaultReply(cookieId, itemId, {
        reply_content: replyContent,
        reply_image: replyImage,
        enabled: replyEnabled,
        reply_once: replyOnce,
        reply_type: replyType,
        api_url: replyApiUrl,
        api_timeout: replyApiTimeout,
        location_name: replyLocation.location_name,
        location_longitude: replyLocation.location_longitude,
        location_latitude: replyLocation.location_latitude,
        location_title: replyLocation.location_title,
        location_subtitle: replyLocation.location_subtitle,
      })
      if (res.success) {
        addToast({ type: 'success', message: res.message || '使用说明已保存' })
        await onSaved()
      } else {
        addToast({ type: 'error', message: res.message || '保存失败' })
      }
    } catch {
      addToast({ type: 'error', message: '保存失败' })
    } finally {
      setReplySaving(false)
    }
  }

  const selectedCards = useMemo(() => {
    const list: SelectableCard[] = []
    for (const key of selectedKeys) {
      const c = cardCache.get(key)
      if (c) list.push(c)
    }
    return list
  }, [selectedKeys, cardCache])

  const sourceBadge = (source: SelectableCard['source']) => {
    if (source === 'own') {
      return <span className="mr-1 inline-block rounded bg-green-100 px-1 py-0.5 text-[10px] font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">自有</span>
    }
    if (source === 'dock_l1') {
      return <span className="mr-1 inline-block rounded bg-blue-100 px-1 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">一级对接</span>
    }
    return <span className="mr-1 inline-block rounded bg-purple-100 px-1 py-0.5 text-[10px] font-medium text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">二级对接</span>
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 70 }}>
      <div className="modal-content max-w-2xl max-h-[88vh] overflow-hidden flex flex-col">
        <div className="modal-header flex items-center justify-between flex-shrink-0">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">单独设置</h2>
            <p className="mt-1 truncate text-sm text-gray-500" title={itemName}>
              {itemName} ·{' '}
              <a href={buildShopItemUrl(itemId)} target="_blank" rel="noreferrer" className="text-blue-500 hover:underline">
                商品链接
              </a>
            </p>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg">
            <X className="w-4 h-4 text-gray-500" />
          </button>
        </div>

        {/* 页签 */}
        <div className="flex flex-shrink-0 border-b border-gray-200 px-4 dark:border-gray-700">
          <button
            onClick={() => setTab('delivery')}
            className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === 'delivery'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <Ticket className="h-4 w-4" />
            发货内容（关联卡券）
          </button>
          <button
            onClick={() => setTab('instruction')}
            className={`flex items-center gap-1.5 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
              tab === 'instruction'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <MessageSquare className="h-4 w-4" />
            使用说明（默认回复）
          </button>
        </div>

        {((tab === 'delivery' && associatedError) || (tab === 'instruction' && replyError)) && (
          <div role="alert" className="mx-4 mt-3 flex items-center justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            <span>{tab === 'delivery' ? associatedError : replyError}</span>
            <button type="button" className="shrink-0 font-medium underline" onClick={() => tab === 'delivery' ? loadAssociated() : loadReply()}>重新加载</button>
          </div>
        )}
        <div className="flex-1 overflow-hidden">
          {tab === 'delivery' ? (
            <div className="flex h-full flex-col p-4">
              <div className="mb-2 flex items-center gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={cardSearch}
                    onChange={(e) => setCardSearch(e.target.value)}
                    placeholder="搜索卡券名称 / 类型"
                    className="input-ios pl-8"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => handleSelectAllCards(!allLoadedSelected)}
                  disabled={selectAllLoading || cardTotal === 0}
                  className={`inline-flex items-center gap-1 rounded-md px-2.5 py-2 text-xs font-medium transition-colors disabled:opacity-50 ${
                    allLoadedSelected
                      ? 'bg-orange-100 text-orange-700 hover:bg-orange-200 dark:bg-orange-900/30 dark:text-orange-400'
                      : 'bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-900/30 dark:text-blue-400'
                  }`}
                >
                  {selectAllLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckSquare className="h-3.5 w-3.5" />}
                  {allLoadedSelected ? '取消全选' : '全选当前筛选'}
                </button>
              </div>

              <div className="mb-2 flex items-center justify-between text-xs text-gray-500">
                <span>已选 {selectedKeys.size} 张卡券</span>
                <span>共 {cardTotal} 个可选</span>
              </div>

              <div className="mb-3"><CardSelectionNotice cards={selectedCards} /></div>
              <div className="flex-1 overflow-y-auto rounded-md border border-gray-200 dark:border-gray-700" style={{ maxHeight: '46vh' }} onScroll={handleCardScroll}>
                {deliveryLoading ? (
                  <div className="flex h-32 items-center justify-center text-sm text-gray-400">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    正在加载卡券...
                  </div>
                ) : cards.length === 0 ? (
                  <div className="flex h-32 items-center justify-center text-sm text-gray-400">
                    暂无可用卡券，请先到「卡券管理」创建
                  </div>
                ) : (
                  cards.map((card) => {
                    const checked = selectedKeys.has(card.unique_key)
                    return (
                      <label
                        key={card.unique_key}
                        className="flex cursor-pointer items-center gap-2.5 border-b border-gray-100 px-3 py-2 last:border-0 hover:bg-blue-50/50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                      >
                        <button
                          type="button"
                          onClick={() => toggleCard(card.unique_key)}
                          className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border border-gray-300 text-blue-600 dark:border-gray-500"
                        >
                          {checked ? <CheckSquare className="h-4 w-4" /> : <Square className="h-4 w-4" />}
                        </button>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm text-slate-700 dark:text-slate-200">{card.name}</div>
                          <div className="text-xs text-gray-400">
                            {sourceBadge(card.source)}
                            {card.source === 'own' && (cardTypeLabels[card.type] || card.type)}
                            {card.source !== 'own' && card.dock_name}
                            {card.is_multi_spec && ` | ${card.spec_name}: ${card.spec_value}`}
                            {card.enabled === false && ' | 已禁用'}
                          </div>
                        </div>
                        {card.price && <div className="flex-shrink-0 text-xs text-gray-400">¥{card.price}</div>}
                      </label>
                    )
                  })
                )}
                {cardLoadingMore && (
                  <div className="flex items-center justify-center py-2 text-xs text-gray-400">
                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                    加载更多...
                  </div>
                )}
              </div>

              {selectedCards.length > 0 && (
                <div className="mt-2 rounded-md bg-gray-50 p-2 text-xs text-gray-500 dark:bg-gray-800">
                  <span className="font-medium text-gray-600 dark:text-gray-300">将发送：</span>
                  {selectedCards.map((c) => c.name).join('、')}
                </div>
              )}
            </div>
          ) : (
            <div className="h-full overflow-y-auto p-4" style={{ maxHeight: '60vh' }}>
              {replyLoading ? (
                <div className="flex h-40 items-center justify-center text-gray-400">
                  <Loader2 className="h-5 w-5 animate-spin" />
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      id="shop-reply-enabled"
                      checked={replyEnabled}
                      onChange={(e) => setReplyEnabled(e.target.checked)}
                      className="w-4 h-4 rounded border-gray-300"
                    />
                    <label htmlFor="shop-reply-enabled" className="font-medium text-gray-900 dark:text-white">
                      启用使用说明（买家咨询该商品时自动回复）
                    </label>
                  </div>

                  <div className="input-group">
                    <label className="input-label">内容方式</label>
                    <div className="flex gap-2">
                      {REPLY_TYPE_OPTIONS.map((opt) => (
                        <button
                          key={opt.value}
                          type="button"
                          onClick={() => setReplyType(opt.value)}
                          disabled={!replyEnabled}
                          className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                            replyType === opt.value
                              ? 'bg-blue-600 text-white border-blue-600'
                              : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-300 dark:border-slate-600 hover:border-blue-400'
                          }`}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {replyType === 'api' && (
                    <>
                      <div className="input-group">
                        <label className="input-label">API 地址</label>
                        <input
                          type="text"
                          value={replyApiUrl}
                          onChange={(e) => setReplyApiUrl(e.target.value)}
                          className="input-ios"
                          placeholder="https://example.com/api/reply"
                          disabled={!replyEnabled}
                        />
                      </div>
                      <div className="input-group">
                        <label className="input-label">超时时间（秒）</label>
                        <input
                          type="number"
                          min={1}
                          max={120}
                          value={replyApiTimeout}
                          onChange={(e) => setReplyApiTimeout(Number(e.target.value) || 80)}
                          className="input-ios"
                          disabled={!replyEnabled}
                        />
                      </div>
                    </>
                  )}

                  {replyType === 'external_contact' && (
                    <LocationContactReplyFields
                      value={replyLocation}
                      onChange={setReplyLocation}
                      disabled={!replyEnabled}
                    />
                  )}

                  {replyType === 'text' && (
                    <>
                      <div className="input-group">
                        <label className="input-label">回复内容</label>
                        <textarea
                          value={replyContent}
                          onChange={(e) => setReplyContent(e.target.value)}
                          className="input-ios h-32 resize-none"
                          placeholder="输入该商品的使用说明内容..."
                          disabled={!replyEnabled}
                        />
                        <p className="mt-1 text-xs text-gray-500">
                          多条消息使用 ###### 分隔，将拆分为多条消息依次发送
                        </p>
                      </div>
                      <div className="input-group">
                        <label className="input-label">回复图片（可选）</label>
                        <input
                          ref={replyImageInputRef}
                          type="file"
                          accept="image/*"
                          onChange={(e) => {
                            const file = e.target.files?.[0]
                            if (file) handleReplyImageUpload(file)
                            e.target.value = ''
                          }}
                          className="hidden"
                          disabled={!replyEnabled}
                        />
                        {replyImage ? (
                          <div className="relative inline-block">
                            <img
                              src={replyImage}
                              alt="回复图片"
                              className="max-h-[150px] max-w-[200px] rounded-lg border border-slate-200 dark:border-slate-700"
                            />
                            <button
                              type="button"
                              onClick={() => setReplyImage('')}
                              disabled={!replyEnabled}
                              className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => replyImageInputRef.current?.click()}
                            disabled={replyImageUploading || !replyEnabled}
                            className="flex items-center gap-2 rounded-lg border-2 border-dashed border-slate-300 px-4 py-2 transition-colors hover:border-blue-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600"
                          >
                            {replyImageUploading ? (
                              <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                <span className="text-sm text-slate-500">上传中...</span>
                              </>
                            ) : (
                              <>
                                <ImagePlus className="h-4 w-4 text-slate-400" />
                                <span className="text-sm text-slate-500">点击上传图片</span>
                              </>
                            )}
                          </button>
                        )}
                        <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                          同时配置图片和文字时，将先发送图片，再发送文字内容
                        </p>
                      </div>
                    </>
                  )}

                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      id="shop-reply-once"
                      checked={replyOnce}
                      onChange={(e) => setReplyOnce(e.target.checked)}
                      className="w-4 h-4 rounded border-gray-300"
                      disabled={!replyEnabled}
                    />
                    <label htmlFor="shop-reply-once" className="text-gray-700 dark:text-gray-300">
                      只回复一次（同一用户咨询该商品只回复一次）
                    </label>
                  </div>

                  <div className="rounded-lg bg-blue-50 p-3 text-sm text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
                    <strong>说明：</strong>
                    <ul className="mt-1 list-inside list-disc space-y-1">
                      <li>使用说明即商品默认回复，优先级高于账号默认回复</li>
                      <li>回复优先级：关键词 &gt; AI回复 &gt; 商品默认回复 &gt; 账号默认回复</li>
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="modal-footer flex justify-end flex-shrink-0">
          <button
            onClick={tab === 'delivery' ? saveDelivery : saveReply}
            disabled={tab === 'delivery' ? deliverySaving || deliveryLoading || !associatedReady : replySaving || replyLoading || !replyLoaded || Boolean(replyError)}
            className="btn-ios-primary"
          >
            {tab === 'delivery' ? (
              deliverySaving ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  保存中...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Save className="w-4 h-4" />
                  保存发货内容
                </span>
              )
            ) : replySaving ? (
              <span className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                保存中...
              </span>
            ) : (
              <span className="flex items-center gap-2">
                <Save className="w-4 h-4" />
                保存使用说明
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ShopItemSettingModal
