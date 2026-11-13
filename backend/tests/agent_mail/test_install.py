"""Install service: status, confirmed endpoints, Claude Code and Codex mutation paths."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from app.database import get_db
from app.main import app
from app.models.schemas import AgentMailInstallStatus
from app.services import agent_mail_install_service as install


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def test_hook_command_forwards_stdin_and_fails_soft(monkeypatch):
    monkeypatch.setattr(install.settings, "port", 8123)
    command = install.hook_command("session-start")
    assert "http://127.0.0.1:8123/api/v1/agent-mail/hooks/session-start" in command
    assert "-f" in command
    assert "--connect-timeout 0.25" in command
    assert "-m 1" in command
    assert "--data-binary @-" in command
    assert "|| true" in command


def test_installed_codex_hooks_accept_python_alias(monkeypatch, tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear|compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/tmp/venv/bin/python /repo/backend/mcp_shim/"
                                        "agent_mail_hook.py --synth-city-url http://127.0.0.1:8000 "
                                        "--provider codex-cli --event session-start"
                                    ),
                                }
                            ],
                        }
                    ],
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/tmp/venv/bin/python /repo/backend/mcp_shim/"
                                        "agent_mail_hook.py --synth-city-url http://127.0.0.1:8000 "
                                        "--provider codex-cli --event user-prompt-submit"
                                    ),
                                }
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(install, "codex_hooks_path", lambda: hooks_path)

    assert install.installed_codex_hooks() == ["SessionStart", "UserPromptSubmit"]


def test_installed_copilot_hooks_use_official_hook_file_shape(monkeypatch, tmp_path):
    hooks_path = tmp_path / "albiex-synth-city-mail.json"
    hooks_path.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {
                            "type": "command",
                            "command": (
                                "/tmp/venv/bin/python /repo/backend/mcp_shim/"
                                "agent_mail_hook.py --synth-city-url http://127.0.0.1:8000 "
                                "--provider copilot-cli --event session-start"
                            ),
                            "timeoutSec": 2,
                        }
                    ],
                    "notification": [
                        {
                            "type": "command",
                            "command": (
                                "/tmp/venv/bin/python /repo/backend/mcp_shim/"
                                "agent_mail_hook.py --synth-city-url http://127.0.0.1:8000 "
                                "--provider copilot-cli --event user-prompt-submit"
                            ),
                            "matcher": "agent_idle",
                            "timeoutSec": 2,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(install, "copilot_hooks_path", lambda: hooks_path)

    assert install.installed_copilot_hooks() == ["notification", "sessionStart"]


def test_installed_opencode_plugin_events_use_managed_plugin(monkeypatch, tmp_path):
    plugin_path = tmp_path / "albiex-synth-city-agent-mail.js"
    plugin_path.write_text(install._opencode_plugin_content(), encoding="utf-8")
    monkeypatch.setattr(install, "opencode_plugin_path", lambda: plugin_path)

    assert install.installed_opencode_plugin_events() == sorted(install.OPENCODE_MAIL_PLUGIN_EVENTS)


def test_opencode_mcp_status_respects_jsonc_precedence(monkeypatch, tmp_path):
    json_path = tmp_path / "opencode.json"
    jsonc_path = tmp_path / "opencode.jsonc"
    json_path.write_text(
        json.dumps({"mcp": {"servers": {install.MCP_SERVER_NAME: install._opencode_mcp_entry()}}}),
        encoding="utf-8",
    )
    jsonc_path.write_text(
        json.dumps({"mcp": {"servers": {install.MCP_SERVER_NAME: {"enabled": False}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(install, "opencode_config_paths", lambda: [json_path, jsonc_path])

    assert install.opencode_mcp_installed() is False

    jsonc_path.write_text(
        json.dumps({"mcp": {"servers": {install.MCP_SERVER_NAME: install._opencode_mcp_entry()}}}),
        encoding="utf-8",
    )

    assert install.opencode_mcp_installed() is True


@pytest.mark.asyncio
async def test_get_status_reports_missing_hooks(monkeypatch):
    monkeypatch.setattr(install.hook_service, "list_hooks", lambda: [])
    monkeypatch.setattr(install.mcp_service, "get_server", AsyncMock(return_value=None))
    monkeypatch.setattr(install, "codex_cli_available", lambda: False)
    monkeypatch.setattr(install, "codex_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_codex_hooks", lambda: [])
    monkeypatch.setattr(install, "copilot_cli_available", lambda: False)
    monkeypatch.setattr(install, "copilot_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_copilot_hooks", lambda: [])
    monkeypatch.setattr(install, "opencode_cli_available", lambda: False)
    monkeypatch.setattr(install, "opencode_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_opencode_plugin_events", lambda: [])
    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    status = await install.get_install_status()

    assert set(status.claude_code_hooks_missing) == set(install.MAIL_HOOK_EVENTS)
    assert status.claude_code_mcp_installed is False
    assert status.curl_available is True
    assert set(status.copilot_hooks_missing) == set(install.COPILOT_MAIL_HOOK_EVENTS)
    assert set(status.opencode_plugin_events_missing) == set(install.OPENCODE_MAIL_PLUGIN_EVENTS)


@pytest.mark.asyncio
async def test_status_treats_stale_hook_commands_as_missing(monkeypatch):
    stale_hook = SimpleNamespace(
        event="SessionStart",
        matcher=None,
        type="command",
        command="curl -s -m 3 -X POST http://127.0.0.1:8123/api/v1/agent-mail/hooks/session-start",
    )
    monkeypatch.setattr(install.hook_service, "list_hooks", lambda: [stale_hook])
    monkeypatch.setattr(install.mcp_service, "get_server", AsyncMock(return_value=None))
    monkeypatch.setattr(install, "codex_cli_available", lambda: False)
    monkeypatch.setattr(install, "codex_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_codex_hooks", lambda: [])
    monkeypatch.setattr(install, "copilot_cli_available", lambda: False)
    monkeypatch.setattr(install, "copilot_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_copilot_hooks", lambda: [])
    monkeypatch.setattr(install, "opencode_cli_available", lambda: False)
    monkeypatch.setattr(install, "opencode_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_opencode_plugin_events", lambda: [])
    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    status = await install.get_install_status()

    assert "SessionStart" in status.claude_code_hooks_missing
    assert "SessionStart" not in status.claude_code_hooks


@pytest.mark.asyncio
async def test_claude_code_apply_adds_user_scope_hooks_and_mcp(monkeypatch, db):
    added_hooks = []
    added_servers = []
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "_installed_mail_hooks", lambda: [])
    monkeypatch.setattr(install.hook_service, "add_hook", lambda hook: added_hooks.append(hook))
    monkeypatch.setattr(install.mcp_service, "get_server", AsyncMock(return_value=None))

    async def add_server(server, project_path=None):
        added_servers.append(server)

    monkeypatch.setattr(install.mcp_service, "add_server", add_server)
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.apply_claude_code_install(db)

    assert {hook.event for hook in added_hooks} == {
        "SessionStart", "UserPromptSubmit", "SessionEnd", "PostToolUse", "PreToolUse",
    }
    assert all(hook.scope == "user" for hook in added_hooks)
    post_tool = next(hook for hook in added_hooks if hook.event == "PostToolUse")
    assert post_tool.matcher == install.POST_TOOL_USE_MATCHER
    question = next(hook for hook in added_hooks if hook.event == "PreToolUse")
    assert question.matcher == "AskUserQuestion"
    assert "team_question_hook.py" in question.command
    assert added_servers[0].scope == "user"
    assert added_servers[0].name == install.MCP_SERVER_NAME


@pytest.mark.asyncio
async def test_claude_code_apply_replaces_stale_agent_mail_hooks(monkeypatch, db):
    stale_hook = SimpleNamespace(
        id="old-hook",
        scope="user",
        event="SessionStart",
        matcher=None,
        type="command",
        command="curl -s -m 3 -X POST http://127.0.0.1:8123/api/v1/agent-mail/hooks/session-start",
    )
    removed_hooks = []
    added_hooks = []
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "_installed_mail_hooks", lambda: [stale_hook])
    monkeypatch.setattr(
        install.hook_service,
        "remove_hook",
        lambda hook_id, scope: removed_hooks.append((hook_id, scope)),
    )
    monkeypatch.setattr(install.hook_service, "add_hook", lambda hook: added_hooks.append(hook))
    monkeypatch.setattr(install.mcp_service, "get_server", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.apply_claude_code_install(db)

    assert ("old-hook", "user") in removed_hooks
    replacement = next(hook for hook in added_hooks if hook.event == "SessionStart")
    assert "--connect-timeout 0.25" in replacement.command
    assert "-m 1" in replacement.command


@pytest.mark.asyncio
async def test_codex_apply_uses_provider_executor(monkeypatch, db, tmp_path):
    calls = []
    hooks_path = tmp_path / "hooks.json"

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

    monkeypatch.setattr(install, "_codex_executor", lambda: FakeExecutor())
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "codex_hooks_path", lambda: hooks_path)
    monkeypatch.setattr(install, "codex_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.apply_codex_install(db)

    assert calls[0][0] == "mcp"
    assert calls[0][1][:5] == [
        "add",
        "--env",
        f"SYNTH_CITY_URL={install.synth_city_base_url()}",
        "--env",
        "SYNTH_CITY_PROVIDER=codex-cli",
    ]
    assert install.MCP_SERVER_NAME in calls[0][1]


@pytest.mark.asyncio
async def test_codex_apply_writes_hooks_json(monkeypatch, db, tmp_path):
    hooks_path = tmp_path / "hooks.json"

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

    monkeypatch.setattr(install, "_codex_executor", lambda: FakeExecutor())
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "codex_hooks_path", lambda: hooks_path)
    monkeypatch.setattr(install, "codex_mcp_installed", lambda: True)
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.apply_codex_install(db)

    doc = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert set(doc["hooks"]) == set(install.CODEX_MAIL_HOOK_EVENTS)
    for event in install.CODEX_MAIL_HOOK_EVENTS:
        groups = doc["hooks"][event]
        assert len(groups) == 1
        assert "agent_mail_hook.py" in groups[0]["hooks"][0]["command"]
    assert doc["hooks"]["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"


@pytest.mark.asyncio
async def test_copilot_apply_uses_provider_executor_and_writes_hooks_json(monkeypatch, db, tmp_path):
    hooks_path = tmp_path / "albiex-synth-city-mail.json"
    calls = []

    class FakeExecutor:
        binary_path = "/usr/bin/copilot"

        def execute(self, command, args, timeout=30):
            calls.append((command, args, timeout))
            return SimpleNamespace(stdout='{"mcpServers":{}}', stderr="", exit_code=0)

    monkeypatch.setattr(install, "_copilot_executor", lambda: FakeExecutor())
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "copilot_hooks_path", lambda: hooks_path)
    monkeypatch.setattr(install, "copilot_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.apply_copilot_install(db)

    assert calls[0][0] == "mcp"
    assert calls[0][1][:6] == [
        "add",
        "--env",
        f"SYNTH_CITY_URL={install.synth_city_base_url()}",
        "--env",
        "SYNTH_CITY_PROVIDER=copilot-cli",
        "--json",
    ]
    doc = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert set(doc["hooks"]) == set(install.COPILOT_MAIL_HOOK_EVENTS)
    assert doc["hooks"]["sessionStart"][0]["command"].endswith("--provider copilot-cli --event session-start")
    assert doc["hooks"]["notification"][0]["matcher"] == "agent_idle"
    assert "hooks" not in doc["hooks"]["sessionStart"][0]


@pytest.mark.asyncio
async def test_opencode_apply_writes_mcp_config_and_plugin(monkeypatch, db, tmp_path):
    config_path = tmp_path / "opencode.json"
    plugin_path = tmp_path / "plugins" / "albiex-synth-city-agent-mail.js"
    monkeypatch.setattr(install, "opencode_cli_available", lambda: True)
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "opencode_config_path", lambda: config_path)
    monkeypatch.setattr(install, "opencode_config_paths", lambda: [config_path])
    monkeypatch.setattr(install, "opencode_plugin_path", lambda: plugin_path)
    monkeypatch.setattr(install, "opencode_question_deny_ledger_path", lambda: tmp_path / "ledger.json")
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.apply_opencode_install(db)

    doc = json.loads(config_path.read_text(encoding="utf-8"))
    entry = doc["mcp"]["servers"][install.MCP_SERVER_NAME]
    assert entry["type"] == "local"
    assert entry["command"] == [install.sys.executable, install.shim_path()]
    assert entry["environment"]["SYNTH_CITY_PROVIDER"] == "opencode-cli"
    plugin = plugin_path.read_text(encoding="utf-8")
    assert "Albiex Synth City Agent Mail OpenCode plugin" in plugin
    assert 'ctx.session.hook("context"' in plugin and "experimental.chat.system.transform" not in plugin


@pytest.mark.asyncio
async def test_opencode_uninstall_removes_managed_mcp_and_plugin(monkeypatch, db, tmp_path):
    config_path = tmp_path / "opencode.json"
    plugin_path = tmp_path / "plugins" / "albiex-synth-city-agent-mail.js"
    plugin_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "mcp": {
                    install.MCP_SERVER_NAME: install._opencode_mcp_entry(),
                    "keep": {"type": "remote", "url": "https://example.test/mcp"},
                }
            }
        ),
        encoding="utf-8",
    )
    plugin_path.write_text(install._opencode_plugin_content(), encoding="utf-8")
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "opencode_config_path", lambda: config_path)
    monkeypatch.setattr(install, "opencode_config_paths", lambda: [config_path])
    monkeypatch.setattr(install, "opencode_plugin_path", lambda: plugin_path)
    monkeypatch.setattr(install, "opencode_question_deny_ledger_path", lambda: tmp_path / "ledger.json")
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.uninstall_opencode(db)

    doc = json.loads(config_path.read_text(encoding="utf-8"))
    assert install.MCP_SERVER_NAME not in doc["mcp"]
    assert "keep" in doc["mcp"]
    assert not plugin_path.exists()


@pytest.mark.asyncio
async def test_codex_uninstall_prunes_only_agent_mail_hooks(monkeypatch, db, tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python /tmp/agent_mail_hook.py --event session-start",
                                },
                                {"type": "command", "command": "echo keep"},
                            ],
                        },
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "curl -X POST "
                                        "http://127.0.0.1:8000/api/v1/agent-mail/hooks/session-start"
                                    ),
                                }
                            ]
                        },
                    ],
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo also-keep"},
                            ]
                        }
                    ],
                }
            },
        ),
        encoding="utf-8",
    )
    removed = []

    class FakeExecutor:
        binary_path = "/usr/bin/codex"

        def execute(self, command, args, timeout=30):
            removed.append((command, args))
            return SimpleNamespace(stdout="", stderr="", exit_code=0)

    monkeypatch.setattr(install, "_codex_executor", lambda: FakeExecutor())
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install, "codex_hooks_path", lambda: hooks_path)
    monkeypatch.setattr(install, "codex_mcp_installed", lambda: True)
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))

    await install.uninstall_codex(db)

    doc = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert doc["hooks"]["SessionStart"] == [
        {
            "matcher": "startup",
            "hooks": [{"type": "command", "command": "echo keep"}],
        }
    ]
    assert doc["hooks"]["UserPromptSubmit"] == [
        {"hooks": [{"type": "command", "command": "echo also-keep"}]}
    ]
    assert removed == [("mcp", ["remove", install.MCP_SERVER_NAME])]


@pytest.mark.asyncio
async def test_install_endpoints_require_confirmation(client, monkeypatch):
    status = AgentMailInstallStatus(
        claude_code_hooks=[],
        claude_code_hooks_missing=[],
        claude_code_mcp_installed=True,
        codex_cli_available=False,
        codex_mcp_installed=False,
        copilot_cli_available=False,
        copilot_mcp_installed=False,
        curl_available=True,
        shim_path="/tmp/shim.py",
        python_path="/usr/bin/python",
        synth_city_url="http://127.0.0.1:8000",
        claude_settings_path="/home/test/.claude/settings.json",
        claude_mcp_config_path="/home/test/.claude.json",
    )
    monkeypatch.setattr(install, "apply_claude_code_install", AsyncMock(return_value=status))
    resp = await client.post("/api/v1/agent-mail/install/claude-code/apply", json={})
    assert resp.status_code == 400

    resp = await client.post(
        "/api/v1/agent-mail/install/claude-code/apply",
        json={"confirmed": True},
    )
    assert resp.status_code == 200
    install.apply_claude_code_install.assert_awaited_once()


@pytest.mark.parametrize("marker", [None, "", "0", "bad", "23"])
def test_question_hook_blocks_only_team_sessions(tmp_path, marker):
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "mcp_shim" / "team_question_hook.py"
    environment = {"HOME": str(tmp_path), "PATH": os.defpath}
    if marker is not None:
        environment["SYNTH_CITY_TEAM_SLOT_ID"] = marker
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"tool_name": "AskUserQuestion"}),
        env=environment, text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    if marker == "23":
        output = json.loads(result.stdout)["hookSpecificOutput"]
        assert output["hookEventName"] == "PreToolUse"
        assert output["permissionDecision"] == "deny"
        assert "Leader" in output["permissionDecisionReason"]
        assert "Supervisor" in output["permissionDecisionReason"]
        assert "operator action record" in output["permissionDecisionReason"]
    else:
        assert result.stdout == ""


@pytest.mark.asyncio
async def test_question_hook_install_status_and_remove_preserve_user_hooks(monkeypatch, db, tmp_path):
    from app.services import hook_service

    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir()
    original = {"env": {"EXAMPLE_SETTING": "preserved"}, "hooks": {
        "PreToolUse": [{"matcher": "AskUserQuestion", "hooks": [
            {"id": "user-hook", "type": "command", "command": "echo user-hook"}]}]}}
    settings_file.write_text(json.dumps(original))
    monkeypatch.setattr(hook_service, "get_claude_user_settings_file", lambda: settings_file)
    monkeypatch.setattr(install, "_backup_before_mutation", AsyncMock())
    monkeypatch.setattr(install.mcp_service, "get_server", AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(install.mcp_service, "remove_server", AsyncMock())
    monkeypatch.setattr(install, "codex_cli_available", lambda: False)
    monkeypatch.setattr(install, "codex_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_codex_hooks", lambda: [])
    monkeypatch.setattr(install, "copilot_cli_available", lambda: False)
    monkeypatch.setattr(install, "copilot_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_copilot_hooks", lambda: [])
    monkeypatch.setattr(install, "opencode_cli_available", lambda: False)
    monkeypatch.setattr(install, "opencode_mcp_installed", lambda: False)
    monkeypatch.setattr(install, "installed_opencode_plugin_events", lambda: [])

    status = await install.apply_claude_code_install(db)
    assert status.claude_code_prompt_block_installed is True
    assert "PreToolUse" in status.claude_code_hooks
    await install.apply_claude_code_install(db)
    installed = json.loads(settings_file.read_text())
    questions = installed["hooks"]["PreToolUse"][0]["hooks"]
    assert len(questions) == 2
    assert questions[0] == original["hooks"]["PreToolUse"][0]["hooks"][0]
    status = await install.uninstall_claude_code(db)
    assert status.claude_code_prompt_block_installed is False
    removed = json.loads(settings_file.read_text())
    assert removed["env"] == original["env"]
    assert removed["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]


def test_question_hook_marker_does_not_own_unrelated_commands(monkeypatch):
    user_hook = SimpleNamespace(type="command", command="echo /custom/team_question_hook.py")
    monkeypatch.setattr(install.hook_service, "list_hooks", lambda: [user_hook])
    assert install._installed_mail_hooks() == []


# --- OpenCode v2 install (#732) -------------------------------------------------------

_V1_PLUGIN = """// Albiex Synth City Agent Mail OpenCode plugin.
export const AlbiexSynthCityAgentMailPlugin = async (ctx) => {
  return {
    event: async ({ event }) => { if (event.type === "session.created") {} },
    "tool.execute.after": async (input) => {},
    "experimental.chat.system.transform": async (input, output) => {},
  };
};
// session-start user-prompt-submit session-end post-tool-use session.idle session.deleted
"""
_DENY = {"action": "question", "resource": "*", "effect": "deny"}


@pytest.fixture
def oc(monkeypatch, tmp_path):
    home = tmp_path / "opencode"
    home.mkdir()
    env = SimpleNamespace(
        json=home / "opencode.json",
        jsonc=home / "opencode.jsonc",
        plugin=home / "plugins" / "albiex-synth-city-agent-mail.js",
        ledger=tmp_path / "synth" / "agent-mail" / "opencode-question-deny.json",
        backup=AsyncMock(),
    )
    monkeypatch.setattr(install, "get_opencode_home", lambda: home)
    # raising=False: these tests must also run against the pre-#732 module (baseline evidence).
    monkeypatch.setattr(install, "opencode_question_deny_ledger_path", lambda: env.ledger, raising=False)
    monkeypatch.setattr(install, "opencode_cli_available", lambda: True)
    monkeypatch.setattr(install, "_backup_before_mutation", env.backup)
    monkeypatch.setattr(install, "_require_upgrade_complete", lambda provider: None)
    monkeypatch.setattr(install, "get_install_status", AsyncMock(return_value=SimpleNamespace()))
    env.doc = lambda path=None: json.loads((path or env.json).read_text(encoding="utf-8"))
    env.ledger_doc = lambda: json.loads(env.ledger.read_text(encoding="utf-8"))
    return env


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _flat_v1_entry():
    """The entry Synth City wrote at mcp.<name> before #732 (literal, not a module helper)."""
    return {
        "type": "local",
        "command": [install.sys.executable, install.shim_path()],
        "enabled": True,
        "environment": {"SYNTH_CITY_URL": install.synth_city_base_url(), "SYNTH_CITY_PROVIDER": "opencode-cli"},
    }


