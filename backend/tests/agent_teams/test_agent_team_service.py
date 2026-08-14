"""Tests for Agent Team preset service behavior."""
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.database import AgentTeamSlot, MailAgentSession, MailTeamMember
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
        copilot_cli_available=True,
        copilot_mcp_installed=True,
        copilot_hooks_missing=[],
        opencode_cli_available=True,
        opencode_mcp_installed=True,
        opencode_plugin_events_missing=[],
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
async def test_duplicate_enabled_repo_slots_are_allowed(db, tmp_path):
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

    updated = await agent_team_service.add_slot(
        db,
        preset.id,
        AgentTeamSlotCreate(
            display_name="Implementer",
            provider="codex-cli",
            repo_path=str(repo),
        ),
    )
    assert [slot.display_name for slot in updated.slots] == ["Primary", "Implementer"]

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
    assert len(updated.slots) == 3


@pytest.mark.asyncio
async def test_slot_ui_color_is_persisted_and_clearable(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Color team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Reviewer",
                    provider="codex-cli",
                    repo_path=str(repo),
                    ui_color="purple",
                )
            ],
        ),
    )

    assert preset.slots[0].ui_color == "purple"

    updated = await agent_team_service.update_slot(
        db,
        preset.slots[0].id,
        AgentTeamSlotUpdate(ui_color="cyan"),
    )
    assert updated.slots[0].ui_color == "cyan"

    updated = await agent_team_service.update_slot(
        db,
        preset.slots[0].id,
        AgentTeamSlotUpdate(ui_color=None),
    )
    assert updated.slots[0].ui_color is None


@pytest.mark.asyncio
async def test_slot_ui_color_rejects_unknown_palette_value(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError) as exc_info:
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad color",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="Reviewer",
                        provider="codex-cli",
                        repo_path=str(repo),
                        ui_color="magenta",
                    )
                ],
            ),
        )

    assert "Unsupported ui_color: magenta" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_slot_rejects_unknown_launch_option(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError) as exc_info:
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad options",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="Dev",
                        provider="codex-cli",
                        repo_path=str(repo),
                        launch_options={"reasoning_efort": "xhigh"},
                    )
                ],
            ),
        )

    assert "Unsupported launch_options for codex-cli" in str(exc_info.value)
    assert "reasoning_efort" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_slot_rejects_provider_launch_mode_mismatch(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError) as exc_info:
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad mode",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="OpenCode",
                        provider="opencode-cli",
                        repo_path=str(repo),
                        launch_mode="fork",
                    )
                ],
            ),
        )

    assert "Unsupported launch_mode for opencode-cli: fork" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_slot_rejects_opencode_reasoning_effort(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError) as exc_info:
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad effort",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="OpenCode",
                        provider="opencode-cli",
                        repo_path=str(repo),
                        launch_options={"reasoning_effort": "xhigh"},
                    )
                ],
            ),
        )

    assert getattr(exc_info.value, "block_code", None) == "reasoning_effort_unsupported"


@pytest.mark.asyncio
async def test_create_slot_rejects_copilot_bedrock_options(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError) as exc_info:
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Bad copilot bedrock",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="Copilot",
                        provider="copilot-cli",
                        repo_path=str(repo),
                        launch_options={
                            "platform": "bedrock",
                            "aws_profile": "jrubio",
                        },
                    )
                ],
            ),
        )

    assert "copilot-cli does not support Bedrock launch options" in str(exc_info.value)
    assert "aws_profile" in str(exc_info.value)
    assert "platform" in str(exc_info.value)


@pytest.mark.asyncio
async def test_launch_plan_warnings_are_included_in_plan_hash(db, tmp_path, monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Warn team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Reviewer",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_options={
                        "platform": "bedrock",
                        "bedrock_model": "openai.gpt-5.5",
                    },
                )
            ],
        ),
    )

    first_plan = await agent_team_service.plan_launch(db, preset.id, AgentTeamLaunchRequest())
    assert first_plan.items[0].warnings

    await agent_team_service.update_slot(
        db,
        preset.slots[0].id,
        AgentTeamSlotUpdate(
            launch_options={
                "platform": "bedrock",
                "aws_region": "us-east-1",
                "aws_profile": "bedrock-prod",
                "bedrock_model": "openai.gpt-5.5",
            }
        ),
    )
    second_plan = await agent_team_service.plan_launch(db, preset.id, AgentTeamLaunchRequest())

    assert second_plan.items[0].warnings != first_plan.items[0].warnings
    assert second_plan.plan_hash != first_plan.plan_hash


