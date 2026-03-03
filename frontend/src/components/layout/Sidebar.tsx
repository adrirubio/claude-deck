import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { ProjectSwitcher } from '@/features/projects/ProjectSwitcher'
import { useSidebar } from '@/contexts/SidebarContext'
import {
  LayoutDashboard,
  Settings,
  Server,
  Terminal,
  Package,
  Webhook,
  Shield,
  Bot,
  Sparkles,
  Brain,
  Paintbrush,
  Activity,
  MessageSquare,
  BarChart3,
  FolderOpen,
  Archive,
  Gauge,
  ClipboardList,
  MonitorPlay,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from 'lucide-react'

const navigation: { name: string; href: string; icon: LucideIcon }[] = [
  // Tier 1: Overview & Setup
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Projects', href: '/projects', icon: FolderOpen },
  { name: 'Config', href: '/config', icon: Settings },

  // Tier 2: Core Configuration Sections
  { name: 'MCP Servers', href: '/mcp', icon: Server },
  { name: 'Commands', href: '/commands', icon: Terminal },
  { name: 'Plugins', href: '/plugins', icon: Package },
  { name: 'Hooks', href: '/hooks', icon: Webhook },
  { name: 'Permissions', href: '/permissions', icon: Shield },
  { name: 'Agents', href: '/agents', icon: Bot },
  { name: 'Skills', href: '/skills', icon: Sparkles },
  { name: 'Memory', href: '/memory', icon: Brain },

  // Tier 3: Customization
  { name: 'Output Styles', href: '/output-styles', icon: Paintbrush },
  { name: 'Status Line', href: '/statusline', icon: Activity },

  // Tier 4: Monitoring & Tools
  { name: 'Sessions', href: '/sessions', icon: MessageSquare },
  { name: 'CC Bridge', href: '/cc-bridge', icon: MonitorPlay },
  { name: 'Plans', href: '/plans', icon: ClipboardList },
  { name: 'Context', href: '/context', icon: Gauge },
  { name: 'Usage', href: '/usage', icon: BarChart3 },
  { name: 'Backup', href: '/backup', icon: Archive },
]

export function Sidebar() {
  const { collapsed, setCollapsed } = useSidebar()

  return (
    <aside className={cn(
      'border-r bg-background transition-all duration-200 flex flex-col',
      collapsed ? 'w-14' : 'w-64'
    )}>
      {!collapsed && (
        <div className="py-4 border-b">
          <ProjectSwitcher />
        </div>
      )}
      <nav className={cn(
        'flex flex-col gap-1 flex-1 overflow-y-auto',
        collapsed ? 'p-2' : 'p-4'
      )}>
        {navigation.map((item) => (
          <NavLink
            key={item.href}
            to={item.href}
            end={item.href === '/'}
            title={collapsed ? item.name : undefined}
            className={({ isActive }) =>
              cn(
                'flex items-center rounded-md text-sm font-medium transition-colors',
                collapsed ? 'justify-center p-2' : 'gap-2 px-3 py-2',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-foreground hover:bg-accent hover:text-accent-foreground'
              )
            }
          >
            <item.icon className="h-4 w-4 shrink-0" />
            {!collapsed && item.name}
          </NavLink>
        ))}
      </nav>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex items-center justify-center p-3 border-t text-muted-foreground hover:text-foreground transition-colors"
        title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
      </button>
    </aside>
  )
}
