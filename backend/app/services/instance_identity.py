"""Runtime identity metadata for this Claude Deck backend instance."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
from datetime import datetime, timezone
from functools import lru_cache

from app.models.schemas import InstanceIdentity

LOGGER = logging.getLogger(__name__)

ALLOWED_ACCENTS: tuple[str, ...] = (
    "blue",
    "green",
    "purple",
    "orange",
    "red",
    "pink",
    "cyan",
    "slate",
)

# The automatic accent never uses a colour that means something in the UI:
# red (error), orange (needs attention) or green (primary action, healthy).
# Every colour in ALLOWED_ACCENTS stays available as an explicit choice.
AUTO_ACCENTS: tuple[str, ...] = (
    "blue",
    "purple",
    "pink",
    "cyan",
    "slate",
)

DEFAULT_INSTANCE_NAME = "This machine"

_STARTED_AT = datetime.now(timezone.utc)
_MAX_NAME_LENGTH = 64
_MAX_ID_LENGTH = 64


def _remove_control_chars(value: str) -> str:
    return "".join(ch for ch in value if ch.isprintable()).strip()


def _get_hostname() -> str:
    hostname = _remove_control_chars(socket.gethostname())
    return hostname or "unknown-host"


def _short_hostname(hostname: str) -> str:
    short = hostname.split(".", 1)[0].strip()
    return short or hostname or "unknown-host"


def _clean_name(raw_name: str | None, fallback: str) -> str:
    name = _remove_control_chars(raw_name or "")
    if not name:
        return fallback[:_MAX_NAME_LENGTH]
    return name[:_MAX_NAME_LENGTH]


def _clean_explicit_id(raw_id: str | None) -> str | None:
    value = _remove_control_chars(raw_id or "")
    if not value:
        return None

    safe = "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})
    return safe[:_MAX_ID_LENGTH] or None


def _stable_id(hostname: str, explicit_id: str | None) -> str:
    cleaned = _clean_explicit_id(explicit_id)
    if cleaned:
        return cleaned
    return hashlib.sha256(f"claude-deck:{hostname}".encode("utf-8")).hexdigest()[:12]


def _accent_from_hostname(hostname: str) -> str:
    digest = hashlib.sha256(hostname.encode("utf-8")).digest()
    return AUTO_ACCENTS[digest[0] % len(AUTO_ACCENTS)]


def _resolve_accent(hostname: str, raw_accent: str | None) -> str:
    accent = _remove_control_chars(raw_accent or "").lower()
    if not accent:
        return _accent_from_hostname(hostname)
    if accent in ALLOWED_ACCENTS:
        return accent

    LOGGER.warning(
        "Unsupported CLAUDE_DECK_INSTANCE_ACCENT=%r; using hostname-derived accent",
        raw_accent,
    )
    return _accent_from_hostname(hostname)


@lru_cache(maxsize=1)
def get_instance_identity() -> InstanceIdentity:
    """Return process-lifetime display identity for this backend instance."""

    hostname = _get_hostname()
    short_hostname = _short_hostname(hostname)
    raw_name = os.getenv("CLAUDE_DECK_INSTANCE_NAME")

    return InstanceIdentity(
        id=_stable_id(hostname, os.getenv("CLAUDE_DECK_INSTANCE_ID")),
        name=_clean_name(raw_name, DEFAULT_INSTANCE_NAME),
        name_configured=bool(_remove_control_chars(raw_name or "")),
        hostname=hostname,
        short_hostname=short_hostname,
        accent=_resolve_accent(hostname, os.getenv("CLAUDE_DECK_INSTANCE_ACCENT")),
        started_at=_STARTED_AT,
    )
