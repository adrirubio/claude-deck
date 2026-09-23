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
    MailWakeAttempt,
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
    MailWakeError,
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


async def _slot(db, cwd, name, *, preset=None, position=0, role=None, charter=None, provider="codex-cli"):
    if preset is None:
        preset = AgentTeamPreset(name="Project team")
        db.add(preset)
        await db.flush()
    ident = derive_repo_identity(cwd)
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=position,
        display_name=name,
        provider=provider,
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


async def _bound_wake_slot(db, svc, cwd, observed, monkeypatch):
    preset, slot = await _slot(
        db, str(cwd), "Owner", provider=observed[0]["provider"]
    )
    observed[0]["team_preset_id"] = preset.id
    observed[0]["team_slot_id"] = slot.id
    monkeypatch.setattr(
        "app.services.agent_mail_service.peer_process.pane_is_alive",
        lambda _pid, _start: True,
    )
    await svc.sync_observed_sessions(db)
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(MailAgentSession(
        member_id=member.id,
        source="mcp",
        provider=observed[0]["provider"],
        session_key=f"mcp:wake:{slot.id}",
        cwd=str(cwd),
        team_preset_id=preset.id,
        team_slot_id=slot.id,
        capability_token_hash=svc.hash_capability_token("wake-test-token"),
        bound_pane_pid=int(observed[0]["pid"]),
        bound_pane_proc_start="test-start",
        wake_enabled=True,
        mailbox_status="connected",
        last_seen_at=datetime.utcnow(),
    ))
    await db.commit()
    return member


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
    assert mcp_session.wake_enabled is True
    assert hook_session.wake_enabled is False
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
    assert observed.wake_enabled is False


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
    assert moved_session.wake_enabled is False


@pytest.mark.asyncio
async def test_reused_manual_mcp_key_keeps_opt_in_only_for_same_registration_identity(
    db, svc, tmp_path
):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    request = MailAgentRegisterRequest(
        source="mcp", provider="codex-cli", cwd=str(repo_a),
        session_key="mcp:manual-reused", pid=5101,
    )
    _member, session = await svc.register_session(db, request)
    session.wake_enabled = True
    session.capability_token_hash = svc.hash_capability_token("manual-token")
    session.bound_pane_pid = 5101
    session.bound_pane_proc_start = "process-start-a"
    await db.commit()

    _same_member, refreshed = await svc.register_session(db, request)
    assert refreshed.wake_enabled is True
    assert refreshed.bound_pane_pid == 5101
    assert refreshed.bound_pane_proc_start == "process-start-a"

    _new_member, rebound = await svc.register_session(
        db,
        request.model_copy(update={"cwd": str(repo_b), "pid": 5102}),
    )
    assert rebound.wake_enabled is False
    assert rebound.bound_pane_pid is None
    assert rebound.bound_pane_proc_start is None


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
    assert members[0].can_nudge is False