@pytest.mark.asyncio
async def test_create_slot_rejects_malformed_model_id(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    with pytest.raises(ValueError) as exc_info:
        await agent_team_service.create_preset(
            db,
            AgentTeamPresetCreate(
                name="Malformed model",
                slots=[
                    AgentTeamSlotCreate(
                        display_name="Reviewer",
                        provider="codex-cli",
                        repo_path=str(repo),
                        launch_options={
                            "platform": "bedrock",
                            "bedrock_model": "OpenAI Pro GPT-5.5",
                        },
                    )
                ],
            ),
        )

    assert "launch_options.bedrock_model must be a concrete provider model ID" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_slot_warns_on_well_formed_unknown_codex_bedrock_model(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Unknown model",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Reviewer",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_options={
                        "platform": "bedrock",
                        "aws_region": "us-east-1",
                        "aws_profile": "jrubio",
                        "bedrock_model": "openai.not-a-real-model",
                    },
                )
            ],
        ),
    )

    assert preset.slots[0].warnings == [
        "Codex Bedrock model requires an AWS account or gateway that exposes this model."
    ]


@pytest.mark.asyncio
async def test_multiple_same_repo_codex_resume_last_slots_are_blocked(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": True},
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": True},
                ),
            ],
        ),
    )

    plan = await agent_team_service.plan_launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(reuse_existing=False),
    )

    assert plan.can_launch is False
    assert plan.spawn_count == 0
    assert plan.blocked_count == 2
    assert {item.block_code for item in plan.items} == {"unsafe_codex_resume_last"}
    assert all("resume --last cannot be used" in item.reasons[0] for item in plan.items)


@pytest.mark.asyncio
async def test_explicit_same_repo_codex_resume_sessions_are_allowed(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": False, "session_id": "planner-session"},
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="codex-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": False, "session_id": "implementer-session"},
                ),
            ],
        ),
    )

    plan = await agent_team_service.plan_launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(reuse_existing=False),
    )

    assert plan.can_launch is True
    assert plan.spawn_count == 2
    assert plan.blocked_count == 0


@pytest.mark.asyncio
async def test_multiple_same_repo_copilot_continue_slots_are_blocked(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Project team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="copilot-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": True},
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="copilot-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": True},
                ),
            ],
        ),
    )

    plan = await agent_team_service.plan_launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(reuse_existing=False),
    )

    assert plan.can_launch is False
    assert plan.spawn_count == 0
    assert plan.blocked_count == 2
    assert {item.block_code for item in plan.items} == {"unsafe_copilot_continue"}
    assert all("Copilot CLI --continue cannot be used" in item.reasons[0] for item in plan.items)


@pytest.mark.asyncio
async def test_multiple_same_repo_opencode_continue_slots_are_blocked(db, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="OpenCode team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="opencode-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": True},
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="opencode-cli",
                    repo_path=str(repo),
                    launch_mode="resume",
                    launch_options={"use_last": True},
                ),
            ],
        ),
    )

    plan = await agent_team_service.plan_launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(reuse_existing=False),
    )

    assert plan.can_launch is False
    assert plan.spawn_count == 0
    assert plan.blocked_count == 2
    assert {item.block_code for item in plan.items} == {"unsafe_opencode_continue"}
    assert all("OpenCode --continue cannot be used" in item.reasons[0] for item in plan.items)


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
async def test_create_from_agent_bridge_keeps_same_repo_sessions(db, tmp_path, monkeypatch):
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

    assert [slot.display_name for slot in preset.slots] == ["repo-a", "repo-b"]


