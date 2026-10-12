"""Collect existing team signals. This read grants no execution authority."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from app.models.database import (
    AgentTeamPreset, GithubApprovalRequest, GithubOwnerObservationPause,
    GithubWorkItem, GithubWorkspace, TeamGithubScope,
)
from app.models.factory_schemas import (
    AgentTeamSummaryResponse, TeamRemainingWork, TeamSummaryAttention, TeamSummaryHumanAction,
)
from app.services.github_coordination_service import hold_code
from app.services.github_operator_attention_service import github_operator_attention_service
from app.services.github_work_progress_service import github_work_progress_service

_ACTORS = ("owner", "leader", "operator", "controller")
_KINDS = {"review_pr", "merge_pr", "inspect_attempt", "inspect_checkpoint", "milestone_acceptance",
          "pilot_decision", "scope_clarification", "provide_evidence"}
_STATES = {"requested", "context_pending", "waiting_for_prerequisites", "historical", "resolved",
           "head_changed", "pr_unavailable", "pr_identity_unavailable"}


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AgentTeamSummaryService:
    def __init__(self, *, progress=None, attention=None, observation_seconds=8, item_limit=64):
        self.progress = progress or github_work_progress_service
        self.attention = attention or github_operator_attention_service
        self.observation_seconds = min(8, max(0.001, observation_seconds))
        self.item_limit = min(64, max(1, item_limit))

    async def _snapshot(self, db, preset_id):
        team = (await db.execute(select(AgentTeamPreset.id, AgentTeamPreset.description,
            AgentTeamPreset.parent_issue_url, AgentTeamPreset.autonomy_enabled, AgentTeamPreset.updated_at)
            .where(AgentTeamPreset.id == preset_id))).one_or_none()
        if team is None:
            return None
        scopes = tuple((await db.execute(select(TeamGithubScope.id, TeamGithubScope.repo_owner,
            TeamGithubScope.repo_name, TeamGithubScope.merge_policy, TeamGithubScope.enabled,
            TeamGithubScope.updated_at).where(TeamGithubScope.preset_id == preset_id)
            .order_by(TeamGithubScope.id).limit(33))).all())
        selected = (select(GithubWorkItem).join(TeamGithubScope,
            TeamGithubScope.id == GithubWorkItem.scope_id).where(TeamGithubScope.preset_id == preset_id,
            GithubWorkItem.dispatch_status.not_in(("merged", "completed"))))
        count = await db.scalar(select(func.count()).select_from(selected.subquery()))
        # Private bindings exist only in the local equality check. Never serialize them.
        items = tuple((await db.execute(selected.with_only_columns(
            GithubWorkItem.id, GithubWorkItem.scope_id, GithubWorkItem.issue_number,
            GithubWorkItem.dispatch_status, GithubWorkItem.escalation_reason, GithubWorkItem.dispatch_nonce,
            GithubWorkItem.owner_slot_id, GithubWorkItem.active_scope_revision, GithubWorkItem.attempt_phase,
            GithubWorkItem.dispatch_head_ref, GithubWorkItem.last_verified_sha, GithubWorkItem.updated_at,
            GithubWorkspace.id.label("workspace_id"), GithubWorkspace.lease_token,
            GithubWorkspace.leased_at, GithubWorkspace.path,
        ).outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
            .order_by(GithubWorkItem.id).limit(self.item_limit + 1))).all())
        approvals = tuple((await db.execute(select(GithubApprovalRequest.id, GithubApprovalRequest.status,
            GithubApprovalRequest.dispatch_nonce, GithubApprovalRequest.approval_round)
            .join(GithubWorkItem, GithubWorkItem.id == GithubApprovalRequest.work_item_id)
            .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
            .where(TeamGithubScope.preset_id == preset_id, GithubApprovalRequest.status == "pending")
            .order_by(GithubApprovalRequest.id).limit(65))).all())
        return team, scopes, items, count, approvals

    async def _pauses(self, db, preset_id):
        return tuple((await db.execute(select(GithubOwnerObservationPause.id,
            GithubOwnerObservationPause.work_item_id, GithubOwnerObservationPause.paused_at,
            GithubOwnerObservationPause.resume_deadline, GithubWorkItem.scope_id, GithubWorkItem.issue_number)
            .join(GithubWorkItem, GithubWorkItem.id == GithubOwnerObservationPause.work_item_id)
            .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
            .where(TeamGithubScope.preset_id == preset_id, GithubOwnerObservationPause.status == "paused",
                   GithubWorkItem.dispatch_status == "escalated",
                   GithubWorkItem.escalation_reason == "owner_observation_pause")
            .order_by(GithubOwnerObservationPause.id).limit(65))).all())

    async def summary(self, db, preset_id):
        started = datetime.now(timezone.utc)
        deadline = asyncio.get_running_loop().time() + self.observation_seconds
        initial = await self._snapshot(db, preset_id)
        if initial is None:
            return None
        team, scope_rows, items, total, approvals = initial
        complete = (total <= self.item_limit and len(items) == total
                    and len(scope_rows) <= 32 and len(approvals) <= 64)
        scopes = [SimpleNamespace(**row._mapping) for row in scope_rows[:32]]
        attention, human_actions, actors, observations = [], [], set(), []
        expires = [started + timedelta(seconds=15)]
        hold = hold_code()
        if hold:
            attention.append(TeamSummaryAttention(code=hold))
            actors.add("operator")

        async def bounded(read):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(read(), timeout=remaining)

        try:
            dispatch = await bounded(lambda: self.attention.dispatch_snapshot(db, scopes))
            complete = complete and dispatch["complete"]
            for action in dispatch["actions"]:
                kind = action.get("kind")
                code = {"inspect_attempt": "attempt_stopped", "inspect_checkpoint": "recovery_decision",
                        "review_pr": "human_review"}.get(kind)
                if code:
                    attention.append(TeamSummaryAttention(code=code, work_item_id=action.get("work_item_id"),
                        scope_id=action["scope_id"], issue_number=action["issue_number"]))
            pauses = await bounded(lambda: self._pauses(db, preset_id))
            complete = complete and len(pauses) <= 64
            for pause in pauses[:64]:
                attention.append(TeamSummaryAttention(code="observation_pause", pause_id=pause.id,
                    work_item_id=pause.work_item_id, scope_id=pause.scope_id, issue_number=pause.issue_number,
                    observed_at=pause.paused_at, resume_deadline=pause.resume_deadline))
                actors.add("operator")
            for item in items[:self.item_limit]:
                if item.dispatch_status == "escalated" and item.escalation_reason in {
                    "owner_idle_timeout", "owner_unavailable", "prepared_owner_unavailable"}:
                    attention.append(TeamSummaryAttention(code="owner_stalled", work_item_id=item.id,
                        scope_id=item.scope_id, issue_number=item.issue_number))
            human = await bounded(lambda: self.attention.summary(db, preset_id))
            complete = complete and human["coverage_complete"]
            expires.append(_utc(human["observation_expires_at"]))
            for action in human["actions"][:64]:
                # Existing action data also contains private context and prose. Use a narrow allowlist.
                kind, state = action.get("kind"), action.get("state")
                if kind not in _KINDS or state not in _STATES:
                    complete = False
                    continue
                human_actions.append(TeamSummaryHumanAction(scope_id=action["scope_id"],
                    issue_number=action["issue_number"], work_item_id=action.get("work_item_id"),
                    kind=kind, state=state, source=action.get("source") if action.get("source") in {
                        "leader", "dispatch"} else "unknown", assessment_current=action.get("assessment_current") is True,
                    pull_request_number=action.get("pull_request_number")))
                if state != "resolved":
                    actors.add("operator")
            complete = complete and len(human["actions"]) <= 64
            for item in items[:self.item_limit]:
                value = await bounded(lambda: self.progress.summary(db, item.id))
                if value is None:
                    complete = False
                    continue
                observations.append(value)
                expires.append(_utc(value.valid_until))
                if value.next_actor in _ACTORS:
                    actors.add(value.next_actor)
        except (TimeoutError, OSError):
            complete = False
            if db.in_transaction():
                await db.rollback()
        # Reuse fresh scalar rows after all asynchronous reads. Never use expired ORM attributes.
        if db.in_transaction():
            await db.rollback()
        final = await self._snapshot(db, preset_id)
        if final is None:
            return None
        changed = final != initial or hold_code() != hold
        now = datetime.now(timezone.utc)
        complete = complete and not changed and min(expires) > now
        known = complete and len(observations) == total and all(
            value.remaining_work.state == "current" and value.remaining_work.effort_low_minutes is not None
            and value.remaining_work.effort_high_minutes is not None
            and value.remaining_work.effort_low_minutes <= value.remaining_work.effort_high_minutes
            and value.remaining_work.confidence != "unknown" for value in observations)
        confidence = min((value.remaining_work.confidence for value in observations),
            key={"low": 0, "medium": 1, "high": 2}.get, default="high") if known else "unknown"
        remaining = TeamRemainingWork(state="known" if known else "unknown", unfinished_items=final[3],
            reported_items=sum(value.remaining_work.state == "current" for value in observations),
            effort_low_minutes=sum(value.remaining_work.effort_low_minutes for value in observations) if known else None,
            effort_high_minutes=sum(value.remaining_work.effort_high_minutes for value in observations) if known else None,
            confidence=confidence, reason="complete" if known else "context_changed" if changed
            else "observation_incomplete" if not complete else "report_unknown")
        final_team = final[0]
        return AgentTeamSummaryResponse(preset_id=preset_id, outcome=final_team.description,
            parent_issue_url=final_team.parent_issue_url, checked_at=now, valid_until=min(expires),
            coverage_complete=complete, hold_code=hold, attention=attention, human_actions=human_actions,
            remaining_work=remaining, next_actors=[actor for actor in _ACTORS if actor in actors],
            next_actor_coverage_complete=complete and len(observations) == total)


agent_team_summary_service = AgentTeamSummaryService()
