"""Read campaign counts without changing dispatch or approval authority."""
from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import re
import time

from sqlalchemy import select

from app.config import settings
from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, TeamGithubScope
from app.models.factory_schemas import (
    CampaignAreaGroup, CampaignDecision, CampaignDoneItem, CampaignQueuedItem,
    CampaignUnderWayItem, TeamCampaignSummary,
)
from app.models.schemas import PlannedCampaignDecision

_PARENT = re.compile(r"https://github\.com/([^/]+)/([^/]+)/issues/([1-9][0-9]*)\Z")
_STATE_PHRASES = {
    "dispatched": "building it",
    "verifying": "waiting for checks",
    "ready_for_review": "reviewing it",
    "awaiting_human_review": "waiting for you",
    "escalated": "waiting for you",
}
_DECISION_TEXT = {
    "review_pr": "Review the pull request.",
    "merge_pr": "Decide whether to merge the pull request.",
    "inspect_attempt": "Decide how to continue the work.",
    "inspect_checkpoint": "Decide how to recover the work.",
    "milestone_acceptance": "Decide whether to accept the milestone.",
    "pilot_decision": "Decide whether to continue the trial.",
    "scope_clarification": "Clarify the work scope.",
    "provide_evidence": "Provide the required evidence.",
}


@dataclass(frozen=True)
class BacklogObservation:
    expires_at: float
    # None means unavailable. An empty tuple means a complete, empty backlog.
    issues: tuple[tuple[int, tuple[str, ...]], ...] | None


def _parent(url):
    match = _PARENT.fullmatch(url or "")
    return (match[1], match[2], int(match[3])) if match else None


def _branch(value):
    return value.removeprefix("origin/") if value else None