def test_v2_plugin_contract_is_recognized_and_v1_needs_update(oc):
    oc.plugin.parent.mkdir(parents=True)
    oc.plugin.write_text(install._opencode_plugin_content(), encoding="utf-8")
    assert install.installed_opencode_plugin_events() == sorted(install.OPENCODE_MAIL_PLUGIN_EVENTS)
    content = install._opencode_plugin_content()
    assert "export default" in content and "setup(ctx)" in content and "import " not in content
    assert '"albiex-synth-city-agent-mail"' in content

    oc.plugin.write_text(_V1_PLUGIN.replace("// Albiex", "// " + install._OPENCODE_PLUGIN_MARKER + " //"), encoding="utf-8")
    # A v1 plugin never loads on OpenCode 2, so none of its events count (#729 answer 4).
    assert install.installed_opencode_plugin_events() == []


@pytest.mark.asyncio
async def test_fresh_install_writes_v2_server_deny_rule_ledger_and_plugin(oc, db):
    _write(oc.json, {"theme": "dark", "mcp": {"servers": {"other": {"type": "remote", "url": "https://x.test"}}}})
    await install.apply_opencode_install(db)

    doc = oc.doc()
    entry = doc["mcp"]["servers"][install.MCP_SERVER_NAME]
    assert entry["type"] == "local" and entry["codemode"] is False and entry["enabled"] is True
    assert entry["command"] == [install.sys.executable, install.shim_path()]
    assert doc["mcp"]["servers"]["other"] == {"type": "remote", "url": "https://x.test"}
    assert doc["theme"] == "dark"
    assert doc["permissions"] == [_DENY]
    ledger = oc.ledger_doc()["entries"][str(oc.json.resolve())]
    assert ledger["state"] == "inserted" and ledger["rule"] == _DENY
    assert install.installed_opencode_plugin_events() == sorted(install.OPENCODE_MAIL_PLUGIN_EVENTS)
    assert install.opencode_mcp_installed() is True
    oc.backup.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_over_v1_migrates_the_owned_flat_entry_and_replaces_the_plugin(oc, db):
    _write(oc.json, {"mcp": {install.MCP_SERVER_NAME: _flat_v1_entry(), "keep": {"type": "local", "command": ["x"]}}})
    oc.plugin.parent.mkdir(parents=True)
    oc.plugin.write_text(_V1_PLUGIN.replace("// Albiex", "// " + install._OPENCODE_PLUGIN_MARKER + " //"), encoding="utf-8")
    assert install.opencode_mcp_installed() is False  # a flat v1 entry needs the update

    await install.apply_opencode_install(db)

    doc = oc.doc()
    assert install.MCP_SERVER_NAME not in doc["mcp"]
    assert doc["mcp"]["keep"] == {"type": "local", "command": ["x"]}
    assert install.MCP_SERVER_NAME in doc["mcp"]["servers"]
    assert install.installed_opencode_plugin_events() == sorted(install.OPENCODE_MAIL_PLUGIN_EVENTS)


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["flat", "servers"])
async def test_a_foreign_entry_under_our_name_is_refused_not_overwritten(oc, db, where):
    foreign = {"type": "local", "command": ["/usr/bin/someone-else"], "enabled": True}
    doc = {"mcp": {install.MCP_SERVER_NAME: foreign}} if where == "flat" else {"mcp": {"servers": {install.MCP_SERVER_NAME: foreign}}}
    _write(oc.json, doc)
    before = oc.json.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="not managed by Albiex Synth City"):
        await install.apply_opencode_install(db)
    assert oc.json.read_text(encoding="utf-8") == before
    assert not oc.plugin.exists() and not oc.ledger.exists()
    oc.backup.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_install_keeps_one_rule_and_the_original_provenance(oc, db):
    _write(oc.json, {"permissions": [{"action": "shell", "resource": "*", "effect": "ask"}]})
    await install.apply_opencode_install(db)
    first = oc.ledger_doc()["entries"][str(oc.json.resolve())]
    await install.apply_opencode_install(db)
    await install.apply_opencode_install(db)

    doc = oc.doc()
    assert doc["permissions"] == [{"action": "shell", "resource": "*", "effect": "ask"}, _DENY]
    assert oc.ledger_doc()["entries"][str(oc.json.resolve())] == first


