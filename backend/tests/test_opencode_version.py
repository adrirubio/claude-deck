"""OpenCode 2 version gate (#730).

Every probe here runs a fake script written to tmp_path. No real OpenCode or
other third-party CLI is executed. Member identity is checked against a fake
/proc tree, so no live process is inspected.
"""
import os
import time

import pytest

from app.services import opencode_version as ov
from app.utils import peer_process


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize(
    "output,expected",
    [
        ("opencode v2.0.29\n", (2, 0, 29)),
        ("2.0.29\n", (2, 0, 29)),
        ("v2.2.7", (2, 2, 7)),
        ("opencode 1.17.11", (1, 17, 11)),
        ("1.0.0", (1, 0, 0)),
        ("opencode v2.1.0-beta.3", (2, 1, 0)),
        ("warning: something\nopencode v2.0.0\n", (2, 0, 0)),
    ],
)
def test_parse_accepts_prefixed_and_bare_versions(output, expected):
    assert ov.parse_opencode_version(output) == expected


@pytest.mark.parametrize(
    "output",
    ["", "opencode", "version 2", "2.0", "opencode v2.0.29 extra", "codex-cli 2.0.0", "v2.x.1"],
)
def test_parse_returns_none_for_anything_else(output):
    assert ov.parse_opencode_version(output) is None


# ---------------------------------------------------------------- probe of the trusted binary

def _fake_opencode(directory, body: str):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "opencode"
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    ov.clear_cache()
    yield bin_dir
    ov.clear_cache()


@pytest.mark.parametrize(
    "body,state,version",
    [
        ('echo "opencode v2.0.29"', "ok", "2.0.29"),
        ('echo "2.0.29"', "ok", "2.0.29"),
        ('echo "opencode v2.0.0"', "ok", "2.0.0"),
        ('echo "opencode 1.17.11"', "unsupported", "1.17.11"),
        ('echo "not a version"', "unknown", None),
        ('echo "opencode v2.0.29"; exit 3', "unknown", None),
    ],
)
def test_gate_states_from_fake_binaries(fake_path, body, state, version):
    _fake_opencode(fake_path, body)
    gate = ov.opencode_version_gate()
    assert gate.state == state
    assert gate.version == version
    assert gate.ready is (state == "ok")
    if state == "unsupported":
        assert gate.reason == ov.REASON_REQUIRED
    if state == "unknown":
        assert gate.reason == ov.REASON_UNKNOWN


def test_gate_is_unknown_without_a_binary(fake_path):
    gate = ov.opencode_version_gate()
    assert gate.state == "unknown" and not gate.ready and gate.identity is None


def test_gate_times_out_as_unknown(fake_path, monkeypatch):
    monkeypatch.setattr(ov, "PROBE_TIMEOUT_SECONDS", 0.2)
    _fake_opencode(fake_path, 'sleep 5; echo "opencode v2.0.29"')
    started = time.monotonic()
    gate = ov.opencode_version_gate()
    assert gate.state == "unknown"
    assert time.monotonic() - started < 3


def test_probe_runs_with_an_empty_environment_allowlist(fake_path, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_CITY_TEAM_SLOT_ID", "29")
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "must-not-leak")
    seen = tmp_path / "env.txt"
    _fake_opencode(fake_path, f'env > "{seen}"; echo "opencode v2.0.29"')
    assert ov.opencode_version_gate().ready
    names = {line.split("=", 1)[0] for line in seen.read_text().splitlines() if "=" in line}
    assert {"HOME", "PATH", "LANG"} <= names
    assert names <= {"HOME", "PATH", "LANG", "PWD", "SHLVL", "_", "OLDPWD"}
    assert "must-not-leak" not in seen.read_text()


