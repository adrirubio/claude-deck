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
