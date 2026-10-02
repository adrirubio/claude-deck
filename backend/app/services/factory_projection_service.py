"""Observational factory projections: bulk SQL, bounded runtime reads, no mutations."""
from __future__ import annotations

import base64
import binascii
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, GithubWorkItem, GithubWorkspace,
    MailAgentSession, MailPaneLifecycle, MailTeamMember, TeamGithubScope,
)
from app.models import factory_schemas as wire
from app.services.agent_mail_service import MCP_HEARTBEAT_TTL_SECONDS
from app.services.github_dispatch_scheduler import github_dispatch_scheduler
from app.services.github_work_item_projection import _load_work_item_authority, _work_item_response
from app.services.providers import get_providers


CATEGORY_STATUSES = {
    "queued": ("pending",), "active": ("dispatched", "verifying"),
    "review": ("awaiting_human_review", "ready_for_review"),
    "attention": ("escalated", "failed"), "finished": ("merged", "completed"),
}
STATUS_CATEGORY = {status: category for category, statuses in CATEGORY_STATUSES.items() for status in statuses}

# Schema-v1 summaries never interpolate freeform persisted/private diagnostics.
REASON_SUMMARIES = {
    "unknown": "State needs inspection.",
    "team_paused": "Team automation is paused.", "scope_paused": "Repository intake is paused.",
    "recovery_only_gate": "Normal intake is blocked while recovery mode is active.",
    "scheduler_stopped": "The scheduler is stopped.",
    "runtime_not_observed": "Runtime availability has not been observed.",
    "job_not_scheduled": "Repository intake is not scheduled.",
    "intake_eligible": "Configured intake is available; work eligibility still applies.",
    "work_queued": "Waiting for dispatch.", "checks_running": "Checks are being verified.",
    "owner_ack_required": "Waiting for the assigned owner to acknowledge the plan.",
    "work_assigned": "Work is assigned to the owner.", "human_review": "Ready for human review.",
    "abandoned_by_operator": "Operator requested stop. Retry may remain available.",
    "attempt_escalated": "The attempt is stopped in factory tracking and needs attention.",
    "approval_pending": "Waiting for the designated Leader's decision.",
    "not_escalated": "Only escalated work can be retried.",
    "active_continuation": "Resolve the active continuation before retrying.",
    "pr_preserved": "Resolve the preserved PR before retrying.",
    "retry_eligible": "The existing retry state checks permit retry.",
    "continuation_disabled": "Continuation is disabled for this repository.",
    "continuation_delivery_pending": "The approved continuation is awaiting delivery.",
    "continuation_ack_required": "The owner must acknowledge the approved continuation.",
    "continuation_not_escalated": "Recovery requires an escalated attempt.",
    "continuation_reason_not_allowed": "The existing recovery route does not permit this reason.",
    "continuation_pr_required": "Recovery requires the preserved PR.",
    "workspace_lease_required": "Recovery requires the current workspace lease.",
    "continuation_budget_exhausted": "The existing continuation budget is exhausted.",
}
KNOWN_ESCALATIONS = {
    "abandoned_by_operator", "plan_blocked", "verification_failed", "verification_timeout",
    "ack_timeout", "owner_idle", "owner_unavailable", "continuation_budget_exhausted",
}


class FactoryReadError(ValueError):
    def __init__(self, code: str, status: int):
        self.code, self.status = code, status
        super().__init__({"invalid_filter": "Select valid compatible filters.",
                          "invalid_cursor": "Refresh from start with the selected filters.",
                          "resource_not_found": "The selected resource was not found.",
                          "projection_failed": "Factory observations could not be loaded."}[code])


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class RuntimeSnapshot:
    public: wire.RuntimeObservation
    job_ids: frozenset[str] | None


def observe_runtime() -> RuntimeSnapshot:
    """Read the same active gate as the public predicate; never ensure/start/sync."""
    try:
        mode = "recovery_only" if github_dispatch_scheduler.recovery_only_attempt is not None else "normal"
        scheduler = github_dispatch_scheduler.scheduler
        if scheduler is None:
            state, jobs = "stopped", frozenset()
        else:
            running = scheduler.running
            state = "running" if running is True else "stopped" if running is False else "unknown"
            jobs = frozenset(job.id for job in scheduler.get_jobs())
        return RuntimeSnapshot(wire.RuntimeObservation(
            mode=mode, scheduler_state=state, observed_at=utc_now(),
            reason_code="runtime_not_observed" if state == "unknown" else None,
        ), jobs)
    except Exception:
        return RuntimeSnapshot(wire.RuntimeObservation(mode="unknown", scheduler_state="unknown",
                                                      observed_at=None, reason_code="runtime_not_observed"), None)


