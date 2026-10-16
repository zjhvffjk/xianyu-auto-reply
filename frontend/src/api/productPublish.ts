/**
 * 商品发布 API 接口层
 *
 * 功能：
 * 1. 素材库 CRUD
 * 2. 单品发布 / 批量发布
 * 3. 发布日志查询
 */
import { get, post, put, del } from '@/utils/request'
import type { ApiResponse } from '@/types'

const PREFIX = '/api/v1/product-publish'

// ==================== 类型定义 ====================

export interface PlatformMaterialAttribute {
  property_id?: string | null
  property_name?: string | null
  value_id?: string | null
  value_name?: string | null
  text?: string | null
  properties?: string | null
}

export interface PlatformCategoryPathItem {
  id: string
  name: string
}

export interface PlatformCategoryCandidate {
  cat_id?: string | null
  cat_name?: string | null
  channel_cat_id?: string | null
  channel_cat_name?: string | null
  leaf_id?: string | null
  tb_cat_id?: string | null
  path: PlatformCategoryPathItem[]
  score?: number | null
  is_selected?: boolean
}

export interface PlatformCategoryPropertyOption {
  property_id: string
  property_name: string
  value_id?: string | null
  value_name: string
  properties?: string | null
  channel_cat_id?: string | null
  tb_cat_id?: string | null
  is_selected?: boolean
}

export interface PlatformCategoryProperty {
  property_id: string
  property_name: string
  input_word?: string | null
  is_multiple?: boolean
  is_decisive_property?: boolean
  options: PlatformCategoryPropertyOption[]
}

export interface PlatformCategoryCardValue {
  catId?: string | null
  catName?: string | null
  channelCatId?: string | null
  channelCatName?: string | null
  tbCatId?: string | null
  isClicked?: string | null
  isUserClick?: string | null
  [key: string]: unknown
}

export interface PlatformCategoryCardData {
  propertyId?: string | null
  propertyName?: string | null
  valuesList?: PlatformCategoryCardValue[]
  [key: string]: unknown
}

export interface PlatformCategoryRecommendData {
  candidates: PlatformCategoryCandidate[]
  properties: PlatformCategoryProperty[]
  card_list?: PlatformCategoryCardData[]
  account_id?: string
}

export interface MaterialVideo {
  url: string
  path?: string | null
  name?: string | null
  size?: number | null
  file_id?: string | null
  width?: number | null
  height?: number | null
  duration_ms?: number | null
}

export interface PublishSpecificationValue {
  name: string
  image?: string | null
}

export interface PublishSpecification {
  name: string
  values: PublishSpecificationValue[]
  support_image?: boolean
}

export interface PublishSkuRow {
  specs: Record<string, string>
  price: number
  stock: number
}

export interface ProductMaterial {
  id: number
  user_id: number
  username?: string  // 管理员场景返回
  title: string
  description: string
  price: number
  original_price?: number | null
  category?: string | null
  platform_category_id?: string | null
  platform_category_name?: string | null
  platform_channel_category_id?: string | null
  platform_channel_category_name?: string | null
  platform_leaf_id?: string | null
  platform_tb_category_id?: string | null
  platform_category_path: PlatformCategoryPathItem[]
  platform_attributes: PlatformMaterialAttribute[]
  category_source: 'manual' | 'recommendation'
  category_confidence?: number | null
  images: string[]
  videos: MaterialVideo[]
  specifications: PublishSpecification[]
  sku_rows: PublishSkuRow[]
  quantity: number
  delivery_method: 'express' | 'pickup'
  shipping_method: 'free' | 'distance' | 'fixed' | 'template' | 'none'
  support_pickup: boolean
  postage: number
  address?: string | null
  address_expected_text?: string | null
  brand?: string | null
  condition: string
  remark?: string | null
  created_at: string
  updated_at: string
  auto_relist?: AutoRelistRule | null
  auto_relist_can_configure?: boolean
  auto_relist_owner_id?: number
}

