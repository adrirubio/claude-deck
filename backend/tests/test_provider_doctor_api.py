"""Tests for provider doctor API."""
from types import SimpleNamespace


def test_provider_doctor_returns_parsed_codex_report(monkeypatch):
    from app.api.v1 import providers as providers_api

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            assert command == "doctor"
            assert args == ["--json"]
            assert timeout == 30
            return SimpleNamespace(
                stdout='{"overallStatus":"ok","codexVersion":"0.133.0"}',
                stderr="",
                exit_code=0,
            )

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.get_provider_doctor("codex-cli")

    assert response["provider"] == "codex-cli"
    assert response["exit_code"] == 0
    assert response["report"]["overallStatus"] == "ok"


def test_provider_doctor_redacts_report_and_stderr(monkeypatch):
    from app.api.v1 import providers as providers_api

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            return SimpleNamespace(
                stdout='{"checks":{"auth":{"token":"secret-token"}}}',
                stderr="api_key=secret-key",
                exit_code=1,
            )

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.get_provider_doctor("codex-cli")

    assert response["report"]["checks"]["auth"] == "[redacted]"
    assert "secret-token" not in str(response)
    assert "api_key=[redacted]" in response["stderr"]
