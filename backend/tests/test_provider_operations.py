"""Sourced operation/catalog fixtures and strict slot-only session observations."""
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import providers as api
from app.database import get_db
from app.models import provider_operations_schemas as wire
from app.services import provider_operations_service as ops
from app.services import factory_projection_service as factory
from app.services.providers import get_providers
from tests.test_provider_readiness import NOW, configured

ROOT = Path(__file__).resolve().parents[2]


def snapshot():
    return ops.Snapshot({p.id: True for p in get_providers()}, configured(), NOW, NOW, 0)


@pytest.mark.parametrize("provider", get_providers(), ids=lambda p: p.id)
def test_contract_matrix(provider):
    report = ops.catalog(provider, snapshot())
    assert set(report.operations) == wire.OPERATION_KEYS
    assert report.native_capabilities == provider.get_capability_matrix()
    for key, operation in report.operations.items():
        assert operation.reason and operation.evidence
        for source in operation.evidence:
            assert (ROOT / source.split("::")[0]).is_file()
        if operation.state == "conditional":
            assert operation.conditions
    assert report.readiness.configuration.state == "ready"
    assert report.readiness.credentials.state == report.readiness.session.state == "unknown"
    assert report.readiness.credentials.observed_at is None
    if provider.id == "pi-cli":
        assert report.operations["execution_controls"].state == "unsupported"
        assert "project-local" in " ".join(report.operations["resume_exact"].conditions)
    if provider.id in {"opencode-cli", "copilot-cli"}:
        assert report.operations["execution_controls"].state == "unknown"


@pytest.mark.parametrize("provider", get_providers(), ids=lambda p: p.id)
def test_native_catalog_agrees_with_frozen_p02_adapters(provider):
    registry = json.loads((ROOT / "frontend/tests/fixtures/factory/native-adapters.json").read_text())["registry"][provider.id]
    catalog = ops.native_surfaces(provider)
    for surface, entry in catalog.items():
        if surface not in registry:
            assert entry.state == "unavailable"
            assert entry.adapter_id is None and entry.access == "none"
        else:
            assert entry.adapter_id == f"{provider.id}:{surface}:{registry[surface]['component']}"
            assert entry.access == ("read_only" if registry[surface]["access"] == "read_only" else "read_write")
    if provider.id in {"opencode-cli", "copilot-cli"}:
        assert all(e.access == "none" for e in catalog.values())


def evidence():
    slot = NS(id=2, preset_id=1, provider="codex-cli")
    member = NS(id=3, team_preset_id=1, team_slot_id=2, participant_kind="team_slot")
    session = NS(id=4, member_id=3, source="mcp", capability_token_hash="synthetic-private", team_preset_id=1, team_slot_id=2, closed_at=None, mailbox_status="connected", last_seen_at=NOW, provider="codex-cli", pid=101, bound_pane_pid=101, bound_pane_proc_start="fixture-start")
    binding = NS(slot_id=2, preset_id=1, pane_pid=101, pane_proc_start="fixture-start")
    return [slot], [member], [session], [binding], set()


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected", [
    ("bound", "bound"), ("duplicate_members", "ambiguous"), ("duplicate_sessions", "ambiguous"),
    ("wrong_provider", "unknown"), ("conflicting_provider", "ambiguous"),
    ("wrong_start", "unknown"), ("retired", "unknown"), ("stale_pid", "unknown"),
    ("offline", "offline"), ("missing_member", "unknown"), ("wrong_member_team", "unknown"),
])
async def test_scoped_session_identity_before_provider_filter(monkeypatch, case, expected):
    slots, members, sessions, bindings, retired = evidence()
    if case == "duplicate_members": members.append(NS(**vars(members[0]), extra=1))
    if case in {"duplicate_sessions", "conflicting_provider"}:
        sessions.append(NS(**{**vars(sessions[0]), "id": 5, "provider": "pi-cli" if case == "conflicting_provider" else "codex-cli"}))
    if case == "wrong_provider": sessions[0].provider = "pi-cli"
    if case == "wrong_start": sessions[0].bound_pane_proc_start = "foreign"
    if case == "retired": retired.add((101, "fixture-start"))
    if case == "stale_pid": sessions[0].last_seen_at = NOW - timedelta(days=1)
    if case == "offline": sessions[0].closed_at = NOW
    if case == "missing_member": members.clear()
    if case == "wrong_member_team": members[0].team_preset_id = 9
    async def read(db, team_ids, authority):
        assert team_ids == {1} and authority == {}
        return slots, members, sessions, bindings, retired
    monkeypatch.setattr(factory, "actor_evidence", read)
    monkeypatch.setattr(ops, "now", lambda: NOW)
    result = await ops.scoped_session(None, "codex-cli", 1, 2)
    assert result.state == expected
    assert result.session_id == (4 if expected == "bound" else None)
    assert "synthetic-private" not in result.model_dump_json()
    assert "fixture-start" not in result.model_dump_json()
    assert "101" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_slot_context_requires_configured_provider_and_same_team(monkeypatch):
    async def read(*_): return evidence()
    monkeypatch.setattr(factory, "actor_evidence", read)
    for provider, team, slot in [("pi-cli",1,2),("codex-cli",9,2),("codex-cli",1,9)]:
        with pytest.raises(ValueError, match="slot_context_not_found"):
            await ops.scoped_session(None, provider, team, slot)


