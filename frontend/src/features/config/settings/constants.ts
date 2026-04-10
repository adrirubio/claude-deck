export const MODEL_OPTIONS = [
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'claude-3-5-haiku-20241022', label: 'Claude 3.5 Haiku' },
]

export const PERMISSION_MODE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'acceptEdits', label: 'Accept Edits' },
  { value: 'auto', label: 'Auto' },
  { value: 'dontAsk', label: "Don't Ask" },
  { value: 'plan', label: 'Plan Mode' },
  { value: 'bypassPermissions', label: 'Bypass Permissions' },
  { value: 'delegate', label: 'Delegate' },
]

export const UPDATE_CHANNEL_OPTIONS = [
  { value: 'stable', label: 'Stable' },
  { value: 'latest', label: 'Latest' },
]

export const LOGIN_METHOD_OPTIONS = [
  { value: 'claudeai', label: 'Claude.ai' },
  { value: 'console', label: 'Console' },
]

export const EFFORT_LEVEL_OPTIONS = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
]

export const TEAMMATE_MODE_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'in-process', label: 'In-Process' },
  { value: 'tmux', label: 'Tmux' },
]
