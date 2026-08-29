"""HTTP surface for team and messages."""
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.config import settings
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailAgentSession,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import agent_mail_service
from app.services.github_approval_service import (
    GithubApprovalError,
    github_approval_service,
)
from app.utils import peer_process


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def live_slot_session_bindings(monkeypatch):
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: True)


async def _member(db, repo_id, name):
    member = MailTeamMember(
        identity_key=f"repo:{repo_id}",
        repo_id=repo_id,
        repo_path=f"/tmp/{name}",
        repo_name=name,
        display_name=name,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def _session_headers(db, member, key):
    token = f"token-{key}"
    db.add(
        MailAgentSession(
            member_id=member.id,
            provider="codex-cli",
            source="mcp",
            session_key=f"mcp:{key}",
            cwd=member.repo_path,
            mailbox_status="connected",
            last_seen_at=datetime.utcnow(),
            capability_token_hash=agent_mail_service.hash_capability_token(token),
        )
    )
    await db.commit()
    return {"X-Deck-Session-Token": token}


async def _dispatch_approval_fixture(db):
    preset = AgentTeamPreset(name="Approval", description="", created_by="test")
    db.add(preset)
    await db.flush()
    slots = []
    members = []
    sessions = []
    tokens = []
    for position, name in enumerate(("Leader", "Owner")):
        slot = AgentTeamSlot(
            preset_id=preset.id,
            position=position,
            display_name=name,
            provider="codex-cli",
            repo_id="approval",
            repo_path="/tmp/approval",
            repo_name="approval",
            launch_mode="plain",
            launch_options={},
            enabled=True,
        )
        db.add(slot)
        await db.flush()
        member = MailTeamMember(
            identity_key=f"slot:approval:{slot.id}",
            repo_id="approval",
            repo_path="/tmp/approval",
            repo_name="approval",
            display_name=name,
            participant_kind="team_slot",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
        )
        db.add(member)
        await db.flush()
        token = f"token-{position}"
        session = MailAgentSession(
            member_id=member.id,
            provider="codex-cli",
            source="mcp",
            session_key=f"mcp:approval:{position}",
            cwd="/tmp/approval",
            team_preset_id=preset.id,
            team_slot_id=slot.id,
            mailbox_status="connected",
            last_seen_at=datetime.utcnow(),
            capability_token_hash=agent_mail_service.hash_capability_token(token),
            bound_pane_pid=1000 + position,
            bound_pane_proc_start=f"start-{position}",
        )
        db.add(session)
        slots.append(slot)
        members.append(member)
        sessions.append(session)
        tokens.append(token)
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="o",
        repo_name="approval",
        repo_path="/tmp/approval",
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=91,
        issue_title="approval",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        routing_method="label",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{slots[1].id}/issue-91-0123456789abcdef",
        approval_round_count=1,
    )
    db.add(item)
    await db.commit()
    return item, members, tokens


@pytest.mark.asyncio
async def test_normalized_initial_request_is_idempotent_and_canonical(db):
    item, members, _tokens = await _dispatch_approval_fixture(db)
    request, created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="  bounded plan  ",
        plan_metadata={"paths": ["b", "a"], "checks": {"lint": True}},
    )
    repeated, repeated_created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="bounded plan",
        plan_metadata={"checks": {"lint": True}, "paths": ["b", "a"]},
    )

    assert created is True
    assert repeated_created is False
    assert repeated.id == request.id
    assert len(request.request_fingerprint) == 64
    assert (
        await db.execute(select(GithubApprovalRequest))
    ).scalars().all() == [request]


@pytest.mark.asyncio
async def test_normalized_initial_request_refuses_conflicting_pending_payload(db):
    item, members, _tokens = await _dispatch_approval_fixture(db)
    await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="first",
    )

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.create_initial_request(
            db,
            item,
            authenticated_owner_member_id=members[1].id,
            summary="second",
        )

    assert exc_info.value.detail == "approval_request_already_pending"
    assert len((await db.execute(select(GithubApprovalRequest))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_normalized_initial_request_supersedes_stale_attempt_identity(db):
    item, members, _tokens = await _dispatch_approval_fixture(db)
    first, _created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="first",
    )
    item.approval_round_count = 2
    await db.commit()

    second, created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="revised",
    )
    await db.refresh(first)

    assert created is True
    assert first.status == "superseded"
    assert first.superseded_at is not None
    assert second.approval_round == 2
    assert second.status == "pending"


