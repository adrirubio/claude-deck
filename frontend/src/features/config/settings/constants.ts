export const MODEL_OPTIONS = [
  { value: 'claude-opus-4-8', label: 'Claude Opus 4.8' },
  { value: 'claude-opus-4-7', label: 'Claude Opus 4.7' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-fable-5', label: 'Claude Fable 5' },
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
  { value: 'xhigh', label: 'Extra High' },
]

export const TEAMMATE_MODE_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'in-process', label: 'In-Process' },
  { value: 'tmux', label: 'Tmux' },
]

export const HANDLER_TYPE_OPTIONS = [
  { value: 'command', label: 'Command' },
  { value: 'http', label: 'HTTP' },
  { value: 'prompt', label: 'Prompt' },
  { value: 'agent', label: 'Agent' },
]

export const SHELL_OPTIONS = [
  { value: 'bash', label: 'Bash' },
  { value: 'powershell', label: 'PowerShell' },
]

export const HOOK_MODEL_OPTIONS = [
  { value: 'fast-model', label: 'Fast Model (default)' },
  { value: 'haiku', label: 'Haiku' },
  { value: 'sonnet', label: 'Sonnet' },
  { value: 'opus', label: 'Opus' },
]

export const TUI_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'fullscreen', label: 'Fullscreen' },
]

export const VIEW_MODE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'verbose', label: 'Verbose' },
  { value: 'focus', label: 'Focus' },
]

export const THEME_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
  { value: 'dark-daltonized', label: 'Dark Daltonized' },
  { value: 'light-daltonized', label: 'Light Daltonized' },
  { value: 'dark-ansi', label: 'Dark ANSI' },
  { value: 'light-ansi', label: 'Light ANSI' },
]

export const NOTIFICATION_CHANNEL_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'terminal_bell', label: 'Terminal bell' },
  { value: 'iterm2', label: 'iTerm2 notification' },
  { value: 'iterm2_with_bell', label: 'iTerm2 + bell' },
  { value: 'kitty', label: 'Kitty notification' },
  { value: 'ghostty', label: 'Ghostty notification' },
  { value: 'notifications_disabled', label: 'Disabled' },
]

export const EDITOR_MODE_OPTIONS = [
  { value: 'normal', label: 'Normal' },
  { value: 'vim', label: 'Vim' },
]

export const SPINNER_VERBS_MODE_OPTIONS = [
  { value: 'default', label: 'Default' },
  { value: 'append', label: 'Append to defaults' },
  { value: 'replace', label: 'Replace defaults' },
]

export const WORKTREE_BASE_REF_OPTIONS = [
  { value: 'fresh', label: 'Fresh (origin/<default-branch>)' },
  { value: 'head', label: 'HEAD (current local branch)' },
]

export const WORKTREE_BG_ISOLATION_OPTIONS = [
  { value: 'worktree', label: 'Worktree (block edits until EnterWorktree)' },
  { value: 'none', label: 'None (edit working copy directly)' },
]

export const HOOK_EVENT_GROUPS = [
  {
    label: 'Lifecycle',
    events: ['SessionStart', 'SessionEnd', 'Stop', 'StopFailure', 'UserPromptSubmit', 'PreCompact', 'PostCompact', 'Notification'],
  },
  {
    label: 'Tool',
    events: ['PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'PermissionRequest', 'PermissionDenied'],
  },
  {
    label: 'Agent & Team',
    events: ['SubagentStart', 'SubagentStop', 'TeammateIdle', 'TaskCreated', 'TaskCompleted'],
  },
  {
    label: 'Config & Infrastructure',
    events: ['InstructionsLoaded', 'ConfigChange', 'CwdChanged', 'FileChanged', 'WorktreeCreate', 'WorktreeRemove', 'Elicitation', 'ElicitationResult'],
  },
] as const
