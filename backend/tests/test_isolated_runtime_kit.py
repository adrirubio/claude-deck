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
import stat
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
    env = dict(env or _env())
    if _kit_runtime_skip_reason() is not None:  # not opted in: nothing may launch (Leader 13723)
        env["PATH"] = str(_launch_guard()) + os.pathsep + env.get("PATH", "")
    return subprocess.run(["bash", str(KIT), *args], capture_output=True, text=True, env=env, timeout=timeout)


_GUARD: list[Path] = []


def _launch_guard() -> Path:
    """A private directory whose setsid, unshare and nsenter refuse. The kit reaches all three
    through PATH and starts its outer anchor with setsid, so without the opt-in no anchor,
    namespace, backend or CLI can start, even if a refusal the test expects regresses."""
    if not _GUARD:
        import atexit
        import tempfile
        guard = Path(tempfile.mkdtemp(prefix="kit-launch-guard-"))
        for tool in ("setsid", "unshare", "nsenter"):
            path = guard / tool
            path.write_text("#!/bin/sh\necho \"kit runtime tests are opt-in: $0 refused\" >&2\nexit 97\n")
            path.chmod(0o755)
        atexit.register(shutil.rmtree, guard, True)
        _GUARD.append(guard)
    return _GUARD[0]


def _identity(pid: int) -> dict:
    """The full identity of a process, as the kit records it: start, argv hash and parent."""
    import hashlib
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    parent = Path(f"/proc/{fields[1]}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "start": fields[19], "argv": hashlib.sha256(Path(f"/proc/{pid}/cmdline").read_bytes()).hexdigest(),
            "ppid": int(fields[1]), "pstart": parent[19]}


def _pidfd_kill(entry: dict) -> None:
    """Stop a recorded process: pidfd first, then the full identity and parent proof, then the signal."""
    import signal
    fd = os.pidfd_open(entry["pid"])
    try:
        assert _identity(entry["pid"]) == entry, "identity changed; not signalled"
        signal.pidfd_send_signal(fd, signal.SIGKILL)
    finally:
        os.close(fd)


_PROBE: list[int] = []


def _namespace_skip_reason(probe_returncode: int):
    """The exact skip reason when the host refuses unprivileged user and network namespaces."""
    return None if probe_returncode == 0 else "capability unavailable: uid_map"


KIT_RUNTIME_FLAG = "SYNTH_CITY_KIT_RUNTIME"


def _kit_runtime_skip_reason():
    """Kit runtime tests are opt-in (Supervisor 13700): a broad -k filter or a full local run
    must never start a namespace, backend or CLI by accident."""
    return None if os.environ.get(KIT_RUNTIME_FLAG) == "1" else "kit runtime tests are opt-in: set SYNTH_CITY_KIT_RUNTIME=1"


def _needs_namespaces():
    """Skip one runtime test (never the module) unless opted in, and on hosts that refuse the
    uid_map write. The opt-in check comes before the namespace probe."""
    opt_in = _kit_runtime_skip_reason()
    if opt_in:
        pytest.skip(opt_in)
    if not _PROBE:
        _PROBE.append(subprocess.run(["unshare", "--user", "--map-root-user", "--net", "true"],
                                     capture_output=True, timeout=10).returncode)
    reason = _namespace_skip_reason(_PROBE[0])
    if reason:
        pytest.skip(reason)


def _alive(pid: int) -> bool:
    """Read-only: whether a process with this pid exists (no signal, not even signal 0)."""
    return Path(f"/proc/{pid}").exists()


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


def test_namespace_capability_is_reported():
    _needs_namespaces()  # opt-in first; the probe it runs is reported, not asserted
    print("namespace capability: available")


@pytest.fixture
def kit_root(tmp_path):
    root = tmp_path / "kit"
    yield root
    _teardown_kit(root)


def _teardown_kit(root):
    # Only an opted-in run can have started a kit; without the flag nothing is run.
    if _kit_runtime_skip_reason() is None and (root / ".deck-runtime-kit").exists():
        _kit("down", "--root", str(root), timeout=60)


def test_fake_provider_runs_through_the_kit_end_to_end(kit_root):
    _needs_namespaces()
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
    _needs_namespaces()
    result = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT=fault))
    assert result.returncode == 2 and "refused" in result.stderr
    started = json.loads((kit_root / "state" / "processes.json").read_text())
    assert {"launcher", "outer", "inner"} <= set(started) and "backend" not in started
    assert not _root_users(kit_root)


def test_kit_refuses_to_enter_or_signal_a_reused_pid(kit_root):
    _needs_namespaces()
    up = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI))
    assert up.returncode == 0, up.stderr
    state = kit_root / "state" / "processes.json"
    processes = json.loads(state.read_text())
    real = dict(processes["inner"])
    processes["inner"]["start"] = str(int(real["start"]) + 1)  # as if the pid had been reused
    state.write_text(json.dumps(processes))
    refused = _kit("exec", "--root", str(kit_root), "--", "sh", "-c", "echo entered")
    # A changed start time means the recorded process is gone and its pid names another one:
    # the kit refuses to enter (fail closed), whichever word it reports.
    assert refused.returncode in (1, 2) and ("refused" in refused.stderr or "not running" in refused.stderr)
    assert "entered" not in refused.stdout
    processes["inner"] = real
    state.write_text(json.dumps(processes))


def test_kit_up_has_a_finite_deadline(kit_root):
    _needs_namespaces()
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
    _needs_namespaces()
    root = tmp_path / "kit"
    (root / "state").mkdir(parents=True)
    (root / ".deck-runtime-kit").write_text("")
    # The victim lives in a namespace of its own, so a full-shaped forged record can name it exactly.
    victim = subprocess.Popen(["unshare", "--user", "--map-root-user", "--net", "sleep", "300"], start_new_session=True)
    time.sleep(0.3)
    victim_id = _identity(victim.pid)  # captured once, immutable, for the proved cleanup below
    victim_net = os.readlink(f"/proc/{victim.pid}/ns/net")
    try:
        (root / "state" / "processes.json").write_text(json.dumps({
            "launcher": _identity(os.getpid()), "outer": victim_id, "backend": victim_id}))
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
        _pidfd_kill(victim_id)
        victim.wait()


def test_down_refuses_an_unrecorded_process_before_any_signal(kit_root):
    _needs_namespaces()
    summary = _up(kit_root)
    started = _kit("exec", "--root", str(kit_root), "--", "sh", "-c",
                   'cd / && setsid env -i sleep 300 </dev/null >/dev/null 2>&1 & echo $!')
    assert started.returncode == 0, started.stderr
    child = int(started.stdout.split()[-1])
    time.sleep(0.2)
    recorded_child = _identity(child)
    down = _kit("down", "--root", str(kit_root))
    assert down.returncode == 1 and "unrecorded" in down.stderr and str(child) in down.stderr, down.stderr
    # Nothing was signalled: the child and every kit process still run, and the root is kept.
    assert _alive(child) and kit_root.exists()
    assert all(_alive(pid) for pid in summary["pids"].values())
    _pidfd_kill(recorded_child)
    time.sleep(0.3)
    again = _kit("down", "--root", str(kit_root))
    assert again.returncode == 0, again.stderr
    assert not kit_root.exists() and not [pid for pid in summary["pids"].values() if _alive(pid)]


def test_up_refuses_a_retained_root_before_starting_anything(kit_root):
    _needs_namespaces()
    _up(kit_root)
    kept = _kit("down", "--root", str(kit_root), "--keep")
    assert kept.returncode == 0, kept.stderr
    before = set(_root_users(kit_root))
    again = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI))
    assert again.returncode == 2 and "refused" in again.stderr
    assert set(_root_users(kit_root)) <= before


def test_an_interrupted_preflight_leaves_no_process(kit_root):
    _needs_namespaces()
    result = _kit("up", "--root", str(kit_root), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  env=_env(RUNTIME_KIT_TEST_FAULT="after_anchor_spawn"))
    assert result.returncode != 0
    time.sleep(0.5)
    assert not _root_users(kit_root)


def test_no_credential_ever_appears_in_a_process_argv(kit_root):
    _needs_namespaces()
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
    _needs_namespaces()
    import sqlite3
    _up(kit_root)
    state = kit_root / "state" / "processes.json"
    processes = json.loads(state.read_text())
    if fault == "dead_backend":
        _pidfd_kill(processes["backend"])
    elif fault == "dead_cli":
        _pidfd_kill(processes["cli"])
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
    if fault == "reused_cli":  # restore the true record so the fixture's proved teardown can run
        processes["cli"]["start"] = str(int(processes["cli"]["start"]) - 1)
        state.write_text(json.dumps(processes))


def test_down_kills_a_recorded_child_that_ignores_term(kit_root):
    _needs_namespaces()
    summary = _up(kit_root, RUNTIME_KIT_TEST_FAULT="stub_ignores_term")
    stub = summary["pids"]["stub"]
    down = _kit("down", "--root", str(kit_root))
    assert down.returncode == 0, down.stderr
    assert not _alive(stub) and not kit_root.exists()


# Signal-free model tests of the ownership helper. The embedded Python helper is loaded in
# process with every /proc read mocked: no process is started and no signal can be sent.
# RUNTIME_KIT_SCRIPT_UNDER_TEST lets an in-memory removal control load a mutated copy.
def _helper_module():
    script = Path(os.environ.get("RUNTIME_KIT_SCRIPT_UNDER_TEST", KIT)).read_text()
    source = script[script.index("KITPY=\'\n") + 7:script.index("\n\'\nkitpy()")]
    namespace = {"__name__": "kitpy_model"}
    exec(compile(source, "kitpy", "exec"), namespace)
    return namespace


ROOT_MODEL = "/tmp/model-kit"
ID_MODEL = "ab" * 16


def _model(preflight=False):
    """A complete, valid kit: launcher, outer, inner, tmux, stub, backend and cli."""
    net, outer_user, inner_user = "net:[50]", "user:[51]", "user:[52]"
    world = {
        100: {"ppid": 1, "net": "net:[1]", "user": "user:[1]", "argv": [b"unshare"]},
        101: {"ppid": 100, "net": net, "user": outer_user,
              "argv": [b"bash", b"/x/scripts/isolated-runtime-kit.sh", b"_outer", ROOT_MODEL.encode(),
                       str(os.getuid()).encode(), str(os.getgid()).encode(), ID_MODEL.encode()]},
        102: {"ppid": 101, "net": net, "user": inner_user,
              "argv": [b"bash", b"/x/scripts/isolated-runtime-kit.sh", b"_inner", ROOT_MODEL.encode(), ID_MODEL.encode()]},
    }
    if not preflight:
        world.update({103: {"ppid": 102, "net": net, "user": inner_user, "argv": [b"tmux"]},
                      104: {"ppid": 102, "net": net, "user": inner_user, "argv": [b"stub"]},
                      105: {"ppid": 102, "net": net, "user": inner_user, "argv": [b"backend"]},
                      106: {"ppid": 103, "net": net, "user": inner_user, "argv": [b"cli"]}})
    for pid, proc in world.items():
        proc["start"] = str(1000 + pid)
    roles = {100: "launcher", 101: "outer", 102: "inner", 103: "tmux", 104: "stub", 105: "backend", 106: "cli"}
    procs = {roles[pid]: {"pid": pid, "start": proc["start"], "argv": f"h{pid}", "ppid": proc["ppid"],
                          "pstart": str(1000 + proc["ppid"])} for pid, proc in world.items()}
    inst = {"id": ID_MODEL, "uid": os.getuid(), "net": None if preflight else net, "user": None if preflight else inner_user}
    return world, procs, inst


