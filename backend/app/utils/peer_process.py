"""Resolve a TCP peer to the tmux pane its process runs in.

Everything here reads Linux kernel interfaces (/proc/net/tcp, /proc/net/tcp6,
/proc/<pid>/stat) and shells out to tmux. On a host without /proc, every
function returns None or an empty mapping rather than raising, so a deployment
with mail_capability_tokens_required = False still serves requests.

The caller MUST invoke resolve_peer_pane synchronously, inside the request
handler. Once the response is sent the peer socket enters TIME_WAIT, its
/proc/net inode reads 0, and no process owns it any more.
"""

import logging
import os
import socket
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_PROC_NET_TABLES = (
    ("/proc/net/tcp", socket.AF_INET),
    ("/proc/net/tcp6", socket.AF_INET6),
)

# /proc/net/tcp columns: sl local_address rem_address st tx_queue:rx_queue
# tr:tm->when retrnsmt uid timeout inode ...
_LOCAL_ADDRESS_COLUMN = 1
_REMOTE_ADDRESS_COLUMN = 2
_STATE_COLUMN = 3
_INODE_COLUMN = 9

# Kernel TCP state codes, as printed in /proc/net/tcp column 4.
_TCP_ESTABLISHED = "01"

# How far up the process tree to walk before giving up on finding a pane.
_MAX_PARENT_WALK = 32


def format_endpoint(host: str, port: int) -> Optional[str]:
    """Render host:port the way /proc/net/tcp does, or None if host is not an IP.

    The kernel prints each 4-byte word of the address in host byte order, so a
    single formatter serves IPv4 and IPv6 alike: pack, then reverse per word.
    """
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            packed = socket.inet_pton(family, host)
        except (OSError, ValueError):
            continue
        words = [packed[index : index + 4][::-1] for index in range(0, len(packed), 4)]
        return f"{b''.join(words).hex().upper()}:{port:04X}"
    return None


_PROC_ROOT = "/proc"


def find_socket_inode(
    host: str, port: int, local_port: Optional[int] = None
) -> Optional[int]:
    """Find the inode of the CALLER's socket, whose local end is host:port.

    A loopback connection appears twice in /proc/net/tcp, as mirror-image rows:
    one owned by the caller and one owned by this backend. We want the caller's,
    so we match host:port against LOCAL_address -- matching rem_address would
    find our own accepted socket and resolve every caller to the backend's pid.

    Pass local_port (this backend's port for the connection) to disambiguate
    when the caller reuses a source port across restarts; the pair is unique.
    Both address families are searched: a connection to ::1 lands in
    /proc/net/tcp6 while 127.0.0.1 lands in /proc/net/tcp.
    """
    wanted = format_endpoint(host, port)
    if wanted is None:
        return None
    for path, _family in _PROC_NET_TABLES:
        try:
            with open(path) as handle:
                next(handle, None)
                for line in handle:
                    parts = line.split()
                    if len(parts) <= _INODE_COLUMN:
                        continue
                    if parts[_LOCAL_ADDRESS_COLUMN].upper() != wanted:
                        continue
                    if parts[_STATE_COLUMN] != _TCP_ESTABLISHED:
                        continue
                    if local_port is not None:
                        remote = parts[_REMOTE_ADDRESS_COLUMN].upper()
                        if not remote.endswith(f":{local_port:04X}"):
                            continue
                    try:
                        inode = int(parts[_INODE_COLUMN])
                    except ValueError:
                        continue
                    if inode:
                        return inode
        except OSError:
            continue
    return None


def find_pid_for_inode(inode: int) -> Optional[int]:
    """Find the process holding the socket with this inode.

    A full scan of every /proc/<pid>/fd measured 2.0-6.3 ms across 140 pids on
    the deployment host, which is why this is safe to call inline in a request.
    """
    target = f"socket:[{inode}]"
    try:
        entries = os.listdir(_PROC_ROOT)
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        fd_dir = f"{_PROC_ROOT}/{entry}/fd"
        try:
            descriptors = os.listdir(fd_dir)
        except OSError:
            continue
        for descriptor in descriptors:
            try:
                if os.readlink(f"{fd_dir}/{descriptor}") == target:
                    return int(entry)
            except OSError:
                continue
    return None


def read_proc_stat(pid: int) -> Optional[tuple[int, str]]:
    """Return (ppid, starttime) for pid, or None if it is gone.

    Field 2 (comm) is parenthesised and may itself contain spaces and
    parentheses, so the parse begins after the last close-paren. From there
    fields[1] is ppid and fields[19] is starttime -- one read, both values.
    """
    try:
        with open(f"{_PROC_ROOT}/{pid}/stat") as handle:
            raw = handle.read()
    except OSError:
        return None
    try:
        fields = raw[raw.rindex(")") + 2 :].split()
        return int(fields[1]), fields[19]
    except (ValueError, IndexError):
        return None


@dataclass(frozen=True)
class PeerPane:
    """The tmux pane a caller's process tree belongs to."""

    pane_pid: int
    pane_proc_start: str
    tmux_target: Optional[str]
    peer_pid: int


def _run_tmux(*args: str) -> Optional[str]:
    """Run a read-only tmux command, or return None if tmux is unavailable."""
    try:
        completed = subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def list_tmux_pane_pids() -> dict[int, str]:
    """Map every live pane's pid to its tmux target."""
    output = _run_tmux(
        "list-panes",
        "-a",
        "-F",
        "#{pane_id} #{pane_pid} #{session_name}:#{window_index}.#{pane_index}",
    )
    if not output:
        return {}
    panes: dict[int, str] = {}
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            panes[int(parts[1])] = parts[2]
        except ValueError:
            continue
    return panes


def resolve_peer_pane(
    host: str, port: int, local_port: Optional[int] = None
) -> Optional[PeerPane]:
    """Resolve a TCP peer to the tmux pane it runs under, or None.

    MUST be called synchronously inside the request handler -- see the module
    docstring. Returns None rather than guessing whenever any link in the chain
    is missing: an unresolvable caller is not a caller in some other pane.
    """
    inode = find_socket_inode(host, port, local_port=local_port)
    if inode is None:
        return None
    peer_pid = find_pid_for_inode(inode)
    if peer_pid is None:
        return None

    panes = list_tmux_pane_pids()
    if not panes:
        return None

    pid = peer_pid
    for _ in range(_MAX_PARENT_WALK):
        stat = read_proc_stat(pid)
        if stat is None:
            return None
        parent_pid, proc_start = stat
        if pid in panes:
            return PeerPane(
                pane_pid=pid,
                pane_proc_start=proc_start,
                tmux_target=panes[pid],
                peer_pid=peer_pid,
            )
        if parent_pid <= 1:
            return None
        pid = parent_pid
    return None
