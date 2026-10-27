import type { ProductMaterial, PlatformCategoryCandidate } from '@/api/productPublish'
export const hasMaterialCategory = (material: ProductMaterial) => Boolean(material.platform_category_id && material.platform_channel_category_id)
export function categoryPathLabel(candidate: PlatformCategoryCandidate): string {
  const names = (candidate.path || []).map(item => item.name).filter(Boolean).filter((name, index, all) => index === 0 || name !== all[index - 1])
  return names.join(' / ') || candidate.cat_name || candidate.channel_cat_name || '未命名类目'
}
export const materialCategoryLabel = (material: ProductMaterial) => categoryPathLabel({path: material.platform_category_path || [], cat_name: material.platform_category_name || material.category})
