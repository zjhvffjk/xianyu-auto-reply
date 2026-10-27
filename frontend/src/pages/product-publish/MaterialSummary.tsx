import { useState } from 'react'
import { ExternalLink, Image, Store } from 'lucide-react'
import type { ProductMaterial } from '@/api/productPublish'
import { getAccountName } from '@/utils/accountLabel'
import { getMaterialImage, getMissingMaterialFields } from '@/utils/materialSummary'

export function MaterialSummary({material}: {material: ProductMaterial}) {
  const [failedImage, setFailedImage] = useState('')
  const image = getMaterialImage(material.images)
  const missing = getMissingMaterialFields(material).filter(field => field !== '成色' && field !== '平台类目')
  const title = material.title || '未命名素材'
  const source = material.catalog_account ? getAccountName(material.catalog_account) : material.catalog_account_pk ? '来源店铺已移除' : ''
  return (
    <div className="flex min-w-0 items-start gap-3 py-1">
      <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-md border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800">
        {image && image !== failedImage ? <img src={image} alt={title} loading="lazy" className="h-full w-full object-cover" onError={() => setFailedImage(image)} /> : <Image className="h-5 w-5 text-slate-300" aria-label="暂无主图" />}
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <p title={title} className="block truncate font-medium text-slate-800 dark:text-slate-100">{title}</p>
        {material.catalog_item_id ? <a href={`https://www.goofish.com/item?id=${encodeURIComponent(material.catalog_item_id)}`} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1 text-xs text-slate-400 hover:text-blue-600">
          <span className="truncate">来源商品 ID：{material.catalog_item_id}</span><ExternalLink className="h-3 w-3 shrink-0" />
        </a> : <p className="text-xs text-slate-400">未关联来源商品</p>}
        {source && <p title={source} className="flex min-w-0 items-center gap-1 text-xs text-slate-500"><Store className="h-3 w-3 shrink-0" /><span className="truncate">{source}</span></p>}
        {missing.length > 0 && <p title={`待补全：${missing.join('、')}`} className="truncate text-xs text-amber-600 dark:text-amber-400">待补全：{missing.join('、')}</p>}
      </div>
    </div>
  )
}