def _bind(module, world, procs, inst):
    def proc_stat(pid):
        proc = world.get(int(pid))
        return None if proc is None else (proc["start"], proc["ppid"])
    module["proc_stat"] = proc_stat
    module["argv_hash"] = lambda pid: f"h{pid}" if int(pid) in world else None
    module["argv_list"] = lambda pid: world[int(pid)]["argv"] if int(pid) in world else None
    def link(pid, kind):
        proc = world.get(int(pid))
        if proc is None:
            raise FileNotFoundError(pid)
        if proc.get("unreadable"):
            raise PermissionError(pid)
        return proc[kind]
    module["link"] = link
    module["own_pids"] = lambda: sorted(world)
    module["HOST"] = {"net": "net:[1]", "user": "user:[1]"}
    module["instance"] = lambda root: inst
    module["processes"] = lambda root: procs
    return module


def test_model_plan_proves_every_role_and_orders_children_first():
    world, procs, inst = _model()
    module = _bind(_helper_module(), world, procs, inst)
    assert module["plan"](ROOT_MODEL) == {"targets": ["cli", "stub", "backend", "tmux", "inner", "outer"], "problems": []}


@pytest.mark.parametrize("role", ["outer", "inner", "tmux", "stub", "backend", "cli"])
def test_model_every_role_needs_its_recorded_parent_role(role):
    world, procs, inst = _model()
    procs[role]["ppid"], procs[role]["pstart"] = 999, "1999"  # a valid-looking but foreign parent
    world[999] = {"ppid": 1, "start": "1999", "net": "net:[1]", "user": "user:[1]", "argv": [b"x"]}
    world[procs[role]["pid"]]["ppid"] = 999
    module = _bind(_helper_module(), world, procs, inst)
    result = module["plan"](ROOT_MODEL)
    assert role not in result["targets"] and result["problems"]


def test_model_a_host_namespace_anchor_never_qualifies_even_with_a_valid_chain():
    world, procs, inst = _model(preflight=True)
    world[101]["net"] = world[102]["net"] = "net:[1]"
    module = _bind(_helper_module(), world, procs, inst)
    result = module["plan"](ROOT_MODEL)
    assert result["targets"] == [] and any("host namespace" in p for p in result["problems"])


def test_model_preflight_anchors_in_their_own_namespaces_qualify():
    world, procs, inst = _model(preflight=True)
    module = _bind(_helper_module(), world, procs, inst)
    assert module["plan"](ROOT_MODEL) == {"targets": ["inner", "outer"], "problems": []}


def test_model_a_foreign_anchor_with_a_wrong_command_is_refused():
    world, procs, inst = _model()
    world[101]["argv"] = [b"bash", b"/x/scripts/isolated-runtime-kit.sh", b"_outer", b"/other/root",
                          str(os.getuid()).encode(), str(os.getgid()).encode(), ID_MODEL.encode()]
    module = _bind(_helper_module(), world, procs, inst)
    result = module["plan"](ROOT_MODEL)
    assert "outer" not in result["targets"] and result["problems"]


def test_model_a_stale_record_never_hides_a_live_process():
    world, procs, inst = _model()
    procs["stub"]["start"] = "7"  # recorded stub exited; pid 104 now names another process in the namespace
    module = _bind(_helper_module(), world, procs, inst)
    result = module["plan"](ROOT_MODEL)
    assert "stub" not in result["targets"] and any("104" in p for p in result["problems"])


def test_model_an_unknown_role_record_is_a_problem():
    world, procs, inst = _model()
    procs["helper"] = dict(procs["stub"])
    module = _bind(_helper_module(), world, procs, inst)
    assert any("unknown role" in p for p in module["plan"](ROOT_MODEL)["problems"])


def test_model_an_unreadable_process_refuses_the_plan():
    world, procs, inst = _model()
    world[200] = {"ppid": 1, "start": "1200", "net": "net:[50]", "user": "user:[52]", "argv": [b"x"], "unreadable": True}
    module = _bind(_helper_module(), world, procs, inst)
    assert any("cannot be inspected" in p for p in module["plan"](ROOT_MODEL)["problems"])


@pytest.mark.parametrize("change", ["argv_only", "replacement_pid", "new_parent"])
def test_model_refresh_changes_only_the_command_line(tmp_path, change):
    world, procs, inst = _model()
    (tmp_path / "state").mkdir()
    module = _bind(_helper_module(), world, procs, inst)
    if change == "argv_only":
        module["argv_hash"] = lambda pid: "after-exec" if int(pid) == 105 else f"h{pid}"
    elif change == "replacement_pid":
        world[105]["start"] = "9999"
    else:
        world[105]["ppid"] = 103
    if change == "argv_only":
        module["refresh"](str(tmp_path), "backend")
        assert json.loads((tmp_path / "state" / "processes.json").read_text())["backend"]["argv"] == "after-exec"
        assert procs["backend"]["start"] == "1105" and procs["backend"]["ppid"] == 102
    else:
        with pytest.raises(SystemExit) as refused:
            module["refresh"](str(tmp_path), "backend")
        assert refused.value.code == 2 and not (tmp_path / "state" / "processes.json").exists()


@pytest.mark.parametrize("fault", ["start", "argv", "parent", "no_pidfd", "launcher"])
def test_model_signal_check_refuses_before_any_signal(monkeypatch, fault):
    world, procs, inst = _model()
    name = "stub"
    if fault == "start":
        procs["stub"]["start"] = "1104" + "0"
    elif fault == "argv":
        procs["stub"]["argv"] = "0" * 64
    elif fault == "parent":
        world[104]["ppid"] = 103
    elif fault == "no_pidfd":
        monkeypatch.setenv("RUNTIME_KIT_TEST_NO_PIDFD", "1")
    else:
        name = "launcher"
    module = _bind(_helper_module(), world, procs, inst)
    module["os"] = type("NoPidfd", (), {"environ": os.environ, "getpid": os.getpid, "getppid": os.getppid,
                                         "getuid": os.getuid, "getgid": os.getgid,
                                         # the pidfd is opened first, by design; only signalling must never happen
                                         "pidfd_open": staticmethod(lambda pid: -7),
                                         "close": staticmethod(lambda fd: None)})
    module["signal"] = type("NoSignal", (), {"pidfd_send_signal": staticmethod(
        lambda fd, sig: (_ for _ in ()).throw(AssertionError("signalled")))})
    with pytest.raises(SystemExit) as refused:
        module["send"](ROOT_MODEL, name, "TERM", dry=False)
    assert refused.value.code in (2, 3, 4)


def test_status_on_an_invalid_root_writes_nothing(tmp_path):
    root = tmp_path / "kit"
    (root / "evidence").mkdir(parents=True)
    (root / ".deck-runtime-kit").write_text("")
    (root / "evidence" / "MANIFEST.sha256").write_text("old evidence\n")
    def tree():
        return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}
    before = tree()
    result = _kit("status", "--root", str(root))
    assert result.returncode == 2 and "refused" in result.stderr
    assert tree() == before


def test_status_publishes_nothing_when_its_summary_fails(kit_root):
    _needs_namespaces()
    _up(kit_root)
    first = _kit("status", "--root", str(kit_root))
    assert first.returncode == 0, first.stderr
    published = (kit_root / "evidence" / "MANIFEST.sha256").read_text()
    link = os.readlink(kit_root / "evidence")
    failed = _kit("status", "--root", str(kit_root), env=_env(RUNTIME_KIT_TEST_FAULT="summary_fails"))
    assert failed.returncode == 1 and "incomplete" in failed.stderr
    assert os.readlink(kit_root / "evidence") == link
    assert (kit_root / "evidence" / "MANIFEST.sha256").read_text() == published
    assert sorted(p.name for p in (kit_root / "evidence.d").iterdir()) == [link.split("/")[-1]]


def test_model_capability_skip_gate():
    assert _namespace_skip_reason(1) == "capability unavailable: uid_map"
    assert _namespace_skip_reason(0) is None


# Status publication (V1 review 5898109183): one commit point (os.replace of a link this run
# created), no deletion of anything but this run's own attempt and link before commit, and
# no deletion at all through a published link. Disposable filesystems only; no kit, no signal.
def _publication(tmp_path, old_target="evidence.d/0000000000000000"):
    root = tmp_path / "kit"
    evd = root / "evidence.d"
    old = evd / "0000000000000000"
    old.mkdir(parents=True)
    (old / "MANIFEST.sha256").write_text("old manifest\n")
    (root / "evidence").symlink_to(old_target)
    new = evd / "1111111111111111"
    new.mkdir()
    (new / "summary.json").write_text('{"summary": "new"}\n')
    (new / "MANIFEST.sha256").write_text("new manifest\n")
    return root, old, new


def _publish(module, root, attempt="1111111111111111"):
    try:
        module["publish"](str(root), attempt)
    except SystemExit as exc:
        return exc.code
    return 0


def test_publish_commits_by_link_swap_and_keeps_previous_attempts(tmp_path, capsys):
    root, old, new = _publication(tmp_path)
    assert _publish(_helper_module(), root) == 0
    assert os.readlink(root / "evidence") == "evidence.d/1111111111111111"
    assert old.is_dir() and (old / "MANIFEST.sha256").read_text() == "old manifest\n"
    assert '"new"' in capsys.readouterr().out


@pytest.mark.parametrize("target", ["relative_traversal", "absolute"])
def test_publish_never_deletes_through_a_published_link(tmp_path, target):
    canary = tmp_path / "canary"
    canary.mkdir()
    (canary / "keep").write_text("keep")
    link = "evidence.d/../../canary" if target == "relative_traversal" else str(canary)
    root, old, new = _publication(tmp_path, old_target=link)
    assert _publish(_helper_module(), root) == 0
    assert (canary / "keep").read_text() == "keep" and old.is_dir() and new.is_dir()


@pytest.mark.parametrize("stage", ["symlink", "replace"])
def test_publish_failure_before_commit_removes_only_this_run(tmp_path, stage):
    root, old, new = _publication(tmp_path)
    other = root / "evidence.d" / "2222222222222222"
    other.mkdir()
    module = _helper_module()
    def broken(*args, **kwargs):
        raise OSError("injected")
    module["_symlink" if stage == "symlink" else "_replace"] = broken
    assert _publish(module, root) == 1
    assert os.readlink(root / "evidence") == "evidence.d/0000000000000000"
    assert (old / "MANIFEST.sha256").read_text() == "old manifest\n"
    assert not new.exists() and other.is_dir()
    assert not [p for p in root.iterdir() if p.name.startswith(".evidence-")]


