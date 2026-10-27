/**
 * 素材编辑与单品发布共用的数据结构、素材回填规则。
 */
import type { MaterialVideo, PlatformCategoryPathItem, PlatformMaterialAttribute, ProductMaterial } from '@/api/productPublish'

export const PUBLISH_DESCRIPTION_LIMIT = 1500
export const MATERIAL_DESCRIPTION_LIMIT = PUBLISH_DESCRIPTION_LIMIT

export type ShippingMethod = 'free' | 'distance' | 'fixed' | 'template' | 'none'

export interface SpecificationValue {
  id: string
  name: string
  image?: string | null
}

export interface ProductSpecification {
  id: string
  name: string
  values: SpecificationValue[]
  supportImage: boolean
}

export interface SkuRow {
  key: string
  specs: Record<string, string>
  price: string
  stock: string
}

export interface DuplicateSpecificationValue {
  specificationName: string
  valueName: string
}

/** 查找同一规格类型下重复的规格值，供素材保存和单品发布共同校验。 */
export function findDuplicateSpecificationValue(
  specifications: ProductSpecification[],
): DuplicateSpecificationValue | null {
  for (const specification of specifications) {
    const values = new Set<string>()
    for (const value of specification.values) {
      const valueName = value.name.trim()
      if (!valueName) continue
      if (values.has(valueName)) {
        return {
          specificationName: specification.name.trim() || '未命名规格',
          valueName,
        }
      }
      values.add(valueName)
    }
  }
  return null
}

/** 按规格定义顺序生成稳定的 SKU key，确保素材库导入后能匹配原价格和库存。 */
export function buildSkuKey(specifications: ProductSpecification[], specs: Record<string, string>): string {
  return specifications
    .filter((specification) => specification.name.trim() && specification.values.some((value) => value.name.trim()))
    .map((specification) => `${specification.name}:${specs[specification.name] || ''}`)
    .join('|')
}

export interface PublishForm {
  account_id: string
  title: string
  description: string
  price: string
  original_price: string
  category: string
  platform_category_id: string
  platform_category_name: string
  platform_channel_category_id: string
  platform_channel_category_name: string
  platform_leaf_id: string
  platform_tb_category_id: string
  platform_category_path: PlatformCategoryPathItem[]
  platform_attributes: PlatformMaterialAttribute[]
  category_source: 'manual' | 'recommendation'
  category_confidence?: number
  videos: MaterialVideo[]
  quantity: number
  address: string
  address_expected_text?: string
  delivery_method: 'express' | 'pickup'
  shipping_method: ShippingMethod
  support_pickup: boolean
  postage: string
  brand: string
  condition: string
  specifications: ProductSpecification[]
  sku_rows: SkuRow[]
}

/** 保留真实的 0 库存和未知成色；账号发布能力限制由发布页另行处理。 */
export function materialToForm(material: Partial<ProductMaterial> = {}): Omit<PublishForm, 'account_id'> {
  const specifications = (material.specifications || []).map((spec, specIndex) => ({
    id: `spec-${specIndex}`,
    name: spec.name,
    supportImage: Boolean(spec.support_image),
    values: (spec.values || []).map((value, valueIndex) => ({
      id: `value-${specIndex}-${valueIndex}`,
      name: value.name,
      image: value.image || null,
    })),
  }))
  return {
    title: material.title ?? '',
    description: material.description ?? '',
    price: String(material.price ?? ''),
    original_price: material.original_price == null ? '' : String(material.original_price),
    category: material.category ?? '',
    platform_category_id: material.platform_category_id ?? '',
    platform_category_name: material.platform_category_name ?? '',
    platform_channel_category_id: material.platform_channel_category_id ?? '',
    platform_channel_category_name: material.platform_channel_category_name ?? '',
    platform_leaf_id: material.platform_leaf_id ?? '',
    platform_tb_category_id: material.platform_tb_category_id ?? '',
    platform_category_path: material.platform_category_path ?? [],
    platform_attributes: material.platform_attributes ?? [],
    category_source: material.category_source ?? 'manual',
    category_confidence: material.category_confidence ?? undefined,
    videos: material.videos ?? [],
    quantity: material.quantity ?? 1,
    address: material.address ?? '',
    address_expected_text: material.address_expected_text ?? undefined,
    delivery_method: material.delivery_method ?? 'express',
    shipping_method: material.shipping_method ?? (material.postage ? 'fixed' : 'free'),
    support_pickup: Boolean(material.support_pickup),
    postage: String(material.postage ?? 0),
    brand: material.brand ?? '',
    condition: material.condition ?? '',
    specifications,
    sku_rows: (material.sku_rows || []).map(row => ({
      key: buildSkuKey(specifications, row.specs || {}),
      specs: { ...row.specs },
      price: String(row.price ?? ''),
      stock: row.stock == null ? '' : String(row.stock),
    })),
  }
}
