"""T-E1/T-P1: new environment inputs, no legacy reads, names-only startup warning."""
import importlib
import importlib.util
import os
import subprocess
import sys
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def clean_product_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("CLAUDE_DECK_", "SYNTH_CITY_")):
            monkeypatch.delenv(key)


class LegacyValuesForbidden(Mapping):
    """Iteration exposes names; retrieving an old value is a contract failure."""

    def __init__(self, source):
        self.source = dict(source)

    def __iter__(self):
        return iter(self.source)

    def __len__(self):
        return len(self.source)

    def __getitem__(self, key):
        if key.startswith("CLAUDE_DECK_"):
            raise AssertionError("A legacy environment value was read")
        return self.source[key]


def identity_service(monkeypatch):
    service = importlib.import_module("app.services.instance_identity")
    service.get_instance_identity.cache_clear()
    monkeypatch.setattr(service.socket, "gethostname", lambda: "rename-fixture.local")
    return service


def load_shim():
    spec = importlib.util.spec_from_file_location("environment_contract_shim", ROOT / "backend/mcp_shim/agent_mail_server.py")
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    return shim


def test_t_e1_old_group_c_identity_values_are_not_even_read(monkeypatch):
    service = identity_service(monkeypatch)
    baseline = service.get_instance_identity()
    service.get_instance_identity.cache_clear()
    environment = dict(os.environ)
    environment.update({"CLAUDE_DECK_INSTANCE_NAME": "legacy-name-secret",
                        "CLAUDE_DECK_INSTANCE_ID": "legacy-id-secret",
                        "CLAUDE_DECK_INSTANCE_ACCENT": "legacy-accent-secret"})
    monkeypatch.setattr(service, "os", SimpleNamespace(getenv=LegacyValuesForbidden(environment).get))
    actual = service.get_instance_identity()
    assert (actual.id, actual.name, actual.accent, actual.name_configured) == (
        baseline.id, baseline.name, baseline.accent, False)
    service.get_instance_identity.cache_clear()


def test_t_e1_new_identity_overrides_work_even_with_unreadable_old_values(monkeypatch):
    service = identity_service(monkeypatch)
    environment = dict(os.environ)
    environment.update({"CLAUDE_DECK_INSTANCE_NAME": "legacy-secret",
                        "CLAUDE_DECK_INSTANCE_ID": "legacy-secret",
                        "CLAUDE_DECK_INSTANCE_ACCENT": "legacy-secret",
                        "SYNTH_CITY_INSTANCE_NAME": "New instance",
                        "SYNTH_CITY_INSTANCE_ID": "new-instance-id",
                        "SYNTH_CITY_INSTANCE_ACCENT": "purple"})
    monkeypatch.setattr(service, "os", SimpleNamespace(getenv=LegacyValuesForbidden(environment).get))
    actual = service.get_instance_identity()
    assert (actual.id, actual.name, actual.accent, actual.name_configured) == (
        "new-instance-id", "New instance", "purple", True)
    service.get_instance_identity.cache_clear()


@pytest.mark.parametrize("legacy", [False, True])
def test_t_e1_shim_reads_only_new_url_and_provider(monkeypatch, legacy):
    prefix = "CLAUDE_DECK_" if legacy else "SYNTH_CITY_"
    monkeypatch.setenv(prefix + "URL", "http://fixture.invalid/custom")
    monkeypatch.setenv(prefix + "PROVIDER", "pi-cli")
    shim = load_shim()
    assert shim.DECK_URL == ("http://127.0.0.1:8000" if legacy else "http://fixture.invalid/custom")
    assert shim.PROVIDER == ("unknown" if legacy else "pi-cli")


def test_t_e1_old_supervisor_credential_is_not_read_or_sent(monkeypatch):
    shim = load_shim()
    environment = dict(os.environ, CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN="legacy-actor-secret")
    monkeypatch.setattr(shim, "os", SimpleNamespace(environ=LegacyValuesForbidden(environment)))
    monkeypatch.setattr(shim.httpx, "request", lambda *_a, **_k: pytest.fail("Old credential must not make a request"))
    assert shim.synth_city_supervisor_checkin(1, "2030-01-01T00:00:00Z")["error"]["code"] == "supervisor_actor_credential_missing"


def test_t_e1_new_supervisor_credential_is_used_and_redacted(monkeypatch):
    shim = load_shim()
    monkeypatch.setenv("SYNTH_CITY_EXTERNAL_ACTOR_TOKEN", "new-actor-secret")
    monkeypatch.setenv("CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN", "old-actor-secret")
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(is_success=True, json=lambda: {"note": "new-actor-secret"})
    monkeypatch.setattr(shim.httpx, "request", request)
    assert shim.synth_city_supervisor_checkin(1, "2030-01-01T00:00:00Z") == {"ok": True, "data": {"note": "[redacted]"}}
    assert calls[0]["headers"] == {"Authorization": "Bearer new-actor-secret"}


def test_t_p1_pi_launch_environment_is_exactly_the_new_surface():
    from app.services.pi_mail_readiness import pi_mail_environment
    environment = pi_mail_environment()
    assert set(environment) == {"SYNTH_CITY_MAIL_OPT_IN", "SYNTH_CITY_PROVIDER", "SYNTH_CITY_URL",
                                "SYNTH_CITY_MAIL_PYTHON", "SYNTH_CITY_MAIL_SHIM"}
    assert environment["SYNTH_CITY_MAIL_OPT_IN"] == "1"
    assert environment["SYNTH_CITY_PROVIDER"] == "pi-cli"
    assert Path(environment["SYNTH_CITY_MAIL_PYTHON"]).is_absolute()
    assert Path(environment["SYNTH_CITY_MAIL_SHIM"]).is_file()


