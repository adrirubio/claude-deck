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
