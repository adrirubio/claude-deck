"""Tests for mixed-provider tmux discovery."""
from types import SimpleNamespace
from unittest.mock import patch


def test_discover_agent_sessions_returns_mixed_providers():
    from app.services.agent_bridge.discovery import discover_agent_sessions

    tmux_output = "\n".join([
        "claudeproj:0.0|claudeproj|main|%1|/repo/a|111|claude",
        "codexproj:0.0|codexproj|main|%2|/repo/b|222|codex",
        "copilotproj:0.0|copilotproj|main|%3|/repo/c|333|copilot",
        "opencodeproj:0.0|opencodeproj|main|%4|/repo/d|444|opencode",
        "shell:0.0|shell|main|%5|/repo/e|555|bash",
    ])

    with patch("app.services.agent_bridge.discovery.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout=tmux_output, stderr="")
        sessions = discover_agent_sessions()

    assert [session["provider"] for session in sessions] == [
        "claude-code",
        "codex-cli",
        "copilot-cli",
        "opencode-cli",
    ]
    assert sessions[0]["provider_display_name"] == "Claude Code"
    assert sessions[1]["provider_display_name"] == "Codex"
    assert sessions[2]["provider_display_name"] == "GitHub Copilot CLI"
    assert sessions[3]["provider_display_name"] == "OpenCode CLI"


def test_discover_agent_sessions_can_filter_provider():
    from app.services.agent_bridge.discovery import discover_agent_sessions

    tmux_output = "\n".join([
        "claudeproj:0.0|claudeproj|main|%1|/repo/a|111|claude",
        "codexproj:0.0|codexproj|main|%2|/repo/b|222|codex",
        "copilotproj:0.0|copilotproj|main|%3|/repo/c|333|copilot",
        "opencodeproj:0.0|opencodeproj|main|%4|/repo/d|444|opencode",
    ])

    with patch("app.services.agent_bridge.discovery.subprocess.run") as run:
        run.return_value = SimpleNamespace(returncode=0, stdout=tmux_output, stderr="")
        sessions = discover_agent_sessions("codex-cli")

    assert len(sessions) == 1
    assert sessions[0]["provider"] == "codex-cli"


def test_discover_agent_sessions_includes_team_environment():
    from app.services.agent_bridge.discovery import discover_agent_sessions

    tmux_output = "snazzyemail:0.0|snazzyemail|main|%1|/repo/a|111|codex"
    env_output = "\n".join(
        [
            "CLAUDE_DECK_TEAM_PRESET_ID=10",
            "CLAUDE_DECK_TEAM_PRESET_NAME=SnazzyEmail",
            "CLAUDE_DECK_TEAM_SLOT_ID=20",
            "CLAUDE_DECK_TEAM_SLOT_NAME=Lead Developer",
            "CLAUDE_DECK_TEAM_SLOT_ROLE=lead developer",
        ]
    )

    def fake_run(args, **_kwargs):
        if args[:2] == ["tmux", "list-panes"]:
            return SimpleNamespace(returncode=0, stdout=tmux_output, stderr="")
        if args[:2] == ["tmux", "show-environment"]:
            return SimpleNamespace(returncode=0, stdout=env_output, stderr="")
        raise AssertionError(args)

    with patch("app.services.agent_bridge.discovery.subprocess.run", side_effect=fake_run):
        sessions = discover_agent_sessions("codex-cli")

    assert sessions == [
        {
            "provider": "codex-cli",
            "provider_display_name": "Codex",
            "tmux_target": "snazzyemail:0.0",
            "session_name": "snazzyemail",
            "window_name": "main",
            "pane_id": "%1",
            "cwd": "/repo/a",
            "pid": "111",
            "status": "active",
            "team_preset_id": 10,
            "team_preset_name": "SnazzyEmail",
            "team_slot_id": 20,
            "team_slot_name": "Lead Developer",
            "team_slot_role": "lead developer",
        }
    ]