@pytest.mark.asyncio
async def test_sync_observed_keeps_row_whose_pid_is_alive(db, svc, tmp_path):
    """A single failed discovery pass must not delete a live pane's row.

    discover_agent_sessions() returns [] for tmux-missing, non-zero exit, and
    timeout, so [] cannot be read as "no panes exist".
    """
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%1",
            pane_id="%1",
            tmux_target="obs:0.0",
            cwd=str(cwd),
            pid=os.getpid(),
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    assert len(await svc.nudgeable_sessions_for_slot(db, slot.id)) == 0

    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=[]):
        await svc.sync_observed_sessions(db)

    kept = (
        await db.execute(select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1"))
    ).scalar_one()
    assert kept.team_slot_id == slot.id


@pytest.mark.asyncio
async def test_sync_observed_still_deletes_row_whose_pid_is_dead(db, svc, tmp_path):
    """Retention becomes pid-aware, not pid-only. A dead pane still goes."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%2",
            pane_id="%2",
            tmux_target="obs:0.1",
            cwd=str(cwd),
            pid=None,
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=[]):
        await svc.sync_observed_sessions(db)

    assert await svc.nudgeable_sessions_for_slot(db, slot.id) == []


@pytest.mark.asyncio
async def test_sync_observed_deletes_row_whose_pid_is_gone(db, svc, tmp_path):
    """A non-null pid that is not running must still be deleted."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    member = await svc.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider="codex-cli",
            session_key="tmux:%3",
            pane_id="%3",
            tmux_target="obs:0.2",
            cwd=str(cwd),
            pid=999999,
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    with patch(
        "app.services.agent_mail_service.discover_agent_sessions", return_value=[]
    ), patch.object(type(svc), "_pid_is_running", return_value=False):
        await svc.sync_observed_sessions(db)

    assert await svc.nudgeable_sessions_for_slot(db, slot.id) == []


@pytest.mark.asyncio
async def test_sync_observed_binds_slot_from_tmux_environment(db, svc, tmp_path):
    """A rebuilt row recovers its slot from the pane's own tmux env."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id == slot.id
    assert session.team_preset_id == preset.id
    member = await db.get(MailTeamMember, session.member_id)
    assert member.participant_kind == "team_slot"


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_from_another_repo(db, svc, tmp_path):
    """An advertised slot whose repo does not match the pane's cwd is rejected."""
    slot_cwd = tmp_path / "slotrepo"
    slot_cwd.mkdir()
    pane_cwd = tmp_path / "elsewhere"
    pane_cwd.mkdir()
    preset, slot = await _slot(db, str(slot_cwd), "Owner")
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(pane_cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None
    member = await db.get(MailTeamMember, session.member_id)
    assert member.participant_kind == "repo"


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_that_no_longer_exists(db, svc, tmp_path):
    """A stale tmux env naming a deleted slot falls back, it does not crash."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": 999,
            "team_slot_id": 999,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_with_a_different_provider(db, svc, tmp_path):
    """A pane advertising a slot whose provider disagrees is rejected."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    assert slot.provider == "codex-cli"
    fake = [
        {
            "provider": "claude-code",
            "provider_display_name": "Claude Code",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None


@pytest.mark.asyncio
async def test_sync_observed_ignores_env_slot_whose_preset_disagrees(db, svc, tmp_path):
    """A reused slot id with a contradictory preset id must not bind."""
    cwd = tmp_path / "obs"
    cwd.mkdir()
    preset, slot = await _slot(db, str(cwd), "Owner")
    fake = [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "obs:0.0",
            "session_name": "obs",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": str(cwd),
            "pid": "4242",
            "status": "active",
            "team_preset_id": preset.id + 500,
            "team_slot_id": slot.id,
        }
    ]
    with patch("app.services.agent_mail_service.discover_agent_sessions", return_value=fake):
        await svc.sync_observed_sessions(db)

    session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%1")
        )
    ).scalar_one()
    assert session.team_slot_id is None


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
    assert members[0].can_nudge is False
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
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

    sleep_calls = []
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", sleep_calls.append)
    member = await _bound_wake_slot(db, svc, cwd, fake, monkeypatch)

    result = await svc.queue_inbox_check(
        db, member.id, actor_type="operator", force=True, reason_code="operator_maintenance"
    )
    tmux_calls = [call for call in calls if call[0][1] == "send-keys"]

    assert result["target"] == "w:0.1"
    assert result["prompt"] == INBOX_CHECK_PROMPT
    assert tmux_calls[0][0] == ["tmux", "send-keys", "-t", "%7", "-l", INBOX_CHECK_PROMPT]
    assert tmux_calls[1][0] == ["tmux", "send-keys", "-t", "%7", "Enter"]
    assert sleep_calls == [TMUX_ENTER_DELAY_SECONDS]


@pytest.mark.asyncio
async def test_wake_never_targets_observed_only_pane_in_another_repo(
    db, svc, tmp_path, monkeypatch
):
    team_cwd = tmp_path / "team"
    other_cwd = tmp_path / "other"
    team_cwd.mkdir()
    other_cwd.mkdir()
    observed = [
        {
            "provider": "codex-cli", "tmux_target": "w:0.1", "pane_id": "%7",
            "cwd": str(team_cwd), "pid": "4242", "status": "active",
        },
        {
            "provider": "claude-code", "tmux_target": "w:0.2", "pane_id": "%8",
            "cwd": str(other_cwd), "pid": "4343", "status": "active",
        },
    ]
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", lambda _delay: None)
    recipient = await _bound_wake_slot(db, svc, team_cwd, observed, monkeypatch)
    other_session = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%8")
        )
    ).scalar_one()
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    assert await svc.auto_nudge_members(db, {recipient.id}, bypass_cooldown=True) == []
    assert not any(command[:2] == ["tmux", "send-keys"] for command in commands)
    commands.clear()
    await svc.send_direct_message(
        db, recipient_member_id=recipient.id, subject="work", body_markdown="Please review"
    )
    assert [command[3] for command in commands if command[:2] == ["tmux", "send-keys"]] == [
        "%7", "%7"
    ]
    commands.clear()
    await svc.send_direct_message(
        db, recipient_member_id=other_session.member_id,
        subject="other", body_markdown="Unrelated project",
    )
    assert not any(command[:2] == ["tmux", "send-keys"] for command in commands)
    attempts = (await db.execute(select(MailWakeAttempt))).scalars().all()
    assert [(attempt.member_id, attempt.failure_code) for attempt in attempts] == [
        (recipient.id, "inbox_empty"),
        (recipient.id, None),
        (other_session.member_id, "wake_target_unbound"),
    ]