@pytest.mark.asyncio
async def test_plan_launch_reuses_distinct_same_repo_sessions(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Same repo team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "implementer",
                "tmux_target": "implementer:0.0",
                "cwd": str(repo),
            },
            {
                "provider": "codex-cli",
                "session_name": "planner",
                "tmux_target": "planner:0.0",
                "cwd": str(repo),
            },
        ],
    )

    plan = await agent_team_service.plan_launch(db, preset.id)

    assert [item.action for item in plan.items] == ["reuse", "reuse"]
    assert [item.matching_session["tmux_target"] for item in plan.items] == [
        "planner:0.0",
        "implementer:0.0",
    ]


@pytest.mark.asyncio
async def test_plan_launch_does_not_reuse_ambiguous_same_repo_sessions(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Same repo team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="A",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
                AgentTeamSlotCreate(
                    display_name="B",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
            ],
        ),
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "main",
                "tmux_target": "main:0.0",
                "cwd": str(repo),
            },
            {
                "provider": "codex-cli",
                "session_name": "backup",
                "tmux_target": "backup:0.0",
                "cwd": str(repo),
            },
        ],
    )

    plan = await agent_team_service.plan_launch(db, preset.id)

    assert [item.action for item in plan.items] == ["spawn", "spawn"]


@pytest.mark.asyncio
async def test_plan_launch_prefers_existing_same_repo_slot_attachment(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Same repo team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
            ],
        ),
    )
    planner_slot = await db.get(AgentTeamSlot, preset.slots[0].id)
    implementer_slot = await db.get(AgentTeamSlot, preset.slots[1].id)
    planner_member = await agent_mail_service.get_or_create_slot_member(db, planner_slot)
    implementer_member = await agent_mail_service.get_or_create_slot_member(db, implementer_slot)
    db.add_all(
        [
            MailAgentSession(
                member_id=planner_member.id,
                source="observed",
                provider="codex-cli",
                session_key="tmux:%1",
                tmux_target="planner:0.0",
                pane_id="%1",
                cwd=str(repo),
                team_preset_id=preset.id,
                team_slot_id=planner_slot.id,
                mailbox_status="observed",
            ),
            MailAgentSession(
                member_id=implementer_member.id,
                source="observed",
                provider="codex-cli",
                session_key="tmux:%2",
                tmux_target="implementer:0.0",
                pane_id="%2",
                cwd=str(repo),
                team_preset_id=preset.id,
                team_slot_id=implementer_slot.id,
                mailbox_status="observed",
            ),
        ]
    )
    await db.commit()
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: [
            {
                "provider": "codex-cli",
                "session_name": "implementer",
                "tmux_target": "implementer:0.0",
                "pane_id": "%2",
                "cwd": str(repo),
            },
            {
                "provider": "codex-cli",
                "session_name": "planner",
                "tmux_target": "planner:0.0",
                "pane_id": "%1",
                "cwd": str(repo),
            },
        ],
    )

    plan = await agent_team_service.plan_launch(db, preset.id)

    assert [item.action for item in plan.items] == ["reuse", "reuse"]
    assert [item.matching_session["tmux_target"] for item in plan.items] == [
        "planner:0.0",
        "implementer:0.0",
    ]


