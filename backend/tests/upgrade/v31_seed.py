"""Executed only in the pinned v3.1 source, with a fresh child environment.

No SQL/ORM row inserts live here. All domain state is created by old APIs.
The only simulated boundaries are provider executables, network/tmux access,
managed system configuration locations, and the attachment creation clock.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import tomlkit


ROOT = Path(sys.argv[1])
HOME_DIR = ROOT / "home"
SOURCE = ROOT / "v3.1.0-source"
TARGET = "upgrade-fixture:0.0"


def reject_network(*_args, **_kwargs):
    raise AssertionError("The v3.1 fixture cannot use network sockets")


def reject_process(*_args, **_kwargs):
    raise FileNotFoundError("No external executables are installed in the fixture")


class InstallerCLI:
    """Interpret only the old installer's mcp add/list command at the CLI edge."""

    def __init__(self, provider):
        self.provider = provider
        self.binary_path = f"/synthetic/{provider}"

    def _path(self):
        return HOME_DIR / (".codex/config.toml" if self.provider == "codex-cli" else ".copilot/mcp-config.json")

    def _read(self):
        path = self._path()
        if not path.exists():
            return {}
        return tomlkit.loads(path.read_text()).unwrap() if path.suffix == ".toml" else json.loads(path.read_text())

    def execute(self, command, args, timeout=30):
        assert command == "mcp", "Only installer MCP operations are simulated"
        key = "mcp_servers" if self.provider == "codex-cli" else "mcpServers"
        doc = self._read()
        servers = doc.setdefault(key, {})
        if args[0] == "list":
            payload = ([{"name": name, **entry} for name, entry in servers.items()]
                       if self.provider == "codex-cli" else {key: servers})
            return SimpleNamespace(exit_code=0, stdout=json.dumps(payload), stderr="")
        assert args[0] == "add"
        separator = args.index("--")
        environment = {}
        index = 1
        while index < separator:
            if args[index] == "--env":
                name, value = args[index + 1].split("=", 1)
                environment[name] = value
                index += 2
            elif args[index] == "--json":
                index += 1
            else:
                server_name = args[index]
                index += 1
        servers[server_name] = {
            "command": args[separator + 1], "args": args[separator + 2:], "env": environment,
        }
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(doc) if path.suffix == ".toml" else json.dumps(doc, indent=2))
        return SimpleNamespace(exit_code=0, stdout="", stderr="")


