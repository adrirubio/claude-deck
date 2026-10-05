"""Public-safe reported human actions; no decision, dispatch or merge authority."""
import asyncio
import re
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.coordination import CoordinationDisposition
from app.models.database import AgentTeamPreset, GithubApprovalRequest, GithubAttemptScopeRevision, GithubWorkItem, TeamGithubScope
from app.services.github_client import github_client
from app.services.github_operator_context_service import (
    SECTION_START, SECTION_END, bind_attempt, check as check_context, covered_by_leader,
    describe, github_operator_context_service, instruction_template,
)


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
                base_ref = pull.get("base", {}).get("ref")
                if not isinstance(base_ref, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,255}", base_ref):
                    base_ref = None
                result = {"state":pull["state"], "merged":pull["merged"], "draft":pull["draft"], "head_sha":head,
                          "base_ref":base_ref,
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
            return {}
        observed = await self.observe_pulls(scope, {a.pull_request_number for a in actions}, client, fresh=True)
        for action in actions:
            pull = observed[action.pull_request_number]
            if pull["state"] == "unavailable":
                raise CoordinationError("human_action_pr_unavailable")
            if (pull["state"] != "open" or pull["merged"] or pull["head_sha"] != action.expected_head_sha
                or (action.kind == "merge_pr" and pull["draft"])):
                raise CoordinationError("human_action_pr_changed")
        return observed

    async def dispatch_snapshot(self, db, scopes):
        actions, complete = [], True
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
                GithubApprovalRequest.request_kind, GithubApprovalRequest.scope_revision_id).join(GithubWorkItem, GithubWorkItem.id==GithubApprovalRequest.work_item_id).where(
                GithubWorkItem.scope_id.in_(scope_by_id), GithubApprovalRequest.status=="pending",
                GithubApprovalRequest.dispatch_nonce==GithubWorkItem.dispatch_nonce).order_by(GithubApprovalRequest.id).limit(65))).all())
        approvals = await pending_approvals()
        pending = {a.work_item_id:a.request_kind for a in approvals}
        async def checkpoint_revisions():
            return list((await db.execute(select(GithubAttemptScopeRevision.id,GithubAttemptScopeRevision.work_item_id,
                GithubAttemptScopeRevision.revision,GithubAttemptScopeRevision.status,GithubAttemptScopeRevision.recovery_checkpoint_stage)
                .join(GithubWorkItem,GithubWorkItem.id==GithubAttemptScopeRevision.work_item_id).where(
                GithubWorkItem.scope_id.in_(scope_by_id),GithubAttemptScopeRevision.dispatch_nonce==GithubWorkItem.dispatch_nonce,
                GithubAttemptScopeRevision.status.in_(["proposed","approved"])).order_by(GithubAttemptScopeRevision.id).limit(65))).all())
        revisions = await checkpoint_revisions()
        approval_revisions = {a.work_item_id:a.scope_revision_id for a in approvals}
        checkpoint_by_item = {}
        for revision in revisions:
            selected = approval_revisions.get(revision.work_item_id)
            if (selected==revision.id or (selected is None and revision.status=="approved")):
                previous = checkpoint_by_item.get(revision.work_item_id)
                if previous is None or revision.revision>previous.revision:
                    checkpoint_by_item[revision.work_item_id]=revision
        if len(approvals)>64 or len(revisions)>64:
            complete = False
        for item in items[:64]:
            scope = scope_by_id[item.scope_id]
            checkpoint = checkpoint_by_item.get(item.id)
            operator_checkpoint = item.dispatch_status=="escalated" and checkpoint is not None and checkpoint.recovery_checkpoint_stage in {"decision_hold","ack_hold"}
            if item.id in pending and not operator_checkpoint and not (item.dispatch_status in {"escalated","failed"} and pending[item.id]=="initial"):
                continue  # Pending Leader decisions do not become operator requests.
            fallback = any((item.status_note or "").startswith(prefix) for prefix in (
                "Auto-merge blocked", "Auto-merge budget exhausted", "Auto-merge failed", "Auto-merge retry budget exhausted"))
            if item.dispatch_status == "ready_for_review" and ((scope.merge_policy != "human" and not fallback) or item.attempt_phase == "diagnostic"):
                continue
            kind = "inspect_checkpoint" if operator_checkpoint else (
                "review_pr" if item.dispatch_status in {"ready_for_review", "awaiting_human_review"} else "inspect_attempt")
            actions = [a for a in actions if not (a["scope_id"]==scope.id and a["issue_number"]==item.issue_number
                and a.get("legacy_reason")=="human_merge" and kind=="review_pr")]
            actions.append({"scope_id":scope.id, "repo":f"{scope.repo_owner}/{scope.repo_name}", "issue_number":item.issue_number,
                "kind":kind, "readiness":"requested", "pull_request_number":item.pr_number if kind=="review_pr" else None,
                "expected_head_sha":item.last_verified_sha if kind=="review_pr" else None, "work_item_id":item.id,
                "required_actor":"operator", "gate_reason":item.escalation_reason or item.dispatch_status,
                "dispatch_epoch":f"{item.dispatched_at or item.created_at}:{item.approval_round_count}:{item.active_scope_revision}",
                "checkpoint_epoch":f"{checkpoint.id}:{checkpoint.revision}:{checkpoint.status}:{checkpoint.recovery_checkpoint_stage}" if operator_checkpoint else None,
                "dispatch_issue_type":item.issue_type,
                "source":"dispatch", "assessment_current":True, "assessment_status":item.dispatch_status,
                "last_assessed_at":None, "evidence_issue_numbers":[item.issue_number], "prerequisite_issue_numbers":[], "state":"requested"})
            if kind=="review_pr" and item.pr_number is None:
                actions[-1]["state"]="pr_identity_unavailable";complete=False
        return {"actions":actions, "items":items, "approvals":approvals, "revisions":revisions, "complete":complete}

    async def summary(self, db, preset_id, client=None, *, include_templates=False):
        from app.services.github_coordination_service import CoordinationError, github_coordination_service as coordination
        if await db.get(AgentTeamPreset, preset_id) is None:
            raise CoordinationError("preset_not_found", 404)
        scopes = list((await db.scalars(select(TeamGithubScope).where(
            TeamGithubScope.preset_id == preset_id).order_by(TeamGithubScope.id).limit(33))).all())
        scope_snapshot = [(s.id,s.repo_owner,s.repo_name,s.merge_policy,s.enabled,s.updated_at) for s in scopes]
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
                actor_conflict = entry.operator_decision_required and entry.required_actor != "operator"
                if actor_conflict:
                    complete = False
                if not reported and (entry.required_actor == "operator" or entry.operator_decision_required):
                    # Older Leaders report a gate without declaring it ready for action.
                    kind = "milestone_acceptance" if entry.reason in {"m1a_acceptance","m1b_acceptance"} else (
                        entry.reason if entry.reason in {"pilot_decision","scope_clarification"} else "scope_clarification")
                    reported = [{"kind":kind, "legacy_reason":entry.reason, "readiness":"waiting_for_prerequisites", "pull_request_number":None,
                                 "expected_head_sha":None, "prerequisite_issue_numbers":[]}]
                if actor_conflict:
                    # Preserve a legacy reported gate without asserting that it is ready.
                    reported = [{**action, "readiness":"waiting_for_prerequisites"} for action in reported]
                for action in reported:
                    actions.append({**action, "scope_id":scope.id, "repo":summary["repo"], "issue_number":entry.issue_number,
                        "gate_reason":entry.reason,
                        "required_actor":entry.required_actor,
                        "source":"leader", "assessment_current":current, "assessment_status":summary["status"],
                        "last_assessed_at":summary["last_assessed_at"], "evidence_issue_numbers":entry.evidence_issue_numbers,
                        "state":action["readiness"] if current else "historical"})
        snapshot = await self.dispatch_snapshot(db, scopes[:32])
        complete = complete and snapshot["complete"]
        for action in actions:
            if action["source"]=="leader" and action["kind"] in {"inspect_attempt", "inspect_checkpoint"}:
                item = next((i for i in snapshot["items"] if i.scope_id==action["scope_id"] and i.issue_number==action["issue_number"]), None)
                if item:
                    bind_attempt(action, item)
                    direct = next((a for a in snapshot["actions"] if a["scope_id"]==action["scope_id"] and a["issue_number"]==action["issue_number"]), None)
                    action["checkpoint_epoch"] = direct.get("checkpoint_epoch") if direct else None
                    if not direct or direct["kind"] != action["kind"]:
                        action.update(state="historical", assessment_current=False)
                        complete = False
        for dispatch_action in snapshot["actions"]:
            actions = [a for a in actions if not (a["scope_id"]==dispatch_action["scope_id"]
                and a["issue_number"]==dispatch_action["issue_number"]
                and a.get("legacy_reason")=="human_merge" and dispatch_action["kind"]=="review_pr")]
            if not covered_by_leader(dispatch_action, [a for a in actions if a["assessment_current"]]):
                actions.append(dispatch_action)
        items, approvals, revisions = snapshot["items"], snapshot["approvals"], snapshot["revisions"]
        def item_identity(item):
            return (item.id,item.scope_id,item.issue_number,item.issue_type,item.dispatch_status,item.pr_number,item.last_verified_sha,
                    item.attempt_phase,item.status_note,item.dispatch_nonce,item.active_scope_revision,
                    item.dispatched_at,item.approval_round_count)
        item_snapshot = [item_identity(i) for i in items]
        # End the DB transaction before bounded GitHub reads; presentation writes no rows.
        await db.commit()
        refs_by_scope = {s.id:{a["pull_request_number"] for a in actions if a["scope_id"]==s.id and a["pull_request_number"]} for s in scopes[:32]}
        issue_refs = {s.id:{a["issue_number"] for a in actions if a["scope_id"]==s.id} for s in scopes[:32]}
        if sum(len(refs) for refs in issue_refs.values()) > 32:
            complete = False
        async def pull_observations():
            return dict(await asyncio.gather(*(
                self._scope_pulls(scope, refs_by_scope[scope.id], client) for scope in scopes[:32] if refs_by_scope[scope.id])))
        if sum(len(refs) for refs in refs_by_scope.values()) > 8:
            complete = False
            observed_by_scope = {}
            contexts = await github_operator_context_service.observe(scopes[:32], issue_refs, client)
        else:
            observed_by_scope, contexts = await asyncio.gather(
                pull_observations(), github_operator_context_service.observe(scopes[:32], issue_refs, client))
        for scope in scopes[:32]:
            pulls = observed_by_scope.get(scope.id, {})
            for action in actions:
                if action["scope_id"]!=scope.id or not action["pull_request_number"]:
                    continue
                pull = pulls.get(action["pull_request_number"], {"state":"unavailable"})
                action["pr_state"] = pull["state"]
                action["pr_observed_at"] = pull.get("observed_at")
                action["pr_observation_expires_at"] = pull.get("expires_at")
                action["observed_head_sha"] = pull.get("head_sha")
                action["pr_base_ref"] = pull.get("base_ref")
                if pull.get("expires_at"):
                    expires.append(pull["expires_at"])
                if pull["state"]=="closed":
                    action["state"] = "resolved"
                elif pull["state"]=="unavailable":
                    action["state"] = "pr_unavailable";complete = False
                elif (not action["expected_head_sha"] and not (action["source"]=="dispatch" and action.get("dispatch_issue_type")=="design"
                    and action["assessment_status"]=="awaiting_human_review")) or (
                    action["expected_head_sha"] and pull["head_sha"]!=action["expected_head_sha"]):
                    action["state"] = "head_changed";complete = False
                elif action["kind"]=="merge_pr" and pull["draft"]:
                    action["state"] = "waiting_for_prerequisites"
        for action in actions:
            action.update(describe(action))
            observation = contexts.get((action["scope_id"], action["issue_number"]), {"state":"unavailable"})
            context_state, updated_at = check_context(action, observation)
            action.update(instructions_state=context_state, instructions_updated_at=updated_at,
                          instructions_checked_at=observation.get("observed_at"))
            if observation.get("expires_at"):
                expires.append(observation["expires_at"])
            if action["state"] in {"requested", "waiting_for_prerequisites"} and context_state != "current":
                action["state"] = "context_pending"
                complete = False
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
        latest_dispatch = await self.dispatch_snapshot(db, scopes[:32])
        latest_items = latest_dispatch["items"]
        latest_scopes = list((await db.scalars(select(TeamGithubScope).where(TeamGithubScope.preset_id==preset_id)
            .order_by(TeamGithubScope.id).limit(33).execution_options(populate_existing=True))).all())
        scope_changed = scope_snapshot != [(s.id,s.repo_owner,s.repo_name,s.merge_policy,s.enabled,s.updated_at) for s in latest_scopes]
        if (item_snapshot != [item_identity(i) for i in latest_items] or approvals != latest_dispatch["approvals"]
            or revisions != latest_dispatch["revisions"] or scope_changed):
            complete = False
            for action in actions:
                if (action["source"]=="dispatch" or scope_changed) and action["state"]!="resolved":
                    action["state"] = "historical"; action["assessment_current"] = False
        deduped = {}
        rank = {"requested":4,"context_pending":3,"waiting_for_prerequisites":2,"historical":1}
        for action in actions:
            key = (action["repo"],action["kind"],action["pull_request_number"] or action["issue_number"])
            previous = deduped.get(key)
            if previous is None or rank.get(action["state"],0)>rank.get(previous["state"],0):
                deduped[key] = action
        actions = list(deduped.values())
        now = datetime.utcnow()
        result = {"preset_id":preset_id, "checked_at":now,
                "observation_expires_at":min([now + timedelta(seconds=60), *expires]),
                "coverage_complete":bool(complete), "actions":actions}
        if include_templates:
            result.update(section_start=SECTION_START, section_end=SECTION_END)
            for action in actions:
                action["context_template"] = instruction_template(action)
        return result

    async def _scope_pulls(self, scope, refs, client):
        return scope.id, await self.observe_pulls(scope, refs, client)


github_operator_attention_service = GithubOperatorAttentionService()