@pytest.mark.asyncio
async def test_cancel_synchronizes_request_revision_and_mail_root(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )
    approval = await db.get(GithubApprovalRequest, response.json()["id"])
    workspace = GithubWorkspace(scope_id=item.scope_id, path="/tmp/cancel-workspace")
    db.add(workspace)
    await db.flush()
    revision = GithubAttemptScopeRevision(
        work_item_id=item.id,
        dispatch_nonce=item.dispatch_nonce,
        revision=1,
        owner_slot_id=item.owner_slot_id,
        owner_member_id=members[1].id,
        phase="diagnostic",
        execution_target="collect evidence",
        summary="bounded plan",
        allowed_paths=["src/example.py"],
        allowed_actions=["inspect"],
        allowed_commands=["pytest -q"],
        prohibited_actions=["merge"],
        tool_fallbacks={},
        baseline_head_sha="a" * 40,
        baseline_tree_sha="b" * 40,
        originating_escalation_reason="retry_count_exhausted",
        expected_workspace_id=workspace.id,
        expected_lease_token_hash="lease-hash",
        max_failed_heads=1,
        status="proposed",
        approval_request_id=approval.id,
    )
    db.add(revision)
    await db.flush()
    approval.scope_revision_id = revision.id
    await db.commit()
    unrelated = await _member(db, "unrelated", "unrelated")

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.cancel(
            db,
            approval,
            requester_member_id=unrelated.id,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "not_approval_requester"

    cancelled, changed = await github_approval_service.cancel(
        db,
        approval,
        requester_member_id=members[1].id,
    )
    repeated, repeated_changed = await github_approval_service.cancel(
        db,
        approval,
        requester_member_id=members[1].id,
    )

    assert changed is True
    assert repeated_changed is False
    assert repeated.id == cancelled.id
    assert cancelled.status == "superseded"
    assert cancelled.superseded_at is not None
    await db.refresh(revision)
    assert revision.status == "superseded"
    root = await db.get(MailMessage, cancelled.request_message_id)
    assert root.request_status == "superseded"
    _unread, pending = await agent_mail_service.counts_for_member(db, members[0].id)
    assert pending == 0

    decision = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval.id,
            "decision": "approved",
            "reason": "too late",
        },
    )
    assert decision.status_code == 409
    assert decision.json()["detail"] == "request_not_pending"


@pytest.mark.asyncio
async def test_operator_can_cancel_pending_approval_request(db):
    item, members, _tokens = await _dispatch_approval_fixture(db)
    approval, _created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="bounded plan",
    )

    cancelled, changed = await github_approval_service.cancel(
        db,
        approval,
        operator=True,
    )

    assert changed is True
    assert cancelled.status == "superseded"


