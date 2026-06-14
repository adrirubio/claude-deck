"""Registry behavior: durable members, ephemeral sessions, observed sync, staleness."""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.database import MailMessage, MailTeamMember
from app.models.schemas import MailAgentRegisterRequest, MailMessageCreate
from app.services.agent_mail_service import (
    HEARTBEAT_TTL_SECONDS,
    INBOX_CHECK_PROMPT,
    MCP_HEARTBEAT_TTL_SECONDS,
    AgentMailService,
)


@pytest.fixture
def svc():
    return AgentMailService()


def _register(cwd, session_key="cc:s1", source="hook", provider="claude-code", pid=None):
    return MailAgentRegisterRequest(
        source=source,
        provider=provider,
        cwd=cwd,
        session_key=session_key,
        pid=pid,
    )


@pytest.mark.asyncio
async def test_register_creates_member_named_after_repo(db, svc, tmp_path):
    cwd = tmp_path / "myrepo"
    cwd.mkdir()
    member, session = await svc.register_session(db, _register(str(cwd)))
    assert member.display_name == "myrepo"
    assert session.mailbox_status == "connected"
    assert session.member_id == member.id


@pytest.mark.asyncio
async def test_second_session_same_repo_reuses_member(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    m1, _ = await svc.register_session(db, _register(str(cwd), session_key="cc:s1"))
    m2, s2 = await svc.register_session(
        db,
        _register(str(cwd), session_key="mcp:abc", source="mcp"),
    )
    assert m1.id == m2.id
    assert s2.session_key == "mcp:abc"


@pytest.mark.asyncio
async def test_reregister_same_session_key_updates_not_duplicates(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    _, s1 = await svc.register_session(db, _register(str(cwd)))
    _, s2 = await svc.register_session(db, _register(str(cwd)))
    assert s1.id == s2.id


@pytest.mark.asyncio
async def test_member_identity_survives_session_end(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    member, _ = await svc.register_session(db, _register(str(cwd)))
    member.role = "backend expert"
    await db.commit()
    await svc.mark_session_offline(db, "cc:s1")
    m2, _ = await svc.register_session(db, _register(str(cwd), session_key="cc:s2"))
    assert m2.id == member.id
    assert m2.role == "backend expert"


@pytest.mark.asyncio
async def test_sync_observed_creates_observed_sessions(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)
    members = await svc.list_team(db)
    assert len(members) == 1
    assert members[0].status == "observed"
    assert members[0].sessions[0].session_key == "tmux:%7"
    assert members[0].can_nudge is True


@pytest.mark.asyncio
async def test_observed_non_codex_session_cannot_be_nudged(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "claude-code",
            "provider_display_name": "Claude Code",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    members = await svc.list_team(db)

    assert members[0].status == "observed"
    assert members[0].can_nudge is False


@pytest.mark.asyncio
async def test_queue_inbox_check_sends_prompt_to_tmux_observed_codex(db, svc, tmp_path, monkeypatch):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    await svc.sync_observed_sessions(db)
    member = (await svc.list_team(db))[0]

    result = await svc.queue_inbox_check(db, member.id)
    tmux_calls = [call for call in calls if call[0][0] == "tmux"]

    assert result["target"] == "w:0.1"
    assert result["prompt"] == INBOX_CHECK_PROMPT
    assert tmux_calls[0][0] == ["tmux", "send-keys", "-t", "w:0.1", "-l", INBOX_CHECK_PROMPT]
    assert tmux_calls[1][0] == ["tmux", "send-keys", "-t", "w:0.1", "Enter"]


@pytest.mark.asyncio
async def test_send_message_auto_nudges_tmux_observed_codex_recipient(db, svc, tmp_path, monkeypatch):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="", stderr="", returncode=0 if command[0] == "tmux" else 1)

    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    await svc.sync_observed_sessions(db)
    recipient = (await svc.list_team(db))[0]
    sender = MailTeamMember(
        repo_id="sender",
        repo_path="/tmp/sender",
        repo_name="sender",
        display_name="sender",
    )
    db.add(sender)
    await db.commit()
    await db.refresh(sender)
    calls.clear()

    await svc.send_message(
        db,
        MailMessageCreate(
            sender_member_id=sender.id,
            recipient_member_id=recipient.id,
            body_markdown="please check this",
        ),
    )

    tmux_calls = [call for call in calls if call[0][0] == "tmux"]
    assert tmux_calls[0][0] == ["tmux", "send-keys", "-t", "w:0.1", "-l", INBOX_CHECK_PROMPT]
    assert tmux_calls[1][0] == ["tmux", "send-keys", "-t", "w:0.1", "Enter"]


@pytest.mark.asyncio
async def test_send_message_auto_nudge_is_throttled(db, svc, tmp_path, monkeypatch):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout="", stderr="", returncode=0 if command[0] == "tmux" else 1)

    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    await svc.sync_observed_sessions(db)
    recipient = (await svc.list_team(db))[0]
    calls.clear()

    for body in ("first", "second"):
        await svc.send_message(
            db,
            MailMessageCreate(
                recipient_member_id=recipient.id,
                body_markdown=body,
            ),
        )

    tmux_calls = [call for call in calls if call[0][0] == "tmux"]
    assert len(tmux_calls) == 2


@pytest.mark.asyncio
async def test_sync_observed_removes_stale_observed_only_members(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)
    assert len(await svc.list_team(db)) == 1

    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=[]):
        await svc.sync_observed_sessions(db)

    assert await svc.list_team(db) == []


@pytest.mark.asyncio
async def test_sync_observed_keeps_stale_member_with_mail_history(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)
    member = (await svc.list_team(db))[0]
    db.add(
        MailMessage(
            kind="message",
            sender_member_id=None,
            recipient_member_id=member.id,
            body_markdown="keep this member",
        )
    )
    await db.commit()

    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=[]):
        await svc.sync_observed_sessions(db)

    members = await svc.list_team(db)
    assert len(members) == 1
    assert members[0].status == "offline"
    assert members[0].sessions == []


