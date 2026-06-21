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
                                        "agent_mail_hook.py --deck-url http://127.0.0.1:8000 "
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
                                        "agent_mail_hook.py --deck-url http://127.0.0.1:8000 "
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
    hooks_path = tmp_path / "claude-deck-mail.json"
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
                                "agent_mail_hook.py --deck-url http://127.0.0.1:8000 "
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
                                "agent_mail_hook.py --deck-url http://127.0.0.1:8000 "
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
    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/curl" if name == "curl" else None)

    status = await install.get_install_status()

    assert set(status.claude_code_hooks_missing) == set(install.MAIL_HOOK_EVENTS)
    assert status.claude_code_mcp_installed is False
    assert status.curl_available is True
    assert set(status.copilot_hooks_missing) == set(install.COPILOT_MAIL_HOOK_EVENTS)


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

    assert {hook.event for hook in added_hooks} == set(install.MAIL_HOOK_EVENTS)
    assert all(hook.scope == "user" for hook in added_hooks)
    post_tool = next(hook for hook in added_hooks if hook.event == "PostToolUse")
    assert post_tool.matcher == install.POST_TOOL_USE_MATCHER
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
        f"CLAUDE_DECK_URL={install.deck_base_url()}",
        "--env",
        "CLAUDE_DECK_PROVIDER=codex-cli",
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
    hooks_path = tmp_path / "claude-deck-mail.json"
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
        f"CLAUDE_DECK_URL={install.deck_base_url()}",
        "--env",
        "CLAUDE_DECK_PROVIDER=copilot-cli",
        "--json",
    ]
    doc = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert doc["version"] == 1
    assert set(doc["hooks"]) == set(install.COPILOT_MAIL_HOOK_EVENTS)
    assert doc["hooks"]["sessionStart"][0]["command"].endswith("--provider copilot-cli --event session-start")
    assert doc["hooks"]["notification"][0]["matcher"] == "agent_idle"
    assert "hooks" not in doc["hooks"]["sessionStart"][0]


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
        deck_url="http://127.0.0.1:8000",
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