@pytest.mark.asyncio
async def test_a_pre_existing_identical_rule_is_never_claimed_or_removed(oc, db):
    _write(oc.json, {"permissions": [dict(_DENY)]})
    await install.apply_opencode_install(db)
    assert oc.doc()["permissions"] == [_DENY]
    assert oc.ledger_doc()["entries"][str(oc.json.resolve())]["state"] == "preexisting"

    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY]  # the user's rule stays
    await install.apply_opencode_install(db)
    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY]


@pytest.mark.asyncio
async def test_uninstall_removes_only_what_it_proves_it_inserted(oc, db):
    _write(oc.json, {"theme": "dark", "mcp": {"servers": {"other": {"type": "remote", "url": "https://x.test"}}}})
    await install.apply_opencode_install(db)
    await install.uninstall_opencode(db)

    doc = oc.doc()
    assert doc["theme"] == "dark"
    assert doc["mcp"]["servers"] == {"other": {"type": "remote", "url": "https://x.test"}}
    assert doc.get("permissions", []) == []
    assert not oc.plugin.exists()
    assert str(oc.json.resolve()) not in oc.ledger_doc()["entries"]


@pytest.mark.asyncio
@pytest.mark.parametrize("ledger_state", ["missing", "corrupt", "other_path", "rule_changed"])
async def test_uninstall_keeps_the_rule_when_ownership_is_unproven(oc, db, ledger_state):
    await install.apply_opencode_install(db)
    assert oc.doc()["permissions"] == [_DENY]
    if ledger_state == "missing":
        oc.ledger.write_text(json.dumps({"version": 1, "entries": {}}), encoding="utf-8")
    elif ledger_state == "corrupt":
        oc.ledger.write_text("{not json", encoding="utf-8")
    elif ledger_state == "other_path":
        oc.ledger.write_text(json.dumps({"version": 1, "entries": {"/elsewhere/opencode.json": {"state": "inserted", "rule": _DENY}}}), encoding="utf-8")
    else:
        ledger = oc.ledger_doc()
        ledger["entries"][str(oc.json.resolve())]["rule"] = {"action": "question", "resource": "*", "effect": "ask"}
        oc.ledger.write_text(json.dumps(ledger), encoding="utf-8")

    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY]


