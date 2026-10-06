"""V19: duplicate and import identity mapping with explicit Leader authority."""
from datetime import datetime

import pytest
from sqlalchemy import select, text

from app.models.database import AgentTeamPreset, AgentTeamSlot, GithubWorkItem, MailTeamMember, TeamGithubScope
from app.models.schemas import (
    AgentTeamCreateFromBridgeRequest,
    AgentTeamCreateFromMailRequest,
    AgentTeamPresetCreate,
    AgentTeamSlotCreate,
)
from app.services.agent_team_service import agent_team_service
from app.services.github_dispatch_service import github_dispatch_service

pytestmark = pytest.mark.asyncio


async def _assign(db, preset_id, slot_id):
    await db.execute(text("UPDATE agent_team_presets SET leader_slot_id = :slot WHERE id = :preset"),
                     {"slot": slot_id, "preset": preset_id})
    await db.commit()


async def test_v19_duplicate_maps_non_first_tied_and_unassigned_leaders(db, tmp_path):
    repo = tmp_path / "v19-dup"
    repo.mkdir()
    source = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V19 source", slots=[
        AgentTeamSlotCreate(display_name="First", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="Second", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="Third", repo_path=str(repo)),
    ]))
    source_ids = [slot.id for slot in source.slots]
    await _assign(db, source.id, source_ids[1])

    clone = await agent_team_service.duplicate_preset(db, source.id, name="V19 clone")
    clone_ids = [slot.id for slot in clone.slots]
    # The clone owns new slot IDs and maps its own corresponding Leader slot.
    assert set(clone_ids).isdisjoint(source_ids)
    assert clone.leader_slot_id == clone_ids[1]
    assert [slot.display_name for slot in clone.slots] == ["First", "Second", "Third"]
    assert clone.autonomy_enabled is False
    # Source identities are preserved unchanged.
    reloaded = await agent_team_service.get_preset(db, source.id)
    assert reloaded.leader_slot_id == source_ids[1]
    assert [slot.id for slot in reloaded.slots] == source_ids

    # Tied positions map by the same slot index.
    tied = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V19 tied", slots=[
        AgentTeamSlotCreate(display_name="Tied A", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="Tied B", repo_path=str(repo)),
    ]))
    tied_ids = [slot.id for slot in tied.slots]
    await db.execute(text("UPDATE agent_team_slots SET position = 0 WHERE preset_id = :preset"),
                     {"preset": tied.id})
    await _assign(db, tied.id, tied_ids[1])
    tied_clone = await agent_team_service.duplicate_preset(db, tied.id, name="V19 tied clone")
    assert tied_clone.leader_slot_id == tied_clone.slots[1].id
    assert tied_clone.leader_slot_id not in tied_ids

    # An unassigned source stays unassigned and inactive in the clone.
    bare = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V19 bare", slots=[
        AgentTeamSlotCreate(display_name="Solo", repo_path=str(repo)),
    ]))
    bare_clone = await agent_team_service.duplicate_preset(db, bare.id, name="V19 bare clone")
    assert bare_clone.leader_slot_id is None
    assert bare_clone.autonomy_enabled is False


async def test_v19_mail_import_creates_new_unassigned_inactive_ids(db, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from app.models.database import MailAgentSession
    from app.services.agent_mail_service import agent_mail_service

    # Synthetic provider discovery and synthetic provider readiness: no host
    # harness is read or contacted in a CI-like environment.
    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", AsyncMock())
    monkeypatch.setattr(agent_team_service, "_fallback_provider", AsyncMock(return_value="codex-cli"))
    for member_id, name in ((901, "Imported owner"), (902, "Imported worker")):
        db.add(MailTeamMember(
            id=member_id, identity_key=f"slot:v19-{member_id}", repo_id="v19",
            repo_path=str(tmp_path), repo_name="v19", display_name=name,
            participant_kind="team_slot", team_preset_id=None, team_slot_id=None))
    for session_id, member_id, provider in ((801, 901, "codex-cli"), (802, 902, "pi-cli")):
        db.add(MailAgentSession(
            id=session_id, member_id=member_id, provider=provider, source="mcp",
            session_key=f"mcp:v19-{session_id}", wake_enabled=True,
            mailbox_status="connected", last_seen_at=datetime.utcnow()))
    await db.flush()
    member_ids = [901, 902]

    preset = await agent_team_service.create_from_agent_mail(
        db, AgentTeamCreateFromMailRequest(name="V19 mail import", member_ids=member_ids))

    slot_ids = [slot.id for slot in preset.slots]
    # The import must create real slots from the synthetic sessions.
    assert len(slot_ids) == 2
    assert set(slot_ids).isdisjoint(member_ids)
    assert [slot.provider for slot in preset.slots] == ["codex-cli", "pi-cli"]
    assert preset.leader_slot_id is None
    assert preset.autonomy_enabled is False
    # Source member identities are preserved unchanged.
    for member_id in member_ids:
        member = await db.get(MailTeamMember, member_id)
        assert member is not None
        assert member.team_slot_id is None


async def test_v19_bridge_import_creates_new_unassigned_inactive_ids(db, tmp_path, monkeypatch):
    repo = tmp_path / "v19-bridge"
    repo.mkdir()
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {"provider": "codex-cli", "session_name": "bridge-agent",
             "tmux_target": "bridge-agent:0.0", "cwd": str(repo)},
        ],
    )

    preset = await agent_team_service.create_from_agent_bridge(
        db, AgentTeamCreateFromBridgeRequest(name="V19 bridge import"))

    assert preset.created_by == "agent-bridge"
    assert preset.leader_slot_id is None
    assert preset.autonomy_enabled is False
    assert [slot.display_name for slot in preset.slots] == ["bridge-agent"]


