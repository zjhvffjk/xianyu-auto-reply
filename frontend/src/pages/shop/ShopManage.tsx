import { getAccountName } from '@/utils/accountLabel'
import { useAuthStore } from '@/store/authStore'
/**
 * 店铺发货设置（已并入「卡券管理」页面，不再单独占一级菜单）
 *
 * 导出两个组件：
 * 1. ShopSwitcher：店铺切换标识（一个闲鱼账号 = 一个店铺）。
 *    外观是一枚紧凑的「店铺」胶囊按钮，点击展开账号列表直接选择，
 *    不占额外一行、不带独立下拉框/状态徽标；选择记入 shopStore（localStorage 持久化）
 * 2. ShopDeliverySettings：当前店铺的宝贝发货设置
 *    （商品列表 / 添加商品 / 单独设置 / 批量操作），随店铺切换同步换源
 *
 * 安全：账号列表经 /api/v1/cookies/details/paginated 拉取，
 * 后端按 token 限定返回范围（普通用户仅本人账号，管理员全量）；
 * 当前选择的账号若不在列表中（如切换用户后残留），自动清空选择。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Package, RefreshCw, Loader2, ChevronDown, Check } from 'lucide-react'
import { getAccountDetails } from '@/api/accounts'
import { useShopStore } from '@/store/shopStore'
import { useUIStore } from '@/store/uiStore'
import { ShopItemSettings } from './ShopItemSettings'
import type { AccountDetail } from '@/types'

/** 直接沿用统一的账号身份显示规则。 */
const getAccountLabel = getAccountName

/** 账号状态文案 */
function getAccountStatusText(account: AccountDetail): string {
  if (!account.enabled) return '已禁用'
  return account.online === undefined ? '状态未知' : account.online ? '在线' : '离线'
}

/** 状态圆点颜色：禁用红 / 在线绿 / 离线灰 */
function getStatusDotClass(account: AccountDetail): string {
  if (!account.enabled) return 'bg-red-500'
  return account.online ? 'bg-green-500' : 'bg-slate-400'
}

/**
 * 店铺切换标识（页头标题旁）
 *
 * 点击胶囊直接展开账号列表选择，不再渲染独立下拉框、状态徽标与刷新按钮。
 */
