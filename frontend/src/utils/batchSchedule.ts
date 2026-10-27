export type BatchMode = 'immediate' | 'scheduled'

/** datetime-local 显示北京时间，不依赖电脑时区。 */
export function defaultBeijingStart(now = new Date()): string {
  return new Date(now.getTime() + 8 * 3600000 + 5 * 60000).toISOString().slice(0, 16)
}

export function batchSchedulePayload(mode: BatchMode, start: string, minutes: number, now = new Date()) {
  if (!Number.isFinite(minutes) || minutes < 0.5 || minutes > 1440) throw new Error('逐件间隔须为0.5～1440分钟')
  const interval_seconds = Math.round(minutes * 60)
  if (mode === 'immediate') return {mode, interval_seconds}
  const date = new Date(`${start}:00+08:00`)
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(start) || !Number.isFinite(date.getTime())
      || new Date(date.getTime() + 8 * 3600000).toISOString().slice(0, 16) !== start) throw new Error('请选择有效的北京时间')
  if (date.getTime() <= now.getTime()) throw new Error('定时开始时间必须晚于当前北京时间')
  return {mode, interval_seconds, start_at: `${start}:00+08:00`}
}

export const batchStateLabels: Record<string, string> = {
  waiting: '等待执行', preparing: '发布准备中', running: '发布中', cancelling: '正在取消剩余任务',
  completed: '执行结束', cancelled: '已取消', attention: '结果待核查',
}
export function formatBeijingTime(value?: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false}).format(new Date(value))
}
