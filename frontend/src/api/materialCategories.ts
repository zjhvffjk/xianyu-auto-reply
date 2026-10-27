import { post } from '@/utils/request'
import type { PlatformCategoryCandidate } from './productPublish'
export interface CategoryResult {id: number; status: string; message?: string; candidate?: PlatformCategoryCandidate | null; current?: PlatformCategoryCandidate | null; category_token?: string}
export const previewMaterialCategories = (ids: number[], mode: 'fill' | 'replace' = 'fill') => post<{success: boolean; message?: string; data: {results: CategoryResult[]}}>('/api/v1/product-publish/materials/category-preview', {ids, mode})
export const confirmMaterialCategories = (entries: {id: number; candidate: PlatformCategoryCandidate; expected_category_token?: string}[], mode: 'fill' | 'replace' = 'fill') => post<{success: boolean; message?: string; data: {results: CategoryResult[]}}>('/api/v1/product-publish/materials/category-confirm', {entries, mode})
