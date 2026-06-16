"""Tests for Agent Team preset service behavior."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.database import AgentTeamSlot
from app.models.schemas import (
    AgentTeamCreateFromMailRequest,
    AgentTeamCreateFromBridgeRequest,
    AgentTeamLaunchRequest,
    AgentTeamPresetCreate,
    AgentTeamSlotCreate,
    AgentTeamSlotUpdate,
)
from app.services.agent_mail_service import agent_mail_service
from app.models.schemas import MailAgentRegisterRequest
from app.services.agent_team_service import PlanConflictError, agent_team_service


def _ready_install_status():
    return SimpleNamespace(
        claude_code_mcp_installed=True,
        claude_code_hooks_missing=[],
        codex_cli_available=True,
        codex_mcp_installed=True,
        codex_hooks_missing=[],
    )


def _provider():
    return SimpleNamespace(
        display_name="Codex",
        get_status=lambda: {"installed": True},
        build_spawn_command=lambda options: ["codex", "--cd", options.directory],
    )


def _provider_with_blocked_directory():
    def build_spawn_command(options):
        if options.directory.endswith("blocked"):
            raise ValueError("blocked directory cannot launch")
        return ["codex", "--cd", options.directory]

    return SimpleNamespace(
        display_name="Codex",
        get_status=lambda: {"installed": True},
        build_spawn_command=build_spawn_command,
    )


@pytest.fixture(autouse=True)
def no_real_process_boundaries(monkeypatch):
    async def fake_install_status():
        return _ready_install_status()

    async def fake_sync_observed_sessions(_db):
        return None

    monkeypatch.setattr("app.services.agent_team_service.get_provider", lambda _provider_id: _provider())
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_install_service.get_install_status",
        fake_install_status,
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.sync_observed_sessions",
        fake_sync_observed_sessions,
    )
    monkeypatch.setattr("app.services.agent_team_service.discover_agent_sessions", lambda: [])


@pytest.mark.asyncio
async def test_duplicate_enabled_repo_slots_are_rejected(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Primary",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )

    with pytest.raises(ValueError, match="duplicate enabled slots"):
        await agent_team_service.add_slot(
            db,
            preset.id,
            AgentTeamSlotCreate(
                display_name="Duplicate",
                provider="codex-cli",
                repo_path=str(repo),
            ),
        )

    updated = await agent_team_service.add_slot(
        db,
        preset.id,
        AgentTeamSlotCreate(
            display_name="Disabled alternative",
            provider="codex-cli",
            repo_path=str(repo),
            enabled=False,
        ),
    )
    assert len(updated.slots) == 2


@pytest.mark.asyncio
async def test_blank_repo_path_is_rejected(db):
    with pytest.raises(ValueError, match="Repo path is required"):
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad team",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="Missing repo",
                        provider="codex-cli",
                        repo_path="",
                    )
                ],
            ),
        )


@pytest.mark.asyncio
async def test_repo_path_outside_allowed_roots_is_rejected(db):
    with pytest.raises(ValueError, match="Repo path must be under the current user's home directory"):
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad root",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="System root",
                        provider="codex-cli",
                        repo_path="/",
                    )
                ],
            ),
        )


@pytest.mark.asyncio
async def test_duplicate_preset_names_are_rejected(db, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="A",
                    provider="codex-cli",
                    repo_path=str(repo_a),
                )
            ],
        ),
    )

    with pytest.raises(ValueError, match="already exists"):
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Project team",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="B",
                        provider="codex-cli",
                        repo_path=str(repo_b),
                    )
                ],
            ),
        )


@pytest.mark.asyncio
async def test_create_from_agent_mail_uses_selected_members(db, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    member_a, _session_a = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:a",
        ),
    )
    member_b, _session_b = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="claude-code",
            cwd=str(repo_b),
            session_key="mcp:b",
        ),
    )
    member_b.role = "Frontend"
    member_b.charter = "Own the web app."
    await db.commit()

    preset = await agent_team_service.create_from_agent_mail(
        db,
        AgentTeamCreateFromMailRequest(
            name="Selected roster",
            member_ids=[member_b.id],
        ),
    )

    assert len(preset.slots) == 1
    assert preset.slots[0].display_name == member_b.display_name
    assert preset.slots[0].provider == "claude-code"
    assert preset.slots[0].role == "Frontend"
    assert preset.slots[0].charter == "Own the web app."
    assert member_a.id != member_b.id


@pytest.mark.asyncio
async def test_create_from_agent_bridge_imports_current_bridge_sessions(db, tmp_path, monkeypatch):
    repo_a = tmp_path / "deck"
    repo_b = tmp_path / "music"
    repo_a.mkdir()
    repo_b.mkdir()
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "deck-agent",
                "tmux_target": "deck-agent:0.0",
                "cwd": str(repo_a),
            },
            {
                "provider": "claude-code",
                "session_name": "music-agent",
                "tmux_target": "music-agent:0.0",
                "cwd": str(repo_b),
            },
        ],
    )

    preset = await agent_team_service.create_from_agent_bridge(
        db,
        AgentTeamCreateFromBridgeRequest(name="Bridge team"),
    )

    assert preset.created_by == "agent-bridge"
    assert [slot.display_name for slot in preset.slots] == ["deck-agent", "music-agent"]
    assert [slot.provider for slot in preset.slots] == ["codex-cli", "claude-code"]
    assert [slot.repo_path for slot in preset.slots] == [str(repo_a), str(repo_b)]


@pytest.mark.asyncio
async def test_create_from_agent_bridge_deduplicates_repo_sessions(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "repo-a",
                "tmux_target": "repo-a:0.0",
                "cwd": str(repo),
            },
            {
                "provider": "codex-cli",
                "session_name": "repo-b",
                "tmux_target": "repo-b:0.0",
                "cwd": str(repo),
            },
        ],
    )

    preset = await agent_team_service.create_from_agent_bridge(
        db,
        AgentTeamCreateFromBridgeRequest(name="Bridge team"),
    )

    assert len(preset.slots) == 1
    assert preset.slots[0].display_name == "repo-a"


@pytest.mark.asyncio
async def test_create_from_agent_bridge_rejects_empty_bridge(db):
    with pytest.raises(ValueError, match="No Agent Bridge sessions"):
        await agent_team_service.create_from_agent_bridge(
            db,
            AgentTeamCreateFromBridgeRequest(name="Bridge team"),
        )


@pytest.mark.asyncio
async def test_reorder_rejects_duplicate_slot_ids(db, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="A",
                    provider="codex-cli",
                    repo_path=str(repo_a),
                ),
                AgentTeamSlotCreate(
                    display_name="B",
                    provider="codex-cli",
                    repo_path=str(repo_b),
                ),
            ],
        ),
    )

    with pytest.raises(ValueError, match="slot_ids must include exactly"):
        await agent_team_service.reorder_slots(
            db,
            preset.id,
            [preset.slots[0].id, preset.slots[0].id],
        )


@pytest.mark.asyncio
async def test_launch_requires_confirmed_plan_hash_and_passes_team_env(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    assert plan.can_launch is True
    assert plan.items[0].action == "spawn"

    with pytest.raises(PlanConflictError):
        await agent_team_service.launch(db, preset.id, AgentTeamLaunchRequest())

    calls = []

    def fake_spawn(provider_id, options, *, extra_env=None):
        calls.append((provider_id, options, extra_env))
        return {"session_name": "repo-abcd", "tmux_target": "repo-abcd:0.0"}

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    result = await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash, requested_by="test"),
    )

    assert result.status == "completed"
    assert result.items[0].status == "pending_registration"
    assert calls[0][0] == "codex-cli"
    assert calls[0][2]["CLAUDE_DECK_TEAM_PRESET_ID"] == str(preset.id)
    assert calls[0][2]["CLAUDE_DECK_TEAM_SLOT_ID"] == str(preset.slots[0].id)


@pytest.mark.asyncio
async def test_launch_uses_custom_bootstrap_prompt(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Bootstrap team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                    bootstrap_prompt="Custom team startup prompt.",
                )
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    calls = []

    def fake_spawn(provider_id, options, *, extra_env=None):
        calls.append((provider_id, options, extra_env))
        return {"session_name": "repo-abcd", "tmux_target": "repo-abcd:0.0"}

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )

    assert calls[0][1].prompt == "Custom team startup prompt."


@pytest.mark.asyncio
async def test_launch_rejects_blocked_plan_without_partial_spawn(db, tmp_path, monkeypatch):
    runnable_repo = tmp_path / "runnable"
    blocked_repo = tmp_path / "blocked"
    runnable_repo.mkdir()
    blocked_repo.mkdir()
    monkeypatch.setattr(
        "app.services.agent_team_service.get_provider",
        lambda _provider_id: _provider_with_blocked_directory(),
    )
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Mixed team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Runnable",
                    provider="codex-cli",
                    repo_path=str(runnable_repo),
                ),
                AgentTeamSlotCreate(
                    display_name="Blocked",
                    provider="codex-cli",
                    repo_path=str(blocked_repo),
                ),
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    assert plan.can_launch is False
    assert {item.action for item in plan.items} == {"spawn", "blocked"}

    calls = []
    monkeypatch.setattr(
        "app.services.agent_team_service.spawn_session",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="Launch plan is blocked"):
        await agent_team_service.launch(
            db,
            preset.id,
            AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
        )

    assert calls == []


@pytest.mark.asyncio
async def test_reuse_tags_only_the_matched_session(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Reuse team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Selected agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    slot = preset.slots[0]
    _member, older_session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:older",
        ),
    )
    _member, selected_session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:selected",
        ),
    )
    selected_session.tmux_target = "repo:0.0"
    await db.commit()
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "repo",
                "tmux_target": "repo:0.0",
                "cwd": str(repo),
            }
        ],
    )

    plan = await agent_team_service.plan_launch(db, preset.id)
    assert plan.items[0].action == "reuse"
    assert plan.items[0].matching_session["tmux_target"] == "repo:0.0"

    await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )
    await db.refresh(older_session)
    await db.refresh(selected_session)

    assert older_session.team_slot_id is None
    assert selected_session.team_slot_id == slot.id


@pytest.mark.asyncio
async def test_reuse_does_not_validate_spawn_only_options(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Reuse team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Running agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "repo",
                "tmux_target": "repo:0.0",
                "cwd": str(repo),
            }
        ],
    )

    plan = await agent_team_service.plan_launch(db, preset.id)

    assert plan.can_launch is True
    assert plan.items[0].action == "reuse"


@pytest.mark.asyncio
async def test_mcp_only_session_is_not_reused_without_bridge_observation(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="MCP-only team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Running agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:running",
        ),
    )

    plan = await agent_team_service.plan_launch(db, preset.id)

    assert plan.can_launch is True
    assert plan.items[0].action == "spawn"


@pytest.mark.asyncio
async def test_reuse_existing_false_plans_spawn_even_with_bridge_match(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Force spawn team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Running agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "repo",
                "tmux_target": "repo:0.0",
                "cwd": str(repo),
            }
        ],
    )

    plan = await agent_team_service.plan_launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(reuse_existing=False),
    )

    assert plan.items[0].action == "spawn"


@pytest.mark.asyncio
async def test_disabled_slots_are_excluded_from_default_plan(db, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Disabled slot team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="A",
                    provider="codex-cli",
                    repo_path=str(repo_a),
                ),
                AgentTeamSlotCreate(
                    display_name="B",
                    provider="codex-cli",
                    repo_path=str(repo_b),
                    enabled=False,
                ),
            ],
        ),
    )

    default_plan = await agent_team_service.plan_launch(db, preset.id)
    full_plan = await agent_team_service.plan_launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(include_disabled=True),
    )

    assert [item.slot_name for item in default_plan.items] == ["A"]
    assert [item.action for item in full_plan.items] == ["spawn", "skip"]
    assert full_plan.items[1].status == "skipped"


@pytest.mark.asyncio
async def test_agent_mail_registration_preserves_team_slot_context(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Release team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Release lead",
                    provider="codex-cli",
                    repo_path=str(repo),
                    role="Release engineer",
                    charter="Own release validation.",
                )
            ],
        ),
    )
    slot = preset.slots[0]

    member, session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:test",
            pid=123,
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )

    assert session.team_preset_id == preset.id
    assert session.team_slot_id == slot.id
    context = await agent_mail_service.build_session_start_context(
        db,
        member.id,
        session_key=session.session_key,
    )
    assert 'Agent Team: "Release team" / slot "Release lead".' in context
    assert "Release engineer" in context
    assert "Own release validation." in context

    _member, registered_again = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:test",
            pid=123,
        ),
    )
    assert registered_again.team_preset_id == preset.id
    assert registered_again.team_slot_id == slot.id


@pytest.mark.asyncio
async def test_deleting_slot_or_preset_clears_session_team_context(db, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Cleanup team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="A",
                    provider="codex-cli",
                    repo_path=str(repo_a),
                ),
                AgentTeamSlotCreate(
                    display_name="B",
                    provider="codex-cli",
                    repo_path=str(repo_b),
                ),
            ],
        ),
    )
    slot_a, slot_b = preset.slots
    _member, session_a = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:a",
            team_preset_id=preset.id,
            team_slot_id=slot_a.id,
        ),
    )
    _member, session_b = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_b),
            session_key="mcp:b",
            team_preset_id=preset.id,
            team_slot_id=slot_b.id,
        ),
    )

    await agent_team_service.delete_slot(db, slot_a.id)
    await db.refresh(session_a)
    await db.refresh(session_b)
    assert session_a.team_preset_id is None
    assert session_a.team_slot_id is None
    assert session_b.team_preset_id == preset.id
    assert session_b.team_slot_id == slot_b.id

    _member, session_a = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:a",
            team_preset_id=preset.id,
            team_slot_id=slot_a.id,
        ),
    )
    assert session_a.team_preset_id is None
    assert session_a.team_slot_id is None

    await agent_team_service.delete_preset(db, preset.id)
    await db.refresh(session_b)
    orphaned_slots = (
        await db.execute(select(AgentTeamSlot).where(AgentTeamSlot.preset_id == preset.id))
    ).scalars().all()
    assert session_b.team_preset_id is None
    assert session_b.team_slot_id is None
    assert orphaned_slots == []


@pytest.mark.asyncio
async def test_changing_slot_identity_clears_old_session_team_context(db, tmp_path):
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Moving team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Moving slot",
                    provider="codex-cli",
                    repo_path=str(repo_a),
                )
            ],
        ),
    )
    slot = preset.slots[0]
    _member, session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:moving",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )

    await agent_team_service.update_slot(
        db,
        slot.id,
        AgentTeamSlotUpdate(repo_path=str(repo_b)),
    )
    await db.refresh(session)

    assert session.team_preset_id is None
    assert session.team_slot_id is None

    _member, session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo_a),
            session_key="mcp:moving",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )
    assert session.team_preset_id is None
    assert session.team_slot_id is None


@pytest.mark.asyncio
async def test_stale_team_env_does_not_reattach_after_slot_provider_change(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Provider move",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Moving slot",
                    provider="codex-cli",
                    repo_path=str(repo),
                )
            ],
        ),
    )
    slot = preset.slots[0]
    _member, session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:stale-env",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )
    await agent_team_service.update_slot(
        db,
        slot.id,
        AgentTeamSlotUpdate(provider="claude-code"),
    )

    _member, session = await agent_mail_service.register_session(
        db,
        MailAgentRegisterRequest(
            source="mcp",
            provider="codex-cli",
            cwd=str(repo),
            session_key="mcp:stale-env",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )

    assert session.team_preset_id is None
    assert session.team_slot_id is None
