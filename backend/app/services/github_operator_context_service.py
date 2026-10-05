"""Check public issue instructions. This service never writes to GitHub."""
import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone

from app.services.github_client import github_client

SECTION_START = "<!-- deck:operator-actions:start -->"
SECTION_END = "<!-- deck:operator-actions:end -->"
_RECORD = re.compile(r"<!-- deck:operator-action:([0-9a-f]{24}):start -->(.*?)"
                     r"<!-- deck:operator-action:end -->", re.S)
_LABEL = re.compile(r"^\*\*([A-Za-z ]+):\*\* *(.*)$", re.M)
_STATES = {"requested": "Requested", "waiting_for_prerequisites": "Waiting for prerequisites"}
_ROLES = {"operator", "leader", "owner", "reviewer", "none"}
_TITLES = {"review_pr":"Review the pull request", "merge_pr":"Review and merge the pull request",
           "pilot_decision":"Record the pilot decision", "milestone_acceptance":"Record milestone acceptance",
           "provide_evidence":"Provide the required evidence", "scope_clarification":"Clarify the remaining scope",
           "inspect_attempt":"Inspect the stopped attempt", "inspect_checkpoint":"Inspect the recovery checkpoint"}
_MAX_BODY = 65536
_MAX_AGE = timedelta(hours=24)


def leader_action(scope, entry, action):
    return {**action.model_dump(), "scope_id": scope.id,
            "repo": f"{scope.repo_owner}/{scope.repo_name}", "issue_number": entry.issue_number,
            "gate_reason": entry.reason, "required_actor": entry.required_actor,
            "source": "leader", "evidence_issue_numbers": entry.evidence_issue_numbers}


def bind_attempt(action, item):
    action.update(work_item_id=item.id,
                  dispatch_epoch=f"{item.dispatched_at or item.created_at}:{item.approval_round_count}:{item.active_scope_revision}")


def covered_by_leader(action, reports):
    return any(report.get("source") == "leader" and not report.get("legacy_reason")
               and report.get("required_actor") == "operator"
               and all(report.get(key) == action.get(key) for key in (
                   "scope_id", "issue_number", "kind", "pull_request_number", "expected_head_sha"))
               and (action["kind"] not in {"inspect_attempt", "inspect_checkpoint"}
                    or report.get("dispatch_epoch") == action.get("dispatch_epoch"))
               for report in reports)


def request_id(action):
    # Only public identity enters this digest. Never use a capability, nonce,
    # lease, raw status note or private snapshot hash as a public request ID.
    identity = {key: action.get(key) for key in (
        "scope_id", "repo", "issue_number", "source", "kind", "gate_reason",
        "required_actor", "pull_request_number", "expected_head_sha", "pr_base_ref",
        "dispatch_epoch", "checkpoint_epoch", "observed_head_sha",
    )}
    # A reported exact head is stable across observation refreshes.
    if identity["expected_head_sha"]:
        identity["observed_head_sha"] = None
    identity["evidence"] = sorted(action.get("evidence_issue_numbers", []))
    identity["prerequisites"] = sorted(action.get("prerequisite_issue_numbers", []))
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def instruction_template(action):
    identifier = request_id(action)
    issue_url = f"https://github.com/{action['repo']}/issues/{action['issue_number']}"
    lines = [f"<!-- deck:operator-action:{identifier}:start -->",
             f"<!-- deck:operator-record scope={action['scope_id']} source={action['source']} -->",
             f"### {instruction_heading(action)}", "",
             f"**Status:** {_STATES.get(action.get('readiness'), 'Requested')}",
             f"**Responsible:** {action.get('required_actor', 'operator')} — WRITE_RESPONSIBLE_PERSON",
             "**Reason:** WRITE_CURRENT_REASON", "**Action:** WRITE_SPECIFIC_OPERATOR_STEPS",
             "**Done when:** WRITE_COMPLETION_CONDITION",
             "**Updated:** WRITE_UTC_TIMESTAMP", f"**Evidence:** {issue_url}"]
    if action.get("pull_request_number"):
        lines[-1] += f" https://github.com/{action['repo']}/pull/{action['pull_request_number']}"
        lines += [f"**PR target:** {action.get('pr_base_ref') or 'WRITE_PR_TARGET'}",
                  f"**Reviewed head:** {action.get('expected_head_sha') or action.get('observed_head_sha') or 'WRITE_REVIEWED_HEAD'}"]
    lines += ["", "<!-- deck:operator-action:end -->"]
    return "\n".join(lines)


