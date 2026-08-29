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

export interface SlotLaunchOptions {
  model?: string
  profile?: string
  profile_v2?: string
  sandbox?: string
  approval_policy?: string
  search?: boolean
  no_alt_screen?: boolean
  dangerously_bypass_approvals_and_sandbox?: boolean
  use_last?: boolean
  session_id?: string
  platform?: 'anthropic' | 'bedrock' | string
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
  skip_permissions?: boolean
  prompt?: string
  [key: string]: unknown
}

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
  ui_color?: string | null
  bootstrap_prompt?: string | null
  launch_mode: string
  launch_options: SlotLaunchOptions
  area_labels?: string[] | null
  expertise?: string | null
  warnings?: string[]
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
  autonomy_enabled: boolean
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
  ui_color?: string | null
  bootstrap_prompt?: string | null
  launch_mode?: string
  launch_options?: SlotLaunchOptions
  area_labels?: string[] | null
  expertise?: string | null
  enabled?: boolean
  position?: number | null
}

export interface AgentTeamSlotUpdate {
  display_name?: string
  provider?: AgentTeamProvider | string
  repo_path?: string
  role?: string | null
  charter?: string | null
  ui_color?: string | null
  bootstrap_prompt?: string | null
  launch_mode?: string
  launch_options?: SlotLaunchOptions
  area_labels?: string[] | null
  expertise?: string | null
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
  autonomy_enabled?: boolean
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
  repo_path_override?: string | null
  slot_prompt_overrides?: Record<number, string> | null
}

export type TeamGithubMergePolicy = 'human' | 'auto'

export interface TeamGithubScope {
  id: number
  preset_id: number
  repo_owner: string
  repo_name: string
  repo_path: string
  dispatch_label: string
  design_label: string
  merge_policy: TeamGithubMergePolicy | string
  max_approval_rounds: number
  max_concurrent_dispatched: number
  max_verification_retries: number
  max_auto_merges_per_day: number
  base_ref: string
  builds_out_of_tree: boolean
  build_dir_template?: string | null
  build_command_hint?: string | null
  max_build_parallelism: number
  continuation_enabled: boolean
  max_continuation_revisions: number
  max_continuation_failed_heads: number
  max_failed_heads_per_revision: number
  max_scope_paths: number
  max_scope_commands: number
  enabled: boolean
  last_polled_at?: string | null
  created_at: string
  updated_at: string
}

export interface TeamGithubScopeInput {
  repo_owner: string
  repo_name: string
  repo_path: string
  dispatch_label?: string
  design_label?: string
  merge_policy?: TeamGithubMergePolicy
  max_approval_rounds?: number
  max_concurrent_dispatched?: number
  max_verification_retries?: number
  max_auto_merges_per_day?: number
  enabled?: boolean
}

export interface TeamGithubScopeUpdate {
  repo_owner?: string
  repo_name?: string
  repo_path?: string
  dispatch_label?: string
  design_label?: string
  merge_policy?: TeamGithubMergePolicy
  max_approval_rounds?: number
  max_concurrent_dispatched?: number
  max_verification_retries?: number
  max_auto_merges_per_day?: number
  enabled?: boolean
}

export interface TeamGithubScopeListResponse {
  scopes: TeamGithubScope[]
}

export interface TeamGithubContinuationPolicyUpdate {
  continuation_enabled: boolean
  max_continuation_revisions: number
  max_continuation_failed_heads: number
  max_failed_heads_per_revision: number
  max_scope_paths: number
  max_scope_commands: number
}

export type GithubApprovalRequestStatus = 'pending' | 'approved' | 'rejected' | 'superseded' | 'expired' | string

export interface GithubApprovalRequest {
  id: number
  work_item_id: number
  request_kind: 'initial_plan' | 'continuation' | string
  dispatch_nonce: string
  approval_round: number
  owner_member_id: number
  leader_member_id: number
  request_message_id?: number | null
  decision_message_id?: number | null
  scope_revision_id?: number | null
  status: GithubApprovalRequestStatus
  reason?: string | null
  created_at: string
  decided_at?: string | null
  superseded_at?: string | null
}

export type GithubAttemptPhase = 'implementation' | 'diagnostic' | string
export type GithubScopeRevisionStatus =
  | 'proposed'
  | 'approved'
  | 'active'
  | 'submitted'
  | 'completed'
  | 'rejected'
  | 'superseded'
  | 'expired'
  | 'exhausted'
  | string

export interface GithubScopeRevision {
  id: number
  work_item_id: number
  dispatch_nonce: string
  revision: number
  owner_slot_id: number
  owner_member_id: number
  phase: GithubAttemptPhase
  execution_target: string
  summary: string
  allowed_paths: string[]
  allowed_actions: string[]
  allowed_commands: string[]
  prohibited_actions: string[]
  tool_fallbacks: Record<string, unknown>
  baseline_head_sha: string
  baseline_tree_sha: string
  originating_escalation_reason: string
  expected_workspace_id: number
  max_failed_heads: number
  failed_head_count: number
  last_failed_head_sha?: string | null
  status: GithubScopeRevisionStatus
  approval_request_id?: number | null
  delivery_message_id?: number | null
  approved_at?: string | null
  delivered_at?: string | null
  acknowledged_at?: string | null
  last_delivery_attempt_at?: string | null
  delivery_attempt_count: number
  last_ack_nudge_at?: string | null
  result_summary?: string | null
  evidence?: Record<string, unknown> | null
  submitted_head_sha?: string | null
  submitted_at?: string | null
  completed_at?: string | null
  expires_at?: string | null
  created_at: string
  approval_request?: GithubApprovalRequest | null
}

export interface GithubWorkItem {
  id: number
  scope_id: number
  repo_owner: string
  repo_name: string
  issue_number: number
  issue_title: string
  issue_url: string
  github_updated_at: string
  issue_type: 'code' | 'design' | string
  dispatch_status: string
  pending_reason?: string | null
  launch_id?: number | null
  owner_slot_id?: number | null
  routing_method?: string | null
  handoff_state?: string | null
  handoff_target_slot_id?: number | null
  approval_round_count: number
  dispatch_nonce?: string | null
  dispatch_head_ref?: string | null
  pr_number?: number | null
  retry_count: number
  last_verified_sha?: string | null
  retry_requested_at?: string | null
  escalation_reason?: string | null
  status_note?: string | null
  auto_merged_at?: string | null
  active_scope_revision: number
  active_scope_summary?: string | null
  active_scope_status?: string | null
  pending_approval_request_id?: number | null
  pending_approval_kind?: string | null
  pending_approval_status?: string | null
  attempt_phase: GithubAttemptPhase
  diagnostic_retry_count: number
  diagnostic_last_verified_sha?: string | null
  revision_failed_head_count?: number | null
  revision_failed_head_budget?: number | null
  revision_approved_at?: string | null
  revision_delivered_at?: string | null
  revision_acknowledged_at?: string | null
  continuation_block_code?: string | null
  retry_allowed: boolean
  retry_block_code?: string | null
  continuation_nudged_at?: string | null
  continuation_activated_at?: string | null
  workspace_path?: string | null
  created_at: string
  updated_at: string
}

export interface GithubWorkItemListResponse {
  items: GithubWorkItem[]
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
  warnings?: string[]
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
  warnings?: string[]
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
