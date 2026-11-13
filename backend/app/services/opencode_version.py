"""OpenCode version gate: Synth City runs OpenCode 2 or later only (#730).

Provenance. Synth City asks exactly one executable for its version: the trusted
binary T, which is ``shutil.which("opencode")`` in the backend's own process resolved
with realpath and identified by (st_dev, st_ino, st_size, st_mtime_ns). The
probe runs ``T --version`` with an empty environment plus an explicit
allowlist, a timeout and bounded output. A member's own executable is never
run.

Member identity. A running member counts as OpenCode 2 only when a process in
its kernel-derived process tree executes T itself (same st_dev and st_ino)
while T's probed version is ready. Registration starts from the TCP peer that
the kernel reports for the request socket and walks up to the tmux pane;
adoption and wake start from the bound pane and walk down. A reported PID is
never trusted. Each candidate's start time is read before and after its
executable, so a reused PID is rejected. A deleted or replaced executable, a
wrapper without a trusted child, an unreadable /proc entry and an unknown
version are all refused (fail closed). Process checks are never cached; only
T's version probe is, keyed by T's identity and bounded by a TTL.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
import selectors
import shutil
import signal
import stat as stat_module
import subprocess
import tempfile
import threading
import time
from typing import Literal, Optional, Sequence

from app.utils import peer_process

MIN_MAJOR = 2
BLOCK_CODE = "opencode_version_unsupported"
REASON_REQUIRED = "OpenCode 2 or later is required"
REASON_UNKNOWN = "OpenCode version or executable identity is unknown"

PROBE_TIMEOUT_SECONDS = 5.0
PROBE_OUTPUT_CAP = 4096
CACHE_TTL_SECONDS = 30.0
MAX_TREE_DEPTH = 8
MAX_TREE_PROCESSES = 64

_VERSION_LINE = re.compile(
    r"^(?:opencode\s+)?v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?\s*$"
)
_DELETED_SUFFIX = " (deleted)"

GateState = Literal["ok", "unsupported", "unknown"]


def _monotonic() -> float:
    return time.monotonic()


def parse_opencode_version(output: str) -> Optional[tuple[int, int, int]]:
    """Parse ``opencode v2.0.29`` or a bare ``2.0.29``; anything else is None."""
    for line in (output or "").splitlines():
        match = _VERSION_LINE.fullmatch(line.strip())
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None


@dataclass(frozen=True)
class BinaryIdentity:
    path: str
    dev: int
    ino: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class VersionGate:
    state: GateState
    version: Optional[str]
    reason: Optional[str]
    identity: Optional[BinaryIdentity] = None

    @property
    def ready(self) -> bool:
        return self.state == "ok"


def _unknown(identity: Optional[BinaryIdentity] = None) -> VersionGate:
    return VersionGate("unknown", None, REASON_UNKNOWN, identity)


def trusted_binary() -> Optional[BinaryIdentity]:
    """Resolve T from the backend's own PATH. None when absent or not a regular file."""
    found = shutil.which("opencode")
    if not found:
        return None
    path = os.path.realpath(found)
    try:
        info = os.stat(path)
    except OSError:
        return None
    if not stat_module.S_ISREG(info.st_mode):
        return None
    return BinaryIdentity(path, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_bounded(process: subprocess.Popen, deadline: float) -> Optional[bytes]:
    """Read stdout and stderr until EOF, at most PROBE_OUTPUT_CAP bytes in total,
    and never past the deadline. None means oversized or late output."""
    collected = bytearray()
    with selectors.DefaultSelector() as selector:
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - _monotonic()
            if remaining <= 0:
                return None
            for key, _events in selector.select(remaining):
                try:
                    chunk = os.read(key.fileobj.fileno(), 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                collected += chunk
                if len(collected) > PROBE_OUTPUT_CAP:
                    return None
    return bytes(collected)


def _stop(process: subprocess.Popen) -> None:
    """Kill the probe's process group, close its pipes and reap it without waiting on them."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _probe(identity: BinaryIdentity) -> VersionGate:
    deadline = _monotonic() + PROBE_TIMEOUT_SECONDS
    with tempfile.TemporaryDirectory(prefix="synth-city-opencode-probe-") as home:
        env = {
            "HOME": home,
            "PATH": f"{os.path.dirname(identity.path)}:/usr/bin:/bin",
            "LANG": "C",
        }
        try:
            # A new session lets the probe kill its whole process group.
            process = subprocess.Popen(
                [identity.path, "--version"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=home,
                start_new_session=True,
            )
        except OSError:
            return _unknown(identity)
        try:
            output = _read_bounded(process, deadline)
            if output is not None:
                process.wait(timeout=max(0.0, deadline - _monotonic()))
        except (OSError, ValueError, subprocess.SubprocessError):
            output = None
        finally:
            if output is None or process.returncode is None:
                _stop(process)
            else:
                for stream in (process.stdout, process.stderr):
                    stream.close()
    if output is None or process.returncode != 0:
        return _unknown(identity)
    # The binary must still be the one that was probed (no replacement during the probe).
    if trusted_binary() != identity:
        return _unknown(identity)
    parsed = parse_opencode_version(output.decode("utf-8", "replace"))
    if parsed is None:
        return _unknown(identity)
    version = ".".join(str(part) for part in parsed)
    if parsed[0] < MIN_MAJOR:
        return VersionGate("unsupported", version, REASON_REQUIRED, identity)
    return VersionGate("ok", version, None, identity)


_cache: dict[BinaryIdentity, tuple[float, VersionGate]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def opencode_version_gate() -> VersionGate:
    """Version gate for the trusted binary T, cached by T's identity and a TTL."""
    identity = trusted_binary()
    if identity is None:
        return _unknown()
    now = _monotonic()
    with _cache_lock:
        cached = _cache.get(identity)
        if cached is not None and cached[0] > now:
            return cached[1]
    gate = _probe(identity)
    with _cache_lock:
        _cache.clear()  # only the current identity is ever worth keeping
        _cache[identity] = (now + CACHE_TTL_SECONDS, gate)
    return gate


def _stat(pid: int) -> Optional[tuple[int, str]]:
    if type(pid) is not int or pid <= 0:
        return None
    return peer_process.read_proc_stat(pid)


def _runs_trusted(pid: int, identity: BinaryIdentity, parent: Optional[int] = None) -> Optional[str]:
    """Return pid's start time when its executable is T, its lifetime is stable
    across the read and, when given, its parent is ``parent``; otherwise None."""
    before = _stat(pid)
    if before is None or (parent is not None and before[0] != parent):
        return None
    exe = f"{peer_process._PROC_ROOT}/{pid}/exe"
    try:
        target = os.readlink(exe)
        if target.endswith(_DELETED_SUFFIX):
            return None
        info = os.stat(exe)
    except OSError:
        return None
    after = _stat(pid)
    if after is None or after != before:
        return None
    if (info.st_dev, info.st_ino) != (identity.dev, identity.ino):
        return None
    return before[1]


def _member_result(gate: VersionGate, found: bool) -> VersionGate:
    if not found:
        return _unknown(gate.identity)
    # T must still be the identity that was probed when the member was observed.
    if trusted_binary() != gate.identity:
        return _unknown(gate.identity)
    return gate


def _chain_is_current(walked_pids: Sequence[int]) -> bool:
    """Every edge of the kernel-derived chain still holds: each pid's parent is the next pid."""
    for child, parent in zip(walked_pids, walked_pids[1:]):
        stat = _stat(child)
        if stat is None or stat[0] != parent:
            return False
    return True


def member_gate_for_peer(
    pane: Optional[peer_process.PeerPane], walked_pids: Sequence[int]
) -> VersionGate:
    """Registration: the kernel-derived peer chain must contain a process running T."""
    gate = opencode_version_gate()
    if not gate.ready:
        return gate
    if pane is None or not walked_pids or walked_pids[-1] != pane.pane_pid:
        return _unknown(gate.identity)
    if peer_process.pane_is_alive_strict(pane.pane_pid, pane.pane_proc_start) is not True:
        return _unknown(gate.identity)
    if not _chain_is_current(walked_pids):
        return _unknown(gate.identity)
    found = any(
        _runs_trusted(pid, gate.identity, parent) is not None
        for pid, parent in zip(walked_pids[:-1], walked_pids[1:])
    ) or _runs_trusted(pane.pane_pid, gate.identity) == pane.pane_proc_start
    # Re-check the chain and the pane after the reads, so a pid reused mid-check cannot count.
    found = (
        found
        and _chain_is_current(walked_pids)
        and peer_process.pane_is_alive_strict(pane.pane_pid, pane.pane_proc_start) is True
    )
    return _member_result(gate, found)


def _children(pid: int) -> Optional[list[int]]:
    task_root = f"{peer_process._PROC_ROOT}/{pid}/task"
    try:
        tasks = os.listdir(task_root)
    except OSError:
        return None
    children: list[int] = []
    for task in tasks:
        try:
            with open(f"{task_root}/{task}/children") as handle:
                raw = handle.read(65536)
        except OSError:
            return None
        for token in raw.split():
            if not token.isdigit():
                return None
            children.append(int(token))
    return children


def member_gate_for_pane(pane_pid: int, pane_proc_start: str) -> VersionGate:
    """Adoption and wake: the bound pane's descendants must contain a process running T.

    Each descendant is checked against the parent it was listed under, and that
    parent's start time is re-read afterwards, so a reused pid cannot count."""
    gate = opencode_version_gate()
    if not gate.ready:
        return gate
    if peer_process.pane_is_alive_strict(pane_pid, pane_proc_start) is not True:
        return _unknown(gate.identity)
    # (pid, its start time) of processes whose children are still to be listed.
    frontier: list[tuple[int, str]] = [(pane_pid, pane_proc_start)]
    seen = {pane_pid}
    # The pane process itself may be the OpenCode TUI.
    found = _runs_trusted(pane_pid, gate.identity) == pane_proc_start
    for _depth in range(0 if found else MAX_TREE_DEPTH):
        next_frontier: list[tuple[int, str]] = []
        for parent, parent_start in frontier:
            children = _children(parent)
            if children is None:
                return _unknown(gate.identity)
            for child in children:
                if child in seen:
                    continue
                seen.add(child)
                if len(seen) > MAX_TREE_PROCESSES:
                    return _unknown(gate.identity)
                stat = _stat(child)
                if stat is None or stat[0] != parent:
                    continue  # exited, or the pid now belongs to another parent
                start = _runs_trusted(child, gate.identity, parent)
                parent_now = _stat(parent)
                if parent_now is None or parent_now[1] != parent_start:
                    return _unknown(gate.identity)
                if start is not None:
                    found = True
                    break
                next_frontier.append((child, stat[1]))
            if found:
                break
        if found or not next_frontier:
            break
        frontier = next_frontier
    if peer_process.pane_is_alive_strict(pane_pid, pane_proc_start) is not True:
        return _unknown(gate.identity)
    return _member_result(gate, found)
