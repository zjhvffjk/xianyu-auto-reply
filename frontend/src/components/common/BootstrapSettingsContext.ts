import { createContext } from 'react'
import type { SystemSettings } from '@/types'

// 只共享本次受保护页面初始化结果，不持久化、不跨登录会话缓存。
export const BootstrapSettingsContext = createContext<SystemSettings | null>(null)
