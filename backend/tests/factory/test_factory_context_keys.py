"""#516: the Audit filters list teams and repositories by name, and the events
read takes a time window. The listing is read-only and needs the Director key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.database import (
    AgentTeamPreset, FactoryAuditEvent, FactoryContextKey, TeamGithubScope,
)
from app.services import factory_audit_service as audit

OPERATOR = "synthetic-context-keys-operator"
HEADERS = {"X-Deck-Operator-Token": OPERATOR}
NOW = datetime(2026, 10, 13, 12, 0, 0)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def store(tmp_path, monkeypatch):
    import app.database as database
    from app.config import settings

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'context-keys.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, autocommit=False, autoflush=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", maker)
    monkeypatch.setattr(settings, "operator_token", OPERATOR)
    try:
        yield maker
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(store):
    from app.main import app

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://context-keys") as http:
        yield http


async def add_team(maker, team_id: int, name: str, *, scope: tuple[int, str, str] | None = None) -> None:
    async with maker() as db:
        db.add(AgentTeamPreset(id=team_id, name=name, created_by="fixture", autonomy_enabled=False))
        await db.flush()
        if scope:
            scope_id, owner, repo = scope
            db.add(TeamGithubScope(
                id=scope_id, preset_id=team_id, repo_owner=owner, repo_name=repo,
                repo_path=f"/tmp/{repo}", base_ref="origin/master", github_auth_mode="ambient",
                merge_policy="human"))
        await db.commit()


async def record(maker, *, team_id: int | None = None, scope_id: int | None = None,
                 at: datetime = NOW, kind: str = "policy_change") -> None:
    actor = audit.derive_actor(actor_kind="operator")
    async with maker() as db:
        await audit.record_event(
            db, event_kind=kind, source="test", occurred_at=at.replace(tzinfo=timezone.utc),
            actor=actor, action_outcome="applied", team_preset_id=team_id, scope_id=scope_id)
        await db.commit()


async def delete_team(maker, team_id: int) -> None:
    async with maker() as db:
        await db.execute(text("DELETE FROM agent_team_presets WHERE id = :id"), {"id": team_id})
        await db.commit()


async def listing(client) -> dict:
    response = await client.get("/api/v1/factory/context-keys", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def names(entries: list[dict]) -> list[str]:
    return sorted(entry["display_name"] for entry in entries)


async def test_the_listing_needs_the_director_key(client, store, monkeypatch):
    from app.config import settings

    assert (await client.get("/api/v1/factory/context-keys")).status_code == 401
    wrong = await client.get("/api/v1/factory/context-keys", headers={"X-Deck-Operator-Token": "wrong"})
    assert wrong.status_code == 401
    monkeypatch.setattr(settings, "operator_token", "")
    assert (await client.get("/api/v1/factory/context-keys", headers=HEADERS)).status_code == 503


async def test_the_route_is_read_only(client, store):
    for method in ("post", "put", "patch", "delete"):
        response = await getattr(client, method)("/api/v1/factory/context-keys", headers=HEADERS)
        assert response.status_code == 405, (method, response.status_code)


async def test_a_team_and_a_repository_are_listed_by_name_with_their_event_count(client, store):
    await add_team(store, 1, "Release crew", scope=(5, "example-org", "sample-app"))
    await record(store, team_id=1, scope_id=5)
    await record(store, team_id=1, scope_id=5)
    data = await listing(client)
    (team,) = data["teams"]
    (repo,) = data["repositories"]
    assert (team["display_name"], team["current"], team["retired_at"], team["event_count"]) == ("Release crew", True, None, 2)
    assert team["context_key"] and team["context_key"].startswith("team:1:")
    assert (repo["display_name"], repo["current"], repo["event_count"]) == ("example-org/sample-app", True, 2)


async def test_a_live_team_without_an_event_is_listed_with_a_null_key_and_allocates_none(client, store):
    await add_team(store, 4, "Fresh crew", scope=(8, "example-org", "fresh-repo"))
    data = await listing(client)
    assert data["teams"] == [{"context_key": None, "display_name": "Fresh crew", "retired_at": None,
                              "event_count": 0, "current": True}]
    assert data["repositories"][0]["context_key"] is None
    async with store() as db:
        assert (await db.execute(select(func.count()).select_from(FactoryContextKey))).scalar_one() == 0


async def test_a_renamed_team_is_one_entry_under_its_current_name(client, store):
    await add_team(store, 1, "Old name")
    await record(store, team_id=1)
    async with store() as db:
        await db.execute(text("UPDATE agent_team_presets SET name = 'New name' WHERE id = 1"))
        await db.commit()
    await record(store, team_id=1)
    data = await listing(client)
    assert names(data["teams"]) == ["New name"]
    assert data["teams"][0]["event_count"] == 2


async def test_a_deleted_team_keeps_its_last_stored_name_and_its_history(client, store):
    await add_team(store, 3, "Retired crew", scope=(7, "example-org", "retired-site"))
    await record(store, team_id=3, scope_id=7)
    await record(store, team_id=3, scope_id=7)
    await delete_team(store, 3)
    data = await listing(client)
    (team,) = data["teams"]
    assert (team["display_name"], team["current"], team["event_count"]) == ("Retired crew", False, 2)
    assert team["retired_at"] is not None
    (repo,) = data["repositories"]
    assert (repo["display_name"], repo["current"]) == ("example-org/retired-site", False)
    # The key still addresses the kept events.
    events = await client.get("/api/v1/factory/audit-events", headers=HEADERS,
                              params={"team_context_key": team["context_key"]})
    assert events.json()["total"] == 2


async def test_two_teams_with_one_name_are_two_entries(client, store):
    await add_team(store, 3, "Retired crew")
    await record(store, team_id=3)
    await delete_team(store, 3)
    await add_team(store, 4, "Retired crew")
    data = await listing(client)
    assert names(data["teams"]) == ["Retired crew", "Retired crew"]
    assert {entry["current"] for entry in data["teams"]} == {True, False}
    keys = [entry["context_key"] for entry in data["teams"]]
    assert None in keys and len(set(keys)) == 2


async def test_a_reused_numeric_id_is_a_new_entry(client, store):
    await add_team(store, 1, "First life")
    await record(store, team_id=1)
    await delete_team(store, 1)
    await add_team(store, 1, "Second life")
    await record(store, team_id=1)
    data = await listing(client)
    assert names(data["teams"]) == ["First life", "Second life"]
    assert sorted(entry["event_count"] for entry in data["teams"]) == [1, 1]
    assert len({entry["context_key"] for entry in data["teams"]}) == 2


async def test_the_listing_writes_nothing(client, store):
    await add_team(store, 1, "Release crew")
    await record(store, team_id=1)
    async with store() as db:
        before = (await db.execute(select(func.count()).select_from(FactoryAuditEvent))).scalar_one()
        keys_before = (await db.execute(select(func.count()).select_from(FactoryContextKey))).scalar_one()
    await listing(client)
    await listing(client)
    async with store() as db:
        assert (await db.execute(select(func.count()).select_from(FactoryAuditEvent))).scalar_one() == before
        assert (await db.execute(select(func.count()).select_from(FactoryContextKey))).scalar_one() == keys_before


async def test_the_events_read_takes_a_time_window(client, store):
    await add_team(store, 1, "Release crew")
    for days_ago in (1, 10, 40):
        await record(store, team_id=1, at=NOW - timedelta(days=days_ago))

    async def total(**params) -> int:
        response = await client.get("/api/v1/factory/audit-events", headers=HEADERS, params=params)
        assert response.status_code == 200, response.text
        return response.json()["total"]

    assert await total() == 3
    assert await total(occurred_after=(NOW - timedelta(days=7)).isoformat()) == 1
    assert await total(occurred_after=(NOW - timedelta(days=30)).isoformat()) == 2
    assert await total(occurred_before=(NOW - timedelta(days=5)).isoformat()) == 2
    assert await total(occurred_after=(NOW - timedelta(days=30)).isoformat(),
                       occurred_before=(NOW - timedelta(days=5)).isoformat()) == 1


async def test_a_time_with_a_zone_is_read_as_that_instant(client, store):
    await add_team(store, 1, "Release crew")
    await record(store, team_id=1, at=NOW)
    inside = (NOW - timedelta(hours=1)).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    after = (NOW + timedelta(hours=1)).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    zoned = (NOW + timedelta(hours=1)).replace(tzinfo=timezone(timedelta(hours=2))).isoformat()
    base = "/api/v1/factory/audit-events"
    assert (await client.get(base, headers=HEADERS, params={"occurred_after": inside})).json()["total"] == 1
    assert (await client.get(base, headers=HEADERS, params={"occurred_after": after})).json()["total"] == 0
    # 13:00 at +02:00 is 11:00 UTC, which is before the event at 12:00 UTC.
    assert (await client.get(base, headers=HEADERS, params={"occurred_after": zoned})).json()["total"] == 1