async def test_v19_import_activation_refuses_dispatch_without_assignment(db, tmp_path):
    """An unassigned imported team refuses dispatch instead of choosing a Leader."""
    repo = tmp_path / "v19-refuse"
    repo.mkdir()
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V19 refuse", slots=[
        AgentTeamSlotCreate(display_name="Only", repo_path=str(repo)),
    ]))
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="example", repo_name="v19-refuse",
                            repo_path=str(repo))
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=19, issue_title="v19",
                          issue_url="https://example.invalid/19",
                          github_updated_at=datetime.utcnow())
    db.add(item)
    await db.commit()

    launched = []

    async def fake_launcher(db_ignored, preset_id, request):
        launched.append(preset_id)
        raise AssertionError("dispatch must refuse before any launch")

    await github_dispatch_service.dispatch_pending(
        db, scope, list(preset.slots), launcher=fake_launcher,
        issue_labels_by_number={19: [scope.dispatch_label]},
        issue_details_by_number={19: {"body": "v19"}}, )
    await db.refresh(item)
    assert launched == []
    assert item.pending_reason == "leader_unavailable"


async def test_v19_reordered_authority_consumers_follow_explicit_assignment(db, tmp_path):
    repo = tmp_path / "v19-reorder"
    repo.mkdir()
    team = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="V19 reorder", slots=[
        AgentTeamSlotCreate(display_name="Alpha", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="Bravo", repo_path=str(repo)),
        AgentTeamSlotCreate(display_name="Charlie", repo_path=str(repo)),
    ]))
    slot_ids = [slot.id for slot in team.slots]
    await _assign(db, team.id, slot_ids[1])
    # The assigned Leader starts in the middle. Reorder moves it away from
    # first position to last.
    await db.execute(text("UPDATE agent_team_slots SET position = CASE id WHEN :a THEN 2 WHEN :b THEN 0 "
                          "ELSE 1 END WHERE preset_id = :preset"),
                     {"a": slot_ids[1], "b": slot_ids[0], "preset": team.id})
    await db.commit()

    slots = list((await db.scalars(
        select(AgentTeamSlot).where(AgentTeamSlot.preset_id == team.id)
        .order_by(AgentTeamSlot.position, AgentTeamSlot.id))).all())
    leader_id = slot_ids[1]
    assert slots[-1].id == slot_ids[1], "the explicit Leader must remain non-first"
    assert slots[0].id != slot_ids[1]
    # Real consumers follow the explicit assignment after the reorder.
    assert github_dispatch_service._leader_slot(slots, leader_id).id == leader_id
    preset = await agent_team_service.get_preset(db, team.id)
    leader_slot = next(slot for slot in slots if slot.id == leader_id)
    other_slot = next(slot for slot in slots if slot.id == slot_ids[0])
    assert await agent_team_service._slot_is_leader(db, preset, leader_slot) is True
    assert await agent_team_service._slot_is_leader(db, preset, other_slot) is False
    scope = TeamGithubScope(preset_id=team.id, repo_owner="example", repo_name="v19-reorder",
                            repo_path=str(repo))
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=21, issue_title="v19 reorder",
                          issue_url="https://example.invalid/21",
                          github_updated_at=datetime.utcnow())
    db.add(item)
    await db.commit()
    routed = await github_dispatch_service.route_item(db, item, slots, [], leader_slot_id=leader_id)
    assert routed == (leader_id, "leader_fallback")
