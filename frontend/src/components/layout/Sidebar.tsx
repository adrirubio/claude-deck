import { NavLink } from 'react-router-dom'
import { LayoutDashboard, ClipboardList, FolderGit2, UsersRound, MonitorPlay, Settings, Mail, ScrollText, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSidebar } from '@/contexts/SidebarContext'
const entries = [
  ['Overview', '/', LayoutDashboard], ['Work', '/work', ClipboardList], ['Repositories', '/repositories', FolderGit2], ['Teams', '/teams', UsersRound], ['Live sessions', '/agent-bridge', MonitorPlay], ['Harnesses', '/harnesses', Settings], ['Agent Mail', '/agent-mail', Mail], ['Audit', '/audit', ScrollText],
] as const
export function Sidebar() {
  const { collapsed, setCollapsed } = useSidebar()
  return <aside className={cn('flex shrink-0 flex-col border-r bg-background w-14 md:relative', collapsed ? 'md:w-14' : 'md:w-60')}>
    <nav aria-label="Main navigation" className="flex-1 space-y-1 overflow-y-auto p-2">{entries.map(([name, href, Icon]) => <NavLink key={href} title={name} aria-label={name} to={href} end={href === '/'} className={({ isActive }) => cn('flex min-h-11 items-center gap-2 rounded border-l-4 p-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current focus-visible:ring-inset', isActive ? 'border-primary bg-accent font-semibold text-foreground' : 'border-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground')}><Icon className="h-4 w-4 shrink-0" />{!collapsed && <span className="hidden md:inline">{name}</span>}</NavLink>)}</nav>
    <button className="hidden min-h-11 md:flex justify-center border-t p-3 transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current focus-visible:ring-inset" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}</button>
  </aside>
}