@pytest.mark.asyncio
async def test_wake_refuses_dead_binding_and_changed_tmux_pane(
    db, svc, tmp_path, monkeypatch
):
    cwd = tmp_path / "team"
    cwd.mkdir()
    observed = [{
        "provider": "codex-cli", "tmux_target": "w:0.1", "pane_id": "%7",
        "cwd": str(cwd), "pid": "4242", "status": "active",
    }]
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    member = await _bound_wake_slot(db, svc, cwd, observed, monkeypatch)
    observed_row = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key == "tmux:%7")
        )
    ).scalar_one()
    observed_row.mailbox_status = "offline"
    await db.commit()
    with pytest.raises(MailWakeError, match="wake_target_unbound"):
        await svc._nudge_session_for_member(db, member.id, datetime.utcnow())
    observed_row.mailbox_status = "observed"
    await db.commit()
    monkeypatch.setattr(
        "app.services.agent_mail_service.peer_process.pane_is_alive",
        lambda _pid, _start: False,
    )
    with pytest.raises(MailWakeError, match="wake_target_unbound"):
        await svc.queue_inbox_check(
            db, member.id, actor_type="operator", force=True,
            reason_code="operator_maintenance",
        )

    monkeypatch.setattr(
        "app.services.agent_mail_service.peer_process.pane_is_alive",
        lambda _pid, _start: True,
    )
    commands = []

    def changed_pane(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(stdout="%7|9999", stderr="", returncode=0)

    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", changed_pane)
    with pytest.raises(MailWakeError, match="wake_target_stale"):
        await svc.queue_inbox_check(
            db, member.id, actor_type="operator", force=True,
            reason_code="operator_maintenance",
        )
    assert not any(command[:2] == ["tmux", "send-keys"] for command in commands)


@pytest.mark.asyncio
async def test_observed_discovery_alone_does_not_make_repo_session_wakeable(
    db, svc, tmp_path, monkeypatch
):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    observed = [{
        "provider": "codex-cli", "tmux_target": "w:0.1", "pane_id": "%21",
        "cwd": str(cwd), "pid": "4210", "status": "active",
    }]
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    await svc.sync_observed_sessions(db)
    member = await svc.get_or_create_repo_member(db, str(cwd))
    with pytest.raises(MailWakeError, match="wake_target_unbound"):
        await svc._nudge_session_for_member(db, member.id, datetime.utcnow())


@pytest.mark.asyncio
async def test_manual_repo_mcp_can_opt_in_to_exact_observed_pane(
    db, svc, tmp_path, monkeypatch
):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    observed = [{
        "provider": "codex-cli", "tmux_target": "w:0.1", "pane_id": "%22",
        "cwd": str(cwd), "pid": "4220", "status": "active",
    }]
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    monkeypatch.setattr(
        "app.services.agent_mail_service.peer_process.pane_is_alive",
        lambda _pid, _start: True,
    )
    member, registered = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp", provider="codex-cli", cwd=str(cwd),
            session_key="mcp:manual-repo", pid=4220,
        ),
    )
    assert registered.wake_enabled is False
    await svc.sync_observed_sessions(db)
    registered.bound_pane_pid = 4220
    registered.bound_pane_proc_start = "test-start"
    registered.capability_token_hash = svc.hash_capability_token("manual-token")
    await db.commit()

    observed_row = (await db.execute(
        select(MailAgentSession).where(MailAgentSession.source == "observed")
    )).scalar_one()
    other_cwd = tmp_path / "other-repo"
    other_cwd.mkdir()
    other_member = await svc.get_or_create_repo_member(db, str(other_cwd))
    observed_row.member_id = other_member.id
    await db.commit()
    with pytest.raises(MailWakeError, match="wake_target_unbound"):
        await svc.set_wake_enabled(
            db, registered.id, True, actor_type="operator", reason_code="manual_opt_in"
        )
    observed_row.member_id = member.id
    await db.commit()

    await svc.set_wake_enabled(
        db, registered.id, True, actor_type="operator", reason_code="manual_opt_in"
    )
    target = await svc._nudge_session_for_member(db, member.id, datetime.utcnow())
    audit = (await db.execute(select(MailWakeAttempt))).scalar_one()
    assert target.pane_id == "%22"
    assert member.participant_kind == "repo"
    assert member.team_slot_id is None
    assert member.role is None
    assert audit.source == "participation_change"
    assert audit.result == "enabled"


