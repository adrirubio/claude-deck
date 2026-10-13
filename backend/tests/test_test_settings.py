"""Test configuration must not inherit installation credentials."""
import pytest
import os
from pathlib import Path
import subprocess
import sys

from app.config import Settings, settings


def test_global_settings_use_disposable_defaults():
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    assert settings.operator_token == ""
    assert settings.github_token == ""
    assert settings.github_app_id == ""
    assert settings.github_coordination_hold_paths == []
    assert settings.mail_capability_tokens_required is True


def test_settings_ignore_dotenv_and_process_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPERATOR_TOKEN=synthetic-dotenv-token\nDEBUG=invalid\n")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-process-token")
    # Explicit test configuration remains possible; ambient values do not apply.
    config = Settings(operator_token="synthetic-explicit-token")
    assert config.operator_token == "synthetic-explicit-token"
    assert config.github_token == ""
    assert config.debug is False


@pytest.mark.parametrize("field", ["operator_token", "github_token", "github_app_private_key_path",
                                  "database_url", "github_recovery_only_attempt"])
def test_settings_repr_excludes_secrets(field):
    config = Settings(_env_file=None, **{field: "synthetic-secret-marker"})
    assert "synthetic-secret-marker" not in repr(config)
    assert "synthetic-secret-marker" not in str(config)
    assert getattr(config, field) == "synthetic-secret-marker"


def test_settings_repr_excludes_private_hold_paths():
    config = Settings(github_coordination_hold_paths=["synthetic-private-hold-path"])
    assert "synthetic-private-hold-path" not in repr(config)


def test_bootstrap_ignores_configured_environment(tmp_path):
    (tmp_path / ".env").write_text(
        "OPERATOR_TOKEN=synthetic-dotenv-token\nGITHUB_APP_ID=123\nDEBUG=invalid\n")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]),
               OPERATOR_TOKEN="synthetic-process-token", DEBUG="invalid",
               DATABASE_URL="synthetic-invalid-database-url")
    result = subprocess.run([
        sys.executable, "-c",
        "import tests.conftest; from app.config import settings; "
        "assert settings.operator_token == ''; assert settings.github_app_id == ''; "
        "assert settings.debug is False; "
        "assert settings.database_url == 'sqlite+aiosqlite:///:memory:'",
    ], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
