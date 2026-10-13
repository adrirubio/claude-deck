import type { AgentStatus } from './agentStatus'

export type AgentTeamProvider = 'claude-code' | 'codex-cli' | 'copilot-cli' | 'opencode-cli' | 'pi-cli'
export type AgentTeamLaunchAction = 'reuse' | 'adopt' | 'spawn' | 'skip' | 'blocked'
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
  controlled_language_enabled?: boolean
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
  parent_issue_url?: string | null
  created_by?: string | null
  created_at: string
  updated_at: string
  autonomy_enabled: boolean
  leader_slot_id?: number | null
  slots: AgentTeamSlot[]
}

export type TeamSummaryAttentionCode =
  | 'attempt_stopped' | 'recovery_decision' | 'human_review' | 'owner_stalled'
  | 'observation_pause' | 'hold' | 'recovery_only' | 'hold_unavailable'

export interface TeamSummaryAttention {
  code: TeamSummaryAttentionCode
  work_item_id?: number | null
  scope_id?: number | null
  issue_number?: number | null
  pause_id?: number | null
  observed_at?: string | null
  resume_deadline?: string | null
}

export interface TeamSummaryHumanAction {
  scope_id: number
  issue_number: number
  work_item_id?: number | null
  kind: 'review_pr' | 'merge_pr' | 'inspect_attempt' | 'inspect_checkpoint' | 'milestone_acceptance'
    | 'pilot_decision' | 'scope_clarification' | 'provide_evidence'
  state: 'requested' | 'context_pending' | 'waiting_for_prerequisites' | 'historical' | 'resolved'
    | 'head_changed' | 'pr_unavailable' | 'pr_identity_unavailable'
  source: 'leader' | 'dispatch' | 'unknown'
  assessment_current: boolean
  pull_request_number?: number | null
}

export interface RequiredCIUnreadableSignal {
  code: 'required_ci_unreadable'
  label: 'Required CI cannot be read'
  since: string
  reason: 'permission_missing' | 'workflow_missing' | 'api_error' | 'unknown'
  next_steps: string[]
}

export interface TeamRequiredCIUnreadable extends RequiredCIUnreadableSignal {
  work_item_id: number
  scope_id: number
  issue_number: number
}

export interface TeamRemainingWork {
  state: 'known' | 'unknown'
  unfinished_items: number
  reported_items: number
  effort_low_minutes?: number | null
  effort_high_minutes?: number | null
  confidence: 'unknown' | 'low' | 'medium' | 'high'
  reason: 'complete' | 'report_unknown' | 'observation_incomplete' | 'context_changed'
}

export interface CampaignDoneItem { title: string; merged_at: string | null }
export interface CampaignUnderWayItem {
  title: string
  owner_short_name: string | null
  state_phrase: 'building it' | 'reviewing it' | 'waiting for checks' | 'waiting for you'
}
export interface CampaignDecision { text: string; state: 'later' | 'now' | 'done' }

// The progress of one team's campaign (#548, #587). Counts come from the server.
export interface TeamCampaignSummary {
  backlog_state: 'available' | 'backlog unavailable'
  done_count: number
  latest_done: CampaignDoneItem[]
  under_way_count: number
  under_way: CampaignUnderWayItem[]
  queued_count: number
  queued: { title: string }[]
  not_started_count: number | null
  not_started_groups: { area: string; count: number }[]
  decisions_ahead: CampaignDecision[]
}

// The status that the controller derives from the clock and the stored promise (#549).
export interface SupervisorObservation {
  status: 'none' | 'healthy' | 'late' | 'absent'
  actor_id: number | null
  checked_at: string | null
  next_check_at: string | null
  grace_seconds: number
  note: string | null
  attention: 'Supervisor check-in overdue' | null
}

// A member waits at an interactive screen. Only the fixed reason is on the wire.
export interface TeamWaitingInput {
  slot_id: number
  reason: 'question' | 'trust' | 'sign_in'
  label: 'Waiting for input'
}

