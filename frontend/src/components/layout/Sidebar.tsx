import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { ProjectSwitcher } from '@/features/projects/ProjectSwitcher'
import { useSidebar } from '@/contexts/SidebarContext'
import { useProviderContext } from '@/contexts/ProviderContext'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { AgentProviderId } from '@/types/providers'
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
  Radio,
  PanelLeftClose,
  PanelLeftOpen,
  type LucideIcon,
} from 'lucide-react'

type NavItem = {
  name: string
  href: string
  icon: LucideIcon
  providerSupport?: AgentProviderId[]
}

type NavGroup = {
  name: string
  items: NavItem[]
}

const CLAUDE_ONLY: AgentProviderId[] = ['claude-code']
const ALL_PROVIDERS: AgentProviderId[] = ['claude-code', 'codex-cli']

const navigation: NavGroup[] = [
  {
    name: 'Primary',
    items: [
      { name: 'Dashboard', href: '/', icon: LayoutDashboard, providerSupport: ALL_PROVIDERS },
      { name: 'Projects', href: '/projects', icon: FolderOpen, providerSupport: ALL_PROVIDERS },
      { name: 'Agent Bridge', href: '/agent-bridge', icon: MonitorPlay, providerSupport: ALL_PROVIDERS },
      { name: 'Sessions', href: '/sessions', icon: MessageSquare, providerSupport: ALL_PROVIDERS },
    ],
  },
  {
    name: 'Configuration',
    items: [
      { name: 'Config', href: '/config', icon: Settings, providerSupport: ALL_PROVIDERS },
      { name: 'MCP Servers', href: '/mcp', icon: Server, providerSupport: CLAUDE_ONLY },
      { name: 'Plugins', href: '/plugins', icon: Package, providerSupport: CLAUDE_ONLY },
      { name: 'Permissions / Trust', href: '/permissions', icon: Shield, providerSupport: CLAUDE_ONLY },
      { name: 'Commands', href: '/commands', icon: Terminal, providerSupport: CLAUDE_ONLY },
      { name: 'Hooks', href: '/hooks', icon: Webhook, providerSupport: CLAUDE_ONLY },
      { name: 'Agents', href: '/agents', icon: Bot, providerSupport: CLAUDE_ONLY },
      { name: 'Skills', href: '/skills', icon: Sparkles, providerSupport: CLAUDE_ONLY },
      { name: 'Memory', href: '/memory', icon: Brain, providerSupport: CLAUDE_ONLY },
      { name: 'Output Styles', href: '/output-styles', icon: Paintbrush, providerSupport: CLAUDE_ONLY },
      { name: 'Status Line', href: '/statusline', icon: Activity, providerSupport: CLAUDE_ONLY },
    ],
  },
  {
    name: 'Operations',
    items: [
      { name: 'Presence', href: '/presence', icon: Radio, providerSupport: ALL_PROVIDERS },
      { name: 'Plans', href: '/plans', icon: ClipboardList, providerSupport: ALL_PROVIDERS },
      { name: 'Context', href: '/context', icon: Gauge, providerSupport: CLAUDE_ONLY },
      { name: 'Usage', href: '/usage', icon: BarChart3, providerSupport: CLAUDE_ONLY },
      { name: 'Backup', href: '/backup', icon: Archive, providerSupport: ALL_PROVIDERS },
    ],
  },
]

function supportsProvider(item: NavItem, providerId: AgentProviderId) {
  return !item.providerSupport || item.providerSupport.includes(providerId)
}

export function Sidebar() {
  const { collapsed, setCollapsed } = useSidebar()
  const { providers, selectedProviderId, setSelectedProviderId } = useProviderContext()
  const visibleGroups = navigation
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => supportsProvider(item, selectedProviderId)),
    }))
    .filter((group) => group.items.length > 0)

  return (
    <aside className={cn(
      'border-r bg-background transition-all duration-200 flex flex-col',
      collapsed ? 'w-14' : 'w-64'
    )}>
      {!collapsed && (
        <div className="py-4 border-b space-y-3">
          <ProjectSwitcher />
          <div className="px-4 space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Agent Provider</p>
            <Select value={selectedProviderId} onValueChange={(value) => setSelectedProviderId(value as AgentProviderId)}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {providers.map((provider) => (
                  <SelectItem key={provider.id} value={provider.id}>
                    {provider.display_name}{!provider.installed ? ' (missing)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}
      <nav className={cn(
        'flex flex-col flex-1 overflow-y-auto',
        collapsed ? 'gap-1 p-2' : 'gap-4 p-4'
      )}>
        {visibleGroups.map((group) => (
          <div key={group.name} className="space-y-1">
            {!collapsed && (
              <p className="px-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {group.name}
              </p>
            )}
            {group.items.map((item) => (
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
          </div>
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
