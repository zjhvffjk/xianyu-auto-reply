import { useCallback } from 'react'
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { useAuthStore } from '@/store/authStore'

interface ShopSelection { accountId: string; label: string | null }
interface ShopSelections {
  selections: Record<string, ShopSelection>
  setSelection: (userId: string, accountId: string | null, label?: string | null) => void
}

/** 只保存店铺ID和展示名；不同登录用户各自记住选择。 */
export const useShopSelections = create<ShopSelections>()(persist(
  (set) => ({
    selections: {},
    setSelection: (userId, accountId, label) => set(state => {
      const selections = { ...state.selections }
      if (accountId) selections[userId] = { accountId, label: label ?? null }
      else delete selections[userId]
      return { selections }
    }),
  }),
  {
    name: 'shop-selections-v2',
    storage: createJSONStorage(() => localStorage),
    partialize: state => ({ selections: state.selections }),
  },
))

export function useShopStore() {
  const userId = useAuthStore(state => state.user?.user_id)
  const userKey = userId == null ? null : String(userId)
  const selection = useShopSelections(state => userKey ? state.selections[userKey] : undefined)
  const setCurrentAccount = useCallback((accountId: string | null, label?: string | null) => {
    if (userKey) useShopSelections.getState().setSelection(userKey, accountId, label)
  }, [userKey])
  return {
    currentAccountId: selection?.accountId ?? null,
    currentAccountLabel: selection?.label ?? null,
    setCurrentAccount,
  }
}
