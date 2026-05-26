"""Tests for agent provider registry and Codex detection."""
from types import SimpleNamespace
from unittest.mock import patch


def test_provider_registry_contains_initial_providers():
    from app.services.providers import get_provider, get_providers

    provider_ids = {provider.id for provider in get_providers()}

    assert provider_ids == {"claude-code", "codex-cli"}
    assert get_provider("claude-code").display_name == "Claude Code"
    assert get_provider("codex-cli").binary_name == "codex"


def test_provider_status_includes_central_capability_matrix():
    from app.services.providers import get_provider

    claude = get_provider("claude-code").get_status()
    codex = get_provider("codex-cli").get_status()

    assert claude["capabilities"]["plugins"] is True
    assert claude["capabilities"]["fork"] is False
    assert claude["capability_matrix"]["plugins"]["state"] == "write_capable"
    assert claude["capability_matrix"]["doctor"]["state"] == "unsupported"
    assert codex["capabilities"]["plugins"] is True
    assert codex["capability_matrix"]["plugins"]["state"] == "read_only"
    assert codex["capability_matrix"]["mcp"]["state"] == "write_capable"
    assert codex["capability_matrix"]["usage"]["state"] == "unsupported"
    assert codex["capability_matrix"]["doctor"]["state"] == "read_only"


def test_provider_capabilities_api_returns_matrix():
    from app.api.v1 import providers as providers_api

    response = providers_api.get_provider_capabilities("codex-cli")

    assert response["provider"] == "codex-cli"
    assert response["capabilities"]["config"] is True
    assert response["capability_matrix"]["config"]["state"] == "write_capable"
    assert response["capability_matrix"]["commands"]["state"] == "unsupported"


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