@pytest.mark.asyncio
async def test_uninstall_keeps_duplicate_identical_rules(oc, db):
    await install.apply_opencode_install(db)
    doc = oc.doc()
    doc["permissions"].append(dict(_DENY))
    _write(oc.json, doc)
    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY, _DENY]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["install", "uninstall"])
@pytest.mark.parametrize("which,content", [
    ("json", "{not json"),
    ("jsonc", "// comment\n{\"mcp\": [}"),
    ("json", "[1, 2]"),
    ("json", json.dumps({"mcp": []})),
    ("json", json.dumps({"mcp": {"servers": []}})),
    ("json", json.dumps({"permissions": {"question": "deny"}})),
])
async def test_malformed_config_is_refused_before_backup_or_any_write(oc, db, action, which, content):
    path = oc.json if which == "json" else oc.jsonc
    path.write_text(content, encoding="utf-8")
    other = oc.jsonc if which == "json" else oc.json
    if action == "uninstall":
        oc.plugin.parent.mkdir(parents=True)
        oc.plugin.write_text(install._opencode_plugin_content(), encoding="utf-8")
    plugin_before = oc.plugin.read_text(encoding="utf-8") if oc.plugin.exists() else None
    with pytest.raises(ValueError):
        if action == "install":
            await install.apply_opencode_install(db)
        else:
            await install.uninstall_opencode(db)
    assert path.read_text(encoding="utf-8") == content
    assert not other.exists()
    assert (oc.plugin.read_text(encoding="utf-8") if oc.plugin.exists() else None) == plugin_before
    assert not oc.ledger.exists()
    oc.backup.assert_not_awaited()


