/** 商品管理与素材导入共用状态选项，实际筛选仍由商品管理接口处理。 */
export const ITEM_STATUS_OPTIONS = [
  {value: 'on_sale', label: '在售'},
  {value: 'off_shelf', label: '已下架'},
  {value: 'sold', label: '已售出'},
  {value: 'deleted', label: '已删除'},
  {value: 'violation', label: '违规'},
  {value: 'unknown', label: '状态未知'},
  {value: 'all', label: '全部'},
] as const
export type ItemPlatformStatus = typeof ITEM_STATUS_OPTIONS[number]['value']
