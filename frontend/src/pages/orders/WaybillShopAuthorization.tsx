import { useEffect, useRef, useState } from 'react'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { getWaybillAuthorization, revokeWaybillAuthorization, startWaybillAuthorization, type WaybillAuthorization } from '@/api/waybills'
import { getApiErrorMessage } from '@/utils/request'
import { ConfirmModal } from '@/components/common/ConfirmModal'

const names: Record<WaybillAuthorization['status'], string> = {
  not_started: '尚未发起', pending: '等待官方回调确认', authorized: '店铺登录已确认',
  expired: '授权请求已过期，请重新发起', revoked: '本地授权已撤销', stale: '平台配置已变化，请重新授权',
}

/** 只记录服务端确认的店铺登录；面单权限和打印结果分别核对。 */
export function WaybillShopAuthorization({ accountId }: { accountId: string }) {
  const [status, setStatus] = useState<WaybillAuthorization | null>(null)
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState('')
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const generation = useRef(0)
  const busy = useRef(false)

  useEffect(() => {
    const current = ++generation.current
    setStatus(null); setUrl(''); setError(''); setLoading(true)
    void getWaybillAuthorization(accountId).then(result => {
      if (current === generation.current) setStatus(result.data)
    }).catch(e => { if (current === generation.current) setError(getApiErrorMessage(e, '读取店铺授权状态失败')) })
      .finally(() => { if (current === generation.current) setLoading(false) })
    return () => { generation.current++ }
  }, [accountId])

  const run = async (name: string, operation: () => Promise<void>) => {
    if (busy.current) return
    const current = generation.current
    busy.current = true; setAction(name); setError('')
    try { await operation() }
    catch (e) { if (current === generation.current) setError(getApiErrorMessage(e, '授权操作未完成，请刷新核对')) }
    finally { busy.current = false; if (current === generation.current) setAction('') }
  }
  const refresh = async () => {
    const current = generation.current
    const result = await getWaybillAuthorization(accountId)
    if (current !== generation.current) return
    setStatus(result.data)
    if (result.data.status !== 'pending') setUrl('')
  }
  const prepare = async () => {
    const current = generation.current
    setUrl('')
    const result = await startWaybillAuthorization(accountId)
    if (current !== generation.current) return
    const link = new URL(result.data.url)
    if (link.protocol !== 'https:' || link.username || link.password || (link.port && link.port !== '443') ||
      !['kuaidizs.cn', 'kdzs.com', 'superboss.cc'].some(domain => link.hostname === domain || link.hostname.endsWith('.' + domain))) {
      throw new Error('官方授权地址未通过校验')
    }
    await refresh()
    if (current === generation.current) setUrl(link.href)
  }
  const revoke = async () => {
    const current = generation.current
    const result = await revokeWaybillAuthorization(accountId)
    if (current !== generation.current) return
    setStatus(result.data); setUrl(''); setConfirmRevoke(false)
  }

  return <section aria-label="店铺登录授权" className="rounded-lg border border-slate-200 p-4 space-y-3 dark:border-slate-700">
    <h4 className="font-medium text-sm">当前店铺授权</h4>
    {loading ? <p className="text-sm text-slate-500">正在读取授权状态…</p> : status && <>
      <p role="status" className={`text-sm ${status.status === 'authorized' ? 'text-emerald-700' : 'text-slate-600'}`}>{names[status.status]}{status.shop_name && ` · ${status.shop_name}`}</p>
      {status.authorized_at && <p className="text-xs text-slate-500">确认时间：{status.authorized_at.replace('T', ' ').slice(0, 19)}</p>}
      <p className="text-xs text-slate-500">进入官方页面完成店铺登录后，点击“刷新授权状态”。只有服务器收到有效回调才会确认；店铺登录不代表电子面单已授权或已打印。</p>
      {!status.platform_configured && <p className="text-xs text-amber-700">平台应用待管理员配置，你无需注册开发者或填写密钥。</p>}
      {status.status === 'pending' && <p className="text-xs text-amber-700">若登录后仍未确认，请管理员核对公网 HTTPS 回调地址。{status.expires_at && `本次请求有效至 ${status.expires_at.replace('T', ' ').slice(0, 19)}。`}</p>}
      <div className="flex flex-wrap gap-2">
        <button className="btn-ios-primary" disabled={!!action || !status.authorization_available} onClick={() => void run('准备授权', prepare)}>{action === '准备授权' ? '正在准备…' : status.status === 'authorized' ? '进入官方店铺' : '准备店铺授权'}</button>
        <button className="btn-ios-secondary" disabled={!!action} onClick={() => void run('刷新授权', refresh)}><RefreshCw className="h-4 w-4" />刷新授权状态</button>
        {['pending', 'authorized', 'expired', 'stale'].includes(status.status) && <button className="btn-ios-secondary" disabled={!!action} onClick={() => setConfirmRevoke(true)}>撤销本地授权</button>}
      </div>
      {url && <a className="inline-flex gap-2 items-center text-sm text-blue-600" href={url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">前往官方确认<ExternalLink className="h-4 w-4" /></a>}
    </>}
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <ConfirmModal isOpen={confirmRevoke} title="撤销本地店铺授权" message="撤销后，本系统将拒绝此店铺旧授权请求的回调。此操作仅解除本地绑定，不会注销快递助手账号。" confirmText="确认撤销" loading={!!action} onConfirm={() => void run('撤销授权', revoke)} onCancel={() => { if (!action) setConfirmRevoke(false) }} />
  </section>
}