export function ShopSwitcher() {
  const userId = useAuthStore(state => state.user?.user_id)
  const { addToast } = useUIStore()
  const { currentAccountId, currentAccountLabel, setCurrentAccount } = useShopStore()
  const [accounts, setAccounts] = useState<AccountDetail[]>([])
  const [loadingAccounts, setLoadingAccounts] = useState(true)
  const [accountsLoaded, setAccountsLoaded] = useState(false)
  const [loadedUserId, setLoadedUserId] = useState<number | undefined>()
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement | null>(null)
  const requestVersion = useRef(0)

  // 加载本人可见账号列表（分页聚合拿全量）
  const loadAccounts = useCallback(async () => {
    const version = ++requestVersion.current
    setLoadingAccounts(true)
    try {
      const collected = await getAccountDetails()
      if (version !== requestVersion.current) return
      setAccounts(collected)
      setAccountsLoaded(true)
      setLoadedUserId(userId)
    } catch {
      if (version !== requestVersion.current) return
      addToast({ type: 'error', message: '账号列表加载失败' })
    } finally {
      if (version === requestVersion.current) setLoadingAccounts(false)
    }
  }, [addToast, userId])

  useEffect(() => {
    setAccounts([])
    setAccountsLoaded(false)
    loadAccounts()
    return () => { requestVersion.current++ }
  }, [loadAccounts])

  // 收敛校验：当前选择不在账号列表中（含登出后残留）→ 清空；在列表里则刷新缓存的显示名
  useEffect(() => {
    if (loadingAccounts || !accountsLoaded || loadedUserId !== userId) return
    if (!currentAccountId) return
    const found = accounts.find((a) => a.id === currentAccountId)
    if (!found) {
      setCurrentAccount(null)
      return
    }
    const freshLabel = getAccountLabel(found)
    if (freshLabel !== currentAccountLabel) setCurrentAccount(currentAccountId, freshLabel)
  }, [accounts, currentAccountId, currentAccountLabel, loadingAccounts, accountsLoaded, loadedUserId, userId, setCurrentAccount])

  // 点击外部 / Esc 关闭下拉
  useEffect(() => {
    if (!open) return
    const handleDocClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleDocClick)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleDocClick)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  const currentAccount = useMemo(
    () => accounts.find((a) => a.id === currentAccountId) || null,
    [accounts, currentAccountId]
  )

  // 切换店铺：同步记下店铺名，供下方设置区标题使用
  const handleSelectAccount = (accountId: string) => {
    const target = accounts.find((a) => a.id === accountId) || null
    setCurrentAccount(accountId, target ? getAccountLabel(target) : null)
    setOpen(false)
  }

  const triggerLabel = currentAccountId
    ? (currentAccountLabel || currentAccount?.note || currentAccountId)
    : '店铺'

  return (
    <div className="relative" ref={boxRef}>
      {/* 明确展示当前店铺，避免仅靠图标和悬停提示辨认。 */}
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        title={currentAccountId ? `当前店铺：${triggerLabel}（点击切换）` : '点击选择店铺'}
        aria-label="切换店铺"
        aria-expanded={open}
        className={`inline-flex h-10 max-w-full items-center gap-2 whitespace-nowrap rounded-lg border py-1 pl-1.5 pr-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${
          currentAccountId
            ? 'border-blue-200 bg-white hover:border-blue-300 hover:bg-blue-50 dark:border-blue-800 dark:bg-slate-800 dark:hover:bg-blue-950'
            : 'border-slate-200 bg-white hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700'
        }`}
      >
        <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600 dark:bg-blue-900/40 dark:text-blue-300">
          {loadingAccounts ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M5 12.5v6.8A2.7 2.7 0 0 0 7.7 22h8.6a2.7 2.7 0 0 0 2.7-2.7v-6.8" />
              <path d="M7.5 3h9a4 4 0 0 1 3.8 2.7l1.2 3.6a3.3 3.3 0 0 1-6 2.6 4 4 0 0 1-7 0 3.3 3.3 0 0 1-6-2.6l1.2-3.6A4 4 0 0 1 7.5 3Z" />
            </svg>
          )}
        </span>
        <span className="max-w-[260px] truncate text-sm font-medium text-slate-700 dark:text-slate-200">
          {currentAccountId ? triggerLabel : '选择店铺'}
        </span>
        <ChevronDown className={`h-3.5 w-3.5 flex-shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-30 mt-1 w-64 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-800">
          {/* 当前账号仅在展开后显示 */}
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-700">
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">选择店铺</span>
            {currentAccountId && (
              <span className="max-w-[10rem] truncate text-xs text-blue-600 dark:text-blue-400">
                当前：{triggerLabel}
              </span>
            )}
          </div>
          <div className="max-h-72 overflow-auto py-1">
            {loadingAccounts ? (
              <div className="flex items-center gap-2 px-3 py-3 text-sm text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载账号列表...
              </div>
            ) : accounts.length === 0 ? (
              <div className="px-3 py-3 text-sm text-amber-600 dark:text-amber-400">
                暂无可用账号，请先到「账号管理」添加并登录闲鱼账号。
              </div>
            ) : (
              accounts.map((account) => {
                const active = account.id === currentAccountId
                return (
                  <button
                    key={account.id}
                    type="button"
                    disabled={!account.enabled}
                    onClick={() => handleSelectAccount(account.id)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors ${
                      account.enabled
                        ? 'hover:bg-slate-50 dark:hover:bg-slate-700'
                        : 'cursor-not-allowed opacity-50'
                    } ${active ? 'bg-blue-50 dark:bg-blue-900/30' : ''}`}
                  >
                    <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${getStatusDotClass(account)}`} />
                    <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
                      {getAccountLabel(account)}
                    </span>
                    <span className="flex-shrink-0 text-xs text-slate-400">
                      {getAccountStatusText(account)}
                    </span>
                    {active && <Check className="h-4 w-4 flex-shrink-0 text-blue-600 dark:text-blue-400" />}
                  </button>
                )
              })
            )}
          </div>
          <div className="flex items-center justify-between border-t border-slate-100 px-2 py-1.5 dark:border-slate-700">
            <span className="text-xs text-slate-400">共 {accounts.length} 个店铺</span>
            <button
              type="button"
              onClick={loadAccounts}
              disabled={loadingAccounts}
              className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-slate-500 transition-colors hover:text-blue-600 disabled:opacity-50 dark:text-slate-400"
            >
              {loadingAccounts ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              刷新
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * 当前店铺的宝贝发货设置
 *
 * 未选店铺时给出引导；选中后渲染该店铺的商品列表与发货配置。
 */
export function ShopDeliverySettings() {
  const { currentAccountId, currentAccountLabel } = useShopStore()

  if (!currentAccountId) {
    return (
      <div className="vben-card">
        <div className="vben-card-header">
          <h2 className="vben-card-title">
            <Package className="w-4 h-4" />
            本店宝贝发货设置
          </h2>
        </div>
        <div className="vben-card-body text-sm text-slate-400">
          请点击标题旁的店铺图标选择店铺，选中后可在这里为每个商品链接设置发货内容（关联卡券）与使用说明。
        </div>
      </div>
    )
  }

  return (
    <div className="vben-card">
      <div className="vben-card-body">
        <ShopItemSettings
          key={currentAccountId}
          accountId={currentAccountId}
          accountLabel={currentAccountLabel || currentAccountId}
        />
      </div>
    </div>
  )
}

export default ShopSwitcher
