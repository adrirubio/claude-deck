import type { AgentProviderId } from '@/types/providers'

export interface AgentSession {
  provider: AgentProviderId
  provider_display_name: string
  tmux_target: string
  session_name: string
  window_name: string
  pane_id: string
  cwd: string
  pid: string
  status: string
  team_preset_id?: number | null
  team_preset_name?: string | null
  team_slot_id?: number | null
  team_slot_name?: string | null
  team_slot_role?: string | null
  team_slot_charter?: string | null
  team_slot_color?: string | null
}

export type CCSession = AgentSession

export interface AgentSessionsResponse {
  sessions: AgentSession[]
  count: number
}

export type CCSessionsResponse = AgentSessionsResponse

export interface CCPreviewResponse {
  target: string
  content: string
}

export interface CCTokenResponse {
  token: string
}

export interface SpawnSessionRequest {
  provider?: AgentProviderId
  directory: string
  mode: 'plain' | 'worktree' | 'resume' | 'fork'
  worktree_name?: string
  session_id?: string
  project_folder?: string
  skip_permissions?: boolean
  prompt?: string
  model?: string
  profile?: string
  profile_v2?: string
  sandbox?: string
  approval_policy?: string
  search?: boolean
  no_alt_screen?: boolean
  dangerously_bypass_approvals_and_sandbox?: boolean
  use_last?: boolean
  platform?: 'anthropic' | 'bedrock'
  aws_region?: string
  aws_profile?: string
  bedrock_model?: string
  agent?: string
  context_tier?: string
  reasoning_effort?: string
  plan?: boolean
  remote?: boolean
  allow_all?: boolean
  no_ask_user?: boolean
}

export interface SpawnSessionResponse {
  tmux_target: string
  session_name: string
}

export interface KillSessionResponse {
  killed: boolean
  error?: string
}

export interface BridgeAttachment {
  id: number
  target: string
  session_name?: string | null
  provider?: string | null
  original_filename?: string | null
  mime_type: string
  size_bytes: number
  sha256: string
  agent_path: string
  prompt_text: string
  created_by?: string | null
  created_at: string
  expires_at?: string | null
}

export interface BridgeAttachmentListResponse {
  attachments: BridgeAttachment[]
}

export interface BridgeAttachmentPasteRequest {
  submit?: boolean
  prefix?: string
  suffix?: string
  require_interactive_relay?: boolean
}

export interface BridgeAttachmentPasteResponse {
  pasted: boolean
  submitted: boolean
  target: string
}

export interface BridgeAttachmentDeleteResponse {
  deleted: boolean
  target: string
  attachment_id: number
}

export interface CodexLaunchModelOption {
  value: string
  label: string
  source: string
  description?: string
  priority?: number
}

export interface CodexLaunchProfileOption {
  value: string
  label: string
  sources?: string[]
  active?: boolean
  parse_error?: string | null
}

export interface CodexLaunchOptionsResponse {
  provider: 'codex-cli'
  config_path: string
  models_cache_path: string
  config_exists: boolean
  config_parse_error: string | null
  models_cache_exists: boolean
  models_cache_parse_error: string | null
  default_model?: string | null
  default_profile?: string | null
  model_options: CodexLaunchModelOption[]
  profile_options: CodexLaunchProfileOption[]
}
