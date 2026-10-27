import type { ProductMaterial } from '@/api/productPublish'

/** 仅标出实际缺失字段，库存 0 是有效数据。 */
export function getMissingMaterialFields(material: ProductMaterial): string[] {
  const fields: string[] = []
  if (!material.title?.trim()) fields.push('标题')
  if (!material.description?.trim()) fields.push('描述')
  if (!getMaterialImage(material.images)) fields.push('图片')
  if (!Number.isFinite(Number(material.price)) || Number(material.price) <= 0) fields.push('售价')
  if (material.quantity == null || !Number.isInteger(Number(material.quantity)) || Number(material.quantity) < 0) fields.push('库存')
  if (!material.platform_category_id || !material.platform_channel_category_id) fields.push('平台类目')
  if (!material.condition?.trim()) fields.push('成色')
  return fields
}

export function getMaterialImage(images: string[] = []): string {
  for (const value of images) {
    const url = typeof value === 'string' ? value.trim() : ''
    if (/^https?:\/\//i.test(url) || url.startsWith('/static/')) return url
    if (url.startsWith('//')) return `https:${url}`
  }
  return ''
}
