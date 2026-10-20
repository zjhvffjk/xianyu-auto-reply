/**
 * 当前店铺状态 store（卡券管理页「店铺切换」用）
 *
 * 功能：
 * 1. 记录用户在卡券管理中选中的当前店铺（对应 xy_accounts.account_id）
 * 2. 选择持久化到 localStorage，刷新页面不丢失；按用户隔离的收敛由
 *    ShopSwitcher 负责（当前账号不在本人账号列表时自动清空）
 * 3. 仅在卡券管理的店铺维设置内生效，不影响其他页面各自的账号选择
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

interface ShopState {
  /** 当前店铺账号ID（xy_accounts.account_id），null 表示未选择 */
  currentAccountId: string | null
  /** 当前店铺显示名（备注/用户名），用于设置区标题展示 */
  currentAccountLabel: string | null
  /** 设置当前店铺；传 null 表示清空选择 */
  setCurrentAccount: (accountId: string | null, label?: string | null) => void
}

export const useShopStore = create<ShopState>()(
  persist(
    (set) => ({
      currentAccountId: null,
      currentAccountLabel: null,

      setCurrentAccount: (accountId, label) => {
        set({ currentAccountId: accountId, currentAccountLabel: accountId ? (label ?? null) : null })
      },
    }),
    {
      name: 'shop-storage',
      storage: createJSONStorage(() => localStorage),
      // 只持久化当前店铺选择
      partialize: (state) => ({
        currentAccountId: state.currentAccountId,
        currentAccountLabel: state.currentAccountLabel,
      }),
    }
  )
)