def github_identity(scope: TeamGithubScope) -> wire.GithubIdentity:
    owner, name = scope.repo_owner, scope.repo_name
    if not (re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner)
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name) and name not in (".", "..")):
        raise FactoryReadError("projection_failed", 500)
    return wire.GithubIdentity(owner=owner, name=name)


def encode_cursor(kind: str, filters: wire.FactoryFilters, row) -> str:
    value = {"v": 1, "kind": kind, "filters": filters.model_dump(),
             "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(), "id": row.id}
    return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None, kind: str, filters: wire.FactoryFilters):
    if cursor is None:
        return None
    try:
        if not cursor or len(cursor) > 2048:
            raise ValueError
        value = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if (type(value) is not dict or set(value) != {"v", "kind", "filters", "updated_at", "id"}
                or type(value["v"]) is not int or value["v"] != 1 or value["kind"] != kind
                or json.dumps(value["filters"], sort_keys=True) != json.dumps(filters.model_dump(), sort_keys=True)
                or type(value["id"]) is not int
                or not 0 < value["id"] < 2**63 or not isinstance(value["updated_at"], str)):
            raise ValueError
        timestamp = datetime.fromisoformat(value["updated_at"])
        if timestamp.tzinfo is None:
            raise ValueError
        return naive_utc(timestamp), value["id"]
    except (ValueError, TypeError, KeyError, binascii.Error, OverflowError):
        raise FactoryReadError("invalid_cursor", 422) from None


async def validate_filters(db: AsyncSession, filters: wire.FactoryFilters) -> None:
    if filters.provider is not None and filters.provider not in {p.id for p in get_providers()}:
        raise FactoryReadError("invalid_filter", 422)
    if filters.scope_id is not None:
        scope = await db.get(TeamGithubScope, filters.scope_id)
        if scope is None:
            raise FactoryReadError("resource_not_found", 404)
        if filters.team_id is not None and scope.preset_id != filters.team_id:
            raise FactoryReadError("invalid_filter", 422)
    if filters.team_id is not None and await db.get(AgentTeamPreset, filters.team_id) is None:
        raise FactoryReadError("resource_not_found", 404)


