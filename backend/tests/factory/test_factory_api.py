"""P01 complete counts, bounded projections, cursor/error and observation contracts."""
import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.database import Base
from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, TeamGithubScope
from app.models import factory_schemas as wire
from app.services import factory_projection_service as projection

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
PRIVATE = "synthetic-private-forbidden"

pytestmark = pytest.mark.asyncio


async def get_ok(client, path, **params):
    response = await client.get("/api/v1/factory/" + path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_complete_counts_and_timestamp_id_pagination(factory_client, factory_store):
    first = await get_ok(factory_client, "work-items", limit=100)
    assert first["total"] == 132
    assert len(first["items"]) == 100
    assert first["has_more"] and first["next_cursor"]
    assert sum(first["counts"][c] for c in (*projection.CATEGORY_STATUSES, "unknown")) == 132
    second = await get_ok(factory_client, "work-items", limit=100, cursor=first["next_cursor"])
    assert second["total"] == 132
    assert len(second["items"]) == 32
    assert not second["has_more"] and second["next_cursor"] is None
    rows = first["items"] + second["items"]
    ids = [r["item"]["id"] for r in rows]
    assert ids == sorted(factory_store.ids.items, reverse=True)
    assert len(set(ids)) == 132
    overview = await get_ok(factory_client, "overview")
    assert overview["counts"] == first["counts"]
    assert first["generated_at"].endswith("Z")


@pytest.mark.parametrize("category", (*projection.CATEGORY_STATUSES, "unknown"))
async def test_category_counts_cover_complete_selected_set(factory_client, factory_store, category):
    response = await get_ok(factory_client, "work-items", category=category, limit=1)
    expected = sum(1 for i in range(132) if projection.STATUS_CATEGORY.get(
        (tuple(projection.STATUS_CATEGORY) + ("future_status",))[i % 10], "unknown") == category)
    assert response["total"] == expected
    assert response["counts"][category] == expected
    assert response["counts"]["total"] == expected
    assert len(response["items"]) == 1
    assert response["items"][0]["category"] == category


async def test_provider_filter_matches_only_current_owner_and_repo_roster(factory_client, factory_store):
    response = await get_ok(factory_client, "work-items", provider="codex-cli", limit=100)
    assert response["total"] == sum(i % 7 != 0 for i in range(132))
    assert all(r["owner"]["configured_provider"] == "codex-cli" for r in response["items"])
    assert (await get_ok(factory_client, "work-items", provider="claude-code"))["total"] == 0
    assert (await get_ok(factory_client, "repositories", provider="codex-cli"))["total"] == 3
    async with factory_store.maker() as db:
        owner = await db.get(AgentTeamSlot, factory_store.ids.owners[0])
        owner.provider = "claude-code"
        await db.commit()
    changed = await get_ok(factory_client, "work-items", provider="codex-cli", limit=100)
    assert 0 < changed["total"] < response["total"]


async def test_same_repository_retains_scope_and_attempt_identity(factory_client, factory_store):
    result = await get_ok(factory_client, "work-items", limit=100)
    assert {r["repository"]["scope_id"] for r in result["items"]} >= set(factory_store.ids.scopes[:2])
    repositories = await get_ok(factory_client, "repositories", team_id=factory_store.ids.teams[0])
    first = next(r for r in repositories["repositories"] if r["scope_id"] == factory_store.ids.scopes[0])
    assert first["overlap"] == {"state": "warning", "other_scope_ids": [factory_store.ids.scopes[1]]}
    async with factory_store.maker() as db:
        # Scope outside selected team stops colliding when its label differs.
        await db.execute(update(TeamGithubScope).where(TeamGithubScope.id == factory_store.ids.scopes[1])
                         .values(dispatch_label="different"))
        await db.commit()
    changed = await get_ok(factory_client, f"repositories/{factory_store.ids.scopes[0]}")
    assert changed["repository"]["overlap"] == {"state": "none", "other_scope_ids": []}


@pytest.mark.parametrize("disable", ("team", "scope"))
async def test_paused_scope_is_distinct_from_active_collision(factory_client, factory_store, disable):
    async with factory_store.maker() as db:
        if disable == "team":
            await db.execute(update(AgentTeamPreset).where(AgentTeamPreset.id == factory_store.ids.teams[1])
                             .values(autonomy_enabled=False))
        else:
            await db.execute(update(TeamGithubScope).where(TeamGithubScope.id == factory_store.ids.scopes[1])
                             .values(enabled=False))
        await db.commit()
    result = await get_ok(factory_client, f"repositories/{factory_store.ids.scopes[0]}")
    assert result["repository"]["overlap"]["state"] == "none"


@pytest.mark.parametrize("path,params,status,code", [
    ("work-items", {"limit": 0}, 422, "invalid_filter"),
    ("work-items", {"limit": 101}, 422, "invalid_filter"),
    ("work-items", {"team_id": -1}, 422, "invalid_filter"),
    ("work-items", {"scope_id": 2**64}, 422, "invalid_filter"),
    ("work-items", {"provider": "made-up"}, 422, "invalid_filter"),
    ("work-items", {"category": "made-up"}, 422, "invalid_filter"),
    ("work-items", {"cursor": "!not-base64"}, 422, "invalid_cursor"),
    ("work-items", {"cursor": ""}, 422, "invalid_cursor"),
    ("overview", {"team_id": 99999}, 404, "resource_not_found"),
    ("overview", {"scope_id": 99999}, 404, "resource_not_found"),
    ("work-items/99999", {}, 404, "resource_not_found"),
    ("work-items/0", {}, 422, "invalid_filter"),
    ("repositories/99999", {}, 404, "resource_not_found"),
    ("repositories/not-a-number", {}, 422, "invalid_filter"),
])
async def test_read_error_envelopes(factory_client, path, params, status, code):
    response = await factory_client.get("/api/v1/factory/" + path, params=params)
    assert response.status_code == status
    body = wire.FactoryErrorResponse.model_validate(response.json())
    assert body.detail.code == code
    assert body.detail.message


async def test_absent_and_incompatible_filters(factory_client, factory_store):
    response = await factory_client.get("/api/v1/factory/overview", params={
        "team_id": factory_store.ids.teams[0], "scope_id": factory_store.ids.scopes[1]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_filter"


@pytest.mark.parametrize("change", ("version", "id", "timestamp", "filters", "kind", "extra"))
async def test_cursor_validation_and_filter_binding(factory_client, change):
    first = await get_ok(factory_client, "work-items", limit=1)
    encoded = first["next_cursor"]
    value = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    if change == "version": value["v"] = 2
    if change == "id": value["id"] = True
    if change == "timestamp": value["updated_at"] = "2026-09-30T12:00:00"
    if change == "filters": value["filters"]["category"] = "active"
    if change == "kind": value["kind"] = "repositories"
    if change == "extra": value["private"] = PRIVATE
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    response = await factory_client.get("/api/v1/factory/work-items", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_cursor"
    assert PRIVATE not in response.text


async def test_reusing_cursor_after_filter_change_is_rejected(factory_client):
    result = await get_ok(factory_client, "work-items", limit=1)
    response = await factory_client.get("/api/v1/factory/work-items", params={
        "category": "active", "cursor": result["next_cursor"]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_cursor"


async def test_mutation_updates_move_record_without_snapshot_promise(factory_client, factory_store):
    first = await get_ok(factory_client, "work-items", limit=2)
    moving = factory_store.ids.items[0]
    async with factory_store.maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == moving)
                         .values(updated_at=NOW.replace(tzinfo=None) + timedelta(seconds=1)))
        await db.commit()
    second = await get_ok(factory_client, "work-items", limit=100, cursor=first["next_cursor"])
    assert moving not in {r["item"]["id"] for r in second["items"]}
    refreshed = await get_ok(factory_client, "work-items", limit=1)
    assert refreshed["items"][0]["item"]["id"] == moving


async def test_repositories_cursor_paginates_scopes(factory_client, factory_store):
    first = await get_ok(factory_client, "repositories", limit=1)
    second = await get_ok(factory_client, "repositories", limit=100, cursor=first["next_cursor"])
    assert first["total"] == second["total"] == 3
    assert [r["scope_id"] for r in first["repositories"] + second["repositories"]] == sorted(factory_store.ids.scopes, reverse=True)
    assert not second["has_more"] and second["next_cursor"] is None


async def test_redaction_list_detail_overview_and_repository(factory_client, factory_store):
    paths = ("work-items", "overview", "repositories",
             f"work-items/{factory_store.ids.by_status['escalated']}", f"repositories/{factory_store.ids.scopes[0]}")
    for path in paths:
        response = await factory_client.get("/api/v1/factory/" + path)
        assert response.status_code == 200, response.text
        assert PRIVATE not in response.text
    result = await get_ok(factory_client, f"work-items/{factory_store.ids.by_status['escalated']}")
    item = result["work_item"]
    assert set(item["item"]) == set(wire.SafeWorkItem.model_fields)
    assert item["category"] == "attention"
    assert item["waiting"]["reason_code"] == "abandoned_by_operator"
    assert item["item"]["active_scope_status"] == "active"
    assert item["workspace"] == {"id": factory_store.ids.workspace, "state": "leased"}
    assert not any(k in json.dumps(item) for k in ("dispatch_nonce", "workspace_path", "active_scope_summary", "allowed_commands"))


async def test_last_verified_sha_only_for_displayed_pr_and_not_diagnostic(factory_client, factory_store):
    item_id = factory_store.ids.by_status["merged"]
    async with factory_store.maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id).values(last_verified_sha="a" * 40))
        await db.commit()
    result = await get_ok(factory_client, f"work-items/{item_id}")
    assert result["work_item"]["item"]["last_verified_sha"] is None
    async with factory_store.maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id).values(pr_number=22))
        await db.commit()
    result = await get_ok(factory_client, f"work-items/{item_id}")
    assert result["work_item"]["item"]["last_verified_sha"] == "a" * 40
    async with factory_store.maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item_id).values(attempt_phase="diagnostic"))
        await db.commit()
    result = await get_ok(factory_client, f"work-items/{item_id}")
    assert result["work_item"]["item"]["last_verified_sha"] is None


