import type { BatchMode } from '@/utils/batchSchedule'

export function BatchScheduleControls({mode, start, minutes, disabled, onMode, onStart, onMinutes}: {
  mode: BatchMode; start: string; minutes: number; disabled: boolean
  onMode: (value: BatchMode) => void; onStart: (value: string) => void; onMinutes: (value: number) => void
}) {
  return <section className="vben-card"><div className="vben-card-header"><h2 className="vben-card-title">发布时间与间隔</h2><span className="text-xs text-slate-500">北京时间（UTC+8）</span></div>
    <div className="vben-card-body space-y-3">
      <div className="flex flex-wrap items-end gap-4">
        <fieldset className="space-y-2" disabled={disabled}><legend className="text-xs text-slate-500">发布方式</legend><div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="radio" name="batch-publish-mode" checked={mode === 'immediate'} onChange={() => onMode('immediate')} />立即开始</label>
          <label className="flex items-center gap-2"><input type="radio" name="batch-publish-mode" checked={mode === 'scheduled'} onChange={() => onMode('scheduled')} />定时发布</label>
        </div></fieldset>
        {mode === 'scheduled' && <label className="flex flex-col gap-1"><span className="text-xs text-slate-500">开始时间（北京时间）</span><input aria-label="定时开始时间（北京时间）" className="input-ios" type="datetime-local" value={start} disabled={disabled} onChange={e => onStart(e.target.value)} /></label>}
        <label className="flex flex-col gap-1"><span className="text-xs text-slate-500">逐件间隔（分钟）</span><input aria-label="逐件间隔（分钟）" className="input-ios w-36" type="number" min="0.5" max="1440" step="0.5" value={Number.isFinite(minutes) ? minutes : ''} disabled={disabled} onChange={e => onMinutes(e.target.value ? Number(e.target.value) : NaN)} /></label>
      </div>
      <p className="text-xs text-slate-500">每件处理结束后再等待所设间隔；最低30秒，默认5分钟。到点后约10秒扫描一次，实际执行时间受排队及平台响应影响。</p>
      <p className="text-xs text-slate-500">任务使用提交时确认的素材内容，后续修改不会覆盖任务。关闭网页不影响执行，服务器需保持运行。</p>
    </div>
  </section>
}