@pytest.mark.asyncio
async def test_jsonc_takes_precedence_and_is_the_written_file(oc, db):
    oc.jsonc.write_text('// mine\n{"theme": "light",}\n', encoding="utf-8")
    await install.apply_opencode_install(db)
    doc = json.loads(install._strip_json_comments_and_trailing_commas(oc.jsonc.read_text(encoding="utf-8")))
    assert doc["theme"] == "light" and install.MCP_SERVER_NAME in doc["mcp"]["servers"]
    assert not oc.json.exists()
    assert str(oc.jsonc.resolve()) in oc.ledger_doc()["entries"]


@pytest.mark.asyncio
async def test_status_reports_v2_events_update_need_and_question_deny(oc, monkeypatch):
    monkeypatch.undo()
    # Re-apply only the path fixtures; get_install_status itself is under test.
    monkeypatch.setattr(install, "get_opencode_home", lambda: oc.json.parent)
    monkeypatch.setattr(install, "opencode_question_deny_ledger_path", lambda: oc.ledger, raising=False)
    oc.plugin.parent.mkdir(parents=True)
    oc.plugin.write_text(_V1_PLUGIN.replace("// Albiex", "// " + install._OPENCODE_PLUGIN_MARKER + " //"), encoding="utf-8")
    status = await install.get_install_status()
    assert status.opencode_plugin_events == []
    assert status.opencode_plugin_events_missing == list(install.OPENCODE_MAIL_PLUGIN_EVENTS)
    assert getattr(status, "opencode_plugin_needs_update", None) is True
    assert getattr(status, "opencode_question_denied", None) is False

    oc.plugin.write_text(install._opencode_plugin_content(), encoding="utf-8")
    _write(oc.json, {"permissions": [_DENY]})
    status = await install.get_install_status()
    assert status.opencode_plugin_events_missing == []
    assert getattr(status, "opencode_plugin_needs_update", None) is False
    assert getattr(status, "opencode_question_denied", None) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_on", ["plugin", "config", "ledger"])
