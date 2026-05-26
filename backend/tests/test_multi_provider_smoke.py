"""Smoke tests for the multi-provider API surface."""
import pytest


def test_provider_registry_smoke_exposes_claude_and_codex_statuses():
    from app.api.v1 import providers as providers_api

    response = providers_api.list_providers()

    provider_ids = {provider["id"] for provider in response["providers"]}
    assert response["count"] == 2
    assert provider_ids == {"claude-code", "codex-cli"}

    claude_status = providers_api.get_provider_status("claude-code")
    codex_status = providers_api.get_provider_status("codex-cli")

    assert claude_status["capabilities"]["sessions"] is True
    assert claude_status["capabilities"]["usage"] is True
    assert codex_status["capabilities"]["sessions"] is True
    assert codex_status["capabilities"]["doctor"] is True
    assert codex_status["capabilities"]["usage"] is False


def test_agent_bridge_session_filter_smoke(monkeypatch):
    from app.api.v1.agent_bridge import router as agent_bridge_api

    calls = []

    def fake_discover(provider=None):
        calls.append(provider)
        return [
            {
                "provider": provider or "claude-code",
                "session_name": "session-1",
                "tmux_target": "session-1:0.0",
            }
        ]

    monkeypatch.setattr(agent_bridge_api, "discover_agent_sessions", fake_discover)

    all_response = agent_bridge_api.list_sessions(provider=None)
    codex_response = agent_bridge_api.list_sessions(provider="codex-cli")

    assert calls == [None, "codex-cli"]
    assert all_response["count"] == 1
    assert codex_response["sessions"][0]["provider"] == "codex-cli"


def test_agent_bridge_spawn_smoke_passes_codex_options(monkeypatch, tmp_path):
    from app.api.v1.agent_bridge import router as agent_bridge_api

    captured = {}

    def fake_spawn(provider_id, options):
        captured["provider_id"] = provider_id
        captured["options"] = options
        return {
            "provider": provider_id,
            "provider_display_name": "Codex CLI",
            "tmux_target": "codex-smoke:0.0",
            "session_name": "codex-smoke",
        }

    monkeypatch.setattr(agent_bridge_api, "spawn_session", fake_spawn)

    response = agent_bridge_api.spawn_session_endpoint(
        agent_bridge_api.SpawnRequest(
            provider="codex-cli",
            directory=str(tmp_path),
            mode="plain",
            profile="default",
            sandbox="workspace-write",
            approval_policy="on-request",
            search=True,
            no_alt_screen=True,
        )
    )

    assert response["provider"] == "codex-cli"
    assert captured["provider_id"] == "codex-cli"
    assert captured["options"].profile == "default"
    assert captured["options"].sandbox == "workspace-write"
    assert captured["options"].approval_policy == "on-request"
    assert captured["options"].search is True
    assert captured["options"].no_alt_screen is True


def test_agent_bridge_spawn_unknown_provider_smoke(tmp_path):
    from app.api.v1.agent_bridge import router as agent_bridge_api

    with pytest.raises(agent_bridge_api.HTTPException) as exc_info:
        agent_bridge_api.spawn_session_endpoint(
            agent_bridge_api.SpawnRequest(
                provider="unknown-provider",
                directory=str(tmp_path),
            )
        )

    assert exc_info.value.status_code == 400
    assert "Unknown provider" in exc_info.value.detail


def test_provider_specific_inventory_smoke_rejects_wrong_provider():
    from app.api.v1 import providers as providers_api

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.get_provider_mcp_inventory("claude-code")

    assert exc_info.value.status_code == 400
    assert "Codex-only" in exc_info.value.detail
