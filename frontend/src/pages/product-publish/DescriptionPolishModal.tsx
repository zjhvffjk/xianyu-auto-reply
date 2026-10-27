import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Sparkles, X } from 'lucide-react'
import { getAiListingConfigs, polishDescription, type AiListingConfig, type PolishedCopy } from '@/api/aiListing'
import { getApiErrorMessage } from '@/utils/apiError'
import { getPolishedCopyError, isPolishedCopyPreview } from '@/utils/polishedCopy'

interface Props {
  title: string
  description: string
  sourceChanged: boolean
  onClose: () => void
  onApply: (copy: PolishedCopy) => void
}

export default function DescriptionPolishModal({ title, description, sourceChanged, onClose, onApply }: Props) {
  const headingId = useId()
  const [configs, setConfigs] = useState<AiListingConfig[]>([])
  const [configId, setConfigId] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<PolishedCopy | null>(null)
  const mounted = useRef(true)
  const pending = useRef(false)
  const [reload, setReload] = useState(0)
  const previewError = result ? getPolishedCopyError(result) : ''

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    getAiListingConfigs(1, 100).then(response => {
      if (!active) return
      if (!response.success) throw new Error(response.message || '加载AI配置失败')
      setConfigs(response.data.list)
      setConfigId(current => response.data.list.some(config => String(config.id) === current) ? current : String(response.data.list[0]?.id ?? ''))
    }).catch(reason => {
      if (active) setError(getApiErrorMessage(reason, '加载AI配置失败'))
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [reload])

  const generate = async () => {
    if (pending.current || !configId || sourceChanged) return
    pending.current = true
    setBusy(true)
    setError('')
    try {
      const response = await polishDescription({ config_id: Number(configId), title, description })
      if (!mounted.current) return
      if (!response.success) {
        setError(response.message || '未生成润色结果，请重试')
        return
      }
      const copy = response.data
      if (!isPolishedCopyPreview(copy)) {
        setError('模型返回的标题或正文为空、格式不正确；原文与当前预览未修改')
        return
      }
      setResult(copy)
    } catch (reason) {
      if (mounted.current) setError(getApiErrorMessage(reason, '润色失败，请重试；原文未修改'))
    } finally {
      pending.current = false
      if (mounted.current) setBusy(false)
    }
  }

  return createPortal(
    <div className="modal-overlay z-[70]" role="dialog" aria-modal="true" aria-labelledby={headingId}>
      <div className="modal-content max-w-4xl max-h-[90vh] flex flex-col">
        <div className="modal-header flex-shrink-0">
          <h2 id={headingId} className="modal-title flex items-center gap-2"><Sparkles className="h-4 w-4 text-blue-500" />AI润色</h2>
          <button type="button" className="modal-close" aria-label="关闭AI润色" onClick={onClose} disabled={busy}><X className="h-5 w-5" /></button>
        </div>
        <div className="modal-body overflow-y-auto space-y-4">
          <p className="text-sm text-slate-500">将标题和正文作为完整文案一起优化、去重。生成后可直接修改右侧标题和正文，核对后一起采用；不自动保存或发布。</p>
          <div className="flex flex-wrap items-end gap-3">
            <div className="input-group flex-1 min-w-[220px]">
              <label htmlFor={`${headingId}-config`} className="input-label">润色模型配置</label>
              <select id={`${headingId}-config`} className="input-ios" value={configId} disabled={loading || busy} onChange={event => { setConfigId(event.target.value); setResult(null); setError('') }}>
                {!configs.length && <option value="">{loading ? '正在加载配置…' : '暂无AI配置'}</option>}
                {configs.map(config => <option key={config.id} value={config.id}>{config.name} · {config.text_model}</option>)}
              </select>
            </div>
            <button type="button" className="btn-ios-secondary" disabled={busy || loading} onClick={() => setReload(current => current + 1)}>刷新配置</button>
            <button type="button" className="btn-ios-primary" disabled={loading || busy || !configId || sourceChanged} onClick={generate}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{busy ? '正在润色…' : result ? '重新润色' : '开始润色'}
            </button>
          </div>
          {!loading && !configs.length && <p className="text-sm text-amber-600">请先到素材库 → AI铺货 → 配置管理添加模型，保存后点击“刷新配置”。</p>}
          {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300">{error}</p>}
          {sourceChanged && <p role="alert" className="text-sm text-amber-600">原表单内容已变化，请关闭后重新打开润色，避免覆盖新的内容。</p>}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-3">
              <h3 className="text-sm font-semibold leading-5 text-slate-700 dark:text-slate-200">原文</h3>
              <div className="input-group"><label className="input-label flex items-center justify-between gap-2">原标题 <span className="text-xs text-slate-400">{title.length}/30</span></label><textarea aria-label="润色原标题" rows={2} className="input-ios h-16 resize-none" readOnly value={title} /></div>
              <div className="input-group"><label className="input-label flex items-center justify-between gap-2">原正文 <span className="text-xs text-slate-400">{description.length}/1500</span></label><textarea aria-label="润色原文" className="input-ios h-64 resize-none" rows={10} readOnly value={description} /></div>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-semibold leading-5 text-slate-700 dark:text-slate-200">润色预览 <span className="text-xs font-normal text-slate-400">可直接修改</span></h3>
              <div className="input-group"><label className="input-label flex items-center justify-between gap-2">新标题 <span className={`text-xs ${(result?.title.length ?? 0) > 30 ? 'text-red-600' : 'text-slate-400'}`}>{result?.title.length ?? 0}/30</span></label><textarea aria-label="润色新标题" rows={2} className="input-ios h-16 resize-none" disabled={!result || busy} value={result?.title ?? ''} onChange={event => setResult(current => current ? { ...current, title: event.target.value } : null)} placeholder="生成后可修改商品标题" /></div>
              <div className="input-group"><label className="input-label flex items-center justify-between gap-2">新正文 <span className={`text-xs ${(result?.description.length ?? 0) > 1500 ? 'text-red-600' : 'text-slate-400'}`}>{result?.description.length ?? 0}/1500</span></label><textarea aria-label="润色预览" className="input-ios h-64 resize-none" rows={10} disabled={!result || busy} value={result?.description ?? ''} onChange={event => setResult(current => current ? { ...current, description: event.target.value } : null)} placeholder={busy ? '模型正在整理整套文案，请稍候…' : '生成后可修改正文'} /></div>
              {previewError && <p role="alert" className="text-sm text-red-600">{previewError}，当前输入已保留。</p>}
            </div>
          </div>
        </div>
        <div className="modal-footer flex-shrink-0"><button type="button" className="btn-ios-secondary" disabled={busy} onClick={onClose}>保留原文</button><button type="button" className="btn-ios-primary" disabled={!result || !!previewError || busy || sourceChanged} onClick={() => { if (result && !getPolishedCopyError(result)) onApply(result) }}>采用标题和正文</button></div>
      </div>
    </div>, document.body,
  )
}
