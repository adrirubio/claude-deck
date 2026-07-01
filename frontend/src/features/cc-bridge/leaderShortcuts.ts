export interface LeaderShortcut {
  keys: string
  label: string
}

export const LEADER_PREFIX_LABEL = 'Ctrl+Space'

export const LEADER_SHORTCUTS: LeaderShortcut[] = [
  { keys: '←/→', label: 'Previous / next displayed pane' },
  { keys: '1-4', label: 'Jump to displayed pane' },
  { keys: 'r', label: 'Toggle read-only / interactive' },
  { keys: 'Esc', label: 'Cancel the leader' },
]
