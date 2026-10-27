import { get, put, post } from '@/utils/request'

export interface RefundMessageSettings {
  enabled: boolean
  unshipped_enabled: boolean
  shipped_enabled: boolean
  unshipped_content: string
  shipped_content: string
}
export interface RefundMessageRecord {
  id: number; order_no: string; status: string; detail: string; created_at: string
}
export interface RefundApplication {
  order_no: string; refund_id: string; title: string; refund_amount: string | null
  refund_type: string; status: string; reason: string; eligible: boolean
  blocked_reason: string; requires_verification: boolean
}
export interface RefundApplicationsResponse {
  success: boolean; data: RefundApplication[]; checked_at: string; limited: boolean
  can_submit: boolean; capability_message: string
  history: RefundApprovalResult[]
}
export interface RefundApprovalResult {
  id: string; order_no: string; refund_id: string; refund_amount: string
  status: string; detail: string; verification_url: string | null
}
const root = (id: string) => `/api/v1/refund-tools/${encodeURIComponent(id)}`
export const getRefundSettings = (id: string) => get<{
  success: boolean; data: RefundMessageSettings; records: RefundMessageRecord[]
}>(`${root(id)}/messages`)
export const saveRefundSettings = (id: string, settings: RefundMessageSettings) =>
  put<{ success: boolean; message: string }>(`${root(id)}/messages`, settings)
export const getRefundApplications = (id: string) =>
  get<RefundApplicationsResponse>(`${root(id)}/applications`, { timeout: 30000 })
export const prepareRefundApprovals = (id: string, entries: Pick<RefundApprovalResult, 'order_no' | 'refund_id' | 'refund_amount'>[]) =>
  post<{success: boolean; data: RefundApprovalResult[]}>(`${root(id)}/approvals/prepare`, { entries }, { timeout: 60000 })
export const getRefundVerification = (id: string, operationId: string, refresh = false) =>
  post<{success: boolean; data: RefundApprovalResult}>(`${root(id)}/approvals/${encodeURIComponent(operationId)}/verification`, { refresh }, { timeout: 40000 })
export const confirmRefundApproval = (id: string, operationId: string) =>
  post<{success: boolean; data: RefundApprovalResult}>(`${root(id)}/approvals/${encodeURIComponent(operationId)}/confirm`, {}, { timeout: 60000 })
