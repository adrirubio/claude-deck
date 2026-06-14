"""Messaging: receipts, broadcast, request lifecycle, stale flag, counts."""
from datetime import datetime, timedelta

import pytest

from app.models.database import MailMessage, MailTeamMember
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import AgentMailService


@pytest.fixture
def svc():
    return AgentMailService()


async def _member(db, repo_id, name):
    member = MailTeamMember(
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
async def test_direct_message_lands_in_recipient_inbox_only(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    msg = await svc.send_message(
        db,
        MailMessageCreate(
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="hi",
            body_markdown="ping",
        ),
    )
    inbox_b = await svc.get_inbox(db, b.id)
    inbox_a = await svc.get_inbox(db, a.id)
    assert [m.id for m in inbox_b.messages] == [msg.id]
    assert inbox_a.messages == []


@pytest.mark.asyncio
async def test_broadcast_targets_everyone_except_sender(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    c = await _member(db, "rc", "gamma")
    await svc.send_message(
        db,
        MailMessageCreate(kind="broadcast", sender_member_id=a.id, body_markdown="all hands"),
    )
    assert (await svc.get_inbox(db, b.id)).unread_count == 1
    assert (await svc.get_inbox(db, c.id)).unread_count == 1
    assert (await svc.get_inbox(db, a.id)).unread_count == 0


@pytest.mark.asyncio
async def test_human_director_message_has_director_sender_name(db, svc):
    b = await _member(db, "rb", "beta")
    await svc.send_message(
        db,
        MailMessageCreate(recipient_member_id=b.id, body_markdown="please review"),
    )
    inbox = await svc.get_inbox(db, b.id)
    assert inbox.messages[0].sender_name == "Director"


@pytest.mark.asyncio
async def test_mark_read_clears_unread_count(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    msg = await svc.send_message(
        db,
        MailMessageCreate(sender_member_id=a.id, recipient_member_id=b.id, body_markdown="x"),
    )
    await svc.mark_read(db, msg.id, b.id)
    assert (await svc.get_inbox(db, b.id)).unread_count == 0


@pytest.mark.asyncio
async def test_context_request_lifecycle_pending_answered_acknowledged(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="How does auth refresh work?",
            body_markdown="Need it for retry wiring.",
            payload={"files_or_symbols": ["app/auth/session.py"]},
        ),
    )
    assert req.request_status == "pending"

    answer = await svc.send_message(
        db,
        MailMessageCreate(
            kind="answer",
            sender_member_id=b.id,
            thread_root_id=req.id,
            body_markdown="Refresh happens in session middleware.",
        ),
    )
    thread = await svc.get_thread(db, req.id)
    assert thread.root.request_status == "answered"

    await svc.ack_message(db, answer.id, a.id)
    thread = await svc.get_thread(db, req.id)
    assert thread.root.request_status == "acknowledged"


@pytest.mark.asyncio
async def test_handoff_ack_by_recipient_closes_it(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    handoff = await svc.send_message(
        db,
        MailMessageCreate(
            kind="handoff",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="take over auth",
            body_markdown="## Handoff",
        ),
    )
    assert handoff.request_status == "pending"

    await svc.ack_message(db, handoff.id, b.id)
    thread = await svc.get_thread(db, handoff.id)
    assert thread.root.request_status == "acknowledged"
    _, pending = await svc.counts_for_member(db, b.id)
    assert pending == 0


@pytest.mark.asyncio
async def test_handoff_completion_reply_does_not_close_acceptance_state(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    handoff = await svc.send_message(
        db,
        MailMessageCreate(
            kind="handoff",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="take over auth",
            body_markdown="## Handoff",
        ),
    )
    await svc.send_message(
        db,
        MailMessageCreate(
            kind="message",
            sender_member_id=b.id,
            thread_root_id=handoff.id,
            body_markdown="Completed the follow-up.",
        ),
    )
    thread = await svc.get_thread(db, handoff.id)
    assert thread.root.request_status == "pending"


@pytest.mark.asyncio
async def test_answer_to_handoff_is_rejected(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    handoff = await svc.send_message(
        db,
        MailMessageCreate(
            kind="handoff",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="take over auth",
            body_markdown="## Handoff",
        ),
    )
    with pytest.raises(ValueError):
        await svc.send_message(
            db,
            MailMessageCreate(
                kind="answer",
                sender_member_id=b.id,
                thread_root_id=handoff.id,
                body_markdown="Taking it.",
            ),
        )


@pytest.mark.asyncio
async def test_answer_is_delivered_back_to_requester(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="q",
            body_markdown="?",
        ),
    )
    await svc.send_message(
        db,
        MailMessageCreate(
            kind="answer",
            sender_member_id=b.id,
            thread_root_id=req.id,
            body_markdown="!",
        ),
    )
    inbox_a = await svc.get_inbox(db, a.id)
    assert inbox_a.unread_count == 1
    assert inbox_a.messages[0].kind == "answer"


@pytest.mark.asyncio
async def test_old_pending_request_is_stale(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="q",
            body_markdown="?",
        ),
    )
    row = await db.get(MailMessage, req.id)
    row.created_at = datetime.utcnow() - timedelta(minutes=30)
    await db.commit()
    inbox = await svc.get_inbox(db, b.id)
    assert inbox.messages[0].is_stale is True


@pytest.mark.asyncio
async def test_counts_for_member_pending_requests(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="q",
            body_markdown="?",
        ),
    )
    unread, pending = await svc.counts_for_member(db, b.id)
    assert unread == 1
    assert pending == 1


@pytest.mark.asyncio
async def test_delivery_counts_track_unseen_stale_and_inbox_checks(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    req = await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=a.id,
            recipient_member_id=b.id,
            subject="q",
            body_markdown="?",
        ),
    )

    await svc.get_inbox(db, b.id)
    await db.refresh(b)
    assert b.last_inbox_checked_at is None

    members = {member.id: member for member in await svc.list_team(db)}
    beta = members[b.id]
    assert beta.pending_count == 1
    assert beta.unseen_pending_count == 1
    assert beta.stale_pending_count == 0
    assert beta.last_inbox_checked_at is None

    await svc.get_inbox(db, b.id, mark_read=True)
    await db.refresh(b)
    assert b.last_inbox_checked_at is not None

    members = {member.id: member for member in await svc.list_team(db)}
    beta = members[b.id]
    assert beta.pending_count == 1
    assert beta.unseen_pending_count == 0
    assert beta.last_inbox_checked_at == b.last_inbox_checked_at

    row = await db.get(MailMessage, req.id)
    row.created_at = datetime.utcnow() - timedelta(minutes=30)
    await db.commit()

    members = {member.id: member for member in await svc.list_team(db)}
    assert members[b.id].stale_pending_count == 1


@pytest.mark.asyncio
async def test_invalid_kind_rejected(db, svc):
    b = await _member(db, "rb", "beta")
    with pytest.raises(ValueError):
        await svc.send_message(
            db,
            MailMessageCreate(
                kind="telepathy",
                recipient_member_id=b.id,
                body_markdown="x",
            ),
        )
