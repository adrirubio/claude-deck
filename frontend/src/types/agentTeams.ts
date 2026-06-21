export type AgentTeamProvider = 'claude-code' | 'codex-cli' | 'copilot-cli' | 'opencode-cli'
export type AgentTeamLaunchAction = 'reuse' | 'spawn' | 'skip' | 'blocked'
export type AgentTeamLaunchStatus =
  | 'ready'
  | 'blocked'
  | 'skipped'
  | 'skipped_disabled'
  | 'reused'
  | 'spawned'
  | 'pending_registration'
  | 'failed'
  | 'blocked_provider_unavailable'
  | 'blocked_agent_mail_not_configured'

export interface AgentTeamSlot {
  id: number
  preset_id: number
  position: number
  display_name: string
  provider: AgentTeamProvider | string
  repo_id: string
  repo_path: string
  repo_name: string
  role?: string | null
  charter?: string | null
  bootstrap_prompt?: string | null
  launch_mode: string
  launch_options: Record<string, unknown>
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface AgentTeamPreset {
  id: number
  name: string
  description?: string | null
  created_by?: string | null
  created_at: string
  updated_at: string
  slots: AgentTeamSlot[]
}

export interface AgentTeamPresetListResponse {
  presets: AgentTeamPreset[]
}

export interface AgentTeamSlotInput {
  display_name: string
  provider: AgentTeamProvider | string
  repo_path: string
  role?: string | null
  charter?: string | null
  bootstrap_prompt?: string | null
  launch_mode?: string
  launch_options?: Record<string, unknown>
  enabled?: boolean
  position?: number | null
}

export interface AgentTeamSlotUpdate {
  display_name?: string
  provider?: AgentTeamProvider | string
  repo_path?: string
  role?: string | null
  charter?: string | null
  bootstrap_prompt?: string | null
  launch_mode?: string
  launch_options?: Record<string, unknown>
  enabled?: boolean
  position?: number
}

export interface AgentTeamPresetInput {
  name: string
  description?: string | null
  created_by?: string | null
  slots?: AgentTeamSlotInput[]
}

export interface AgentTeamPresetUpdate {
  name?: string
  description?: string | null
}

export interface AgentTeamCreateFromMailRequest {
  name: string
  description?: string | null
  member_ids?: number[] | null
  include_offline?: boolean
}

export interface AgentTeamCreateFromBridgeRequest {
  name: string
  description?: string | null
}

export interface AgentTeamLaunchRequest {
  requested_by?: string | null
  slot_ids?: number[] | null
  reuse_existing?: boolean
  include_disabled?: boolean
  confirm_plan_hash?: string | null
  skip_plan_confirmation?: boolean
}

export interface AgentTeamLaunchPlanItem {
  slot_id: number
  slot_name: string
  provider: string
  repo_id: string
  repo_path: string
  repo_name: string
  action: AgentTeamLaunchAction
  status: string
  reasons: string[]
  matching_session?: Record<string, unknown> | null
  block_code?: string | null
}

export interface AgentTeamLaunchPlan {
  preset_id: number
  preset_name: string
  plan_hash: string
  generated_at: string
  can_launch: boolean
  items: AgentTeamLaunchPlanItem[]
  reuse_count: number
  spawn_count: number
  skipped_count: number
  blocked_count: number
}

export interface AgentTeamLaunchResultItem {
  slot_id: number
  slot_name: string
  action: AgentTeamLaunchAction
  status: AgentTeamLaunchStatus
  provider: string
  repo_path: string
  session_name?: string | null
  tmux_target?: string | null
  agent_mail_member_id?: number | null
  message?: string | null
  block_code?: string | null
  error?: string | null
}

export interface AgentTeamLaunchResult {
  launch_id: number
  preset_id: number
  preset_name: string
  plan_hash: string
  status: string
  launched_at: string
  completed_at: string
  items: AgentTeamLaunchResultItem[]
}
