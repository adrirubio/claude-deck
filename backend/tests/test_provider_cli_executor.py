"""Tests for provider-aware CLI execution."""
from types import SimpleNamespace
from unittest.mock import patch


def test_provider_cli_executor_uses_codex_binary_and_whitelist():
    from app.services.cli_executor import ProviderCLIExecutor

    with patch("app.services.cli_executor.shutil.which", return_value="/usr/bin/codex"), \
         patch("app.services.cli_executor.subprocess.run") as run:
        run.return_value = SimpleNamespace(stdout="{}", stderr="", returncode=0)
        result = ProviderCLIExecutor("codex-cli").execute("doctor", ["--json"])

    run.assert_called_once()
    assert run.call_args.args[0] == ["/usr/bin/codex", "doctor", "--json"]
    assert result.exit_code == 0


def test_provider_cli_api_redacts_sensitive_output(monkeypatch):
    from app.api.v1 import providers as providers_api
    from app.models.schemas import CLIExecuteRequest

    class FakeExecutor:
        binary_path = "/usr/bin/codex"
        provider = SimpleNamespace(display_name="Codex")
        ALLOWED_COMMANDS = ["doctor"]

        def validate_command(self, command):
            return command == "doctor"

        def execute(self, command, args):
            return SimpleNamespace(stdout="token=secret-token", stderr="api_key=secret-key", exit_code=0)

    monkeypatch.setattr(providers_api, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    response = providers_api.execute_provider_cli(
        "codex-cli",
        CLIExecuteRequest(command="doctor", args=[]),
    )

    assert response.stdout == "token=[redacted]"
    assert response.stderr == "api_key=[redacted]"


def test_provider_cli_executor_rejects_unsafe_codex_command():
    from app.services.cli_executor import ProviderCLIExecutor

    executor = ProviderCLIExecutor("codex-cli")

    assert executor.validate_command("exec") is False
    assert executor.validate_command("logout") is False
    assert executor.validate_command("doctor") is True


def test_provider_cli_executor_uses_container_message_when_no_agent_clis(monkeypatch):
    from app.services import runtime_environment
    from app.services.cli_executor import ProviderCLIExecutor

    monkeypatch.setattr(runtime_environment, "is_containerized", lambda: True)
    monkeypatch.setattr("app.services.cli_executor.shutil.which", lambda _name: None)
    monkeypatch.setattr("app.services.runtime_environment.shutil.which", lambda _name: None)

    executor = ProviderCLIExecutor("codex-cli")

    try:
        executor.execute("doctor", ["--json"])
    except ValueError as exc:
        assert str(exc) == runtime_environment.CONTAINER_AGENT_CLI_WARNING
    else:
        raise AssertionError("Expected missing binary error")


def test_legacy_cli_executor_defaults_to_claude_code():
    from app.services.cli_executor import CLIExecutor

    with patch("app.services.cli_executor.shutil.which", return_value="/usr/bin/claude"):
        executor = CLIExecutor()

    assert executor.provider_id == "claude-code"
    assert executor.claude_binary == "/usr/bin/claude"
