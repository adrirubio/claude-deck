"""Smoke test: agent mail tables exist and accept rows."""
import pytest

from app.models.database import MailAgentSession, MailMessage, MailReceipt, MailTeamMember


@pytest.mark.asyncio
async def test_tables_create_and_accept_rows(db):
    member = MailTeamMember(
        identity_key="repo:abc123",
        repo_id="abc123",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="r",
    )
    db.add(member)
    await db.flush()

    db.add(MailAgentSession(member_id=member.id, source="hook", session_key="cc:s1"))
    msg = MailMessage(
        kind="context_request",
        body_markdown="hi",
        request_status="pending",
        recipient_member_id=member.id,
    )
    db.add(msg)
    await db.flush()
    db.add(MailReceipt(message_id=msg.id, member_id=member.id))
    await db.commit()

    assert member.id
    assert msg.id