export interface AutoRelistRule {
  id: number
  material_id: number
  owner_id: number
  account_id: string
  current_item_id: string
  card_id: number
  enabled: boolean
  delay_seconds: number
  status: 'active' | 'disabled' | 'waiting' | 'retrying' | 'error' | 'paused'
  status_text?: string
  version: number
  retry_count: number
  next_retry_at?: string | null
  last_order_no?: string | null
  last_order_id?: number | null
  last_order_updated_at?: string | null
  last_old_item_id?: string | null
  last_new_item_id?: string | null
  last_error?: string | null
  paused_reason?: string | null
  last_relisted_at?: string | null
  created_at?: string | null
  updated_at?: string | null
  can_configure?: boolean
  publish_state?: string
  result_unknown?: boolean
}

export interface AutoRelistEvent {
  id: number
  rule_id?: number
  material_id?: number
  owner_id?: number
  account_id?: string
  order_no: string
  old_item_id: string
  new_item_id?: string | null
  status: string
  status_text?: string
  publish_state: string
  result_unknown: boolean
  attempt_count: number
  error_message?: string | null
  reconcile_message?: string | null
  publish_request_id?: string | null
  next_retry_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface AutoRelistEventPage {
  list: AutoRelistEvent[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface MaterialCreateParams {
  title: string
  description: string
  price: number
  original_price?: number | null
  category?: string | null
  platform_category_id?: string | null
  platform_category_name?: string | null
  platform_channel_category_id?: string | null
  platform_channel_category_name?: string | null
  platform_leaf_id?: string | null
  platform_tb_category_id?: string | null
  platform_category_path?: PlatformCategoryPathItem[]
  platform_attributes?: PlatformMaterialAttribute[]
  category_source?: 'manual' | 'recommendation'
  category_confidence?: number | null
  images: string[]
  videos?: MaterialVideo[]
  specifications?: PublishSpecification[]
  sku_rows?: PublishSkuRow[]
  quantity?: number
  delivery_method?: 'express' | 'pickup'
  shipping_method?: 'free' | 'distance' | 'fixed' | 'template' | 'none'
  support_pickup?: boolean
  postage?: number
  address?: string | null
  address_expected_text?: string | null
  brand?: string | null
  condition?: string
  remark?: string | null
}

export interface MaterialListResponse {
  success: boolean
  message: string
  data: {
    list: ProductMaterial[]
    total: number
    page: number
    page_size: number
    total_pages: number
  }
}

export interface PublishLog {
  id: number
  user_id: number
  username?: string  // 管理员场景返回
  account_id: string
  title: string
  description?: string
  price?: string
  material_id?: number | null
  batch_id?: string | null
  status: 'pending' | 'publishing' | 'success' | 'failed'
  item_url?: string | null
  item_id?: string | null
  error_message?: string | null
  resolved_address_id?: number | null
  resolved_address_text?: string | null
  address_source?: 'material' | 'account_pool' | 'global_pool' | 'personal_pool' | null
  created_at: string
  updated_at: string
}

export interface PublishLogListResponse {
  success: boolean
  message: string
  data: {
    list: PublishLog[]
    total: number
    page: number
    page_size: number
    total_pages: number
  }
}

export interface BatchAccountStatus {
  account_id: string
  total: number
  success: number
  failed: number
  publishing: number
  pending: number
  sync_status: 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'unknown'
  sync_message: string
  sync_total_count: number
  sync_saved_count: number
}

export interface BatchStatusResponse {
  success: boolean
  message: string
  data: {
    batch_id: string
    total: number
    success: number
    failed: number
    publishing: number
    pending: number
    finished: boolean
    account_statuses: BatchAccountStatus[]
  }
}

export interface PublishSingleResponseData {
  item_url?: string | null
  item_id?: string | null
  log_id?: number
  sync_status?: 'success' | 'failed' | 'skipped'
  sync_message?: string | null
  sync_total_count?: number
  sync_saved_count?: number
}

export type PublishSingleResponse = ApiResponse<PublishSingleResponseData>

export interface PublishCommissionConfig {
  title: string
  default_title: string
  tips: string
  percent: string
  max_commission: string
  tip_url: string
}

export interface PublishAccountCapability {
  account_id: string
  is_fish_shop: boolean
  support_sku_or_inventory: boolean
  commission_config: PublishCommissionConfig
}

export interface PublishBatchResponseData {
  batch_id: string
  total: number
}

export type PublishBatchResponse = ApiResponse<PublishBatchResponseData>

/** 根据商品标题和描述推荐闲鱼平台分类。 */
export const recommendPlatformCategory = (params: {
  title: string
  description: string
  account_id?: string
  current_card_list?: PlatformCategoryCardData[]
  selected_list?: Record<string, unknown>[]
  cat_id?: string
  cat_name?: string
  channel_cat_id?: string
}): Promise<ApiResponse<PlatformCategoryRecommendData>> =>
  post(`${PREFIX}/category/recommend`, params)

// ==================== 素材库接口 ====================

/** 创建素材 */
export const createMaterial = (params: MaterialCreateParams): Promise<ApiResponse> =>
  post(`${PREFIX}/materials`, params)

/** 分页查询素材列表 */
export const getMaterials = (
  page = 1,
  pageSize = 20,
  filters?: { title?: string; category?: string; condition?: string; platform_category_id?: string }
): Promise<MaterialListResponse> => {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  })
  if (filters?.title) params.append('title', filters.title)
  if (filters?.category) params.append('category', filters.category)
  if (filters?.condition) params.append('condition', filters.condition)
  if (filters?.platform_category_id) params.append('platform_category_id', filters.platform_category_id)
  return get(`${PREFIX}/materials?${params}`)
}

/** 素材库里已有的分类名（筛选下拉选项） */
export const getMaterialCategories = (): Promise<ApiResponse<{ categories: string[] }>> =>
  get(`${PREFIX}/materials/categories`)

/** 获取单条素材详情 */
export const getMaterial = (id: number): Promise<ApiResponse<ProductMaterial>> =>
  get(`${PREFIX}/materials/${id}`)

/** 更新素材 */
export const updateMaterial = (
  id: number,
  params: Partial<MaterialCreateParams>
): Promise<ApiResponse> => put(`${PREFIX}/materials/${id}`, params)

/** 删除素材 */
export const deleteMaterial = (id: number): Promise<ApiResponse> =>
  del(`${PREFIX}/materials/${id}`)

/** 批量删除素材 */
export const batchDeleteMaterials = (ids: number[]): Promise<ApiResponse> =>
  post(`${PREFIX}/materials/batch-delete`, { ids })

/** 「商品库 → 素材库」同步预览数据 */
export interface MaterialSyncPreviewData {
  /** 还差多少条商品没有进素材库 */
  missing: number
  /** 各账号待同步条数（key 为账号ID） */
  by_account: Record<string, number>
  /** 素材池现有条数 */
  pooled: number
  /** 本次自动补回的判重键行数 */
  backfilled: number
}

/** 「商品库 → 素材库」单批同步结果 */
export interface MaterialSyncResultData {
  /** 本次同步开始时的缺口总数 */
  total_missing: number
  /** 本批实际处理条数 */
  processed: number
  /** 本批新增素材条数 */
  created: number
  /** 本批写入失败条数 */
  failed: number
  /** 本批跳过条数（如商品没有可用图片） */
  skipped: number
  /** 还剩多少条没同步（为 0 表示已补完） */
  remaining: number
  /** 是否因命中账号风控而中断 */
  aborted: boolean
  /** 失败/跳过原因明细 */
  errors: { item_id: string; reason: string }[]
}

/** 预览商品库与素材库的差集（只读，不写任何数据） */
export const getMaterialSyncPreview = (): Promise<ApiResponse<MaterialSyncPreviewData>> =>
  get(`${PREFIX}/materials/sync-preview`)

/** 从商品库同步一批缺失商品到素材库（幂等：已存在的不重建、不覆盖） */
export const syncMaterialsFromItems = (
  limit?: number
): Promise<ApiResponse<MaterialSyncResultData>> =>
  post(`${PREFIX}/materials/sync-from-items`, limit ? { limit } : {})

/** 「素材类目回填」单批结果 */
export interface MaterialCategoryBackfillResultData {
  /** 本次开始时的待补总数 */
  total_missing: number
  /** 本批实际处理条数 */
  processed: number
  /** 本批成功补全条数 */
  updated: number
  /** 本批失败条数 */
  failed: number
  /** 还剩多少条待补（为 0 表示已补完） */
  remaining: number
  /** 失败原因明细 */
  errors: { item_id: string; reason: string }[]
}

/** 预览还有多少素材缺渠道类目（只读，不调平台接口） */
export const getMaterialCategoryBackfillPreview = (): Promise<ApiResponse<{ missing: number }>> =>
  get(`${PREFIX}/materials/category-backfill-preview`)

/** 给历史素材补全渠道类目（发布必需：缺 channelCatId 会被闲鱼拒绝） */
export const backfillMaterialCategories = (
  limit?: number
): Promise<ApiResponse<MaterialCategoryBackfillResultData>> =>
  post(`${PREFIX}/materials/backfill-categories`, limit ? { limit } : {})

/** 风险检测命中的单个词 */
export interface ContentRiskHit {
  term: string
  level: 'block' | 'warn'
  group_id: string
  label: string
}

/** 风险检测命中的违规类型 */
export interface ContentRiskRule {
  group_id: string
  label: string
  level: 'block' | 'warn'
  rule: string
  hint: string
}

export interface ContentRiskResult {
  level: 'none' | 'warn' | 'block'
  /** 是否属于高危，true 时后端默认拦截发布 */
  blocked: boolean
  hit_count: number
  hits: ContentRiskHit[]
  rules: ContentRiskRule[]
  term_count: number
}

/** 批量预检时，单条素材的命中明细 */
export interface MaterialRiskItem {
  material_id: number
  title: string
  risk: ContentRiskResult
}

/** 发布前内容风险预检（离线词库，只查文字，不查图片） */
export const checkContentRisk = (params: {
  title?: string
  description?: string
  category?: string
  material_ids?: number[]
}): Promise<ApiResponse<{ risk: ContentRiskResult; material_risks: MaterialRiskItem[] }>> =>
  post(`${PREFIX}/risk-check`, params)

/** 查询素材自动续售规则。 */
export const getAutoRelistRule = (materialId: number): Promise<ApiResponse<AutoRelistRule | null>> =>
  get(`${PREFIX}/materials/${materialId}/auto-relist`)

/** 保存素材自动续售规则。 */
export const saveAutoRelistRule = (
  materialId: number,
  params: {
    account_id?: string | null
    current_item_id?: string | null
    card_id?: number | null
    enabled: boolean
    delay_seconds: number
    expected_version?: number | null
  },
): Promise<ApiResponse<AutoRelistRule>> => put(`${PREFIX}/materials/${materialId}/auto-relist`, params)

/** 分页查询自动续售记录。 */
export const getAutoRelistEvents = (
  materialId: number,
  page = 1,
  pageSize = 20,
): Promise<ApiResponse<AutoRelistEventPage>> =>
  get(`${PREFIX}/materials/${materialId}/auto-relist/events?page=${page}&page_size=${pageSize}`)

/** 管理员集中查询自动续售事件，可按状态筛选。 */
export const getAllAutoRelistEvents = (
  page = 1,
  pageSize = 20,
  status?: string,
): Promise<ApiResponse<AutoRelistEventPage>> => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (status?.trim()) params.set('status', status.trim())
  return get(`${PREFIX}/auto-relist/events?${params.toString()}`)
}

