import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { ChevronDown, Loader2, Search, Store } from 'lucide-react'
import type { AccountDetail } from '@/types'
import { getAccountName, getAccountNickname } from '@/utils/accountLabel'

interface Props {
  accounts: AccountDetail[]
  selected: Set<string>
  loading: boolean
  error: string
  disabled: boolean
  onChange: (ids: Set<string>) => void
  onRetry: () => void
}

/** 标题旁的发布目标多选；展示昵称，提交仍沿用原账号ID。 */
export function BatchTargetShopPicker({ accounts, selected, loading, error, disabled, onChange, onRetry }: Props) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [left, setLeft] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const id = useId()
  const selectedAccounts = accounts.filter(account => selected.has(account.id))
  const label = loading ? '正在加载店铺…' : error ? '店铺加载失败'
    : selectedAccounts.length === 1 ? `发布到：${getAccountNickname(selectedAccounts[0])}`
    : selectedAccounts.length > 1 ? `已选 ${selectedAccounts.length} 个店铺` : '选择发布店铺'
  const positionPanel = useCallback(() => {
    const bounds = boxRef.current?.getBoundingClientRect()
    if (!bounds) return
    const width = Math.min(320, window.innerWidth - 32)
    setLeft(Math.max(16, Math.min(bounds.left, window.innerWidth - 16 - width)) - bounds.left)
  }, [])
  useLayoutEffect(() => { if (open) positionPanel() }, [open, label, positionPanel])
  useEffect(() => {
    if (!open) return
    searchRef.current?.focus()
    const onOutside = (event: PointerEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); triggerRef.current?.focus() }
    }
    document.addEventListener('pointerdown', onOutside)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', positionPanel)
    return () => {
      document.removeEventListener('pointerdown', onOutside)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', positionPanel)
    }
  }, [open, positionPanel])
  const keyword = search.trim().toLocaleLowerCase()
  const filtered = accounts.filter(account => `${getAccountName(account)} ${account.id}`.toLocaleLowerCase().includes(keyword))
  return <div ref={boxRef} className="relative min-w-0 max-w-full">
    <button ref={triggerRef} type="button" aria-label="发布目标店铺" aria-describedby={`${id}-summary`}
      aria-expanded={open} aria-haspopup="dialog" aria-controls={open ? id : undefined} disabled={disabled}
      title={selectedAccounts.map(getAccountName).join('、') || '选择一个或多个发布目标店铺'}
      onClick={() => { setSearch(''); setOpen(value => !value) }}
      className="inline-flex h-10 max-w-full items-center gap-2 rounded-lg border border-blue-200 bg-white py-1 pl-1.5 pr-3 text-sm hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 dark:border-blue-800 dark:bg-slate-800 dark:hover:bg-blue-950">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600 dark:bg-blue-900/40 dark:text-blue-300">{loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Store className="h-5 w-5" />}</span>
      <span className="max-w-[220px] truncate font-medium text-slate-700 dark:text-slate-200">{label}</span>
      <ChevronDown className={`h-3.5 w-3.5 shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
    </button>
    <span id={`${id}-summary`} className="sr-only">{label}</span>
    {open && <div id={id} role="dialog" aria-label="选择发布目标店铺" style={{ left }}
      className="absolute top-full z-40 mt-1 w-80 max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <div className="space-y-2 border-b border-slate-100 p-3 dark:border-slate-700"><p className="text-xs font-medium text-slate-500">选择发布目标店铺，可多选</p><div className="relative"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" /><input ref={searchRef} className="input-ios h-9 w-full pl-8 text-sm" placeholder="搜索店铺昵称或账号" value={search} onChange={event => setSearch(event.target.value)} /></div></div>
      <div className="max-h-64 overflow-y-auto p-1">
        {loading ? <p className="px-3 py-4 text-sm text-slate-500">正在加载店铺…</p> : error ? <div role="alert" className="space-y-2 px-3 py-3 text-sm text-red-600"><p>{error}</p><button type="button" disabled={disabled} className="text-blue-600" onClick={onRetry}>重新加载</button></div>
          : filtered.length === 0 ? <p className="px-3 py-4 text-sm text-slate-500">{accounts.length ? '未找到匹配店铺' : '暂无可用店铺，请先添加账号'}</p>
          : filtered.map(account => <label key={account.id} className={`flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 hover:bg-blue-50 dark:hover:bg-slate-700 ${selected.has(account.id) ? 'bg-blue-50 dark:bg-blue-950' : ''}`}>
            <input type="checkbox" aria-label={`发布到 ${getAccountName(account)}`} disabled={disabled} checked={selected.has(account.id)} onChange={() => { const next = new Set(selected); next.has(account.id) ? next.delete(account.id) : next.add(account.id); onChange(next) }} />
            <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-slate-700 dark:text-slate-200">{getAccountNickname(account)}</span><span className="block truncate text-xs text-slate-400">{getAccountName(account)} · {account.id}</span></span>
            <span className="shrink-0 text-xs text-slate-400">{account.online === true ? '在线' : account.online === false ? '离线' : '状态待检查'}</span>
          </label>)}
      </div>
      <div className="flex items-center justify-between gap-2 border-t border-slate-100 px-3 py-2 text-xs text-slate-500 dark:border-slate-700"><span>已选 {selected.size} 个店铺</span><button type="button" className="text-blue-600 disabled:opacity-40" disabled={disabled || !selected.size} onClick={() => onChange(new Set())}>清空选择</button></div>
      <p className="px-3 pb-3 text-xs text-slate-400">每个目标店铺发布全部已选素材。手动发布不受自动任务开关限制，发布能力以平台执行结果为准。</p>
    </div>}
  </div>
}
