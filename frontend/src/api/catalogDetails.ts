import { get, post } from '@/utils/request'
import type { ApiResponse } from '@/types'

export interface CatalogDetailJob {
  job_id: string
  account_id: string
  state: 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'
  total: number
  processed: number
  succeeded: number
  cached: number
  failed: number
  failures: Array<{ item_id: string; message: string }>
  checked_item_ids?: string[]
  message: string
}

export const isDetailSyncRunning = (job: CatalogDetailJob | null) =>
  job?.state === 'queued' || job?.state === 'running'

export const startCatalogDetailSync = (accountId: string, itemIds?: string[]) =>
  post<ApiResponse<CatalogDetailJob>>(`/api/v1/items/detail-sync/${encodeURIComponent(accountId)}`, { item_ids: itemIds || [] })

export const getCatalogDetailSync = (accountId: string, jobId?: string) =>
  get<ApiResponse<CatalogDetailJob | null>>(`/api/v1/items/detail-sync/${encodeURIComponent(accountId)}${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`)