/** 人工确认未知发布结果，后端验证商品归属后仅安排本地关联迁移。 */
export const reconcileAutoRelistEvent = (
  materialId: number,
  eventId: number,
  params: { outcome: 'published' | 'not_published'; new_item_id?: string },
): Promise<ApiResponse<AutoRelistEvent>> =>
  post(`${PREFIX}/materials/${materialId}/auto-relist/events/${eventId}/reconcile`, {
    ...params,
  })

/** 将发布结果未知的续售记录标记为本次失败，并重新排队发布当前订单。 */
export const markAutoRelistEventFailed = (
  materialId: number,
  eventId: number,
): Promise<ApiResponse<AutoRelistEvent>> =>
  post(`${PREFIX}/materials/${materialId}/auto-relist/events/${eventId}/mark-failed`)

// ==================== 发布接口 ====================

/** 查询账号是否开通鱼小铺及其发布能力。 */
export const getPublishAccountCapability = (
  accountId: string,
): Promise<ApiResponse<PublishAccountCapability>> =>
  get(`${PREFIX}/accounts/${encodeURIComponent(accountId)}/capability`)

/** 单品发布（同步调用闲鱼发布接口） */
export const publishSingle = (params: {
  force_publish?: boolean
  account_id: string
  title: string
  description: string
  price: number
  original_price?: number | null
  category?: string
  platform_category_id?: string | null
  platform_category_name?: string | null
  platform_channel_category_id?: string | null
  platform_channel_category_name?: string | null
  platform_leaf_id?: string | null
  platform_tb_category_id?: string | null
  platform_category_path?: PlatformCategoryPathItem[]
  platform_attributes?: PlatformMaterialAttribute[]
  category_source?: 'manual' | 'recommendation'
  category_confidence?: number | null
  images: string[]        // 本地绝对路径，由 uploadProductImages 返回
  videos?: MaterialVideo[]
  quantity?: number
  specifications?: PublishSpecification[]
  sku_rows?: PublishSkuRow[]
  stock?: number
  address?: string
  address_expected_text?: string
  delivery_method?: string
  shipping_method?: 'free' | 'distance' | 'fixed' | 'template' | 'none'
  support_pickup?: boolean
  postage?: number
  brand?: string
  condition?: string
}): Promise<PublishSingleResponse> =>
  post(`${PREFIX}/publish/single`, params, { timeout: 90000 })

