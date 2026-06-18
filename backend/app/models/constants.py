"""Shared constants for the application."""
from enum import StrEnum


class SessionStatus(StrEnum):
    """Observed agent session status values."""
    ACTIVE = "active"
    IDLE = "idle"
    ERROR = "error"
    STOPPED = "stopped"