def instruction_heading(action):
    title = _TITLES.get(action["kind"], "Operator action")
    return f"{title} — PR #{action['pull_request_number']}" if action.get("pull_request_number") else title


def describe(action, *, include_template=False):
    identifier = request_id(action)
    result = {"context_request_id": identifier,
              "instructions_url": f"https://github.com/{action['repo']}/issues/{action['issue_number']}#current-operator-actions"}
    if include_template:
        result["context_template"] = instruction_template(action)
    return result


def inspect_issue(issue, owner, repo, number):
    """Retain structural observations, never issue prose or private diagnostics."""
    expected_repo = f"https://api.github.com/repos/{owner}/{repo}"
    if (not isinstance(issue, dict) or type(issue.get("number")) is not int
        or issue["number"] != number or "pull_request" in issue
        or str(issue.get("repository_url", "")).casefold() != expected_repo.casefold()
        or issue.get("state") not in {"open", "closed"}):
        return {"state": "unavailable", "records": {}}
    body = issue.get("body") or ""
    if not isinstance(body, str) or len(body) > _MAX_BODY:
        return {"state": "invalid", "records": {}}
    if SECTION_START not in body and SECTION_END not in body:
        return {"state": "missing", "records": {}}
    if body.count(SECTION_START) != 1 or body.count(SECTION_END) != 1:
        return {"state": "invalid", "records": {}}
    begin, end = body.index(SECTION_START), body.index(SECTION_END)
    # Instructions must be near the start and rendered as prose, not hidden in
    # a code fence or an HTML comment. A malformed section is never ready.
    prefix = body[:begin]
    if (begin > 4096 or end < begin or prefix.count("```") % 2
        or prefix.count("~~~") % 2 or prefix.count("<!--") != prefix.count("-->")):
        return {"state": "invalid", "records": {}}
    if prefix and not prefix.endswith("\n"):
        return {"state": "invalid", "records": {}}
    section = body[begin + len(SECTION_START):end]
    if ("```" in section or "~~~" in section
        # Keep the current section in plain Markdown. Raw HTML can hide or
        # collapse valid-looking records, including containers opened above it.
        or re.search(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>)", prefix + section)
        or len(re.findall(r"^## Current operator actions\s*$", body, re.M)) != 1
        or not re.search(r"^## Current operator actions\s*$", section, re.M)):
        return {"state": "invalid", "records": {}}
    matches = list(_RECORD.finditer(section))
    # The shared prefix occurs in both the start and end marker of each record.
    if (len(matches) > 16 or section.count("<!-- deck:operator-action:") != 2 * len(matches)
        or section.count("<!-- deck:operator-action:end -->") != len(matches)):
        return {"state": "invalid", "records": {}}
    records = {}
    for match in matches:
        identifier, text = match.groups()
        if identifier in records:
            return {"state": "invalid", "records": {}}
        metadata = re.findall(r"^<!-- deck:operator-record scope=([1-9][0-9]{0,18}) source=(leader|dispatch) -->$", text, re.M)
        if len(metadata) != 1:
            return {"state":"invalid", "records":{}}
        text = re.sub(r"^<!-- deck:operator-record scope=[1-9][0-9]{0,18} source=(leader|dispatch) -->$", "", text, flags=re.M)
        headings = re.findall(r"^### (.+)$", text, re.M)
        labels = list(_LABEL.finditer(text))
        fields = {}
        for index, label in enumerate(labels):
            stop = labels[index + 1].start() if index + 1 < len(labels) else len(text)
            if label[1] in fields:
                return {"state": "invalid", "records": {}}
            fields[label[1]] = text[label.start(2):stop].strip()
        responsible = fields.get("Responsible", "").split(" — ", 1)[0]
        try:
            updated = datetime.fromisoformat(fields.get("Updated", "").replace("Z", "+00:00"))
            if updated.tzinfo is None:
                raise ValueError("timezone_required")
            updated = updated.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            updated = None
        required = ("Status", "Responsible", "Reason", "Action",
                    "Done when", "Updated", "Evidence")
        valid = (all(fields.get(key) for key in required)
                 and all(len(value) <= 1600 for value in fields.values())
                 and "WRITE_" not in text and "<!--" not in text and "-->" not in text
                 and len(headings) == 1
                 and responsible in _ROLES)
        records[identifier] = {
            "valid": bool(valid),
            "status": fields.get("Status") if fields.get("Status") in {*_STATES.values(), "Cleared", "Superseded"} else None,
            "actor": responsible if responsible in _ROLES else None,
            "scope_id": int(metadata[0][0]), "source": metadata[0][1],
            "heading_digest": hashlib.sha256((headings[0] if len(headings)==1 else "").encode()).hexdigest(),
            "updated_at": updated,
            "issue_link": bool(re.search(rf"https://github\.com/{re.escape(owner)}/{re.escape(repo)}/issues/{number}(?:[\s)#?]|$)", fields.get("Evidence", ""))),
            "pr_links": [(path, value) for path, value in re.findall(
                r"https://github\.com/([\w.-]+/[\w.-]+)/pull/([1-9][0-9]*)\b", fields.get("Evidence", ""))
                if path == f"{owner}/{repo}"],
            "pr_target_digest": hashlib.sha256(fields.get("PR target", "").encode()).hexdigest(),
            "reviewed_head": fields.get("Reviewed head") if re.fullmatch(r"[0-9a-f]{40}", fields.get("Reviewed head", "")) else None,
        }
    return {"state": "observed", "records": records, "issue_state": issue["state"]}


