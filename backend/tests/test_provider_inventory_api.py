"""Tests for read-only Codex MCP and plugin inventory endpoints."""
from types import SimpleNamespace


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
