/**
 * 店铺管理 API 门面
 *
 * 说明：店铺管理不新增后端接口，全部复用现有能力——
 * - 账号列表：/api/v1/cookies/details/paginated（getAccountDetailsPaginated）
 * - 店铺商品：/api/v1/items/cookie/{id}（getItems，一次返回该账号全部商品）
 * - 卡券关联：/api/v1/cards/item/{id}/cards（getCardsByItemId / updateItemCards）
 * - 使用说明：商品默认回复接口（getItemDefaultReply / saveItemDefaultReply / 批量）
 * - 平台刷新：/api/v1/items/get-all-from-account（fetchAllItemsFromAccount）
 *
 * 本文件只做店铺管理视角的薄封装与类型导出，业务逻辑仍在原模块。
 */
import { getItemsPaginated } from '@/api/items'
import type { Item } from '@/types'

export interface ShopItemListParams {
  page?: number
  pageSize?: number
  keyword?: string
}

/**
 * 分页获取店铺商品（宝贝设置表格数据源，与商品管理同接口）
 *
 * @param accountId 店铺账号ID（xy_accounts.account_id）
 */
export async function getShopItemsPaginated(
  accountId: string,
  params: ShopItemListParams = {}
): Promise<{
  success: boolean
  data: Item[]
  total: number
  page: number
  page_size: number
  total_pages: number
}> {
  return getItemsPaginated(
    params.page ?? 1,
    params.pageSize ?? 20,
    accountId,
    params.keyword?.trim() ? { keyword: params.keyword.trim() } : undefined
  )
}