async def test_unknown_private_reason_is_generic_and_finished_is_tracking_only(factory_client, factory_store):
    async with factory_store.maker() as db:
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == factory_store.ids.by_status["failed"])
                         .values(escalation_reason=PRIVATE))
        await db.commit()
    failed = await get_ok(factory_client, f"work-items/{factory_store.ids.by_status['failed']}")
    assert failed["work_item"]["waiting"]["reason_code"] == "unknown"
    assert PRIVATE not in json.dumps(failed)
    completed = await get_ok(factory_client, f"work-items/{factory_store.ids.by_status['completed']}")
    assert completed["work_item"]["category"] == "finished"
    assert "delivery_outcome" not in json.dumps(completed)


async def test_projection_failure_is_not_zero_data(factory_client, monkeypatch):
    monkeypatch.setattr(projection, "counts", AsyncMock(side_effect=RuntimeError(PRIVATE)))
    response = await factory_client.get("/api/v1/factory/overview")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "projection_failed"
    assert PRIVATE not in response.text and "counts" not in response.json()


async def test_sql_query_count_bounded_between_one_and_hundred_rows(factory_client, factory_store, record_property):
    measured = []
    for limit in (1, 100):
        factory_store.statements.clear()
        response = await get_ok(factory_client, "work-items", limit=limit)
        assert len(response["items"]) == limit
        measured.append(len(factory_store.statements))
    assert measured[0] == measured[1]
    assert measured[1] <= 12
    record_property("query_counts_one_hundred", measured)


