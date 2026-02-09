import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { ProjectSwitcher } from '@/features/projects/ProjectSwitcher'
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
  { name: 'Context', href: '/context', icon: Gauge },
  { name: 'Usage', href: '/usage', icon: BarChart3 },
  { name: 'Backup', href: '/backup', icon: Archive },
]

export function Sidebar() {
  return (
    <aside className="w-64 border-r bg-background">
      <div className="py-4 border-b">
        <ProjectSwitcher />
      </div>
      <nav className="flex flex-col gap-1 p-4">
        {navigation.map((item) => (
          <NavLink
            key={item.href}
            to={item.href}
            end={item.href === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-foreground hover:bg-accent hover:text-accent-foreground'
              )
            }
          >
            <item.icon className="h-4 w-4" />
            {item.name}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