/** 批量发布（异步，立即返回 batch_id） */
export const publishBatch = (params: {
  force_publish?: boolean
  account_ids: string[]
  material_ids: number[]
}): Promise<PublishBatchResponse> => post(`${PREFIX}/publish/batch`, params)

/** 查询批量发布任务状态 */
export const getBatchStatus = (batchId: string): Promise<BatchStatusResponse> =>
  get(`${PREFIX}/publish/batch/${batchId}/status`)

// ==================== 图片上传 ====================

/** 上传商品图片（返回本地路径供 Playwright 使用 + URL 供预览）
 *  注意：不要手动设置 Content-Type，axios 会自动添加正确的 multipart boundary
 */
export const uploadProductImages = async (files: File[]): Promise<{
  success: boolean
  message: string
  data?: { paths: string[]; urls: string[] }
}> => {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))
  return post(`${PREFIX}/upload/images`, formData)
}

/** 上传商品视频，返回本地路径和预览地址。 */
export const uploadProductVideos = async (files: File[]): Promise<{
  success: boolean
  message: string
  data?: { videos: MaterialVideo[]; paths: string[]; urls: string[] }
}> => {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  return post(`${PREFIX}/upload/videos`, formData)
}

/** 分页查询发布日志 */
export const getPublishLogs = (
  page = 1,
  pageSize = 20,
  accountId?: string,
  status?: string
): Promise<PublishLogListResponse> => {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  })
  if (accountId) params.append('account_id', accountId)
  if (status) params.append('status', status)
  return get(`${PREFIX}/logs?${params}`)
}

export const clearPublishLogs = async (): Promise<{ success: boolean; message: string }> => {
  return del<{ success: boolean; message: string }>(`${PREFIX}/logs/clear`)
}