async def test_an_interrupted_install_never_claims_an_unproven_insertion(oc, db, monkeypatch, fail_on):
    _write(oc.json, {"theme": "dark"})
    real = getattr(install, "_atomic_write_text", None)
    if real is None:
        pytest.fail("no atomic write path exists for config, plugin and ownership record")

    def flaky(path, text):
        target = {"plugin": oc.plugin, "config": oc.json, "ledger": oc.ledger}[fail_on]
        if path == target:
            raise OSError("disk full")
        real(path, text)

    monkeypatch.setattr(install, "_atomic_write_text", flaky)
    with pytest.raises(OSError):
        await install.apply_opencode_install(db)
    assert oc.doc()["theme"] == "dark"  # user settings survive at every step
    assert not oc.ledger.exists()  # nothing claims an insertion yet

    monkeypatch.setattr(install, "_atomic_write_text", real)
    await install.apply_opencode_install(db)  # a re-run of Set up repairs the state
    doc = oc.doc()
    assert doc["theme"] == "dark" and doc["permissions"] == [_DENY]
    state = oc.ledger_doc()["entries"][str(oc.json.resolve())]["state"]
    # The rule was already written when only the ledger failed, so it is not provably ours.
    assert state == ("preexisting" if fail_on == "ledger" else "inserted")
    await install.uninstall_opencode(db)
    assert oc.doc().get("permissions") == ([_DENY] if fail_on == "ledger" else [])


