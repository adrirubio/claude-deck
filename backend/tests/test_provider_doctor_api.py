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

