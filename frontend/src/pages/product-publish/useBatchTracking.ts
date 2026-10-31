import { useCallback, useEffect, useRef, useState } from 'react'
import { getBatchStatus, type BatchStatusResponse } from '@/api/productPublish'
import { subscribePublishHistoryCleared } from '@/utils/publishHistoryEvents'

/** 查询失败保留请求号；串行轮询，失联不视为完成，不自动重新提交。 */
export function useBatchTracking(userId: number | undefined) {
  const key = `batch-publish:${userId ?? 'anonymous'}`
  const [batchId, setBatchId] = useState<string | null>(null)
  const [progress, setProgress] = useState<BatchStatusResponse['data'] | null>(null)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [restoring, setRestoring] = useState(true)
  const [revision, setRevision] = useState(0)
  const generation = useRef(0)
  const [storageError, setStorageError] = useState('')
  useEffect(() => subscribePublishHistoryCleared(userId, () => setRevision(v => v + 1)), [userId])
  useEffect(() => {
    generation.current++
    setProgress(null); setError(''); setRestoring(true)
    try { setBatchId(sessionStorage.getItem(key)); setStorageError('') }
    catch { setStorageError('浏览器无法保存任务跟踪，请允许会话存储后再发布') }
    setRestoring(false)
    return () => { generation.current++ }
  }, [key])
  const remember = useCallback((id: string) => {
    try { sessionStorage.setItem(key, id) }
    catch { setStorageError('浏览器无法保存任务跟踪，请允许会话存储后再发布'); throw new Error('storage unavailable') }
    setProgress(null); setError(''); setBatchId(id)
  }, [key])
  const forget = useCallback(() => {
    sessionStorage.removeItem(key)
    generation.current++
    setBatchId(null); setProgress(null); setError(''); setChecking(false)
  }, [key])
  useEffect(() => {
    if (!batchId || restoring) return
    const version = ++generation.current
    let timeout: ReturnType<typeof setTimeout> | undefined
    const poll = async () => {
      setChecking(true)
      let repeat = false
      try {
        const res = await getBatchStatus(batchId)
        if (version !== generation.current) return
        if (!res.success) setError(res.message || '尚未查到任务，请核查发布日志，勿重复提交')
        else if (res.data.history_cleared && res.data.finished) {
          sessionStorage.removeItem(key)
          setBatchId(null); setProgress(null); setError('')
        }
        else {
          setProgress(res.data); setError('')
          repeat = !res.data.finished && !res.data.tracking_lost
        }
      } catch {
        if (version !== generation.current) return
        setError('进度查询失败，请恢复查询。任务可能仍在执行，勿重复提交。')
      } finally {
        if (version === generation.current) {
          setChecking(false)
          if (repeat) timeout = setTimeout(poll, 3000)
        }
      }
    }
    void poll()
    return () => { generation.current++; clearTimeout(timeout) }
  }, [batchId, restoring, revision])
  return { batchId, progress, error, checking, restoring, storageError, remember, forget,
    refresh: () => setRevision(r => r + 1), locked: restoring || Boolean(batchId && !progress?.finished && !progress?.mode) }
}