_NODE_DRIVER = r"""
import { pathToFileURL } from "node:url";
const [pluginPath, scriptJson] = process.argv.slice(2);
const calls = [];
globalThis.fetch = async (url, init) => { calls.push({ route: url.split("/hooks/")[1], body: JSON.parse(init.body) }); return { ok: true, json: async () => ({}) }; };
const handlers = { events: [], tool: {}, session: {}, permission: {} };
const ctx = {
  event: { subscribe: (fn) => handlers.events.push(fn) },
  tool: { hook: (name, fn) => { handlers.tool[name] = fn; } },
  session: { hook: (name, fn) => { handlers.session[name] = fn; } },
  permission: { hook: (name, fn) => { handlers.permission[name] = fn; } },
};
const plugin = (await import(pathToFileURL(pluginPath).href)).default;
plugin.setup(ctx);
const results = [];
for (const step of JSON.parse(scriptJson)) {
  if (step.event) for (const fn of handlers.events) await fn(step.event);
  if (step.evaluate) { const input = { ...step.evaluate }; await handlers.permission.evaluate(input); results.push(input); }
  if (step.toolAfter) await handlers.tool["execute.after"](step.toolAfter);
}
console.log(JSON.stringify({ calls, results }));
"""


def _form(kind, form_id, created, kind_meta="question"):
    return {"type": kind, "created": created, "data": {"sessionID": "ses_a", "form": {"id": form_id, "metadata": {"kind": kind_meta}}},
            "location": {"directory": "/work/repo"}}