def test_probe_result_is_cached_and_invalidated_when_the_binary_changes(fake_path, tmp_path):
    counter = tmp_path / "count"
    binary = _fake_opencode(fake_path, f'echo x >> "{counter}"; echo "opencode v2.0.29"')
    assert ov.opencode_version_gate().ready
    assert ov.opencode_version_gate().ready
    assert counter.read_text().count("x") == 1  # second call came from the cache
    # Replace the binary: a new inode and mtime must miss the cache.
    binary.unlink()
    _fake_opencode(fake_path, f'echo x >> "{counter}"; echo "opencode 1.17.11"')
    gate = ov.opencode_version_gate()
    assert gate.state == "unsupported"
    assert counter.read_text().count("x") == 2


def test_probe_result_expires_after_the_ttl(fake_path, tmp_path, monkeypatch):
    counter = tmp_path / "count"
    _fake_opencode(fake_path, f'echo x >> "{counter}"; echo "opencode v2.0.29"')
    clock = [1000.0]
    monkeypatch.setattr(ov, "_monotonic", lambda: clock[0])
    ov.opencode_version_gate()
    clock[0] += ov.CACHE_TTL_SECONDS + 1
    ov.opencode_version_gate()
    assert counter.read_text().count("x") == 2


def test_binary_replaced_during_the_probe_is_unknown(fake_path, tmp_path):
    # The fake binary replaces itself while it runs: the identity observed after
    # the probe no longer matches the one that was probed.
    path = fake_path / "opencode"
    replacement = tmp_path / "replacement"
    replacement.write_text('#!/bin/sh\necho "opencode v2.0.29"\n')
    replacement.chmod(0o755)
    _fake_opencode(fake_path, f'cp "{replacement}" "{path}.new"; mv -f "{path}.new" "{path}"; echo "opencode v2.0.29"')
    assert ov.opencode_version_gate().state == "unknown"


# ---------------------------------------------------------------- member process identity

class FakeProc:
    """A fake /proc tree with stat, exe and task/<pid>/children entries."""

    def __init__(self, root):
        self.root = root
        root.mkdir()
        # pane_is_alive_strict reads <root>/self/stat to prove /proc is readable.
        self.add(999999, 1, "self", start="1", path_name="self")

    def add(self, pid, ppid, name, *, start="100", exe=None, children=(), path_name=None):
        directory = self.root / (path_name or str(pid))
        directory.mkdir(exist_ok=True)
        fields = ["S", str(ppid)] + ["0"] * 17 + [start, "0", "0"]
        (directory / "stat").write_text(f"{pid} ({name}) " + " ".join(fields) + "\n")
        task = directory / "task" / str(pid)
        task.mkdir(parents=True, exist_ok=True)
        (task / "children").write_text(" ".join(str(c) for c in children) + (" " if children else ""))
        if exe is not None:
            link = directory / "exe"
            if link.is_symlink():
                link.unlink()
            os.symlink(str(exe), link)
        return directory


@pytest.fixture
def proc(tmp_path, monkeypatch):
    fake = FakeProc(tmp_path / "proc")
    monkeypatch.setattr(peer_process, "_PROC_ROOT", str(fake.root))
    return fake


@pytest.fixture
def trusted_v2(fake_path):
    binary = _fake_opencode(fake_path, 'echo "opencode v2.0.29"')
    return binary


def _shell():
    return "/bin/sh"


def test_registration_accepts_a_member_running_the_trusted_v2_binary(proc, trusted_v2):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 10, "opencode", exe=trusted_v2, children=(30,))
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    gate = ov.member_gate_for_peer(pane, (30, 20, 10))
    assert gate.state == "ok" and gate.ready


def test_registration_accepts_a_wrapper_parent_only_through_its_trusted_child(proc, trusted_v2):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=40)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 10, "node", exe="/usr/bin/node")  # wrapper named node, not trusted
    proc.add(30, 20, "opencode", exe=trusted_v2)
    proc.add(40, 30, "python", exe="/usr/bin/python3")
    assert ov.member_gate_for_peer(pane, (40, 30, 20, 10)).ready
    # Without the trusted child, a wrapper alone never counts.
    assert not ov.member_gate_for_peer(pane, (40, 20, 10)).ready