@pytest.mark.asyncio
async def test_opted_in_repo_binding_refuses_multiple_matching_panes(
    db, svc, tmp_path, monkeypatch
):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    observed = [
        {"provider": "codex-cli", "tmux_target": f"w:0.{index}",
         "pane_id": f"%{index + 30}", "cwd": str(cwd), "pid": "4230",
         "status": "active"}
        for index in range(2)
    ]
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    monkeypatch.setattr(
        "app.services.agent_mail_service.peer_process.pane_is_alive",
        lambda _pid, _start: True,
    )
    member, registered = await svc.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp", provider="codex-cli", cwd=str(cwd),
            session_key="mcp:ambiguous-repo", pid=4230,
        ),
    )
    await svc.sync_observed_sessions(db)
    registered.bound_pane_pid = 4230
    registered.bound_pane_proc_start = "test-start"
    registered.capability_token_hash = svc.hash_capability_token("manual-token")
    registered.wake_enabled = True
    await db.commit()
    with pytest.raises(MailWakeError, match="wake_target_ambiguous"):
        await svc._nudge_session_for_member(db, member.id, datetime.utcnow())


@pytest.mark.asyncio
async def test_duplicate_mcp_bindings_for_one_pane_refuse_wake_and_opt_in(
    db, svc, tmp_path, monkeypatch
):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    observed = [{
        "provider": "codex-cli", "tmux_target": "w:0.1", "pane_id": "%41",
        "cwd": str(cwd), "pid": "4241", "status": "active",
    }]
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    member = await _bound_wake_slot(db, svc, cwd, observed, monkeypatch)
    original = (await db.execute(
        select(MailAgentSession).where(MailAgentSession.source == "mcp")
    )).scalar_one()
    duplicate = MailAgentSession(
        member_id=member.id,
        source="mcp",
        provider=original.provider,
        session_key="mcp:duplicate-binding",
        cwd=original.cwd,
        team_preset_id=original.team_preset_id,
        team_slot_id=original.team_slot_id,
        capability_token_hash=svc.hash_capability_token("duplicate-token"),
        bound_pane_pid=original.bound_pane_pid,
        bound_pane_proc_start=original.bound_pane_proc_start,
        wake_enabled=False,
        mailbox_status="connected",
        last_seen_at=datetime.utcnow(),
    )
    db.add(duplicate)
    await db.commit()

    with pytest.raises(MailWakeError, match="wake_target_ambiguous"):
        await svc._nudge_session_for_member(db, member.id, datetime.utcnow())
    with pytest.raises(MailWakeError, match="wake_target_ambiguous"):
        await svc.set_wake_enabled(
            db, duplicate.id, True, actor_type="operator", reason_code="manual_opt_in"
        )
    assert duplicate.wake_enabled is False