@pytest.mark.parametrize("which", ["evidence_dir", "attempt"])
def test_publish_refuses_symlinked_paths_and_deletes_nothing(tmp_path, which):
    root, old, new = _publication(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep").write_text("keep")
    if which == "attempt":
        target = root / "evidence.d" / "3333333333333333"
        target.symlink_to(elsewhere)
        attempt = "3333333333333333"
    else:
        moved = tmp_path / "real-evidence.d"
        (root / "evidence.d").rename(moved)
        (root / "evidence.d").symlink_to(moved)
        attempt = "1111111111111111"
    assert _publish(_helper_module(), root, attempt) == 2
    assert (elsewhere / "keep").read_text() == "keep"
    assert os.readlink(root / "evidence") == "evidence.d/0000000000000000"


def test_publish_output_failure_after_commit_keeps_both_and_says_so(tmp_path, capsys):
    root, old, new = _publication(tmp_path)
    module = _helper_module()
    def broken(text):
        raise OSError("injected output failure")
    module["_write_out"] = broken
    assert _publish(module, root) == 1
    assert os.readlink(root / "evidence") == "evidence.d/1111111111111111"
    assert old.is_dir() and new.is_dir()
    assert "published, but the summary could not be printed" in capsys.readouterr().err


# #912: an OpenCode member in the kit must be pinned to the kit's stub model. The kit
# writes a stub-only provider config into its own HOME before launch, keeps the Agent
# Mail install's entries, and refuses to launch when that config can't be proved.
STUB_URL = "http://127.0.0.1:18781"
MAIL_SERVER = "albiex-synth-city-mail"
DENY_RULE = {"action": "question", "resource": "*", "effect": "deny"}


SHIM = REPO / "backend" / "mcp_shim" / "agent_mail_server.py"
os.environ.setdefault("RUNTIME_KIT_REPO_ROOT", str(REPO))  # where the kit helper finds the installed shim
TRUSTED_PYTHON = os.path.realpath(shutil.which("python3"))
os.environ.setdefault("RUNTIME_KIT_PYTHON", TRUSTED_PYTHON)  # the kit backend's interpreter, as up passes it


def _mail_entry():  # what the Agent Mail install writes for OpenCode 2 in the kit
    return {"type": "local", "command": [os.environ["RUNTIME_KIT_PYTHON"], str(SHIM)],
            "enabled": True, "codemode": False,
            "environment": {"SYNTH_CITY_URL": "http://127.0.0.1:18780", "SYNTH_CITY_PROVIDER": "opencode-cli"}}


def _opencode_home(tmp_path, doc=None):
    root = tmp_path / "kit"
    home = root / "home" / ".config" / "opencode"
    home.mkdir(parents=True)
    (root / "state").mkdir()
    if doc is None:
        doc = {"mcp": {"servers": {MAIL_SERVER: _mail_entry()}}, "permissions": [dict(DENY_RULE)]}
    if doc is not False:
        (home / "opencode.json").write_text(json.dumps(doc))
    return root, home / "opencode.json"


def _opencode(module, command, root, url=STUB_URL):
    try:
        module[command](str(root), url)
    except SystemExit as exc:
        return exc.code
    return 0


def test_opencode_config_is_stub_only_and_keeps_the_install(tmp_path, capsys):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    doc = json.loads(path.read_text())
    assert doc["enabled_providers"] == ["kitstub"]
    assert doc["model"] == "kitstub/stub"
    assert list(doc["provider"]) == ["kitstub"]
    assert doc["provider"]["kitstub"]["options"]["baseURL"] == STUB_URL + "/v1"
    assert list(doc["provider"]["kitstub"]["models"]) == ["stub"]
    assert doc["autoupdate"] is False and doc["share"] == "disabled"
    # The install's Mail entry and question-deny rule are kept unchanged.
    assert doc["mcp"]["servers"][MAIL_SERVER]["codemode"] is False
    assert DENY_RULE in doc["permissions"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary == {"providers": ["kitstub"], "enabled_providers": ["kitstub"], "model": "kitstub/stub",
                       "base_url": "127.0.0.1:18781", "mail_entry": True, "question_denied": True}
    assert _opencode(module, "opencode_check", root) == 0


@pytest.mark.parametrize("case", ["no_config", "jsonc", "no_mail_entry", "no_deny_rule", "foreign_provider",
                                  "not_an_object", "remote_stub", "unwritable", "mail_empty", "mail_disabled",
                                  "mail_remote", "mail_no_command", "mail_codemode", "mail_other_backend",
                                  "mail_empty_executable", "mail_false_executable", "mail_foreign_shim",
                                  "mail_other_script", "mail_python_named_false", "mail_python_alias"])
def test_opencode_config_refuses_unsafe_merges(tmp_path, case):
    doc = None
    if case == "no_config":
        doc = False
    elif case == "no_mail_entry":
        doc = {"mcp": {"servers": {}}, "permissions": [dict(DENY_RULE)]}
    elif case == "no_deny_rule":
        doc = {"mcp": {"servers": {MAIL_SERVER: _mail_entry()}}, "permissions": []}
    elif case.startswith("mail_"):  # V1 review 5899008490 finding 3: an unusable install entry
        entry = _mail_entry()
        if case == "mail_empty":
            entry = {}
        elif case == "mail_disabled":
            entry["enabled"] = False
        elif case == "mail_remote":
            entry["type"] = "remote"
        elif case == "mail_no_command":
            del entry["command"]
        elif case == "mail_codemode":
            entry["codemode"] = True
        elif case == "mail_other_backend":
            entry["environment"]["SYNTH_CITY_URL"] = "http://127.0.0.1:8011"
        elif case == "mail_empty_executable":  # V1 review 5899105931 finding 3
            entry["command"][0] = ""
        elif case == "mail_false_executable":
            entry["command"][0] = "/bin/false"
        elif case == "mail_foreign_shim":
            entry["command"][1] = "/nonexistent/elsewhere/mcp_shim/agent_mail_server.py"
        elif case == "mail_other_script":
            entry["command"] = [entry["command"][0], str(REPO / "scripts" / "ci" / "old_names.py"), str(SHIM)]
        elif case == "mail_python_alias":  # an alias resolving to the trusted interpreter is accepted
            alias = tmp_path / "alias" / "python3"
            alias.parent.mkdir()
            alias.symlink_to(os.environ["RUNTIME_KIT_PYTHON"])
            entry["command"][0] = str(alias)
        elif case == "mail_python_named_false":  # V1 review 5899246315 finding 3: a name proves nothing
            fake = tmp_path / "bin" / "python3"
            fake.parent.mkdir()
            fake.symlink_to("/bin/false")
            entry["command"][0] = str(fake)
        doc = {"mcp": {"servers": {MAIL_SERVER: entry}}, "permissions": [dict(DENY_RULE)]}
    elif case == "foreign_provider":
        doc = {"mcp": {"servers": {MAIL_SERVER: _mail_entry()}}, "permissions": [dict(DENY_RULE)],
               "provider": {"openai": {"options": {"baseURL": "https://api.example.invalid/v1"}}}}
    elif case == "not_an_object":
        doc = ["not", "an", "object"]
    root, path = _opencode_home(tmp_path, doc)
    if case == "jsonc":
        path.with_suffix(".jsonc").write_text("{ // comments can't be merged safely\n}")
    before = path.read_bytes() if path.exists() else None
    url = "http://10.0.0.1:18781" if case == "remote_stub" else STUB_URL
    if case == "unwritable":
        path.parent.chmod(0o500)
    try:
        if case == "mail_python_alias":
            assert _opencode(_helper_module(), "opencode_config", root, url) == 0
            return
        assert _opencode(_helper_module(), "opencode_config", root, url) == 2
    finally:
        path.parent.chmod(0o700)
    # A refusal changes nothing.
    assert (path.read_bytes() if path.exists() else None) == before
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".opencode")]


@pytest.mark.parametrize("tamper", ["extra_provider", "enabled_widened", "enabled_missing", "remote_base_url",
                                    "model_elsewhere", "mail_entry_removed", "deny_rule_removed",
                                    "mail_emptied", "mail_disabled", "mail_codemode", "adapter_changed",
                                    "autoupdate_on", "share_on", "unrelated_key_added"])
def test_opencode_check_refuses_a_config_that_is_not_stub_only(tmp_path, tamper):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    doc = json.loads(path.read_text())
    if tamper == "extra_provider":
        doc["provider"]["openai"] = {"options": {"baseURL": "https://api.example.invalid/v1"}}
    elif tamper == "enabled_widened":
        doc["enabled_providers"] = ["kitstub", "opencode"]
    elif tamper == "enabled_missing":
        del doc["enabled_providers"]
    elif tamper == "remote_base_url":
        doc["provider"]["kitstub"]["options"]["baseURL"] = "http://10.0.0.1:18781/v1"
    elif tamper == "model_elsewhere":
        doc["model"] = "opencode/free"
    elif tamper == "mail_entry_removed":
        del doc["mcp"]["servers"][MAIL_SERVER]
    elif tamper == "mail_emptied":
        doc["mcp"]["servers"][MAIL_SERVER] = {}
    elif tamper == "mail_disabled":
        doc["mcp"]["servers"][MAIL_SERVER]["enabled"] = False
    elif tamper == "mail_codemode":
        doc["mcp"]["servers"][MAIL_SERVER]["codemode"] = True
    elif tamper == "adapter_changed":
        doc["provider"]["kitstub"]["npm"] = "@ai-sdk/anthropic"
    elif tamper == "autoupdate_on":
        doc["autoupdate"] = True
    elif tamper == "share_on":
        doc["share"] = "auto"
    elif tamper == "unrelated_key_added":  # any change after the proved write is refused
        doc["instructions"] = ["anything"]
    else:
        doc["permissions"] = []
    path.write_text(json.dumps(doc))
    assert _opencode(module, "opencode_check", root) == 2


def _opencode_control(tmp_path, monkeypatch, old, new):
    script = KIT.read_text()
    assert script.count(old) == 1, old
    mutated = tmp_path / "mutated-kit.sh"
    mutated.write_text(script.replace(old, new))
    monkeypatch.setenv("RUNTIME_KIT_SCRIPT_UNDER_TEST", str(mutated))


# In-memory removal controls: each mutation of the helper must make a test above fail.
@pytest.mark.parametrize("control", ["no_enabled_providers", "no_validation", "overwrite_not_merge"])
def test_opencode_controls_are_caught(tmp_path, monkeypatch, control):
    if control == "no_enabled_providers":
        _opencode_control(tmp_path, monkeypatch, "doc[\"enabled_providers\"] = [KIT_PROVIDER]", "pass")
    elif control == "no_validation":
        _opencode_control(tmp_path, monkeypatch, "def opencode_check(root, stub_url):\n",
                          "def opencode_check(root, stub_url):\n    return {}\n")
    else:
        _opencode_control(tmp_path, monkeypatch, "doc = _opencode_load(path)", "doc = {}")
    failed = []
    for name, test in (("written", lambda: test_opencode_config_is_stub_only_and_keeps_the_install(
                            tmp_path / "a", _NullCapsys())),
                       ("tamper", lambda: test_opencode_check_refuses_a_config_that_is_not_stub_only(
                            tmp_path / "b", "enabled_missing"))):
        (tmp_path / ("a" if name == "written" else "b")).mkdir()
        try:
            test()
        except (AssertionError, KeyError, json.JSONDecodeError):
            failed.append(name)
    assert failed, f"control {control} was not caught"


