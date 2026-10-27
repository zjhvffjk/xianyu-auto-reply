import { useRef, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { recommendPlatformCategory, type ProductMaterial, type PlatformCategoryCandidate } from '@/api/productPublish'
import { previewMaterialCategories, confirmMaterialCategories } from '@/api/materialCategories'
import { categoryPathLabel } from '@/utils/materialCategory'

interface Row {material: ProductMaterial; status: string; message: string; candidates: PlatformCategoryCandidate[]; choice: string}
export function MaterialCategoryBatchModal({materials, accountId, onClose, onSaved, onEdit, onBack}: {
  materials: ProductMaterial[]; accountId: string | null; onClose: () => void; onSaved: () => void; onEdit: (material: ProductMaterial) => void
  onBack?: () => void
}) {
  const [rows, setRows] = useState<Row[]>(materials.map(material => ({material, status: 'pending', message: '待获取建议', candidates: [], choice: ''})))
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const stop = useRef(false)
  const running = useRef(false)
  const update = (id: number, patch: Partial<Row>) => setRows(previous => previous.map(row => row.material.id === id ? {...row, ...patch} : row))
  const prepare = async () => {
    if (running.current) return
    running.current = true; stop.current = false; setBusy(true); setProgress(0); setError('')
    try {
      const preview = await previewMaterialCategories(materials.map(material => material.id))
      if (!preview.success) throw new Error(preview.message || '读取类目失败')
      for (const [index, result] of preview.data.results.entries()) {
        if (stop.current) break
        const material = materials.find(item => item.id === result.id)!
        update(result.id, {choice: '', candidates: []})
        if (result.status !== 'ready') update(result.id, {status: result.status, message: result.message || '已跳过'})
        else if (result.candidate) update(result.id, {status: 'ready', candidates: [result.candidate], message: '来自商品管理，请确认类目'})
        else if (!accountId) update(result.id, {status: 'failed', message: '请先选择店铺，再获取官方类目建议'})
        else {
          update(result.id, {status: 'loading', message: '正在获取官方类目建议…'})
          try {
            const response = await recommendPlatformCategory({account_id: accountId, title: material.title, description: material.description})
            if (!response.success) throw new Error(response.message || '类目推荐失败')
            const candidates = (response.data?.candidates || []).filter(candidate => candidate.cat_id && candidate.channel_cat_id && candidate.cat_name)
            update(result.id, {status: candidates.length ? 'ready' : 'failed', candidates, message: candidates.length ? '请选择并确认建议类目' : '没有完整建议，请打开素材编辑手动选择'})
          } catch (e) { update(result.id, {status: 'failed', message: e instanceof Error ? e.message : '类目推荐失败'}) }
        }
        setProgress(index + 1)
      }
    } catch (e) { setError(e instanceof Error ? e.message : '获取建议失败') }
    finally { setBusy(false); running.current = false }
  }
  const entries = rows.filter(row => row.status === 'ready' && row.choice !== '' && row.candidates[Number(row.choice)]).map(row => ({id: row.material.id, candidate: row.candidates[Number(row.choice)]}))
  const save = async () => {
    if (running.current || !entries.length) return
    running.current = true; setBusy(true); setSaving(true); setError('')
    try {
      const response = await confirmMaterialCategories(entries)
      if (!response.success) throw new Error(response.message || '保存失败')
      response.data.results.forEach(result => update(result.id, {status: result.status, choice: '', message: result.message || '已处理'}))
      onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试') }
    finally { running.current = false; setBusy(false); setSaving(false) }
  }
  return <div className="modal-overlay" style={{zIndex: 80}}><div className="modal-content max-w-3xl">
    <div className="modal-header flex items-center justify-between"><h2 className="text-lg font-semibold">补全所选素材的平台类目</h2><button aria-label="关闭类目补全" disabled={busy} onClick={onClose}><X className="h-5 w-5" /></button></div>
    <div className="modal-body space-y-3">
      <p className="text-sm text-slate-500">先复用商品管理已有类目；缺失时获取官方建议。请选择后再保存，完整类目会跳过。只更新本地素材。</p>
      <div className="flex items-center gap-2"><button className="btn-ios-secondary" disabled={busy} onClick={prepare}>获取 / 重新获取建议</button>{busy && <span className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />{saving ? '正在保存已确认类目…' : `处理中 ${progress}/${materials.length}`}</span>}{busy && !saving && <button className="text-sm text-blue-600" onClick={() => {stop.current = true}}>停止获取</button>}</div>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <div className="max-h-96 divide-y divide-slate-100 overflow-auto rounded-lg border border-slate-200 dark:divide-slate-700 dark:border-slate-700">{rows.map(row => <div className="space-y-2 p-3" key={row.material.id}>
        <p className="truncate text-sm font-medium" title={row.material.title}>{row.material.title}</p>
        <p className={`text-xs ${row.status === 'failed' ? 'text-red-600' : row.status === 'saved' ? 'text-green-700' : 'text-slate-500'}`}>{row.message}</p>
        {row.status !== 'skipped' && row.status !== 'saved' && <button disabled={busy} className="text-xs text-blue-600 hover:underline" onClick={() => onEdit(row.material)}>打开素材编辑手动选择</button>}
        {row.status === 'ready' && <select aria-label={`素材 ${row.material.id} 的建议类目`} className="input-ios" disabled={busy} value={row.choice} onChange={e => update(row.material.id, {choice: e.target.value})}>
          <option value="">请选择要保存的类目</option>{row.candidates.map((candidate, index) => <option value={index} key={`${candidate.cat_id}-${candidate.channel_cat_id}-${index}`}>{categoryPathLabel(candidate)}</option>)}
        </select>}
      </div>)}</div>
    </div>
    <div className="modal-footer flex flex-wrap justify-end gap-2">{onBack && <button className="btn-ios-secondary mr-auto" disabled={busy} onClick={onBack}>返回设置方式</button>}<button className="btn-ios-secondary" disabled={busy} onClick={onClose}>关闭</button><button className="btn-ios-primary" disabled={busy || !entries.length} onClick={save}>保存已选择的类目（{entries.length}）</button></div>
  </div></div>
}
