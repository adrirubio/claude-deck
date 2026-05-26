"""Tests for agent provider registry and Codex detection."""
from types import SimpleNamespace
from unittest.mock import patch


def test_provider_registry_contains_initial_providers():
    from app.services.providers import get_provider, get_providers

    provider_ids = {provider.id for provider in get_providers()}

    assert provider_ids == {"claude-code", "codex-cli"}
    assert get_provider("claude-code").display_name == "Claude Code"
    assert get_provider("codex-cli").binary_name == "codex"


def test_provider_status_includes_capability_details():
    from app.services.providers import get_provider

    claude_status = get_provider("claude-code").get_status()
    codex_status = get_provider("codex-cli").get_status()

    assert claude_status["capabilities"]["spawn"] is True
    assert claude_status["capability_details"]["spawn"]["state"] == "write_capable"
    assert claude_status["capability_details"]["fork"]["state"] == "unsupported"

    assert codex_status["capabilities"]["plugins"] is True
    assert codex_status["capability_details"]["plugins"]["state"] == "read_only"
    assert codex_status["capability_details"]["doctor"]["state"] == "read_only"
    assert codex_status["capability_details"]["usage"]["state"] == "unsupported"


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
