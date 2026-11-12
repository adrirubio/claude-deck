"""T-I1–T-I4: ordinary starts must finish evidence-gated provider upgrades."""
import json
import sqlite3
from pathlib import Path
import zipfile

import pytest

from .provider_upgrade_harness import OLD, NEW, entries, provision, run_startup, customize


@pytest.mark.parametrize("provider", ["claude-code", "muse-cli", "codex-cli", "copilot-cli", "opencode-cli"])
def test_t_i1_pinned_v31_ordinary_start_rewrites_registration(tmp_path, provider):
    install = provision(tmp_path / "install")
    custom_url = customize(install, provider)
    before = entries(install, provider)[OLD]
    result = run_startup(install)
    assert result.returncode == 0, result.stderr[-4000:]
    after = entries(install, provider)
    assert OLD not in after, "ordinary startup left the positively owned old registration"
    assert NEW in after, "ordinary startup did not install the new registration"
    env_key = "environment" if provider == "opencode-cli" else "env"
    assert after[NEW][env_key]["SYNTH_CITY_URL"] == before[env_key]["CLAUDE_DECK_URL"]
    assert after[NEW][env_key]["SYNTH_CITY_PROVIDER"] == before[env_key]["CLAUDE_DECK_PROVIDER"]
    assert not any(key.startswith("CLAUDE_DECK_") for key in after[NEW][env_key])
    assert after[NEW][env_key]["SYNTH_CITY_URL"] == custom_url
    assert after[NEW][env_key]["PRIVATE_SETTING"] == "synthetic-unpublished-value"
    assert after[NEW]["upgrade_custom"] == {"keep": False}
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"][provider]["state"] == "verified", status["providers"][provider]
    assert custom_url not in json.dumps(status) and "synthetic-unpublished-value" not in json.dumps(status)
    assert not (install.root / "network-attempts").exists(), "tools/list attempted session registration or other network access"
    with sqlite3.connect(install.app_dir / "synth_city.db") as db:
        assert db.execute("SELECT count(*) FROM mail_agent_sessions").fetchone()[0] == len(install.before.records["mail_agent_sessions"])
        backups = db.execute("SELECT file_path FROM backups WHERE name LIKE 'provider-upgrade-%'").fetchall()
    assert backups, "provider rewrite has no durably indexed safety backup"
    for (raw,) in backups:
        path = Path(raw)
        assert path.is_absolute() and path.parent == install.home / ".albiex-synth-city/backups"
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert archive.namelist()


def test_t_i2_unowned_registration_remains_byte_identical_and_needs_attention(tmp_path):
    install = provision(tmp_path / "install")
    path = install.home / ".claude.json"
    doc = json.loads(path.read_text())
    doc["mcpServers"][OLD]["args"] = ["/unrelated/agent_mail_server.py"]
    path.write_text(json.dumps(doc, indent=3) + "\n")
    before = path.read_bytes()
    result = run_startup(install)
    assert result.returncode == 0, result.stderr[-4000:]
    assert path.read_bytes() == before
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"]["claude-code"]["state"] == "needs_attention"


@pytest.mark.parametrize("operation", ["remove", "add"])
def test_t_i3_cli_failure_is_incomplete_and_normal_restart_finishes(tmp_path, operation):
    install = provision(tmp_path / "install")
    before = entries(install, "codex-cli")[OLD]
    first = run_startup(install, environment={"PROVIDER_TEST_CLI_FAIL": operation})
    assert first.returncode == 0, first.stderr[-4000:]
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"]["codex-cli"]["state"] == "incomplete"
    if operation == "remove":
        assert entries(install, "codex-cli")[OLD] == before
    second = run_startup(install)
    assert second.returncode == 0, second.stderr[-4000:]
    after = entries(install, "codex-cli")
    assert OLD not in after and NEW in after
    assert after[NEW]["env"]["SYNTH_CITY_URL"] == before["env"]["CLAUDE_DECK_URL"]


@pytest.mark.parametrize("boundary", ["captured", "backup_durable", "backup_indexed", "old_removed",
                                     "new_applied", "verified", "status_durable"])
def test_t_i3_abrupt_cut_resumes_at_ordinary_start_without_old_registration(tmp_path, boundary):
    install = provision(tmp_path / "install")
    code = '''
import os
from app.services import provider_upgrade as upgrade
def cut(stage, record):
    if stage == BOUNDARY and record.get('provider') == 'codex-cli':
        os._exit(77)
upgrade._checkpoint = cut
'''.replace("BOUNDARY", repr(boundary))
    first = run_startup(install, code=code)
    assert first.returncode == 77, first.stderr[-4000:]
    second = run_startup(install)
    assert second.returncode == 0, second.stderr[-4000:]
    after = entries(install, "codex-cli")
    assert OLD not in after and NEW in after
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"]["codex-cli"]["state"] == "verified"


