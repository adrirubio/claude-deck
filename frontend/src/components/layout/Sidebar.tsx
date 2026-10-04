import { NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, ClipboardList, FolderGit2, UsersRound, MonitorPlay, Settings, Mail, FolderOpen, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSidebar } from '@/contexts/SidebarContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import { ProjectSwitcher } from '@/features/projects/ProjectSwitcher'
import type { AgentProviderId } from '@/types/providers'
const entries = [
  ['Overview', '/', LayoutDashboard], ['Work', '/work', ClipboardList], ['Repositories', '/repositories', FolderGit2], ['Teams', '/teams', UsersRound], ['Live sessions', '/agent-bridge', MonitorPlay], ['Harnesses', '/harnesses', Settings], ['Agent Mail', '/agent-mail', Mail], ['Local projects', '/projects', FolderOpen],
] as const
export function Sidebar() {
  const { collapsed, setCollapsed } = useSidebar()
  const location = useLocation()
  const { providers, selectedProviderId, setSelectedProviderId } = useProviderContext()
  const native = location.pathname.startsWith('/harnesses') || /^\/(config|mcp|plugins|commands|hooks|permissions|agents|skills|memory|backup|output-styles|statusline|sessions|plans|context|usage)(\/|$)/.test(location.pathname)
  return <aside className={cn('flex shrink-0 flex-col border-r bg-background w-14 md:relative', collapsed ? 'md:w-14' : 'md:w-60')}>
    {native && !collapsed && <div className="hidden md:block space-y-3 border-b py-3"><ProjectSwitcher /><label className="grid gap-1 px-3 text-sm">Saved native harness preference<select className="rounded border bg-background p-2" value={selectedProviderId} onChange={event => setSelectedProviderId(event.target.value as AgentProviderId)}>{providers.map(p => <option key={p.id} value={p.id}>{p.display_name}</option>)}</select></label></div>}
    <nav aria-label="Main navigation" className="flex-1 space-y-1 overflow-y-auto p-2">{entries.map(([name, href, Icon]) => <NavLink key={href} title={name} aria-label={name} to={href} end={href === '/'} className={({ isActive }) => cn('flex items-center gap-2 rounded p-2 text-sm focus-visible:outline focus-visible:outline-2', isActive ? 'bg-primary text-primary-foreground' : 'hover:bg-accent')}><Icon className="h-4 w-4 shrink-0" />{!collapsed && <span className="hidden md:inline">{name}</span>}</NavLink>)}</nav>
    <button className="hidden md:flex justify-center border-t p-3" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}</button>
  </aside>
}
