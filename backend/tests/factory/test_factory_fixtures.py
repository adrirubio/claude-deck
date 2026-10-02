"""Frozen cross-lane contract responses from disposable API requests only."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.api.v1.deps import require_mail_session_or_operator
from app.main import app
from app.models import factory_schemas as wire
from app.models.database import GithubWorkItem, MailAgentSession, TeamGithubScope
from app.services import factory_projection_service as projection

pytestmark = pytest.mark.asyncio
FIXTURES = Path(__file__).parent / "fixtures" / "v1"
NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


async def test_frozen_response_contract(factory_client, factory_store, monkeypatch, request):
    files = {}
    ids = factory_store.ids

    async def record(file, scenario, endpoint, query=None, status=200, method="GET", **kwargs):
        response = await factory_client.request(method, endpoint, params=query, **kwargs)
        assert response.status_code == status, response.text
        files.setdefault(file, {})[scenario] = {
            "endpoint": endpoint, "query": query or {}, "method": method,
            "http_status": status, "response": response.json(),
        }
        return response.json()

    await record("overview", "normal", "/api/v1/factory/overview")
    await record("overview", "team_filter", "/api/v1/factory/overview", {"team_id": ids.teams[0]})
    for mode, state, jobs in (("recovery_only", "running", True), ("normal", "stopped", False),
                               ("unknown", "unknown", False)):
        runtime = projection.RuntimeSnapshot(wire.RuntimeObservation(mode=mode, scheduler_state=state,
            observed_at=None if mode == "unknown" else NOW - timedelta(seconds=1),
            reason_code="runtime_not_observed" if mode == "unknown" else None),
            factory_store.runtime.job_ids if jobs else frozenset())
        monkeypatch.setattr(projection, "observe_runtime", lambda: runtime)
        name = "unknown" if mode == "unknown" else mode if mode == "recovery_only" else "stopped"
        await record("overview", name, "/api/v1/factory/overview")
        await record("repositories", name, "/api/v1/factory/repositories")
    monkeypatch.setattr(projection, "observe_runtime", lambda: factory_store.runtime)

    first = await record("work-items", "first_page", "/api/v1/factory/work-items", {"limit": 2})
    await record("work-items", "next_page", "/api/v1/factory/work-items",
                 {"limit": 2, "cursor": first["next_cursor"]})
    for category in (*projection.CATEGORY_STATUSES, "unknown"):
        await record("work-items", category, "/api/v1/factory/work-items", {"category": category, "limit": 1})
    await record("work-items", "provider_filter", "/api/v1/factory/work-items", {"provider": "codex-cli", "limit": 2})
    await record("work-items", "empty", "/api/v1/factory/work-items", {"scope_id": ids.scopes[2], "category": "review"})
    for status, item_id in ids.by_status.items():
        await record("work-item", status, f"/api/v1/factory/work-items/{item_id}")
    await record("repositories", "normal", "/api/v1/factory/repositories")
    first_repo = await record("repositories", "first_page", "/api/v1/factory/repositories", {"limit": 2})
    await record("repositories", "last_page", "/api/v1/factory/repositories",
                 {"limit": 2, "cursor": first_repo["next_cursor"]})
    await record("repositories", "filtered_overlap", "/api/v1/factory/repositories", {"team_id": ids.teams[0]})
    for name, scope in zip(("fresh_overlap", "never_polled_overlap", "paused"), ids.scopes):
        await record("repository", name, f"/api/v1/factory/repositories/{scope}")
    async with factory_store.maker() as db:
        scope = await db.get(TeamGithubScope, ids.scopes[0])
        scope.last_polled_at = (NOW - timedelta(seconds=121)).replace(tzinfo=None)
        await db.commit()
    await record("repository", "stale", f"/api/v1/factory/repositories/{ids.scopes[0]}")
    await record("overview", "stale", "/api/v1/factory/overview")
    no_job = projection.RuntimeSnapshot(factory_store.runtime.public, frozenset())
    monkeypatch.setattr(projection, "observe_runtime", lambda: no_job)
    await record("repositories", "missing_job", "/api/v1/factory/repositories")
    monkeypatch.setattr(projection, "observe_runtime", lambda: factory_store.runtime)

    async with factory_store.maker() as db:
        owner_session = (await db.execute(select(MailAgentSession).where(
            MailAgentSession.team_slot_id == ids.owners[1]))).scalar_one()
        owner_session.closed_at = NOW.replace(tzinfo=None)
        await db.commit()
    await record("work-item", "verified_offline_owner", f"/api/v1/factory/work-items/{ids.items[1]}")
    async with factory_store.maker() as db:
        owner_session = await db.get(MailAgentSession, owner_session.id)
        owner_session.closed_at = None
        db.add(MailAgentSession(member_id=owner_session.member_id, session_key="fixture-duplicate",
            source="mcp", provider="codex-cli", team_preset_id=ids.teams[1], team_slot_id=ids.owners[1],
            capability_token_hash="synthetic-private-forbidden", mailbox_status="connected",
            last_seen_at=NOW.replace(tzinfo=None), bound_pane_pid=owner_session.bound_pane_pid,
            bound_pane_proc_start=owner_session.bound_pane_proc_start))
        await db.commit()
    await record("work-item", "ambiguous_owner", f"/api/v1/factory/work-items/{ids.items[1]}")

    async with factory_store.maker() as db:
        escalated = await db.get(GithubWorkItem, ids.by_status["escalated"])
        escalated.active_scope_revision = 0
        escalated.last_verified_sha = "a" * 40
        await db.commit()
    await record("work-item", "preserved_pr", f"/api/v1/factory/work-items/{ids.by_status['escalated']}")
    async with factory_store.maker() as db:
        escalated = await db.get(GithubWorkItem, ids.by_status["escalated"])
        escalated.pr_number = None
        await db.commit()
    await record("work-item", "operator_stop_retry_eligible", f"/api/v1/factory/work-items/{ids.by_status['escalated']}")

    await record("errors", "missing_work_item", "/api/v1/factory/work-items/9999", status=404)
    await record("errors", "missing_repository", "/api/v1/factory/repositories/9999", status=404)
    await record("errors", "invalid_filter", "/api/v1/factory/work-items", {"limit": 0}, status=422)
    await record("errors", "invalid_cursor", "/api/v1/factory/work-items", {"cursor": "invalid"}, status=422)
    await record("errors", "incompatible_filters", "/api/v1/factory/overview",
                 {"team_id": ids.teams[0], "scope_id": ids.scopes[1]}, status=422)
    async def failed(*args, **kwargs):
        raise RuntimeError("synthetic-private-forbidden")
    with monkeypatch.context() as patch:
        patch.setattr(projection, "overview", failed)
        await record("errors", "projection_failed", "/api/v1/factory/overview", status=500)

    # Protected write routes retain their existing error envelopes. Every call
    # below fails before mutation; none is a factory remedy or authority grant.
    retry_path = f"/api/v1/agent-teams/github-work-items/{ids.items[1]}/retry"
    await record("protected-errors", "unauthenticated", retry_path, status=401, method="POST", json={})
    await record("protected-errors", "state_conflict", retry_path, status=409, method="POST", json={},
                 headers={"X-Deck-Operator-Token": "synthetic-factory-operator"})
    monkeypatch.setattr(projection.settings, "mail_capability_tokens_required", True)
    async def synthetic_owner():
        return owner_session
    app.dependency_overrides[require_mail_session_or_operator] = synthetic_owner
    try:
        await record("protected-errors", "wrong_actor", retry_path, status=403, method="POST", json={})
    finally:
        app.dependency_overrides.pop(require_mail_session_or_operator)

    schemas = {name: getattr(wire, name).model_json_schema() for name in (
        "OverviewResponse", "WorkListResponse", "WorkDetailResponse", "RepositoryListResponse",
        "RepositoryDetailResponse", "FactoryErrorResponse")}
    files["schema"] = {"schema_version": 1, "models": schemas}
    files["mapping"] = {"schema_version": 1, "categories": projection.CATEGORY_STATUSES,
                        "reason_summaries": projection.REASON_SUMMARIES,
                        "action_sources": {
                            "retry": {"source": "GithubDispatchService.retry_eligibility",
                                      "path": "backend/app/services/github_dispatch_service.py",
                                      "projection": "shared legacy _work_item_response.retry_allowed/retry_block_code",
                                      "required_actor": "leader", "states": ["eligible", "blocked", "unknown"]},
                            **{name: {"source": source,
                                      "eligibility": "protected existing route; full preconditions not evaluated by read",
                                      "path": "backend/app/api/v1/agent_teams.py",
                                      "required_actor": actor, "states": ["unknown"],
                                      "block_code": "unknown",
                                      "reason": "Open attempt recovery to check available actions."}
                               for name, actor, source in (
                                  ("resume_attempt", "operator", "resume_github_work_item_attempt"),
                                  ("escalate_attempt", "operator", "abandon_github_work_item"),
                                  ("cancel_continuation_request", "owner", "cancel_github_work_item_continuation_request / GithubApprovalService.cancel"),
                                  ("cancel_active_revision", "operator", "cancel_active_github_work_item_scope_revision"),
                                  ("release_recovery_checkpoint", "operator", "release_github_recovery_checkpoint"))}},
                        "fallback_category": "unknown", "unknown_reason_summary": projection.REASON_SUMMARIES["unknown"]}
    for name, value in files.items():
        # JSON normalization turns immutable status tuples into artifact arrays.
        value = json.loads(json.dumps(value))
        assert "synthetic-private-forbidden" not in json.dumps(value)
        path = FIXTURES / f"{name}.json"
        if request.config.getoption("--freeze-factory-fixtures"):
            FIXTURES.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        else:
            assert json.loads(path.read_text()) == value, f"Contract changed: {path.name}"
