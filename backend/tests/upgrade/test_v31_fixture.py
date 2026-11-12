"""Section-7 shared Fixture contracts, prerequisites for T-D1/T-D7/T-G2."""
import copy
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from .v31_fixture import V31_SOURCE_SHA, SemanticSnapshot, copy_database_set


def test_fixture_executes_pinned_v31_code_and_keeps_committed_wal(v31_install, tmp_path):
    install = v31_install
    assert install.manifest["source_sha"] == V31_SOURCE_SHA
    assert install.manifest["version"] == "3.1.0"
    assert Path(install.manifest["imported_app"]).is_relative_to(install.source)
    assert install.database == install.app_dir / "claude_registry.db"
    wal = Path(str(install.database) + "-wal")
    assert wal.stat().st_size > 32
    assert Path(str(install.database) + "-shm").stat().st_size > 0
    # Main-file-only recovery must lose the final API-created sentinel. A
    # nonempty WAL left over from a checkpoint would not prove this property.
    main_only = tmp_path / "main-only.db"
    main_only.write_bytes(install.database.read_bytes())
    with sqlite3.connect(main_only) as db:
        assert db.execute("SELECT count(*) FROM agent_team_presets WHERE name = ?",
                          ("WAL-only team",)).fetchone()[0] == 0
    rows = install.before.records["agent_team_presets"].values()
    assert any(row["name"] == "WAL-only team" for row in rows)


def test_fixture_contains_api_created_domain_records_and_exact_paths(v31_install):
    install = v31_install
    records = install.before.records
    for table in ("agent_team_presets", "agent_team_slots", "mail_team_members",
                  "mail_agent_sessions", "mail_messages", "team_github_scopes", "backups",
                  "bridge_session_attachments", "deck_compat_migrations"):
        assert records[table], f"Missing fixture table contents: {table}"
    scope = next(iter(records["team_github_scopes"].values()))
    assert scope["dispatch_label"] == "claude-deck-ready"
    assert scope["design_label"] == "claude-deck-design"
    assert scope["merge_policy"] == "human"
    assert scope["enabled"] == 0
    settings = json.loads((install.home / ".claude/settings.json").read_text())
    assert settings["env"]["UPGRADE_FIXTURE_SETTING"] == "keep this setting"
    assert any(row["body_markdown"] == "Keep this pre-upgrade mail history."
               for row in records["mail_messages"].values())
    assert any(slot["provider"] == "pi-cli" for slot in records["agent_team_slots"].values())
    for row in records["backups"].values():
        assert Path(row["file_path"]).is_relative_to(install.home / ".claude-registry/backups")
    assert install.before.paths
    for fields in install.before.paths.values():
        assert fields


def test_fixture_backup_is_listable_downloadable_valid_and_restorable(v31_install):
    evidence = v31_install.manifest["backup_reader_checks"]
    assert evidence["listed"] is True
    assert evidence["download_sha256"] == v31_install.before.files[evidence["file_path"]]
    assert evidence["valid"] is True
    assert evidence["restored"] is True
    assert evidence["restored_setting"] == "keep this setting"


def test_fixture_has_one_live_and_one_expired_attachment_with_real_bytes(v31_install):
    install = v31_install
    rows = list(install.before.records["bridge_session_attachments"].values())
    now = datetime.fromisoformat(install.manifest["snapshot_time"])
    assert len(rows) == 2
    assert sum(datetime.fromisoformat(row["expires_at"]) > now for row in rows) == 1
    assert sum(datetime.fromisoformat(row["expires_at"]) < now for row in rows) == 1
    for row in rows:
        path = Path(row["storage_path"])
        assert path.is_relative_to(install.home / ".claude-registry/bridge-attachments")
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        assert install.before.files[str(path)] == row["sha256"]
        assert row["agent_path"] == str(path)
        assert str(path) in row["prompt_text"]