class _NullCapsys:
    def readouterr(self):
        class Out:
            out = json.dumps({"providers": ["kitstub"], "enabled_providers": ["kitstub"], "model": "kitstub/stub",
                              "base_url": "127.0.0.1:18781", "mail_entry": True, "question_denied": True})
            err = ""
        return Out()


def test_opencode_member_launch_is_pinned_to_the_stub(tmp_path):
    """End to end with the fake CLI: the stub-only config is proved before launch, and the
    slot launches with the stub model, so the product's own per-member config pins it too.
    The fake is not OpenCode, so the product's OpenCode 2 gate refuses its registration:
    a real member's registration is proved only by a real OpenCode run (a later phase)."""
    _needs_namespaces()
    import sqlite3
    from app.services.opencode_process_identity import config_content
    root = tmp_path / "kit"
    up = _kit("up", "--root", str(root), "--provider", "opencode-cli", "--cli", str(FAKE_CLI))
    try:
        assert up.returncode == 1 and "did not register" in up.stderr, up.stderr
        assert _opencode(_helper_module(), "opencode_check", root) == 0
        doc = json.loads((root / "home" / ".config" / "opencode" / "opencode.json").read_text())
        assert doc["enabled_providers"] == ["kitstub"] and MAIL_SERVER in doc["mcp"]["servers"]
        db = sqlite3.connect(f"file:{root / 'kit.db'}?mode=ro", uri=True)
        try:
            rows = db.execute("select provider, launch_options from agent_team_slots").fetchall()
        finally:
            db.close()
        assert [(provider, json.loads(options)["model"]) for provider, options in rows] == [("opencode-cli", "kitstub/stub")]
        member = json.loads(config_content(model="kitstub/stub", agent=None))
        assert member["enabled_providers"] == ["kitstub"] and member["model"] == "kitstub/stub"
    finally:
        down = _kit("down", "--root", str(root))
    assert down.returncode == 0, down.stderr
    assert not root.exists()


def test_status_provider_proof_cannot_be_bypassed_by_the_marker(tmp_path):
    """V1 review 5899008490 finding 2, end to end: another provider keeps its normal status;
    a missing or changed provider marker is refused before anything is written."""
    _needs_namespaces()
    root = tmp_path / "kit"
    _up(root)
    try:
        status = _kit("status", "--root", str(root))
        assert status.returncode == 0, status.stderr
        assert not (root / "evidence" / "opencode-config.json").exists()
        published = os.readlink(root / "evidence")
        attempts = sorted(p.name for p in (root / "evidence.d").iterdir())
        marker = root / "state" / "provider"
        for change in ("missing", "opencode-cli"):
            if change == "missing":
                marker.unlink()
            else:
                marker.write_text(change + "\n")
            again = _kit("status", "--root", str(root))
            assert again.returncode == 2 and "kit provider cannot be proved" in again.stderr, again.stderr
            assert os.readlink(root / "evidence") == published
            assert sorted(p.name for p in (root / "evidence.d").iterdir()) == attempts
    finally:
        down = _kit("down", "--root", str(root))
    assert down.returncode == 0, down.stderr
    assert not root.exists()


# V1 review 5899008490 finding 1: no path component of the config may lead out of the kit.
@pytest.mark.parametrize("component", ["home", ".config", "opencode"])
def test_opencode_config_refuses_a_symlinked_directory_and_writes_nothing_outside(tmp_path, component):
    root, path = _opencode_home(tmp_path)
    outside = tmp_path / "outside"
    chain = {"home": root / "home", ".config": root / "home" / ".config", "opencode": path.parent}
    chain[component].rename(outside)
    chain[component].symlink_to(outside)
    victim = outside / (path.relative_to(chain[component]))
    before = victim.read_bytes()
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 2
    assert victim.read_bytes() == before
    assert not [p for p in victim.parent.iterdir() if p.name.startswith(".opencode")]
    assert _opencode(module, "opencode_check", root) == 2


def _kit_db(root, slot_provider, session_provider, state_provider):
    import sqlite3
    db = sqlite3.connect(root / "kit.db")
    db.execute("CREATE TABLE agent_team_slots (id INTEGER PRIMARY KEY, provider TEXT)")
    db.execute("CREATE TABLE mail_agent_sessions (id INTEGER PRIMARY KEY, provider TEXT, team_slot_id INTEGER, closed_at TEXT)")
    db.execute("INSERT INTO agent_team_slots VALUES (7, ?)", (slot_provider,))
    if session_provider is not None:
        db.execute("INSERT INTO mail_agent_sessions VALUES (1, ?, 7, NULL)", (session_provider,))
    db.commit()
    db.close()
    (root / "state" / "launch.json").write_text(json.dumps({"slot_id": 7}))
    if state_provider is not None:
        (root / "state" / "provider").write_text(state_provider + "\n")


# V1 review 5899008490 finding 2: the provider that decides the OpenCode proof is bound to
# the launched slot and the registered session; a missing or different marker is refused.
@pytest.mark.parametrize("slot, session, marker, expected", [
    ("opencode-cli", "opencode-cli", "opencode-cli", "opencode-cli"),
    ("claude-code", "claude-code", "claude-code", "claude-code"),
    ("opencode-cli", "opencode-cli", None, None),
    ("opencode-cli", "opencode-cli", "claude-code", None),
    ("claude-code", "opencode-cli", "claude-code", None),
    ("opencode-cli", None, "opencode-cli", None),
])
def test_kit_provider_is_bound_to_the_launch_and_registration(tmp_path, capsys, slot, session, marker, expected):
    root, _ = _opencode_home(tmp_path)
    _kit_db(root, slot, session, marker)
    module = _helper_module()
    try:
        module["kit_provider"](str(root))
        code = 0
    except SystemExit as exc:
        code = exc.code
    if expected is None:
        assert code == 2
    else:
        assert code == 0 and capsys.readouterr().out.strip() == expected


# V1 review 5899008490 finding 4: the config is proved again at the end of capture and must
# match the captured proof exactly; a change during capture publishes nothing.
def test_opencode_final_check_refuses_a_config_changed_during_capture(tmp_path, capsys):
    root, path = _opencode_home(tmp_path)
    _kit_db(root, "opencode-cli", "opencode-cli", "opencode-cli")
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    capsys.readouterr()
    captured = tmp_path / "opencode-config.json"
    assert _opencode(module, "opencode_check", root) == 0
    captured.write_text(capsys.readouterr().out)
    def final():
        try:
            module["opencode_final"](str(root), STUB_URL, str(captured))
        except SystemExit as exc:
            return exc.code
        return 0
    assert final() == 0
    doc = json.loads(path.read_text())
    doc["enabled_providers"] = ["kitstub", "opencode"]
    path.write_text(json.dumps(doc))
    assert final() == 2
    path.write_text(json.dumps({**doc, "enabled_providers": ["kitstub"]}))  # back to valid, but not byte-identical
    assert final() == 2


# In-memory removal controls for the V1 5899008490 batch: each must make a test above fail.
@pytest.mark.parametrize("control", ["no_ancestor_check", "marker_only", "mail_presence_only", "final_skipped"])
def test_opencode_correction_controls_are_caught(tmp_path, monkeypatch, capsys, control):
    if control == "no_ancestor_check":
        _opencode_control(tmp_path, monkeypatch, "        if not stat.S_ISDIR(info.st_mode):\n", "        if False:\n")
        run = lambda: test_opencode_config_refuses_a_symlinked_directory_and_writes_nothing_outside(tmp_path / "t", "home")
    elif control == "marker_only":
        _opencode_control(tmp_path, monkeypatch, "not (marker == slot[0] == session[0])", "False")
        run = lambda: test_kit_provider_is_bound_to_the_launch_and_registration(
            tmp_path / "t", capsys, "opencode-cli", "opencode-cli", "claude-code", None)
    elif control == "mail_presence_only":
        _opencode_control(tmp_path, monkeypatch, "    return (entry.get(\"type\") == \"local\"", "    return True or (entry.get(\"type\") == \"local\"")
        run = lambda: test_opencode_check_refuses_a_config_that_is_not_stub_only(tmp_path / "t", "mail_entry_removed") or \
            test_opencode_config_refuses_unsafe_merges(tmp_path / "u", "mail_disabled")
    else:
        _opencode_control(tmp_path, monkeypatch, "def opencode_final(root, stub_url, captured):\n",
                          "def opencode_final(root, stub_url, captured):\n    return\n")
        run = lambda: test_opencode_final_check_refuses_a_config_changed_during_capture(tmp_path / "t", capsys)
    (tmp_path / "t").mkdir()
    (tmp_path / "u").mkdir()
    with pytest.raises(AssertionError):
        run()


# V1 review 5899105931 findings 1 and 2: the proof file is confined and replaced safely, and a
# refusal before launch leaves both the config and the proof exactly as they were.
@pytest.mark.parametrize("case", ["state_symlink", "digest_hardlink", "digest_symlink", "digest_directory",
                                  "digest_replace_fails"])
def test_opencode_proof_file_is_confined_and_a_refusal_changes_nothing(tmp_path, case):
    root, path = _opencode_home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    canary = outside / "canary"
    canary.write_text("outside canary\n")
    digest = root / "state" / "opencode-config.sha256"
    module = _helper_module()
    if case == "state_symlink":
        (root / "state").rmdir()
        (root / "state").symlink_to(outside)
    elif case == "digest_hardlink":
        os.link(canary, digest)
    elif case == "digest_symlink":
        digest.symlink_to(canary)
    elif case == "digest_directory":
        digest.mkdir()
    else:
        real = module["_replace"]
        def failing(src, dst):
            if str(dst).endswith("opencode-config.sha256"):
                raise OSError("injected")
            return real(src, dst)
        module["_replace"] = failing
    config_before = path.read_bytes()
    code = _opencode(module, "opencode_config", root)
    assert canary.read_text() == "outside canary\n"
    assert sorted(p.name for p in outside.iterdir()) == ["canary"]
    if case == "digest_hardlink":  # replaced as a new file: the outside link target is untouched
        assert code == 0 and os.stat(digest).st_ino != os.stat(canary).st_ino
    else:
        assert code == 2
        assert path.read_bytes() == config_before
        assert not [p for p in path.parent.iterdir() if p.name.startswith(".opencode")]
        if case == "digest_directory":
            assert digest.is_dir() and not any(digest.iterdir())
        if case == "digest_replace_fails":
            assert not digest.exists()


def test_opencode_config_rename_failure_restores_the_earlier_proof(tmp_path):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    digest = root / "state" / "opencode-config.sha256"
    proof_before = digest.read_bytes()
    doc = json.loads(path.read_text())  # a later setup run would write different bytes
    doc["instructions"] = ["kept as it is"]
    path.write_text(json.dumps(doc))
    config_before = path.read_bytes()
    real = module["_replace"]
    def failing(src, dst):
        if str(dst).endswith("opencode.json"):
            raise OSError("injected")
        return real(src, dst)
    module["_replace"] = failing
    assert _opencode(module, "opencode_config", root) == 2
    assert path.read_bytes() == config_before and digest.read_bytes() == proof_before
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".opencode")]
    assert not [p for p in digest.parent.iterdir() if p.name.startswith(".opencode")]
    assert _opencode(module, "opencode_check", root) == 2  # the earlier proof doesn't prove these bytes


