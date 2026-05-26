"""Tests for normalized provider API errors."""
from types import SimpleNamespace

import pytest


def test_provider_status_unknown_provider_returns_structured_404():
    from app.api.v1 import providers as providers_api

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.get_provider_status("missing-provider")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "unknown_provider"
    assert exc_info.value.detail["provider"] == "missing-provider"


def test_provider_doctor_unsupported_capability_returns_contract_error():
    from app.api.v1 import providers as providers_api

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.get_provider_doctor("claude-code")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "code": "unsupported_operation",
        "message": "Claude Code does not support doctor diagnostics",
        "provider": "claude-code",
        "operation": "doctor diagnostics",
        "capability": "doctor",
    }


def test_provider_mcp_inventory_wrong_provider_returns_contract_error():
    from app.api.v1 import providers as providers_api

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.get_provider_mcp_inventory("claude-code")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "unsupported_provider_operation"
    assert exc_info.value.detail["provider"] == "claude-code"
    assert exc_info.value.detail["operation"] == "MCP inventory"
    assert exc_info.value.detail["supported_providers"] == ["codex-cli"]


def test_provider_cli_disallowed_command_returns_contract_error(monkeypatch):
    from app.api.v1 import providers as providers_api
    from app.models.schemas import CLIExecuteRequest

    class FakeExecutor:
        binary_path = "/usr/bin/codex"
        provider = SimpleNamespace(display_name="Codex")
        provider_id = "codex-cli"
        ALLOWED_COMMANDS = ["doctor"]

        def validate_command(self, command):
            return command == "doctor"

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.execute_provider_cli(
            "codex-cli",
            CLIExecuteRequest(command="logout", args=[]),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "command_not_allowed"
    assert exc_info.value.detail["provider"] == "codex-cli"
    assert exc_info.value.detail["operation"] == "cli:logout"


def test_provider_cli_missing_binary_returns_contract_error(monkeypatch):
    from app.api.v1 import providers as providers_api
    from app.models.schemas import CLIExecuteRequest

    class FakeExecutor:
        binary_path = None
        provider = SimpleNamespace(display_name="Codex")
        provider_id = "codex-cli"
        ALLOWED_COMMANDS = ["doctor"]

        def validate_command(self, command):
            return command == "doctor"

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.execute_provider_cli(
            "codex-cli",
            CLIExecuteRequest(command="doctor", args=[]),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {
        "code": "provider_binary_missing",
        "message": "Codex binary not found in PATH.",
        "provider": "codex-cli",
        "operation": "cli:doctor",
    }
