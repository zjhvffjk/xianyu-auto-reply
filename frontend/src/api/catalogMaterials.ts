import { post } from '@/utils/request'
export interface CatalogImportResult {
  item_id: string
  status: 'created' | 'exists' | 'failed'
  material_id?: number
  message: string
}
export const importCatalogMaterials = (accountId: string, itemIds: string[]) =>
  post<{success: boolean; message: string; data: {results: CatalogImportResult[]}}>('/api/v1/product-publish/materials/from-catalog', {account_id: accountId, item_ids: itemIds})