# In-memory removal controls for the V1 5899105931 batch.
@pytest.mark.parametrize("control", ["state_unchecked", "command_unchecked", "no_proof_restore"])
def test_opencode_proof_controls_are_caught(tmp_path, monkeypatch, control):
    if control == "state_unchecked":
        _opencode_control(tmp_path, monkeypatch, "    if not stat.S_ISDIR(info.st_mode):\n        die(2, \"refused: the kit state directory",
                          "    if False:\n        die(2, \"refused: the kit state directory")
        run = lambda: test_opencode_proof_file_is_confined_and_a_refusal_changes_nothing(tmp_path / "t", "state_symlink")
    elif control == "command_unchecked":
        _opencode_control(tmp_path, monkeypatch, "def _mail_command_ok(command):\n",
                          "def _mail_command_ok(command):\n    return True\n")
        run = lambda: test_opencode_config_refuses_unsafe_merges(tmp_path / "t", "mail_false_executable")
    else:
        _opencode_control(tmp_path, monkeypatch, "                    _replace(restore, digest)\n",
                          "                    os.unlink(restore)\n")
        run = lambda: test_opencode_config_rename_failure_restores_the_earlier_proof(tmp_path / "t")
    (tmp_path / "t").mkdir()
    with pytest.raises(AssertionError):
        run()


# Supervisor 13700: kit tests that start a real namespace, backend or CLI are opt-in, so a
# broad -k filter or a full local run never starts a runtime by accident.
REFUSAL_ONLY = {  # run everywhere: each is refused by argument or root checks before any namespace
    "test_kit_refuses_a_foreign_synth_city_or_mail_credential",
    "test_kit_refuses_a_root_it_does_not_own",
    "test_status_on_an_invalid_root_writes_nothing",
    "test_stub_script_kit_up_refuses_a_malformed_script_before_creating_anything",  # #912 A1b
    "test_stub_script_kit_status_refuses_the_option",
}


def test_kit_runtime_tests_are_opt_in(monkeypatch):
    def no_probe(*args, **kwargs):
        raise AssertionError("the namespace probe ran without the opt-in flag")
    monkeypatch.setattr(subprocess, "run", no_probe)
    for value in (None, "", "0", "yes"):
        if value is None:
            monkeypatch.delenv("SYNTH_CITY_KIT_RUNTIME", raising=False)
        else:
            monkeypatch.setenv("SYNTH_CITY_KIT_RUNTIME", value)
        with pytest.raises(pytest.skip.Exception, match="opt-in: set SYNTH_CITY_KIT_RUNTIME=1"):
            _needs_namespaces()


def test_every_runtime_test_reaches_the_opt_in_gate_first():
    import ast
    tree = ast.parse(Path(__file__).read_text())
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def called(node):
        return {call.func.id for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}

    def reaches(name, seen):
        found = set()
        for callee in called(functions[name]):
            if callee in functions and callee not in seen:
                seen.add(callee)
                found |= {callee} | reaches(callee, seen)
        return found

    ungated = set()
    for name, node in functions.items():
        if not name.startswith("test_"):
            continue
        if name in ("test_every_runtime_test_reaches_the_opt_in_gate_first",  # this audit
                    "test_kit_fixture_teardown_runs_nothing_without_the_opt_in",  # _kit mocked
                    "test_kit_without_the_opt_in_runs_behind_a_boundary_that_cannot_launch",  # subprocess.run mocked
                    "test_launch_guard_control_is_caught",  # runs the mocked test above
                    "test_up_keeps_the_opencode_helper_outcome",  # one extracted step, kitpy mocked
                    "test_opencode_outcome_control_is_caught"):
            continue
        uses = reaches(name, set()) | called(node)
        starts = any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                     and isinstance(call.func.value, ast.Name) and call.func.value.id == "subprocess"
                     and call.func.attr in ("run", "Popen", "call", "check_call", "check_output")
                     for call in ast.walk(node))
        if not ({"_kit", "_up"} & uses or starts):
            continue
        body = [stmt for stmt in node.body if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))]
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
                and getattr(first.value.func, "id", None) == "_needs_namespaces"):
            ungated.add(name)
    assert ungated == REFUSAL_ONLY


def test_kit_fixture_teardown_runs_nothing_without_the_opt_in(tmp_path, monkeypatch):
    root = tmp_path / "kit"
    root.mkdir()
    (root / ".deck-runtime-kit").write_text("")
    calls = []
    monkeypatch.setitem(globals(), "_kit", lambda *args, **kwargs: calls.append(args))
    monkeypatch.delenv(KIT_RUNTIME_FLAG, raising=False)
    _teardown_kit(root)
    assert calls == []
    monkeypatch.setenv(KIT_RUNTIME_FLAG, "1")
    _teardown_kit(root)
    assert calls == [("down", "--root", str(root))]


def test_opt_in_gate_control_is_caught(monkeypatch):
    # In-memory control: without the gate, the opt-in test fails (the probe would run).
    monkeypatch.setitem(globals(), "_kit_runtime_skip_reason", lambda: None)
    monkeypatch.setitem(globals(), "_PROBE", [])
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        test_kit_runtime_tests_are_opt_in(monkeypatch)


# V1 review 5899246315 findings 1 and 2: a failed restore is incomplete, never an unchanged
# refusal; a partial staging write leaves no temporary file.
def test_opencode_failed_restore_is_incomplete_and_leaves_no_temporary_file(tmp_path):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    doc = json.loads(path.read_text())
    doc["instructions"] = ["kept as it is"]
    path.write_text(json.dumps(doc))
    config_before = path.read_bytes()
    real = module["_replace"]
    calls = []
    def failing(src, dst):
        calls.append(os.path.basename(str(dst)))
        if str(dst).endswith("opencode.json") or len(calls) > 2:
            raise OSError("injected")
        return real(src, dst)
    module["_replace"] = failing
    assert _opencode(module, "opencode_config", root) == 1
    assert path.read_bytes() == config_before
    for directory in (path.parent, root / "state"):
        assert not [p for p in directory.iterdir() if p.name.startswith(".opencode")]


@pytest.mark.parametrize("which", [0, 1])
def test_opencode_partial_staging_write_leaves_no_temporary_file(tmp_path, which):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    config_before = path.read_bytes()
    real = module["_fdopen"]
    count = []
    class Broken:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self.handle.close()
        def write(self, text):
            self.handle.write(text[:5])
            raise OSError("injected partial write")
    def fdopen(fd, mode):
        count.append(fd)
        handle = real(fd, mode)
        return Broken(handle) if len(count) - 1 == which else handle
    module["_fdopen"] = fdopen
    assert _opencode(module, "opencode_config", root) == 2
    assert path.read_bytes() == config_before
    assert not (root / "state" / "opencode-config.sha256").exists()
    for directory in (path.parent, root / "state"):
        assert not [p for p in directory.iterdir() if p.name.startswith(".opencode")]


def test_opencode_partial_restore_write_is_incomplete_and_leaves_no_temporary_file(tmp_path):
    """The restore stage itself fails part-way: exit 1, the config unchanged, no temporary file."""
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    doc = json.loads(path.read_text())
    doc["instructions"] = ["kept as it is"]
    path.write_text(json.dumps(doc))
    config_before = path.read_bytes()
    real_replace, real_fdopen = module["_replace"], module["_fdopen"]
    def replace(src, dst):
        if str(dst).endswith("opencode.json"):
            raise OSError("injected config rename failure")
        return real_replace(src, dst)
    opened = []
    class Broken:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self.handle.close()
        def write(self, text):
            self.handle.write(text[:3])
            raise OSError("injected partial restore write")
    def fdopen(fd, mode):
        opened.append(fd)
        handle = real_fdopen(fd, mode)
        return Broken(handle) if len(opened) == 3 else handle  # config, proof, then the restore stage
    module["_replace"], module["_fdopen"] = replace, fdopen
    assert _opencode(module, "opencode_config", root) == 1
    assert len(opened) == 3
    assert path.read_bytes() == config_before
    for directory in (path.parent, root / "state"):
        assert not [p for p in directory.iterdir() if p.name.startswith(".opencode")]


# Leader 13723: an unset flag must prevent runtime even if a refusal regresses. Without the
# flag, every kit command runs behind a PATH boundary whose setsid, unshare and nsenter only
# record the attempt and fail, so no anchor, namespace, backend or CLI can start.
def test_kit_without_the_opt_in_runs_behind_a_boundary_that_cannot_launch(tmp_path, monkeypatch):
    seen = []
    def fake_run(argv, **kwargs):
        seen.append(kwargs["env"])
        return subprocess.CompletedProcess(argv, 2, "", "refused")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.delenv(KIT_RUNTIME_FLAG, raising=False)
    _kit("up", "--root", str(tmp_path / "kit"), "--provider", "claude-code", "--cli", str(FAKE_CLI))
    _kit("status", "--root", str(tmp_path / "kit"), env=_env(EXTRA="1"))
    for env in seen:
        guard = Path(env["PATH"].split(os.pathsep)[0])
        for tool in ("setsid", "unshare", "nsenter"):
            script = guard / tool
            assert script.is_file() and os.access(script, os.X_OK)
            text = script.read_text()
            assert "exit 97" in text and "kit runtime tests are opt-in" in text
    assert len(seen) == 2
    monkeypatch.setenv(KIT_RUNTIME_FLAG, "1")  # opted in: the caller's PATH, unchanged
    _kit("up", "--root", str(tmp_path / "kit2"))
    assert seen[-1]["PATH"] == os.environ["PATH"]


def test_kit_starts_every_namespace_through_path_resolved_tools():
    """The boundary works only if the kit reaches setsid, unshare and nsenter through PATH:
    no absolute path to them, and setsid (resolved from the caller's PATH) starts the outer anchor."""
    import re
    script = KIT.read_text()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"/(?:usr/)?s?bin/(?:setsid|unshare|nsenter)\b", code)
    assert re.search(r"\n\s*setsid env -i [^\n]*\\\n\s*unshare --user --map-root-user --net", code)


def test_launch_guard_control_is_caught(tmp_path, monkeypatch):
    # In-memory control: a guard that doesn't refuse makes the boundary test fail.
    empty = tmp_path / "no-guard"
    empty.mkdir()
    monkeypatch.setitem(globals(), "_launch_guard", lambda: empty)
    with pytest.raises(AssertionError):
        test_kit_without_the_opt_in_runs_behind_a_boundary_that_cannot_launch(tmp_path, monkeypatch)


# V1 review 5899323915: a cleanup that fails is never hidden. When a temporary file can't be
# removed, or the earlier proof can't be restored, setup stops as incomplete (exit 1) and
# names every file it kept; it never reports an unchanged refusal or raises.
def _failing_temp_unlink(monkeypatch):
    real = os.unlink
    def unlink(path, *args, **kwargs):
        if os.path.basename(str(path)).startswith(".opencode-"):
            raise OSError("injected unlink failure")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(os, "unlink", unlink)