def check(action, observation, now=None):
    now = now or datetime.utcnow()
    if observation.get("state") != "observed":
        return observation.get("state", "unavailable"), None
    record = observation["records"].get(request_id(action))
    if record is None:
        return "missing", None
    if record.get("status") in {"Cleared", "Superseded"}:
        return "cleared", record.get("updated_at")
    if (not record["valid"] or not record["issue_link"]
        or record["actor"] != action.get("required_actor", "operator")
        or record["scope_id"] != action["scope_id"]
        or record["source"] != action["source"]
        or record["heading_digest"] != hashlib.sha256(instruction_heading(action).encode()).hexdigest()
        or record["status"] != _STATES.get(action.get("readiness"), "Requested")):
        return "invalid", record.get("updated_at")
    updated = record["updated_at"]
    if updated is None or updated > now + timedelta(minutes=5) or now - updated >= _MAX_AGE:
        return "stale", updated
    if action.get("pull_request_number"):
        if (not action.get("pr_base_ref") or record["pr_target_digest"] != hashlib.sha256(action["pr_base_ref"].encode()).hexdigest()
            or record["reviewed_head"] != (action.get("expected_head_sha") or action.get("observed_head_sha"))
            or (action["repo"], str(action["pull_request_number"])) not in record["pr_links"]):
            return "invalid", updated
    return "current", updated


