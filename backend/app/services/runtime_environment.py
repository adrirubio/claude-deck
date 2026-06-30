"""Runtime environment diagnostics."""
from __future__ import annotations

import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

CONTAINER_AGENT_CLI_WARNING = (
    "No agent CLIs detected. Claude Deck must run in the same environment where "
    "your agents are installed — Docker can't see your host's CLIs."
)


def is_containerized() -> bool:
    """Return True when Claude Deck appears to be running in a container."""
    return Path("/.dockerenv").exists()


def agent_cli_warning_for_statuses(statuses: Iterable[Mapping[str, Any]]) -> str | None:
    """Return the container warning when every provider CLI is missing."""
    status_list = list(statuses)
    if not status_list or not is_containerized():
        return None
    if any(bool(status.get("installed")) for status in status_list):
        return None
    return CONTAINER_AGENT_CLI_WARNING


def agent_cli_warning_for_binaries(binary_names: Iterable[str]) -> str | None:
    """Return the container warning when none of the named binaries are in PATH."""
    names = [name for name in binary_names if name]
    if not names or not is_containerized():
        return None
    if any(shutil.which(name) for name in names):
        return None
    return CONTAINER_AGENT_CLI_WARNING


def annotate_provider_statuses(
    statuses: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Annotate provider statuses with runtime environment warning metadata."""
    status_list = [dict(status) for status in statuses]
    warning = agent_cli_warning_for_statuses(status_list)
    if warning:
        for status in status_list:
            if not status.get("installed"):
                status["unavailable_reason"] = warning
                status["unavailable_code"] = "container_agent_clis_missing"
    return status_list, {
        "containerized": is_containerized(),
        "agent_cli_warning": warning,
    }
