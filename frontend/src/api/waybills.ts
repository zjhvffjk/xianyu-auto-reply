import { get, put, post, del } from '@/utils/request'

export interface WaybillRecipient {
  name: string
  phone: string
  province: string
  city: string
  county: string
  address: string
}
export interface WaybillPreview {
  order_no: string
  title: string
  amount: string
  quantity: number
  recipient: WaybillRecipient
  errors: string[]
  recipient_errors: string[]
  record: WaybillRecord | null
}
export interface WaybillSettings {
  platform_configured: boolean
  legacy_allowed: boolean
  authorization_available: boolean
  embedded_print_available: boolean
  configured: boolean
  app_key: string
  has_secret: boolean
  login_user: string
  mall_user_id: string
  verified_at: string | null
}
export interface WaybillPlatformConfig {
  configured: boolean
  app_key: string
  has_secret: boolean
  authorization_available: boolean
  embedded_print_available: boolean
}
export interface WaybillRecord {
  id: string
  order_no: string
  status: string
  detail: string
  waybill_no: string
  carrier: string
  template_id: string
  platform_status: string | null
  updated_at: string | null
}
export interface WaybillTemplate { id: string; carrier: string; code: string; type: string }
export interface WaybillAuthorization {
  status: 'not_started' | 'pending' | 'authorized' | 'expired' | 'revoked' | 'stale'
  platform_configured: boolean
  authorization_available: boolean
  shop_name: string
  authorized_at: string | null
  expires_at: string | null
  embedded_print_available: boolean
  callback_path: string
}
interface Result<T> { success: boolean; data: T; message?: string }
async function checked<T>(request: Promise<Result<T>>): Promise<Result<T>> {
  const result = await request
  if (result.success !== true || result.data == null) throw new Error(result.message || '操作未完成，请刷新后核对')
  return result
}
const prefix = (account: string) => `/api/v1/waybills/${encodeURIComponent(account)}`
export const getWaybillAuthorization = (account: string) => checked(get<Result<WaybillAuthorization>>(`${prefix(account)}/authorization`))
export const startWaybillAuthorization = (account: string) => checked(post<Result<{ url: string; status: string; expires_at: string }>>(`${prefix(account)}/authorization`))
export const revokeWaybillAuthorization = (account: string) => checked(del<Result<WaybillAuthorization>>(`${prefix(account)}/authorization`))
export const getWaybillPlatformConfig = () => checked(get<Result<WaybillPlatformConfig>>('/api/v1/waybills/platform/config'))
export const saveWaybillPlatformConfig = (data: { app_key: string; app_secret?: string }) =>
  checked(put<Result<WaybillPlatformConfig>>('/api/v1/waybills/platform/config', data))
export const getWaybillSettings = (account: string) => checked(get<Result<WaybillSettings>>(`${prefix(account)}/settings`))
export const saveWaybillSettings = (account: string, data: {
  app_key: string; app_secret?: string; login_user: string; mall_user_id: string
}) => checked(put<Result<WaybillSettings>>(`${prefix(account)}/settings`, data))
export const getWaybillTemplates = (account: string) => checked(post<Result<WaybillTemplate[]>>(`${prefix(account)}/templates`))
export const previewWaybills = (account: string, order_nos: string[]) => checked(post<Result<WaybillPreview[]>>(`${prefix(account)}/preview`, { order_nos }))
export const syncWaybill = (account: string, order_no: string, recipient: WaybillRecipient) =>
  checked(post<Result<WaybillRecord>>(`${prefix(account)}/sync`, { order_no, recipient }))
export const numberWaybill = (account: string, order_no: string, template_id: string) =>
  checked(post<Result<WaybillRecord>>(`${prefix(account)}/number`, { order_no, template_id }))
export const getWaybillWorkbench = (account: string) => checked(post<Result<{ url: string }>>(`${prefix(account)}/workbench`))
export const getWaybillRecords = (account: string, page = 1, page_size = 20) =>
  checked(get<Result<{ items: WaybillRecord[]; total: number }>>(`${prefix(account)}/records`, { params: { page, page_size } }))
