"""Messaging: receipts, broadcast, request lifecycle, stale flag, counts."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select, text

from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    MailMessage,
    MailReceipt,
    MailTeamMember,
    TeamGithubScope,
)
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import (
    AgentMailService,
    MailDeliveryIntegrityError,
)


@pytest.fixture
def svc():
    return AgentMailService()


async def _member(db, repo_id, name, *, team_preset_id=None, identity_key=None):
    member = MailTeamMember(
        identity_key=identity_key or f"repo:{repo_id}",
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
        team_preset_id=team_preset_id,
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
    stored = await db.get(MailMessage, msg.id)
    assert (stored.audience_type, stored.audience_id) == ("member", str(b.id))
    assert (stored.sender_type, msg.sender_type) == ("member", "member")


@pytest.mark.asyncio
async def test_broadcast_targets_everyone_except_sender(db, svc):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    c = await _member(db, "rc", "gamma")
    await svc.send_message(
        db,
        MailMessageCreate(
            kind="broadcast",
            sender_member_id=a.id,
            body_markdown="all hands",
            audience_type="operator_global",
            audience_id="global",
        ),
        operator_authorized=True,
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
        sender_type="director",
        operator_authorized=True,
    )
    inbox = await svc.get_inbox(db, b.id)
    assert inbox.messages[0].sender_name == "Director"
    assert inbox.messages[0].sender_type == "director"


@pytest.mark.asyncio
async def test_service_and_director_messages_have_distinct_senders(db, svc):
    recipient = await _member(db, "recipient", "Recipient")
    system = await svc.send_direct_message(
        db, recipient_member_id=recipient.id, subject="Service notice",
        body_markdown="Check the backlog.", auto_nudge=False,
    )
    director = await svc.send_message(
        db, MailMessageCreate(recipient_member_id=recipient.id,
                              subject="Director note", body_markdown="Keep the change small."),
        sender_type="director", operator_authorized=True, auto_nudge=False,
    )
    assert (system.sender_name, system.sender_type) == ("Albiex Synth City", "system")
    assert (director.sender_name, director.sender_type) == ("Director", "director")
    inbox = await svc.get_inbox(db, recipient.id)
    assert {(row.sender_name, row.sender_type) for row in inbox.messages} == {
        ("Albiex Synth City", "system"), ("Director", "director"),
    }


@pytest.mark.asyncio
async def test_system_broadcast_and_directly_created_notice_show_deck(db, svc):
    preset = AgentTeamPreset(name="System sender team")
    db.add(preset)
    await db.commit()
    await _member(db, "recipient", "Recipient", team_preset_id=preset.id)
    broadcast = await svc.send_broadcast(
        db, subject="Service broadcast", body_markdown="Check the backlog.",
        audience_type="team_preset", audience_id=str(preset.id), auto_nudge=False,
    )
    notice = MailMessage(kind="message", subject="Waiting for input",
                         body_markdown="The slot waits for input.",
                         payload={"notice": "native_input_wait"})
    db.add(notice)
    await db.commit()
    response = await svc._message_response(db, notice, for_member_id=None)
    assert (broadcast.sender_name, broadcast.sender_type) == ("Albiex Synth City", "system")
    assert (response.sender_name, response.sender_type) == ("Albiex Synth City", "system")
    assert notice.sender_type == "system"


@pytest.mark.asyncio
@pytest.mark.parametrize("subject,payload,delivery_key,expected", [
    ("A notice", {"kind": "github_dispatch_idle_nudge"}, None, "Albiex Synth City"),
    ("Reconcile assigned backlog and independent work", None, None, "Albiex Synth City"),
    ("Release needed: issue #5", None, None, "Albiex Synth City"),
    ("Code PR ready for review", None, None, "Albiex Synth City"),
    ("Continuation progress check: issue #2", None, None, "Albiex Synth City"),
    ("An old notice", None, "backlog:1:2:3", "Albiex Synth City"),
    ("Waiting for input", {"notice": "native_input_wait"}, None, "Albiex Synth City"),
    ("An old note", None, None, "Albiex Synth City or Director (recorded before v3.1)"),
    ("An old note", {"sender_type": "director"}, None, "Albiex Synth City or Director (recorded before v3.1)"),
    ("An old note", {"kind": []}, None, "Albiex Synth City or Director (recorded before v3.1)"),
    ("Progress check: unrelated text", None, None, "Albiex Synth City or Director (recorded before v3.1)"),
])
async def test_legacy_senderless_rows_use_reliable_or_uncertain_attribution(
    db, svc, subject, payload, delivery_key, expected,
):
    row = MailMessage(subject=subject, body_markdown="Historical message.",
                      payload=payload, delivery_key=delivery_key)
    db.add(row)
    await db.commit()
    await db.execute(text("UPDATE mail_messages SET sender_type = NULL WHERE id = :id"),
                     {"id": row.id})
    await db.commit()
    await db.refresh(row)
    response = await svc._message_response(db, row, for_member_id=None)
    assert response.sender_name == expected
    assert response.sender_type == ("system" if expected == "Albiex Synth City" else "legacy")
    assert row.sender_type is None


@pytest.mark.asyncio
async def test_dispatch_brief_is_attributed_to_deck(db, svc, monkeypatch):
    from app.services.agent_mail_service import agent_mail_service
    from app.services.github_dispatch_service import github_dispatch_service

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", AsyncMock())
    preset = AgentTeamPreset(name="Dispatch sender team")
    db.add(preset)
    await db.commit()
    slot = AgentTeamSlot(preset_id=preset.id, display_name="Backend owner",
                         provider="codex-cli", repo_id="repo", repo_name="repo", repo_path="/tmp/repo")
    db.add(slot)
    await db.commit()
    item = GithubWorkItem(id=55, issue_number=527, scope_id=1)
    await github_dispatch_service._send_dispatch_brief_to_slot(
        db, item, preset_slots=[slot], owner_slot_id=slot.id, brief="Read the assigned issue.",
    )
    member = await agent_mail_service.get_or_create_slot_member(db, slot)
    inbox = await svc.get_inbox(db, member.id)
    assert len(inbox.messages) == 1
    assert (inbox.messages[0].sender_name, inbox.messages[0].sender_type) == ("Albiex Synth City", "system")
    assert inbox.messages[0].id == item.brief_message_id


@pytest.mark.asyncio
async def test_director_sender_requires_operator_authorization(db, svc):
    recipient = await _member(db, "recipient", "Recipient")
    with pytest.raises(ValueError, match="Director sender requires operator authorization"):
        await svc.send_message(
            db, MailMessageCreate(recipient_member_id=recipient.id, body_markdown="Spoofed note."),
            sender_type="director", auto_nudge=False,
        )


@pytest.mark.asyncio
async def test_delivery_key_cannot_change_system_sender_to_director(db, svc):
    recipient = await _member(db, "recipient", "Recipient")
    request = MailMessageCreate(recipient_member_id=recipient.id, body_markdown="Same body.")
    first = await svc.send_message(db, request, auto_nudge=False, delivery_key="sender-test")
    retry = await svc.send_message(db, request, auto_nudge=False, delivery_key="sender-test")
    assert first.id == retry.id
    with pytest.raises(MailDeliveryIntegrityError):
        await svc.send_message(
            db, request, auto_nudge=False, delivery_key="sender-test",
            sender_type="director", operator_authorized=True,
        )


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
    answer_row = await db.get(MailMessage, answer.id)
    assert (answer_row.audience_type, answer_row.audience_id) == ("member", str(a.id))

    await svc.ack_message(db, answer.id, a.id)
    thread = await svc.get_thread(db, req.id)
    assert thread.root.request_status == "acknowledged"


@pytest.mark.asyncio
async def test_superseded_context_request_is_terminal(db, svc):
    requester = await _member(db, "ra", "alpha")
    recipient = await _member(db, "rb", "beta")
    request = await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=requester.id,
            recipient_member_id=recipient.id,
            body_markdown="Approve this plan.",
        ),
    )
    root = await db.get(MailMessage, request.id)
    root.request_status = "superseded"
    await db.commit()

    with pytest.raises(ValueError, match="superseded context requests cannot be answered"):
        await svc.send_message(
            db,
            MailMessageCreate(
                kind="answer",
                sender_member_id=recipient.id,
                thread_root_id=request.id,
                body_markdown="Too late.",
            ),
        )

    _unread, pending = await svc.counts_for_member(db, recipient.id)
    assert pending == 0


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


@pytest.mark.asyncio
async def test_server_delivery_key_recovers_exact_message_without_duplicate_receipt(
    db, svc, monkeypatch
):
    recipient = await _member(db, "rb", "beta")
    nudges = []

    async def record_nudge(*_args, **_kwargs):
        nudges.append(True)

    monkeypatch.setattr(svc, "auto_nudge_members", record_nudge)
    request = MailMessageCreate(
        recipient_member_id=recipient.id,
        subject="Approval request",
        body_markdown="Review the bounded plan.",
        payload={"work_item_id": 7, "summary": "bounded"},
    )
    first = await svc.send_message(db, request, delivery_key="approval:7:request")
    repeated = await svc.send_message(db, request, delivery_key="approval:7:request")

    assert repeated.id == first.id
    assert nudges == [True]
    assert (
        await db.execute(select(func.count()).select_from(MailMessage))
    ).scalar_one() == 1
    assert (
        await db.execute(select(func.count()).select_from(MailReceipt))
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_server_delivery_key_rejects_different_message(db, svc):
    recipient = await _member(db, "rb", "beta")
    await svc.send_message(
        db,
        MailMessageCreate(
            recipient_member_id=recipient.id,
            body_markdown="original",
            payload={"work_item_id": 7},
        ),
        delivery_key="approval:7:request",
    )

    with pytest.raises(MailDeliveryIntegrityError):
        await svc.send_message(
            db,
            MailMessageCreate(
                recipient_member_id=recipient.id,
                body_markdown="changed",
                payload={"work_item_id": 7},
            ),
            delivery_key="approval:7:request",
        )

    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert len(messages) == 1
    assert messages[0].body_markdown == "original"


def _broadcast(audience_type, audience_id, *, sender_member_id=None, body="broadcast"):
    return MailMessageCreate(
        kind="broadcast",
        sender_member_id=sender_member_id,
        body_markdown=body,
        audience_type=audience_type,
        audience_id=str(audience_id),
    )


@pytest.mark.asyncio
async def test_repository_broadcast_uses_exact_repo_id(db, svc):
    sender = await _member(db, "repo-a", "sender")
    same_repo = await _member(
        db, "repo-a", "same repo", identity_key="repo:repo-a:second-member"
    )
    other_repo = await _member(db, "repo-b", "other repo")

    await svc.send_message(db, _broadcast("repository", "repo-a", sender_member_id=sender.id))

    assert (await svc.get_inbox(db, same_repo.id)).unread_count == 1
    assert (await svc.get_inbox(db, other_repo.id)).unread_count == 0


@pytest.mark.asyncio
async def test_team_preset_broadcast_only_targets_preset_members(db, svc):
    preset = AgentTeamPreset(name="mail audience")
    other_preset = AgentTeamPreset(name="other audience")
    db.add_all([preset, other_preset])
    await db.flush()
    sender = await _member(db, "repo-a", "sender", team_preset_id=preset.id)
    member = await _member(db, "repo-b", "member", team_preset_id=preset.id)
    outsider = await _member(db, "repo-c", "outsider", team_preset_id=other_preset.id)

    await svc.send_message(db, _broadcast("team_preset", preset.id, sender_member_id=sender.id))

    assert (await svc.get_inbox(db, member.id)).unread_count == 1
    assert (await svc.get_inbox(db, outsider.id)).unread_count == 0


@pytest.mark.asyncio
async def test_work_item_broadcast_restricts_preset_and_configured_repo(db, svc):
    preset = AgentTeamPreset(name="work item team")
    outsider_preset = AgentTeamPreset(name="other team")
    db.add_all([preset, outsider_preset])
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo-a",
        repo_path="/tmp/repo-a",
    )
    slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="worker",
        provider="codex-cli",
        repo_id="repo-a-id",
        repo_path="/tmp/repo-a",
        repo_name="repo-a",
    )
    db.add_all([scope, slot])
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=3,
        issue_title="Issue",
        issue_url="https://example.test/3",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    match = await _member(db, "repo-a-id", "match", team_preset_id=preset.id)
    wrong_repo = await _member(db, "repo-b-id", "wrong repo", team_preset_id=preset.id)
    wrong_preset = await _member(
        db,
        "repo-a-id",
        "wrong preset",
        team_preset_id=outsider_preset.id,
        identity_key="slot:wrong-preset",
    )

    await svc.send_message(db, _broadcast("work_item", item.id))

    assert (await svc.get_inbox(db, match.id)).unread_count == 1
    assert (await svc.get_inbox(db, wrong_repo.id)).unread_count == 0
    assert (await svc.get_inbox(db, wrong_preset.id)).unread_count == 0


@pytest.mark.asyncio
async def test_work_item_broadcast_fails_closed_without_unambiguous_repo(db, svc):
    preset = AgentTeamPreset(name="ambiguous team")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo-a",
        repo_path="/tmp/repo-a",
    )
    slots = [
        AgentTeamSlot(
            preset_id=preset.id,
            position=index,
            display_name=f"worker-{index}",
            provider="codex-cli",
            repo_id=repo_id,
            repo_path="/tmp/repo-a",
            repo_name="repo-a",
        )
        for index, repo_id in enumerate(("repo-a", "repo-b"))
    ]
    db.add_all([scope, *slots])
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=4,
        issue_title="Ambiguous",
        issue_url="https://example.test/4",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    with pytest.raises(ValueError, match="unambiguous configured repository"):
        await svc.send_message(db, _broadcast("work_item", item.id))


@pytest.mark.asyncio
async def test_global_broadcast_requires_trusted_operator_authorization(db, svc):
    member = await _member(db, "repo-a", "member")
    request = _broadcast("operator_global", "global")
    with pytest.raises(ValueError, match="operator_authorization_required"):
        await svc.send_message(db, request, sender_actor_id=1)
    await svc.send_message(db, request, operator_authorized=True)
    assert (await svc.get_inbox(db, member.id)).unread_count == 1


@pytest.mark.asyncio
async def test_missing_or_invalid_audience_rejected(db, svc):
    with pytest.raises(ValueError, match="explicit audience"):
        await svc.send_message(db, MailMessageCreate(body_markdown="implicit"))
    with pytest.raises(ValueError, match="does not exist"):
        await svc.send_message(db, _broadcast("team_preset", "999999"))
    with pytest.raises(ValueError, match="positive integer"):
        await svc.send_message(db, _broadcast("work_item", "not-an-id"))


@pytest.mark.asyncio
async def test_keyed_replay_preserves_receipts_after_membership_changes(db, svc):
    first_member = await _member(db, "repo-a", "first")
    request = _broadcast("repository", "repo-a")
    first = await svc.send_message(db, request, delivery_key="repo-broadcast:1")
    first_member.repo_id = "repo-other"
    await db.commit()
    later_member = await _member(
        db, "repo-a", "later", identity_key="repo:repo-a:later"
    )

    replay = await svc.send_message(db, request, delivery_key="repo-broadcast:1")

    assert replay.id == first.id
    receipt_ids = set((await svc.recipient_ids_for_message(db, first.id)))
    assert receipt_ids == {first_member.id}
    assert later_member.id not in receipt_ids


@pytest.mark.asyncio
async def test_keyed_replay_rejects_conflicting_audience(db, svc):
    await _member(db, "repo-a", "alpha")
    await _member(db, "repo-b", "beta")
    await svc.send_message(
        db, _broadcast("repository", "repo-a"), delivery_key="audience-conflict:1"
    )

    with pytest.raises(MailDeliveryIntegrityError):
        await svc.send_message(
            db, _broadcast("repository", "repo-b"), delivery_key="audience-conflict:1"
        )


@pytest.mark.asyncio
async def test_legacy_direct_keyed_replay_keeps_original_receipt(db, svc):
    recipient = await _member(db, "repo-a", "recipient")
    request = MailMessageCreate(recipient_member_id=recipient.id, body_markdown="legacy")
    original = await svc.send_message(db, request, delivery_key="legacy-direct:1")
    stored = await db.get(MailMessage, original.id)
    stored.audience_type = None
    stored.audience_id = None
    await db.commit()

    replay = await svc.send_message(db, request, delivery_key="legacy-direct:1")

    assert replay.id == original.id
    assert await svc.recipient_ids_for_message(db, original.id) == {recipient.id}


@pytest.mark.asyncio
async def test_keyed_answer_replay_still_checks_current_thread_authority(db, svc):
    sender = await _member(db, "repo-a", "sender")
    recipient = await _member(db, "repo-a", "recipient", identity_key="repo:repo-a:recipient")
    root = await svc.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=sender.id,
            recipient_member_id=recipient.id,
            body_markdown="Question",
        ),
    )
    answer = MailMessageCreate(
        kind="answer",
        sender_member_id=recipient.id,
        thread_root_id=root.id,
        body_markdown="Answer",
    )
    await svc.send_message(db, answer, delivery_key="answer-replay:1")
    stored_root = await db.get(MailMessage, root.id)
    stored_root.request_status = "superseded"
    await db.commit()

    with pytest.raises(ValueError, match="superseded context requests"):
        await svc.send_message(db, answer, delivery_key="answer-replay:1")


@pytest.mark.asyncio
async def test_legacy_global_broadcast_cannot_replay_as_scoped(db, svc):
    first = await _member(db, "legacy-a", "legacy-a")
    second = await _member(db, "legacy-b", "legacy-b")
    historical = MailMessage(
        kind="broadcast",
        body_markdown="broadcast",
        delivery_key="legacy-global:1",
    )
    db.add(historical)
    await db.flush()
    db.add_all(
        [
            MailReceipt(message_id=historical.id, member_id=first.id),
            MailReceipt(message_id=historical.id, member_id=second.id),
        ]
    )
    await db.commit()

    with pytest.raises(MailDeliveryIntegrityError):
        await svc.send_message(
            db,
            _broadcast("repository", "legacy-a"),
            delivery_key="legacy-global:1",
        )

    assert await svc.recipient_ids_for_message(db, historical.id) == {first.id, second.id}


def test_delivery_key_is_not_agent_authored_schema():
    assert "delivery_key" not in MailMessageCreate.model_fields


@pytest.mark.asyncio
async def test_thread_reply_preserves_all_original_participant_receipts(db, svc):
    first = await _member(db, "thread-first", "first")
    second = await _member(db, "thread-second", "second")
    root = await svc.send_message(
        db,
        MailMessageCreate(
            sender_member_id=first.id,
            recipient_member_id=second.id,
            body_markdown="Original",
        ),
    )

    reply = await svc.send_message(
        db,
        MailMessageCreate(thread_root_id=root.id, body_markdown="Coordinator reply"),
    )

    assert reply.audience_type == "member"
    assert reply.audience_id == f"thread:{root.id}"
    assert await svc.recipient_ids_for_message(db, reply.id) == {first.id, second.id}


# --- #752: canonical thread roots, delivery and retrieval -------------------------------------
# A reply may pass ANY message id of a thread. Everything that follows (permission, audience,
# receipts, the stored thread id, the delivery key and the thread view) must use the canonical
# root, while an explicit answer still resolves only the request row it names.

async def _mail_count(db):
    return (
        await db.scalar(select(func.count()).select_from(MailMessage)),
        await db.scalar(select(func.count()).select_from(MailReceipt)),
    )


async def _raw_row(db, sender, recipient, thread, *, kind="message", status=None, holders=()):
    """A row written directly, as an older release stored it (thread id may be a non-root)."""
    row = MailMessage(
        kind=kind, sender_member_id=sender.id if sender else None,
        recipient_member_id=recipient.id if recipient else None, thread_root_id=thread,
        body_markdown="legacy", request_status=status, audience_type="member",
        audience_id=str(recipient.id) if recipient else None,
    )
    db.add(row)
    await db.flush()
    for member in holders:
        db.add(MailReceipt(message_id=row.id, member_id=member.id))
    await db.flush()
    return row


async def _pair(db, svc, tag):
    first = await _member(db, f"{tag}-a", f"{tag}-a")
    second = await _member(db, f"{tag}-b", f"{tag}-b")
    root = await svc.send_message(
        db, MailMessageCreate(sender_member_id=first.id, recipient_member_id=second.id, body_markdown="root"))
    return first, second, root


async def _reply(svc, db, sender, thread, **kwargs):
    return await svc.send_message(
        db, MailMessageCreate(sender_member_id=sender.id, thread_root_id=thread, body_markdown="reply", **kwargs))


@pytest.mark.asyncio
async def test_reply_by_root_id_reaches_the_other_participant(db, svc):
    first, second, root = await _pair(db, svc, "root")
    by_second = await _reply(svc, db, second, root.id)
    by_first = await _reply(svc, db, first, root.id)
    assert await svc.recipient_ids_for_message(db, by_second.id) == {first.id}
    assert await svc.recipient_ids_for_message(db, by_first.id) == {second.id}
    assert by_second.thread_root_id == by_first.thread_root_id == root.id


@pytest.mark.asyncio
async def test_reply_by_reply_id_reaches_the_same_participants(db, svc):
    first, second, root = await _pair(db, svc, "byreply")
    reply = await _reply(svc, db, first, root.id)
    nested = await _reply(svc, db, second, reply.id)
    assert await svc.recipient_ids_for_message(db, nested.id) == {first.id}
    assert nested.thread_root_id == root.id


@pytest.mark.asyncio
async def test_reply_with_own_earlier_reply_id_reaches_the_other_participant(db, svc):
    first, second, root = await _pair(db, svc, "own")
    reply = await _reply(svc, db, first, root.id)
    again = await _reply(svc, db, first, reply.id)
    assert await svc.recipient_ids_for_message(db, again.id) == {second.id}
    assert again.thread_root_id == root.id


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [2, 3, 5, 32])
async def test_deep_chains_resolve_to_the_canonical_root(db, svc, depth):
    first, second, root = await _pair(db, svc, f"deep{depth}")
    parent = root.id
    for index in range(depth):
        sender = second if index % 2 == 0 else first
        row = await _raw_row(db, sender, None, parent, holders=(first, second))
        parent = row.id
    sent = await _reply(svc, db, first, parent)
    assert sent.thread_root_id == root.id
    assert await svc.recipient_ids_for_message(db, sent.id) == {second.id}
    assert (await svc.resolve_canonical_root(db, parent)).id == root.id


@pytest.mark.asyncio
async def test_stored_thread_root_is_canonical_and_get_thread_lists_every_reply(db, svc):
    first, second, root = await _pair(db, svc, "view")
    one = await _reply(svc, db, first, root.id)
    two = await _reply(svc, db, second, one.id)
    three = await _reply(svc, db, first, two.id)
    thread = await svc.get_thread(db, root.id)
    assert [reply.id for reply in thread.replies] == [one.id, two.id, three.id]
    assert {reply.thread_root_id for reply in thread.replies} == {root.id}
    assert thread.replies_complete is True and thread.replies_incomplete_reason is None


@pytest.mark.asyncio
async def test_missing_ancestor_cycle_and_33_hops_refuse_without_rows(db, svc):
    first, second, root = await _pair(db, svc, "refuse")
    # A missing ancestor two hops up (the one-hop check still passes, the resolver refuses).
    orphan_parent = await _raw_row(db, second, None, 987654, holders=(first, second))
    orphan_child = await _raw_row(db, second, None, orphan_parent.id, holders=(first, second))
    # A two-row cycle and a self loop.
    loop_a = await _raw_row(db, second, None, None, holders=(first, second))
    loop_b = await _raw_row(db, second, None, loop_a.id, holders=(first, second))
    loop_a.thread_root_id = loop_b.id
    self_loop = await _raw_row(db, second, None, None, holders=(first, second))
    self_loop.thread_root_id = self_loop.id
    # 32 hops resolve, 33 refuse.
    parent = root.id
    hops = {}
    for index in range(1, 34):
        row = await _raw_row(db, second, None, parent, holders=(first, second))
        hops[index] = row.id
        parent = row.id
    await db.commit()
    before = await _mail_count(db)
    for bad in (orphan_child.id, loop_b.id, loop_a.id, self_loop.id, hops[33]):
        with pytest.raises(ValueError):
            await svc.resolve_canonical_root(db, bad)
    for bad in (orphan_child.id, loop_b.id, hops[33]):
        with pytest.raises(ValueError):
            await _reply(svc, db, first, bad)
    assert await _mail_count(db) == before
    assert (await svc.resolve_canonical_root(db, hops[32])).id == root.id
    assert (await _reply(svc, db, first, hops[32])).thread_root_id == root.id


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [True, False])
async def test_reply_reaching_nobody_refuses_without_rows(db, svc, commit):
    first = await _member(db, f"nobody-{commit}", f"nobody-{commit}")
    lonely = await _raw_row(db, first, None, None, holders=(first,))
    await db.commit()
    before = await _mail_count(db)
    with pytest.raises(ValueError):
        await svc.send_message(
            db, MailMessageCreate(sender_member_id=first.id, thread_root_id=lonely.id, body_markdown="to nobody"),
            commit=commit)
    assert await _mail_count(db) == before
    await db.rollback()
    assert await _mail_count(db) == before


@pytest.mark.asyncio
async def test_explicit_recipient_in_the_canonical_set_is_normalized(db, svc):
    first, second, root = await _pair(db, svc, "explicit")
    reply = await _reply(svc, db, first, root.id, recipient_member_id=second.id)
    assert await svc.recipient_ids_for_message(db, reply.id) == {second.id}
    assert reply.thread_root_id == root.id


@pytest.mark.asyncio
async def test_foreign_explicit_recipient_refuses_before_any_mutation(db, svc):
    first, second, root = await _pair(db, svc, "foreign")
    stranger = await _member(db, "foreign-x", "foreign-x")
    before = await _mail_count(db)
    with pytest.raises(ValueError):
        await _reply(svc, db, first, root.id, recipient_member_id=stranger.id)
    assert await _mail_count(db) == before


@pytest.mark.asyncio
async def test_direct_message_behavior_is_unchanged(db, svc):
    first = await _member(db, "direct-a", "direct-a")
    second = await _member(db, "direct-b", "direct-b")
    message = await svc.send_message(
        db, MailMessageCreate(sender_member_id=first.id, recipient_member_id=second.id, body_markdown="hi"))
    assert message.thread_root_id is None
    assert message.audience_id == str(second.id)
    assert await svc.recipient_ids_for_message(db, message.id) == {second.id}


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["context_request", "handoff"])
async def test_request_with_a_thread_id_refuses(db, svc, kind):
    """A request starts its own thread: it is refused, for a member and for an external actor."""
    from app.models.database import MailExternalActor

    first, second, root = await _pair(db, svc, f"nested-{kind}")
    actor = MailExternalActor(actor_key=f"refuse-{kind}", display_name="Actor", kind="external_tool",
                              token_hash=f"hash-{kind}")
    db.add(actor)
    await db.commit()
    before = await _mail_count(db)
    with pytest.raises(ValueError, match="a request starts its own thread"):
        await svc.send_message(db, MailMessageCreate(
            kind=kind, sender_member_id=first.id, recipient_member_id=second.id,
            thread_root_id=root.id, body_markdown="a request inside a thread"))
    with pytest.raises(ValueError, match="a request starts its own thread"):
        await svc.send_message(db, MailMessageCreate(
            kind=kind, recipient_member_id=second.id, thread_root_id=root.id, body_markdown="actor request"),
            sender_actor_id=actor.id)
    assert await _mail_count(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["context_request", "handoff"])
async def test_an_outsider_gets_the_authorization_refusal_before_the_request_refusal(db, svc, kind):
    first, second, root = await _pair(db, svc, f"order-{kind}")
    outsider = await _member(db, f"order-x-{kind}", f"order-x-{kind}")
    before = await _mail_count(db)
    with pytest.raises(PermissionError):
        await svc.send_message(db, MailMessageCreate(
            kind=kind, sender_member_id=outsider.id, recipient_member_id=first.id,
            thread_root_id=root.id, body_markdown="not a participant"))
    assert await _mail_count(db) == before


@pytest.mark.asyncio
async def test_self_and_stranger_recipients_are_refused_but_the_other_participant_is_accepted(db, svc):
    first, second, root = await _pair(db, svc, "selfaddr")
    stranger = await _member(db, "selfaddr-x", "selfaddr-x")
    before = await _mail_count(db)
    for recipient in (first, stranger):
        with pytest.raises(ValueError, match="not a participant of the thread"):
            await _reply(svc, db, first, root.id, recipient_member_id=recipient.id)
    assert await _mail_count(db) == before
    ok = await _reply(svc, db, first, root.id, recipient_member_id=second.id)
    assert ok.thread_root_id == root.id
    assert await svc.recipient_ids_for_message(db, ok.id) == {second.id}


@pytest.mark.asyncio
async def test_answer_resolves_only_the_supplied_pending_request_never_an_ancestor(db, svc):
    first = await _member(db, "answer-a", "answer-a")
    second = await _member(db, "answer-b", "answer-b")
    ancestor = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=first.id, recipient_member_id=second.id, body_markdown="root ask"))
    legacy = await _raw_row(db, first, second, ancestor.id, kind="context_request", status="pending",
                            holders=(first, second))
    await db.commit()
    answer = await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=second.id, thread_root_id=legacy.id, body_markdown="answers the nested one"))
    assert answer.thread_root_id == ancestor.id
    assert (await db.get(MailMessage, legacy.id)).request_status == "answered"
    assert (await db.get(MailMessage, ancestor.id)).request_status == "pending"
    assert first.id in await svc.recipient_ids_for_message(db, answer.id)
    root_answer = await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=second.id, thread_root_id=ancestor.id, body_markdown="answers the root"))
    assert (await db.get(MailMessage, ancestor.id)).request_status == "answered"
    assert root_answer.thread_root_id == ancestor.id


@pytest.mark.asyncio
async def test_answer_through_an_ordinary_reply_id_resolves_the_canonical_root_request(db, svc):
    first = await _member(db, "viaord-a", "viaord-a")
    second = await _member(db, "viaord-b", "viaord-b")
    ask = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=first.id, recipient_member_id=second.id, body_markdown="ask"))
    follow = await _reply(svc, db, first, ask.id)
    answer = await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=second.id, thread_root_id=follow.id, body_markdown="answered"))
    assert answer.thread_root_id == ask.id
    assert (await db.get(MailMessage, ask.id)).request_status == "answered"
    # An ordinary reply id under a root that is NOT addressed to the answerer resolves nothing.
    third = await _member(db, "viaord-c", "viaord-c")
    other_ask = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=first.id, recipient_member_id=third.id, body_markdown="other"))
    other_follow = await _reply(svc, db, first, other_ask.id)
    with pytest.raises(PermissionError):
        await svc.send_message(db, MailMessageCreate(
            kind="answer", sender_member_id=second.id, thread_root_id=other_follow.id, body_markdown="no"))
    assert (await db.get(MailMessage, other_ask.id)).request_status == "pending"


@pytest.mark.asyncio
async def test_third_member_with_intermediate_only_access_is_refused_on_get_thread_reply_and_answer(db, svc):
    """The third member can read the supplied row's PARENT (one hop), so the existing check passes.
    Only the canonical-root check refuses: the member has no access to the thread's real root."""
    first, second, root = await _pair(db, svc, "third")
    third = await _member(db, "third-x", "third-x")
    parent = await _raw_row(db, first, second, root.id, holders=(first, second, third))
    intermediate = await _raw_row(db, first, third, parent.id, kind="context_request", status="pending",
                                  holders=(first, third))
    await db.commit()
    before = await _mail_count(db)
    with pytest.raises(PermissionError):
        await svc.get_thread(db, intermediate.id, for_member_id=third.id)
    with pytest.raises(PermissionError):
        await _reply(svc, db, third, intermediate.id)
    with pytest.raises(PermissionError):
        await svc.send_message(db, MailMessageCreate(
            kind="answer", sender_member_id=third.id, thread_root_id=intermediate.id, body_markdown="no"))
    assert await _mail_count(db) == before
    assert (await db.get(MailMessage, intermediate.id)).request_status == "pending"
    # A member of the real root can still read and reply through the same intermediate id.
    assert (await svc.get_thread(db, intermediate.id, for_member_id=second.id)).root.id == root.id
    assert (await _reply(svc, db, second, intermediate.id)).thread_root_id == root.id


