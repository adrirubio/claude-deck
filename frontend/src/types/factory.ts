// Generated from accepted P01 schema1; provenance: tests/fixtures/factory/PROVENANCE.md.
export type FactoryErrorDetail = {
  code:
    | "invalid_filter"
    | "invalid_cursor"
    | "resource_not_found"
    | "projection_failed";
  message: string;
};

export type FactoryErrorResponse = {
  detail: FactoryErrorDetail;
};

export type AutomationSummary = {
  configured_scopes: number;
  enabled_scopes: number;
  intake_blocked_scopes: number;
  intake_eligible_scopes: number;
  intake_unknown_scopes: number;
  never_polled_scopes: number;
  paused_scopes: number;
  runtime: RuntimeObservation;
  stale_scopes: number;
};

export type FactoryCounts = {
  active: number;
  attention: number;
  finished: number;
  queued: number;
  review: number;
  total: number;
  unknown: number;
};

export type FactoryFilters = {
  provider: string | null;
  scope_id: number | null;
  team_id: number | null;
};

export type RuntimeObservation = {
  mode: "normal" | "recovery_only" | "unknown";
  observed_at: string | null;
  reason_code: string | null;
  scheduler_state: "running" | "stopped" | "unknown";
};

export type OverviewResponse = {
  automation: AutomationSummary;
  counts: FactoryCounts;
  filters: FactoryFilters;
  generated_at: string;
  schema_version: 1;
};

export type GithubIdentity = {
  name: string;
  owner: string;
};

export type IntakeProjection = {
  reason_code: string;
  state: "eligible" | "blocked" | "unknown";
  summary: string;
};

export type OverlapObservation = {
  other_scope_ids: number[];
  state: "none" | "warning" | "unknown";
};

export type PollObservation = {
  freshness: "fresh" | "stale" | "never_polled" | "suspended" | "unknown";
  interval_seconds: number;
  last_polled_at: string | null;
};

export type RepositoryProjection = {
  configured_enabled: boolean;
  github: GithubIdentity;
  intake: IntakeProjection;
  overlap: OverlapObservation;
  poll: PollObservation;
  scope_enabled: boolean;
  scope_id: number;
  team: TeamReference;
  team_automation_enabled: boolean;
};

export type TeamReference = {
  id: number;
  name: string;
};

export type RepositoryDetailResponse = {
  generated_at: string;
  repository: RepositoryProjection;
  schema_version: 1;
};

export type RepositoryListResponse = {
  filters: FactoryFilters;
  generated_at: string;
  has_more: boolean;
  next_cursor: string | null;
  repositories: RepositoryProjection[];
  schema_version: 1;
  total: number;
};

export type ApproverReference = {
  member_id: number | null;
  slot_id: number | null;
  source: "first_enabled_slot" | "explicit_assignment" | "unknown";
};

export type BridgeTarget = {
  member_id: number;
  session_id: number;
  slot_id: number;
  team_id: number;
};

export type FactoryAction = {
  block_code: string | null;
  name:
    | "retry"
    | "resume_attempt"
    | "escalate_attempt"
    | "cancel_continuation_request"
    | "cancel_active_revision"
    | "release_recovery_checkpoint";
  reason: string;
  required_actor: "leader" | "owner" | "operator" | "unknown";
  state: "eligible" | "blocked" | "unknown";
};

export type LaunchPlanHint = {
  slot_id: number;
  team_id: number;
};

export type LinkHints = {
  bridge_target: BridgeTarget | null;
  launch_plan: LaunchPlanHint | null;
  mail: MailHint | null;
};

export type MailHint = {
  member_id: number;
  slot_id: number;
  team_id: number;
};

export type OwnerReference = {
  configured_provider: string | null;
  member_id: number | null;
  name: string;
  provider_label: string | null;
  slot_id: number;
};

export type SafeWorkItem = {
  active_scope_revision: number;
  active_scope_status: string | null;
  approval_round_count: number;
  attempt_phase: string;
  created_at: string;
  diagnostic_retry_count: number;
  dispatch_status: string;
  github_updated_at: string;
  id: number;
  issue_number: number;
  issue_title: string;
  issue_type: string;
  last_verified_sha: string | null;
  pending_approval_kind: string | null;
  pending_approval_status: string | null;
  pr_number: number | null;
  retry_count: number;
  scope_id: number;
  updated_at: string;
};

export type SessionAssociation = {
  bridge_target: BridgeTarget | null;
  observed_provider: string | null;
  state: "bound" | "offline" | "ambiguous" | "unknown";
};

export type WaitingActor = {
  actor: "owner" | "leader" | "operator" | "human" | "unknown";
  reason_code: string;
  summary: string;
};

export type WorkPolicy = {
  continuation_enabled: boolean;
  max_approval_rounds: number;
  max_verification_retries: number;
  merge_policy: string;
};

export type WorkProjection = {
  actions: FactoryAction[];
  approver: ApproverReference | null;
  approver_session: SessionAssociation;
  category:
    "queued" | "active" | "review" | "attention" | "finished" | "unknown";
  item: SafeWorkItem;
  links: LinkHints;
  owner: OwnerReference | null;
  policy: WorkPolicy;
  repository: WorkRepository;
  session: SessionAssociation;
  team: TeamReference;
  waiting: WaitingActor | null;
  workspace: WorkspaceAssociation | null;
};

export type WorkRepository = {
  display_name: string;
  github: GithubIdentity;
  scope_id: number;
};

export type WorkspaceAssociation = {
  id: number;
  state: "leased" | "released" | "unknown";
};

export type WorkDetailResponse = {
  generated_at: string;
  schema_version: 1;
  work_item: WorkProjection;
};

export type WorkFilters = {
  category:
    | "all"
    | "queued"
    | "active"
    | "review"
    | "attention"
    | "finished"
    | "unknown";
  provider: string | null;
  scope_id: number | null;
  team_id: number | null;
};

export type WorkListResponse = {
  counts: FactoryCounts;
  filters: WorkFilters;
  generated_at: string;
  has_more: boolean;
  items: WorkProjection[];
  next_cursor: string | null;
  schema_version: 1;
  total: number;
};
