import type { InstanceAccent } from '@/types/status'

export interface InstanceAccentClasses {
  headerBorder: string
  badge: string
  dot: string
  terminal: string
}

export const DEFAULT_INSTANCE_ACCENT: InstanceAccent = 'blue'

export const INSTANCE_ACCENT_CLASSES: Record<InstanceAccent, InstanceAccentClasses> = {
  blue: {
    headerBorder: 'border-t-blue-500',
    badge: 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300',
    dot: 'bg-blue-500',
    terminal: 'border-blue-500/40',
  },
  green: {
    headerBorder: 'border-t-green-500',
    badge: 'border-green-500/40 bg-green-500/10 text-green-700 dark:text-green-300',
    dot: 'bg-green-500',
    terminal: 'border-green-500/40',
  },
  purple: {
    headerBorder: 'border-t-purple-500',
    badge: 'border-purple-500/40 bg-purple-500/10 text-purple-700 dark:text-purple-300',
    dot: 'bg-purple-500',
    terminal: 'border-purple-500/40',
  },
  orange: {
    headerBorder: 'border-t-orange-500',
    badge: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
    dot: 'bg-orange-500',
    terminal: 'border-orange-500/40',
  },
  red: {
    headerBorder: 'border-t-red-500',
    badge: 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300',
    dot: 'bg-red-500',
    terminal: 'border-red-500/40',
  },
  pink: {
    headerBorder: 'border-t-pink-500',
    badge: 'border-pink-500/40 bg-pink-500/10 text-pink-700 dark:text-pink-300',
    dot: 'bg-pink-500',
    terminal: 'border-pink-500/40',
  },
  cyan: {
    headerBorder: 'border-t-cyan-500',
    badge: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
    dot: 'bg-cyan-500',
    terminal: 'border-cyan-500/40',
  },
  slate: {
    headerBorder: 'border-t-slate-500',
    badge: 'border-slate-500/40 bg-slate-500/10 text-slate-700 dark:text-slate-300',
    dot: 'bg-slate-500',
    terminal: 'border-slate-500/40',
  },
}

export function getInstanceAccentClasses(accent?: string | null): InstanceAccentClasses {
  if (!accent || !(accent in INSTANCE_ACCENT_CLASSES)) {
    return INSTANCE_ACCENT_CLASSES[DEFAULT_INSTANCE_ACCENT]
  }

  return INSTANCE_ACCENT_CLASSES[accent as InstanceAccent]
}
