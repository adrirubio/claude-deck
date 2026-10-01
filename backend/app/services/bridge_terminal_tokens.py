"""Short-lived, single-use grants for one bridge target and purpose."""

import secrets
import time
from dataclasses import dataclass
from typing import Literal


TerminalPurpose = Literal["readonly", "interactive", "attachment"]
TERMINAL_PROTOCOL_PREFIX = "deck-terminal."


def token_from_protocol_header(value: str) -> str:
    protocols = [protocol.strip() for protocol in value.split(",") if protocol.strip()]
    if len(protocols) != 1 or not protocols[0].startswith(TERMINAL_PROTOCOL_PREFIX):
        return ""
    return protocols[0][len(TERMINAL_PROTOCOL_PREFIX):]


@dataclass(frozen=True)
class TerminalGrant:
    issued_at: float
    target: str
    purpose: TerminalPurpose


class TerminalTokenStore:
    def __init__(self, ttl_seconds: int = 30):
        self._ttl_seconds = ttl_seconds
        self._tokens: dict[str, TerminalGrant] = {}

    def issue(self, target: str, purpose: TerminalPurpose) -> str:
        now = time.monotonic()
        self._tokens = {
            token: grant
            for token, grant in self._tokens.items()
            if now - grant.issued_at <= self._ttl_seconds
        }
        token = secrets.token_urlsafe(32)
        self._tokens[token] = TerminalGrant(now, target, purpose)
        return token

    def consume(self, token: str, target: str, purpose: TerminalPurpose) -> bool:
        grant = self._tokens.pop(token, None)
        return (
            grant is not None
            and time.monotonic() - grant.issued_at <= self._ttl_seconds
            and grant.target == target
            and grant.purpose == purpose
        )
