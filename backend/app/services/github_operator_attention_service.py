"""Public-safe reported human actions; no decision, dispatch or merge authority."""
import asyncio
import re
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.coordination import CoordinationDisposition
from app.models.database import AgentTeamPreset, GithubApprovalRequest, GithubWorkItem, TeamGithubScope
from app.services.github_client import github_client


class GithubOperatorAttentionService:
    def __init__(self):
        self._pr_cache = {}

    async def observe_pulls(self, scope, numbers, client=None, *, fresh=False):
        client = client or github_client
        async def read(number):
            key = (scope.id, scope.repo_owner, scope.repo_name, scope.updated_at, number)
            cached = self._pr_cache.get(key)
            if not fresh and cached and cached[0] > time.monotonic():
                return number, cached[1]
            observed_at = datetime.utcnow()
            try:
                pull = await asyncio.wait_for(client.get_pull(scope.repo_owner, scope.repo_name, number), timeout=8)
                head = pull.get("head", {}).get("sha")
                repo = pull.get("base", {}).get("repo", {}).get("full_name")
                if (type(pull.get("number")) is not int or pull["number"] != number
                    or not isinstance(repo, str) or repo.casefold() != f"{scope.repo_owner}/{scope.repo_name}".casefold()
                    or pull.get("state") not in {"open", "closed"}
                    or not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head)
                    or type(pull.get("merged")) is not bool or type(pull.get("draft")) is not bool):
                    raise ValueError("invalid_pr_observation")
                result = {"state":pull["state"], "merged":pull["merged"], "draft":pull["draft"], "head_sha":head,
                          "observed_at":observed_at, "expires_at":observed_at + timedelta(seconds=60)}
            except Exception:
                result = {"state":"unavailable", "observed_at":observed_at,
                          "expires_at":observed_at + timedelta(seconds=10)}
            # Fixed capacity bounds process memory; cache stores only safe GitHub identity.
            if len(self._pr_cache) >= 64:
                self._pr_cache.pop(next(iter(self._pr_cache)))
            self._pr_cache[key] = (time.monotonic() + (10 if result["state"]=="unavailable" else 60), result)
            return number, result
        assert len(numbers) <= 8
        return dict(await asyncio.gather(*(read(n) for n in sorted(set(numbers)))))

    async def validate_actions(self, scope, entries, client):
        from app.services.github_coordination_service import CoordinationError
        actions = [action for entry in entries for action in entry.human_actions if action.pull_request_number]
        if not actions:
            return
        observed = await self.observe_pulls(scope, {a.pull_request_number for a in actions}, client, fresh=True)
        for action in actions:
            pull = observed[action.pull_request_number]
            if pull["state"] == "unavailable":
                raise CoordinationError("human_action_pr_unavailable")
            if (pull["state"] != "open" or pull["merged"] or pull["head_sha"] != action.expected_head_sha
                or (action.kind == "merge_pr" and pull["draft"])):
                raise CoordinationError("human_action_pr_changed")

    async def summary(self, db, preset_id, client=None):
        from app.services.github_coordination_service import CoordinationError, github_coordination_service as coordination
        if await db.get(AgentTeamPreset, preset_id) is None:
            raise CoordinationError("preset_not_found", 404)
        scopes = list((await db.scalars(select(TeamGithubScope).where(
            TeamGithubScope.preset_id == preset_id).order_by(TeamGithubScope.id).limit(33))).all())
        complete = len(scopes) <= 32
        actions, expires, versions = [], [], {}
        for scope in scopes[:32]:
            summary = await coordination.summary(db, scope.id)
            if not summary["enabled"]:
                continue
            versions[scope.id] = summary["version"]
            current = summary["assessment_current"]
            complete = complete and current
            if current and summary["observation_expires_at"]:
                expires.append(summary["observation_expires_at"])
            for raw in summary["entries"]:
                try:
                    entry = CoordinationDisposition.model_validate(raw)
                except ValueError:
                    complete = False
                    continue
                reported = [a.model_dump() for a in entry.human_actions]
                if not reported and entry.required_actor == "operator":
                    # Older Leaders report a gate without declaring it ready for action.
                    kind = entry.reason if entry.reason in {"pilot_decision", "milestone_acceptance", "scope_clarification"} else "scope_clarification"
                    reported = [{"kind":kind, "legacy_reason":entry.reason, "readiness":"waiting_for_prerequisites", "pull_request_number":None,
                                 "expected_head_sha":None, "prerequisite_issue_numbers":[]}]
                for action in reported:
                    actions.append({**action, "scope_id":scope.id, "repo":summary["repo"], "issue_number":entry.issue_number,
                        "source":"leader", "assessment_current":current, "assessment_status":summary["status"],
                        "last_assessed_at":summary["last_assessed_at"], "evidence_issue_numbers":entry.evidence_issue_numbers,
                        "state":action["readiness"] if current else "historical"})
        # Existing dispatched review/recovery actions remain visible on the Roster too.
        scope_by_id = {s.id:s for s in scopes[:32]}
        items = list((await db.scalars(select(GithubWorkItem).where(
            GithubWorkItem.scope_id.in_(scope_by_id),
            GithubWorkItem.dispatch_status.in_(["ready_for_review", "awaiting_human_review", "escalated", "failed"]),
        ).order_by(GithubWorkItem.id).limit(65))).all())
        if len(items) > 64:
            complete = False
        async def pending_approvals():
            return list((await db.execute(select(GithubApprovalRequest.id, GithubApprovalRequest.work_item_id,
                GithubApprovalRequest.request_kind).join(GithubWorkItem, GithubWorkItem.id==GithubApprovalRequest.work_item_id).where(
                GithubWorkItem.scope_id.in_(scope_by_id), GithubApprovalRequest.status=="pending",
                GithubApprovalRequest.dispatch_nonce==GithubWorkItem.dispatch_nonce).order_by(GithubApprovalRequest.id).limit(65))).all())
        approvals = await pending_approvals()
        pending = {a.work_item_id:a.request_kind for a in approvals}
        if len(approvals)>64:
            complete = False
        for item in items[:64]:
            scope = scope_by_id[item.scope_id]
            if item.id in pending and not (item.dispatch_status in {"escalated","failed"} and pending[item.id]=="initial"):
                continue  # Pending Leader decisions do not become operator requests.
            fallback = any((item.status_note or "").startswith(prefix) for prefix in (
                "Auto-merge blocked", "Auto-merge budget exhausted", "Auto-merge failed", "Auto-merge retry budget exhausted"))
            if item.dispatch_status == "ready_for_review" and ((scope.merge_policy != "human" and not fallback) or item.attempt_phase == "diagnostic"):
                continue
            kind = "review_pr" if item.dispatch_status in {"ready_for_review", "awaiting_human_review"} else "inspect_attempt"
            actions = [a for a in actions if not (a["scope_id"]==scope.id and a["issue_number"]==item.issue_number
                and a.get("legacy_reason")=="human_merge" and kind=="review_pr")]
            actions.append({"scope_id":scope.id, "repo":f"{scope.repo_owner}/{scope.repo_name}", "issue_number":item.issue_number,
                "kind":kind, "readiness":"requested", "pull_request_number":item.pr_number if kind=="review_pr" else None,
                "expected_head_sha":item.last_verified_sha if kind=="review_pr" else None, "work_item_id":item.id,
                "source":"dispatch", "assessment_current":True, "assessment_status":item.dispatch_status,
                "last_assessed_at":None, "evidence_issue_numbers":[item.issue_number], "prerequisite_issue_numbers":[], "state":"requested"})
        item_snapshot = [(i.id, i.dispatch_status, i.pr_number, i.last_verified_sha, i.attempt_phase) for i in items]
        # End the DB transaction before bounded GitHub reads; presentation writes no rows.
        await db.commit()
        refs_by_scope = {s.id:{a["pull_request_number"] for a in actions if a["scope_id"]==s.id and a["pull_request_number"]} for s in scopes[:32]}
        if sum(len(refs) for refs in refs_by_scope.values()) > 8:
            complete = False
            observed_by_scope = {}
        else:
            observed_by_scope = dict(await asyncio.gather(*(
                self._scope_pulls(scope, refs_by_scope[scope.id], client) for scope in scopes[:32] if refs_by_scope[scope.id])))
        for scope in scopes[:32]:
            pulls = observed_by_scope.get(scope.id, {})
            for action in actions:
                if action["scope_id"]!=scope.id or not action["pull_request_number"]:
                    continue
                pull = pulls.get(action["pull_request_number"], {"state":"unavailable"})
                action["pr_state"] = pull["state"]
                action["pr_observed_at"] = pull.get("observed_at")
                action["pr_observation_expires_at"] = pull.get("expires_at")
                if pull.get("expires_at"):
                    expires.append(pull["expires_at"])
                if pull["state"]=="closed":
                    action["state"] = "resolved"
                elif pull["state"]=="unavailable":
                    action["state"] = "pr_unavailable";complete = False
                elif not action["expected_head_sha"] or pull["head_sha"]!=action["expected_head_sha"]:
                    action["state"] = "head_changed";complete = False
                elif action["kind"]=="merge_pr" and pull["draft"]:
                    action["state"] = "waiting_for_prerequisites"
        # Network reads can overlap a correction, OFF/HOLD, routing or dispatch
        # change. Retain the original report as history instead of mixing revisions.
        for scope_id, version in versions.items():
            latest = await coordination.summary(db, scope_id)
            row = await coordination.state(db, scope_id)
            if not latest["assessment_current"] or latest["version"] != version or row.version != latest["version"]:
                complete = False
                for action in actions:
                    if action["scope_id"]==scope_id and action["source"]=="leader":
                        action["assessment_current"] = False
                        if action["state"] not in {"resolved", "head_changed", "pr_unavailable"}:
                            action["state"] = "historical"
        latest_items = list((await db.scalars(select(GithubWorkItem).where(
            GithubWorkItem.scope_id.in_(scope_by_id),
            GithubWorkItem.dispatch_status.in_(["ready_for_review", "awaiting_human_review", "escalated", "failed"]),
        ).order_by(GithubWorkItem.id).limit(65).execution_options(populate_existing=True))).all())
        if (item_snapshot != [(i.id, i.dispatch_status, i.pr_number, i.last_verified_sha, i.attempt_phase) for i in latest_items]
            or approvals != await pending_approvals()):
            complete = False
            for action in actions:
                if action["source"]=="dispatch" and action["state"]!="resolved":
                    action["state"] = "historical"; action["assessment_current"] = False
        deduped = {}
        rank = {"requested":3,"waiting_for_prerequisites":2,"historical":1}
        for action in actions:
            key = (action["repo"],action["kind"],action["pull_request_number"] or action["issue_number"])
            previous = deduped.get(key)
            if previous is None or rank.get(action["state"],0)>rank.get(previous["state"],0):
                deduped[key] = action
        actions = list(deduped.values())
        now = datetime.utcnow()
        return {"preset_id":preset_id, "checked_at":now,
                "observation_expires_at":min([now + timedelta(seconds=60), *expires]),
                "coverage_complete":bool(complete), "actions":actions}

    async def _scope_pulls(self, scope, refs, client):
        return scope.id, await self.observe_pulls(scope, refs, client)


github_operator_attention_service = GithubOperatorAttentionService()
