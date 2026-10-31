/** 通知已打开的发布页面刷新历史；不改变发布任务状态。 */
export const PUBLISH_HISTORY_CLEARED = 'publish-history-cleared'

export function notifyPublishHistoryCleared(userId: number | undefined) {
  window.dispatchEvent(new Event(PUBLISH_HISTORY_CLEARED))
  try { localStorage.setItem(`${PUBLISH_HISTORY_CLEARED}:${userId}`, String(Date.now())) } catch { /* 服务器已保存，刷新页面仍生效。 */ }
}

export function subscribePublishHistoryCleared(userId: number | undefined, refresh: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key === `${PUBLISH_HISTORY_CLEARED}:${userId}`) refresh()
  }
  window.addEventListener(PUBLISH_HISTORY_CLEARED, refresh)
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(PUBLISH_HISTORY_CLEARED, refresh)
    window.removeEventListener('storage', onStorage)
  }
}