@pytest.mark.asyncio
async def test_opt_out_suppresses_manual_and_automatic_team_wakes(
    db, svc, tmp_path, monkeypatch
):
    cwd = tmp_path / "repo"
    cwd.mkdir()
    observed = [{
        "provider": "codex-cli", "tmux_target": "w:0.1", "pane_id": "%7",
        "cwd": str(cwd), "pid": "4242", "status": "active",
    }]
    commands = []
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: observed
    )
    monkeypatch.setattr(
        "app.services.agent_mail_service.subprocess.run",
        lambda command, **_kwargs: commands.append(command)
        or SimpleNamespace(stdout="%7|4242", stderr="", returncode=0),
    )
    member = await _bound_wake_slot(db, svc, cwd, observed, monkeypatch)
    binding = (await db.execute(
        select(MailAgentSession).where(MailAgentSession.source == "mcp")
    )).scalar_one()
    await svc.set_wake_enabled(
        db, binding.id, False, actor_type="operator", reason_code="manual_opt_out"
    )
    assert await svc.auto_nudge_members(db, {member.id}, bypass_cooldown=True) == []
    with pytest.raises(MailWakeError, match="wake_opted_out"):
        await svc.queue_inbox_check(
            db, member.id, actor_type="operator", force=True,
            reason_code="operator_maintenance",
        )
    assert not any(command[:2] == ["tmux", "send-keys"] for command in commands)


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
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

    sleep_calls = []
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", sleep_calls.append)
    recipient = await _bound_wake_slot(db, svc, cwd, fake, monkeypatch)
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

    tmux_calls = [call for call in calls if call[0][1] == "send-keys"]
    assert tmux_calls[0][0] == ["tmux", "send-keys", "-t", "%7", "-l", INBOX_CHECK_PROMPT]
    assert tmux_calls[1][0] == ["tmux", "send-keys", "-t", "%7", "Enter"]
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
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

    sleep_calls = []
    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", sleep_calls.append)
    recipient = await _bound_wake_slot(db, svc, cwd, fake, monkeypatch)
    calls.clear()

    for body in ("first", "second"):
        await svc.send_message(
            db,
            MailMessageCreate(
                recipient_member_id=recipient.id,
                body_markdown=body,
            ),
        )

    tmux_calls = [call for call in calls if call[0][1] == "send-keys"]
    assert len(tmux_calls) == 2
    assert sleep_calls == [TMUX_ENTER_DELAY_SECONDS]


@pytest.mark.asyncio
async def test_dispatch_brief_nudge_bypasses_the_cooldown(db, svc, tmp_path, monkeypatch):
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
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", lambda _: None)
    recipient = await _bound_wake_slot(db, svc, cwd, fake, monkeypatch)
    calls.clear()

    await svc.send_direct_message(
        db,
        recipient_member_id=recipient.id,
        subject="blocker merged",
        body_markdown="fyi",
    )
    assert len([command for command, _ in calls if command[1] == "send-keys"]) == 2

    dispatch_nudge_prompt = "Read issue #900 and execute that assignment now."
    await svc.send_direct_message(
        db,
        recipient_member_id=recipient.id,
        subject="Autonomous dispatch: issue #900",
        body_markdown="brief",
        bypass_nudge_cooldown=True,
        nudge_prompt=dispatch_nudge_prompt,
    )

    tmux_calls = [command for command, _ in calls if command[1] == "send-keys"]
    assert len(tmux_calls) == 4
    assert tmux_calls[2] == [
        "tmux",
        "send-keys",
        "-t",
        "%7",
        "-l",
        dispatch_nudge_prompt,
    ]


@pytest.mark.asyncio
async def test_ordinary_send_still_throttled_after_a_bypassed_brief(
    db, svc, tmp_path, monkeypatch
):
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
        return SimpleNamespace(
            stdout="%7|4242" if command[1] == "display-message" else "",
            stderr="", returncode=0,
        )

    monkeypatch.setattr("app.services.agent_mail_service.discover_agent_sessions", lambda: fake)
    monkeypatch.setattr("app.services.agent_mail_service.subprocess.run", fake_run)
    monkeypatch.setattr("app.services.agent_mail_service.time.sleep", lambda _: None)
    recipient = await _bound_wake_slot(db, svc, cwd, fake, monkeypatch)
    calls.clear()

    await svc.send_direct_message(
        db,
        recipient_member_id=recipient.id,
        subject="brief",
        body_markdown="b",
        bypass_nudge_cooldown=True,
    )
    assert len([command for command, _ in calls if command[1] == "send-keys"]) == 2

    await svc.send_direct_message(
        db,
        recipient_member_id=recipient.id,
        subject="chatter",
        body_markdown="c",
    )
    assert len([command for command, _ in calls if command[1] == "send-keys"]) == 2


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

    with pytest.raises(MailWakeError, match="wake_target_unbound"):
        await svc.queue_inbox_check(
            db, member.id, actor_type="operator", force=True,
            reason_code="operator_maintenance",
        )

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
