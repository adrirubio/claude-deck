"""Launch prerequisite agreement without host configuration or provider processes."""
import ast
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.provider_readiness_service import agent_mail_ready_reason, configuration_readiness
from app.services import provider_operations_service as ops
from app.services.providers import get_providers

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def configured(**changes):
    values = dict(
        claude_code_mcp_installed=True, claude_code_hooks_missing=[],
        codex_cli_available=True, codex_mcp_installed=True, codex_hooks_missing=[],
        copilot_cli_available=True, copilot_mcp_installed=True, copilot_hooks_missing=[],
        opencode_cli_available=True, opencode_mcp_installed=True, opencode_plugin_events_missing=[],
        pi_mail_ready=True, pi_mail_reason=None,
    )
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("provider", get_providers(), ids=lambda p: p.id)
@pytest.mark.parametrize("installed", [True, False, None])
def test_binary_and_shared_mail_agreement(provider, installed):
    status = configured()
    readiness = configuration_readiness(provider.id, provider.display_name, installed, status)
    assert (readiness.state == "ready") == (installed is True and agent_mail_ready_reason(provider.id, status) is None)
    assert readiness.state == ("ready" if installed else "blocked" if installed is False else "unknown")


@pytest.mark.parametrize("provider,key", [
    ("claude-code", "claude_code_mcp_installed"), ("codex-cli", "codex_mcp_installed"),
    ("copilot-cli", "copilot_mcp_installed"), ("opencode-cli", "opencode_mcp_installed"),
    ("pi-cli", "pi_mail_ready"),
])
def test_missing_positive_mail_evidence_blocks_launch_without_verified_absence(provider, key):
    status = configured(**{key: False})
    reason = agent_mail_ready_reason(provider, status)
    assert reason
    readiness = configuration_readiness(provider, provider, True, status)
    assert readiness.state == "blocked"
    assert readiness.checks[1].state == "unknown"
    assert "failed probe" in readiness.checks[1].reason


def test_pi_private_wrapper_and_unknown_default_preserved():
    from app.services.agent_team_service import AgentTeamService

    status = configured(pi_mail_ready=False, pi_mail_reason="synthetic-private-diagnostic")
    service = AgentTeamService()
    assert service._agent_mail_ready_reason("pi-cli", status) == "synthetic-private-diagnostic"
    assert agent_mail_ready_reason("unknown", status) is None
    assert "synthetic-private" not in configuration_readiness("pi-cli", "Pi", True, status).model_dump_json()


@pytest.mark.parametrize("provider", get_providers(), ids=lambda p: p.id)
def test_failed_snapshot_is_unknown_not_credentials_or_ready(provider):
    report = ops.catalog(provider, ops.Snapshot({provider.id: True}, None, NOW, NOW, 0, True))
    assert report.readiness.configuration.state == "unknown"
    assert report.readiness.credentials.state == "unknown"
    assert report.readiness.probe_state == "failed"
    assert report.readiness.session.state == "unknown"


@pytest.mark.asyncio
async def test_pending_worker_is_single_flight_after_request_timeout(monkeypatch):
    future = Future()
    class Executor:
        calls = 0
        def submit(self, _):
            self.calls += 1
            return future
    executor = Executor()
    monkeypatch.setattr(ops, "_executor", executor)
    monkeypatch.setattr(ops, "_future", None)
    monkeypatch.setattr(ops, "WAIT_SECONDS", .001)
    assert await ops.readiness_snapshot() is None
    assert await ops.readiness_snapshot() is None
    assert executor.calls == 1
    assert not future.cancelled()
    future.set_result(ops.Snapshot({}, configured(), NOW, NOW, ops.time.monotonic()))
    assert await ops.readiness_snapshot() is future.result()
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_expired_snapshot_starts_one_refresh(monkeypatch):
    old = Future()
    old.set_result(ops.Snapshot({}, None, NOW, NOW, -1000, True))
    fresh = Future()
    fresh.set_result(ops.Snapshot({}, configured(), NOW, NOW, ops.time.monotonic()))
    class Executor:
        calls = 0
        def submit(self, _):
            self.calls += 1
            return fresh
    executor = Executor()
    monkeypatch.setattr(ops, "_future", old)
    monkeypatch.setattr(ops, "_executor", executor)
    assert await ops.readiness_snapshot() is fresh.result()
    assert await ops.readiness_snapshot() is fresh.result()
    assert executor.calls == 1


