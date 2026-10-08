import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Header } from './Header'
import { Sidebar } from './Sidebar'
import { Footer } from './Footer'
import { SidebarContext } from '@/contexts/SidebarContext'

export function MainLayout() {
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 768)

  return (
    <SidebarContext.Provider value={{ collapsed, setCollapsed }}>
      <div className="flex h-screen flex-col bg-gradient-brand">
        <a href="#main-content" className="sr-only focus:not-sr-only focus:p-2">Skip to content</a>
        <Header />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 overflow-y-auto p-3 md:p-6">
            <Outlet />
          </main>
        </div>
        <Footer />
      </div>
    </SidebarContext.Provider>
  )
}