@pytest.mark.asyncio
async def test_normalized_initial_request_derives_current_owner_and_leader(db):
    item, members, _tokens = await _dispatch_approval_fixture(db)

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.create_initial_request(
            db,
            item,
            authenticated_owner_member_id=members[0].id,
            summary="leader self-submits",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "not_item_owner"
    assert (await db.execute(select(GithubApprovalRequest))).scalars().all() == []


@pytest.mark.asyncio
async def test_explicit_initial_approval_route_commits_authority_then_links_mail(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    observed_linkage = []

    async def observe_nudge(nudge_db, member_ids, **_kwargs):
        approval = (
            await nudge_db.execute(select(GithubApprovalRequest))
        ).scalar_one()
        observed_linkage.append((approval.request_message_id, member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", observe_nudge)
    response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "Change one bounded file and run its focused test.",
            "plan_metadata": {"paths": ["src/example.py"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_kind"] == "initial_plan"
    assert payload["owner_member_id"] == members[1].id
    assert payload["leader_member_id"] == members[0].id
    assert payload["request_message_id"] is not None
    assert observed_linkage == [
        (payload["request_message_id"], {members[0].id})
    ]
    message = await db.get(MailMessage, payload["request_message_id"])
    assert message.delivery_key == f"github-approval:{payload['id']}:request"
    assert message.payload["approval_request_id"] == payload["id"]


@pytest.mark.asyncio
async def test_explicit_initial_approval_route_repairs_unlinked_durable_mail(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    approval, _created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="bounded",
    )
    mail = await agent_mail_service.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=members[1].id,
            recipient_member_id=members[0].id,
            subject=f"Approval request for work item {item.id}",
            body_markdown="bounded",
            payload={
                "approval_request_id": approval.id,
                "approval_round": approval.approval_round,
                "dispatch_nonce": approval.dispatch_nonce,
                "plan_metadata": {},
                "request_kind": approval.request_kind,
                "summary": "bounded",
                "work_item_id": approval.work_item_id,
            },
        ),
        authenticated_sender_member_id=members[1].id,
        delivery_key=f"github-approval:{approval.id}:request",
        auto_nudge=False,
    )
    assert approval.request_message_id is None

    response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded",
        },
    )

    assert response.status_code == 200
    assert response.json()["request_message_id"] == mail.id
    assert len((await db.execute(select(MailMessage))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_generic_context_request_creates_no_approval_authority(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)

    response = await client.post(
        "/api/v1/agent-mail/messages",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "kind": "context_request",
            "sender_member_id": members[1].id,
            "recipient_member_id": members[0].id,
            "body_markdown": "Question only",
            "payload": {
                "work_item_id": item.id,
                "dispatch_nonce": item.dispatch_nonce,
            },
        },
    )

    assert response.status_code == 200
    assert (await db.execute(select(GithubApprovalRequest))).scalars().all() == []


@pytest.mark.asyncio
async def test_explicit_leader_decision_is_linked_to_current_round(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    leader, owner = members
    request = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "plan says no risky changes",
        },
    )
    assert request.status_code == 200
    assert request.json()["approval_round"] == 1
    request_message_id = request.json()["request_message_id"]
    approval_request_id = request.json()["id"]

    bypass = await client.post(
        "/api/v1/agent-mail/messages",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "kind": "answer",
            "sender_member_id": leader.id,
            "thread_root_id": request_message_id,
            "body_markdown": "approved",
            "decision": "approved",
        },
    )
    assert bypass.status_code == 409
    assert bypass.json()["detail"] == "use_decisions_route"
    assert (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all() == []

    decision = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval_request_id,
            "decision": "approved",
            "reason": "No, this does not need revision; approved.",
        },
    )

    assert decision.status_code == 200
    assert decision.json()["decision"] == "approved"
    assert decision.json()["approval_round"] == 1
    stored = (await db.execute(select(MailMessage).where(MailMessage.decision == "approved"))).scalar_one()
    assert stored.thread_root_id == request_message_id
    approval = await db.get(GithubApprovalRequest, approval_request_id)
    assert approval.status == "approved"
    assert approval.decision_message_id == stored.id
    assert stored.delivery_key == f"github-approval:{approval.id}:decision"


