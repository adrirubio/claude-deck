"""Tests for read-only Codex MCP and plugin inventory endpoints."""
from types import SimpleNamespace

import pytest


def test_codex_mcp_inventory_parses_json_and_redacts(monkeypatch):
    from app.api.v1 import providers as providers_api

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            assert command == "mcp"
            assert args == ["list", "--json"]
            return SimpleNamespace(
                stdout='{"servers":{"local":{"command":"node","authToken":"abc123"}}}',
                stderr="",
                exit_code=0,
            )

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.get_provider_mcp_inventory("codex-cli")

    assert response["exit_code"] == 0
    assert response["parse_error"] is None
    assert response["servers"]["servers"]["local"]["authToken"] == "[redacted]"
    assert "abc123" not in response["raw_stdout"]
    assert '"authToken": "[redacted]"' in response["raw_stdout"]


def test_codex_mcp_inventory_surfaces_errors(monkeypatch):
    from app.api.v1 import providers as providers_api

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            return SimpleNamespace(
                stdout="{not-json",
                stderr="auth_token=secret-value failed",
                exit_code=2,
            )

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.get_provider_mcp_inventory("codex-cli")

    assert response["exit_code"] == 2
    assert response["servers"] is None
    assert response["parse_error"]
    assert "auth_token=[redacted]" in response["stderr"]


def test_codex_plugin_inventory_returns_text_and_best_effort_rows(monkeypatch):
    from app.api.v1 import providers as providers_api

    header = f"{'PLUGIN':<28}{'STATUS':<16}{'VERSION':<12}PATH"
    blank_version_row = (
        f"{'linear@openai-curated':<28}"
        f"{'not installed':<16}"
        f"{'':<12}"
        "/home/user/.codex/plugins/linear"
    )
    version_row = (
        f"{'review@openai-curated':<28}"
        f"{'installed':<16}"
        f"{'0.4.0':<12}"
        "/tmp/review plugin"
    )

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            assert command == "plugin"
            assert args == ["list"]
            return SimpleNamespace(
                stdout=(
                    "Marketplace `openai-curated`\n"
                    "/home/user/.codex/marketplaces/openai-curated/marketplace.json\n"
                    "\n"
                    f"{header}\n"
                    f"{blank_version_row}\n"
                    f"{version_row}\n"
                ),
                stderr="",
                exit_code=0,
            )

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.get_provider_plugin_inventory("codex-cli")

    assert response["exit_code"] == 0
    assert response["raw_stdout"].startswith("Marketplace")
    assert response["plugins"] == [
        {
            "name": "linear@openai-curated",
            "status": "not installed",
            "path": "/home/user/.codex/plugins/linear",
        },
        {
            "name": "review@openai-curated",
            "status": "installed",
            "version": "0.4.0",
            "path": "/tmp/review plugin",
        },
    ]
    assert "version" not in response["plugins"][0]
    assert all("marketplace.json" not in plugin["name"] for plugin in response["plugins"])
    assert response["mutation_capabilities"]["install"]["state"] == "supported"
    assert response["mutation_capabilities"]["remove"]["state"] == "supported"
    assert response["mutation_capabilities"]["enable"]["state"] == "unsupported"
    assert response["mutation_capabilities"]["disable"]["state"] == "unsupported"


def test_codex_feature_inventory_parses_known_features(monkeypatch):
    from app.api.v1 import providers as providers_api

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            assert command == "features"
            assert args == ["list"]
            return SimpleNamespace(
                stdout=(
                    "goals                                   stable             true\n"
                    "memories                                experimental       false\n"
                    "default_mode_request_user_input         under development  false\n"
                    "bad line that should be ignored\n"
                ),
                stderr="",
                exit_code=0,
            )

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.get_provider_feature_inventory("codex-cli")

    assert response["exit_code"] == 0
    assert response["features"] == [
        {"name": "goals", "stage": "stable", "enabled": True},
        {"name": "memories", "stage": "experimental", "enabled": False},
        {"name": "default_mode_request_user_input", "stage": "under development", "enabled": False},
    ]


def test_codex_mcp_add_uses_cli_command_args_and_env(monkeypatch):
    from app.api.v1 import providers as providers_api

    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="added auth_token=secret-value", stderr="", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.add_provider_mcp_server(
        "codex-cli",
        providers_api.CodexMcpAddRequest(
            name="linear",
            command="npx",
            args=["-y", "@linear/mcp"],
            env={"LINEAR_API_KEY": "secret-value"},
        ),
    )

    assert calls == [
        (
            "mcp",
            ["add", "--env", "LINEAR_API_KEY=secret-value", "linear", "--", "npx", "-y", "@linear/mcp"],
            30,
        )
    ]
    assert response["exit_code"] == 0
    assert "secret-value" not in response["stdout"]