def _kept(directory):
    return sorted(p.name for p in directory.iterdir() if p.name.startswith(".opencode-"))


@pytest.mark.parametrize("stage", [0, 1])
def test_opencode_partial_write_with_failed_cleanup_is_incomplete_and_names_the_file(tmp_path, monkeypatch,
                                                                                    capsys, stage):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    config_before = path.read_bytes()
    real = module["_fdopen"]
    opened = []
    class Broken:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self.handle.close()
        def write(self, text):
            self.handle.write(text[:4])
            raise OSError("injected partial write")
    def fdopen(fd, mode):
        opened.append(fd)
        handle = real(fd, mode)
        return Broken(handle) if len(opened) - 1 == stage else handle
    module["_fdopen"] = fdopen
    _failing_temp_unlink(monkeypatch)
    assert _opencode(module, "opencode_config", root) == 1
    err = capsys.readouterr().err
    assert "incomplete" in err
    kept = _kept(path.parent) + _kept(root / "state")
    assert kept and all(name in err for name in kept)
    assert path.read_bytes() == config_before


def test_opencode_failed_restore_with_failed_cleanup_is_incomplete_and_names_the_file(tmp_path, monkeypatch, capsys):
    root, path = _opencode_home(tmp_path)
    module = _helper_module()
    assert _opencode(module, "opencode_config", root) == 0
    doc = json.loads(path.read_text())
    doc["instructions"] = ["kept as it is"]
    path.write_text(json.dumps(doc))
    config_before = path.read_bytes()
    capsys.readouterr()
    real = module["_replace"]
    calls = []
    def failing(src, dst):
        calls.append(str(dst))
        if str(dst).endswith("opencode.json") or len(calls) > 2:
            raise OSError("injected")
        return real(src, dst)
    module["_replace"] = failing
    _failing_temp_unlink(monkeypatch)
    assert _opencode(module, "opencode_config", root) == 1
    err = capsys.readouterr().err
    assert "incomplete" in err and "proof" in err
    kept = _kept(path.parent) + _kept(root / "state")
    assert kept and all(name in err for name in kept)
    assert path.read_bytes() == config_before


def test_hidden_cleanup_failure_control_is_caught(tmp_path, monkeypatch, capsys):
    # In-memory control: ignoring kept files would report an unchanged refusal again.
    _opencode_control(tmp_path, monkeypatch, "        if config_changed or not restored or kept:\n",
                      "        if config_changed or not restored:\n")
    (tmp_path / "t").mkdir()
    with pytest.raises(AssertionError):
        test_opencode_partial_write_with_failed_cleanup_is_incomplete_and_names_the_file(
            tmp_path / "t", monkeypatch, capsys, 0)


# V1 review 5899358665: up keeps the helper's outcome. The OpenCode setup step of up is run
# on its own, with the kit's real refuse/incomplete/fail and a mocked kitpy; no kit starts.
def _opencode_setup_step(helper_code: int) -> subprocess.CompletedProcess:
    script = KIT.read_text()
    reporters = "\n".join(line for line in script.splitlines()
                          if line.startswith(("refuse() {", "fail() {", "incomplete() {")))
    start = script.index("  # #912: an OpenCode member reaches only the kit stub.")
    end = script.index("  launch=\"$(in_ns", start)
    step = script[start:end]
    program = "\n".join([
        reporters,
        f"kitpy() {{ echo 'helper: details' >&2; return {helper_code}; }}",
        'ROOT=/nonexistent/kit KIT_STUB_URL=http://127.0.0.1:18781 PROVIDER=opencode-cli',
        "step() {", step, "}", "step",  # inside a function, as in up
        "echo continued",
    ])
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=10,
                          env={"PATH": "/usr/bin:/bin"})


@pytest.mark.parametrize("helper, code, prefix", [(0, 0, None), (1, 1, "incomplete:"), (2, 2, "refused:")])
def test_up_keeps_the_opencode_helper_outcome(helper, code, prefix):
    result = _opencode_setup_step(helper)
    assert result.returncode == code, result.stderr
    if prefix is None:
        assert result.stdout.strip() == "continued"
    else:
        assert "continued" not in result.stdout
        assert f"isolated-runtime-kit: {prefix}" in result.stderr and "helper: details" in result.stderr


def test_opencode_outcome_control_is_caught(tmp_path, monkeypatch):
    # In-memory control: routing the helper's incomplete outcome to refuse again is caught.
    _opencode_control(tmp_path, monkeypatch, '      1) incomplete "the OpenCode config setup did not finish cleanly',
                      '      1) refuse "the OpenCode config setup did not finish cleanly')
    monkeypatch.setitem(globals(), "KIT", Path(os.environ["RUNTIME_KIT_SCRIPT_UNDER_TEST"]))
    with pytest.raises(AssertionError):
        test_up_keeps_the_opencode_helper_outcome(1, 1, "incomplete:")


# --- Scripted stub replies (#912 A1a) ------------------------------------------------------
# The stub can serve a script of text and tool-call turns, so a provider CLI can be driven
# through a tool call. These tests load the stub module by path and run its server on
# 127.0.0.1 port 0 in a thread: no subprocess, no namespace, no kit.
STUB = REPO / "scripts" / "runtime-kit" / "stub_provider.py"
STUB_SCRIPT = [{"text": "first"}, {"tool_call": {"name": "read", "arguments": {"filePath": "README.md"}}},
               {"text": "last"}]


