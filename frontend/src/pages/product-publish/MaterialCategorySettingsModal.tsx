import { useState } from 'react'
import { X, ChevronRight } from 'lucide-react'
import type { ProductMaterial } from '@/api/productPublish'
import { hasMaterialCategory } from '@/utils/materialCategory'
import { MaterialCategoryBatchModal } from './MaterialCategoryBatchModal'
import { MaterialCategoryReplaceModal } from './MaterialCategoryReplaceModal'

export function MaterialCategorySettingsModal({materials, accountId, onClose, onSaved, onEdit}: {
  materials: ProductMaterial[]; accountId: string | null; onClose: () => void
  onSaved: () => void; onEdit: (material: ProductMaterial) => void
}) {
  const [mode, setMode] = useState<'fill' | 'replace' | null>(null)
  const [saved, setSaved] = useState(false)
  const missing = materials.filter(m => !hasMaterialCategory(m)).length
  const handleSaved = () => {setSaved(true); onSaved()}
  const onBack = saved ? undefined : () => setMode(null)
  if (mode === 'fill') return <MaterialCategoryBatchModal materials={materials} accountId={accountId} onClose={onClose} onSaved={handleSaved} onEdit={onEdit} onBack={onBack} />
  if (mode === 'replace') return <MaterialCategoryReplaceModal materials={materials} accountId={accountId} onClose={onClose} onSaved={handleSaved} onBack={onBack} />
  return <div className="modal-overlay" style={{zIndex: 80}}><div className="modal-content max-w-xl">
    <div className="modal-header flex items-center justify-between"><h2 className="text-lg font-semibold">批量设置类目</h2><button aria-label="关闭类目设置" onClick={onClose}><X className="h-5 w-5" /></button></div>
    <div className="modal-body space-y-3">
      <p className="text-sm text-slate-500">已选 {materials.length} 件素材，其中 {missing} 件缺少完整类目。选择处理方式，核对后再保存。</p>
      <button className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 p-4 text-left hover:border-blue-400 hover:bg-blue-50/50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800" disabled={!missing} onClick={() => setMode('fill')}>
        <span><span className="block font-medium">仅补全缺失（{missing} 件）</span><span className="mt-1 block text-sm text-slate-500">逐件获取建议，跳过已有完整类目的素材。</span></span><ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
      </button>
      {!missing && <p className="px-1 text-xs text-slate-500">所选素材类目均已完整，需要更换时请选择“统一修改所选”。</p>}
      <button className="flex w-full items-center justify-between gap-3 rounded-xl border border-slate-200 p-4 text-left hover:border-blue-400 hover:bg-blue-50/50 dark:border-slate-700 dark:hover:bg-slate-800" onClick={() => setMode('replace')}>
        <span><span className="block font-medium">统一修改所选（{materials.length} 件）</span><span className="mt-1 block text-sm text-slate-500">统一选择新类目，预览原类目与新类目后确认修改。</span></span><ChevronRight className="h-4 w-4 shrink-0 text-slate-400" />
      </button>
      <p className="text-xs text-slate-400">只更新素材库，保存前不会改变任何类目，也不会发布商品。</p>
    </div>
    <div className="modal-footer flex justify-end"><button className="btn-ios-secondary" onClick={onClose}>暂不设置</button></div>
  </div></div>
}
