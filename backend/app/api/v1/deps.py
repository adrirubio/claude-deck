"""Shared route dependencies for capability-token enforcement."""

import hmac
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.database import MailAgentSession
from app.services.agent_mail_service import agent_mail_service

logger = logging.getLogger(__name__)

_missing_token_logged: set[int] = set()


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


def derive_member_id(
    session: Optional[MailAgentSession],
    claimed: Optional[int],
    *,
    detail: str = "sender_not_token_holder",
) -> Optional[int]:
    """Derive the acting member from the token and refuse disagreement."""
    if session is None:
        if claimed is None:
            raise HTTPException(status_code=400, detail="member_id_required")
        if claimed not in _missing_token_logged:
            _missing_token_logged.add(claimed)
            logger.warning(
                "capability_token_missing: unauthenticated write as member %s "
                "accepted because mail_capability_tokens_required is False",
                claimed,
            )
        return claimed
    if claimed is not None and claimed != session.member_id:
        raise HTTPException(status_code=403, detail=detail)
    return session.member_id
