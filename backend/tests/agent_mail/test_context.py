"""Injection context builders: state-based, idempotent, short."""
import pytest

from app.models.database import MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import AgentMailService


@pytest.fixture
def svc():
    return AgentMailService()


async def _member(db, repo_id, name, role=None, charter=None):
    member = MailTeamMember(
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
        role=role,
        charter=charter,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
async def test_session_start_context_includes_identity_team_and_inbox(db, svc):
    me = await _member(
        db,
        "ra",
        "backend-agent",
        role="backend expert",
        charter="Owns the API",
    )
    other = await _member(db, "rb", "frontend-agent", role="frontend")
    await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=other.id,
            recipient_member_id=me.id,
            subject="auth?",
            body_markdown="?",
        ),
    )

    ctx = await svc.build_session_start_context(db, me.id)
    assert 'You are "backend-agent"' in ctx
    assert "backend expert" in ctx
    assert "Owns the API" in ctx
    assert "frontend-agent" in ctx
    assert "1 pending request" in ctx
    assert "deck_check_inbox" in ctx


@pytest.mark.asyncio
async def test_prompt_submit_context_none_when_inbox_clear(db, svc):
    me = await _member(db, "ra", "solo")
    assert await svc.build_prompt_submit_context(db, me.id) is None


@pytest.mark.asyncio
async def test_prompt_submit_context_mentions_pending(db, svc):
    me = await _member(db, "ra", "backend-agent")
    other = await _member(db, "rb", "frontend-agent")
    await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=other.id,
            recipient_member_id=me.id,
            subject="auth refresh",
            body_markdown="?",
        ),
    )
    ctx = await svc.build_prompt_submit_context(db, me.id)
    assert ctx is not None
    assert "1 pending request" in ctx
    assert "deck_check_inbox" in ctx
