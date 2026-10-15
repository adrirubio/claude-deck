"""Settings writes need the Director key when one is configured.

These routers change the controller's own harness settings. Several of those
settings are commands that run (hooks, MCP servers, the status line), so a
write is as strong as running a command as the controller. When a Director
key is configured, every write on them needs it; reads stay open. Without a
configured key (a single-user install), they stay open as before.
"""
import importlib
import re

import httpx
import pytest
import pytest_asyncio
from fastapi.routing import APIRoute

from app.config import settings
from app.main import app

KEY = "director-key-for-tests"
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
GUARDED_MODULES = [
    "agents", "backup", "cli", "codex_config", "commands", "config", "hooks", "mcp",
    "memory", "output_styles", "permissions", "plugins", "projects", "providers",
    "statusline", "usage",
]
# Prefixes given to include_router in app/api/v1/router.py.
INCLUDE_PREFIXES = {"mcp": "/mcp"}


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def _routes(write: bool) -> list[tuple[str, str]]:
    """Read each module's own router: FastAPI 0.143 no longer flattens app.routes."""
    found = []
    for name in GUARDED_MODULES:
        module = importlib.import_module(f"app.api.v1.{name}")
        prefix = settings.api_v1_prefix + INCLUDE_PREFIXES.get(name, "")
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in sorted(route.methods):
                if (method not in READ_METHODS) == write:
                    found.append((method, _concrete(prefix + route.path)))
    return found


# Agent Mail install routes write the same native settings (hooks, MCP servers)
# but live on the Mail router, whose other writes must stay open to agents.
MAIL_INSTALL_WRITES = [
    ("POST", f"{settings.api_v1_prefix}/agent-mail/install/{harness}/{action}")
    for harness in ("claude-code", "codex", "copilot", "opencode", "muse")
    for action in ("apply", "uninstall")
]
WRITES = _routes(write=True) + MAIL_INSTALL_WRITES


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    # A guard check must not read the developer's installed MCP servers.
    monkeypatch.setenv("HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_the_guarded_routers_have_writes():
    assert len(WRITES) > 50, WRITES
    assert ("POST", "/api/v1/mcp/servers/x/test") in WRITES
    assert ("POST", "/api/v1/hooks") in WRITES


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", WRITES)
async def test_a_write_without_the_key_is_refused(client, monkeypatch, method, path):
    monkeypatch.setattr(settings, "operator_token", KEY)

    missing = await client.request(method, path)
    wrong = await client.request(method, path, headers={"X-Deck-Operator-Token": "wrong"})

    assert (missing.status_code, missing.json()["detail"]) == (401, "operator_token_required")
    assert (wrong.status_code, wrong.json()["detail"]) == (401, "operator_token_invalid")


@pytest.mark.asyncio
async def test_a_write_with_the_key_reaches_the_route(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", KEY)

    response = await client.post(
        "/api/v1/config/validate-settings",
        headers={"X-Deck-Operator-Token": KEY},
        json={"settings": {}},
    )

    assert response.status_code not in {401, 503}, response.text


@pytest.mark.asyncio
async def test_reads_stay_open_when_a_key_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", KEY)

    response = await client.get("/api/v1/mcp/servers")

    assert response.status_code not in {401, 503}, response.text


@pytest.mark.asyncio
async def test_writes_stay_open_without_a_configured_key(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_token", "")

    response = await client.post("/api/v1/config/validate-settings", json={"settings": {}})

    assert response.status_code not in {401, 503}, response.text