// One unanswered-reminder signal (#528). Read it through parseReminders: the wire is not trusted.
export interface ReminderAttention {
  kind: 'workspace_release' | 'backlog_reconcile'
  scope_id: number
  work_item_id?: number | null
  issue_number?: number | null
  issue_numbers?: number[]
  owner_slot_id?: number | null
  owner_name?: string | null
  reminder_count: number
  reminder_cap: number
  waiting_since?: string | null
  elapsed_seconds?: number | null
  notification_budget_resets_at?: string | null
}

// GET agent-teams/presets/{id}/summary. A display-only read: it grants no action.
export interface AgentTeamSummary {
  preset_id: number
  description: string | null
  parent_issue_url: string | null
  supervisor: 'none'
  // Missing on an older server. Null means Deck could not read it.
  supervisor_observation?: SupervisorObservation | null
  waiting_input?: TeamWaitingInput[] | null
  // Missing on an older server. A row that cannot be read is ignored.
  reminder_attention?: ReminderAttention[]
  reminder_attention_complete?: boolean
  checked_at: string
  valid_until: string
  coverage_complete: boolean
  hold_code: 'hold' | 'recovery_only' | 'hold_unavailable' | null
  attention: TeamSummaryAttention[]
  required_ci_unreadable?: TeamRequiredCIUnreadable[]
  human_actions: TeamSummaryHumanAction[]
  remaining_work: TeamRemainingWork
  next_actors: ('owner' | 'leader' | 'operator' | 'controller')[]
  next_actor_coverage_complete: boolean
  campaign?: TeamCampaignSummary
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
  controlled_language_enabled?: boolean
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
  controlled_language_enabled?: boolean
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
  autonomy_enabled?: false
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
  adopt_unbound_sessions?: boolean
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
  github_auth_mode: 'unknown' | 'ambient' | 'app' | string
  github_auth_configured: boolean
  github_poll_token_configured: boolean
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
  base_ref?: string
  github_auth_mode?: 'unknown' | 'ambient' | 'app'
  builds_out_of_tree?: boolean
  build_dir_template?: string
  build_command_hint?: string | null
  max_build_parallelism?: number
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
  base_ref?: string
  github_auth_mode?: 'unknown' | 'ambient' | 'app'
  builds_out_of_tree?: boolean
  build_dir_template?: string
  build_command_hint?: string | null
  max_build_parallelism?: number
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
  recovery_checkpoint_stage?: string | null
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
  cancelled_at?: string | null
  cancellation_reason?: string | null
  expires_at?: string | null
  created_at: string
  approval_request?: GithubApprovalRequest | null
}

export interface AgentActivityObservation {
  slot_id: number
  state: 'working' | 'idle' | 'stopped' | 'unknown'
  reason: string
  observed_at: string | null
  agent_status?: AgentStatus | null
}

export interface AgentTeamActivityResponse {
  preset_id: number
  checked_at: string
  valid_until: string
  slots: AgentActivityObservation[]
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
  ack_evidence_message_id?: number | null
  dispatch_head_ref?: string | null
  pr_number?: number | null
  retry_count: number
  last_verified_sha?: string | null
  retry_requested_at?: string | null
  escalation_reason?: string | null
  status_note?: string | null
  checks_unavailable_since?: string | null
  checks_unavailable_reason?: RequiredCIUnreadableSignal['reason'] | null
  required_ci_unreadable?: RequiredCIUnreadableSignal | null
  auto_merged_at?: string | null
  active_scope_revision: number
  active_scope_summary?: string | null
  active_scope_status?: string | null
  pending_approval_request_id?: number | null
  pending_approval_kind?: string | null
  pending_approval_status?: string | null
  recovery_checkpoint_stage?: string | null
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

export interface GithubWorkspace {
  id: number
  scope_id: number
  path: string
  kind: string
  lease_state: string
  leased_item_id?: number | null
  leased_at?: string | null
  enabled: boolean
  provision_error?: string | null
}

export interface GithubRecoveryGate {
  active: boolean
  scope_id?: number
  work_item_id?: number
  pr_number?: number
  identity_matches?: boolean
  scheduler_running?: boolean
  job_scheduled?: boolean
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
  adopt_count: number
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
  workspace_trust_changed?: boolean
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
