"""Agent Bridge session metadata for Agent Team launches."""

import pytest
from datetime import datetime, timedelta

from app.models.database import MailAgentSession, MailTeamMember
from app.services.agent_mail_service import agent_mail_service
from app.utils import peer_process

from app.models.database import AgentTeamPreset, AgentTeamSlot


@pytest.mark.asyncio
async def test_agent_bridge_sessions_enrich_team_role_from_db(db, tmp_path):
    from app.api.v1.agent_bridge.router import _enrich_team_sessions

    preset = AgentTeamPreset(name="SnazzyEmail", description="", created_by="test")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Architect",
        provider="claude-code",
        repo_id="repo-1",
        repo_path=str(tmp_path),
        repo_name="repo",
        role="architect",
        charter="Own architecture",
        ui_color="purple",
        launch_mode="plain",
        launch_options={},
        enabled=True,
    )
    db.add(slot)
    await db.commit()

    sessions = await _enrich_team_sessions(
        [
            {
                "provider": "claude-code",
                "tmux_target": "snazzyemail:0.0",
                "team_slot_id": slot.id,
            }
        ],
        db,
    )

    assert sessions[0]["team_preset_id"] == preset.id
    assert sessions[0]["team_preset_name"] == "SnazzyEmail"
    assert sessions[0]["team_slot_name"] == "Architect"
    assert sessions[0]["team_slot_position"] == 0
    assert sessions[0]["team_slot_role"] == "architect"
    assert sessions[0]["team_slot_charter"] == "Own architecture"
    assert sessions[0]["team_slot_color"] == "purple"


@pytest.mark.asyncio
async def test_agent_bridge_mail_projection_matches_same_repo_panes_independently(
    db, monkeypatch
):
    from app.api.v1.agent_bridge import router as bridge_router

    discovered = []
    expected_member_ids = []
    expected_mcp_ids = []
    for index in range(2):
        preset = AgentTeamPreset(name=f"Preset {index}", description="", created_by="test")
        db.add(preset)
        await db.flush()
        slot = AgentTeamSlot(
            preset_id=preset.id,
            position=0,
            display_name=f"Pane {index}",
            provider="codex-cli",
            repo_id="same-repo",
            repo_path="/tmp/same-repo",
            repo_name="same-repo",
            launch_mode="plain",
            launch_options={},
            enabled=True,
        )
        db.add(slot)
        await db.flush()
        member = MailTeamMember(
            identity_key=f"slot:same-repo:{slot.id}",
            repo_id="same-repo",
            repo_path="/tmp/same-repo",
            repo_name="same-repo",
            display_name=f"Member {index}",
            participant_kind="team_slot",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        )
        db.add(member)
        await db.flush()
        pane_id = f"%{index + 1}"
        pane_pid = 7000 + index
        observed = MailAgentSession(
            member_id=member.id,
            provider="codex-cli",
            source="observed",
            session_key=f"tmux:{pane_id}",
            pane_id=pane_id,
            pid=pane_pid,
            tmux_target=f"deck:{index}.0",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
        observed.wake_enabled = True
        db.add(observed)
        mcp = MailAgentSession(
            member_id=member.id,
            provider="codex-cli",
            source="mcp",
            session_key=f"mcp:{index}",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
            mailbox_status="connected",
            last_seen_at=datetime.utcnow(),
            capability_token_hash=agent_mail_service.hash_capability_token(
                f"secret-token-{index}"
            ),
            bound_pane_pid=pane_pid,
            bound_pane_proc_start=f"start-{pane_pid}",
        )
        mcp.wake_enabled = True
        db.add(mcp)
        await db.flush()
        expected_member_ids.append(member.id)
        expected_mcp_ids.append(mcp.id)
        discovered.append(
            {
                "provider": "codex-cli",
                "tmux_target": f"deck:{index}.0",
                "pane_id": pane_id,
                "cwd": "/tmp/same-repo",
                "pid": str(pane_pid),
                "team_slot_id": slot.id,
            }
        )
    await db.commit()
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: True)
    monkeypatch.setattr(
        bridge_router, "discover_agent_sessions", lambda _provider: discovered
    )

    async def fail_if_sync_is_called(*_args, **_kwargs):
        raise AssertionError("GET /sessions must not synchronize observed sessions")

    monkeypatch.setattr(
        agent_mail_service, "sync_observed_sessions", fail_if_sync_is_called
    )

    response = await bridge_router.list_sessions(db=db)
    projected = response["sessions"]

    assert [pane["mail_member_id"] for pane in projected] == expected_member_ids
    assert [pane["mail_mcp_session_id"] for pane in projected] == expected_mcp_ids
    assert [pane["mail_wake_state"] for pane in projected] == ["wakeable", "wakeable"]
    assert [pane["mail_wake_target"] for pane in projected] == ["deck:0.0", "deck:1.0"]
    assert "secret-token-0" not in str(projected)
    assert "capability_token_hash" not in str(projected)


