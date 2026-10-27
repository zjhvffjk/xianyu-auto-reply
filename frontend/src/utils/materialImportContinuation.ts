import type { CatalogImportResult } from '@/api/catalogMaterials'
import type { ProductMaterial } from '@/api/productPublish'

export function newlyImportedMaterialIds(results: CatalogImportResult[]): number[] {
  return [...new Set(results.filter(row => row.status === 'created' && Number.isSafeInteger(row.material_id) && Number(row.material_id) > 0)
    .map(row => row.material_id!))]
}

export async function loadImportedMaterials(ids: number[], fetchOne: (id: number) => Promise<{
  success: boolean; data?: ProductMaterial | null; message?: string
}>): Promise<ProductMaterial[]> {
  return Promise.all(ids.map(async id => {
    const result = await fetchOne(id)
    if (!result.success || !result.data || result.data.id !== id) {
      throw new Error(`读取素材失败（ID：${id}）${result.message ? `：${result.message}` : ''}`)
    }
    return result.data
  }))
}
