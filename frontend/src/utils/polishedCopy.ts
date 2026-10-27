/** 判断结果是否可供编辑；字数、换行问题交给采用前校验，不截断结果。 */
export function isPolishedCopyPreview(copy: unknown): copy is { title: string; description: string } {
  if (!copy || typeof copy !== 'object') return false
  const { title, description } = copy as { title?: unknown; description?: unknown }
  return typeof title === 'string' && !!title.trim() && typeof description === 'string' && !!description.trim()
}

/** 生成结果和人工微调共用的采用前校验。 */
export function getPolishedCopyError(copy: unknown): string {
  if (!copy || typeof copy !== 'object') return '请先生成润色预览'
  const { title, description } = copy as { title?: unknown; description?: unknown }
  if (typeof title !== 'string' || !title.trim()) return '请填写新标题'
  if (/[\r\n]/.test(title)) return '新标题不能包含换行'
  if (title.length > 30) return '新标题超过30字，请精简后采用'
  if (typeof description !== 'string' || !description.trim()) return '请填写新正文'
  if (description.length > 1500) return '新正文超过1500字，请精简后采用'
  return ''
}