def test_shared_reason_preserves_all_original_decisions():
    # Reviewed source is immutable; execute only the old pure decision tree.
    import subprocess
    source = subprocess.run(["git", "show", "667841e7e71ea4c1007a4124273bb7c3a6b04869:backend/app/services/agent_team_service.py"], capture_output=True, text=True, check=True).stdout
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == "_agent_mail_ready_reason")
    module = ast.Module(body=[node], type_ignores=[])
    namespace = {"Any": object}
    exec(compile(module, "reviewed-pure-launch-readiness", "exec"), namespace)
    original = namespace["_agent_mail_ready_reason"]
    cases = [configured(), configured(pi_mail_ready=False, pi_mail_reason="fixture reason")]
    for key, value in vars(configured()).items():
        if isinstance(value, bool):
            cases.append(configured(**{key: False}))
        elif isinstance(value, list):
            cases.append(configured(**{key: ["missing"]}))
    for provider in [p.id for p in get_providers()] + ["unknown"]:
        for status in cases:
            assert agent_mail_ready_reason(provider, status) == original(None, provider, status)


@pytest.mark.parametrize("key,value", [("codex_mcp_installed", "true"), ("codex_cli_available", 1), ("codex_hooks_missing", None)])
def test_malformed_legacy_snapshot_remains_unknown(key, value):
    result = configuration_readiness("codex-cli", "Codex", True, configured(**{key: value}))
    assert result.state == "unknown"
    assert result.checks[1].code == "mail_check_unavailable"


def test_snapshot_exception_has_no_private_projection(monkeypatch):
    def broken(*_, **kwargs):
        raise RuntimeError("synthetic-private-error")
    monkeypatch.setattr(ops, "_observe_install_status", broken)
    monkeypatch.setattr(ops.shutil, "which", lambda _: "/synthetic-private-binary")
    result = ops._collect_snapshot()
    assert result.failed and result.install_status is None
    for provider in get_providers():
        assert "synthetic-private" not in ops.catalog(provider, result).model_dump_json()


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b"[]", b"x" * 8193])
def test_malformed_observer_payload_is_unknown(monkeypatch, payload):
    monkeypatch.setattr(ops.shutil, "which", lambda _: None)
    monkeypatch.setattr(ops, "_observe_install_status", lambda: payload)
    result = ops._collect_snapshot()
    assert result.failed and result.install_status is None


