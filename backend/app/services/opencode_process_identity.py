"""OpenCode v2 member identity: session ids, launch config and process argv (#731).

A team member runs ``opencode <dir> --standalone --session <ses_id>`` and its own
private server, ``opencode serve --stdio``, as a child. The shared background
service, ``opencode serve --service``, runs with whichever member started it,
so it is never a member (#729 spec, answer 3).
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets
import string
from typing import Optional, Sequence

_BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
_SESSION_ID = re.compile(r"ses[0-9A-Za-z_-]{1,96}")
_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._:@+-]*"
_MODEL = re.compile(rf"{_SEGMENT}(?:/{_SEGMENT})+(?:#[A-Za-z0-9][A-Za-z0-9._-]*)?")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MAX_MODEL_LENGTH = 256
# Largest /proc/<pid>/cmdline accepted. A longer one is refused, never parsed from its prefix.
CMDLINE_CAP = 65536


def new_session_id() -> str:
    """A Synth City-chosen id in OpenCode's native shape: ``ses_`` and 26 base62 characters."""
    return "ses_" + "".join(secrets.choice(_BASE62) for _ in range(26))


def is_session_id(value: object) -> bool:
    """OpenCode refuses session ids that do not start with ``ses``."""
    return isinstance(value, str) and _SESSION_ID.fullmatch(value) is not None


def is_model(value: object) -> bool:
    """``provider/model`` with an optional ``#variant``."""
    return (
        isinstance(value, str)
        and len(value) <= _MAX_MODEL_LENGTH
        and _MODEL.fullmatch(value) is not None
    )


def is_agent(value: object) -> bool:
    return isinstance(value, str) and _AGENT.fullmatch(value) is not None


def config_content(*, model: Optional[str], agent: Optional[str]) -> str:
    """The per-member ``OPENCODE_CONFIG_CONTENT``. It holds no secret: the member's
    private server and plugins can read the whole environment (#729 F10)."""
    config: dict[str, object] = {}
    if model:
        config["model"] = model
    if agent:
        config["default_agent"] = agent
    config["update"] = "disable"
    if model:
        config["enabled_providers"] = [model.split("/", 1)[0]]
    else:
        # No model chosen: stop a silent fallback to OpenCode's hosted free models (#729 F5).
        config["disabled_providers"] = ["opencode"]
    return json.dumps(config, separators=(",", ":"))


@dataclass(frozen=True)
class OpenCodeMember:
    directory: str
    session_id: str
    auto: bool


def _is_opencode(argv: Sequence[str]) -> bool:
    return bool(argv) and Path(argv[0]).name == "opencode"


def parse_member_argv(argv: Sequence[str]) -> Optional[OpenCodeMember]:
    """The exact member launch, or None. Any other flag, ``--continue`` included, is refused."""
    if not _is_opencode(argv) or len(argv) < 2 or argv[1].startswith("-") or argv[1] == "serve":
        return None
    directory = argv[1]
    standalone = auto = False
    session_ids: list[str] = []
    index = 2
    while index < len(argv):
        token = argv[index]
        if token == "--standalone" and not standalone:
            standalone = True
        elif token == "--auto" and not auto:
            auto = True
        elif token in {"--session", "--prompt"}:
            if index + 1 >= len(argv):
                return None
            if token == "--session":
                session_ids.append(argv[index + 1])
            index += 1
        else:
            return None
        index += 1
    if not standalone or len(session_ids) != 1 or not is_session_id(session_ids[0]):
        return None
    return OpenCodeMember(directory, session_ids[0], auto)


def is_server_argv(argv: Sequence[str]) -> bool:
    return _is_opencode(argv) and len(argv) > 1 and argv[1] == "serve"


def is_private_server_argv(argv: Sequence[str]) -> bool:
    """A member's own ``opencode serve --stdio`` child, never the shared service."""
    return is_server_argv(argv) and "--stdio" in argv[2:] and "--service" not in argv[2:]


def read_argv(pid: int) -> Optional[list[str]]:
    """``/proc/<pid>/cmdline`` as argv, or None when unreadable or over CMDLINE_CAP.

    A truncated prefix could hide a forbidden tail such as ``--continue``, so an
    oversized command line is refused rather than parsed."""
    from app.utils import peer_process

    if type(pid) is not int or pid <= 0:
        return None
    try:
        with open(f"{peer_process._PROC_ROOT}/{pid}/cmdline", "rb") as handle:
            raw = handle.read(CMDLINE_CAP + 1)
    except OSError:
        return None
    if len(raw) > CMDLINE_CAP:
        return None
    parts = raw.split(b"\0")
    if parts and parts[-1] == b"":
        parts.pop()
    if not parts:
        return None
    return [part.decode("utf-8", "replace") for part in parts]


def is_current_member(
    pane_pid: int, pane_start: str, session_id: object, auxiliary_pid: Optional[int] = None,
) -> bool:
    """The bound pane runs the exact OpenCode 2 member for ``session_id``.

    ``auxiliary_pid`` is the process that registered with Agent Mail: the pane
    itself, or its private ``serve --stdio`` child, never the shared service.
    """
    from app.services import opencode_version
    from app.utils import peer_process

    if not is_session_id(session_id):
        return False
    argv = read_argv(pane_pid)
    member = parse_member_argv(argv) if argv else None
    if member is None or member.session_id != session_id:
        return False
    if auxiliary_pid is not None and auxiliary_pid != pane_pid:
        server_argv = read_argv(auxiliary_pid)
        stat = peer_process.read_proc_stat(auxiliary_pid)
        if not server_argv or not is_private_server_argv(server_argv) or stat is None or stat[0] != pane_pid:
            return False
    return opencode_version.member_gate_for_pane(pane_pid, pane_start).ready