@pytest.mark.asyncio
async def test_launch_reuses_distinct_same_repo_sessions(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Same repo team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Planner",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
                AgentTeamSlotCreate(
                    display_name="Implementer",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
            ],
        ),
    )
    repo_member = await agent_mail_service.get_or_create_repo_member(db, str(repo))
    db.add_all(
        [
            MailAgentSession(
                member_id=repo_member.id,
                source="observed",
                provider="codex-cli",
                session_key="tmux:%1",
                tmux_target="planner:0.0",
                pane_id="%1",
                cwd=str(repo),
                mailbox_status="observed",
            ),
            MailAgentSession(
                member_id=repo_member.id,
                source="observed",
                provider="codex-cli",
                session_key="tmux:%2",
                tmux_target="implementer:0.0",
                pane_id="%2",
                cwd=str(repo),
                mailbox_status="observed",
            ),
        ]
    )
    await db.commit()
    discovered_sessions = [
        {
            "provider": "codex-cli",
            "session_name": "planner",
            "tmux_target": "planner:0.0",
            "pane_id": "%1",
            "cwd": str(repo),
            "pid": "101",
        },
        {
            "provider": "codex-cli",
            "session_name": "implementer",
            "tmux_target": "implementer:0.0",
            "pane_id": "%2",
            "cwd": str(repo),
            "pid": "102",
        },
    ]
    monkeypatch.setattr(
        "app.services.agent_team_service.discover_agent_sessions",
        lambda: discovered_sessions,
    )

    plan = await agent_team_service.plan_launch(db, preset.id)
    assert [item.matching_session["session_key"] for item in plan.items] == ["tmux:%1", "tmux:%2"]

    result = await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )
    sessions = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.session_key.in_(["tmux:%1", "tmux:%2"]))
        )
    ).scalars().all()
    sessions_by_key = {session.session_key: session for session in sessions}

    assert [item.status for item in result.items] == ["reused", "reused"]
    assert result.items[0].agent_mail_member_id != result.items[1].agent_mail_member_id
    assert sessions_by_key["tmux:%1"].team_slot_id == preset.slots[0].id
    assert sessions_by_key["tmux:%2"].team_slot_id == preset.slots[1].id
    assert await db.get(MailTeamMember, repo_member.id) is None


@pytest.mark.asyncio
async def test_disabled_same_repo_slot_does_not_consume_reuse_match(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Same repo team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Disabled",
                    provider="codex-cli",
                    repo_path=str(repo),
                    enabled=False,
                ),
                AgentTeamSlotCreate(
                    display_name="Enabled",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
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
        AgentTeamLaunchRequest(include_disabled=True),
    )

    assert [item.action for item in plan.items] == ["skip", "reuse"]
    assert plan.items[1].matching_session["tmux_target"] == "repo:0.0"


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
                    ui_color="green",
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
    assert calls[0][2]["CLAUDE_DECK_TEAM_SLOT_COLOR"] == "green"
    assert "GH_TOKEN" not in calls[0][2]
    assert "GITHUB_TOKEN" not in calls[0][2]


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

    assert calls[0][1].prompt.startswith("Custom team startup prompt.")
    assert "deck_retry_work_item" in calls[0][1].prompt


@pytest.mark.asyncio
async def test_launch_uses_slot_prompt_override(db, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Override prompt team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
                    provider="codex-cli",
                    repo_path=str(repo),
                    bootstrap_prompt="Static team startup prompt.",
                )
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    slot_id = preset.slots[0].id
    calls = []

    def fake_spawn(provider_id, options, *, extra_env=None):
        calls.append((provider_id, options, extra_env))
        return {"session_name": "repo-abcd", "tmux_target": "repo-abcd:0.0"}

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(
            confirm_plan_hash=plan.plan_hash,
            slot_prompt_overrides={slot_id: "Dispatch-specific issue brief."},
        ),
    )

    assert calls[0][1].prompt == "Dispatch-specific issue brief."


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
async def test_deleting_slot_clears_context_when_session_cwd_cannot_resolve(
    db,
    tmp_path,
    monkeypatch,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Cleanup team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="A",
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
            session_key="mcp:a",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        ),
    )

    async def fail_repo_member(_db, _cwd):
        raise FileNotFoundError("missing cwd")

    monkeypatch.setattr(
        "app.services.agent_team_service.agent_mail_service.get_or_create_repo_member",
        fail_repo_member,
    )

    await agent_team_service.delete_slot(db, slot.id)
    await db.refresh(session)

    assert session.team_preset_id is None
    assert session.team_slot_id is None


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


@pytest.mark.asyncio
async def test_launch_writes_a_pane_binding_on_the_spawn_path(db, tmp_path, monkeypatch):
    """Without this row every Deck-launched pane gets bind_pending forever."""
    from sqlalchemy import text

    repo = tmp_path / "binding-spawn-repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Binding team",
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
    assert plan.items[0].action == "spawn"

    def fake_spawn(provider_id, options, *, extra_env=None):
        return {
            "session_name": "repo-abcd",
            "tmux_target": "repo-abcd:0.0",
            "pane_pid": 4242,
        }

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    monkeypatch.setattr(
        "app.services.agent_team_service.read_proc_stat", lambda pid: (1, "120913170")
    )

    result = await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )
    assert result.items[0].pane_pid == 4242

    rows = (
        await db.execute(
            text(
                "SELECT pane_pid, pane_proc_start, slot_id, preset_id, tmux_target "
                "FROM agent_pane_bindings"
            )
        )
    ).all()
    assert rows == [(4242, "120913170", preset.slots[0].id, preset.id, "repo-abcd:0.0")]