def test_fixture_registrations_come_from_old_installers_and_keep_custom_url(v31_install):
    home = v31_install.home
    claude = json.loads((home / ".claude.json").read_text())["mcpServers"]["claude-deck-mail"]
    import tomllib
    codex = tomllib.loads((home / ".codex/config.toml").read_text())["mcp_servers"]["claude-deck-mail"]
    copilot = json.loads((home / ".copilot/mcp-config.json").read_text())["mcpServers"]["claude-deck-mail"]
    opencode = json.loads((home / ".config/opencode/opencode.json").read_text())["mcp"]["claude-deck-mail"]
    assert set(v31_install.manifest["installed_providers"]) == {
        "claude-code", "codex-cli", "copilot-cli", "opencode-cli"}
    for entry in (claude, codex, copilot):
        assert entry["env"]["CLAUDE_DECK_PROVIDER"]
        assert entry["env"]["CLAUDE_DECK_URL"]
        assert Path(entry["args"][0]).is_file()
    assert opencode["environment"]["CLAUDE_DECK_URL"] == "http://127.0.0.1:43219/custom"
    assert (home / ".codex/hooks.json").is_file()
    assert (home / ".copilot/hooks/claude-deck-mail.json").is_file()
    assert (home / ".config/opencode/plugins/claude-deck-agent-mail.js").is_file()
    assert any("pi-agent-mail" in arg for arg in v31_install.manifest["pi_command"])


def test_fixture_browser_state_uses_both_original_storage_areas(v31_install):
    state = v31_install.browser_state
    assert state["localStorage"] == {"claude-deck:selected-provider": "pi-cli"}
    assert state["sessionStorage"] == {
        "claude-deck.agent-teams.operator-token": "synthetic-upgrade-operator"}


def test_snapshot_reads_do_not_checkpoint_or_modify_the_fixture(v31_install):
    install = v31_install
    paths = [Path(str(install.database) + suffix) for suffix in ("", "-wal", "-shm")]
    before = [path.read_bytes() for path in paths]
    again = SemanticSnapshot.capture(install.database)
    install.before.assert_preserved(again)
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("mutation", ["delete", "field", "path", "label", "file"])
def test_semantic_comparison_rejects_lost_or_changed_preexisting_data(v31_install, mutation):
    before = v31_install.before
    after = copy.deepcopy(before)
    table = "agent_team_presets"
    key = next(iter(after.records[table]))
    if mutation == "delete":
        del after.records[table][key]
    elif mutation == "field":
        after.records[table][key]["description"] = "silently changed"
    elif mutation == "path":
        row = next(iter(after.records["backups"].values()))
        row["file_path"] += ".wrong"
    elif mutation == "label":
        row = next(iter(after.records["team_github_scopes"].values()))
        row["dispatch_label"] = "silently-reset-label"
    else:
        after.files[next(iter(after.files))] = "different bytes"
    with pytest.raises(AssertionError):
        before.assert_preserved(after)


def test_snapshot_allows_only_explicit_path_mappings_and_new_rows(v31_install):
    before = v31_install.before
    after = copy.deepcopy(before)
    mapping = {}
    for table, rows in after.records.items():
        for row in rows.values():
            for field in ("file_path", "storage_path", "agent_path", "prompt_text"):
                value = row.get(field)
                if isinstance(value, str) and ".claude-registry" in value:
                    new_value = value.replace(".claude-registry", ".albiex-synth-city")
                    mapping[value] = new_value
                    row[field] = new_value
    after.files = {mapping.get(path, path): digest for path, digest in after.files.items()}
    after.records["backups"]["new-migration-row"] = {"id": 999, "name": "new metadata"}
    before.assert_preserved(after, path_map=mapping)
    # A mapping must never authorize rewriting unrelated charter/history text.
    table = "mail_messages"
    row = next(iter(after.records[table].values()))
    old_text = row["body_markdown"]
    row["body_markdown"] = "changed history"
    with pytest.raises(AssertionError):
        before.assert_preserved(after, path_map=mapping | {old_text: "changed history"})


def test_snapshot_reads_wal_changes_and_detects_physical_row_mutations(v31_install, tmp_path):
    database = copy_database_set(v31_install.database, tmp_path)
    original = SemanticSnapshot.capture(database)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE agent_team_presets SET description = ? WHERE id = ?",
                   ("corrupted after upgrade", v31_install.manifest["preset_id"]))
    changed = SemanticSnapshot.capture(database)
    with pytest.raises(AssertionError):
        original.assert_preserved(changed)