def test_codex_mcp_add_uses_url_cli_args(monkeypatch):
    from app.api.v1 import providers as providers_api

    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="added", stderr="", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    providers_api.add_provider_mcp_server(
        "codex-cli",
        providers_api.CodexMcpAddRequest(
            name="remote-server",
            url="https://example.com/mcp",
            bearer_token_env_var="MCP_TOKEN",
        ),
    )

    assert calls == [
        (
            "mcp",
            ["add", "--url", "https://example.com/mcp", "--bearer-token-env-var", "MCP_TOKEN", "remote-server"],
            30,
        )
    ]


def test_codex_mcp_add_rejects_ambiguous_payload():
    from app.api.v1 import providers as providers_api

    request = providers_api.CodexMcpAddRequest(
        name="bad-server",
        command="npx",
        url="https://example.com/mcp",
    )

    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.add_provider_mcp_server("codex-cli", request)

    assert exc_info.value.status_code == 400


def test_codex_mcp_remove_uses_cli_remove(monkeypatch):
    from app.api.v1 import providers as providers_api

    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="removed", stderr="", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.remove_provider_mcp_server("codex-cli", "linear")

    assert calls == [("mcp", ["remove", "linear"], 30)]
    assert response["exit_code"] == 0


def test_codex_plugin_install_uses_cli_add_with_marketplace(monkeypatch):
    from app.api.v1 import providers as providers_api

    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="installed auth_token=secret-value", stderr="", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.install_provider_plugin(
        "codex-cli",
        providers_api.CodexPluginMutationRequest(name="linear", marketplace="openai-curated"),
    )

    assert calls == [("plugin", ["add", "linear", "--marketplace", "openai-curated"], 60)]
    assert response["action"] == "install"
    assert response["exit_code"] == 0
    assert "secret-value" not in response["stdout"]


def test_codex_plugin_install_accepts_selector(monkeypatch):
    from app.api.v1 import providers as providers_api

    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="installed", stderr="", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    providers_api.install_provider_plugin(
        "codex-cli",
        providers_api.CodexPluginMutationRequest(name="linear@openai-curated"),
    )

    assert calls == [("plugin", ["add", "linear@openai-curated"], 60)]


def test_codex_plugin_remove_uses_cli_remove(monkeypatch):
    from app.api.v1 import providers as providers_api

    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="removed", stderr="token=secret-value", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.remove_provider_plugin(
        "codex-cli",
        "linear",
        marketplace="openai-curated",
    )

    assert calls == [("plugin", ["remove", "linear", "--marketplace", "openai-curated"], 60)]
    assert response["action"] == "remove"
    assert "secret-value" not in response["stderr"]


def test_codex_plugin_mutation_rejects_unsafe_selectors():
    from app.api.v1 import providers as providers_api
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        providers_api.CodexPluginMutationRequest(name="../bad")

    request = providers_api.CodexPluginMutationRequest(
        name="linear@openai-curated",
        marketplace="other",
    )
    with pytest.raises(providers_api.HTTPException) as exc_info:
        providers_api.install_provider_plugin("codex-cli", request)

    assert exc_info.value.status_code == 400

    with pytest.raises(providers_api.HTTPException) as remove_exc:
        providers_api.remove_provider_plugin("codex-cli", "..bad")

    assert remove_exc.value.status_code == 400


def test_codex_plugin_enable_disable_are_explicitly_unsupported():
    from app.api.v1 import providers as providers_api

    with pytest.raises(providers_api.HTTPException) as enable_exc:
        providers_api.enable_provider_plugin("codex-cli", "linear@openai-curated")
    with pytest.raises(providers_api.HTTPException) as disable_exc:
        providers_api.disable_provider_plugin("codex-cli", "linear@openai-curated")

    assert enable_exc.value.status_code == 400
    assert "does not expose plugin enable" in enable_exc.value.detail
    assert disable_exc.value.status_code == 400
    assert "does not expose plugin disable" in disable_exc.value.detail


def test_codex_plugin_enable_disable_reject_unsafe_selectors():
    from app.api.v1 import providers as providers_api

    with pytest.raises(providers_api.HTTPException) as enable_exc:
        providers_api.enable_provider_plugin("codex-cli", "..bad")
    with pytest.raises(providers_api.HTTPException) as disable_exc:
        providers_api.disable_provider_plugin("codex-cli", "..bad")

    assert enable_exc.value.status_code == 400
    assert "Plugin selector" in enable_exc.value.detail
    assert disable_exc.value.status_code == 400
    assert "Plugin selector" in disable_exc.value.detail