def _run_plugin(tmp_path, steps, env=None):
    import os
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    plugin = tmp_path / "plugin.mjs"
    plugin.write_text(install._opencode_plugin_content(), encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(_NODE_DRIVER, encoding="utf-8")
    result = subprocess.run([node, str(driver), str(plugin), json.dumps(steps)], capture_output=True, text=True,
                            timeout=30, env={"PATH": os.environ.get("PATH", ""), **(env or {})})
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_plugin_reports_one_wait_per_member_with_one_generation(tmp_path):
    out = _run_plugin(tmp_path, [
        {"event": _form("form.created", "A", 1_000)},
        {"event": _form("form.created", "B", 1_005)},
        {"event": _form("form.replied", "A", 1_010)},
        {"event": _form("form.cancelled", "B", 1_020)},
        {"event": _form("form.created", "C", 900)},  # clock went back: still strictly newer
        {"event": _form("form.replied", "C", 1_030)},
    ])
    waits = [c["body"] for c in out["calls"] if c["route"] == "input-wait"]
    assert [(w["state"], w["generation"]) for w in waits] == [("open", 1000), ("clear", 1000), ("open", 1001), ("clear", 1001)]
    assert all(w["kind"] == "question" and w["provider"] == "opencode-cli" for w in waits)


def test_plugin_sends_no_clear_after_an_unknown_close_or_overflow(tmp_path):
    out = _run_plugin(tmp_path, [
        {"event": _form("form.created", "A", 2_000)},
        {"event": _form("form.replied", "X", 2_001)},  # an id it never saw: uncertain
        {"event": _form("form.replied", "A", 2_002)},
    ])
    assert [c["body"]["state"] for c in out["calls"] if c["route"] == "input-wait"] == ["open"]
    steps = [{"event": _form("form.created", f"Q{i}", 3_000 + i)} for i in range(65)]
    steps += [{"event": _form("form.replied", f"Q{i}", 4_000 + i)} for i in range(65)]
    out = _run_plugin(tmp_path, steps)
    assert [c["body"]["state"] for c in out["calls"] if c["route"] == "input-wait"] == ["open"]


def test_plugin_denies_questions_only_for_team_slots_and_maps_tool_input(tmp_path):
    team = _run_plugin(tmp_path, [{"evaluate": {"action": "question", "resources": ["*"], "effect": "allow"}},
                                  {"evaluate": {"action": "shell", "resources": ["*"], "effect": "allow"}},
                                  {"toolAfter": {"tool": "edit", "sessionID": "ses_a", "input": {"filePath": "/w/a.py"}}}],
                       env={"SYNTH_CITY_TEAM_SLOT_ID": "7"})
    assert team["results"][0]["effect"] == "deny" and "Leader" in team["results"][0]["message"]
    assert team["results"][1]["effect"] == "allow"
    post = [c["body"] for c in team["calls"] if c["route"] == "post-tool-use"][0]
    assert post["tool_input"]["file_path"] == "/w/a.py" and post["team_slot_id"] == 7
    solo = _run_plugin(tmp_path, [{"evaluate": {"action": "question", "resources": ["*"], "effect": "allow"}}])
    assert solo["results"][0]["effect"] == "allow"


# V1 review 5890688064: plugin uncertainty must outlive the interval that caused it, and a
# deny-rule ownership record must be revoked before any mutation and whenever it is ambiguous.
from tests.agent_mail.test_opencode_input_wait import _binding, _gen, _record, maker, team  # noqa: E402,F401


def _wait_states(out):
    return [c["body"]["state"] for c in out["calls"] if c["route"] == "input-wait"]


@pytest.mark.asyncio
async def test_an_overflowed_wait_survives_a_later_complete_interval(tmp_path, maker, team):
    generation = _gen()
    steps = [{"event": _form("form.created", f"Q{i}", generation + i)} for i in range(65)]
    # Q64 is dropped at the cap and stays open; only the 64 tracked forms close.
    steps += [{"event": _form("form.replied", f"Q{i}", generation + 100 + i)} for i in range(64)]
    steps += [{"event": _form("form.created", "later", generation + 200)},
              {"event": _form("form.replied", "later", generation + 201)}]
    out = _run_plugin(tmp_path, steps)
    waits = [c["body"] for c in out["calls"] if c["route"] == "input-wait"]
    assert [w["state"] for w in waits] == ["open", "open"]  # no clear once the process is uncertain
    for wait in waits:
        await _record(maker, wait["state"], wait["generation"])
    assert (await _binding(maker, team)).waiting_input_reason == "question", "Q64 is still open"


def test_an_unknown_close_keeps_the_plugin_uncertain_for_later_intervals(tmp_path):
    out = _run_plugin(tmp_path, [
        {"event": _form("form.created", "A", 5_000)},
        {"event": _form("form.replied", "X", 5_001)},  # never seen: order is unprovable
        {"event": _form("form.replied", "A", 5_002)},
        {"event": _form("form.created", "B", 5_003)},
        {"event": _form("form.replied", "B", 5_004)},
        {"event": _form("form.created", "C", 5_005)},
        {"event": _form("form.replied", "C", 5_006)},
    ])
    assert _wait_states(out) == ["open", "open", "open"]


@pytest.mark.asyncio
async def test_remove_after_duplicates_never_reuses_the_stale_ownership_record(oc, db):
    await install.apply_opencode_install(db)
    doc = oc.doc(); doc["permissions"].append(dict(_DENY)); _write(oc.json, doc)
    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY, _DENY]  # ambiguous: both kept
    assert str(oc.json.resolve()) not in oc.ledger_doc()["entries"]  # and the claim is revoked
    doc = oc.doc(); doc["permissions"] = [dict(_DENY)]; _write(oc.json, doc)  # the user keeps one
    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["missing", "non_identical"])
async def test_remove_revokes_ownership_when_the_rule_is_missing_or_changed(oc, db, change):
    await install.apply_opencode_install(db)
    doc = oc.doc()
    doc["permissions"] = [] if change == "missing" else [{"action": "question", "resource": "*", "effect": "ask"}]
    _write(oc.json, doc)
    await install.uninstall_opencode(db)
    assert str(oc.json.resolve()) not in oc.ledger_doc()["entries"]
    doc = oc.doc(); doc["permissions"] = [dict(_DENY)]; _write(oc.json, doc)  # the user adds their own
    await install.uninstall_opencode(db)
    assert oc.doc()["permissions"] == [_DENY]


@pytest.mark.asyncio
async def test_a_failed_ownership_revocation_leaves_the_config_unchanged(oc, db, monkeypatch):
    await install.apply_opencode_install(db)
    before = oc.json.read_text(encoding="utf-8")
    real = install._atomic_write_text

    def fail_ledger(path, text):
        if path == oc.ledger:
            raise OSError("synthetic interrupted uninstall")
        real(path, text)

    monkeypatch.setattr(install, "_atomic_write_text", fail_ledger)
    with pytest.raises(OSError):
        await install.uninstall_opencode(db)
    assert oc.json.read_text(encoding="utf-8") == before  # nothing changed before the revocation
    monkeypatch.setattr(install, "_atomic_write_text", real)
    await install.uninstall_opencode(db)  # the proof is intact, so a retry removes only our rule
    assert oc.doc().get("permissions") == []


@pytest.mark.asyncio
async def test_a_failed_config_write_after_revocation_keeps_the_rule_unowned(oc, db, monkeypatch):
    await install.apply_opencode_install(db)
    real = install._atomic_write_text
    order = []

    def fail_config(path, text):
        order.append("ledger" if path == oc.ledger else "config" if path == oc.json else str(path))
        if path == oc.json:
            raise OSError("synthetic interrupted uninstall")
        real(path, text)

    monkeypatch.setattr(install, "_atomic_write_text", fail_config)
    with pytest.raises(OSError):
        await install.uninstall_opencode(db)
    assert order[:2] == ["ledger", "config"]  # the revocation is durable before the config changes
    assert oc.doc()["permissions"] == [_DENY]
    assert str(oc.json.resolve()) not in oc.ledger_doc()["entries"]
    monkeypatch.setattr(install, "_atomic_write_text", real)
    await install.uninstall_opencode(db)  # unowned now: the user's view of the rule is kept
    assert oc.doc()["permissions"] == [_DENY]