def work_query(filters: wire.FactoryFilters):
    query = (select(GithubWorkItem, TeamGithubScope, AgentTeamPreset)
             .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
             .join(AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
             .outerjoin(AgentTeamSlot, and_(AgentTeamSlot.id == GithubWorkItem.owner_slot_id,
                                           AgentTeamSlot.preset_id == TeamGithubScope.preset_id)))
    if filters.team_id is not None:
        query = query.where(AgentTeamPreset.id == filters.team_id)
    if filters.scope_id is not None:
        query = query.where(TeamGithubScope.id == filters.scope_id)
    if filters.provider is not None:
        query = query.where(AgentTeamSlot.provider == filters.provider)
    category = getattr(filters, "category", "all")
    if category == "unknown":
        query = query.where(GithubWorkItem.dispatch_status.not_in(tuple(STATUS_CATEGORY)))
    elif category != "all":
        query = query.where(GithubWorkItem.dispatch_status.in_(CATEGORY_STATUSES[category]))
    return query


def repository_query(filters: wire.FactoryFilters):
    query = select(TeamGithubScope, AgentTeamPreset).join(AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
    if filters.team_id is not None:
        query = query.where(AgentTeamPreset.id == filters.team_id)
    if filters.scope_id is not None:
        query = query.where(TeamGithubScope.id == filters.scope_id)
    if filters.provider is not None:
        # A scope has no owner. Provider scope views match the team's configured
        # roster; work views still filter strictly by each item's actual owner.
        query = query.where(exists(select(AgentTeamSlot.id).where(
            AgentTeamSlot.preset_id == TeamGithubScope.preset_id, AgentTeamSlot.provider == filters.provider)))
    return query


async def counts(db: AsyncSession, query) -> wire.FactoryCounts:
    selected = query.with_only_columns(GithubWorkItem.id, GithubWorkItem.dispatch_status).subquery()
    rows = (await db.execute(select(selected.c.dispatch_status, func.count())
                             .group_by(selected.c.dispatch_status))).all()
    value = dict.fromkeys(wire.FactoryCounts.model_fields, 0)
    for status, count in rows:
        category = STATUS_CATEGORY.get(status, "unknown")
        value[category] += count
        value["total"] += count
    return wire.FactoryCounts(**value)


def intake(scope, team, runtime: RuntimeSnapshot) -> wire.IntakeProjection:
    if not team.autonomy_enabled:
        code, state = "team_paused", "blocked"
    elif not scope.enabled:
        code, state = "scope_paused", "blocked"
    elif runtime.public.mode == "recovery_only":
        code, state = "recovery_only_gate", "blocked"
    elif runtime.public.scheduler_state == "stopped":
        code, state = "scheduler_stopped", "blocked"
    elif runtime.public.mode == "unknown" or runtime.public.scheduler_state == "unknown" or runtime.job_ids is None:
        code, state = "runtime_not_observed", "unknown"
    elif github_dispatch_scheduler._job_id(scope.repo_owner, scope.repo_name) not in runtime.job_ids:
        code, state = "job_not_scheduled", "blocked"
    else:
        code, state = "intake_eligible", "eligible"
    return wire.IntakeProjection(state=state, reason_code=code, summary=REASON_SUMMARIES[code])


def poll(scope, effective_intake, now) -> wire.PollObservation:
    if effective_intake.state == "blocked":
        freshness = "suspended"
    elif effective_intake.state == "unknown":
        freshness = "unknown"
    elif scope.last_polled_at is None:
        freshness = "never_polled"
    elif naive_utc(scope.last_polled_at) < naive_utc(now) - timedelta(seconds=2 * settings.github_dispatch_interval_seconds):
        freshness = "stale"
    else:
        freshness = "fresh"
    return wire.PollObservation(interval_seconds=settings.github_dispatch_interval_seconds,
                                last_polled_at=scope.last_polled_at, freshness=freshness)


async def repository_projections(db, rows, runtime, now):
    if not rows:
        return []
    # Bulk observation includes teams outside the selected filters. Independent
    # scopes remain separate; this is an advisory collision, not arbitration.
    collisions = (await db.execute(select(TeamGithubScope)
        .join(AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
        .where(TeamGithubScope.enabled.is_(True), AgentTeamPreset.autonomy_enabled.is_(True)))).scalars().all()
    by_identity = defaultdict(list)
    for candidate in collisions:
        identity = github_identity(candidate)
        by_identity[(identity.owner.lower(), identity.name.lower(), candidate.dispatch_label)].append(candidate.id)
    result = []
    for scope, team in rows:
        identity = github_identity(scope)
        configured = bool(team.autonomy_enabled and scope.enabled)
        others = sorted(i for i in by_identity[(identity.owner.lower(), identity.name.lower(), scope.dispatch_label)]
                        if i != scope.id) if configured else []
        effective = intake(scope, team, runtime)
        result.append(wire.RepositoryProjection(
            scope_id=scope.id, team=wire.TeamReference(id=team.id, name=team.name), github=identity,
            team_automation_enabled=team.autonomy_enabled, scope_enabled=scope.enabled,
            configured_enabled=configured, intake=effective, poll=poll(scope, effective, now),
            overlap=wire.OverlapObservation(state="warning" if others else "none", other_scope_ids=others),
        ))
    return result


async def actor_evidence(db, team_ids, authority):
    slots = (await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.preset_id.in_(team_ids))
                            .order_by(AgentTeamSlot.position, AgentTeamSlot.id))).scalars().all()
    members = (await db.execute(select(MailTeamMember).where(
        MailTeamMember.team_preset_id.in_(team_ids), MailTeamMember.participant_kind == "team_slot"))).scalars().all()
    member_ids = [m.id for m in members]
    sessions = (await db.execute(select(MailAgentSession).where(MailAgentSession.member_id.in_(member_ids)))).scalars().all()
    bindings = (await db.execute(select(AgentPaneBinding).where(AgentPaneBinding.preset_id.in_(team_ids)))).scalars().all()
    retired = (await db.execute(select(MailPaneLifecycle).where(
        MailPaneLifecycle.pane_pid.in_([b.pane_pid for b in bindings])))).scalars().all()
    return slots, members, sessions, bindings, {(r.pane_pid, r.pane_proc_start) for r in retired}


def association(slot, member, sessions, bindings, retired, now):
    if slot is None or member is None:
        return wire.SessionAssociation(state="unknown")
    candidates = [s for s in sessions if s.member_id == member.id and s.source == "mcp"
                  and s.capability_token_hash is not None and s.team_preset_id == slot.preset_id
                  and s.team_slot_id == slot.id]
    if not candidates:
        return wire.SessionAssociation(state="unknown")
    live = [s for s in candidates if s.closed_at is None and s.mailbox_status == "connected"
            and naive_utc(s.last_seen_at) >= naive_utc(now) - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS)]
    if len(live) > 1:
        return wire.SessionAssociation(state="ambiguous")
    if not live:
        # A stale heartbeat with a PID can still be live under the legacy
        # predicate. Without a process observation, retain unknown, not offline.
        offline = all(s.closed_at is not None or (s.pid is None and (
            s.mailbox_status == "offline" or naive_utc(s.last_seen_at) < naive_utc(now)
            - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS))) for s in candidates)
        return wire.SessionAssociation(state="offline" if offline else "unknown")
    current = live[0]
    verified = [b for b in bindings if b.slot_id == slot.id and b.preset_id == slot.preset_id
                and current.bound_pane_pid == b.pane_pid and current.bound_pane_proc_start == b.pane_proc_start
                and (b.pane_pid, b.pane_proc_start) not in retired]
    if len(verified) != 1:
        return wire.SessionAssociation(state="unknown")
    return wire.SessionAssociation(state="bound", observed_provider=current.provider,
        bridge_target=wire.BridgeTarget(team_id=slot.preset_id, slot_id=slot.id,
                                       member_id=member.id, session_id=current.id))