async def test_factory_gets_do_not_write_or_call_runtime_mutations(factory_client, factory_store, monkeypatch):
    from app.services.agent_mail_service import agent_mail_service
    from app.services.agent_bridge import discovery
    from app.services.github_client import GithubClient
    from app.services.github_dispatch_service import github_dispatch_service
    def forbidden(*args, **kwargs):
        raise AssertionError("live boundary called by factory read")
    monkeypatch.setattr(GithubClient, "_client", forbidden)
    monkeypatch.setattr(discovery, "discover_agent_sessions", forbidden)
    monkeypatch.setattr(discovery, "capture_pane_preview", forbidden)
    for provider in projection.get_providers():
        monkeypatch.setattr(provider, "get_status", forbidden)
        monkeypatch.setattr(provider, "get_version", forbidden)
        monkeypatch.setattr(provider, "build_spawn_command", forbidden)
    for name in ("send_message", "register_session"):
        monkeypatch.setattr(agent_mail_service, name, AsyncMock(side_effect=forbidden))
    monkeypatch.setattr(github_dispatch_service, "prepare_attempt", AsyncMock(side_effect=forbidden))
    scheduler = projection.github_dispatch_scheduler
    for name in ("start", "sync_jobs", "run_repo_once"):
        monkeypatch.setattr(scheduler, name, AsyncMock(side_effect=AssertionError("mutation called")))
    async with factory_store.maker() as db:
        before = {table.name: (await db.execute(select(table))).all() for table in Base.metadata.tables.values()}
    factory_store.statements.clear()
    for path in ("overview", "work-items", "repositories", f"work-items/{factory_store.ids.items[1]}",
                 f"repositories/{factory_store.ids.scopes[0]}"):
        await get_ok(factory_client, path)
    assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER"))
                   for s in factory_store.statements)
    assert all(s.lstrip().upper().startswith(("SELECT", "BEGIN")) for s in factory_store.statements)
    async with factory_store.maker() as db:
        after = {table.name: (await db.execute(select(table))).all() for table in Base.metadata.tables.values()}
    assert after == before
