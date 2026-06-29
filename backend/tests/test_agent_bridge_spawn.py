"""Tests for provider-aware tmux spawning."""
import json
import shlex
from types import SimpleNamespace


def test_claude_worktree_uses_generated_session_name_when_blank(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="worktree"),
    )

    assert result["session_name"] == "repo-abcd"
    assert calls[0][:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    assert "--worktree repo-abcd" in calls[0][7]
    assert spawn.get_spawned_sessions()["repo-abcd"]["worktree_name"] == "repo-abcd"


def test_claude_resume_resolves_directory_from_transcript_cwd(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.cc_bridge import spawn as claude_spawn
    from app.services.providers.base import SpawnCommandOptions

    project_dir = tmp_path / "claude-deck"
    project_dir.mkdir()
    project_folder = "-tmp-claude-deck"
    session_id = "session-123"
    transcript_dir = tmp_path / ".claude" / "projects" / project_folder
    transcript_dir.mkdir(parents=True)
    transcript = transcript_dir / f"{session_id}.jsonl"
    transcript.write_text(json.dumps({"cwd": str(project_dir)}) + "\n", encoding="utf-8")

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(claude_spawn.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "claude-deck-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(
            directory="",
            mode="resume",
            session_id=session_id,
            project_folder=project_folder,
        ),
    )

    assert result["session_name"] == "claude-deck-abcd"
    assert calls[0][:7] == ["tmux", "new-session", "-d", "-s", "claude-deck-abcd", "-c", str(project_dir)]
    assert "--resume session-123" in calls[0][7]


def test_bedrock_platform_injects_env_flags(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="plain",
            platform="bedrock",
            aws_region="us-east-1",
            aws_profile="bedrock-prod",
        ),
    )

    argv = calls[0]
    # Fixed prefix stays identical to the no-env command.
    assert argv[:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    # Env flags are injected as -e KEY=VALUE pairs before the shell command.
    assert "-e" in argv
    assert "CLAUDE_CODE_USE_BEDROCK=1" in argv
    assert "AWS_REGION=us-east-1" in argv
    assert "AWS_PROFILE=bedrock-prod" in argv
    assert spawn.get_spawned_sessions()["repo-abcd"]["platform"] == "bedrock"


def test_codex_bedrock_platform_sets_config_override_and_aws_env(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "codex-cli",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="plain",
            platform="bedrock",
            aws_region="us-east-2",
            aws_profile="codex-bedrock",
            bedrock_model="openai.gpt-5.5",
        ),
    )

    argv = calls[0]
    assert argv[:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    assert "AWS_REGION=us-east-2" in argv
    assert "AWS_PROFILE=codex-bedrock" in argv
    assert "CLAUDE_CODE_USE_BEDROCK=1" not in argv
    assert "ANTHROPIC_MODEL=openai.gpt-5.5" not in argv

    command_parts = shlex.split(argv[-1])
    assert command_parts[:3] == ["codex", "--cd", str(tmp_path)]
    assert command_parts[command_parts.index("--config") + 1] == 'model_provider="amazon-bedrock"'
    assert command_parts[command_parts.index("--model") + 1] == "openai.gpt-5.5"
    assert spawn.get_spawned_sessions()["repo-abcd"]["platform"] == "bedrock"


def test_codex_spawn_sets_reasoning_effort(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "codex-cli",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="plain",
            reasoning_effort="xhigh",
        ),
    )

    command_parts = shlex.split(calls[0][-1])
    config_values = [
        command_parts[index + 1]
        for index, part in enumerate(command_parts)
        if part == "--config"
    ]
    assert 'model_reasoning_effort="xhigh"' in config_values


def test_codex_spawn_rejects_invalid_reasoning_effort(tmp_path):
    from app.services.providers import get_provider
    from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions

    provider = get_provider("codex-cli")

    try:
        provider.build_spawn_command(
            SpawnCommandOptions(directory=str(tmp_path), reasoning_effort="minimal")
        )
    except ProviderLaunchError as exc:
        assert exc.block_code == "invalid_reasoning_effort"
    else:
        raise AssertionError("expected invalid Codex reasoning effort to be rejected")


