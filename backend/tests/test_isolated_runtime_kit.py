"""The isolated runtime kit (#902): one namespace for a provider live check.

These tests run the real kit script. The end-to-end test starts an isolated
backend, a stub model provider and a fake provider CLI inside the kit's own
user and network namespaces, and proves registration, binding, isolation and
cleanup. Nothing here is skipped: a host that can't run the kit fails loudly,
because the kit is the evidence path for every harness live check.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "scripts" / "isolated-runtime-kit.sh"
FAKE_CLI = REPO / "scripts" / "runtime-kit" / "fake_cli.sh"
HOST_NET = os.readlink("/proc/self/ns/net")


def _env(**extra: str) -> dict[str, str]:
    """A caller environment without any Synth City URL or Mail credential."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("SYNTH_CITY_")}
    env.update(extra)
    return env


def _kit(*args: str, env: dict[str, str] | None = None, timeout: float = 150) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(KIT), *args], capture_output=True, text=True,
                          env=env or _env(), timeout=timeout)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _root_users(root: Path) -> list[int]:
    """Live processes whose cwd, cmdline or environment names the kit root."""
    needle = str(root).encode()
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            cwd = os.readlink(entry / "cwd").encode()
            blob = (entry / "cmdline").read_bytes() + (entry / "environ").read_bytes()
        except OSError:
            continue
        if cwd.startswith(needle) or needle in blob:
            found.append(int(entry.name))
    return found


def test_host_provides_what_the_kit_needs():
    # Report the missing piece by name instead of failing deep inside the kit.
    for tool in ("bash", "tmux", "unshare", "nsenter", "ip", "timeout", "setsid"):
        assert shutil.which(tool), f"{tool} is required by the isolated runtime kit"
    probe = subprocess.run(["unshare", "--user", "--map-root-user", "--net", "true"],
                           capture_output=True, text=True, timeout=10)
    assert probe.returncode == 0, f"unprivileged user and network namespaces are refused: {probe.stderr.strip()}"


@pytest.fixture
def kit_root(tmp_path):
    root = tmp_path / "kit"
    yield root
    if (root / ".deck-runtime-kit").exists():
        _kit("down", "--root", str(root), timeout=60)


def test_fake_provider_runs_through_the_kit_end_to_end(kit_root):
    up = _kit("up", "--root", str(kit_root), "--provider", "codex-cli", "--cli", str(FAKE_CLI))
    assert up.returncode == 0, up.stderr
    summary = json.loads(up.stdout.strip().splitlines()[-1])

    # Isolation: its own network namespace, loopback only, the caller's uid.
    assert summary["net_namespace"] != HOST_NET
    assert summary["links"] == ["lo"]
    assert summary["uid"] == os.getuid() and summary["gid"] == os.getgid()

    # The real launch wrote the pane binding, and the fake CLI registered from that pane.
    registration = summary["registration"]
    assert registration["provider"] == "codex-cli"
    assert registration["team_slot_id"] == summary["slot_id"]
    assert registration["bound_pane_pid"] == summary["pane_pid"]
    assert summary["pane_command"] == "codex"
    assert summary["stub_requests"] >= 1

    status = _kit("status", "--root", str(kit_root))
    assert status.returncode == 0, status.stderr
    evidence = kit_root / "evidence"
    manifest = (evidence / "MANIFEST.sha256").read_text()
    for name in ("namespaces.json", "links.txt", "processes.txt", "pane.json", "registration.json",
                 "environment-names.json", "stub-requests.jsonl"):
        assert (evidence / name).is_file() and name in manifest
    # Every kit process runs with the allowlisted environment: names only, no credentials.
    names = json.loads((evidence / "environment-names.json").read_text())
    assert names and all(not key.startswith(("GITHUB_", "ANTHROPIC_", "OPENAI_")) for proc in names.values()
                         for key in proc)
    # Tokens never reach the printed output or the evidence.
    for text in (up.stdout, up.stderr, status.stdout, *(p.read_text() for p in evidence.iterdir())):
        assert "e2e-director-key" not in text and "runtime-kit-operator" not in text

    inside = _kit("exec", "--root", str(kit_root), "--", "sh", "-c", 'readlink /proc/self/ns/net; id -u')
    assert inside.returncode == 0, inside.stderr
    assert inside.stdout.split() == [summary["net_namespace"], str(os.getuid())]

    pids = [int(pid) for pid in summary["pids"].values()]
    down = _kit("down", "--root", str(kit_root))
    assert down.returncode == 0, down.stderr
    assert not kit_root.exists()
    assert not [pid for pid in pids if _alive(pid)]
    assert not _root_users(kit_root)


@pytest.mark.parametrize("variable", ["SYNTH_CITY_URL", "SYNTH_CITY_SESSION_TOKEN"])
def test_kit_refuses_a_foreign_synth_city_or_mail_credential(tmp_path, variable):
    result = _kit("up", "--root", str(tmp_path / "kit"), "--provider", "codex-cli", "--cli", str(FAKE_CLI),
                  env=_env(**{variable: "http://127.0.0.1:8011" if variable.endswith("URL") else "x"}))
    assert result.returncode == 2 and "refused" in result.stderr
    assert not (tmp_path / "kit" / "state").exists()


def test_kit_refuses_a_root_it_does_not_own(tmp_path):
    root = tmp_path / "kit"
    root.mkdir()
    (root / "someone-else").write_text("x")
    result = _kit("up", "--root", str(root), "--provider", "codex-cli", "--cli", str(FAKE_CLI))
    assert result.returncode == 2 and "refused" in result.stderr
    assert (root / "someone-else").exists()


@pytest.mark.parametrize("fault", ["uid_mismatch", "join_mismatch"])
def test_kit_preflight_fails_closed_before_the_backend_starts(kit_root, fault):
    result = _kit("up", "--root", str(kit_root), "--provider", "codex-cli", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT=fault))
    assert result.returncode == 2 and "refused" in result.stderr
    assert "backend" not in json.loads((kit_root / "state" / "started.json").read_text())
    assert not _root_users(kit_root)


def test_kit_refuses_to_enter_or_signal_a_reused_pid(kit_root):
    up = _kit("up", "--root", str(kit_root), "--provider", "codex-cli", "--cli", str(FAKE_CLI))
    assert up.returncode == 0, up.stderr
    state = kit_root / "state" / "processes.json"
    processes = json.loads(state.read_text())
    real = dict(processes["inner"])
    processes["inner"]["start"] = str(int(real["start"]) + 1)  # as if the pid had been reused
    state.write_text(json.dumps(processes))
    refused = _kit("exec", "--root", str(kit_root), "--", "true")
    assert refused.returncode == 2 and "refused" in refused.stderr
    processes["inner"] = real
    state.write_text(json.dumps(processes))


def test_kit_up_has_a_finite_deadline(kit_root):
    started = time.monotonic()
    result = _kit("up", "--root", str(kit_root), "--provider", "codex-cli", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT="no_registration", RUNTIME_KIT_UP_DEADLINE="20"))
    assert result.returncode != 0 and "deadline" in result.stderr
    assert time.monotonic() - started < 60
    assert not _root_users(kit_root)
