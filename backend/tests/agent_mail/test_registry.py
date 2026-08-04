"""Registry behavior: durable members, ephemeral sessions, observed sync, staleness."""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    MailAgentSession,
    MailMessage,
    MailTeamMember,
)
from app.models.schemas import MailAgentRegisterRequest, MailMessageCreate
from app.services.agent_mail_service import (
    HEARTBEAT_TTL_SECONDS,
    INBOX_CHECK_PROMPT,
    MCP_HEARTBEAT_TTL_SECONDS,
    OBSERVED_TTL_SECONDS,
    TMUX_ENTER_DELAY_SECONDS,
    AgentMailService,
)
from app.utils.repo_utils import derive_repo_identity


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


async def _slot(db, cwd, name, *, preset=None, position=0, role=None, charter=None):
    if preset is None:
        preset = AgentTeamPreset(name="Project team")
        db.add(preset)
        await db.flush()
    ident = derive_repo_identity(cwd)
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=position,
        display_name=name,
        provider="codex-cli",
        repo_id=ident["repo_id"],
        repo_path=ident["repo_root"],
        repo_name=ident["repo_name"],
        role=role,
        charter=charter,
    )
    db.add(slot)
    await db.commit()
    await db.refresh(preset)
    await db.refresh(slot)
    return preset, slot


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
async def test_same_repo_team_slots_are_distinct_mail_participants(db, svc, tmp_path):
    cwd = tmp_path / "r"
    cwd.mkdir()
    planner_preset, planner_slot = await _slot(
        db,
        str(cwd),
        "Planner",
        position=0,
        role="planner/reviewer",
    )
    _, implementer_slot = await _slot(
        db,
        str(cwd),
        "Implementer",
        preset=planner_preset,
        position=1,
        role="implementer",
    )

    planner, _ = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(cwd),
            session_key="mcp:planner",
            team_preset_id=planner_preset.id,
            team_slot_id=planner_slot.id,
        ),
    )
    implementer, _ = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(cwd),
            session_key="mcp:implementer",
            team_preset_id=planner_preset.id,
            team_slot_id=implementer_slot.id,
        ),
    )

    assert planner.id != implementer.id
    assert planner.repo_id == implementer.repo_id
    assert planner.identity_key == svc._slot_identity_key(planner_slot)
    assert implementer.identity_key == svc._slot_identity_key(implementer_slot)

    message = await svc.send_message(
        db,
        MailMessageCreate(
            kind="handoff",
            sender_member_id=planner.id,
            recipient_member_id=implementer.id,
            body_markdown="Please implement plan v1.",
        ),
        auto_nudge=False,
    )
    planner_inbox = await svc.get_inbox(db, planner.id)
    implementer_inbox = await svc.get_inbox(db, implementer.id)

    assert planner_inbox.pending_count == 0
    assert implementer_inbox.pending_count == 1
    assert [item.id for item in implementer_inbox.messages] == [message.id]


@pytest.mark.asyncio
async def test_mcp_registration_infers_slot_from_related_hook_process(
    db,
    svc,
    tmp_path,
    monkeypatch,
):
    cwd = tmp_path / "r"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Planner")
    slot_member, hook_session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="hook",
            provider="codex-cli",
            cwd=str(cwd),
            session_key="codex:planner",
            pid=200,
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )
    monkeypatch.setattr(svc, "_pids_related", lambda left, right: {left, right} == {300, 200})

    mcp_member, mcp_session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(cwd),
            session_key="mcp:planner",
            pid=300,
        ),
    )

    assert mcp_member.id == slot_member.id
    assert mcp_session.member_id == slot_member.id
    assert mcp_session.team_preset_id == preset.id
    assert mcp_session.team_slot_id == slot.id
    assert hook_session.team_slot_id == slot.id


@pytest.mark.asyncio
async def test_observed_tmux_session_infers_slot_from_related_hook_process(
    db,
    svc,
    tmp_path,
    monkeypatch,
):
    cwd = tmp_path / "r"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Planner")
    slot_member, _hook_session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="hook",
            provider="codex-cli",
            cwd=str(cwd),
            session_key="codex:planner",
            pid=200,
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )
    monkeypatch.setattr(svc, "_pids_related", lambda left, right: {left, right} == {100, 200})
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "cwd": str(cwd),
                "pane_id": "%1",
                "pid": "100",
                "tmux_target": "planner:0.0",
            }
        ],
    )

    await svc.sync_observed_sessions(db)

    result = await db.execute(
        select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
    )
    observed = result.scalar_one()
    assert observed.member_id == slot_member.id
    assert observed.team_preset_id == preset.id
    assert observed.team_slot_id == slot.id
    assert observed.tmux_target == "planner:0.0"