def test_copilot_spawn_builds_cli_flags(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "copilot-cli",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="resume",
            use_last=True,
            model="claude-sonnet-4.6",
            agent="planner",
            context_tier="long_context",
            reasoning_effort="high",
            plan=True,
            remote=True,
            allow_all=True,
            no_ask_user=True,
            prompt="Review the plan",
        ),
    )

    command_parts = shlex.split(calls[0][-1])
    assert command_parts[:3] == ["copilot", "-C", str(tmp_path)]
    assert "--continue" in command_parts
    assert command_parts[command_parts.index("--model") + 1] == "claude-sonnet-4.6"
    assert command_parts[command_parts.index("--agent") + 1] == "planner"
    assert command_parts[command_parts.index("--context") + 1] == "long_context"
    assert command_parts[command_parts.index("--effort") + 1] == "high"
    assert "--plan" in command_parts
    assert "--remote" in command_parts
    assert "--allow-all" in command_parts
    assert "--no-ask-user" in command_parts
    assert command_parts[command_parts.index("-i") + 1] == "Review the plan"


def test_opencode_spawn_builds_cli_flags(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "opencode-cli",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="resume",
            use_last=True,
            model="anthropic/claude-sonnet-4.6",
            agent="planner",
            prompt="Review the plan",
        ),
    )

    command_parts = shlex.split(calls[0][-1])
    assert command_parts[:2] == ["opencode", str(tmp_path)]
    assert "--continue" in command_parts
    assert command_parts[command_parts.index("--model") + 1] == "anthropic/claude-sonnet-4.6"
    assert command_parts[command_parts.index("--agent") + 1] == "planner"
    assert command_parts[command_parts.index("--prompt") + 1] == "Review the plan"
    assert "--variant" not in command_parts


def test_opencode_spawn_rejects_unsupported_tui_flags(tmp_path):
    from app.services.providers import get_provider
    from app.services.providers.base import SpawnCommandOptions

    provider = get_provider("opencode-cli")

    try:
        provider.build_spawn_command(
            SpawnCommandOptions(directory=str(tmp_path), reasoning_effort="high")
        )
    except ValueError as exc:
        assert "does not support reasoning_effort" in str(exc)
        assert getattr(exc, "block_code", None) == "reasoning_effort_unsupported"
    else:
        raise AssertionError("expected OpenCode variant launch to be rejected")

    try:
        provider.build_spawn_command(
            SpawnCommandOptions(directory=str(tmp_path), dangerously_bypass_approvals_and_sandbox=True)
        )
    except ValueError as exc:
        assert "does not support permission bypass" in str(exc)
    else:
        raise AssertionError("expected OpenCode permission bypass launch to be rejected")


def test_anthropic_platform_adds_no_env_flags(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
    )

    argv = calls[0]
    assert "-e" not in argv
    assert argv[:7] == ["tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path)]
    assert len(argv) == 8
    assert spawn.get_spawned_sessions()["repo-abcd"]["platform"] == "anthropic"


def test_spawn_session_accepts_controlled_extra_env(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "codex-cli",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
        extra_env={"CLAUDE_DECK_TEAM_SLOT_ID": "7"},
    )

    assert "CLAUDE_DECK_TEAM_SLOT_ID=7" in calls[0]


def test_claude_spawn_session_accepts_controlled_extra_env(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
        extra_env={"CLAUDE_DECK_TEAM_SLOT_ID": "7"},
    )

    assert "CLAUDE_DECK_TEAM_SLOT_ID=7" in calls[0]


def test_spawn_session_rejects_invalid_extra_env_names(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")

    try:
        spawn.spawn_session(
            "codex-cli",
            SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
            extra_env={"bad-name": "7"},
        )
    except ValueError as exc:
        assert "Invalid environment variable name" in str(exc)
    else:
        raise AssertionError("Expected invalid env name to be rejected")
