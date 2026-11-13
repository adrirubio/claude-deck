"""Tests for provider-aware tmux spawning."""
import json
import shlex
from types import SimpleNamespace

import pytest


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
    assert calls[0][:10] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "repo-abcd",
        "-c",
        str(tmp_path),
        "-P",
        "-F",
        "#{pane_pid}",
    ]
    assert "--worktree repo-abcd" in calls[0][-1]
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
    assert calls[0][:10] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "claude-deck-abcd",
        "-c",
        str(project_dir),
        "-P",
        "-F",
        "#{pane_pid}",
    ]
    assert "--resume session-123" in calls[0][-1]


def test_claude_resume_requires_a_transcript_for_directory_inference(monkeypatch, tmp_path):
    from app.services.cc_bridge import spawn as claude_spawn

    monkeypatch.setattr(claude_spawn.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(ValueError, match="provide the directory path explicitly"):
        claude_spawn._resolve_project_directory("-tmp", "session-123")


@pytest.mark.parametrize(
    ("project_folder", "session_id"),
    [
        ("../outside", "session-123"),
        ("-tmp-claude-deck", "../outside"),
        ("-tmp-claude-deck", "session/other"),
    ],
)
def test_claude_resume_rejects_path_segments(monkeypatch, tmp_path, project_folder, session_id):
    from app.services.cc_bridge import spawn as claude_spawn

    monkeypatch.setattr(claude_spawn.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(ValueError):
        claude_spawn._resolve_project_directory(project_folder, session_id)


def test_claude_resume_rejects_symlink_escapes(monkeypatch, tmp_path):
    from app.services.cc_bridge import spawn as claude_spawn

    projects_root = tmp_path / ".claude" / "projects"
    projects_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (projects_root / "-escaped-project").symlink_to(outside, target_is_directory=True)
    (projects_root / "-safe-project").mkdir()
    (outside / "session-123.jsonl").write_text(json.dumps({"cwd": str(outside)}))
    (projects_root / "-safe-project" / "session-123.jsonl").symlink_to(
        outside / "session-123.jsonl"
    )

    monkeypatch.setattr(claude_spawn.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(ValueError, match="Invalid project folder"):
        claude_spawn._resolve_project_directory("-escaped-project", "session-123")
    with pytest.raises(ValueError, match="Invalid Claude transcript path"):
        claude_spawn._resolve_project_directory("-safe-project", "session-123")


def test_legacy_claude_bridge_uses_provider_spawn_and_kill(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn as provider_spawn
    from app.services.cc_bridge import spawn as claude_spawn

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="4321\n", stderr="")

    monkeypatch.setattr(provider_spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(provider_spawn.subprocess, "run", fake_run)
    provider_spawn.get_spawned_sessions().clear()

    result = claude_spawn.spawn_session(
        directory=str(tmp_path), mode="worktree", worktree_name="feature-x"
    )

    assert result == {"tmux_target": "repo-abcd:0.0", "session_name": "repo-abcd"}
    assert calls[0][:10] == [
        "tmux", "new-session", "-d", "-s", "repo-abcd", "-c", str(tmp_path), "-P", "-F", "#{pane_pid}"
    ]
    assert "--worktree feature-x" in calls[0][-1]
    assert claude_spawn.get_spawned_sessions()["repo-abcd"]["worktree_name"] == "feature-x"

    assert claude_spawn.kill_session("repo-abcd", cleanup_worktree=True) == {"killed": True}
    assert calls[1] == ["tmux", "kill-session", "-t", "repo-abcd"]
    assert calls[2] == [
        "git", "-C", str(tmp_path), "worktree", "remove", "feature-x", "--force"
    ]
    assert "repo-abcd" not in provider_spawn.get_spawned_sessions()


def test_legacy_claude_bridge_rejects_traversal_in_directory(tmp_path):
    from app.services.cc_bridge import spawn as claude_spawn

    with pytest.raises(ValueError, match="traversal"):
        claude_spawn.spawn_session(directory=str(tmp_path / ".."))


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


def _opencode_spawn_fixture(monkeypatch):
    from app.services import opencode_version
    from app.services.agent_bridge import spawn

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="4242\n", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    trusted = opencode_version.BinaryIdentity("/opt/trusted/bin/opencode", 1, 2, 3, 4)
    monkeypatch.setattr(opencode_version, "opencode_version_gate", lambda: opencode_version.VersionGate("ok", "2.2.7", None, trusted))
    spawn.get_spawned_sessions().clear()
    return spawn, calls


def _tmux_env(args):
    env = {}
    for flag, value in zip(args, args[1:]):
        if flag == "-e":
            key, _, val = value.partition("=")
            env[key] = val
    return env


def test_opencode_spawn_builds_the_v2_member_command_and_env(monkeypatch, tmp_path):
    import json

    from app.services.providers.base import SpawnCommandOptions

    spawn, calls = _opencode_spawn_fixture(monkeypatch)
    result = spawn.spawn_session(
        "opencode-cli",
        SpawnCommandOptions(
            directory=str(tmp_path),
            mode="resume",
            session_id="ses_e2e111c0dffe5XAqhRWBFFBZDf",
            model="anthropic/claude-sonnet-4.6#high",
            agent="planner",
            skip_permissions=True,
            prompt="Review the plan",
        ),
        extra_env={"SYNTH_CITY_TEAM_SLOT_ID": "7"},
    )

    # The exact v2 contract (#729 spec): the probed binary, standalone, exact session, --auto.
    assert shlex.split(calls[0][-1]) == [
        "/opt/trusted/bin/opencode", str(tmp_path), "--standalone",
        "--session", "ses_e2e111c0dffe5XAqhRWBFFBZDf", "--auto", "--prompt", "Review the plan",
    ]
    env = _tmux_env(calls[0])
    assert env["SYNTH_CITY_TEAM_SLOT_ID"] == "7"
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"]) == {
        "model": "anthropic/claude-sonnet-4.6#high",
        "default_agent": "planner",
        "update": "disable",
        "enabled_providers": ["anthropic"],
        "permissions": [{"action": "question", "resource": "*", "effect": "deny"}],
    }
    assert result["session_id"] == "ses_e2e111c0dffe5XAqhRWBFFBZDf"


def test_opencode_plain_spawn_chooses_an_exact_session_id(monkeypatch, tmp_path):
    import json
    import re

    from app.services.providers.base import SpawnCommandOptions

    spawn, calls = _opencode_spawn_fixture(monkeypatch)
    result = spawn.spawn_session("opencode-cli", SpawnCommandOptions(directory=str(tmp_path)))

    parts = shlex.split(calls[0][-1])
    assert parts[:3] == ["/opt/trusted/bin/opencode", str(tmp_path), "--standalone"]
    assert parts[3] == "--session" and re.fullmatch(r"ses_[0-9A-Za-z]{26}", parts[4])
    assert len(parts) == 5
    assert result["session_id"] == parts[4]
    assert json.loads(_tmux_env(calls[0])["OPENCODE_CONFIG_CONTENT"]) == {
        "update": "disable", "disabled_providers": ["opencode"],
        "permissions": [{"action": "question", "resource": "*", "effect": "deny"}],
    }


@pytest.mark.parametrize("options,code", [
    ({"reasoning_effort": "high"}, "reasoning_effort_unsupported"),
    ({"mode": "resume", "use_last": True}, "opencode_continue_unsupported"),
    ({"use_last": True}, "opencode_continue_unsupported"),
])
def test_opencode_spawn_refuses_unsupported_options_with_a_block_code(tmp_path, options, code):
    from app.services.providers import get_provider
    from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions

    with pytest.raises(ProviderLaunchError) as raised:
        get_provider("opencode-cli").build_spawn_command(SpawnCommandOptions(directory=str(tmp_path), **options))
    assert raised.value.block_code == code


@pytest.mark.parametrize("options,message", [
    ({"dangerously_bypass_approvals_and_sandbox": True}, "does not support permission bypass"),
    ({"mode": "resume"}, "session_id is required"),
    ({"mode": "resume", "session_id": "0b5b3c1e-4c1d-4b6f-9f0e-0d4d6d1f2a3b"}, "must start with ses"),
    ({"session_id": "deck-slot-29"}, "must start with ses"),
    ({"mode": "fork", "session_id": "ses_abc"}, "Unsupported OpenCode CLI mode"),
    ({"model": "claude-sonnet-4.6"}, "provider/model"),
    ({"agent": "two words"}, "agent"),
    ({"platform": "bedrock", "model": "anthropic/claude-sonnet-4.6"}, "amazon-bedrock/"),
    ({"platform": "bedrock"}, "amazon-bedrock/"),
])
def test_opencode_spawn_rejects_invalid_options(tmp_path, options, message):
    from app.services.providers import get_provider
    from app.services.providers.base import SpawnCommandOptions

    with pytest.raises(ValueError, match=message):
        get_provider("opencode-cli").build_spawn_command(SpawnCommandOptions(directory=str(tmp_path), **options))


def test_opencode_bedrock_member_allows_only_the_bedrock_provider(tmp_path):
    import json

    from app.services.providers import get_provider
    from app.services.providers.base import SpawnCommandOptions

    options = SpawnCommandOptions(
        directory=str(tmp_path), platform="bedrock", aws_region="us-east-1",
        model="amazon-bedrock/anthropic.claude-sonnet-4-6-v1:0", session_id="ses_abc",
    )
    provider = get_provider("opencode-cli")
    assert provider.build_spawn_command(options) == ["opencode", str(tmp_path), "--standalone", "--session", "ses_abc"]
    assert json.loads(provider.build_spawn_env(options)["OPENCODE_CONFIG_CONTENT"])["enabled_providers"] == ["amazon-bedrock"]


def test_other_providers_add_no_spawn_env(tmp_path):
    from app.services.providers import get_provider
    from app.services.providers.base import SpawnCommandOptions

    for provider_id in ("claude-code", "codex-cli", "copilot-cli", "muse-cli", "pi-cli"):
        assert get_provider(provider_id).build_spawn_env(SpawnCommandOptions(directory=str(tmp_path))) == {}


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
    assert argv[:10] == [
        "tmux",
        "new-session",
        "-d",
        "-s",
        "repo-abcd",
        "-c",
        str(tmp_path),
        "-P",
        "-F",
        "#{pane_pid}",
    ]
    assert len(argv) == 11
    assert spawn.get_spawned_sessions()["repo-abcd"]["platform"] == "anthropic"


def test_spawn_session_returns_the_pane_pid(monkeypatch, tmp_path):
    """The binding writer keys on this; a None pid means the pane never binds."""
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    def fake_run(args, capture_output=True, text=True, timeout=10):
        return SimpleNamespace(returncode=0, stdout="49769\n", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
    )
    assert result["pane_pid"] == 49769


def test_spawn_session_pane_pid_is_none_when_tmux_prints_nothing(monkeypatch, tmp_path):
    """Every other test stubs an empty stdout, which must not raise."""
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    def fake_run(args, capture_output=True, text=True, timeout=10):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    spawn.get_spawned_sessions().clear()

    result = spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
    )
    assert result["pane_pid"] is None


def test_spawn_session_accepts_controlled_extra_env(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    monkeypatch.setattr(spawn, "prepare_workspace_trust", lambda *args: False)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "codex-cli",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
        extra_env={"SYNTH_CITY_TEAM_SLOT_ID": "7"},
    )

    assert "SYNTH_CITY_TEAM_SLOT_ID=7" in calls[0]


def test_claude_spawn_session_accepts_controlled_extra_env(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions

    calls = []

    def fake_run(args, capture_output=True, text=True, timeout=10):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spawn, "_session_name_for", lambda directory: "repo-abcd")
    monkeypatch.setattr(spawn.subprocess, "run", fake_run)
    monkeypatch.setattr(spawn, "prepare_workspace_trust", lambda *args: False)
    spawn.get_spawned_sessions().clear()

    spawn.spawn_session(
        "claude-code",
        SpawnCommandOptions(directory=str(tmp_path), mode="plain"),
        extra_env={"SYNTH_CITY_TEAM_SLOT_ID": "7"},
    )

    assert "SYNTH_CITY_TEAM_SLOT_ID=7" in calls[0]


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


def test_team_trust_is_prepared_before_tmux_spawn(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions
    calls = []
    def trust(provider, directory):
        calls.append(("trust", provider, directory))
        return True
    def run(args, **kwargs):
        calls.append(("spawn", args))
        return SimpleNamespace(returncode=0, stdout="123\n", stderr="")
    monkeypatch.setattr(spawn, "prepare_workspace_trust", trust)
    monkeypatch.setattr(spawn.subprocess, "run", run)
    result = spawn.spawn_session("claude-code", SpawnCommandOptions(directory=str(tmp_path)),
                                 extra_env={"SYNTH_CITY_TEAM_SLOT_ID": "7"})
    assert calls[0] == ("trust", "claude-code", str(tmp_path))
    assert calls[1][1][:2] == ["tmux", "new-session"]
    assert result["workspace_trust_changed"] is True


def test_trust_refusal_stops_team_spawn(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions
    calls = []
    def trust(*args):
        raise ValueError("Workspace trust could not be prepared")
    monkeypatch.setattr(spawn, "prepare_workspace_trust", trust)
    monkeypatch.setattr(spawn.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="Workspace trust"):
        spawn.spawn_session("codex-cli", SpawnCommandOptions(directory=str(tmp_path)),
                            extra_env={"SYNTH_CITY_TEAM_SLOT_ID": "7"})
    assert calls == []


def test_non_team_spawn_does_not_change_workspace_trust(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions
    monkeypatch.setattr(spawn, "prepare_workspace_trust", lambda *args: pytest.fail("non-team trust mutation"))
    monkeypatch.setattr(spawn.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout="123\n", stderr=""))
    result = spawn.spawn_session("codex-cli", SpawnCommandOptions(directory=str(tmp_path)))
    assert result["workspace_trust_changed"] is False


def test_failed_spawn_reports_completed_trust_change(monkeypatch, tmp_path):
    from app.services.agent_bridge import spawn
    from app.services.providers.base import SpawnCommandOptions
    monkeypatch.setattr(spawn, "prepare_workspace_trust", lambda *args: True)
    monkeypatch.setattr(spawn.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout="", stderr="fixture failure"))
    with pytest.raises(ValueError) as error:
        spawn.spawn_session("codex-cli", SpawnCommandOptions(directory=str(tmp_path)),
                            extra_env={"SYNTH_CITY_TEAM_SLOT_ID": "7"})
    assert error.value.workspace_trust_changed is True


@pytest.mark.parametrize("state", ["unsupported", "unknown"])
def test_opencode_spawn_refuses_below_2_before_tmux(monkeypatch, tmp_path, state):
    from app.services import opencode_version
    from app.services.agent_bridge import spawn
    from app.services.providers.base import ProviderLaunchError, SpawnCommandOptions

    calls = []
    monkeypatch.setattr(spawn.subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(
        opencode_version,
        "opencode_version_gate",
        lambda: opencode_version.VersionGate(state, "1.17.11" if state == "unsupported" else None, "fixture"),
    )
    with pytest.raises(ProviderLaunchError) as raised:
        spawn.spawn_session("opencode-cli", SpawnCommandOptions(directory=str(tmp_path)))
    assert raised.value.block_code == opencode_version.BLOCK_CODE
    assert opencode_version.REASON_REQUIRED in str(raised.value)
    assert calls == []  # no tmux command ran


def test_bridge_new_session_returns_the_opencode_block_code(monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app.api.v1.agent_bridge import router
    from app.services import opencode_version
    from app.services.providers.base import ProviderLaunchError

    def refused(*_args, **_kwargs):
        raise ProviderLaunchError(f"{opencode_version.BLOCK_CODE}: {opencode_version.REASON_REQUIRED}", opencode_version.BLOCK_CODE)

    monkeypatch.setattr(router, "spawn_session", refused)
    with pytest.raises(HTTPException) as raised:
        router.spawn_session_endpoint(router.SpawnRequest(provider="opencode-cli", directory=str(tmp_path)), principal=None)
    assert raised.value.status_code == 400
    assert raised.value.detail["block_code"] == opencode_version.BLOCK_CODE


def test_bridge_new_session_returns_the_opencode_continue_block_code(tmp_path):
    from fastapi import HTTPException

    from app.api.v1.agent_bridge import router

    with pytest.raises(HTTPException) as raised:
        router.spawn_session_endpoint(
            router.SpawnRequest(provider="opencode-cli", directory=str(tmp_path), mode="resume", use_last=True),
            principal=None,
        )
    assert raised.value.status_code == 400
    assert raised.value.detail["block_code"] == "opencode_continue_unsupported"
