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
# Caller-session variables that must never reach a process inside the kit.
LEAK_PREFIXES = ("CLAUDE", "ANTHROPIC_", "OPENAI_", "SSH_", "GH_", "SYSTEMD_", "INVOCATION_ID", "JOURNAL_STREAM")


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
    up = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI),
              env=_env(RUNTIME_KIT_CANARY="caller-secret-canary"))
    assert up.returncode == 0, up.stderr
    summary = json.loads(up.stdout.strip().splitlines()[-1])

    # Isolation: its own network namespace, loopback only, the caller's uid.
    assert summary["net_namespace"] != HOST_NET
    assert summary["links"] == ["lo"]
    assert summary["uid"] == os.getuid() and summary["gid"] == os.getgid()

    # The real launch wrote the pane binding, and the fake CLI registered from that pane.
    registration = summary["registration"]
    assert registration["provider"] == "claude-code"
    assert registration["team_slot_id"] == summary["slot_id"]
    assert registration["bound_pane_pid"] == summary["pane_pid"]
    assert summary["pane_command"] == "claude"
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
    assert set(names) == set(summary["pids"])
    leaked = {proc: [key for key in keys if key == "RUNTIME_KIT_CANARY" or key.startswith(LEAK_PREFIXES)]
              for proc, keys in names.items()}
    assert not any(leaked.values()), leaked
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
    result = _kit("up", "--root", str(tmp_path / "kit"), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  env=_env(**{variable: "http://127.0.0.1:8011" if variable.endswith("URL") else "x"}))
    assert result.returncode == 2 and "refused" in result.stderr
    assert not (tmp_path / "kit" / "state").exists()


def test_kit_refuses_a_root_it_does_not_own(tmp_path):
    root = tmp_path / "kit"
    root.mkdir()
    (root / "someone-else").write_text("x")
    result = _kit("up", "--root", str(root), "--provider", "claude-code", "--cli", str(FAKE_CLI))
    assert result.returncode == 2 and "refused" in result.stderr
    assert (root / "someone-else").exists()


@pytest.mark.parametrize("fault", ["uid_mismatch", "join_mismatch"])
def test_kit_preflight_fails_closed_before_the_backend_starts(kit_root, fault):
    result = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT=fault))
    assert result.returncode == 2 and "refused" in result.stderr
    started = json.loads((kit_root / "state" / "processes.json").read_text())
    assert {"launcher", "outer", "inner"} <= set(started) and "backend" not in started
    assert not _root_users(kit_root)


def test_kit_refuses_to_enter_or_signal_a_reused_pid(kit_root):
    up = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI))
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
    result = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT="no_registration", RUNTIME_KIT_UP_DEADLINE="20"))
    assert result.returncode != 0 and "deadline" in result.stderr
    assert time.monotonic() - started < 60
    assert not _root_users(kit_root)


