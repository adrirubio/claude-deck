"""Messaging: receipts, broadcast, request lifecycle, stale flag, counts."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

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
