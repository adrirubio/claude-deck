import json

import pytest

from app.services import agent_mail_install_service as svc


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(svc, "muse_cli_available", lambda: True)

    async def no_backup(db, scope):
        return None

    monkeypatch.setattr(svc, "_backup_before_mutation", no_backup)
    return tmp_path / "settings.json"


@pytest.mark.asyncio
async def test_install_keeps_existing_servers_and_hooks(settings_file):
    other_hook = {"hooks": [{"type": "command", "command": "/usr/bin/true"}]}
    settings_file.write_text(json.dumps({"schema_version": 1, "tui": {"theme": "dark"},
        "mcpServers": {"mine": {"transport": "stdio", "command": "x"}},
        "hooks": {"SessionStart": [other_hook]}}))
    await svc.apply_muse_install(None)
    doc = json.loads(settings_file.read_text())
    assert doc["schema_version"] == 1 and doc["tui"] == {"theme": "dark"}
    assert doc["mcpServers"]["mine"] == {"transport": "stdio", "command": "x"}
    assert doc["mcpServers"]["claude-deck-mail"]["transport"] == "stdio"
    assert other_hook in doc["hooks"]["SessionStart"]
    assert svc.muse_mcp_installed() and sorted(svc.installed_muse_hooks()) == ["SessionStart", "UserPromptSubmit"]
    await svc.apply_muse_install(None)  # idempotent: no duplicate groups
    doc = json.loads(settings_file.read_text())
    assert len(doc["hooks"]["SessionStart"]) == 2
    await svc.uninstall_muse(None)
    doc = json.loads(settings_file.read_text())
    assert "claude-deck-mail" not in doc["mcpServers"] and doc["hooks"]["SessionStart"] == [other_hook]
    assert "UserPromptSubmit" not in doc["hooks"]


@pytest.mark.asyncio
async def test_install_creates_a_versioned_file(settings_file):
    status = await svc.apply_muse_install(None)
    assert json.loads(settings_file.read_text())["schema_version"] == 1
    assert status.muse_settings_path == str(settings_file)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["{not json", "[]", '{"schema_version": 1, "mcpServers": []}'])
async def test_install_refuses_malformed_settings(settings_file, content):
    settings_file.write_text(content)
    with pytest.raises(ValueError):
        await svc.apply_muse_install(None)
    assert settings_file.read_text() == content


def test_hook_command_names_the_provider():
    assert "--provider muse-cli" in svc.muse_hook_command("session-start")


def test_readiness_needs_the_mcp_entry_and_both_hooks():
    from types import SimpleNamespace
    from app.services.provider_readiness_service import configuration_readiness
    ready = SimpleNamespace(muse_cli_available=True, muse_mcp_installed=True, muse_hooks_missing=[])
    assert configuration_readiness("muse-cli", "Muse Code", True, ready).state == "ready"
    missing = SimpleNamespace(muse_cli_available=True, muse_mcp_installed=True, muse_hooks_missing=["SessionStart"])
    assert configuration_readiness("muse-cli", "Muse Code", True, missing).state == "blocked"


def test_hook_session_key_uses_the_muse_prefix():
    from app.api.v1.agent_mail import _hook_provider, _hook_session_key
    payload = {"provider": "muse-cli", "session_id": "01a13be9-b3fa-79f3-941d-e49637f03184"}
    assert _hook_provider(payload) == "muse-cli"
    assert _hook_session_key(payload) == "muse:01a13be9-b3fa-79f3-941d-e49637f03184"