@pytest.mark.asyncio
async def test_http_validation_unknown_provider_and_private_failure(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    async def db(): yield None
    async def observation(): return snapshot()
    async def failure(*_): raise RuntimeError("synthetic-private-path-token-error")
    app.dependency_overrides[get_db] = db
    monkeypatch.setattr(ops, "readiness_snapshot", observation)
    monkeypatch.setattr(ops, "scoped_session", failure)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.get("/providers/codex-cli/operations")
        assert response.status_code == 200
        assert response.json()["readiness"]["session"]["state"] == "unknown"
        for query in ["team_id=1", "slot_id=2", "team_id=0&slot_id=2", "team_id=1&slot_id=-1"]:
            assert (await client.get(f"/providers/codex-cli/operations?{query}")).status_code == 422
        assert (await client.get("/providers/missing/operations")).status_code == 404
        failed = await client.get("/providers/codex-cli/operations?team_id=1&slot_id=2")
        assert failed.status_code == 200 and failed.json()["readiness"]["session"]["state"] == "unknown"
        assert "synthetic-private" not in failed.text
        assert (await client.post("/providers/codex-cli/operations")).status_code == 405


def test_frozen_catalog_fixtures_match_service():
    fixture = json.loads((Path(__file__).parent / "fixtures/provider-operations/v1/catalog.json").read_text())
    for provider in get_providers():
        assert ops.catalog(provider, snapshot()).model_dump(mode="json") == fixture["providers"][provider.id]


@pytest.mark.asyncio
async def test_real_slot_sql_observation_is_bounded_read_only(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.database import Base
    from app.models.database import AgentTeamPreset, AgentTeamSlot, MailTeamMember, MailAgentSession, AgentPaneBinding

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'slot.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    statements = []
    monkeypatch.setattr(ops, "now", lambda: NOW)
    try:
        async with maker() as db:
            team = AgentTeamPreset(name="Synthetic P03 team")
            db.add(team)
            await db.flush()
            slot = AgentTeamSlot(preset_id=team.id, position=0, provider="codex-cli", display_name="Synthetic owner", repo_id="fixture", repo_path="/synthetic-private", repo_name="fixture")
            db.add(slot)
            await db.flush()
            member = MailTeamMember(identity_key="synthetic-identity", repo_id="fixture", repo_path="/synthetic-private", repo_name="fixture", display_name="Synthetic owner", participant_kind="team_slot", team_preset_id=team.id, team_slot_id=slot.id)
            db.add(member)
            await db.flush()
            session = MailAgentSession(member_id=member.id, provider="codex-cli", source="mcp", session_key="synthetic-session", team_preset_id=team.id, team_slot_id=slot.id, capability_token_hash="synthetic-private", bound_pane_pid=101, bound_pane_proc_start="fixture-start", last_seen_at=NOW.replace(tzinfo=None), mailbox_status="connected")
            db.add_all([session, AgentPaneBinding(preset_id=team.id, slot_id=slot.id, pane_pid=101, pane_proc_start="fixture-start", tmux_target="synthetic-private")])
            await db.commit()
            @event.listens_for(engine.sync_engine, "before_cursor_execute")
            def record(_conn, _cursor, statement, _params, _context, _many):
                statements.append(statement)
            result = await ops.scoped_session(db, "codex-cli", team.id, slot.id)
            assert result.state == "bound" and result.session_id == session.id
            assert len(statements) == 5
            assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
            assert "synthetic-private" not in result.model_dump_json()
            assert not db.new and not db.dirty and not db.deleted
    finally:
        await engine.dispose()