async def seed():
    # Block all real provider/tmux invocations and all network traffic, even if
    # future changes accidentally reach an unanticipated boundary.
    socket.socket.connect = reject_network
    socket.socket.connect_ex = reject_network
    subprocess.Popen = reject_process
    asyncio.create_subprocess_exec = reject_process
    from app.utils import path_utils
    path_utils.get_managed_settings_file = lambda: HOME_DIR / "absent-managed-settings.json"
    path_utils.get_managed_mcp_config_file = lambda: HOME_DIR / "absent-managed-mcp.json"

    import app.config
    from app.config import settings
    from app.database import engine, init_db
    from app.api.v1.router import router
    from app.services import agent_mail_install_service as installer
    from app.services.agent_bridge import attachments
    from app.services.providers.base import SpawnCommandOptions
    from app.services.providers.pi_cli import PiCliProvider
    from app.services.pi_mail_readiness import integration_path, pi_mail_environment
    from fastapi import FastAPI

    assert Path(app.config.__file__).is_relative_to(SOURCE)
    assert settings.app_version == "3.1.0"
    assert settings.database_url == "sqlite+aiosqlite:///./claude_registry.db"
    assert settings.bridge_attachment_dir == "~/.claude-registry/bridge-attachments"
    assert settings.test_instance is False
    assert not (Path.cwd() / ".env").exists()
    cli = {name: InstallerCLI(name) for name in ("codex-cli", "copilot-cli")}
    installer._codex_executor = lambda: cli["codex-cli"]
    installer._copilot_executor = lambda: cli["copilot-cli"]
    installer._opencode_executor = lambda: SimpleNamespace(binary_path="/synthetic/opencode")
    attachments.discover_agent_sessions = lambda: [{
        "tmux_target": TARGET, "session_name": "upgrade-fixture", "provider": "codex-cli",
    }]
    await init_db()
    # Router-only ASGI transport: no network listener, startup lifecycle,
    # scheduler, launch, pane cleanup, or live-instance contact.
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    headers = {"X-Deck-Operator-Token": "synthetic-upgrade-operator"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture", headers=headers) as client:
        async def request(method, path, **kwargs):
            response = await client.request(method, "/api/v1" + path, **kwargs)
            assert response.is_success, f"{method} {path}: {response.status_code}: {response.text}"
            return response

        async def api(method, path, **kwargs):
            return (await request(method, path, **kwargs)).json()

        await api("PUT", "/config/settings", json={"scope": "user", "settings": {
            "env": {"UPGRADE_FIXTURE_SETTING": "keep this setting"},
        }})
        repository = HOME_DIR / "project"
        repository.mkdir()
        preset = await api("POST", "/agent-teams/presets", json={
            "name": "Pre-upgrade team", "description": "Keep this pre-upgrade team.",
            "slots": [{"display_name": "Builder", "provider": "codex-cli", "repo_path": str(repository)},
                      {"display_name": "Pi", "provider": "pi-cli", "repo_path": str(repository),
                       "launch_options": {"platform": "openrouter"}}],
        })
        await api("POST", f"/agent-teams/presets/{preset['id']}/github-scopes", json={
            "repo_owner": "fixture", "repo_name": "upgrade", "repo_path": str(repository), "enabled": False,
        })
        registrations = []
        for name, provider in (("a", "codex-cli"), ("b", "pi-cli")):
            directory = repository / name
            directory.mkdir()
            registrations.append(await api("POST", "/agent-mail/agent/register", json={
                "source": "mcp", "provider": provider, "cwd": str(directory), "session_key": f"upgrade-fixture-{name}",
            }))
        await api("POST", "/agent-mail/messages", headers={
            "X-Deck-Session-Token": registrations[0]["capability_token"],
        }, json={"recipient_member_id": registrations[1]["member"]["id"],
                 "subject": "Upgrade baseline", "body_markdown": "Keep this pre-upgrade mail history."})

        installed = []
        for slug, provider in (("claude-code", "claude-code"), ("codex", "codex-cli"),
                               ("copilot", "copilot-cli"), ("opencode", "opencode-cli")):
            await api("POST", f"/agent-mail/install/{slug}/apply", json={"confirmed": True})
            installed.append(provider)
        custom = installer.opencode_config_path()
        config = json.loads(custom.read_text())
        config["mcp"][installer.MCP_SERVER_NAME]["environment"]["CLAUDE_DECK_URL"] = "http://127.0.0.1:43219/custom"
        custom.write_text(json.dumps(config, indent=2))

        backup = await api("POST", "/backup/create", json={"name": "pre-upgrade-restorable", "scope": "user"})
        listed = await api("GET", "/backup/list")
        download = await request("GET", f"/backup/{backup['id']}/download")
        valid = await api("POST", f"/backup/{backup['id']}/validate")
        # Prove real restoration by changing a setting before calling restore.
        settings_file = HOME_DIR / ".claude/settings.json"
        original_settings = settings_file.read_bytes()
        await api("PUT", "/config/settings", json={"scope": "user", "settings": {
            "env": {"UPGRADE_FIXTURE_SETTING": "changed before restore"},
        }})
        assert json.loads(settings_file.read_text())["env"]["UPGRADE_FIXTURE_SETTING"] == "changed before restore"
        restored = await api("POST", f"/backup/{backup['id']}/restore", json={"install_dependencies": False})
        assert settings_file.read_bytes() == original_settings
        backup_checks = {
            "listed": any(row["id"] == backup["id"] for row in listed["backups"]),
            "download_sha256": hashlib.sha256(download.content).hexdigest(),
            "file_path": backup["file_path"], "valid": valid["valid"], "restored": restored["success"],
            "restored_setting": json.loads(settings_file.read_text())["env"]["UPGRADE_FIXTURE_SETTING"],
        }

        now = datetime.utcnow()
        real_clock = attachments._utcnow
        try:
            for age, name in ((timedelta(days=10), "expired"), (timedelta(), "live")):
                created = now - age
                attachments._utcnow = lambda: created
                token = await api("GET", "/agent-bridge/token", params={"target": TARGET, "purpose": "attachment"})
                await api("POST", f"/agent-bridge/sessions/{TARGET}/attachments",
                          headers={"X-Claude-Deck-Terminal-Token": token["token"]},
                          files={"file": (f"{name}.png", b"\x89PNG\r\n\x1a\n" + name.encode() + b"\0" * 32, "image/png")})
        finally:
            attachments._utcnow = real_clock

        # Checkpoint everything so only a deliberate final API transaction is
        # WAL-only. Keep a connection open so shutdown cannot erase the set.
        database = Path.cwd() / "claude_registry.db"
        keeper = sqlite3.connect(database)
        keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await api("POST", "/agent-teams/presets", json={"name": "WAL-only team", "description": "Committed only in WAL"})
        exported = ROOT / "wal-export"
        exported.mkdir()
        for suffix in ("", "-wal", "-shm"):
            shutil.copyfile(Path(str(database) + suffix), exported / (database.name + suffix))
        await engine.dispose()
        keeper.close()
        for suffix in ("", "-wal", "-shm"):
            shutil.copyfile(exported / (database.name + suffix), Path(str(database) + suffix))
        shutil.rmtree(exported)

    # Derive both key literals from the archived frontend. Keep their real
    # storage namespaces: sessionStorage for the operator, localStorage for provider.
    operator_source = (SOURCE / "frontend/src/features/agent-teams/operatorAuth.ts").read_text()
    provider_source = (SOURCE / "frontend/src/contexts/ProviderContext.tsx").read_text()
    operator_key = re.search(r"OPERATOR_TOKEN_KEY = '([^']+)'", operator_source).group(1)
    provider_key = re.search(r"STORAGE_KEY = '([^']+)'", provider_source).group(1)
    assert "window.sessionStorage" in operator_source
    assert "window.localStorage" in provider_source
    browser = {"sessionStorage": {operator_key: "synthetic-upgrade-operator"}, "localStorage": {provider_key: "pi-cli"}}
    (ROOT / "browser-storage.json").write_text(json.dumps(browser, indent=2))
    command = PiCliProvider().build_spawn_command(SpawnCommandOptions(directory=str(repository), platform="openrouter"))
    extension = integration_path() / "extension.ts"
    assert extension.is_file() and (integration_path() / "manifest.ts").is_file()
    command[1:1] = ["--extension", str(extension)]
    manifest = {
        "source_sha": sys.argv[2], "version": settings.app_version,
        "imported_app": str(Path(sys.modules["app.config"].__file__)),
        "preset_id": preset["id"], "snapshot_time": now.isoformat(),
        "installed_providers": installed, "backup_reader_checks": backup_checks,
        "pi_command": command, "pi_environment": pi_mail_environment(),
        "limits": "Provider CLIs/tmux and the Pi runtime are simulated; no real launch, upgrade, or power-loss proof.",
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(seed())
