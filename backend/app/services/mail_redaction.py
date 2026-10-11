"""Remove workspace lease tokens from Mail reads that do not authenticate a recipient.

The dispatch brief and the release reminder give the owner its lease token, and
the owner reads them through its authenticated inbox. The all-messages list, the
thread read and the external-actor thread read return the same messages to
callers that are not that owner, so they pass every message through here. The
current writers put the token in the body only; the payload redaction covers
future formats.

Lease tokens are hex (`secrets.token_hex`), so they never contain the characters
that end a match. The redaction is deliberately narrow: only lease-token
assignments in text and lease-token keys in payloads. Commit SHAs, digests and
ordinary prose stay.
"""
import re
from typing import Any, TypeVar

from app.models.schemas import (
    ExternalAgentMailRequestStatus,
    MailMessageResponse,
    MailThreadResponse,
)

ThreadT = TypeVar("ThreadT", MailThreadResponse, ExternalAgentMailRequestStatus)

REDACTED = "[redacted]"

# lease_token="x", lease_token='x', lease_token=x, "lease_token": "x", lease-token: x
_LEASE_ASSIGNMENT = re.compile(
    r"(?i)(\blease[_\-]?token[\"']?\s*[:=]\s*)([\"']?)(?!\[redacted\])[^\s\"',;)}\]]+"
)
_LEASE_KEY = re.compile(r"(?i)^lease[_\-]?token$")


def redact_lease_text(text: str | None) -> str | None:
    if not text:
        return text
    return _LEASE_ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)


def redact_lease_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if isinstance(key, str) and _LEASE_KEY.match(key) and item is not None
            else redact_lease_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_lease_payload(item) for item in value]
    if isinstance(value, str):
        return redact_lease_text(value)
    return value


def redact_lease_message(message: MailMessageResponse) -> MailMessageResponse:
    return message.model_copy(update={
        "body_markdown": redact_lease_text(message.body_markdown),
        "payload": redact_lease_payload(message.payload),
    })


def redact_lease_thread(thread: ThreadT) -> ThreadT:
    return thread.model_copy(update={
        "root": redact_lease_message(thread.root),
        "replies": [redact_lease_message(reply) for reply in thread.replies],
    })