class GithubOperatorContextService:
    def __init__(self):
        self._cache = {}

    async def draft_actions(self, db, scope, entries, pulls):
        from app.services.github_coordination_service import CoordinationError
        actions = [leader_action(scope, entry, action) for entry in entries for action in entry.human_actions]
        inspections = {a["issue_number"] for a in actions if a["kind"] in {"inspect_attempt", "inspect_checkpoint"}}
        from app.services.github_operator_attention_service import github_operator_attention_service as attention
        snapshot = await attention.dispatch_snapshot(db, [scope]) if inspections else {"items":[], "actions":[], "complete":True}
        if not snapshot["complete"]:
            raise CoordinationError("human_action_context_unavailable")
        by_number = {item.issue_number: item for item in snapshot["items"]}
        direct = {action["issue_number"]: action for action in snapshot["actions"]}
        for action in actions:
            if action["kind"] in {"inspect_attempt", "inspect_checkpoint"}:
                item = by_number.get(action["issue_number"])
                observed = direct.get(action["issue_number"])
                if item is None or observed is None or observed["kind"] != action["kind"]:
                    raise CoordinationError("human_action_attempt_changed")
                bind_attempt(action, item)
                action["checkpoint_epoch"] = observed.get("checkpoint_epoch")
            if action["pull_request_number"]:
                action["pr_base_ref"] = pulls.get(action["pull_request_number"], {}).get("base_ref")
        return actions

    async def validate_report(self, db, scope, entries, issues, pulls, client=None):
        from app.services.github_coordination_service import CoordinationError
        actions = await self.draft_actions(db, scope, entries, pulls)
        observations = {number: inspect_issue(issue, scope.repo_owner, scope.repo_name, number)
                        for number, issue in issues.items()}
        active = {request_id(action) for action in actions}
        for action in actions:
            state, _updated = check(action, observations.get(action["issue_number"], {"state":"unavailable"}))
            if state != "current":
                raise CoordinationError("human_action_context_required", 422)
        requested_dispatch = any(record["scope_id"] == scope.id and record["source"] == "dispatch"
                                 and record["status"] == "Requested"
                                 for observation in observations.values() for record in observation["records"].values())
        direct = []
        if requested_dispatch:
            from app.services.github_operator_attention_service import github_operator_attention_service as attention
            snapshot = await attention.dispatch_snapshot(db, [scope])
            if not snapshot["complete"]:
                raise CoordinationError("human_action_context_unavailable")
            direct = [action for action in snapshot["actions"] if not covered_by_leader(action, actions)]
        numbers = {a["pull_request_number"] for a in direct if a["pull_request_number"]}
        if len(numbers | set(pulls)) > 8:
            raise CoordinationError("human_action_context_unavailable")
        await db.commit()
        observed = await attention.observe_pulls(scope, numbers, client, fresh=True) if numbers else {}
        for action in direct:
            if action["pull_request_number"]:
                pull = observed.get(action["pull_request_number"], {})
                if pull.get("state") == "unavailable":
                    raise CoordinationError("human_action_context_unavailable")
                if pull.get("state") == "closed":
                    continue
                action.update(pr_base_ref=pull.get("base_ref"), observed_head_sha=pull.get("head_sha"))
            active.add(request_id(action))
        # The issue must stop requesting a superseded Leader action, too. Other
        # scopes retain their own records; this cannot rewrite their instructions.
        for observation in observations.values():
            for identifier, record in observation["records"].items():
                if (record["scope_id"] == scope.id and record["source"] in {"leader", "dispatch"}
                    and record["status"] == "Requested" and identifier not in active):
                    raise CoordinationError("human_action_context_not_cleared", 422)

    def invalidate(self, scope):
        for key in list(self._cache):
            if key[0] == scope.id:
                del self._cache[key]

    async def observe(self, scopes, references, client=None):
        client = client or github_client

        async def read(scope, number):
            key = (scope.id, scope.repo_owner, scope.repo_name, scope.updated_at, number)
            cached = self._cache.get(key)
            if cached and cached[0] > time.monotonic():
                return (scope.id, number), cached[1]
            now = datetime.utcnow()
            try:
                issues = await asyncio.wait_for(client.get_issues_by_number(
                    scope.repo_owner, scope.repo_name, [number]), timeout=6)
                result = inspect_issue(issues.get(number), scope.repo_owner, scope.repo_name, number)
            except Exception:
                result = {"state": "unavailable", "records": {}}
            ttl = 10 if result["state"] == "unavailable" else 60
            expiry = now + timedelta(seconds=ttl)
            for record in result["records"].values():
                updated = record["updated_at"]
                if updated and now < updated + _MAX_AGE < expiry:
                    expiry = updated + _MAX_AGE
            result.update(observed_at=now, expires_at=expiry)
            if len(self._cache) >= 64:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (time.monotonic() + ttl, result)
            return (scope.id, number), result

        # Concurrent, bounded reads; a UI poll never writes to GitHub or sends Mail.
        selected = [(scope, number) for scope in scopes for number in sorted(references.get(scope.id, set()))][:32]
        return dict(await asyncio.gather(*(read(scope, number) for scope, number in selected)))


github_operator_context_service = GithubOperatorContextService()
