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
}

export interface SpawnSessionResponse {
  tmux_target: string
  session_name: string
}

export interface KillSessionResponse {
  killed: boolean
  error?: string
}