@pytest.mark.asyncio
async def test_delivery_key_replay_with_a_nested_id_is_idempotent(db, svc):
    first, second, root = await _pair(db, svc, "replay")
    reply = await _reply(svc, db, first, root.id)
    sent = await svc.send_message(db, MailMessageCreate(
        sender_member_id=second.id, thread_root_id=reply.id, body_markdown="once"), delivery_key="k-752")
    same = await svc.send_message(db, MailMessageCreate(
        sender_member_id=second.id, thread_root_id=reply.id, body_markdown="once"), delivery_key="k-752")
    by_root = await svc.send_message(db, MailMessageCreate(
        sender_member_id=second.id, thread_root_id=root.id, body_markdown="once"), delivery_key="k-752")
    assert sent.id == same.id == by_root.id
    assert sent.thread_root_id == root.id
    assert await db.scalar(select(func.count()).select_from(MailMessage)
                           .where(MailMessage.delivery_key == "k-752")) == 1


@pytest.mark.asyncio
async def test_get_thread_returns_the_canonical_root_with_both_authorizations(db, svc):
    first, second, root = await _pair(db, svc, "canon")
    stranger = await _member(db, "canon-x", "canon-x")
    reply = await _reply(svc, db, first, root.id)
    nested = await _reply(svc, db, second, reply.id)
    thread = await svc.get_thread(db, nested.id, for_member_id=second.id)
    assert thread.root.id == root.id
    assert [item.id for item in thread.replies] == [reply.id, nested.id]
    with pytest.raises(PermissionError):
        await svc.get_thread(db, nested.id, for_member_id=stranger.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("count,complete,reason", [(500, True, None), (501, False, "reply_limit")])
async def test_get_thread_reply_limit_sentinel(db, svc, count, complete, reason):
    first, second, root = await _pair(db, svc, f"limit{count}")
    db.add_all([MailMessage(kind="message", sender_member_id=second.id, thread_root_id=root.id,
                            body_markdown=f"r{index}", audience_type="member", audience_id=str(first.id))
                for index in range(count)])
    await db.commit()
    thread = await svc.get_thread(db, root.id)
    assert len(thread.replies) == min(count, 500)
    assert thread.replies_complete is complete
    assert thread.replies_incomplete_reason == reason


# --- bounded thread traversal (#752): work does not grow with the number of descendants -------------

async def _bulk_replies(db, parent, sender, count, *, base=None, invert=False):
    """``count`` replies stored directly under ``parent``; ids ascend, created_at ascends (or descends)."""
    base = base or datetime(2026, 1, 1)
    rows = [{"kind": "message", "sender_member_id": sender.id, "thread_root_id": parent, "body_markdown": "r",
             "audience_type": "member", "audience_id": str(sender.id),
             "created_at": base + timedelta(seconds=(-index if invert else index))} for index in range(count)]
    await db.execute(MailMessage.__table__.insert(), rows)
    await db.commit()


async def _vm_operations(db, read):
    """SQLite virtual-machine operations (sampled every 10) used by one awaited read."""
    connection = await (await db.connection()).get_raw_connection()
    driver = connection.driver_connection
    ticks = [0]

    def tick():
        ticks[0] += 1
        return 0

    await driver.set_progress_handler(tick, 10)
    try:
        await read()
    finally:
        await driver.set_progress_handler(None, 0)
    return ticks[0] * 10


@pytest.mark.asyncio
async def test_thread_read_work_does_not_grow_with_direct_children(db, svc):
    first, second, small = await _pair(db, svc, "work-small")
    _f, _s, large = await _pair(db, svc, "work-large")
    await _bulk_replies(db, small.id, second, 600)
    await _bulk_replies(db, large.id, second, 6000)
    small_ops = await _vm_operations(db, lambda: svc.get_thread(db, small.id))
    large_ops = await _vm_operations(db, lambda: svc.get_thread(db, large.id))
    for root in (small, large):
        thread = await svc.get_thread(db, root.id)
        assert len(thread.replies) == 500 and thread.replies_incomplete_reason == "reply_limit"
    assert large_ops <= small_ops * 1.25, (small_ops, large_ops)


@pytest.mark.asyncio
async def test_thread_read_work_does_not_grow_with_a_wide_legacy_parent(db, svc):
    first, second, small = await _pair(db, svc, "wide-small")
    _f, _s, large = await _pair(db, svc, "wide-large")
    small_parent = await _raw_row(db, second, None, small.id, holders=(first, second))
    large_parent = await _raw_row(db, second, None, large.id, holders=(first, second))
    await db.commit()
    await _bulk_replies(db, small_parent.id, second, 600)
    await _bulk_replies(db, large_parent.id, second, 6000)
    small_ops = await _vm_operations(db, lambda: svc.get_thread(db, small.id))
    large_ops = await _vm_operations(db, lambda: svc.get_thread(db, large.id))
    thread = await svc.get_thread(db, large.id)
    assert len(thread.replies) == 500 and thread.replies_incomplete_reason == "reply_limit"
    assert large_ops <= small_ops * 1.25, (small_ops, large_ops)


@pytest.mark.asyncio
async def test_a_truncated_thread_holds_the_smallest_ids_by_depth_and_id_and_displays_by_time(db, svc):
    first, second, root = await _pair(db, svc, "oracle")
    parents = [await _raw_row(db, second, None, root.id, holders=(first, second)) for _ in range(3)]
    await db.commit()
    # Children spread over the three depth-1 parents with interleaved ids; later ids are EARLIER in time.
    base = datetime(2026, 1, 1)
    rows = [{"kind": "message", "sender_member_id": second.id, "thread_root_id": parents[index % 3].id,
             "body_markdown": "r", "audience_type": "member", "audience_id": str(second.id),
             "created_at": base - timedelta(seconds=index)} for index in range(700)]
    await db.execute(MailMessage.__table__.insert(), rows)
    await db.commit()
    everything = (await db.execute(select(MailMessage.id, MailMessage.thread_root_id, MailMessage.created_at)
                                   .where(MailMessage.id > root.id))).all()
    depth = {parent.id: 1 for parent in parents}
    ordered = sorted(((depth.get(row.thread_root_id, 0) + (0 if row.thread_root_id == root.id else 1)
                       if row.id not in depth else 1, row.id) for row in everything))
    oracle = [row_id for _depth, row_id in ordered][:500]
    created = {row.id: row.created_at for row in everything}
    thread = await svc.get_thread(db, root.id)
    assert thread.replies_complete is False and thread.replies_incomplete_reason == "reply_limit"
    assert {reply.id for reply in thread.replies} == set(oracle)
    assert [reply.id for reply in thread.replies] == sorted(oracle, key=lambda row_id: (created[row_id], row_id))


@pytest.mark.asyncio
async def test_the_thread_probe_uses_the_thread_root_index_without_sorting(db, svc):
    first, second, root = await _pair(db, svc, "plan")
    await _bulk_replies(db, root.id, second, 40)
    query = AgentMailService._thread_child_page(root.id, 0)
    sql = str(query.compile(compile_kwargs={"literal_binds": True}))
    detail = " ".join(row[3] for row in (await db.execute(text("EXPLAIN QUERY PLAN " + sql))).all())
    assert "SEARCH" in detail and "ix_mail_messages_thread_root_id" in detail
    assert "TEMP B-TREE" not in detail and "SCAN" not in detail


@pytest.mark.asyncio
async def test_a_chain_deeper_than_the_limit_stops_at_depth_thirty_three(db, svc):
    first, second, root = await _pair(db, svc, "chain40")
    parent = root.id
    for _ in range(40):
        parent = (await _raw_row(db, second, None, parent, holders=(first, second))).id
    await db.commit()
    thread = await svc.get_thread(db, root.id)
    assert len(thread.replies) == 33 and thread.replies_incomplete_reason == "depth_limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("depth,complete,reason", [(32, True, None), (33, False, "depth_limit")])
async def test_get_thread_depth_limit_sentinel(db, svc, depth, complete, reason):
    first, second, root = await _pair(db, svc, f"depth{depth}")
    parent = root.id
    for _ in range(depth):
        parent = (await _raw_row(db, second, None, parent, holders=(first, second))).id
    await db.commit()
    thread = await svc.get_thread(db, root.id)
    assert thread.replies_complete is complete
    assert thread.replies_incomplete_reason == reason
    assert len(thread.replies) == depth


# --- #752 correction: canonical audience, exact answer target, replay -----------------------------
# The audience and receipts of every thread message come from the canonical root. The request row an
# answer resolves is a separate, exact target, and a replay must not silently change it.

async def _canonical_fixture(db, svc, tag):
    """Root R (context_request A to B, pending) and a legacy nested request C to B inside it."""
    a = await _member(db, f"{tag}-a", f"{tag}-a")
    b = await _member(db, f"{tag}-b", f"{tag}-b")
    c = await _member(db, f"{tag}-c", f"{tag}-c")
    root = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=a.id, recipient_member_id=b.id, body_markdown="root ask"),
        auto_nudge=False)
    nested = await _raw_row(db, c, b, root.id, kind="context_request", status="pending", holders=(c, b))
    await db.commit()
    return a, b, c, root, nested