def test_registration_refuses_a_member_running_another_binary(proc, trusted_v2, tmp_path):
    other = _fake_opencode(tmp_path / "elsewhere", 'echo "opencode v2.0.29"')  # same output, different file
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 10, "opencode", exe=other)
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    gate = ov.member_gate_for_peer(pane, (30, 20, 10))
    assert gate.state == "unknown" and gate.reason == ov.REASON_UNKNOWN


def test_registration_refuses_v1_even_with_a_matching_process(proc, fake_path):
    v1 = _fake_opencode(fake_path, 'echo "opencode 1.17.11"')
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 10, "opencode", exe=v1)
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    gate = ov.member_gate_for_peer(pane, (30, 20, 10))
    assert gate.state == "unsupported" and gate.reason == ov.REASON_REQUIRED


def test_registration_refuses_a_deleted_executable(proc, trusted_v2):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 10, "opencode", exe=f"{trusted_v2} (deleted)")
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    assert ov.member_gate_for_peer(pane, (30, 20, 10)).state == "unknown"


def test_registration_refuses_when_the_pid_is_reused_during_the_check(proc, trusted_v2, monkeypatch):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 10, "opencode", start="700", exe=trusted_v2)
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    real_stat = peer_process.read_proc_stat
    real_readlink = os.readlink
    reused = {"now": False}

    def readlink(path, *args, **kwargs):
        if str(path).endswith("/20/exe"):
            reused["now"] = True  # pid 20 is replaced while its exe is being read
        return real_readlink(path, *args, **kwargs)

    def stat(pid):
        if pid == 20 and reused["now"]:
            return (10, "701")
        return real_stat(pid)

    monkeypatch.setattr(peer_process, "read_proc_stat", stat)
    monkeypatch.setattr(ov.os, "readlink", readlink)
    assert ov.member_gate_for_peer(pane, (30, 20, 10)).state == "unknown"

def test_registration_refuses_unknown_identity(proc, trusted_v2):
    assert ov.member_gate_for_peer(None, ()).state == "unknown"
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    # Pane process missing from /proc: unreadable identity fails closed.
    assert ov.member_gate_for_peer(pane, (30, 20, 10)).state == "unknown"


def test_registration_refuses_a_stale_pane(proc, trusted_v2):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="999", exe=_shell())  # pane pid reused
    proc.add(20, 10, "opencode", exe=trusted_v2)
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    assert ov.member_gate_for_peer(pane, (30, 20, 10)).state == "unknown"


def test_pane_check_finds_the_trusted_v2_descendant(proc, trusted_v2):
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 10, "opencode", exe=trusted_v2, children=(21,))
    proc.add(21, 20, "opencode", exe=trusted_v2)
    assert ov.member_gate_for_pane(10, "500").ready


def test_pane_check_refuses_without_a_trusted_descendant(proc, trusted_v2, tmp_path):
    other = _fake_opencode(tmp_path / "elsewhere", 'echo "opencode v2.0.29"')
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 10, "opencode", exe=other)
    assert ov.member_gate_for_pane(10, "500").state == "unknown"


def test_pane_check_refuses_a_stale_pane_and_unreadable_children(proc, trusted_v2):
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 10, "opencode", exe=trusted_v2)
    assert ov.member_gate_for_pane(10, "501").state == "unknown"
    os.remove(proc.root / "10" / "task" / "10" / "children")
    assert ov.member_gate_for_pane(10, "500").state == "unknown"


def test_pane_check_refuses_v1(proc, fake_path):
    v1 = _fake_opencode(fake_path, 'echo "opencode 1.17.11"')
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 10, "opencode", exe=v1)
    gate = ov.member_gate_for_pane(10, "500")
    assert gate.state == "unsupported" and gate.reason == ov.REASON_REQUIRED