class AgentTeamCampaignService:
    def __init__(self, *, interval_seconds=None, clock=time.monotonic):
        self.interval_seconds = max(1, interval_seconds or settings.github_dispatch_interval_seconds)
        self.clock = clock
        self._cache: dict[tuple, BacklogObservation] = {}

    async def _scopes(self, db, preset_id=None, scope_id=None):
        query = select(TeamGithubScope.id, TeamGithubScope.preset_id, TeamGithubScope.created_at,
            TeamGithubScope.repo_owner, TeamGithubScope.repo_name, TeamGithubScope.base_ref,
            AgentTeamPreset.parent_issue_url, AgentTeamPreset.backlog_milestone).join(
            AgentTeamPreset, AgentTeamPreset.id == TeamGithubScope.preset_id)
        if preset_id is not None:
            query = query.where(TeamGithubScope.preset_id == preset_id)
        if scope_id is not None:
            query = query.where(TeamGithubScope.id == scope_id)
        return (await db.execute(query.order_by(TeamGithubScope.id))).all()

    @staticmethod
    def _key(scope):
        return (scope.id, scope.preset_id, scope.created_at, scope.repo_owner, scope.repo_name,
                scope.parent_issue_url, scope.backlog_milestone)

    async def _read_backlog(self, scope, client):
        owner, repo = scope.repo_owner, scope.repo_name
        parent = _parent(scope.parent_issue_url)
        if scope.backlog_milestone:
            milestones = await client.list_milestones(owner, repo)
            matches = [m for m in milestones if m.get("title") == scope.backlog_milestone]
            if len(matches) != 1:
                return None
            milestone = matches[0].get("number")
        elif parent and parent[:2] == (owner, repo):
            issue = await client.get_issue(owner, repo, parent[2])
            milestone_data = issue.get("milestone") if issue else None
            milestone = milestone_data.get("number") if isinstance(milestone_data, dict) else None
        else:
            return None
        if type(milestone) is not int or milestone <= 0:
            return None
        issues = await client.list_milestone_issues(owner, repo, milestone)
        observed = {}
        for issue in issues:
            if not isinstance(issue, dict):
                return None
            if "pull_request" in issue:
                continue
            number, labels = issue.get("number"), issue.get("labels")
            if (type(number) is not int or number <= 0 or not isinstance(labels, list)
                    or not all(isinstance(label, dict) and isinstance(label.get("name"), str) for label in labels)):
                return None
            if parent == (owner, repo, number):
                continue
            value = tuple(sorted({label["name"] for label in labels}))
            if number in observed and observed[number] != value:
                return None
            observed[number] = value
        return tuple(sorted(observed.items()))

    async def refresh_scope(self, db, scope, client):
        """Use the existing poll client. Keep this read outside dispatch decisions."""
        scope_id = scope.id
        rows = await self._scopes(db, scope_id=scope_id)
        if not rows:
            return
        captured = rows[0]
        key, started = self._key(captured), self.clock()
        cached = self._cache.get(key)
        if cached and cached.expires_at > started:
            return
        try:
            issues = await asyncio.wait_for(self._read_backlog(captured, client), timeout=8)
        except Exception:
            # Never expose credential-bearing request objects or raw GitHub errors.
            issues = None
        fresh = await self._scopes(db, scope_id=scope_id)
        if not fresh or self._key(fresh[0]) != key:
            return
        self._cache = {k: v for k, v in self._cache.items() if v.expires_at > started}
        if len(self._cache) >= 1024:
            oldest = min(self._cache, key=lambda k: self._cache[k].expires_at)
            self._cache.pop(oldest)
        self._cache[key] = BacklogObservation(started + self.interval_seconds, issues)

    async def summary(self, db, preset_id, human_actions=()):
        scopes = await self._scopes(db, preset_id=preset_id)
        by_scope = {scope.id: scope for scope in scopes}
        now = self.clock()
        observations = {scope.id: self._cache.get(self._key(scope)) for scope in scopes}
        available = bool(scopes) and all(observation is not None and observation.expires_at > now
            and observation.issues is not None for observation in observations.values())
        backlog = {}
        if available:
            for scope in scopes:
                for number, labels in observations[scope.id].issues:
                    backlog[(scope.repo_owner, scope.repo_name, number)] = labels
        rows = (await db.execute(select(GithubWorkItem.id, GithubWorkItem.scope_id,
            GithubWorkItem.issue_number, GithubWorkItem.issue_title, GithubWorkItem.dispatch_status,
            GithubWorkItem.dispatch_base_ref, GithubWorkItem.auto_merged_at,
            AgentTeamSlot.display_name).join(TeamGithubScope,
                TeamGithubScope.id == GithubWorkItem.scope_id).outerjoin(AgentTeamSlot,
                AgentTeamSlot.id == GithubWorkItem.owner_slot_id).where(
                TeamGithubScope.preset_id == preset_id).order_by(GithubWorkItem.id))).all()
        work = {}
        for row in rows:
            scope = by_scope[row.scope_id]
            key = (scope.repo_owner, scope.repo_name, row.issue_number)
            if _parent(scope.parent_issue_url) == key:
                continue
            if not available or key in backlog:
                work[key] = row
        done, under_way, queued = [], [], []
        for row in work.values():
            scope = by_scope[row.scope_id]
            if (row.dispatch_status == "merged" and _branch(row.dispatch_base_ref)
                    and _branch(row.dispatch_base_ref) == _branch(scope.base_ref)):
                done.append(row)
            elif row.dispatch_status in _STATE_PHRASES:
                under_way.append(CampaignUnderWayItem(title=row.issue_title,
                    owner_short_name=row.display_name.split()[0] if row.display_name and row.display_name.split() else None,
                    state_phrase=_STATE_PHRASES[row.dispatch_status]))
            elif row.dispatch_status == "pending":
                queued.append(CampaignQueuedItem(title=row.issue_title))
        done.sort(key=lambda row: (row.auto_merged_at or datetime.min, row.id), reverse=True)
        groups = Counter()
        if available:
            slot_labels = (await db.scalars(select(AgentTeamSlot.area_labels).where(
                AgentTeamSlot.preset_id == preset_id).order_by(AgentTeamSlot.position, AgentTeamSlot.id))).all()
            areas = list(dict.fromkeys(label for labels in slot_labels for label in (labels or []) if isinstance(label, str)))
            for key, labels in backlog.items():
                if key not in work:
                    groups[next((area for area in areas if area in labels), "Other")] += 1
        decisions = []
        for action in human_actions:
            if (action.assessment_current and action.state in {"requested", "context_pending"}
                    and action.kind in _DECISION_TEXT):
                text = "Complete the action details." if action.state == "context_pending" else _DECISION_TEXT[action.kind]
                decision = CampaignDecision(text=text, state="now")
                if decision not in decisions:
                    decisions.append(decision)
        planned = await db.scalar(select(AgentTeamPreset.planned_decisions).where(AgentTeamPreset.id == preset_id))
        for value in planned or []:
            # Legacy or manually damaged data cannot insert raw objects into the response.
            try:
                decision = PlannedCampaignDecision.model_validate(value)
            except ValueError:
                continue
            decisions.append(CampaignDecision(text=decision.text, state=decision.state))
        return TeamCampaignSummary(backlog_state="available" if available else "backlog unavailable",
            done_count=len(done), latest_done=[CampaignDoneItem(title=row.issue_title,
                merged_at=row.auto_merged_at) for row in done[:3]],
            under_way_count=len(under_way), under_way=under_way, queued_count=len(queued), queued=queued,
            not_started_count=sum(groups.values()) if available else None,
            not_started_groups=[CampaignAreaGroup(area=area, count=count) for area, count in sorted(groups.items())],
            decisions_ahead=decisions)


agent_team_campaign_service = AgentTeamCampaignService()