def test_test_instance_skips_provider_discovery_and_mutation(tmp_path):
    install = provision(tmp_path / "install")
    paths = [install.home / name for name in (".claude.json", ".codex/config.toml", ".copilot/mcp-config.json")]
    before = [path.read_bytes() for path in paths]
    result = run_startup(install, test_instance=True,
        code="from app.database import init_db\nasyncio.run(init_db())")
    assert result.returncode == 0, result.stderr[-4000:]
    assert [path.read_bytes() for path in paths] == before
    assert not (install.root / "cli-operations.jsonl").exists()


@pytest.mark.parametrize("owned_mcp,owned_plugin", [(True, False), (False, True), (True, True)])
def test_t_i2_t_i4_opencode_artifacts_have_independent_ownership(tmp_path, owned_mcp, owned_plugin):
    install = provision(tmp_path / "install")
    config = install.home / ".config/opencode/opencode.json"
    old_plugin = config.parent / "plugins/claude-deck-agent-mail.js"
    new_plugin = old_plugin.with_name("albiex-synth-city-agent-mail.js")
    if not owned_mcp:
        doc = json.loads(config.read_text())
        doc["mcp"][OLD]["command"] = ["python", "/unrelated/agent_mail_server.py"]
        config.write_text(json.dumps(doc, indent=3) + "\n")
    if not owned_plugin:
        old_plugin.write_text("// user plugin; keep exactly\nexport const Custom = () => {};\n")
    before_config, before_plugin = config.read_bytes(), old_plugin.read_bytes()
    result = run_startup(install)
    assert result.returncode == 0, result.stderr[-4000:]
    if owned_mcp:
        assert OLD not in entries(install, "opencode-cli") and NEW in entries(install, "opencode-cli")
    else:
        assert config.read_bytes() == before_config
    if owned_plugin:
        assert not old_plugin.exists()
        assert "Albiex Synth City Agent Mail OpenCode plugin" in new_plugin.read_text()
        assert "export const AlbiexSynthCityAgentMailPlugin" in new_plugin.read_text()
        assert "CLAUDE_DECK_" not in new_plugin.read_text()
    else:
        assert old_plugin.read_bytes() == before_plugin
        assert not new_plugin.exists()


@pytest.mark.parametrize("equal", [True, False])
def test_t_i3_both_names_preserve_matching_values_or_stop_before_mutation(tmp_path, equal):
    install = provision(tmp_path / "install")
    path = install.home / ".claude.json"
    doc = json.loads(path.read_text())
    old = doc["mcpServers"][OLD]
    new = old | {"env": {"SYNTH_CITY_URL": old["env"]["CLAUDE_DECK_URL"], "SYNTH_CITY_PROVIDER": "claude-code"}}
    if not equal:
        new["env"]["SYNTH_CITY_URL"] = "http://conflict.invalid"
    doc["mcpServers"][NEW] = new
    path.write_text(json.dumps(doc, indent=3))
    before = path.read_bytes()
    result = run_startup(install)
    assert result.returncode == 0, result.stderr[-4000:]
    after = entries(install, "claude-code")
    if equal:
        assert OLD not in after and after[NEW] == new
    else:
        assert path.read_bytes() == before
        status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
        assert status["providers"]["claude-code"]["state"] == "needs_attention"


def test_t_i4_copilot_hook_filename_follows_new_registration(tmp_path):
    install = provision(tmp_path / "install")
    old = install.home / ".copilot/hooks/claude-deck-mail.json"
    new = old.with_name(NEW + ".json")
    assert old.is_file() and not new.exists()
    result = run_startup(install)
    assert result.returncode == 0, result.stderr[-4000:]
    assert not old.exists() and new.is_file()
    assert "--deck-url" not in new.read_text()
    assert "--synth-city-url" in new.read_text()