@pytest.mark.parametrize("legacy", [False, True])
def test_t_e1_hook_defaults_and_identity_use_new_keys_only(monkeypatch, legacy):
    from mcp_shim import agent_mail_hook as hook
    prefix = "CLAUDE_DECK_" if legacy else "SYNTH_CITY_"
    for suffix, value in {"URL": "http://fixture.invalid/custom", "PROVIDER": "claude-code",
                          "TEAM_PRESET_ID": "71", "TEAM_SLOT_ID": "72"}.items():
        monkeypatch.setenv(prefix + suffix, value)
    monkeypatch.setattr(hook.sys, "argv", ["hook", "--event", "session-start"])
    monkeypatch.setattr(hook, "_read_payload", lambda: {})
    monkeypatch.setattr(hook, "_write_hook_output", lambda *_args: None)
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {})
    monkeypatch.setattr(hook.httpx, "post", post)
    assert hook.main() == 0
    assert calls[0][0] == ("http://127.0.0.1:8000" if legacy else "http://fixture.invalid/custom") + "/api/v1/agent-mail/hooks/session-start"
    payload = calls[0][1]
    assert payload["provider"] == ("codex-cli" if legacy else "claude-code")
    if legacy:
        assert "team_preset_id" not in payload and "team_slot_id" not in payload
    else:
        assert (payload["team_preset_id"], payload["team_slot_id"]) == (71, 72)


@pytest.mark.parametrize("legacy", [False, True])
def test_t_e1_question_hook_ignores_old_session_marker(legacy):
    prefix = "CLAUDE_DECK_" if legacy else "SYNTH_CITY_"
    result = subprocess.run([sys.executable, str(ROOT / "backend/mcp_shim/team_question_hook.py")],
                            input='{"tool_name":"AskUserQuestion"}', text=True, capture_output=True,
                            env={**os.environ, prefix + "TEAM_SLOT_ID": "71"}, check=True, timeout=5)
    if legacy:
        assert result.stdout == ""
    else:
        import json
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_t_e1_warning_uses_keys_only_once_and_names_the_replacements(monkeypatch, caplog):
    warning = importlib.import_module("mcp_shim.environment_warning")
    warning.warn_legacy_environment.cache_clear()
    environment = dict(os.environ)
    environment.update({"CLAUDE_DECK_INSTANCE_NAME": "forbidden-name-value",
                        "CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN": "forbidden-credential-value",
                        "CLAUDE_DECK_MAIL_TOKEN": "forbidden-synthetic-value"})
    monkeypatch.setattr(warning, "os", SimpleNamespace(environ=LegacyValuesForbidden(environment)))
    try:
        warning.warn_legacy_environment()
        warning.warn_legacy_environment()
        records = [r.getMessage() for r in caplog.records if "CLAUDE_DECK_" in r.getMessage()]
        assert len(records) == 1
        for suffix in ("INSTANCE_NAME", "EXTERNAL_ACTOR_TOKEN", "MAIL_TOKEN"):
            assert "CLAUDE_DECK_" + suffix in records[0]
            assert "SYNTH_CITY_" + suffix in records[0]
        assert "forbidden-" not in records[0]
    finally:
        warning.warn_legacy_environment.cache_clear()


@pytest.mark.parametrize("script,args", [("agent_mail_server.py", []), ("agent_mail_hook.py", ["--help"]),
                                        ("team_question_hook.py", [])])
def test_t_e1_standalone_startup_warns_on_stderr_not_protocol_stdout(script, args):
    environment = dict(os.environ, CLAUDE_DECK_PROVIDER="pi-cli", SYNTH_CITY_PROVIDER="pi-cli",
                       CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN="never-print-this-old-value")
    result = subprocess.run([sys.executable, str(ROOT / "backend/mcp_shim" / script), *args],
                            input="", text=True, capture_output=True, env=environment, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN" in result.stderr
    assert "SYNTH_CITY_EXTERNAL_ACTOR_TOKEN" in result.stderr
    assert "never-print-this-old-value" not in result.stderr + result.stdout
    assert "CLAUDE_DECK_" not in result.stdout


@pytest.mark.asyncio
async def test_t_e1_backend_lifespan_wires_the_warning_once(monkeypatch, caplog):
    main = importlib.import_module("app.main")
    warning = importlib.import_module("mcp_shim.environment_warning")
    warning.warn_legacy_environment.cache_clear()
    monkeypatch.setenv("CLAUDE_DECK_INSTANCE_NAME", "never-print-backend-value")
    @asynccontextmanager
    async def session():
        yield object()
    monkeypatch.setattr(main, "init_db", AsyncMock())
    monkeypatch.setattr(main, "AsyncSessionLocal", session)
    monkeypatch.setattr(main.agent_bridge_attachment_service, "cleanup_expired", AsyncMock())
    monkeypatch.setattr(main.settings, "test_instance", True)
    monkeypatch.setattr(main.test_instance_campaign_poller, "start", AsyncMock())
    monkeypatch.setattr(main.test_instance_campaign_poller, "shutdown", AsyncMock())
    monkeypatch.setattr(main.github_dispatch_scheduler, "shutdown", AsyncMock())
    monkeypatch.setattr("app.services.cc_bridge.pty_relay.close_all_relays", AsyncMock())
    try:
        for _ in range(2):
            async with main.lifespan(main.app):
                pass
        records = [r.getMessage() for r in caplog.records if "CLAUDE_DECK_INSTANCE_NAME" in r.getMessage()]
        assert len(records) == 1
        assert "SYNTH_CITY_INSTANCE_NAME" in records[0]
        assert "never-print-backend-value" not in caplog.text
    finally:
        warning.warn_legacy_environment.cache_clear()
