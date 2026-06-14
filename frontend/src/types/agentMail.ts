export type MailMessageKind = 'message' | 'broadcast' | 'context_request' | 'handoff' | 'answer'
export type MailRequestStatus = 'pending' | 'answered' | 'acknowledged'
export type MailMemberStatus = 'connected' | 'observed' | 'offline'
export type MailSessionSource = 'hook' | 'mcp' | 'observed' | string
export type MailWakeMethod = 'tmux' | 'codex_app_server' | string
export type MailWakeState = 'wakeable' | 'delivered_waiting' | 'offline' | string

export interface MailSessionResponse {
  id: number
  provider: string
  source: MailSessionSource
  session_key: string
  cwd?: string | null
  tmux_target?: string | null
  mailbox_status: MailMemberStatus | string
  activity?: string | null
  last_seen_at?: string | null
}

export interface MailMemberResponse {
  id: number
  repo_id: string
  repo_path: string
  repo_name: string
  display_name: string
  role?: string | null
  charter?: string | null
  status: MailMemberStatus
  unread_count: number
  pending_count: number
  unseen_pending_count: number
  stale_pending_count: number
  can_nudge: boolean
  wake_methods?: MailWakeMethod[]
  wake_state?: MailWakeState
  last_inbox_checked_at?: string | null
  sessions: MailSessionResponse[]
}

export interface TeamListResponse {
  members: MailMemberResponse[]
}

export interface MailMemberUpdate {
  display_name?: string
  role?: string | null
  charter?: string | null
}

export interface MailMessageCreate {
  kind?: MailMessageKind
  sender_member_id?: number | null
  recipient_member_id?: number | null
  thread_root_id?: number | null
  subject?: string | null
  body_markdown: string
  payload?: Record<string, unknown> | null
}

export interface MailMessageResponse {
  id: number
  thread_root_id?: number | null
  kind: MailMessageKind
  sender_member_id?: number | null
  sender_name: string
  recipient_member_id?: number | null
  subject?: string | null
  body_markdown: string
  payload?: Record<string, unknown> | null
  request_status?: MailRequestStatus | null
  is_stale: boolean
  read_at?: string | null
  acked_at?: string | null
  created_at: string
}

export interface MailThreadResponse {
  root: MailMessageResponse
  replies: MailMessageResponse[]
}

export interface MailInboxResponse {
  member_id: number
  unread_count: number
  pending_count: number
  messages: MailMessageResponse[]
}

export interface AgentMailInstallStatus {
  claude_code_hooks: string[]
  claude_code_hooks_missing: string[]
  claude_code_mcp_installed: boolean
  codex_cli_available: boolean
  codex_mcp_installed: boolean
  codex_hooks: string[]
  codex_hooks_missing: string[]
  codex_app_server_available: boolean
  codex_app_server_running: boolean
  codex_remote_control_running: boolean
  codex_app_server_error?: string | null
  codex_remote_control_error?: string | null
  curl_available: boolean
  shim_path: string
  python_path: string
  deck_url: string
  claude_settings_path?: string | null
  claude_mcp_config_path?: string | null
  codex_hooks_path?: string | null
}

export interface AgentMailSnippets {
  codex_config_toml: string
  codex_agents_md: string
}