def waiting(item, legacy, owner_session):
    status = item.dispatch_status
    if status in ("merged", "completed"):
        return None
    if legacy.pending_approval_status == "pending":
        actor, code = "leader", "approval_pending"
    elif status == "pending":
        actor, code = "unknown", "work_queued"
    elif status == "verifying":
        actor, code = "unknown", "checks_running"
    elif status == "dispatched":
        actor, code = "owner", "owner_ack_required" if item.ack_received_at is None else "work_assigned"
    elif status in ("ready_for_review", "awaiting_human_review"):
        actor, code = "human", "human_review"
    elif status in ("escalated", "failed"):
        actor = "operator"
        code = ("abandoned_by_operator" if item.escalation_reason == "abandoned_by_operator" else
                "attempt_escalated" if item.escalation_reason in KNOWN_ESCALATIONS else "unknown")
    else:
        actor, code = "unknown", "unknown"
    return wire.WaitingActor(actor=actor, reason_code=code, summary=REASON_SUMMARIES[code])


def actions(legacy):
    retry_code = "retry_eligible" if legacy.retry_allowed else legacy.retry_block_code
    retry_known = retry_code in REASON_SUMMARIES
    result = [wire.FactoryAction(name="retry", state="eligible" if legacy.retry_allowed else "blocked" if retry_known else "unknown",
        block_code=None if legacy.retry_allowed else retry_code if retry_known else "unknown",
        reason=REASON_SUMMARIES.get(retry_code, REASON_SUMMARIES["unknown"]), required_actor="leader")]
    # Prepared-attempt resume is a different remedy from continuation proposal.
    # Do not relabel continuation policy as that route's eligibility predicate.
    result.append(wire.FactoryAction(name="resume_attempt", state="unknown", block_code="unknown",
        reason="Open attempt recovery to check available actions.", required_actor="operator"))
    for name, actor in (("escalate_attempt", "operator"), ("cancel_continuation_request", "owner"),
                        ("cancel_active_revision", "operator"), ("release_recovery_checkpoint", "operator")):
        result.append(wire.FactoryAction(name=name, state="unknown", block_code="unknown",
            reason="Open attempt recovery to check available actions.", required_actor=actor))
    return result