@pytest.mark.asyncio
async def test_agent_bridge_mail_projection_marks_stale_binding_without_mutation(
    db, monkeypatch
):
    from app.api.v1.agent_bridge.router import _project_mail_wake_state

    preset = AgentTeamPreset(name="Stale", description="", created_by="test")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Stale pane",
        provider="codex-cli",
        repo_id="stale-repo",
        repo_path="/tmp/stale-repo",
        repo_name="stale-repo",
        launch_mode="plain",
        launch_options={},
        enabled=True,
    )
    db.add(slot)
    await db.flush()
    member = MailTeamMember(
        identity_key=f"slot:stale-repo:{slot.id}",
        repo_id="stale-repo",
        repo_path="/tmp/stale-repo",
        repo_name="stale-repo",
        display_name="Stale",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=slot.id,
    )
    db.add(member)
    await db.flush()
    observed = MailAgentSession(
        member_id=member.id,
        provider="codex-cli",
        source="observed",
        session_key="tmux:%stale",
        pane_id="%stale",
        pid=8000,
        tmux_target="deck:stale.0",
        team_preset_id=preset.id,
        team_slot_id=slot.id,
        mailbox_status="observed",
        last_seen_at=datetime.utcnow(),
    )
    observed.wake_enabled = True
    db.add(observed)
    db.add(
        MailAgentSession(
            member_id=member.id,
            provider="codex-cli",
            source="mcp",
            session_key="mcp:stale",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
            mailbox_status="connected",
            last_seen_at=datetime.utcnow() - timedelta(hours=2),
            capability_token_hash=agent_mail_service.hash_capability_token("stale-secret"),
            bound_pane_pid=8000,
            bound_pane_proc_start="old-start",
        )
    )
    await db.commit()
    before = observed.last_seen_at
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: True)

    projected = await _project_mail_wake_state(
        [{
            "provider": "codex-cli",
            "tmux_target": "deck:stale.0",
            "pane_id": "%stale",
            "cwd": "/tmp/stale-repo",
            "pid": "8000",
        }],
        db,
    )

    assert projected[0]["mail_wake_state"] == "stale"
    assert projected[0]["mail_wake_reason"] == "wake_target_stale"
    assert projected[0]["mail_mcp_session_id"] is None
    assert projected[0]["mail_wake_target"] is None
    assert observed.last_seen_at == before


@pytest.mark.asyncio
async def test_agent_bridge_projection_does_not_expose_wrong_context_binding(db, monkeypatch):
    from app.api.v1.agent_bridge.router import _project_mail_wake_state

    member = MailTeamMember(
        identity_key="repo:projection-context",
        repo_id="projection-context",
        repo_path="/tmp/projection-context",
        repo_name="projection-context",
        display_name="Context",
    )
    db.add(member)
    await db.flush()
    db.add(MailAgentSession(
        member_id=member.id,
        provider="codex-cli",
        source="observed",
        session_key="tmux:%context",
        pane_id="%context",
        pid=8100,
        tmux_target="deck:context.0",
        cwd="/tmp/projection-context",
        mailbox_status="observed",
        last_seen_at=datetime.utcnow(),
    ))
    db.add(MailAgentSession(
        member_id=member.id,
        provider="codex-cli",
        source="mcp",
        session_key="mcp:wrong-context",
        cwd="/tmp/other-context",
        capability_token_hash=agent_mail_service.hash_capability_token("secret"),
        bound_pane_pid=8100,
        bound_pane_proc_start="start-8100",
        wake_enabled=True,
        mailbox_status="connected",
        last_seen_at=datetime.utcnow(),
    ))
    await db.commit()
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: True)

    projected = await _project_mail_wake_state([{
        "provider": "codex-cli",
        "tmux_target": "deck:context.0",
        "pane_id": "%context",
        "pid": "8100",
    }], db)

    assert projected[0]["mail_mcp_session_id"] is None
    assert projected[0]["mail_wake_enabled"] is None
    assert projected[0]["mail_wake_target"] is None


@pytest.mark.asyncio
async def test_agent_bridge_mail_projection_reports_ambiguous_observation_read_only(db):
    from app.api.v1.agent_bridge.router import _project_mail_wake_state

    member = MailTeamMember(
        identity_key="repo:ambiguous",
        repo_id="ambiguous",
        repo_path="/tmp/ambiguous",
        repo_name="ambiguous",
        display_name="Ambiguous",
    )
    db.add(member)
    await db.flush()
    observed_rows = []
    for session_key in ("tmux:ambiguous:one", "tmux:ambiguous:two"):
        observed = MailAgentSession(
            member_id=member.id,
            provider="codex-cli",
            source="observed",
            session_key=session_key,
            pane_id="%ambiguous",
            pid=9000,
            tmux_target="deck:ambiguous.0",
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
        db.add(observed)
        observed_rows.append(observed)
    await db.commit()
    before = [row.last_seen_at for row in observed_rows]

    projected = await _project_mail_wake_state(
        [{
            "provider": "codex-cli",
            "tmux_target": "deck:ambiguous.0",
            "pane_id": "%ambiguous",
            "cwd": "/tmp/ambiguous",
            "pid": "9000",
        }],
        db,
    )

    assert projected[0]["mail_wake_state"] == "ambiguous"
    assert projected[0]["mail_wake_reason"] == "wake_target_ambiguous"
    assert projected[0]["mail_wake_target"] is None
    assert [row.last_seen_at for row in observed_rows] == before