def _stub_module(path: Path = STUB):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"kit_stub_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _StubServer:
    """The stub's own server on an ephemeral loopback port, in a thread of this process."""

    def __init__(self, module, tmp_path: Path, script: list | None):
        import threading
        self.log = tmp_path / "stub-requests.jsonl"
        script_path = None
        if script is not None:
            script_path = tmp_path / "stub-script.json"
            script_path.write_text(json.dumps(script))
        turns = module.load_script(script_path) if script_path else None
        self.server = module.make_server(0, self.log, turns)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def chat(self, stream: bool = False, prompt: str = "secret prompt text"):
        import urllib.request
        body = json.dumps({"model": "stub", "stream": stream,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        request = urllib.request.Request(self.url + "/v1/chat/completions", data=body,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read().decode()
        if not stream:
            return json.loads(raw)
        chunks = [line[len("data: "):] for line in raw.split("\n\n") if line]
        assert chunks[-1] == "[DONE]"
        return [json.loads(chunk) for chunk in chunks[:-1]]

    def entries(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def _with_stub(module, tmp_path, script, check):
    server = _StubServer(module, tmp_path, script)
    try:
        return check(server)
    finally:
        server.close()


def _strict_json(text):
    def refuse(constant):
        raise AssertionError(f"served arguments are not strict JSON: {constant}")
    return json.loads(text, parse_constant=refuse)


def _check_json_turns(server):
    first, call, last, after = (server.chat() for _ in range(4))
    assert first["choices"][0]["message"] == {"role": "assistant", "content": "first"}
    assert first["choices"][0]["finish_reason"] == "stop"
    message = call["choices"][0]["message"]
    assert call["choices"][0]["finish_reason"] == "tool_calls"
    assert message["role"] == "assistant" and message.get("content") is None
    assert message["tool_calls"] == [{"id": "call_stub_1", "type": "function",
                                      "function": {"name": "read", "arguments": '{"filePath": "README.md"}'}}]
    assert _strict_json(message["tool_calls"][0]["function"]["arguments"]) == {"filePath": "README.md"}
    assert last["choices"][0]["message"]["content"] == "last"
    assert after["choices"][0]["message"]["content"] == "stub reply from the isolated runtime kit"  # script ended


def _check_sse_turns(server):
    first, call = server.chat(stream=True), server.chat(stream=True)
    assert [c["choices"][0]["delta"] for c in first] == [{"role": "assistant", "content": "first"}, {}]
    assert first[-1]["choices"][0]["finish_reason"] == "stop"
    assert all(c["object"] == "chat.completion.chunk" for c in first + call)
    deltas = [c["choices"][0]["delta"] for c in call]
    assert deltas == [{"role": "assistant"},
                      {"tool_calls": [{"index": 0, "id": "call_stub_1", "type": "function",
                                       "function": {"name": "read", "arguments": '{"filePath": "README.md"}'}}]},
                      {}]
    assert call[-1]["choices"][0]["finish_reason"] == "tool_calls"


def _check_log(server):
    for stream in (False, True, False, False):
        server.chat(stream=stream)
    entries = server.entries()
    assert [(e["turn"], e["kind"]) for e in entries] == [(0, "text"), (1, "tool_call"), (2, "text"),
                                                          (None, "fallback")]
    text = server.log.read_text()
    assert "secret prompt text" not in text and "README.md" not in text and "first" not in text
    assert all(len(e["sha256"]) == 64 for e in entries)


def test_stub_script_serves_text_and_tool_call_turns_as_json(tmp_path):
    _with_stub(_stub_module(), tmp_path, STUB_SCRIPT, _check_json_turns)


def test_stub_script_serves_text_and_tool_call_turns_as_sse(tmp_path):
    _with_stub(_stub_module(), tmp_path, STUB_SCRIPT, _check_sse_turns)


def test_stub_script_log_keeps_turn_and_kind_but_no_text(tmp_path):
    _with_stub(_stub_module(), tmp_path, STUB_SCRIPT, _check_log)


def test_stub_script_serves_finite_number_arguments_as_strict_json(tmp_path):
    script = [{"tool_call": {"name": "read", "arguments": {"limit": 1.5e308, "low": -1.5e308, "offset": -0.0,
                                                            "tiny": 0.0, "n": 3}}}]
    path = tmp_path / "underflow.json"  # 1e-400 underflows to 0.0: finite, so it is kept
    path.write_text('[{"tool_call": {"name": "read", "arguments": {"tiny": 1e-400}}}]')
    assert _stub_module().load_script(path) == [{"tool_call": {"name": "read", "arguments": {"tiny": 0.0}}}]

    def check(server):
        arguments = server.chat()["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        assert _strict_json(arguments) == {"limit": 1.5e308, "low": -1.5e308, "offset": -0.0, "tiny": 0.0, "n": 3}
    _with_stub(_stub_module(), tmp_path, script, check)


def test_stub_script_absent_keeps_the_default_replies_and_log(tmp_path):
    def check(server):
        plain, chunks = server.chat(), server.chat(stream=True)
        assert plain["choices"][0] == {"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": "stub reply from the isolated runtime kit"}}
        assert [c["choices"][0]["delta"] for c in chunks] == [
            {"role": "assistant", "content": "stub reply from the isolated runtime kit"}, {}]
        assert [sorted(e) for e in server.entries()] == [["bytes", "model", "path", "sha256", "time"]] * 2
    _with_stub(_stub_module(), tmp_path, None, check)


def _bad_scripts():
    turn = {"text": "x"}
    return {
        "not_json": "{",
        "not_a_list": json.dumps({"text": "x"}),
        "empty": "[]",
        "too_many_turns": json.dumps([turn] * 65),
        "oversized": json.dumps([{"text": "x" * (64 << 10)}]),
        "extra_key": json.dumps([{"text": "x", "tool_call": {"name": "read", "arguments": {}}}]),
        "unknown_kind": json.dumps([{"image": "x"}]),
        "text_not_string": json.dumps([{"text": 1}]),
        "tool_extra_key": json.dumps([{"tool_call": {"name": "read", "arguments": {}, "id": "x"}}]),
        "tool_no_name": json.dumps([{"tool_call": {"name": "", "arguments": {}}}]),
        "tool_arguments_not_object": json.dumps([{"tool_call": {"name": "read", "arguments": "{}"}}]),
        "nan_argument": '[{"tool_call": {"name": "read", "arguments": {"x": NaN}}}]',
        "infinity_argument": '[{"tool_call": {"name": "read", "arguments": {"x": Infinity}}}]',
        "neg_infinity_argument": '[{"tool_call": {"name": "read", "arguments": {"x": [-Infinity]}}}]',
        "deep_nesting": b"[" * 10000 + b"0" + b"]" * 9999,  # 20,000 bytes: within the size limit
        "exponent_overflow": '[{"tool_call": {"name": "read", "arguments": {"nested": [1e400]}}}]',
        "neg_exponent_overflow": '[{"tool_call": {"name": "read", "arguments": {"deep": {"x": [-1e400]}}}}]',
        "huge_integer": '[{"tool_call": {"name": "read", "arguments": {"n": %s}}}]' % ("9" * 5000),  # digit limit
    }


@pytest.mark.parametrize("case", sorted(_bad_scripts()))
def test_stub_script_refuses_a_malformed_script_before_serving(tmp_path, case, capsys):
    module = _stub_module()
    path = tmp_path / "stub-script.json"
    content = _bad_scripts()[case]
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    with pytest.raises(module.ScriptError):
        module.load_script(path)
    bound = []
    module.make_server = lambda *args: bound.append(args)  # main must refuse before it binds
    assert module.main(["--port", "0", "--log", str(tmp_path / "log.jsonl"), "--script", str(path)]) == 2
    assert bound == [] and "refused" in capsys.readouterr().err


def test_stub_script_accepts_the_limits(tmp_path):
    module = _stub_module()
    path = tmp_path / "stub-script.json"
    path.write_text(json.dumps([{"text": "x"}] * 64))
    assert len(module.load_script(path)) == 64


# Mutation controls: each patched copy of the stub must make a check above fail.
_STUB_CONTROLS = {
    "no_tool_call_branch": ('if "tool_call" in turn:', 'if "tool_call_removed" in turn:'),
    "sse_tool_call_as_text": ('{"tool_calls": [dict(call, index=0)]}', '{"content": "text"}'),
    "no_validation": ("def load_script(path", "def _unchecked(path"),
    "no_constant_check": ("parse_constant=_refuse_constant", "parse_constant=None"),
    "no_float_check": ("parse_float=_finite_float", "parse_float=None"),
}


@pytest.mark.parametrize("control", sorted(_STUB_CONTROLS))
def test_stub_script_controls_are_caught(tmp_path, control):
    old, new = _STUB_CONTROLS[control]
    source = STUB.read_text()
    assert source.count(old) == 1, old
    source = source.replace(old, new)
    if control == "no_validation":
        source += "\n\ndef load_script(path):\n    return json.loads(Path(path).read_text())\n"
    mutated = tmp_path / "mutated_stub.py"
    mutated.write_text(source)
    module = _stub_module(mutated)
    failed = []
    for name, check in (("json", _check_json_turns), ("sse", _check_sse_turns), ("log", _check_log)):
        work = tmp_path / name
        work.mkdir()
        try:
            _with_stub(module, work, STUB_SCRIPT, check)
        except (AssertionError, KeyError, TypeError, IndexError, OSError):
            failed.append(name)
    if control in ("no_validation", "no_constant_check", "no_float_check"):
        path = tmp_path / "bad.json"
        path.write_text(_bad_scripts()[{"no_validation": "extra_key", "no_constant_check": "nan_argument",
                                        "no_float_check": "exponent_overflow"}[control]])
        try:
            module.load_script(path)
        except module.ScriptError:
            pass
        else:
            failed.append("validation")
    assert failed, f"control {control} was not caught"
    assert STUB.read_text().count(old) == 1  # the control changed only its own copy


# --- The kit passes a scripted stub (#912 A1b) ---------------------------------------------
# up copies a validated script into its own state, the stub is started with that copy, and
# status proves the copy against its recorded digest. Model tests run the kit helper in
# process; the step tests run single extracted steps of up with a mocked kitpy. No kit starts.
def _stub_kit(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_KIT_REPO_ROOT", str(REPO))
    root = tmp_path / "kit"
    (root / "state").mkdir(parents=True)
    return _helper_module(), root


def _helper_call(module, command, *args):
    try:
        module[command](*map(str, args))
    except SystemExit as exc:
        return exc.code
    return 0


def _stub_source(tmp_path, case):
    path = tmp_path / "source.json"
    if case == "missing":
        return path
    if case == "symlink":
        real = tmp_path / "real.json"
        real.write_text(json.dumps(STUB_SCRIPT))
        path.symlink_to(real)
    elif case == "directory":
        path.mkdir()
    elif case == "fifo":
        os.mkfifo(path)
    elif case == "oversized":
        path.write_text(json.dumps([{"text": "x" * (64 << 10)}]))
    else:
        content = _bad_scripts()[{"nan": "nan_argument", "extra_key": "extra_key",
                                  "overflow": "exponent_overflow"}.get(case, case)] if case != "valid" else (
            json.dumps(STUB_SCRIPT))
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


SOURCE_REFUSALS = ["missing", "symlink", "directory", "fifo", "oversized", "nan", "extra_key", "overflow",
                   "deep_nesting"]


@pytest.mark.parametrize("case", SOURCE_REFUSALS)
def test_stub_script_source_is_refused_without_blocking(tmp_path, monkeypatch, case):
    import threading
    module, _root = _stub_kit(tmp_path, monkeypatch)
    source = _stub_source(tmp_path, case)
    result = []

    def check():
        try:
            result.append(_helper_call(module, "stub_script_check_source", source))
        except Exception as exc:  # reported as a failure of this test, not a thread warning
            result.append(exc)
    worker = threading.Thread(target=check, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "the source check blocked"  # a FIFO must not block the open or a read
    assert result == [2]


def test_stub_script_source_accepts_a_valid_script(tmp_path, monkeypatch):
    module, _root = _stub_kit(tmp_path, monkeypatch)
    assert _helper_call(module, "stub_script_check_source", _stub_source(tmp_path, "valid")) == 0


def test_stub_script_copy_is_private_and_recorded(tmp_path, monkeypatch, capsys):
    import hashlib
    module, root = _stub_kit(tmp_path, monkeypatch)
    source = _stub_source(tmp_path, "valid")
    assert _helper_call(module, "stub_script", root, source) == 0
    copy, digest = root / "state" / "stub-script.json", root / "state" / "stub-script.sha256"
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert copy.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600 and stat.S_IMODE(digest.stat().st_mode) == 0o600
    assert digest.read_text() == expected + "\n"
    assert capsys.readouterr().out.strip() == expected
    assert _helper_call(module, "stub_script_verify", root) == 0
    assert capsys.readouterr().out.strip() == expected


@pytest.mark.parametrize("case", ["existing_copy", "existing_digest", "state_symlink", "no_state", "nan"])
def test_stub_script_copy_refusals_keep_what_is_there(tmp_path, monkeypatch, case):
    module, root = _stub_kit(tmp_path, monkeypatch)
    source = _stub_source(tmp_path, "nan" if case == "nan" else "valid")
    state = root / "state"
    if case == "existing_copy":
        (state / "stub-script.json").write_text("other")
    elif case == "existing_digest":
        (state / "stub-script.sha256").write_text("other")
    elif case in ("state_symlink", "no_state"):
        state.rmdir()
        if case == "state_symlink":
            (tmp_path / "elsewhere").mkdir()
            state.symlink_to(tmp_path / "elsewhere")
    before = {p.name: p.read_bytes() for p in state.iterdir()} if state.is_dir() else None
    assert _helper_call(module, "stub_script", root, source) == 2
    after = {p.name: p.read_bytes() for p in state.iterdir()} if state.is_dir() else None
    assert after == before
    if case == "state_symlink":
        assert list((tmp_path / "elsewhere").iterdir()) == []


@pytest.mark.parametrize("failing", [1, 2])  # the copy write, or the digest write after the copy
def test_stub_script_failed_write_removes_only_its_own_files(tmp_path, monkeypatch, capsys, failing):
    module, root = _stub_kit(tmp_path, monkeypatch)
    calls = []

    def write(fd, data):
        calls.append(fd)
        if len(calls) == failing:
            raise OSError(28, "No space left on device")
        return os.write(fd, data)
    module["_write"] = write
    assert _helper_call(module, "stub_script", root, _stub_source(tmp_path, "valid")) == 2
    assert list((root / "state").iterdir()) == []
    err = capsys.readouterr().err
    assert "nothing was kept" in err and "incomplete" not in err


@pytest.mark.parametrize("change", ["replaced_file", "replaced_symlink", "uncertain"])
def test_stub_script_failed_write_keeps_a_replaced_or_uncertain_file(tmp_path, monkeypatch, capsys, change):
    module, root = _stub_kit(tmp_path, monkeypatch)
    state = root / "state"
    copy = state / "stub-script.json"

    def write(fd, data):
        if change == "replaced_file":
            copy.unlink()
            copy.write_text("someone else")
        elif change == "replaced_symlink":
            copy.unlink()
            copy.symlink_to(tmp_path / "anything")
        else:
            state.chmod(0o600)  # the identity can no longer be read
        raise OSError(5, "Input/output error")
    module["_write"] = write
    try:
        code = _helper_call(module, "stub_script", root, _stub_source(tmp_path, "valid"))
    finally:
        state.chmod(0o700)
    assert code == 1
    err = capsys.readouterr().err
    assert "incomplete" in err and str(copy) in err
    assert os.path.lexists(copy)
    if change == "replaced_file":
        assert copy.read_text() == "someone else"


@pytest.mark.parametrize("tamper", ["changed_copy", "copy_symlink", "digest_missing", "copy_missing",
                                    "digest_symlink"])
def test_stub_script_verify_refuses_an_unproved_copy(tmp_path, monkeypatch, tamper):
    module, root = _stub_kit(tmp_path, monkeypatch)
    assert _helper_call(module, "stub_script", root, _stub_source(tmp_path, "valid")) == 0
    copy, digest = root / "state" / "stub-script.json", root / "state" / "stub-script.sha256"
    if tamper == "changed_copy":
        copy.chmod(0o600)
        copy.write_text(json.dumps([{"text": "changed"}]))
    elif tamper in ("copy_symlink", "digest_symlink"):
        target = copy if tamper == "copy_symlink" else digest
        saved = tmp_path / "saved"
        target.rename(saved)
        target.symlink_to(saved)
    elif tamper == "digest_missing":
        digest.unlink()
    else:
        copy.unlink()
    assert _helper_call(module, "stub_script_verify", root) == 2


def test_stub_script_verify_without_a_script_passes_and_prints_nothing(tmp_path, monkeypatch, capsys):
    module, root = _stub_kit(tmp_path, monkeypatch)
    assert _helper_call(module, "stub_script_verify", root) == 0
    assert capsys.readouterr().out == ""


def _kit_step(start: str, end: str, body: list[str]) -> subprocess.CompletedProcess:
    """One extracted step of up, with the kit's real refuse/incomplete/fail; nothing starts."""
    script = KIT.read_text()
    reporters = "\n".join(line for line in script.splitlines()
                          if line.startswith(("refuse() {", "fail() {", "incomplete() {")))
    first = script.index(start)
    step = script[first:script.index(end, first)]
    program = "\n".join([reporters, *body[:-1], "step() {", step, body[-1], "}", "step", "echo continued"])
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=10,
                          env={"PATH": "/usr/bin:/bin"})


@pytest.mark.parametrize("helper, code, prefix", [(0, 0, None), (1, 1, "incomplete:"), (2, 2, "refused:"),
                                                  (7, 1, "failed:")])
def test_stub_script_up_copy_step_keeps_the_helper_outcome(helper, code, prefix):
    result = _kit_step("  if [[ -n \"$STUB_SCRIPT\" ]]; then  # #912: the stub serves only this private",
                       "\n  fi\n", [f"kitpy() {{ echo 'helper: details' >&2; return {helper}; }}",
                                    "ROOT=/nonexistent/kit STUB_SCRIPT=/nonexistent/script.json", "  fi"])
    assert result.returncode == code, result.stderr
    if prefix is None:
        assert result.stdout.strip() == "continued"
    else:
        assert "continued" not in result.stdout and f"isolated-runtime-kit: {prefix}" in result.stderr


@pytest.mark.parametrize("with_copy", [True, False])
def test_stub_script_spawn_passes_the_copy_only_when_it_exists(tmp_path, with_copy):
    root = tmp_path / "kit"
    (root / "state").mkdir(parents=True)
    if with_copy:
        (root / "state" / "stub-script.json").write_text("[]")
    result = _kit_step("  local stub_args=()", "\n", [f"ROOT={root}",
                       '  printf "<%s>" "${stub_args[@]}"; echo'])
    expected = f"<--script><{root}/state/stub-script.json>" if with_copy else "<>"
    assert result.returncode == 0 and result.stdout.splitlines()[0] == expected, result.stderr


def test_stub_script_kit_up_refuses_a_malformed_script_before_creating_anything(tmp_path):
    source = _stub_source(tmp_path, "nan")
    result = _kit("up", "--root", str(tmp_path / "kit"), "--provider", "claude-code", "--cli", str(FAKE_CLI),
                  "--stub-script", str(source))
    assert result.returncode == 2 and "refused: the stub script was not accepted" in result.stderr
    assert "non-finite" in result.stderr  # the stub's own validator decided
    assert not (tmp_path / "kit").exists()


def test_stub_script_kit_status_refuses_the_option(tmp_path):
    root = tmp_path / "kit"
    root.mkdir()
    result = _kit("status", "--root", str(root), "--stub-script", str(_stub_source(tmp_path, "valid")))
    assert result.returncode == 2 and "only for up" in result.stderr
    assert list(root.iterdir()) == []


# Mutation controls for A1b: each mutated copy of the kit must make a named test fail.
_KIT_STUB_CONTROLS = {
    "no_regular_file_check": ("        if not stat.S_ISREG(os.fstat(fd).st_mode):\n",
                              "        if False:\n"),
    "no_status_digest_check": ("    if hashlib.sha256(data).hexdigest() != recorded:\n", "    if False:\n"),
    "spawn_ignores_the_copy": ('stub_args=(--script "$ROOT/state/stub-script.json")', "stub_args=()"),
    "no_source_validation": ("def _validate_stub_script(data):\n", "def _validate_stub_script(data):\n    return\n"),
    "no_cleanup_identity_check": ("(now.st_dev, now.st_ino) != (created.st_dev, created.st_ino)", "False"),
}


@pytest.mark.parametrize("control", sorted(_KIT_STUB_CONTROLS))
def test_stub_script_kit_controls_are_caught(tmp_path, monkeypatch, capsys, control):
    import hashlib
    real = KIT
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    old, new = _KIT_STUB_CONTROLS[control]
    _opencode_control(tmp_path, monkeypatch, old, new)
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises((AssertionError, OSError)):
        if control == "no_regular_file_check":
            test_stub_script_source_is_refused_without_blocking(work, monkeypatch, "directory")
        elif control == "no_status_digest_check":
            test_stub_script_verify_refuses_an_unproved_copy(work, monkeypatch, "changed_copy")
        elif control == "spawn_ignores_the_copy":
            monkeypatch.setitem(globals(), "KIT", Path(os.environ["RUNTIME_KIT_SCRIPT_UNDER_TEST"]))
            test_stub_script_spawn_passes_the_copy_only_when_it_exists(work, True)
        elif control == "no_source_validation":
            test_stub_script_source_is_refused_without_blocking(work, monkeypatch, "nan")
        else:
            test_stub_script_failed_write_keeps_a_replaced_or_uncertain_file(work, monkeypatch, capsys,
                                                                              "replaced_file")
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before  # only the mutated copy changed


# V1 review 5901413154: the final digest check of capture must keep the verifier's status.
# The kit's own capture_evidence and status publish block run verbatim against a temporary
# root, with the real kit helper (stub-script-verify, publish, discard) and only the runtime
# boundaries mocked; nothing starts and no namespace is entered.
def _capture_harness(root: Path, case: str) -> subprocess.CompletedProcess:
    script = KIT.read_text()
    reporters = "\n".join(line for line in script.splitlines()
                          if line.startswith(("refuse() {", "fail() {", "incomplete() {", "note() {")))
    kitpy_source = script[script.index("KITPY='\n"):script.index("\n'\nkitpy()") + 2]
    capture = script[script.index("capture_evidence() {"):script.index("\n}\n", script.index("capture_evidence() {")) + 3]
    block_start = script.index("  local id att\n")
    block = script[block_start:script.index("\n}\n", block_start)]
    transition = {
        "absent_to_invalid": 'printf "[]" >"$ROOT/state/stub-script.json"',  # a copy without its digest
        "valid_to_tampered": 'printf "[{\\"text\\": \\"changed\\"}]" >"$ROOT/state/stub-script.json"',
    }.get(case, ":")
    program = "\n".join([
        "set -euo pipefail",
        reporters,
        kitpy_source,
        f'real_kitpy() {{ RUNTIME_KIT_REPO_ROOT="{REPO}" python3 -I -c "$KITPY" "$@"; }}',
        'kitpy() { case "$1" in kit-provider) echo claude-code ;; verify|opencode-check|opencode-final) ;;'
        ' *) real_kitpy "$@" ;; esac; }',
        "in_ns() { echo '{\"net\": \"n\", \"user\": \"u\"}'; }",
        "registration_row() { echo '{}'; }",
        f"summary() {{ echo '{{}}'; {transition}; }}",
        f'ROOT="{root}" KIT_STUB_URL=http://127.0.0.1:18781',
        capture,
        "status_publish() {", block, "}",
        "status_publish",
    ])
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=30,
                          env={"PATH": "/usr/bin:/bin"})


def _capture_root(tmp_path, monkeypatch, case):
    root = tmp_path / "kit"
    (root / "state").mkdir(parents=True)
    (root / "state" / "processes.json").write_text("{}")
    previous = root / "evidence.d" / ("0" * 16)
    previous.mkdir(parents=True)
    (previous / "MANIFEST.sha256").write_text("previous evidence\n")
    (root / "evidence").symlink_to("evidence.d/" + "0" * 16)
    if case in ("valid", "valid_to_tampered"):
        monkeypatch.setenv("RUNTIME_KIT_REPO_ROOT", str(REPO))
        assert _helper_call(_helper_module(), "stub_script", root, _stub_source(tmp_path, "valid")) == 0
    return root


@pytest.mark.parametrize("case", ["absent_to_invalid", "valid_to_tampered"])
def test_stub_script_change_during_capture_publishes_nothing(tmp_path, monkeypatch, case):
    root = _capture_root(tmp_path, monkeypatch, case)
    result = _capture_harness(root, case)
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "the published evidence is unchanged" in result.stderr
    assert os.readlink(root / "evidence") == "evidence.d/" + "0" * 16
    assert (root / "evidence" / "MANIFEST.sha256").read_text() == "previous evidence\n"
    assert sorted(p.name for p in (root / "evidence.d").iterdir()) == ["0" * 16]  # the new attempt is removed


@pytest.mark.parametrize("case", ["absent", "valid"])
def test_stub_script_capture_publishes_truthful_evidence(tmp_path, monkeypatch, case):
    root = _capture_root(tmp_path, monkeypatch, case)
    result = _capture_harness(root, case)
    assert result.returncode == 0, (result.stdout, result.stderr)
    published = root / "evidence"
    assert os.readlink(published) != "evidence.d/" + "0" * 16
    manifest = (published / "MANIFEST.sha256").read_text()
    if case == "absent":
        assert not (published / "stub-script.sha256").exists() and "stub-script.sha256" not in manifest
    else:
        recorded = (root / "state" / "stub-script.sha256").read_text()
        assert (published / "stub-script.sha256").read_text() == recorded
        assert "stub-script.sha256" in manifest


def _final_check_step() -> subprocess.CompletedProcess:
    """The final checks of capture alone, with a verifier that refuses and prints nothing."""
    script = KIT.read_text()
    start = script.index("  # The provider and the config are proved again")
    lines = script[start:script.index("  if ((${#opencode[@]})); then", start)]
    program = "\n".join([
        'kitpy() { if [[ "$1" == kit-provider ]]; then echo claude-code; else return 2; fi; }',
        "step() {", "  local provider=claude-code stub_sha=''", lines, "  echo manifest-ran", "}",
        "step && echo step-ok || echo step-failed",
    ])
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, timeout=10,
                          env={"PATH": "/usr/bin:/bin", "ROOT": "/nonexistent/kit"})


def test_stub_script_final_check_keeps_the_verifier_status():
    # A refusing verifier must stop capture before its manifest, even when no script was in
    # use (an empty expected digest).
    result = _final_check_step()
    assert result.stdout.split() == ["step-failed"], result.stdout


def test_stub_script_capture_status_control_is_caught(tmp_path, monkeypatch):
    # In-memory control: restoring the comparison that discards the verifier status is caught.
    import hashlib
    real = KIT
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    _opencode_control(tmp_path, monkeypatch,
                      '  final_sha="$(kitpy stub-script-verify "$ROOT")" || return 1\n'
                      '  [[ "$final_sha" == "$stub_sha" ]] || return 1\n',
                      '  [[ "$(kitpy stub-script-verify "$ROOT")" == "$stub_sha" ]] || return 1\n')
    monkeypatch.setitem(globals(), "KIT", Path(os.environ["RUNTIME_KIT_SCRIPT_UNDER_TEST"]))
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(AssertionError):
        test_stub_script_change_during_capture_publishes_nothing(work, monkeypatch, "absent_to_invalid")
    with pytest.raises(AssertionError):
        test_stub_script_final_check_keeps_the_verifier_status()
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before
