"""Credential-free provider CLI boundary and ordinary-startup upgrade fixture.

The old files come from the frozen v3.1 installer, not this implementation.
Only the external CLI edge and unrelated autonomous services are simulated.
"""
import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import tomlkit

from .v31_fixture import build_v31_install


OLD = "claude-deck-mail"
NEW = "albiex-synth-city-mail"
BACKEND = Path(__file__).resolve().parents[2]
# Muse shipped after v3.1. This immutable pre-rename pin supplies its genuine
# installer only; the frozen four-provider/database fixture remains unchanged.
MUSE_SOURCE_SHA = "872fc08e7f92b0c10f86dedfe5918ab07de83e7f"


def provision(root):
    install = build_v31_install(root)
    archive = subprocess.check_output(["git", "archive", MUSE_SOURCE_SHA, "backend/app", "backend/mcp_shim"], cwd=BACKEND.parent)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(install.source, filter="data")
    env = {"HOME": str(install.home), "PATH": str(install.root / "no-external-binaries"),
           "PYTHONPATH": str(install.app_dir), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
    seeded = subprocess.run([sys.executable, "-c", '''
import asyncio
from unittest.mock import AsyncMock
from app.services import agent_mail_install_service as installer
installer.get_install_status = AsyncMock(return_value=None)
installer.muse_cli_available = lambda: True
assert installer.MCP_SERVER_NAME == 'claude-deck-mail'
asyncio.run(installer.apply_muse_install(None))
'''], cwd=install.app_dir, env=env, capture_output=True, text=True, timeout=30)
    assert seeded.returncode == 0, seeded.stderr[-3000:]
    for name in ("app", "mcp_shim"):
        shutil.rmtree(install.app_dir / name)
        shutil.copytree(BACKEND / name, install.app_dir / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    sandbox = install.root / "no-network"
    sandbox.mkdir()
    (sandbox / "sitecustomize.py").write_text('''
import os, socket
from pathlib import Path
def reject(*args, **kwargs):
    with (Path(os.environ['PROVIDER_TEST_ROOT'])/'network-attempts').open('a') as file:
        file.write('attempt\\n')
    raise OSError('Provider upgrade fixture forbids network sockets')
socket.socket.connect = reject
socket.socket.connect_ex = reject
''')
    return install


class FileCLI:
    """Model successful/failed CLI operations against the actual config files."""

    def __init__(self, provider):
        self.provider = provider
        self.binary_path = "/synthetic/" + provider

    def execute(self, command, args, timeout=30, env=None):
        assert command == "mcp"
        home = Path((env or os.environ)["HOME"])
        codex = self.provider == "codex-cli"
        path = (Path((env or os.environ).get("CODEX_HOME", home / ".codex")) / "config.toml"
                if codex else Path((env or os.environ).get("COPILOT_HOME", home / ".copilot")) / "mcp-config.json")
        key = "mcp_servers" if codex else "mcpServers"
        doc = (tomlkit.parse(path.read_text()) if codex else json.loads(path.read_text())) if path.exists() else {}
        servers = doc.setdefault(key, {})
        operation = args[0]
        audit = Path(os.environ["PROVIDER_TEST_ROOT"]) / "cli-operations.jsonl"
        with audit.open("a") as stream:
            stream.write(json.dumps([self.provider, operation]) + "\n")
        failure = os.environ.get("PROVIDER_TEST_CLI_FAIL")
        if failure == operation:
            return SimpleNamespace(exit_code=1, stdout="", stderr="synthetic CLI failure")
        if operation == "list":
            plain = doc.unwrap() if codex else doc
            entries = plain.get(key, {})
            payload = ([{"name": name, **entry} for name, entry in entries.items()]
                       if codex else {key: entries})
            return SimpleNamespace(exit_code=0, stdout=json.dumps(payload), stderr="")
        if operation == "remove":
            servers.pop(args[1], None)
        else:
            assert operation == "add"
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
                    server = args[index]
                    index += 1
            servers[server] = {"command": args[separator + 1], "args": args[separator + 2:], "env": environment}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tomlkit.dumps(doc) if codex else json.dumps(doc, indent=2))
        return SimpleNamespace(exit_code=0, stdout="", stderr="")


async def startup(test_instance=False):
    import app.main as main
    from app.database import engine
    from app.services import agent_mail_install_service as installer
    from app.services.cc_bridge import pty_relay
    main.settings.test_instance = test_instance
    installer._codex_executor = lambda: FileCLI("codex-cli")
    installer._copilot_executor = lambda: FileCLI("copilot-cli")
    installer._opencode_executor = lambda: SimpleNamespace(binary_path="/synthetic/opencode")
    with patch.object(main.github_dispatch_scheduler, "start", new=AsyncMock()), \
            patch.object(main.github_dispatch_scheduler, "shutdown", new=AsyncMock()), \
            patch.object(main.test_instance_campaign_poller, "start", new=AsyncMock()), \
            patch.object(main.test_instance_campaign_poller, "shutdown", new=AsyncMock()), \
            patch.object(main.agent_bridge_attachment_service, "cleanup_expired", new=AsyncMock()), \
            patch.object(pty_relay, "cleanup_orphaned_relays"), \
            patch.object(pty_relay, "close_all_relays", new=AsyncMock()):
        async with main.lifespan(main.app):
            pass
    await engine.dispose()


def run_startup(install, *, test_instance=False, environment=None, code=""):
    env = {"HOME": str(install.home), "PATH": "/usr/local/bin:/usr/bin:/bin",
           "PYTHONPATH": str(install.root / "no-network") + ":" + str(install.app_dir) + ":" + str(BACKEND), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "OPERATOR_TOKEN": "synthetic-upgrade-operator",
           "PROVIDER_TEST_ROOT": str(install.root)} | (environment or {})
    script = ("import asyncio\nfrom tests.upgrade.provider_upgrade_harness import startup\n"
              + code + "\nasyncio.run(startup(" + repr(test_instance) + "))\n")
    return subprocess.run([sys.executable, "-c", script], cwd=install.app_dir,
                          env=env, capture_output=True, text=True, timeout=90)


def config_file(install, provider):
    relative, key = {
        "claude-code": (".claude.json", "mcpServers"),
        "muse-cli": (".config/muse/settings.json", "mcpServers"),
        "codex-cli": (".codex/config.toml", "mcp_servers"),
        "copilot-cli": (".copilot/mcp-config.json", "mcpServers"),
        "opencode-cli": (".config/opencode/opencode.json", "mcp"),
    }[provider]
    return install.home / relative, key


def entries(install, provider):
    path, key = config_file(install, provider)
    doc = tomlkit.parse(path.read_text()).unwrap() if path.suffix == ".toml" else json.loads(path.read_text())
    return doc.get(key, {})


def customize(install, provider):
    path, key = config_file(install, provider)
    doc = tomlkit.parse(path.read_text()) if path.suffix == ".toml" else json.loads(path.read_text())
    entry = doc[key][OLD]
    environment = entry["environment" if provider == "opencode-cli" else "env"]
    previous = environment["CLAUDE_DECK_URL"]
    url = "http://127.0.0.1:43219/" + provider + "/CLAUDE_DECK_URL?keep=1"
    environment["CLAUDE_DECK_URL"] = url
    environment["PRIVATE_SETTING"] = "synthetic-unpublished-value"
    entry["upgrade_custom"] = {"keep": False}
    path.write_text(tomlkit.dumps(doc) if path.suffix == ".toml" else json.dumps(doc))
    hooks = {"claude-code": ".claude/settings.json", "muse-cli": ".config/muse/settings.json",
             "codex-cli": ".codex/hooks.json", "copilot-cli": ".copilot/hooks/claude-deck-mail.json"}
    if provider in hooks:
        target = install.home / hooks[provider]
        # This is an operator customization of genuine installer output, not
        # hand-authored ownership evidence.
        target.write_text(target.read_text().replace(previous, url))
    return url
