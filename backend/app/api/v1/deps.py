"""Shared route dependencies for capability-token enforcement."""

import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.database import MailAgentSession
from app.services.agent_mail_service import agent_mail_service

async def mail_session(
    x_deck_session_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[MailAgentSession]:
    """Resolve the calling session from its capability token."""
    if not x_deck_session_token:
        if settings.mail_capability_tokens_required:
            raise HTTPException(status_code=401, detail="session_token_required")
        return None

    hashed = agent_mail_service.hash_capability_token(x_deck_session_token)
    result = await db.execute(
        select(MailAgentSession).where(MailAgentSession.capability_token_hash.is_not(None))
    )
    for session in result.scalars().all():
        if hmac.compare_digest(session.capability_token_hash, hashed):
            return session
    raise HTTPException(status_code=401, detail="session_token_invalid")


async def require_mail_session(
    session: Optional[MailAgentSession] = Depends(mail_session),
) -> MailAgentSession:
    """Like mail_session, but never None."""
    if session is None:
        raise HTTPException(status_code=401, detail="session_token_required")
    return session


def require_session_slot(session: MailAgentSession) -> int:
    """Return the bound slot id or refuse an unbound session."""
    if session.team_slot_id is None:
        raise HTTPException(status_code=403, detail="session_not_slot_bound")
    return session.team_slot_id


async def require_operator(
    x_deck_operator_token: str | None = Header(default=None),
) -> None:
    """Authenticate the operator by a secret no agent is given.

    A sibling of require_session_slot, not a variant: that one authenticates an
    agent by what the kernel says about it, this one authenticates the operator
    by a shared secret. Do not merge them -- an agent's own session token must
    never open an operator route.

    Three distinguishable refusals, in this order:

      settings.operator_token empty  -> 503 operator_token_unconfigured
      no header (or an empty one)    -> 401 operator_token_required
      a header that does not match   -> 401 operator_token_invalid

    The empty check comes FIRST and that ordering is load-bearing. hmac.
    compare_digest("", "") returns True, so an implementation that leaves the
    empty setting to the comparison authorizes every caller who sends no header
    -- measured: 200 with the full workspace listing -- while its source still
    reads fail-closed. It refuses a *garbage* header, so a suite that never
    sends an empty one would not notice.

    The comparison is over BYTES because compare_digest raises TypeError on str
    values holding non-ASCII characters, and an unhandled TypeError here is an
    HTTP 500 rather than a refusal (measured).

    settings.operator_token is read at CALL time, not captured at import: the
    settings object is built when config.py is imported, so a module-level
    constant would freeze the empty default and make the 503 unconditional.

    What this credential is worth: the backend and every agent pane share a
    uid, so a determined pane can read backend/.env. This is a boundary against
    an opportunistic adversary, not a co-resident one -- it moves the attack
    from knowing a URL to deliberately reading a 600 file. Do not describe it
    as authenticating a human.
    """
    expected = settings.operator_token
    if not expected:
        raise HTTPException(status_code=503, detail="operator_token_unconfigured")
    if not x_deck_operator_token:
        raise HTTPException(status_code=401, detail="operator_token_required")
    if not hmac.compare_digest(
        x_deck_operator_token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="operator_token_invalid")
