"""Tests for Codex export-only backups."""
import asyncio
import json
import zipfile
from datetime import datetime
from types import SimpleNamespace


class FakeDb:
    def add(self, backup):
        backup.id = 1
        backup.created_at = datetime(2026, 5, 25, 12, 0, 0)

    async def commit(self):
        return None

    async def refresh(self, backup):
        return None


def test_codex_backup_exports_config_rules_and_redacted_inventory(monkeypatch, tmp_path):
    from app.services import backup_service
    from app.services.backup_service import BackupService

    codex_home = tmp_path / "my-codex"
    rules_dir = codex_home / "rules"
    rules_dir.mkdir(parents=True)
    (codex_home / "config.toml").write_text(
        'model = "gpt-5"\nauthToken = "secret-config-token"\n',
        encoding="utf-8",
    )
    (codex_home / "work.config.toml").write_text('profile = "work"\n', encoding="utf-8")
    (rules_dir / "team.rules").write_text("Always test changes.\n", encoding="utf-8")
    (codex_home / "auth.json").write_text('{"token":"must-not-export"}', encoding="utf-8")
    (codex_home / "history.jsonl").write_text("must-not-export\n", encoding="utf-8")
    (codex_home / "models_cache.json").write_text("must-not-export\n", encoding="utf-8")

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(backup_service, "get_backup_storage_dir", lambda: backup_dir)

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            if command == "mcp":
                return SimpleNamespace(
                    stdout='{"servers":{"linear":{"command":"npx","env":{"LINEAR_API_KEY":"secret-api-key"}}}}',
                    stderr="",
                    exit_code=0,
                )
            if command == "plugin":
                return SimpleNamespace(
                    stdout="PLUGIN   STATUS   VERSION   PATH\nlinear   installed          /tmp/linear\n",
                    stderr="auth_token=secret-plugin-token",
                    exit_code=0,
                )
            raise AssertionError(command)

    monkeypatch.setattr(backup_service, "ProviderCLIExecutor", lambda provider_id: FakeExecutor())

    service = BackupService(FakeDb(), codex_home=codex_home)
    backup, manifest = asyncio.run(service.create_backup(
        name="codex-export",
        scope="codex",
        description="Codex export",
    ))

    assert backup.scope == "codex"
    assert manifest.claude_code_version is None
    assert manifest.contents.provider_inventory["provider"] == "codex-cli"
    assert manifest.contents.provider_inventory["mcp"]["servers"]["servers"]["linear"]["env"]["LINEAR_API_KEY"] == "[redacted]"

    with zipfile.ZipFile(backup.file_path) as zf:
        names = set(zf.namelist())
        assert "my-codex/config.toml" in names
        assert "my-codex/work.config.toml" in names
        assert "my-codex/rules/team.rules" in names
        assert "my-codex/provider-inventory.json" in names
        assert ".codex/provider-inventory.json" not in names
        assert "my-codex/auth.json" not in names
        assert "my-codex/history.jsonl" not in names
        assert "my-codex/models_cache.json" not in names

        config_export = zf.read("my-codex/config.toml").decode()
        assert "secret-config-token" not in config_export
        assert 'authToken = "[redacted]"' in config_export

        inventory_export = json.loads(zf.read("my-codex/provider-inventory.json"))
        assert "secret-api-key" not in json.dumps(inventory_export)
        assert "secret-plugin-token" not in json.dumps(inventory_export)


def test_codex_backup_restore_is_export_only(tmp_path):
    from app.services.backup_service import BackupService

    archive_path = tmp_path / "codex.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        zf.writestr("manifest.json", "{}")

    service = BackupService(db=None, codex_home=tmp_path / ".codex")

    async def fake_get_backup(_backup_id):
        return SimpleNamespace(
            scope="codex",
            file_path=str(archive_path),
            name="codex-export",
            created_at=datetime(2026, 5, 25, 12, 0, 0),
        )

    service.get_backup = fake_get_backup

    result = asyncio.run(service.restore_backup(1))

    assert result.success is False
    assert "export-only" in result.message
