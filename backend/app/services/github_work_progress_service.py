"""Publication observations and next actions; no dispatch authority changes."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

import httpx
from pydantic import ValidationError
from sqlalchemy import JSON, exists, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import settings
from app.models.database import (
    AgentTeamPreset, GithubApprovalRequest, GithubBacklogCoordination,
    GithubWorkItem, GithubWorkspace, TeamGithubScope,
)
from app.models.github_work_progress import GithubWorkProgressSnapshot
from app.models.github_work_progress_schemas import (
    GithubPublicationObservation, GithubWorkProgressResponse,
)
from app.services.github_client import GithubClientResponseError, github_client
from app.services.github_coordination_service import hold_code
from app.services.github_work_progress_observation import (
    ProgressObservationError, WorkspaceProgressContext, workspace_progress_observer,
)

_SHA = re.compile(r"[0-9a-f]{40}")
_REPO_PART = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,250}")
_CACHE_SECONDS = 15


@dataclass(frozen=True)
class _SavedSnapshot:
    observed_at: datetime
    identity: dict
    observation: dict


@dataclass(frozen=True)
class _SourceTarget:
    workspace: WorkspaceProgressContext
    head_ref: str | None
    repo_owner: str
    repo_name: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value else None


def _ref(value: object) -> bool:
    return (isinstance(value, str) and _REF.fullmatch(value) is not None
            and all(part and not part.startswith(".") and not part.endswith((".", ".lock"))
                    for part in value.split("/")) and ".." not in value)


def _base_identity(item, scope) -> dict:
    return {"scope_id": scope.id, "repo_owner": scope.repo_owner,
            "repo_name": scope.repo_name, "repo_path": scope.repo_path,
            "created_at": _iso(item.created_at), "dispatch_nonce": item.dispatch_nonce,
            "owner_slot_id": item.owner_slot_id, "head_ref": item.dispatch_head_ref}


def _identity(item, scope, workspace) -> dict:
    return {**_base_identity(item, scope), "workspace_id": workspace.id,
            "workspace_path": workspace.path, "workspace_kind": workspace.kind,
            "leased_at": _iso(workspace.leased_at)}


def _historical(snapshot, reason: str) -> GithubPublicationObservation:
    if snapshot is not None:
        try:
            return GithubPublicationObservation.model_validate(snapshot.observation).model_copy(
                update={"state": "historical", "reason": reason})
        except (ValidationError, TypeError, ValueError):
            pass
    return GithubPublicationObservation(state="unavailable", reason=reason)


def _next_step(item, scope, preset, pending, hold: str | None) -> tuple[str, str, str]:
    if item.dispatch_status in {"merged", "completed"}:
        return "complete", "none", "This tracked item is complete."
    if hold:
        return "paused", "operator", "Read the safety hold and its current issue instructions."
    if not scope.enabled or not preset.autonomy_enabled:
        return "paused", "operator", "Review the paused automation and its current issue instructions."
    if item.dispatch_status in {"escalated", "failed"}:
        return "intervention", "operator", "Read the issue and guarded recovery details."
    if pending:
        return "plan_review", "leader", "Review the pending plan through the supported approval process."
    if item.dispatch_status == "awaiting_human_review":
        return "review", "operator", "Read the human summary and review the design PR."
    if item.handoff_state:
        return "handoff", "leader", "Reconcile the recorded handoff and its responsible owner."
    if item.dispatch_status == "pending":
        return "queue", "leader", "Reconcile dependencies, routing, and available capacity."
    if item.dispatch_status == "ready_for_review":
        if item.attempt_phase == "diagnostic":
            return "diagnostic_review", "leader", "Reconcile diagnostic evidence through the existing recovery process."
        fallback = any((item.status_note or "").startswith(prefix) for prefix in (
            "Auto-merge blocked", "Auto-merge budget exhausted",
            "Auto-merge failed", "Auto-merge retry budget exhausted",
        ))
        if scope.merge_policy == "human" or fallback:
            return "review", "operator", "Read the human summary and exact-head review and CI evidence."
        return "review", "controller", "Check the configured merge requirements and current PR evidence."
    if item.dispatch_status in {"pr_opened", "verifying"}:
        return "ci", "controller", "Observe current PR checks. Independent review remains a separate gate."
    if item.dispatch_status == "dispatched":
        if item.ack_received_at is None:
            return "planning", "owner", "Prepare the plan or acknowledge its supported approval."
        return "implementation", "owner", "Continue approved work and publish a safe draft checkpoint."
    return "unknown", "leader", "Reconcile the current item before assigning its next action."


class GithubWorkProgressService:
    def __init__(self, observer=None, client=None):
        self.observer = observer or workspace_progress_observer
        self.client = client or github_client

    async def _rows(self, db: AsyncSession, item_id: int, *, final=False):
        columns = [GithubWorkItem, TeamGithubScope, AgentTeamPreset, GithubWorkspace]
        if final:
            columns.extend([
                select(GithubApprovalRequest.id).where(
                    GithubApprovalRequest.work_item_id == GithubWorkItem.id,
                    GithubApprovalRequest.dispatch_nonce == GithubWorkItem.dispatch_nonce,
                    GithubApprovalRequest.approval_round == GithubWorkItem.approval_round_count,
                    GithubApprovalRequest.status == "pending",
                ).correlate(GithubWorkItem).limit(1).scalar_subquery(),
                select(GithubBacklogCoordination.last_polled_at).where(
                    GithubBacklogCoordination.scope_id == TeamGithubScope.id,
                ).correlate(TeamGithubScope).scalar_subquery(),
            ])
        return (await db.execute(
            select(*columns)
            .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
            .join(AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
            .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
            .where(GithubWorkItem.id == item_id)
            .execution_options(populate_existing=True)
        )).one_or_none()

    async def _observe(self, target, previous, now):
        context = target.workspace
        local = await self.observer.read(context)
        result = GithubPublicationObservation(
            state="current", observed_at=now, local_sha=local.sha,
            tracked_changes=local.tracked_changes, untracked_files=local.untracked_files,
        )
        if not _ref(target.head_ref):
            result.state = "unavailable"; result.reason = "branch_not_assigned"
        elif local.branch != target.head_ref:
            result.state = "unavailable"
            result.reason = "detached_head" if local.branch is None else "branch_mismatch"
        elif not all(part not in {".", ".."} and _REPO_PART.fullmatch(part or "")
                     for part in (target.repo_owner, target.repo_name)):
            result.state = "unavailable"; result.reason = "remote_unavailable"
        else:
            result.destination_url = (
                f"https://github.com/{target.repo_owner}/{target.repo_name}/tree/{target.head_ref}")
            try:
                remote = await asyncio.wait_for(self.client.get_ref(
                    target.repo_owner, target.repo_name, target.head_ref,
                    token=settings.github_token), timeout=4)
                if remote is None:
                    # GitHub also uses 404 for an inaccessible private repo.
                    # No confirmed head is not proof of an unpublished branch.
                    result.state = "unavailable"; result.reason = "remote_unavailable"
                else:
                    if not isinstance(remote, dict):
                        raise GithubClientResponseError("invalid_progress_ref")
                    obj = remote.get("object")
                    sha = obj.get("sha") if isinstance(obj, dict) else None
                    if (remote.get("ref") != f"refs/heads/{target.head_ref}"
                            or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                            or obj.get("type") != "commit"):
                        raise GithubClientResponseError("invalid_progress_ref")
                    result.published_sha = sha
                    result.publication_time_source = "github_head_observation"
                    result.publication_first_observed_at = (
                        previous.publication_first_observed_at
                        if previous and previous.published_sha == sha else now)
                    result.relation, result.unpublished_commits = await self.observer.compare(
                        context, local.sha, sha)
            except ProgressObservationError as error:
                result.relation = "unknown"; result.reason = error.reason
            except (GithubClientResponseError, httpx.HTTPError, TimeoutError):
                result.state = "unavailable"; result.reason = "remote_unavailable"
        if not await self.observer.confirm(context, local):
            raise ProgressObservationError("changed_during_read")
        return result

    async def summary(self, db: AsyncSession, item_id: int) -> GithubWorkProgressResponse | None:
        rows = await self._rows(db, item_id)
        if rows is None:
            return None
        item, scope, preset, workspace = rows
        started_identity = _base_identity(item, scope)
        started_created_at = item.created_at
        workspace_identity = _identity(item, scope, workspace) if workspace else None
        leased_at = workspace.leased_at if workspace else None
        lease = workspace.lease_token if workspace else None
        target = (_SourceTarget(
            WorkspaceProgressContext(scope.repo_path, workspace.path, workspace.kind),
            item.dispatch_head_ref, scope.repo_owner, scope.repo_name,
        ) if workspace else None)
        now = datetime.now(timezone.utc)
        cached_row = await db.get(GithubWorkProgressSnapshot, item_id)
        snapshot = (_SavedSnapshot(cached_row.observed_at, deepcopy(cached_row.identity),
                                   deepcopy(cached_row.observation)) if cached_row else None)
        matching = (snapshot if snapshot and isinstance(snapshot.identity, dict)
                    and all(snapshot.identity.get(key) == value
                            for key, value in started_identity.items()) else None)
        if workspace is None or lease is None:
            publication = _historical(matching, "workspace_not_leased")
        elif (matching and matching.identity == workspace_identity
              and timedelta(0) <= now - _utc(matching.observed_at) < timedelta(seconds=_CACHE_SECONDS)):
            try:
                publication = GithubPublicationObservation.model_validate(matching.observation)
            except (ValidationError, TypeError, ValueError):
                publication = _historical(None, "snapshot_unavailable")
        else:
            identity = workspace_identity
            # Used for the conditional write only. Never put this private value
            # in an observation, cache identity, log, or API response.
            prior = _historical(matching, "snapshot_unavailable") if matching else None
            try:
                publication = await asyncio.wait_for(
                    self._observe(target, prior, now), timeout=8)
            except ProgressObservationError as error:
                publication = _historical(matching, error.reason)
            except (TimeoutError, OSError):
                publication = _historical(matching, "observation_timeout")
            else:
                # Keep the last trustworthy joint observation when a new read
                # is incomplete. Its times and values remain historical.
                if publication.state != "current" and matching is not None:
                    publication = _historical(matching, publication.reason or "snapshot_unavailable")
                # The facts are advisory. Write only our cache row, conditional
                # on the exact registered item and lease still being current.
                guard = exists(select(GithubWorkItem.id)
                    .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
                    .join(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                    .where(
                        GithubWorkItem.id == item_id,
                        GithubWorkItem.created_at == started_created_at,
                        GithubWorkItem.dispatch_nonce == identity["dispatch_nonce"],
                        GithubWorkItem.owner_slot_id == identity["owner_slot_id"],
                        GithubWorkItem.dispatch_head_ref == identity["head_ref"],
                        TeamGithubScope.id == identity["scope_id"],
                        TeamGithubScope.repo_owner == identity["repo_owner"],
                        TeamGithubScope.repo_name == identity["repo_name"],
                        TeamGithubScope.repo_path == identity["repo_path"],
                        GithubWorkspace.id == identity["workspace_id"],
                        GithubWorkspace.path == identity["workspace_path"],
                        GithubWorkspace.kind == identity["workspace_kind"],
                        GithubWorkspace.leased_at == leased_at,
                        GithubWorkspace.lease_token == lease,
                    ))
                data = publication.model_dump(mode="json")
                table = GithubWorkProgressSnapshot.__table__
                try:
                    if snapshot is None:
                        statement = insert(table).from_select(
                            ["work_item_id", "observed_at", "identity", "observation"],
                            select(literal(item_id), literal(now.replace(tzinfo=None)),
                                   literal(identity, type_=JSON), literal(data, type_=JSON))
                            .where(guard, ~exists(select(table.c.work_item_id)
                                .where(table.c.work_item_id == item_id))),
                        )
                    else:
                        statement = update(table).where(
                            table.c.work_item_id == item_id, guard,
                            table.c.observed_at <= now.replace(tzinfo=None),
                        ).values(observed_at=now.replace(tzinfo=None),
                                 identity=identity, observation=data)
                    changed = await db.execute(statement)
                    if changed.rowcount != 1:
                        await db.rollback()
                        publication = _historical(matching, "changed_during_read")
                    else:
                        await db.commit()
                except (IntegrityError, OperationalError):
                    await db.rollback()
                    publication = _historical(matching, "snapshot_unavailable")
        # End any old read snapshot. Every path receives one coherent final
        # item/scope/preset/workspace/approval projection after asynchronous work.
        if db.in_transaction():
            await db.rollback()
        rows = await self._rows(db, item_id, final=True)
        if rows is None:
            return None
        item, scope, preset, final_workspace, pending, polled_at = rows
        if _base_identity(item, scope) != started_identity:
            publication = GithubPublicationObservation(state="unavailable", reason="changed_during_read")
        elif publication.state == "current" and (
            final_workspace is None or final_workspace.lease_token != lease
            or _identity(item, scope, final_workspace) != workspace_identity
        ):
            publication = publication.model_copy(update={
                "state": "historical",
                "reason": "workspace_not_leased" if final_workspace is None or not final_workspace.lease_token
                else "changed_during_read",
            })
        phase, actor, action = _next_step(item, scope, preset, pending, hold_code())
        if phase in {"implementation", "planning"} and (
            final_workspace is None or not final_workspace.lease_token
        ):
            phase, actor, action = ("workspace_wait", "leader",
                "Reconcile the missing workspace lease before work continues.")
        check_head = item.last_verified_sha
        if not isinstance(check_head, str) or not _SHA.fullmatch(check_head):
            check_head = None
        return GithubWorkProgressResponse(
            work_item_id=item_id, dispatch_nonce=item.dispatch_nonce,
            owner_slot_id=item.owner_slot_id, checked_at=datetime.now(timezone.utc),
            valid_until=min(now + timedelta(seconds=_CACHE_SECONDS),
                _utc(publication.observed_at) + timedelta(seconds=_CACHE_SECONDS))
                if publication.state == "current" and publication.observed_at
                else now + timedelta(seconds=_CACHE_SECONDS),
            phase=phase, next_actor=actor, next_action=action,
            next_poll_expected_at=(_utc(polled_at) + timedelta(
                seconds=settings.github_dispatch_interval_seconds)) if polled_at else None,
            last_check_head=check_head, publication=publication,
        )


github_work_progress_service = GithubWorkProgressService()