def test_binary_replaced_after_the_probe_refuses_running_members(proc, fake_path):
    binary = _fake_opencode(fake_path, 'echo "opencode v2.0.29"')
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 10, "opencode", exe=binary)
    assert ov.member_gate_for_pane(10, "500").ready
    # The binary on disk is replaced after the member started and after the
    # probe was cached. The member's exe still names the path, but the trusted
    # identity (inode) changed, so the old process must not count.
    preserved = binary.with_name("opencode.old")
    os.link(binary, preserved)
    binary.unlink()
    _fake_opencode(fake_path, 'echo "opencode v2.0.29"')
    os.remove(proc.root / "20" / "exe")
    os.symlink(str(preserved), proc.root / "20" / "exe")
    assert ov.member_gate_for_pane(10, "500").state == "unknown"


def test_readiness_strings_match_the_gate_module():
    from app.services import provider_readiness_service as readiness

    assert readiness.OPENCODE_VERSION_REASON == ov.REASON_REQUIRED
    assert readiness.OPENCODE_VERSION_CODE == ov.BLOCK_CODE


# ---------------------------------------------------------------- review findings (bounds and parent edges)

def test_probe_output_is_capped_while_reading(fake_path, monkeypatch):
    monkeypatch.setattr(ov, "PROBE_TIMEOUT_SECONDS", 3.0)
    _fake_opencode(fake_path, 'echo "opencode v2.0.29"; head -c 2097152 /dev/zero')
    started = time.monotonic()
    gate = ov.opencode_version_gate()
    assert gate.state == "unknown"  # oversized output fails closed
    assert time.monotonic() - started < 3


def test_probe_returns_by_its_deadline_when_a_detached_child_keeps_stdout(fake_path, monkeypatch):
    monkeypatch.setattr(ov, "PROBE_TIMEOUT_SECONDS", 0.5)
    # setsid moves the child out of the probe's process group; it keeps stdout open.
    _fake_opencode(fake_path, 'setsid sleep 5 & echo "opencode v2.0.29"')
    started = time.monotonic()
    gate = ov.opencode_version_gate()
    assert time.monotonic() - started < 2
    assert gate.state == "unknown"


def test_pane_check_refuses_a_listed_child_whose_pid_now_has_another_parent(proc, trusted_v2):
    # The pane lists 20 as a child, but pid 20 now belongs to an unrelated
    # trusted-v2 process whose parent is 99 (the pid was reused).
    proc.add(10, 1, "bash", start="500", exe=_shell(), children=(20,))
    proc.add(20, 99, "opencode", exe=trusted_v2)
    assert ov.member_gate_for_pane(10, "500").state == "unknown"


def test_registration_refuses_a_stale_peer_chain(proc, trusted_v2):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 77, "opencode", exe=trusted_v2)  # 20 no longer descends from the pane
    proc.add(30, 20, "python", exe="/usr/bin/python3")
    assert ov.member_gate_for_peer(pane, (30, 20, 10)).state == "unknown"


def test_registration_refuses_when_the_shim_no_longer_descends_from_the_trusted_process(proc, trusted_v2):
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(10, 1, "bash", start="500", exe=_shell())
    proc.add(20, 10, "opencode", exe=trusted_v2)
    proc.add(30, 55, "python", exe="/usr/bin/python3")  # peer pid reused under another parent
    assert ov.member_gate_for_peer(pane, (30, 20, 10)).state == "unknown"


def test_pane_process_itself_may_be_the_trusted_tui(proc, trusted_v2):
    proc.add(10, 1, "opencode", start="500", exe=trusted_v2)
    assert ov.member_gate_for_pane(10, "500").ready
    pane = peer_process.PeerPane(pane_pid=10, pane_proc_start="500", tmux_target="%1", peer_pid=30)
    proc.add(30, 10, "python", exe="/usr/bin/python3")
    assert ov.member_gate_for_peer(pane, (30, 10)).ready
