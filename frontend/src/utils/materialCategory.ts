import type { ProductMaterial, PlatformCategoryCandidate } from '@/api/productPublish'
export const hasMaterialCategory = (material: ProductMaterial) => Boolean(material.platform_category_id && material.platform_channel_category_id)
export function categoryPathLabel(candidate: PlatformCategoryCandidate): string {
  const names = (candidate.path || []).map(item => item.name).filter(Boolean).filter((name, index, all) => index === 0 || name !== all[index - 1])
  return names.join(' / ') || candidate.cat_name || candidate.channel_cat_name || '未命名类目'
}
export const materialCategoryLabel = (material: ProductMaterial) => categoryPathLabel({path: material.platform_category_path || [], cat_name: material.platform_category_name || material.category})

export function savedMaterialCategoryChoices(materials: ProductMaterial[]): PlatformCategoryCandidate[] {
  const unique = new Map<string, PlatformCategoryCandidate>()
  for (const material of materials) {
    const name = material.platform_category_name || material.category
    if (!hasMaterialCategory(material) || !name?.trim()) continue
    const candidate: PlatformCategoryCandidate = {
      cat_id: material.platform_category_id, cat_name: name,
      channel_cat_id: material.platform_channel_category_id,
      channel_cat_name: material.platform_channel_category_name,
      tb_cat_id: material.platform_tb_category_id, leaf_id: material.platform_leaf_id,
      path: material.platform_category_path || [],
    }
    const key = JSON.stringify([candidate.cat_id, candidate.channel_cat_id, candidate.tb_cat_id || '', candidate.leaf_id || ''])
    if (!unique.has(key)) unique.set(key, candidate)
  }
  return [...unique.values()]
}

export function categoryRecommendationInput(material: ProductMaterial, keyword: string) {
  const query = keyword.trim()
  return query ? {title: query, description: query} : {title: material.title, description: material.description}
}