async def work_projections(db, rows, now):
    if not rows:
        return []
    authority = await _load_work_item_authority(db, [item for item, _, _ in rows])
    team_ids = {team.id for _, _, team in rows}
    slots, members, sessions, bindings, retired = await actor_evidence(db, team_ids, authority)
    slots_by_id = {s.id: s for s in slots}
    members_by_id = {m.id: m for m in members}
    members_by_slot = defaultdict(list)
    leaders = {}
    for slot in slots:
        if slot.enabled:
            leaders.setdefault(slot.preset_id, slot)
    for member in members:
        slot = slots_by_id.get(member.team_slot_id)
        if slot is not None and slot.preset_id == member.team_preset_id:
            members_by_slot[slot.id].append(member)
    workspaces = (await db.execute(select(GithubWorkspace).where(
        GithubWorkspace.leased_item_id.in_([row[0].id for row in rows])))).scalars().all()
    by_item = {w.leased_item_id: w for w in workspaces}
    providers = {p.id: p.display_name for p in get_providers()}
    result = []
    for item, scope, team in rows:
        auth = authority[item.id]
        workspace = by_item.get(item.id)
        legacy = _work_item_response(item, scope, workspace.path if workspace else None,
            active_revision=auth.active_revision, pending_approval=auth.pending_approval,
            pending_revision=auth.pending_revision, continuation_revision_count=auth.revision_count,
            continuation_failed_head_count=auth.failed_head_count)
        slot = slots_by_id.get(item.owner_slot_id)
        if slot is not None and slot.preset_id != team.id:
            slot = None
        owner_members = members_by_slot.get(slot.id, []) if slot is not None else []
        member = owner_members[0] if len(owner_members) == 1 else None
        leader_slot = leaders.get(team.id)
        leader_members = members_by_slot.get(leader_slot.id, []) if leader_slot else []
        leader_member = leader_members[0] if len(leader_members) == 1 else None
        designated_id = auth.pending_approval.leader_member_id if auth.pending_approval else item.ack_approver_member_id
        if designated_id is not None:
            designated = members_by_id.get(designated_id)
            designated_slot = slots_by_id.get(designated.team_slot_id) if designated else None
            if (designated is None or designated.team_preset_id != team.id
                    or designated_slot is None or designated_slot.preset_id != team.id):
                leader_member, leader_slot = None, None
            else:
                leader_member = designated
                leader_slot = designated_slot
        owner_session = association(slot, member, sessions, bindings, retired, now)
        if len(owner_members) > 1:
            owner_session = wire.SessionAssociation(state="ambiguous")
        leader_session = association(leader_slot, leader_member, sessions, bindings, retired, now)
        offline_slot = (slot if owner_session.state == "offline" else
                        leader_slot if leader_session.state == "offline" else None)
        safe = {name: getattr(legacy, name) for name in wire.SafeWorkItem.model_fields}
        if (item.pr_number is None or item.attempt_phase == "diagnostic"
                or not re.fullmatch(r"[0-9a-fA-F]{40}", item.last_verified_sha or "")):
            safe["last_verified_sha"] = None
        identity = github_identity(scope)
        result.append(wire.WorkProjection(
            item=wire.SafeWorkItem(**safe), team=wire.TeamReference(id=team.id, name=team.name),
            repository=wire.WorkRepository(scope_id=scope.id, github=identity,
                                            display_name=f"{identity.owner}/{identity.name}"),
            category=STATUS_CATEGORY.get(item.dispatch_status, "unknown"),
            owner=wire.OwnerReference(slot_id=slot.id, member_id=member.id if member else None,
                name=slot.display_name, configured_provider=slot.provider, provider_label=providers.get(slot.provider)) if slot else None,
            approver=wire.ApproverReference(slot_id=leader_slot.id, member_id=leader_member.id if leader_member else None,
                source="first_enabled_slot" if leaders.get(team.id) == leader_slot else "unknown") if leader_slot else None,
            waiting=waiting(item, legacy, owner_session), session=owner_session, approver_session=leader_session,
            policy=wire.WorkPolicy(merge_policy=scope.merge_policy, max_verification_retries=scope.max_verification_retries,
                                  max_approval_rounds=scope.max_approval_rounds, continuation_enabled=scope.continuation_enabled),
            workspace=wire.WorkspaceAssociation(id=workspace.id, state="leased") if workspace else None,
            actions=actions(legacy), links=wire.LinkHints(
                mail=wire.MailHint(team_id=team.id, slot_id=slot.id, member_id=member.id) if slot and member else None,
                launch_plan=wire.LaunchPlanHint(team_id=team.id, slot_id=offline_slot.id) if offline_slot else None,
                bridge_target=owner_session.bridge_target),
        ))
    return result


