export type TeamSlotUIColor = 'blue' | 'purple' | 'green' | 'amber' | 'red' | 'cyan' | 'slate'

export const TEAM_SLOT_COLOR_OPTIONS: { value: TeamSlotUIColor; label: string }[] = [
  { value: 'blue', label: 'Blue' },
  { value: 'purple', label: 'Purple' },
  { value: 'green', label: 'Green' },
  { value: 'amber', label: 'Amber' },
  { value: 'red', label: 'Red' },
  { value: 'cyan', label: 'Cyan' },
  { value: 'slate', label: 'Slate' },
]

export interface TeamSlotColorClasses {
  card: string
  badge: string
  dot: string
  terminalBar: string
  terminalWrapper: string
}

export interface TeamSlotTerminalTheme {
  background: string
  foreground: string
  cursor: string
  selectionBackground: string
}

const TEAM_SLOT_COLOR_VALUES = new Set(TEAM_SLOT_COLOR_OPTIONS.map((option) => option.value))

const DEFAULT_CLASSES: TeamSlotColorClasses = {
  card: '',
  badge: '',
  dot: 'bg-muted-foreground',
  terminalBar: '',
  terminalWrapper: 'bg-background',
}

const COLOR_CLASSES: Record<TeamSlotUIColor, TeamSlotColorClasses> = {
  blue: {
    card: 'border-l-4 border-l-blue-500 bg-blue-500/5',
    badge: 'border-blue-500/50 bg-blue-500/10 text-blue-300',
    dot: 'bg-blue-400',
    terminalBar: 'border-blue-500/60',
    terminalWrapper: 'bg-blue-950/20',
  },
  purple: {
    card: 'border-l-4 border-l-purple-500 bg-purple-500/5',
    badge: 'border-purple-500/50 bg-purple-500/10 text-purple-300',
    dot: 'bg-purple-400',
    terminalBar: 'border-purple-500/60',
    terminalWrapper: 'bg-purple-950/20',
  },
  green: {
    card: 'border-l-4 border-l-emerald-500 bg-emerald-500/5',
    badge: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300',
    dot: 'bg-emerald-400',
    terminalBar: 'border-emerald-500/60',
    terminalWrapper: 'bg-emerald-950/20',
  },
  amber: {
    card: 'border-l-4 border-l-amber-500 bg-amber-500/5',
    badge: 'border-amber-500/50 bg-amber-500/10 text-amber-300',
    dot: 'bg-amber-400',
    terminalBar: 'border-amber-500/60',
    terminalWrapper: 'bg-amber-950/20',
  },
  red: {
    card: 'border-l-4 border-l-red-500 bg-red-500/5',
    badge: 'border-red-500/50 bg-red-500/10 text-red-300',
    dot: 'bg-red-400',
    terminalBar: 'border-red-500/60',
    terminalWrapper: 'bg-red-950/20',
  },
  cyan: {
    card: 'border-l-4 border-l-cyan-500 bg-cyan-500/5',
    badge: 'border-cyan-500/50 bg-cyan-500/10 text-cyan-300',
    dot: 'bg-cyan-400',
    terminalBar: 'border-cyan-500/60',
    terminalWrapper: 'bg-cyan-950/20',
  },
  slate: {
    card: 'border-l-4 border-l-slate-500 bg-slate-500/5',
    badge: 'border-slate-500/50 bg-slate-500/10 text-slate-300',
    dot: 'bg-slate-400',
    terminalBar: 'border-slate-500/60',
    terminalWrapper: 'bg-slate-950/20',
  },
}

const TERMINAL_THEMES: Record<TeamSlotUIColor, TeamSlotTerminalTheme> = {
  blue: { background: '#0b1220', foreground: '#dbeafe', cursor: '#bfdbfe', selectionBackground: '#1d4ed866' },
  purple: { background: '#151023', foreground: '#ede9fe', cursor: '#ddd6fe', selectionBackground: '#7e22ce66' },
  green: { background: '#07170f', foreground: '#d1fae5', cursor: '#a7f3d0', selectionBackground: '#04785766' },
  amber: { background: '#1b1407', foreground: '#fef3c7', cursor: '#fde68a', selectionBackground: '#b4530966' },
  red: { background: '#1f0d0d', foreground: '#fee2e2', cursor: '#fecaca', selectionBackground: '#b91c1c66' },
  cyan: { background: '#071a1c', foreground: '#cffafe', cursor: '#a5f3fc', selectionBackground: '#0e749066' },
  slate: { background: '#111827', foreground: '#e5e7eb', cursor: '#cbd5e1', selectionBackground: '#47556966' },
}

export function normalizeTeamSlotColor(value: string | null | undefined): TeamSlotUIColor | null {
  const color = value?.trim() as TeamSlotUIColor | undefined
  return color && TEAM_SLOT_COLOR_VALUES.has(color) ? color : null
}

export function getTeamSlotColorClasses(value: string | null | undefined): TeamSlotColorClasses {
  const color = normalizeTeamSlotColor(value)
  return color ? COLOR_CLASSES[color] : DEFAULT_CLASSES
}

export function getTeamSlotTerminalTheme(value: string | null | undefined): TeamSlotTerminalTheme | null {
  const color = normalizeTeamSlotColor(value)
  return color ? TERMINAL_THEMES[color] : null
}
