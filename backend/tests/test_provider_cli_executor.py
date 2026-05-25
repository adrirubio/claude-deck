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


def test_provider_cli_executor_rejects_unsafe_codex_command():
    from app.services.cli_executor import ProviderCLIExecutor

    executor = ProviderCLIExecutor("codex-cli")

    assert executor.validate_command("exec") is False
    assert executor.validate_command("logout") is False
    assert executor.validate_command("doctor") is True


def test_legacy_cli_executor_defaults_to_claude_code():
    from app.services.cli_executor import CLIExecutor

    with patch("app.services.cli_executor.shutil.which", return_value="/usr/bin/claude"):
        executor = CLIExecutor()

    assert executor.provider_id == "claude-code"
    assert executor.claude_binary == "/usr/bin/claude"

