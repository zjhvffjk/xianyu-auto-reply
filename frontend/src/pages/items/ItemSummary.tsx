import { useState } from 'react'
import { ExternalLink, Package } from 'lucide-react'
import type { Item } from '@/types'

/** 商品主图、标题和 ID 共用一列，便于对照辨认。 */
export function ItemSummary({ item }: { item: Item }) {
  const [failedImage, setFailedImage] = useState('')
  const title = item.item_title || item.title || '未命名商品'
  const image = item.item_image || ''
  const href = `https://www.goofish.com/item?id=${encodeURIComponent(item.item_id)}`

  return (
    <div className="flex min-w-0 items-center gap-3 py-1">
      <div className="relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800">
        <Package className="h-5 w-5 text-slate-300 dark:text-slate-500" aria-hidden="true" />
        {image && failedImage !== image && (
          <img src={image} alt={title} loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover" onError={() => setFailedImage(image)} />
        )}
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <a href={href} target="_blank" rel="noopener noreferrer" title={title} className="block truncate text-sm font-medium leading-5 text-slate-800 transition-colors hover:text-blue-600 dark:text-slate-100 dark:hover:text-blue-400">
          {title}
        </a>
        <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1 text-xs text-slate-500 transition-colors hover:text-blue-600 dark:text-slate-400">
          <span className="truncate">商品 ID：{item.item_id}</span>
          <ExternalLink className="h-3 w-3 shrink-0" aria-hidden="true" />
        </a>
      </div>
    </div>
  )
}
