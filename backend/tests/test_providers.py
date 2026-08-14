"""Tests for agent provider registry and Codex detection."""
from types import SimpleNamespace
from unittest.mock import patch


def test_provider_registry_contains_initial_providers():
    from app.services.providers import get_provider, get_providers

    provider_ids = {provider.id for provider in get_providers()}

    assert provider_ids == {"claude-code", "codex-cli", "copilot-cli", "opencode-cli"}
    assert get_provider("claude-code").display_name == "Claude Code"
    assert get_provider("codex-cli").binary_name == "codex"
    assert get_provider("copilot-cli").binary_name == "copilot"
    assert get_provider("opencode-cli").binary_name == "opencode"


def test_provider_status_includes_central_capability_matrix():
    from app.services.providers import get_provider

    claude = get_provider("claude-code").get_status()
    codex = get_provider("codex-cli").get_status()

    assert claude["capabilities"]["plugins"] is True
    assert claude["capabilities"]["fork"] is False
    assert claude["capability_matrix"]["plugins"]["state"] == "write_capable"
    assert claude["capability_details"]["plugins"]["state"] == "write_capable"
    assert claude["capability_matrix"]["doctor"]["state"] == "unsupported"
    assert codex["capabilities"]["plugins"] is True
    assert codex["capability_matrix"]["plugins"]["state"] == "write_capable"
    assert codex["capability_details"]["plugins"]["state"] == "write_capable"
    assert codex["capability_matrix"]["mcp"]["state"] == "write_capable"
    assert codex["capability_matrix"]["usage"]["state"] == "unsupported"
    assert codex["capability_matrix"]["doctor"]["state"] == "read_only"
    copilot = get_provider("copilot-cli").get_status()
    assert copilot["capabilities"]["spawn"] is True
    assert copilot["capability_matrix"]["mcp"]["state"] == "write_capable"
    assert copilot["capability_matrix"]["config"]["state"] == "unsupported"
    opencode = get_provider("opencode-cli").get_status()
    assert opencode["capabilities"]["spawn"] is True
    assert opencode["capability_matrix"]["mcp"]["state"] == "write_capable"
    assert opencode["capability_matrix"]["hooks"]["state"] == "write_capable"


def test_provider_capabilities_api_returns_matrix():
    from app.api.v1 import providers as providers_api

    response = providers_api.get_provider_capabilities("codex-cli")

    assert response["provider"] == "codex-cli"
    assert response["capabilities"]["config"] is True
    assert response["capability_matrix"]["config"]["state"] == "write_capable"
    assert response["capability_matrix"]["commands"]["state"] == "unsupported"


def test_provider_list_warns_when_containerized_without_agent_clis(monkeypatch):
    from app.api.v1 import providers as providers_api
    from app.services import runtime_environment

    class FakeProvider:
        id = "claude-code"
        binary_name = "claude"

        def get_status(self):
            return {
                "id": self.id,
                "display_name": "Claude Code",
                "binary_name": self.binary_name,
                "installed": False,
            }

    monkeypatch.setattr(runtime_environment, "is_containerized", lambda: True)
    monkeypatch.setattr(providers_api, "get_providers", lambda: [FakeProvider()])

    response = providers_api.list_providers()

    assert response["environment"]["containerized"] is True
    assert response["environment"]["agent_cli_warning"] == runtime_environment.CONTAINER_AGENT_CLI_WARNING
    assert response["providers"][0]["unavailable_code"] == "container_agent_clis_missing"
    assert response["providers"][0]["unavailable_reason"] == runtime_environment.CONTAINER_AGENT_CLI_WARNING


def test_codex_process_detection_matches_interactive_binary():
    from app.services.providers import get_provider

    provider = get_provider("codex-cli")

    assert provider.is_process_match("codex", "123") is True
    assert provider.is_process_match("/usr/local/bin/codex", "123") is True
    assert provider.is_process_match("codex-exec-server", "123") is False


def test_codex_process_detection_matches_node_wrapper_descendant():
    from app.services.providers import get_provider

    provider = get_provider("codex-cli")

    with patch("app.services.providers.base.subprocess.run") as run:
        run.return_value = SimpleNamespace(stdout="456 /usr/local/bin/codex\n")
        assert provider.is_process_match("node", "123") is True


def test_copilot_process_detection_matches_binary_and_node_wrapper():
    from app.services.providers import get_provider

    provider = get_provider("copilot-cli")

    assert provider.is_process_match("copilot", "123") is True
    assert provider.is_process_match("/usr/local/bin/copilot", "123") is True
    assert provider.is_process_match("copilot-language-server", "123") is False
    with patch("app.services.providers.base.subprocess.run") as run:
        run.return_value = SimpleNamespace(stdout="456 /usr/local/bin/copilot\n")
        assert provider.is_process_match("node", "123") is True


def test_opencode_process_detection_matches_binary_and_wrappers():
    from app.services.providers import get_provider

    provider = get_provider("opencode-cli")

    assert provider.is_process_match("opencode", "123") is True
    assert provider.is_process_match("/usr/local/bin/opencode", "123") is True
    assert provider.is_process_match("opencode-server", "123") is False
    with patch("app.services.providers.base.subprocess.run") as run:
        run.return_value = SimpleNamespace(stdout="456 /usr/local/bin/opencode\n")
        assert provider.is_process_match("bun", "123") is True


def test_argv0_name_tolerates_blank_commands():
    from app.services.providers.base import argv0_name

    assert argv0_name(" ") == ""
    assert argv0_name("\t") == ""
    assert argv0_name("") == ""
    assert argv0_name("  codex  ") == "codex"


def test_discovery_survives_a_blank_pane_command():
    from app.services.agent_bridge.discovery import discover_agent_sessions

    tmux_output = "\n".join(
        [
            "blank:0.0|blank|main|%1|/repo/a|111| ",
            "codexproj:0.0|codexproj|main|%2|/repo/b|222|codex",
        ]
    )

    def fake_run(args, **_kwargs):
        if args[:2] == ["tmux", "list-panes"]:
            return SimpleNamespace(returncode=0, stdout=tmux_output, stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    with patch(
        "app.services.agent_bridge.discovery.subprocess.run", side_effect=fake_run
    ):
        sessions = discover_agent_sessions()

    assert [session["pane_id"] for session in sessions] == ["%2"]


def test_opencode_home_respects_xdg_config_home(monkeypatch, tmp_path):
    from app.services.providers.opencode_cli import get_opencode_home

    monkeypatch.delenv("OPENCODE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert get_opencode_home() == tmp_path / "xdg" / "opencode"

    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "custom"))

    assert get_opencode_home() == tmp_path / "custom"
