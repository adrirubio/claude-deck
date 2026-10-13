import {
  Archive, BarChart3, Bot, Brain, ClipboardList, Gauge, History, PanelBottom, Palette,
  Puzzle, Server, Settings, ShieldCheck, Sparkles, Terminal, Webhook, type LucideIcon,
} from 'lucide-react'
import type { DashboardStats } from '@/contexts/DashboardContext'
import type { NativeSurface } from '@/features/native-settings/surfaceRegistry'

// Plain names, groups and one-line purposes for the native pages of a harness.
// The Harnesses page shows these. It shows the code names (config, mcp, ...) only
// inside "Technical details". A purpose uses no lowercase code name, so a person
// reads words, not identifiers.

export type SurfaceGroup = 'Settings' | 'Extensions' | 'History & usage' | 'Safety'
export const SURFACE_GROUPS: SurfaceGroup[] = ['Settings', 'Extensions', 'History & usage', 'Safety']

export interface SurfaceInfo {
  group: SurfaceGroup
  name: string
  purpose: string
  icon: LucideIcon
  /** The count phrase for the tile, or null when the loaded data has none. */
  count?: (stats: DashboardStats) => string | null
}

function counted(value: number | null | undefined, one: string, many: string): string | null {
  if (value === null || value === undefined) return null
  if (value === 0) return 'None yet'
  return `${value} ${value === 1 ? one : many}`
}

export const surfaceInfo: Partial<Record<NativeSurface, SurfaceInfo>> = {
  config: { group: 'Settings', name: 'Configuration', purpose: 'Model, defaults and environment', icon: Settings,
    count: stats => counted(stats.settingsKeys, 'setting', 'settings') },
  permissions: { group: 'Settings', name: 'Permissions', purpose: 'What it may do without asking', icon: ShieldCheck,
    count: stats => counted(stats.permissionCount, 'rule', 'rules') },
  hooks: { group: 'Settings', name: 'Hooks', purpose: 'Commands that run on events', icon: Webhook,
    count: stats => counted(stats.hookCount, 'hook', 'hooks') },
  memory: { group: 'Settings', name: 'Memory (CLAUDE.md)', purpose: 'Instructions read in every session', icon: Brain },
  statusline: { group: 'Settings', name: 'Status line', purpose: 'The bar at the bottom of the terminal', icon: PanelBottom },
  'output-styles': { group: 'Settings', name: 'Output styles', purpose: 'How replies are formatted', icon: Palette,
    count: stats => counted(stats.outputStyleCount, 'style', 'styles') },
  mcp: { group: 'Extensions', name: 'MCP servers', purpose: 'Tools that the harness can call', icon: Server,
    count: stats => counted(stats.mcpServerCount, 'server', 'servers') },
  plugins: { group: 'Extensions', name: 'Plugins', purpose: 'Bundles that add tools and helpers', icon: Puzzle,
    count: stats => counted(stats.pluginCount, 'installed', 'installed') },
  commands: { group: 'Extensions', name: 'Slash commands', purpose: 'Reusable prompts that you start with a slash', icon: Terminal,
    count: stats => counted(stats.commandCount, 'command', 'commands') },
  agents: { group: 'Extensions', name: 'Agents', purpose: 'Specialist helpers it can delegate to', icon: Bot,
    count: stats => counted(stats.agentCount, 'agent', 'agents') },
  skills: { group: 'Extensions', name: 'Skills', purpose: 'Know-how loaded when needed', icon: Sparkles,
    count: stats => counted(stats.skillCount, 'skill', 'skills') },
  sessions: { group: 'History & usage', name: 'Sessions', purpose: 'Past conversations', icon: History,
    count: stats => counted(stats.sessionCount, 'session', 'sessions') },
  plans: { group: 'History & usage', name: 'Plans', purpose: 'Plans that the harness wrote', icon: ClipboardList,
    count: stats => counted(stats.planCount, 'plan', 'plans') },
  context: { group: 'History & usage', name: 'Context window', purpose: 'How full each live session is', icon: Gauge,
    count: stats => (stats.contextActiveCount === null ? null : `${stats.contextActiveCount} live`) },
  usage: { group: 'History & usage', name: 'Usage', purpose: 'Tokens and estimated cost', icon: BarChart3 },
  backup: { group: 'Safety', name: 'Backup & restore', purpose: 'Save and restore these settings', icon: Archive },
}
