import React, { Suspense, useContext, useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { TopNavbar } from './TopNavbar'
import { TabsBar } from './TabsBar'
import { Toast } from '@/components/common/Toast'
import { PageLoading } from '@/components/common/Loading'
import { PopupAnnouncementModal } from '@/components/common/PopupAnnouncementModal'
import { BootstrapSettingsContext } from '@/components/common/BootstrapSettingsContext'
import { getDefaultLoginBrandingSettings, getSystemSettings, LOGIN_BRANDING_UPDATED_EVENT, normalizeLoginBrandingSettings } from '@/api/settings'
import type { LoginBrandingSettings } from '@/types'
import { useUIStore } from '@/store/uiStore'
import { cn } from '@/utils/cn'

// 懒加载 ChatNew，由 MainLayout 直接管理生命周期以实现 KeepAlive
const ChatNew = React.lazy(() => import('@/pages/chat-new/ChatNew').then(m => ({ default: m.ChatNew })))

export function MainLayout() {
  const { sidebarCollapsed } = useUIStore()
  const bootstrapSettings = useContext(BootstrapSettingsContext)
  // 与原行为一致：首次挂载确定名称初值，后续变更继续通过品牌设置事件更新。
  const [initialSettings] = useState(bootstrapSettings)
  const [systemName, setSystemName] = useState(() => normalizeLoginBrandingSettings(initialSettings)['login.system_name'])
  const location = useLocation()
  const isChatNew = location.pathname === '/online-chat-new'
  // 首次访问后始终挂载，切换菜单时仅隐藏不卸载
  const [chatNewMounted, setChatNewMounted] = useState(false)

  useEffect(() => {
    if (isChatNew && !chatNewMounted) setChatNewMounted(true)
  }, [isChatNew, chatNewMounted])

  useEffect(() => {
    let cancelled = false
    let brandingUpdated = false

    const loadSystemName = async () => {
      try {
        const result = initialSettings ? { success: true, data: initialSettings } : await getSystemSettings()
        if (!cancelled && !brandingUpdated && result.success) {
          setSystemName(normalizeLoginBrandingSettings(result.data)['login.system_name'])
        }
      } catch {
        if (!cancelled && !brandingUpdated) {
          setSystemName(getDefaultLoginBrandingSettings()['login.system_name'])
        }
      }
    }

    loadSystemName()

    const handleBrandingUpdated = (event: Event) => {
      const customEvent = event as CustomEvent<LoginBrandingSettings>
      brandingUpdated = true
      setSystemName(customEvent.detail?.['login.system_name'] || getDefaultLoginBrandingSettings()['login.system_name'])
    }

    window.addEventListener(LOGIN_BRANDING_UPDATED_EVENT, handleBrandingUpdated as EventListener)

    return () => {
      cancelled = true
      window.removeEventListener(LOGIN_BRANDING_UPDATED_EVENT, handleBrandingUpdated as EventListener)
    }
  }, [initialSettings])

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors duration-200">
      <Sidebar systemName={systemName} />
      
      {/* Main content area - 响应侧边栏收缩状态 */}
      <div className={cn(
        'min-h-screen flex flex-col transition-[margin] duration-200',
        // <640px 无边距，>=640px 根据收缩状态调整（16px / 56px）
        'ml-0 sm:ml-16',
        !sidebarCollapsed && 'sm:ml-56'
      )}>
        {/* Fixed header area */}
        <div className="sticky top-0 z-40 bg-slate-50 dark:bg-slate-900">
          {/* Top navbar */}
          <TopNavbar systemName={systemName} />
          
          {/* Tabs bar */}
          <TabsBar />
        </div>
        
        {/* Page content */}
        <main className="flex-1 p-3 sm:p-4 lg:p-6 overflow-x-hidden">
          {/* 其他页面通过 Outlet 渲染，ChatNew 活跃时隐藏 */}
          <div style={{ display: isChatNew ? 'none' : undefined }}>
            <Outlet />
          </div>
          {/* ChatNew KeepAlive：首次访问后始终挂载，切换菜单时仅隐藏 */}
          {chatNewMounted && (
            <div style={{ display: isChatNew ? undefined : 'none' }}>
              <Suspense fallback={<PageLoading />}>
                <ChatNew />
              </Suspense>
            </div>
          )}
        </main>
      </div>

      {/* Toast notifications */}
      <Toast />

      {/* 登录弹窗公告 */}
      <PopupAnnouncementModal />
    </div>
  )
}
