"""Hook ingest endpoints: register, inject, heartbeat, fail soft."""
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models.database import AgentTeamPreset, AgentTeamSlot, MailAgentSession, MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service
from app.utils.repo_utils import derive_repo_identity


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_session_start_registers_and_injects(client, db, tmp_path):
    cwd = tmp_path / "myrepo"
    cwd.mkdir()
    resp = await client.post(
        "/api/v1/agent-mail/hooks/session-start",
        json={"session_id": "s1", "cwd": str(cwd), "source": "startup"},
    )
    assert resp.status_code == 200
    out = resp.json()["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert 'You are "myrepo"' in out["additionalContext"]

    team = await agent_mail_service.list_team(db)
    assert team[0].status == "connected"


@pytest.mark.asyncio
async def test_codex_hook_registers_with_codex_session_key(client, db, tmp_path):
    cwd = tmp_path / "myrepo"
    cwd.mkdir()

    resp = await client.post(
        "/api/v1/agent-mail/hooks/session-start",
        json={
            "provider": "codex-cli",
            "session_id": "codex-session",
            "cwd": str(cwd),
            "pid": 123,
        },
    )

    assert resp.status_code == 200
    team = await agent_mail_service.list_team(db)
    assert team[0].sessions[0].provider == "codex-cli"
    assert team[0].sessions[0].session_key == "codex:codex-session"


@pytest.mark.asyncio
async def test_codex_hook_session_key_is_team_slot_qualified(client, db, tmp_path):
    cwd = tmp_path / "myrepo"
    cwd.mkdir()
    ident = derive_repo_identity(str(cwd))
    preset = AgentTeamPreset(name="Same repo team")
    db.add(preset)
    await db.flush()
    planner = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Planner",
        provider="codex-cli",
        repo_id=ident["repo_id"],
        repo_path=ident["repo_root"],
        repo_name=ident["repo_name"],
    )
    implementer = AgentTeamSlot(
        preset_id=preset.id,
        position=1,
        display_name="Implementer",
        provider="codex-cli",
        repo_id=ident["repo_id"],
        repo_path=ident["repo_root"],
        repo_name=ident["repo_name"],
    )
    db.add_all([planner, implementer])
    await db.commit()
    await db.refresh(preset)
    await db.refresh(planner)
    await db.refresh(implementer)

    for slot in (planner, implementer):
        resp = await client.post(
            "/api/v1/agent-mail/hooks/session-start",
            json={
                "provider": "codex-cli",
                "session_id": "shared-resumed-session",
                "cwd": str(cwd),
                "pid": 123,
                "team_preset_id": preset.id,
                "team_slot_id": slot.id,
            },
        )
        assert resp.status_code == 200

    sessions = (
        await db.execute(
            select(MailAgentSession).order_by(MailAgentSession.session_key.asc())
        )
    ).scalars().all()
    assert {session.session_key for session in sessions} == {
        f"codex:shared-resumed-session:team-slot:{planner.id}",
        f"codex:shared-resumed-session:team-slot:{implementer.id}",
    }
    assert {session.team_slot_id for session in sessions} == {planner.id, implementer.id}


@pytest.mark.asyncio
async def test_session_start_without_session_id_fails_soft(client):
    resp = await client.post("/api/v1/agent-mail/hooks/session-start", json={"cwd": "/tmp"})
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_user_prompt_submit_injects_only_when_inbox_nonempty(client, db, tmp_path):
    cwd_path = tmp_path / "myrepo"
    cwd_path.mkdir()
    cwd = str(cwd_path)
    await client.post(
        "/api/v1/agent-mail/hooks/session-start",
        json={"session_id": "s1", "cwd": cwd},
    )
    resp = await client.post(
        "/api/v1/agent-mail/hooks/user-prompt-submit",
        json={"session_id": "s1", "cwd": cwd, "prompt": "hi"},
    )
    assert resp.json() == {}

    team = await agent_mail_service.list_team(db)
    me = team[0]
    other = MailTeamMember(
        identity_key="repo:other",
        repo_id="other",
        repo_path="/tmp/o",
        repo_name="o",
        display_name="o",
    )
    db.add(other)
    await db.commit()
    await db.refresh(other)
    await agent_mail_service.send_message(
        db,
        MailMessageCreate(sender_member_id=other.id, recipient_member_id=me.id, body_markdown="ping"),
    )

    resp = await client.post(
        "/api/v1/agent-mail/hooks/user-prompt-submit",
        json={"session_id": "s1", "cwd": cwd, "prompt": "hi"},
    )
    out = resp.json()["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert "1 unread" in out["additionalContext"]


@pytest.mark.asyncio
async def test_session_end_marks_offline(client, db, tmp_path):
    cwd_path = tmp_path / "myrepo"
    cwd_path.mkdir()
    cwd = str(cwd_path)
    await client.post(
        "/api/v1/agent-mail/hooks/session-start",
        json={"session_id": "s1", "cwd": cwd},
    )
    resp = await client.post(
        "/api/v1/agent-mail/hooks/session-end",
        json={"session_id": "s1", "cwd": cwd},
    )
    assert resp.status_code == 200
    team = await agent_mail_service.list_team(db)
    assert team[0].status == "offline"


@pytest.mark.asyncio
async def test_post_tool_use_updates_activity(client, db, tmp_path):
    cwd_path = tmp_path / "myrepo"
    cwd_path.mkdir()
    cwd = str(cwd_path)
    await client.post(
        "/api/v1/agent-mail/hooks/session-start",
        json={"session_id": "s1", "cwd": cwd},
    )
    resp = await client.post(
        "/api/v1/agent-mail/hooks/post-tool-use",
        json={
            "session_id": "s1",
            "cwd": cwd,
            "tool_name": "Edit",
            "tool_input": {"file_path": f"{cwd}/src/main.py"},
        },
    )
    assert resp.status_code == 200
    team = await agent_mail_service.list_team(db)
    assert "main.py" in team[0].sessions[0].activity