async def _answer(svc, db, sender, thread, **kwargs):
    return await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=sender.id, thread_root_id=thread, body_markdown="answer"),
        auto_nudge=False, **kwargs)


@pytest.mark.asyncio
async def test_a_nested_answer_is_delivered_to_the_canonical_roots_participants_not_the_requester(db, svc):
    a, b, c, root, nested = await _canonical_fixture(db, svc, "canon-pos")
    answer = await _answer(svc, db, b, nested.id)
    assert await svc.recipient_ids_for_message(db, answer.id) == {a.id}   # the root's sender, never C
    assert answer.thread_root_id == root.id
    assert (await db.get(MailMessage, nested.id)).request_status == "answered"
    assert (await db.get(MailMessage, root.id)).request_status == "pending"
    assert (await db.get(MailMessage, answer.id)).payload == {"resolves_request_id": nested.id}


@pytest.mark.asyncio
async def test_a_nested_answer_cannot_pass_a_root_the_answerer_is_not_part_of(db, svc):
    a = await _member(db, "canon-neg-a", "canon-neg-a")
    b = await _member(db, "canon-neg-b", "canon-neg-b")
    c = await _member(db, "canon-neg-c", "canon-neg-c")
    root = await svc.send_message(db, MailMessageCreate(
        sender_member_id=a.id, recipient_member_id=c.id, body_markdown="A and C only"), auto_nudge=False)
    nested = await _raw_row(db, a, b, root.id, kind="context_request", status="pending", holders=(a, b))
    await db.commit()
    before = await _mail_count(db)
    with pytest.raises(PermissionError):
        await _answer(svc, db, b, nested.id)
    assert await _mail_count(db) == before
    assert (await db.get(MailMessage, nested.id)).request_status == "pending"


