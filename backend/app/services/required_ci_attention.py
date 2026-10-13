"""Observe unreadable CI without granting authority or charging a retry."""
from datetime import datetime, timedelta, timezone

import httpx

from app.models.schemas import RequiredCIUnreadableSignal


GRACE_PERIOD = timedelta(minutes=15)
SAFE_REASONS = {"permission_missing", "workflow_missing", "api_error", "unknown"}


def safe_reason(value):
    return value if isinstance(value, str) and value in SAFE_REASONS else "unknown"


def error_reason(error):
    cause = error.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        if cause.response.status_code == 401:
            return "permission_missing"
        # A 403 can also mean rate limiting. Use only a known permission refusal.
        try:
            message = cause.response.json().get("message")
        except (ValueError, AttributeError):
            message = None
        if cause.response.status_code == 403 and isinstance(message, str) and message in {
            "Resource not accessible by integration", "Resource not accessible by personal access token"
        }:
            return "permission_missing"
        return "api_error"
    if isinstance(cause, (httpx.HTTPError, TimeoutError)):
        return "api_error"
    return safe_reason(str(error))


def note_unreadable(item, reason, *, now=None):
    if item.checks_unavailable_since is None:
        item.checks_unavailable_since = now or datetime.utcnow()
    item.checks_unavailable_reason = safe_reason(reason)


def note_readable(item):
    item.checks_unavailable_since = None
    item.checks_unavailable_reason = None


def signal(item, *, now=None):
    since = item.checks_unavailable_since
    if since is None or item.dispatch_status in {"merged", "completed"}:
        return None
    since = since.replace(tzinfo=timezone.utc) if since.tzinfo is None else since.astimezone(timezone.utc)
    current = now or datetime.now(timezone.utc)
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    if current - since < GRACE_PERIOD:
        return None
    return RequiredCIUnreadableSignal(
        since=since, reason=safe_reason(item.checks_unavailable_reason)
    )
