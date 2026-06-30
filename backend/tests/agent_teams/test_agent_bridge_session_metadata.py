"""Agent Bridge session metadata for Agent Team launches."""

import pytest

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