@pytest.mark.asyncio
async def test_a_same_key_replay_with_the_same_exact_target_is_idempotent(db, svc):
    a, b, c, root, nested = await _canonical_fixture(db, svc, "replay-same")
    first = await _answer(svc, db, b, nested.id, delivery_key="k-exact")
    again = await _answer(svc, db, b, nested.id, delivery_key="k-exact")
    assert first.id == again.id
    assert await db.scalar(select(func.count()).select_from(MailMessage)
                           .where(MailMessage.delivery_key == "k-exact")) == 1
    assert (await db.get(MailMessage, nested.id)).request_status == "answered"


@pytest.mark.asyncio
async def test_a_same_key_replay_through_another_target_conflicts_and_resolves_nothing(db, svc):
    a, b, c, root, nested = await _canonical_fixture(db, svc, "replay-conflict")
    other = await _raw_row(db, c, b, root.id, kind="context_request", status="pending", holders=(c, b))
    await db.commit()
    await _answer(svc, db, b, nested.id, delivery_key="k-conflict")
    before = await _mail_count(db)
    with pytest.raises(MailDeliveryIntegrityError):
        await _answer(svc, db, b, root.id, delivery_key="k-conflict")       # the root request instead
    with pytest.raises(MailDeliveryIntegrityError):
        await _answer(svc, db, b, other.id, delivery_key="k-conflict")      # another nested request
    assert await _mail_count(db) == before
    assert (await db.get(MailMessage, root.id)).request_status == "pending"
    assert (await db.get(MailMessage, other.id)).request_status == "pending"
    assert (await db.get(MailMessage, nested.id)).request_status == "answered"


