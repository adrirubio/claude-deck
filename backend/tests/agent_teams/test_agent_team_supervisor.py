"""An optional supervisor promises its next check without gaining authority."""
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import AgentTeamPreset, MailExternalActor


@pytest_asyncio.fixture
async def supervisor_client(db, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "synthetic-director-token")

    async def database():
        yield db

    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = database
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous


async def supervisor_team(db):
    team = AgentTeamPreset(name="Supervised", description="Optional supervision.")
    actor = MailExternalActor(actor_key="supervisor-fixture", display_name="Supervisor",
                              kind="external_tool", token_hash=hashlib.sha256(b"synthetic-actor-token").hexdigest())
    db.add_all([team, actor])
    await db.commit()
    return team, actor


@pytest.mark.asyncio
async def test_director_can_bind_supervisor_without_starting_automation(db, supervisor_client):
    team, actor = await supervisor_team(db)
    team_id, actor_id = team.id, actor.id
    response = await supervisor_client.put(f"/api/v1/agent-teams/presets/{team_id}/supervisor",
        headers={"X-Deck-Operator-Token": "synthetic-director-token"}, json={"actor_id": actor_id})
    assert response.status_code == 200
    assert response.json()["actor_id"] == actor_id
    assert response.json()["status"] == "absent"
    await db.refresh(team)
    assert team.supervisor_actor_id == actor_id
    assert not team.autonomy_enabled


@pytest.mark.parametrize("elapsed,status", [(-1, "healthy"), (0, "late"), (1799, "late"), (1800, "absent")])
def test_supervisor_status_uses_clock_boundaries(elapsed, status):
    from app.services.agent_team_supervisor_service import supervisor_observation
    promised = datetime(2026, 10, 13, tzinfo=timezone.utc)
    team = SimpleNamespace(supervisor_actor_id=7, supervisor_checked_at=promised - timedelta(minutes=10),
        supervisor_next_check_at=promised, supervisor_grace_seconds=None, supervisor_note="Checked.")
    result = supervisor_observation(team, now=promised + timedelta(seconds=elapsed))
    assert result["status"] == status
    assert result["grace_seconds"] == 1800
    assert result["attention"] == ("Supervisor check-in overdue" if status in {"late", "absent"} else None)


def test_supervisor_status_none_is_optional_and_default_grace_uses_last_interval():
    from app.services.agent_team_supervisor_service import supervisor_observation
    promised = datetime(2026, 10, 13)
    team = SimpleNamespace(supervisor_actor_id=None, supervisor_checked_at=None,
        supervisor_next_check_at=None, supervisor_grace_seconds=None, supervisor_note=None)
    assert supervisor_observation(team, now=promised)["status"] == "none"
    team.supervisor_actor_id = 7
    assert supervisor_observation(team, now=promised)["status"] == "absent"
    team.supervisor_checked_at = promised - timedelta(hours=1)
    team.supervisor_next_check_at = promised
    assert supervisor_observation(team, now=promised)["grace_seconds"] == 7200
    team.supervisor_grace_seconds = 120
    assert supervisor_observation(team, now=promised + timedelta(seconds=120))["status"] == "absent"


@pytest.mark.parametrize("seconds", [-1, 0, 86401])
def test_supervisor_refuses_invalid_promises(seconds):
    from app.services.agent_team_supervisor_service import validate_promise
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="supervisor_next_check_invalid"):
        validate_promise(now + timedelta(seconds=seconds), now=now)