@pytest.mark.asyncio
async def test_stale_connected_session_reports_offline(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    _, session = await svc.register_session(db, _register(str(cwd)))
    session.last_seen_at = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()
    members = await svc.list_team(db)
    assert members[0].status == "offline"


@pytest.mark.asyncio
async def test_mcp_session_uses_longer_connected_window(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    _, session = await svc.register_session(
        db,
        _register(str(cwd), session_key="mcp:abc", source="mcp", provider="codex-cli"),
    )
    session.last_seen_at = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()
    members = await svc.list_team(db)
    assert members[0].status == "connected"

    session.last_seen_at = datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()
    members = await svc.list_team(db)
    assert members[0].status == "offline"


@pytest.mark.asyncio
async def test_live_mcp_process_stays_connected_after_heartbeat_ttl(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    _, session = await svc.register_session(
        db,
        _register(
            str(cwd),
            session_key="mcp:abc",
            source="mcp",
            provider="codex-cli",
            pid=os.getpid(),
        ),
    )
    session.last_seen_at = datetime.utcnow() - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()

    members = await svc.list_team(db)

    assert members[0].status == "connected"
    assert members[0].sessions[0].mailbox_status == "connected"


@pytest.mark.asyncio
async def test_dead_mcp_process_reports_offline_even_before_ttl(db, svc, tmp_path, monkeypatch):
    cwd = tmp_path / "r"
    cwd.mkdir()
    await svc.register_session(
        db,
        _register(
            str(cwd),
            session_key="mcp:abc",
            source="mcp",
            provider="codex-cli",
            pid=12345,
        ),
    )
    monkeypatch.setattr(svc, "_pid_is_running", lambda pid: False)

    members = await svc.list_team(db)

    assert members[0].status == "offline"
    assert members[0].sessions[0].mailbox_status == "offline"


@pytest.mark.asyncio
async def test_heartbeat_refreshes_and_sets_activity(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    _, session = await svc.register_session(db, _register(str(cwd)))
    session.last_seen_at = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TTL_SECONDS + 60)
    await db.commit()
    await svc.heartbeat_session(db, "cc:s1", activity="edited src/main.py")
    members = await svc.list_team(db)
    assert members[0].status == "connected"
    assert members[0].sessions[0].activity == "edited src/main.py"