@pytest.mark.asyncio
@pytest.mark.parametrize("child_pipe", ["inherited", "closed"])
@pytest.mark.parametrize("failure", ["deadline", "nonzero_exit"])
async def test_observer_failure_cleans_descendants_before_shared_refresh(monkeypatch, tmp_path, child_pipe, failure):
    # Only inert Python processes and temporary markers; never installed CLIs.
    import asyncio
    import json
    import os
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    started, completed = tmp_path / "child-started", tmp_path / "child-completed"
    child = (
        "import os,time; from pathlib import Path; "
        f"Path({str(started)!r}).write_text(str(os.getpid())); "
        f"time.sleep(1.2); Path({str(completed)!r}).write_text('completed')"
    )
    redirects = ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if child_pipe == "closed" else ""
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]{redirects}); "
        + ("time.sleep(3)" if failure == "deadline" else "time.sleep(.15); sys.exit(1)")
    )
    real_popen = subprocess.Popen
    observers = []

    def child_exists():
        return started.exists() and Path(f"/proc/{int(started.read_text())}").exists()

    def fixture_popen(command, **kwargs):
        assert command[1:] == ["-m", "app.services.provider_operations_service", "--snapshot"]
        assert kwargs["start_new_session"] is True
        if observers:
            assert observers[0].returncode is not None
            assert not child_exists(), "Refresh overlapped previous probe descendant"
        program = parent if not observers else f"print({json.dumps({k: None for k in ops.INSTALL_FIELDS})!r})"
        # Exercise the exact cleanup supervisor without invoking its real probes.
        supervisor = (
            "import sys; from app.services import provider_operations_service as ops; "
            f"sys.stdout.buffer.write(ops._supervised_observation([sys.executable,'-c',{program!r}]))"
        )
        observer = real_popen([sys.executable, "-c", supervisor], **kwargs)
        observers.append(observer)
        return observer

    monkeypatch.setattr(ops.subprocess, "Popen", fixture_popen)
    monkeypatch.setattr(ops, "get_providers", lambda: [])
    monkeypatch.setattr(ops, "AGGREGATE_SECONDS", .7)
    monkeypatch.setattr(ops, "WAIT_SECONDS", .01)
    monkeypatch.setattr(ops, "_future", None)
    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(ops, "_executor", executor)
        assert await ops.readiness_snapshot() is None
        assert await ops.readiness_snapshot() is None
        first = await asyncio.wrap_future(ops._future)
        assert first.failed and started.exists()
        assert observers[0].returncode is not None and not child_exists()
        assert len(observers) == 1 and not completed.exists()
        monkeypatch.setattr(ops, "TTL_SECONDS", 0)
        await ops.readiness_snapshot()
        second = await asyncio.wrap_future(ops._future)
        assert not second.failed and len(observers) == 2
        await asyncio.sleep(1.3)  # Beyond the child's completion marker deadline.
        assert not completed.exists() and not child_exists()
    assert os.getpgrp() != observers[0].pid  # The test runner's group was untouched.


@pytest.mark.asyncio
async def test_observer_allowlist_never_returns_missing_hook_or_pi_diagnostic(monkeypatch):
    from app.services import agent_mail_install_service as install
    async def observe():
        return configured(pi_mail_reason="synthetic-private", codex_hooks_missing=["synthetic-private"])
    monkeypatch.setattr(install, "get_install_status", observe)
    payload = await ops._snapshot_payload()
    assert set(payload) == set(ops.INSTALL_FIELDS)
    assert payload["codex_hooks_missing"] == ["missing"]
    assert "synthetic-private" not in str(payload)


@pytest.mark.parametrize("provider,mail_key", [("claude-code","claude_code_mcp_installed"),("codex-cli","codex_mcp_installed"),("copilot-cli","copilot_mcp_installed"),("opencode-cli","opencode_mcp_installed"),("pi-cli","pi_mail_ready")])
@pytest.mark.parametrize("installed,mail", [(True,True),(True,False),(False,True),(False,False)])
def test_real_launch_plan_configuration_agrees_for_same_snapshot(monkeypatch, provider, mail_key, installed, mail):
    from app.services import agent_team_service as teams
    service = teams.AgentTeamService()
    fake = SimpleNamespace(display_name=provider, get_status=lambda: {"installed":installed})
    monkeypatch.setattr(teams, "get_provider", lambda _: fake)
    monkeypatch.setattr(service, "_slot_launch_warnings", lambda *_: [])
    monkeypatch.setattr(service, "_validate_spawn_options", lambda *_: None)
    slot = SimpleNamespace(id=2, display_name="Synthetic slot", provider=provider, enabled=True, repo_id="fixture",repo_path="/synthetic",repo_name="fixture",launch_options={})
    status = configured(**{mail_key:mail})
    launch = service._plan_slot(slot, None, status)
    readiness = configuration_readiness(provider, provider, installed, status)
    assert (launch.status == "ready") == (readiness.state == "ready")
    if not installed:
        assert launch.block_code == "provider_unavailable"
    elif not mail:
        assert launch.block_code == "agent_mail_not_configured"