# V1 review 5896490172 (PR #905): destructive steps belong to one validated kit instance,
# cleanup is proved by namespace containment, a retained root is refused, no credential
# appears in any argv, and status fails when its proof is incomplete.
def _up(root, **env):
    up = _kit("up", "--root", str(root), "--provider", "claude-code", "--cli", str(FAKE_CLI), env=_env(**env))
    assert up.returncode == 0, up.stderr
    return json.loads(up.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("state", ["no_instance", "copied_instance", "host_namespace", "forged_namespace"])
def test_down_never_signals_or_deletes_outside_its_own_instance(tmp_path, state):
    root = tmp_path / "kit"
    (root / "state").mkdir(parents=True)
    (root / ".deck-runtime-kit").write_text("")
    # The victim lives in a namespace of its own, so a forged record can name it exactly.
    victim = subprocess.Popen(["unshare", "--user", "--map-root-user", "--net", "sleep", "300"], start_new_session=True)
    time.sleep(0.3)
    start = Path(f"/proc/{victim.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    victim_net = os.readlink(f"/proc/{victim.pid}/ns/net")
    try:
        (root / "state" / "processes.json").write_text(json.dumps({
            "outer": {"pid": victim.pid, "start": start}, "backend": {"pid": victim.pid, "start": start}}))
        here = root.stat()
        record = {"id": "0" * 32, "root_dev": here.st_dev, "root_ino": here.st_ino, "uid": os.getuid(),
                  "net": None, "user": None}
        if state == "copied_instance":  # copied from another root: its directory identity differs
            record["root_ino"] += 1
        elif state == "host_namespace":
            record["net"] = HOST_NET
        elif state == "forged_namespace":  # a real namespace, but no anchor of this instance proves it
            record["net"] = victim_net
        if state != "no_instance":
            path = root / "state" / "instance.json"
            path.write_text(json.dumps(record))
            path.chmod(0o600)
        result = _kit("down", "--root", str(root))
        # Invalid ownership is refused outright; a real but unproved namespace is reported, never signalled.
        expected = ("incomplete", 1) if state == "forged_namespace" else ("refused", 2)
        assert (result.returncode, expected[0] in result.stderr) == (expected[1], True), result.stderr
        assert victim.poll() is None and root.exists()
    finally:
        victim.kill()
        victim.wait()


def test_down_stops_a_detached_process_inside_the_kit_namespace(kit_root):
    _up(kit_root)
    started = _kit("exec", "--root", str(kit_root), "--", "sh", "-c",
                   'cd / && setsid env -i sleep 300 </dev/null >/dev/null 2>&1 & echo $!')
    assert started.returncode == 0, started.stderr
    child = int(started.stdout.split()[-1])
    assert _alive(child)
    down = _kit("down", "--root", str(kit_root))
    assert down.returncode == 0, down.stderr
    assert not _alive(child) and not kit_root.exists()


def test_up_refuses_a_retained_root_before_starting_anything(kit_root):
    _up(kit_root)
    kept = _kit("down", "--root", str(kit_root), "--keep")
    assert kept.returncode == 0, kept.stderr
    before = set(_root_users(kit_root))
    again = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI))
    assert again.returncode == 2 and "refused" in again.stderr
    assert set(_root_users(kit_root)) <= before


def test_an_interrupted_preflight_leaves_no_process(kit_root):
    result = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT="after_anchor_spawn"))
    assert result.returncode != 0
    time.sleep(0.5)
    assert not _root_users(kit_root)


def test_no_credential_ever_appears_in_a_process_argv(kit_root):
    import threading
    seen: set[bytes] = set()
    done = threading.Event()

    def observe():
        while not done.is_set():
            for entry in Path("/proc").iterdir():
                if entry.name.isdigit():
                    try:
                        if entry.stat().st_uid == os.getuid():
                            seen.add((entry / "cmdline").read_bytes())
                    except OSError:
                        pass
            time.sleep(0.01)

    watcher = threading.Thread(target=observe, daemon=True)
    watcher.start()
    try:
        _up(kit_root)
        _kit("status", "--root", str(kit_root))
    finally:
        done.set()
        watcher.join()
    for name in ("run-token", "operator-token"):
        secret = (kit_root / "state" / name).read_text().strip().encode()
        assert secret and not [argv for argv in seen if secret in argv], name


@pytest.mark.parametrize("fault", ["dead_backend", "unhealthy_backend", "dead_cli", "reused_cli", "missing_registration"])
def test_status_fails_when_its_proof_is_incomplete(kit_root, fault):
    import signal
    import sqlite3
    _up(kit_root)
    state = kit_root / "state" / "processes.json"
    processes = json.loads(state.read_text())
    if fault == "dead_backend":
        os.kill(processes["backend"]["pid"], signal.SIGKILL)
    elif fault == "dead_cli":
        os.kill(processes["cli"]["pid"], signal.SIGKILL)
    elif fault == "reused_cli":
        processes["cli"]["start"] = str(int(processes["cli"]["start"]) + 1)
        state.write_text(json.dumps(processes))
    elif fault == "unhealthy_backend":  # alive, but no longer proves it is this run's backend
        token = kit_root / "state" / "run-token"
        token.write_text("0" * 32)
    else:
        with sqlite3.connect(kit_root / "kit.db") as db:
            db.execute("UPDATE mail_agent_sessions SET closed_at = CURRENT_TIMESTAMP")
    time.sleep(0.5)
    result = _kit("status", "--root", str(kit_root))
    assert result.returncode != 0 and ("incomplete" in result.stderr or "refused" in result.stderr), result.stderr
    assert not (kit_root / "evidence" / "MANIFEST.sha256").exists()