async def overview(db, filters):
    await validate_filters(db, filters)
    runtime, now = observe_runtime(), utc_now()
    selected_counts = await counts(db, work_query(filters))
    scopes = (await db.execute(repository_query(filters))).all()
    automation = {name: 0 for name in wire.AutomationSummary.model_fields if name != "runtime"}
    for scope, team in scopes:
        automation["configured_scopes"] += 1
        if not (scope.enabled and team.autonomy_enabled):
            automation["paused_scopes"] += 1
            continue
        automation["enabled_scopes"] += 1
        effective = intake(scope, team, runtime)
        field = {"eligible": "intake_eligible_scopes", "blocked": "intake_blocked_scopes", "unknown": "intake_unknown_scopes"}[effective.state]
        automation[field] += 1
        freshness = poll(scope, effective, now).freshness
        automation["never_polled_scopes"] += freshness == "never_polled"
        automation["stale_scopes"] += freshness == "stale"
    return wire.OverviewResponse(generated_at=now, filters=filters, counts=selected_counts,
                                 automation=wire.AutomationSummary(runtime=runtime.public, **automation))


async def work_list(db, filters, limit, cursor):
    await validate_filters(db, filters)
    after = decode_cursor(cursor, "work", filters)
    query = work_query(filters)
    selected_counts = await counts(db, query)
    if after:
        timestamp, row_id = after
        query = query.where(or_(GithubWorkItem.updated_at < timestamp,
                               and_(GithubWorkItem.updated_at == timestamp, GithubWorkItem.id < row_id)))
    rows = (await db.execute(query.order_by(GithubWorkItem.updated_at.desc(), GithubWorkItem.id.desc()).limit(limit + 1))).all()
    has_more, rows = len(rows) > limit, rows[:limit]
    now = utc_now()
    return wire.WorkListResponse(generated_at=now, filters=filters, total=selected_counts.total,
        has_more=has_more, next_cursor=encode_cursor("work", filters, rows[-1][0]) if has_more else None,
        counts=selected_counts, items=await work_projections(db, rows, now))


async def work_detail(db, item_id):
    rows = (await db.execute(work_query(wire.FactoryFilters()).where(GithubWorkItem.id == item_id))).all()
    if not rows:
        raise FactoryReadError("resource_not_found", 404)
    now = utc_now()
    return wire.WorkDetailResponse(generated_at=now, work_item=(await work_projections(db, rows, now))[0])


async def repositories(db, filters, limit, cursor):
    await validate_filters(db, filters)
    after = decode_cursor(cursor, "repositories", filters)
    query = repository_query(filters)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    if after:
        timestamp, row_id = after
        query = query.where(or_(TeamGithubScope.updated_at < timestamp,
                               and_(TeamGithubScope.updated_at == timestamp, TeamGithubScope.id < row_id)))
    rows = (await db.execute(query.order_by(TeamGithubScope.updated_at.desc(), TeamGithubScope.id.desc()).limit(limit + 1))).all()
    has_more, rows = len(rows) > limit, rows[:limit]
    runtime, now = observe_runtime(), utc_now()
    return wire.RepositoryListResponse(generated_at=now, filters=filters, total=total, has_more=has_more,
        next_cursor=encode_cursor("repositories", filters, rows[-1][0]) if has_more else None,
        repositories=await repository_projections(db, rows, runtime, now))


async def repository_detail(db, scope_id):
    rows = (await db.execute(repository_query(wire.FactoryFilters(scope_id=scope_id)))).all()
    if not rows:
        raise FactoryReadError("resource_not_found", 404)
    runtime, now = observe_runtime(), utc_now()
    return wire.RepositoryDetailResponse(generated_at=now,
        repository=(await repository_projections(db, rows, runtime, now))[0])
