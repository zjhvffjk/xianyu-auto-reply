/**
 * 店铺管理纯函数工具（商品链接解析 / 商品行映射）
 *
 * 说明：
 * 1. 本文件不依赖任何运行时模块（仅有类型导入），可被 Node 直接加载执行，
 *    便于 tests/test_shop_management.py 做行为级验证
 * 2. 闲鱼商品链接的常见形态：
 *    - https://www.goofish.com/item?id=771234567890
 *    - https://www.goofish.com/item/?id=771234567890&spm=...
 *    - https://www.goofish.com/item/771234567890 （路径形态）
 *    - 直接粘贴商品ID（纯数字）
 *    - 混在分享文案里的链接（前后带其他文字）
 * 3. 解析失败一律返回 null，由调用方提示用户，不做猜测
 */
import type { Item } from '@/types'

/** 商品ID最短长度：超过可能是其他数字，不足则不采纳 */
const MIN_ITEM_ID_LENGTH = 5
/** 商品ID最长长度（防御异常输入） */
const MAX_ITEM_ID_LENGTH = 32

/** 匹配查询参数中的 id / item_id / itemId（值必须是数字） */
const QUERY_ID_PATTERN = /[?&](?:id|item_id|itemId)=(\d+)/i
/** 匹配路径形态 /item/123456 或 /item/123456.html */
const PATH_ID_PATTERN = /\/item\/(\d+)/i

/**
 * 从任意输入中解析闲鱼商品ID
 *
 * @param input 用户输入（商品链接 / 商品ID / 混排文案）
 * @returns 商品ID；无法解析返回 null
 */
export function parseShopItemId(input: string): string | null {
  if (!input) return null
  const text = input.trim()
  if (!text) return null

  // 纯数字：直接作为商品ID（去除首尾空白后的整体判断）
  if (/^\d+$/.test(text)) {
    return isValidItemId(text) ? text : null
  }

  // 链接形态：先查查询参数，再查路径
  const queryMatch = text.match(QUERY_ID_PATTERN)
  if (queryMatch && isValidItemId(queryMatch[1])) {
    return queryMatch[1]
  }

  const pathMatch = text.match(PATH_ID_PATTERN)
  if (pathMatch && isValidItemId(pathMatch[1])) {
    return pathMatch[1]
  }

  return null
}

/** 商品ID长度合理性校验 */
function isValidItemId(itemId: string): boolean {
  return itemId.length >= MIN_ITEM_ID_LENGTH && itemId.length <= MAX_ITEM_ID_LENGTH
}

/**
 * 根据商品ID生成闲鱼商品链接（用于表格展示与跳转）
 *
 * @param itemId 商品ID
 */
export function buildShopItemUrl(itemId: string): string {
  return `https://www.goofish.com/item?id=${itemId}`
}

/** 宝贝设置表格行数据（从商品接口响应映射） */
export interface ShopItemRow {
  itemId: string
  title: string
  price: string
  /** 平台商品状态文案（鱼小铺账号有值，如 在售/已下架） */
  statusDesc: string
  /** 平台状态归一值（在卖/售出/下架/用户删除/违规，后端 platform_status） */
  platformStatus: string
  /** 是否已配置发货卡券 */
  hasCard: boolean
  /** 是否已配置使用说明（默认回复） */
  hasDefaultReply: boolean
  /** 是否多规格商品 */
  isMultiSpec: boolean
  /** 库存（鱼小铺） */
  quantity: string
  /** 上架时间（鱼小铺） */
  shelfTime: string
  /** 是否鱼小铺商品（仅鱼小铺可改价） */
  isSellerItem: boolean
}

/** 商品接口响应 → 宝贝设置表格行 */
export function toShopItemRow(item: Item): ShopItemRow {
  return {
    itemId: String(item.item_id ?? ''),
    title: item.title || item.item_title || '',
    price: item.price || item.item_price || '',
    statusDesc: item.item_status_desc || '',
    platformStatus: item.platform_status || '',
    hasCard: Boolean(item.has_card),
    hasDefaultReply: Boolean(item.has_default_reply),
    isMultiSpec: Boolean(item.is_multi_spec),
    quantity: item.item_quantity === undefined || item.item_quantity === null ? '' : String(item.item_quantity),
    shelfTime: item.item_shelf_time || '',
    isSellerItem: Boolean(item.is_seller_item),
  }
}

/** 宝贝设置页 tab 口径：已设置/未设置以「卡券或使用说明任一有配置」为准 */
export type ShopItemTab = 'all' | 'configured' | 'unconfigured'

/** 判断一行商品在指定 tab 下是否可见 */
export function matchShopItemTab(row: ShopItemRow, tab: ShopItemTab): boolean {
  if (tab === 'all') return true
  const configured = row.hasCard || row.hasDefaultReply
  return tab === 'configured' ? configured : !configured
}

/** 商品是否已下架（按平台状态文案判断，空状态视为在售） */
export function isShopItemOffshelf(row: ShopItemRow): boolean {
  return (row.statusDesc || '').includes('下架')
}

/**
 * 商品是否在售（宝贝设置列表口径：只列在售商品）
 *
 * 已下架/已售出/用户删除/违规的商品当前没人买得到，配了发货也不会触发，
 * 所以不进入宝贝设置列表；与商品管理列表默认口径、关联商品弹窗保持一致。
 * 状态为空按在售处理：个人版账号不返回平台状态，老数据也可能缺状态。
 */
export function isShopItemOnSale(row: ShopItemRow): boolean {
  const status = row.platformStatus || row.statusDesc || ''
  if (!status) return true
  return status.includes('在卖') || status.includes('在售')
}