@pytest.mark.asyncio
async def test_pane_binding_is_written_before_the_slot_loop_ends(db, tmp_path, monkeypatch):
    """The first row must exist while the second slot is launching."""
    from sqlalchemy import text

    repo = tmp_path / "binding-order-repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Ordering team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Agent one",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
                AgentTeamSlotCreate(
                    display_name="Agent two",
                    provider="codex-cli",
                    repo_path=str(repo),
                ),
            ],
        ),
    )
    plan = await agent_team_service.plan_launch(db, preset.id)
    assert [item.action for item in plan.items] == ["spawn", "spawn"]

    spawn_calls: list[int] = []
    observed: list[list] = []

    def fake_spawn(provider_id, options, *, extra_env=None):
        spawn_calls.append(len(spawn_calls))
        return {
            "session_name": f"repo-abc{len(spawn_calls)}",
            "tmux_target": f"repo-abc{len(spawn_calls)}:0.0",
            "pane_pid": 4240 + len(spawn_calls),
        }

    real_bootstrap = agent_team_service._bootstrap_prompt

    async def spy_bootstrap(db_arg, preset_arg, slot_arg):
        observed.append(
            (await db_arg.execute(text("SELECT pane_pid FROM agent_pane_bindings"))).all()
        )
        return await real_bootstrap(db_arg, preset_arg, slot_arg)

    monkeypatch.setattr("app.services.agent_team_service.spawn_session", fake_spawn)
    monkeypatch.setattr(
        "app.services.agent_team_service.read_proc_stat", lambda pid: (1, "120913170")
    )
    monkeypatch.setattr(agent_team_service, "_bootstrap_prompt", spy_bootstrap)

    await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )

    assert observed[0] == []
    assert observed[1] == [(4241,)]
    final = (await db.execute(text("SELECT pane_pid FROM agent_pane_bindings"))).all()
    assert sorted(final) == [(4241,), (4242,)]


@pytest.mark.asyncio
async def test_launch_writes_a_pane_binding_on_the_reuse_path(db, tmp_path, monkeypatch):
    """Reuse coerces the discovery pid and updates the existing row."""
    from sqlalchemy import text

    repo = tmp_path / "binding-reuse-repo"
    repo.mkdir()
    preset = await agent_team_service.create_preset(
        db,
        AgentTeamPresetCreate(
            name="Reuse team",
            slots=[
                AgentTeamSlotCreate(
                    display_name="Dev agent",
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
                "session_name": "repo-abcd",
                "tmux_target": "repo-abcd:0.0",
                "pid": "4242",
                "provider": "codex-cli",
                "cwd": str(repo),
                "wakeable": True,
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.agent_team_service.read_proc_stat", lambda pid: (1, "120913170")
    )

    plan = await agent_team_service.plan_launch(db, preset.id)
    assert plan.items[0].action == "reuse", plan.items[0].reasons

    await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=plan.plan_hash),
    )
    rows = (
        await db.execute(
            text("SELECT id, pane_pid, typeof(pane_pid), slot_id FROM agent_pane_bindings")
        )
    ).all()
    assert len(rows) == 1
    first_id = rows[0][0]
    assert rows[0][1] == 4242
    assert rows[0][2] == "integer"

    second_plan = await agent_team_service.plan_launch(db, preset.id)
    await agent_team_service.launch(
        db,
        preset.id,
        AgentTeamLaunchRequest(confirm_plan_hash=second_plan.plan_hash),
    )
    second_rows = (
        await db.execute(text("SELECT id, pane_pid FROM agent_pane_bindings"))
    ).all()
    assert second_rows == [(first_id, 4242)]
