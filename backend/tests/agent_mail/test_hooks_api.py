"""Hook ingest endpoints: register, inject, heartbeat, fail soft."""
import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.database import MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service


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