@pytest.mark.asyncio
async def test_identical_rejection_replay_does_not_advance_twice(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    approval_request = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )
    approval_request_id = approval_request.json()["id"]
    payload = {
        "work_item_id": item.id,
        "dispatch_nonce": item.dispatch_nonce,
        "approval_request_id": approval_request_id,
        "decision": "rejected",
        "reason": "Revise the plan",
    }

    first = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json=payload,
    )
    repeated = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json=payload,
    )
    opposite = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={**payload, "decision": "approved"},
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["id"] == first.json()["id"]
    assert opposite.status_code == 409
    assert opposite.json()["detail"] == "approval_request_already_decided"
    await db.refresh(item)
    assert item.approval_round_count == 2
    decisions = (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all()
    assert [message.id for message in decisions] == [first.json()["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("durable_mail", [False, True])
async def test_decision_route_recovers_committed_authority(
    client, db, monkeypatch, durable_mail
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    approval_response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )
    approval_id = approval_response.json()["id"]
    approval, decided = await github_approval_service.decide(
        db,
        item,
        authenticated_leader_member_id=members[0].id,
        decision="rejected",
        reason="Revise the plan",
        request_id=approval_id,
    )
    assert decided is True
    durable_message = None
    if durable_mail:
        durable_message = await agent_mail_service.send_authoritative_decision(
            db,
            MailMessageCreate(
                kind="answer",
                sender_member_id=members[0].id,
                thread_root_id=approval.request_message_id,
                body_markdown="Revise the plan",
                payload={
                    "approval_request_id": approval.id,
                    "request_kind": approval.request_kind,
                    "work_item_id": approval.work_item_id,
                },
                decision="rejected",
            ),
            authenticated_sender_member_id=members[0].id,
            approval_round=approval.approval_round,
            delivery_key=f"github-approval:{approval.id}:decision",
        )
        assert approval.decision_message_id is None

    recovered = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval.id,
            "decision": "rejected",
            "reason": "Revise the plan",
        },
    )

    assert recovered.status_code == 200
    if durable_message is not None:
        assert recovered.json()["id"] == durable_message.id
    await db.refresh(approval)
    await db.refresh(item)
    assert approval.decision_message_id == recovered.json()["id"]
    assert item.approval_round_count == 2
    decisions = (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all()
    assert len(decisions) == 1


@pytest.mark.asyncio
async def test_rejection_opens_next_round_and_clears_old_ack(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    leader, owner = members
    item.ack_received_at = datetime.utcnow()
    item.ack_approver_member_id = leader.id
    item.ack_evidence_message_id = 99
    item.ack_enforcement_epoch = 1
    item.ack_approval_round = 1
    item.last_nudge_at = datetime.utcnow()
    await db.commit()
    approval_request = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "plan",
        },
    )
    assert approval_request.status_code == 200

    decision = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval_request.json()["id"],
            "decision": "rejected",
            "reason": "Revise the plan",
        },
    )

    assert decision.status_code == 200
    await db.refresh(item)
    assert item.approval_round_count == 2
    assert item.dispatch_nonce == "0123456789abcdef"
    assert item.ack_received_at is None
    assert item.ack_approver_member_id is None
    assert item.ack_evidence_message_id is None
    assert item.ack_enforcement_epoch is None
    assert item.ack_approval_round is None
    assert item.last_nudge_at is None


