"""Schema v1 for observational factory reads; private ORM fields never serialize."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


Timestamp = Annotated[datetime, AfterValidator(_utc)]
PositiveId = Annotated[int, Field(gt=0)]
Category = Literal["queued", "active", "review", "attention", "finished", "unknown"]
Eligibility = Literal["eligible", "blocked", "unknown"]


class FactoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactoryFilters(FactoryModel):
    team_id: PositiveId | None = None
    scope_id: PositiveId | None = None
    provider: str | None = None


class WorkFilters(FactoryFilters):
    category: Literal["all", "queued", "active", "review", "attention", "finished", "unknown"] = "all"


class FactoryCounts(FactoryModel):
    total: int = 0
    queued: int = 0
    active: int = 0
    review: int = 0
    attention: int = 0
    finished: int = 0
    unknown: int = 0


class RuntimeObservation(FactoryModel):
    mode: Literal["normal", "recovery_only", "unknown"]
    scheduler_state: Literal["running", "stopped", "unknown"]
    observed_at: Timestamp | None
    reason_code: str | None


class AutomationSummary(FactoryModel):
    configured_scopes: int = 0
    enabled_scopes: int = 0
    paused_scopes: int = 0
    never_polled_scopes: int = 0
    stale_scopes: int = 0
    intake_eligible_scopes: int = 0
    intake_blocked_scopes: int = 0
    intake_unknown_scopes: int = 0
    runtime: RuntimeObservation


class TeamReference(FactoryModel):
    id: PositiveId
    name: str


class GithubIdentity(FactoryModel):
    owner: str
    name: str


class WorkRepository(FactoryModel):
    scope_id: PositiveId
    github: GithubIdentity
    display_name: str


class OwnerReference(FactoryModel):
    slot_id: PositiveId
    member_id: PositiveId | None
    name: str
    configured_provider: str | None
    provider_label: str | None


class ApproverReference(FactoryModel):
    slot_id: PositiveId | None
    member_id: PositiveId | None
    source: Literal["first_enabled_slot", "explicit_assignment", "unknown"]


class BridgeTarget(FactoryModel):
    team_id: PositiveId
    slot_id: PositiveId
    member_id: PositiveId
    session_id: PositiveId


class SessionAssociation(FactoryModel):
    state: Literal["bound", "offline", "ambiguous", "unknown"]
    observed_provider: str | None = None
    bridge_target: BridgeTarget | None = None


class MailHint(FactoryModel):
    team_id: PositiveId
    slot_id: PositiveId
    member_id: PositiveId


class LaunchPlanHint(FactoryModel):
    team_id: PositiveId
    slot_id: PositiveId


class LinkHints(FactoryModel):
    mail: MailHint | None = None
    launch_plan: LaunchPlanHint | None = None
    bridge_target: BridgeTarget | None = None


class WaitingActor(FactoryModel):
    actor: Literal["owner", "leader", "operator", "human", "unknown"]
    reason_code: str
    summary: str


class FactoryAction(FactoryModel):
    name: Literal["retry", "resume_attempt", "escalate_attempt", "cancel_continuation_request",
                  "cancel_active_revision", "release_recovery_checkpoint"]
    state: Eligibility
    block_code: str | None
    reason: str
    required_actor: Literal["leader", "owner", "operator", "unknown"]


class WorkPolicy(FactoryModel):
    merge_policy: str
    max_verification_retries: int
    max_approval_rounds: int
    continuation_enabled: bool


class WorkspaceAssociation(FactoryModel):
    id: PositiveId
    state: Literal["leased", "released", "unknown"]


class SafeWorkItem(FactoryModel):
    id: PositiveId
    scope_id: PositiveId
    issue_number: PositiveId
    issue_title: str
    issue_type: str
    dispatch_status: str
    attempt_phase: str
    pr_number: PositiveId | None
    retry_count: int
    approval_round_count: int
    diagnostic_retry_count: int
    active_scope_revision: int
    active_scope_status: str | None
    pending_approval_kind: str | None
    pending_approval_status: str | None
    created_at: Timestamp
    updated_at: Timestamp
    github_updated_at: Timestamp
    last_verified_sha: str | None


class WorkProjection(FactoryModel):
    item: SafeWorkItem
    team: TeamReference
    repository: WorkRepository
    category: Category
    owner: OwnerReference | None
    approver: ApproverReference | None
    waiting: WaitingActor | None
    session: SessionAssociation
    approver_session: SessionAssociation
    policy: WorkPolicy
    workspace: WorkspaceAssociation | None
    actions: list[FactoryAction]
    links: LinkHints


class IntakeProjection(FactoryModel):
    state: Eligibility
    reason_code: str
    summary: str


class PollObservation(FactoryModel):
    interval_seconds: int
    last_polled_at: Timestamp | None
    freshness: Literal["fresh", "stale", "never_polled", "suspended", "unknown"]


class OverlapObservation(FactoryModel):
    state: Literal["none", "warning", "unknown"]
    other_scope_ids: list[PositiveId]


class RepositoryProjection(FactoryModel):
    scope_id: PositiveId
    team: TeamReference
    github: GithubIdentity
    team_automation_enabled: bool
    scope_enabled: bool
    configured_enabled: bool
    intake: IntakeProjection
    poll: PollObservation
    overlap: OverlapObservation


class FactoryEnvelope(FactoryModel):
    schema_version: Literal[1] = 1
    generated_at: Timestamp


class OverviewResponse(FactoryEnvelope):
    filters: FactoryFilters
    counts: FactoryCounts
    automation: AutomationSummary


class WorkListResponse(FactoryEnvelope):
    filters: WorkFilters
    total: int
    has_more: bool
    next_cursor: str | None
    counts: FactoryCounts
    items: list[WorkProjection]


class WorkDetailResponse(FactoryEnvelope):
    work_item: WorkProjection


class RepositoryListResponse(FactoryEnvelope):
    filters: FactoryFilters
    total: int
    has_more: bool
    next_cursor: str | None
    repositories: list[RepositoryProjection]


class RepositoryDetailResponse(FactoryEnvelope):
    repository: RepositoryProjection


class FactoryErrorDetail(FactoryModel):
    code: Literal["invalid_filter", "invalid_cursor", "resource_not_found", "projection_failed"]
    message: str


class FactoryErrorResponse(FactoryModel):
    detail: FactoryErrorDetail