@pytest.mark.asyncio
async def test_reused_session_key_clears_stale_team_slot_context(db, svc, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    preset, slot = await _slot(db, str(repo_a), "Planner")
    slot_member, session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:reused",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )

    preserved_member, preserved_session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:reused",
        ),
    )

    assert preserved_member.id == slot_member.id
    assert preserved_session.id == session.id
    assert preserved_session.team_slot_id == slot.id

    moved_member, moved_session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_b),
            session_key="mcp:reused",
        ),
    )

    assert moved_member.participant_kind == "repo"
    assert moved_member.repo_path == str(repo_b)
    assert moved_session.id == session.id
    assert moved_session.member_id == moved_member.id
    assert moved_session.team_preset_id is None
    assert moved_session.team_slot_id is None


@pytest.mark.asyncio
async def test_register_ignores_mismatched_team_slot_context(db, svc, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    preset, slot = await _slot(db, str(repo_a), "Planner")

    member, session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_b),
            session_key="mcp:mismatch",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )

    assert member.participant_kind == "repo"
    assert member.repo_path == str(repo_b)
    assert session.team_preset_id is None
    assert session.team_slot_id is None


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
async def test_observed_session_attaches_to_matching_team_slot_participant(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Implementer", role="implementer")
    member, _ = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="hook",
            provider="codex-cli",
            cwd=str(cwd),
            session_key="codex:s1",
            pid=4242,
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )
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

    assert [candidate.id for candidate in members] == [member.id]
    assert members[0].participant_kind == "team_slot"
    assert members[0].team_slot_id == slot.id
    assert members[0].can_nudge is True
    assert {session.source for session in members[0].sessions} == {"hook", "observed"}


@pytest.mark.asyncio
async def test_observed_session_ignores_stale_pid_match(db, svc, tmp_path):
    old_cwd = tmp_path / "old"
    new_cwd = tmp_path / "new"
    old_cwd.mkdir()
    new_cwd.mkdir()
    preset, slot = await _slot(db, str(old_cwd), "Old slot")
    _member, stale_session = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="hook",
            provider="codex-cli",
            cwd=str(old_cwd),
            session_key="codex:old",
            pid=4242,
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )
    stale_session.last_seen_at = datetime.utcnow() - timedelta(seconds=HEARTBEAT_TTL_SECONDS + 30)
    await db.commit()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(new_cwd),
            "pid": "4242",
            "status": "active",
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    members = await svc.list_team(db)
    observed_member = next(member for member in members if member.repo_path == str(new_cwd))

    assert observed_member.participant_kind == "repo"
    assert observed_member.repo_name == "new"
    assert observed_member.sessions[0].session_key == "tmux:%7"


@pytest.mark.asyncio
async def test_sync_preserves_observed_session_team_slot_attachment(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Reused slot")
    slot_member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=slot_member.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%7",
            cwd=str(cwd),
            tmux_target="w:0.1",
            pane_id="%7",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
            mailbox_status="observed",
        )
    )
    await db.commit()
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
    assert members[0].id == slot_member.id
    assert members[0].participant_kind == "team_slot"
    assert members[0].team_slot_id == slot.id
    assert members[0].sessions[0].team_slot_id == slot.id