@pytest.mark.asyncio
async def test_decision_route_requires_a_session_token(client, db, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, _tokens = await _dispatch_approval_fixture(db)

    response = await client.post(
        "/api/v1/agent-mail/decisions",
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "decision": "approved",
            "reason": "approved",
        },
    )

    assert response.status_code == 401
    assert (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_stale_leader_token_cannot_record_a_decision(client, db, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    leader, owner = members
    request = await client.post(
        "/api/v1/agent-mail/messages",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "kind": "context_request",
            "sender_member_id": owner.id,
            "recipient_member_id": leader.id,
            "body_markdown": "plan",
            "payload": {
                "work_item_id": item.id,
                "dispatch_nonce": item.dispatch_nonce,
            },
        },
    )
    assert request.status_code == 200
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda _pid, _start: False)

    response = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "decision": "approved",
            "reason": "stale approval",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "session_token_stale"
    assert (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_decision_route_refuses_the_owner_as_approver(client, db, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    approval_request = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "plan",
        },
    )
    assert approval_request.status_code == 200

    response = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval_request.json()["id"],
            "decision": "approved",
            "reason": "self approval",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "not_designated_leader"
    assert (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_decision_route_ignores_generic_context_roots(client, db, monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    payload = {
        "work_item_id": item.id,
        "dispatch_nonce": item.dispatch_nonce,
        "decision": "approved",
        "reason": "approved",
    }

    missing = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json=payload,
    )
    assert missing.status_code == 404

    owner = _members[1]
    leader = _members[0]
    for index in range(2):
        request = await client.post(
            "/api/v1/agent-mail/messages",
            headers={"X-Deck-Session-Token": tokens[1]},
            json={
                "kind": "context_request",
                "sender_member_id": owner.id,
                "recipient_member_id": leader.id,
                "body_markdown": f"plan {index}",
                "payload": {
                    "work_item_id": item.id,
                    "dispatch_nonce": item.dispatch_nonce,
                },
            },
        )
        assert request.status_code == 200
    still_missing = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json=payload,
    )

    assert still_missing.status_code == 404
    assert still_missing.json()["detail"] == "no_current_approval_request"
    assert (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_team_empty(client):
    resp = await client.get("/api/v1/agent-mail/team?sync=false")
    assert resp.status_code == 200
    assert resp.json() == {"members": []}


@pytest.mark.asyncio
async def test_patch_member_sets_role_and_charter(client, db):
    member = await _member(db, "ra", "alpha")
    resp = await client.patch(
        f"/api/v1/agent-mail/members/{member.id}",
        json={
            "display_name": "Backend",
            "role": "backend expert",
            "charter": "Owns API",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Backend"
    assert body["role"] == "backend expert"


@pytest.mark.asyncio
async def test_patch_unknown_member_404(client):
    resp = await client.patch("/api/v1/agent-mail/members/999", json={"role": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_send_and_thread_roundtrip(client, db):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    a_headers = await _session_headers(db, a, "a")
    b_headers = await _session_headers(db, b, "b")
    resp = await client.post(
        "/api/v1/agent-mail/messages",
        headers=a_headers,
        json={
            "kind": "context_request",
            "sender_member_id": a.id,
            "recipient_member_id": b.id,
            "subject": "q",
            "body_markdown": "?",
        },
    )
    assert resp.status_code == 200
    root_id = resp.json()["id"]

    resp = await client.post(
        "/api/v1/agent-mail/messages",
        headers=b_headers,
        json={
            "kind": "answer",
            "sender_member_id": b.id,
            "thread_root_id": root_id,
            "body_markdown": "!",
        },
    )
    assert resp.status_code == 200

    resp = await client.get(f"/api/v1/agent-mail/messages/{root_id}/thread")
    assert resp.status_code == 200
    assert resp.json()["root"]["request_status"] == "answered"
    assert len(resp.json()["replies"]) == 1


@pytest.mark.asyncio
async def test_invalid_kind_is_400(client, db):
    b = await _member(db, "rb", "beta")
    headers = await _session_headers(db, b, "invalid")
    resp = await client.post(
        "/api/v1/agent-mail/messages",
        headers=headers,
        json={"kind": "bogus", "recipient_member_id": b.id, "body_markdown": "x"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_inbox_read_ack_endpoints(client, db):
    a = await _member(db, "ra", "alpha")
    b = await _member(db, "rb", "beta")
    a_headers = await _session_headers(db, a, "inbox-a")
    b_headers = await _session_headers(db, b, "inbox-b")
    resp = await client.post(
        "/api/v1/agent-mail/messages",
        headers=a_headers,
        json={"sender_member_id": a.id, "recipient_member_id": b.id, "body_markdown": "hi"},
    )
    msg_id = resp.json()["id"]

    resp = await client.get("/api/v1/agent-mail/agent/inbox", headers=b_headers)
    assert resp.json()["unread_count"] == 1

    await client.post(
        f"/api/v1/agent-mail/messages/{msg_id}/read",
        headers=b_headers,
        json={"member_id": b.id},
    )
    resp = await client.get("/api/v1/agent-mail/agent/inbox", headers=b_headers)
    assert resp.json()["unread_count"] == 0

    resp = await client.post(
        f"/api/v1/agent-mail/messages/{msg_id}/ack",
        headers=b_headers,
        json={"member_id": b.id},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_inbox_refreshes_stale_mcp_session(client, db):
    member = await _member(db, "ra", "alpha")
    stale_seen_at = datetime.utcnow() - timedelta(hours=3)
    session = MailAgentSession(
        member_id=member.id,
        provider="codex-cli",
        source="mcp",
        session_key="mcp:abc",
        cwd=member.repo_path,
        mailbox_status="offline",
        last_seen_at=stale_seen_at,
        capability_token_hash=agent_mail_service.hash_capability_token("stale-token"),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    resp = await client.get(
        "/api/v1/agent-mail/agent/inbox",
        headers={"X-Deck-Session-Token": "stale-token"},
    )

    assert resp.status_code == 200
    await db.refresh(session)
    assert session.mailbox_status == "connected"
    assert session.last_seen_at > stale_seen_at

    resp = await client.get("/api/v1/agent-mail/team?sync=false")
    assert resp.status_code == 200
    body = resp.json()
    assert body["members"][0]["status"] == "connected"