@pytest.mark.parametrize("failure", ["capture", "backup", "index", "write", "status"])
def test_t_i3_transient_storage_failure_is_not_completion_and_restarts_finish(tmp_path, failure):
    install = provision(tmp_path / "install")
    code = '''
from app.services import provider_upgrade as u, provider_upgrade_artifacts as a
from pathlib import Path
FAILURE = CHOICE
if FAILURE == 'capture':
    original = a.snapshot
    def failed(path):
        if str(path).endswith('.codex/hooks.json'):
            raise OSError('synthetic unreadable capture')
        return original(path)
    a.snapshot = failed
elif FAILURE in ('backup', 'index'):
    name = '_backup' if FAILURE == 'backup' else '_index_backup'
    original = getattr(u, name)
    if FAILURE == 'index':
        async def failed(record):
            if record['provider'] == 'codex-cli':
                raise OSError('synthetic index failure')
            return await original(record)
    else:
        def failed(record):
            if record['provider'] == 'codex-cli':
                raise OSError('synthetic backup failure')
            return original(record)
    setattr(u, name, failed)
elif FAILURE == 'write':
    original = u._write
    def failed(file, target):
        if str(file['path']).endswith('.codex/config.toml') and target == file['after']:
            raise OSError('synthetic file write failure')
        return original(file, target)
    u._write = failed
else:
    original = u._atomic
    def failed(path, data, mode=0o600):
        if Path(path).name == 'provider-upgrade-status.json' and b'"codex-cli"' in data:
            raise OSError('synthetic status publication failure')
        return original(path, data, mode)
    u._atomic = failed
'''.replace("CHOICE", repr(failure))
    first = run_startup(install, code=code)
    assert first.returncode == 0, first.stderr[-4000:]
    if failure in {"capture", "backup", "index"}:
        assert OLD in entries(install, "codex-cli")
        assert NEW not in entries(install, "codex-cli")
    second = run_startup(install)
    assert second.returncode == 0, second.stderr[-4000:]
    assert OLD not in entries(install, "codex-cli") and NEW in entries(install, "codex-cli")
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"]["codex-cli"]["state"] == "verified"


def test_t_i3_cut_between_removal_and_stage_publication_recovers_and_backup_precedes_mutation(tmp_path):
    install = provision(tmp_path / "install")
    code = '''
import os, sqlite3, zipfile
from pathlib import Path
from app.services import provider_upgrade as u
original = u._write
def cut(file, target):
    if str(file['path']).endswith('.codex/config.toml') and target == file['removed']:
        with sqlite3.connect('synth_city.db') as db:
            indexed = db.execute("SELECT file_path FROM backups WHERE name LIKE 'provider-upgrade-%'").fetchall()
        assert indexed, 'mutation preceded the backup index barrier'
        assert all(Path(row[0]).is_absolute() and Path(row[0]).is_file() for row in indexed)
        for row in indexed:
            with zipfile.ZipFile(row[0]) as archive:
                assert archive.testzip() is None
        original(file, target)
        os._exit(77)
    return original(file, target)
u._write = cut
'''
    first = run_startup(install, code=code)
    assert first.returncode == 77, first.stderr[-4000:]
    assert OLD not in entries(install, "codex-cli") and NEW not in entries(install, "codex-cli")
    second = run_startup(install)
    assert second.returncode == 0, second.stderr[-4000:]
    assert NEW in entries(install, "codex-cli") and OLD not in entries(install, "codex-cli")
    with sqlite3.connect(install.app_dir / "synth_city.db") as db:
        paths = [row[0] for row in db.execute("SELECT file_path FROM backups WHERE name LIKE 'provider-upgrade-%'")]
    assert len(paths) == len(set(paths)) == len(list((install.home / '.albiex-synth-city/backups').glob('provider-upgrade-*.zip')))


@pytest.mark.parametrize("defect", ["server_name", "missing_tool"])
def test_t_i1_protocol_failure_is_incomplete_until_the_actual_shipped_shim_verifies(tmp_path, defect):
    install = provision(tmp_path / "install")
    shim = install.app_dir / "mcp_shim/agent_mail_server.py"
    original = shim.read_text()
    if defect == "server_name":
        broken = original.replace('FastMCP("albiex-synth-city-mail")', 'FastMCP("synthetic-wrong-server")')
    else:
        broken = original.replace('@mcp.tool()\ndef synth_city_ack_message', 'def synth_city_ack_message')
    assert broken != original
    shim.write_text(broken)
    first = run_startup(install)
    assert first.returncode == 0, first.stderr[-4000:]
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"]["codex-cli"]["state"] == "incomplete"
    assert status["providers"]["codex-cli"]["stage"] != "verified"
    shim.write_text(original)
    second = run_startup(install)
    assert second.returncode == 0, second.stderr[-4000:]
    status = json.loads((install.home / ".albiex-synth-city/provider-upgrade-status.json").read_text())
    assert status["providers"]["codex-cli"]["state"] == "verified"