@pytest.mark.asyncio
async def test_sync_does_not_preserve_team_slot_when_observed_pid_changes(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Reused slot")
    slot_member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=slot_member.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%7",
            cwd=str(cwd),
            tmux_target="w:0.1",
            pane_id="%7",
            pid=111,
            team_preset_id=preset.id,
            team_slot_id=slot.id,
            mailbox_status="observed",
        )
    )
    await db.commit()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "w:0.1",
            "session_name": "w",
            "window_name": "main",
            "pane_id": "%7",
            "cwd": str(cwd),
            "pid": "222",
            "status": "active",
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    members = await svc.list_team(db)
    session = (
        await db.execute(select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%7"))
    ).scalar_one()

    assert session.pid == 222
    assert session.team_slot_id is None
    assert session.member_id != slot_member.id
    assert members[0].participant_kind == "repo"
    assert members[0].sessions[0].session_key == "tmux:%7"


@pytest.mark.asyncio
async def test_observed_unsupported_provider_session_cannot_be_nudged(db, svc, tmp_path):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "unknown-agent",
            "provider_display_name": "Unknown Agent",
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
@pytest.mark.parametrize(
    ("provider", "display_name"),
    [("codex-cli", "Codex"), ("claude-code", "Claude Code")],
)
async def test_queue_inbox_check_sends_prompt_to_tmux_observed_agent(
    db,
    svc,
    tmp_path,
    monkeypatch,
    provider,
    display_name,
):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": provider,
            "provider_display_name": display_name,
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

    sleep_calls = []
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", sleep_calls.append)
    await svc.sync_observed_sessions(db)
    member = (await svc.list_team(db))[0]

    result = await svc.queue_inbox_check(db, member.id)
    tmux_calls = [call for call in calls if call[0][0] == "tmux"]

    assert result["target"] == "w:0.1"
    assert result["prompt"] == INBOX_CHECK_PROMPT
    assert tmux_calls[0][0] == ["tmux", "send-keys", "-t", "w:0.1", "-l", INBOX_CHECK_PROMPT]
    assert tmux_calls[1][0] == ["tmux", "send-keys", "-t", "w:0.1", "Enter"]
    assert sleep_calls == [TMUX_ENTER_DELAY_SECONDS]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "display_name"),
    [("codex-cli", "Codex"), ("claude-code", "Claude Code")],
)
async def test_send_message_auto_nudges_tmux_observed_recipient(
    db,
    svc,
    tmp_path,
    monkeypatch,
    provider,
    display_name,
):
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": provider,
            "provider_display_name": display_name,
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

    sleep_calls = []
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", sleep_calls.append)
    await svc.sync_observed_sessions(db)
    recipient = (await svc.list_team(db))[0]
    sender = MailTeamMember(
        identity_key="repo:sender",
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
    assert sleep_calls == [TMUX_ENTER_DELAY_SECONDS]


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

    sleep_calls = []
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", sleep_calls.append)
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
    assert sleep_calls == [TMUX_ENTER_DELAY_SECONDS]


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


def test_observed_session_past_ttl_with_live_pid_reads_observed(svc):
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert svc._effective_status(session, now) == "observed"


def test_revived_observed_session_is_still_nudgeable(svc):
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        provider="claude-code",
        tmux_target="tizonia:1.0",
        mailbox_status="observed",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert svc._session_can_nudge(session, now) is True


def test_observed_session_past_ttl_with_dead_pid_reads_offline(svc, monkeypatch):
    monkeypatch.setattr(svc, "_pid_is_running", lambda pid: False)
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=123456,
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert svc._effective_status(session, now) == "offline"


def test_observed_session_past_ttl_without_pid_reads_offline(svc):
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=None,
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert svc._effective_status(session, now) == "offline"


def test_explicitly_offline_observed_session_stays_offline_with_live_pid(svc):
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="offline",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert svc._effective_status(session, now) == "offline"


def test_observed_session_within_ttl_keeps_mailbox_status(svc):
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=None,
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS - 60),
    )

    assert svc._effective_status(session, now) == "observed"


def test_mcp_session_past_ttl_with_live_pid_stays_connected(svc):
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="mcp",
        mailbox_status="connected",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=MCP_HEARTBEAT_TTL_SECONDS + 60),
    )

    assert svc._effective_status(session, now) == "connected"


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
@pytest.mark.parametrize("provider", ["codex-cli", "claude-code"])
async def test_connected_mcp_session_without_tmux_is_delivered_waiting(db, svc, tmp_path, provider):
    cwd = tmp_path / "r"
    cwd.mkdir()
    await svc.register_session(
        db,
        _register(str(cwd), session_key="mcp:abc", source="mcp", provider=provider),
    )

    members = await svc.list_team(db)

    assert members[0].status == "connected"
    assert members[0].can_nudge is False
    assert members[0].wake_methods == []
    assert members[0].wake_state == "delivered_waiting"


@pytest.mark.asyncio
async def test_queue_inbox_check_does_not_use_app_server_for_connected_codex_mcp_session(db, svc, tmp_path, monkeypatch):
    cwd = tmp_path / "r"
    cwd.mkdir()
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])
    member, _ = await svc.register_session(
        db,
        _register(str(cwd), session_key="mcp:abc", source="mcp", provider="codex-cli"),
    )

    with pytest.raises(ValueError, match="No Agent Mail wake path"):
        await svc.queue_inbox_check(db, member.id)

    inbox = await svc.get_inbox(db, member.id, unread_only=True)
    assert inbox.unread_count == 0


@pytest.mark.asyncio
async def test_send_message_to_non_tmux_codex_stays_unread_until_agent_polls(db, svc, tmp_path, monkeypatch):
    cwd = tmp_path / "r"
    cwd.mkdir()
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: [])
    recipient, _ = await svc.register_session(
        db,
        _register(str(cwd), session_key="mcp:abc", source="mcp", provider="codex-cli"),
    )

    await svc.send_message(
        db,
        MailMessageCreate(
            recipient_member_id=recipient.id,
            body_markdown="please check this",
        ),
    )

    inbox = await svc.get_inbox(db, recipient.id, unread_only=True)
    assert inbox.unread_count == 1
    assert inbox.messages[0].body_markdown == "please check this"


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