@pytest.mark.asyncio
async def test_a_normal_answer_replays_through_any_reply_id_of_the_same_thread(db, svc):
    first = await _member(db, "replay-norm-a", "replay-norm-a")
    second = await _member(db, "replay-norm-b", "replay-norm-b")
    ask = await svc.send_message(db, MailMessageCreate(
        kind="context_request", sender_member_id=first.id, recipient_member_id=second.id, body_markdown="ask"),
        auto_nudge=False)
    follow = await _reply(svc, db, first, ask.id)
    one = await _answer(svc, db, second, ask.id, delivery_key="k-normal")
    two = await _answer(svc, db, second, follow.id, delivery_key="k-normal")
    assert one.id == two.id
    assert (await db.get(MailMessage, one.id)).payload is None
    assert (await db.get(MailMessage, ask.id)).request_status == "answered"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["message", "answer"])
async def test_a_caller_cannot_supply_the_reserved_resolution_metadata(db, svc, kind):
    a, b, c, root, nested = await _canonical_fixture(db, svc, f"reserved-{kind}")
    before = await _mail_count(db)
    with pytest.raises(ValueError, match="resolves_request_id"):
        await svc.send_message(db, MailMessageCreate(
            kind=kind, sender_member_id=b.id, thread_root_id=nested.id, body_markdown="spoof",
            payload={"resolves_request_id": root.id, "note": "kept elsewhere"}), auto_nudge=False)
    assert await _mail_count(db) == before
    assert (await db.get(MailMessage, root.id)).request_status == "pending"
    # Other caller payload fields are preserved on an ordinary answer.
    kept = await svc.send_message(db, MailMessageCreate(
        kind="answer", sender_member_id=b.id, thread_root_id=root.id, body_markdown="ok",
        payload={"note": "kept"}), auto_nudge=False)
    assert (await db.get(MailMessage, kept.id)).payload == {"note": "kept"}
