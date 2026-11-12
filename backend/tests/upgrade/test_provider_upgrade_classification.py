"""T-I2: positive evidence, complete values and independent artifacts."""
import copy
import asyncio
import json

import pytest


def test_t_i2_server_name_and_hook_substrings_are_not_installation_identity(tmp_path):
    from app.services.provider_upgrade_artifacts import is_owned_entry
    shim = tmp_path / "ours/mcp_shim/agent_mail_server.py"
    shim.parent.mkdir(parents=True)
    shim.write_text("# actual installation")
    own = {"command": "/usr/bin/python3", "args": [str(shim)], "env": {"CLAUDE_DECK_URL": "http://custom.invalid"}}
    assert is_owned_entry(own, shim)
    for args in ([str(tmp_path / "other/agent_mail_server.py")], ["-c", str(shim)],
                 [str(shim) + ".other"], ["claude-deck-mail"]):
        assert not is_owned_entry(own | {"args": args}, shim)
    assert not is_owned_entry({"command": "echo", "args": [str(shim)]}, shim)


@pytest.mark.parametrize("provider,payload", [
    ("codex-cli", [{"name": "claude-deck-mail", "command": "python", "args": ["/owned/shim"]}]),
    ("copilot-cli", {"mcpServers": {"claude-deck-mail": {"command": "python", "args": ["/owned/shim"]}}}),
])
def test_t_i2_cli_list_is_parsed_not_substring_matched(provider, payload):
    from app.services.provider_upgrade_artifacts import parse_cli_entries
    assert "claude-deck-mail" in parse_cli_entries(provider, json.dumps(payload))
    for text in ('notice: claude-deck-mail installed', '"claude-deck-mail"', '{"notice":"claude-deck-mail"}'):
        with pytest.raises(ValueError):
            parse_cli_entries(provider, text)


def test_t_i1_full_entry_capture_preserves_custom_values_and_rejects_env_conflicts():
    from app.services.provider_upgrade_artifacts import renamed_entry
    entry = {"command": "python", "args": ["/owned/shim"], "env": {
        "CLAUDE_DECK_URL": "http://127.0.0.1:43219/custom", "CLAUDE_DECK_PROVIDER": "codex-cli",
        "PRIVATE_SETTING": "synthetic-private-value"}, "custom": {"enabled": False}}
    before = copy.deepcopy(entry)
    result = renamed_entry(entry)
    assert entry == before
    assert result == entry | {"env": {"SYNTH_CITY_URL": entry["env"]["CLAUDE_DECK_URL"],
        "SYNTH_CITY_PROVIDER": "codex-cli", "PRIVATE_SETTING": "synthetic-private-value"}}
    with pytest.raises(ValueError):
        renamed_entry(entry | {"env": entry["env"] | {"SYNTH_CITY_URL": "http://conflict.invalid"}})


def test_t_i2_jsonc_edit_preserves_unrelated_bytes_and_rejects_duplicate_keys():
    from app.services.provider_upgrade_artifacts import edit_json
    source = '{\n // keep comment\n "mcp": {"claude-deck-mail": {"command":"python"},\n "unrelated": { "x" : 2, },},\n "other" : [1,2,],\n}\n'
    result = edit_json(source, ("mcp", "claude-deck-mail"), None, rename="albiex-synth-city-mail")
    assert result == source.replace('"claude-deck-mail"', '"albiex-synth-city-mail"')
    with pytest.raises(ValueError):
        edit_json('{"mcp": {}, "mcp": {}}', ("mcp",), {})


@pytest.mark.parametrize("provider,functions", [
    ("claude-code", ["apply_claude_code_install", "uninstall_claude_code"]),
    ("muse-cli", ["apply_muse_install", "uninstall_muse"]),
    ("codex-cli", ["apply_codex_install", "uninstall_codex"]),
    ("copilot-cli", ["apply_copilot_install", "uninstall_copilot"]),
    ("opencode-cli", ["apply_opencode_install", "uninstall_opencode"]),
])
@pytest.mark.parametrize("state", ["incomplete", "needs_attention"])
def test_setup_actions_cannot_regenerate_over_an_active_upgrade(monkeypatch, provider, functions, state):
    from unittest.mock import AsyncMock
    from app.services import provider_upgrade, agent_mail_install_service as install
    monkeypatch.setattr(provider_upgrade, "read_status", lambda: {provider: {"state": state, "stage": "old_removed"}})
    backup = AsyncMock(side_effect=AssertionError("manual mutation reached the safety capture"))
    monkeypatch.setattr(install, "_backup_before_mutation", backup)
    for name in functions:
        with pytest.raises(ValueError, match="upgrade"):
            asyncio.run(getattr(install, name)(None))
    backup.assert_not_called()
