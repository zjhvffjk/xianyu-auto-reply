import { useEffect, useRef, useState } from 'react'
import { getWaybillPlatformConfig, saveWaybillPlatformConfig, type WaybillPlatformConfig } from '@/api/waybills'
import { getApiErrorMessage } from '@/utils/request'

/** 管理员统一应用配置。店铺授权与凭据保存分别显示。 */
export function WaybillPlatformSettings({ onSaved }: { onSaved: () => void }) {
  const [config, setConfig] = useState<WaybillPlatformConfig | null>(null)
  const [appKey, setAppKey] = useState('')
  const [secret, setSecret] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [callbackCopied, setCallbackCopied] = useState(false)
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    let cancelled = false
    void getWaybillPlatformConfig().then(result => {
      if (!cancelled) { setConfig(result.data); setAppKey(result.data.app_key) }
    }).catch(e => { if (!cancelled) setError(getApiErrorMessage(e, '读取平台配置失败')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true; mounted.current = false }
  }, [])

  const save = async () => {
    if (saving) return
    setSaving(true); setError(''); setMessage('')
    try {
      const result = await saveWaybillPlatformConfig({ app_key: appKey.trim(), ...(secret ? { app_secret: secret } : {}) })
      if (!mounted.current) return
      setConfig(result.data); setAppKey(result.data.app_key); setSecret('')
      setMessage('平台凭据已加密保存，可在下方准备店铺登录授权；电子面单和系统内打印仍需联调。')
      onSaved()
    } catch (e) {
      if (mounted.current) setError(getApiErrorMessage(e, '保存平台配置失败'))
    } finally { if (mounted.current) setSaving(false) }
  }

  return <section className="rounded-lg border border-slate-200 p-4 space-y-4" aria-label="管理员平台应用配置">
    <div><h4 className="text-sm font-medium">平台统一应用 · 管理员</h4>
      <p className="text-xs text-slate-500 mt-2">填写平台申请的服务商应用凭据，统一供后续商家授权使用。保存配置不会将任何店铺标记为已授权。</p></div>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    {message && <p role="status" className="text-sm text-green-700">{message}</p>}
    <div className="space-y-2 text-xs text-slate-500"><p>官方店铺授权回调地址（发货信息回调配置）：</p>
      <code className="block break-all rounded bg-slate-50 p-2 dark:bg-slate-800">{window.location.origin}/api/v1/waybills/provider/callback</code>
      <button className="text-blue-600" onClick={() => void navigator.clipboard.writeText(`${window.location.origin}/api/v1/waybills/provider/callback`).then(() => setCallbackCopied(true)).catch(() => setError('复制失败，请手动复制回调地址'))}>{callbackCopied ? '已复制回调地址' : '复制回调地址'}</button>
      <p>正式联调请使用公网 HTTPS 域名；127.0.0.1 开发地址无法接收服务商回调。本轮回调只确认店铺登录，发货结果回传尚待接入。</p>
    </div>
    {loading ? <p className="text-sm text-slate-500">正在读取平台配置…</p> : <>
      <div className="grid sm:grid-cols-2 gap-4">
        <label className="input-group"><span className="input-label">平台 AppKey</span><input className="input-ios" autoComplete="off" value={appKey} disabled={saving || !config} onChange={e => setAppKey(e.target.value)} placeholder="服务商应用审核后获取" /></label>
        <label className="input-group"><span className="input-label">平台 AppSecret</span><input className="input-ios" type="password" autoComplete="new-password" value={secret} disabled={saving || !config} onChange={e => setSecret(e.target.value)} placeholder={config?.has_secret ? '已加密保存，留空保留原密钥' : '填写服务商应用密钥'} /></label>
      </div>
      <button className="btn-ios-primary" disabled={saving || !config || !appKey.trim() || ((!config.has_secret || appKey.trim() !== config.app_key) && !secret.trim())} onClick={() => void save()}>{saving ? '正在保存…' : '保存平台应用'}</button>
    </>}
  </section>
}
