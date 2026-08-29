"""HTTP surface for team and messages."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import get_db
from app.main import app, spa_not_found_exception_handler
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
    MailReceipt,
    MailTeamMember,
    TeamGithubScope,
)
from app.models.schemas import MailMessageCreate
from app.services.agent_mail_service import (
    MailDeliveryIntegrityError,
    agent_mail_service,
)
from app.services.github_approval_service import (
    GithubApprovalError,
    github_approval_service,
)
from app.services.github_client import GithubCommitSnapshot, github_client
from app.services.github_dispatch_service import github_dispatch_service
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


async def _continuation_approval_fixture(db):
    item, members, tokens = await _dispatch_approval_fixture(db)
    scope = await db.get(TeamGithubScope, item.scope_id)
    scope.continuation_enabled = True
    scope.github_auth_mode = "ambient"
    item.dispatch_status = "escalated"
    item.escalation_reason = "retry_count_exhausted"
    item.pr_number = 52
    item.retry_count = 7
    item.last_verified_sha = "f" * 40
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/continuation-approval-workspace",
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="lease-secret",
    )
    db.add(workspace)
    await db.commit()
    return item, scope, members, tokens, workspace


def _stub_continuation_github(monkeypatch):
    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "head": {"sha": "a" * 40}}

    async def get_commit_snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    async def get_recursive_tree(*_args, **_kwargs):
        return []

    monkeypatch.setattr(github_client, "get_pull", get_pull)
    monkeypatch.setattr(github_client, "get_commit_snapshot", get_commit_snapshot)
    monkeypatch.setattr(github_client, "get_recursive_tree", get_recursive_tree)


def _continuation_request_body(item):
    return {
        "dispatch_nonce": item.dispatch_nonce,
        "phase": "implementation",
        "execution_target": "workspace",
        "summary": "Apply the approved bounded fix",
        "allowed_paths": ["src/example.py"],
        "allowed_actions": [
            "edit_production",
            "push_pr_head",
            "request_verification",
        ],
        "allowed_commands": ["pytest -q"],
        "prohibited_actions": ["Do not edit CI"],
        "max_failed_heads": 1,
        "tool_fallbacks": {},
        "lease_token": "lease-secret",
    }


@pytest.mark.asyncio
async def test_continuation_request_and_explicit_leader_decision_are_idempotent(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _scope, members, tokens, _workspace = await _continuation_approval_fixture(
        db
    )
    _stub_continuation_github(monkeypatch)

    proposed = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json=_continuation_request_body(item),
    )
    replay = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json=_continuation_request_body(item),
    )

    assert proposed.status_code == 200
    assert replay.status_code == 200
    approval_id = proposed.json()["approval"]["id"]
    revision_id = proposed.json()["revision"]["id"]
    assert replay.json()["approval"]["id"] == approval_id
    assert replay.json()["revision"]["id"] == revision_id
    assert "lease-secret" not in proposed.text
    assert "expected_lease_token_hash" not in proposed.text
    approval = await db.get(GithubApprovalRequest, approval_id)
    revision = await db.get(GithubAttemptScopeRevision, revision_id)
    assert approval.request_message_id is not None
    request_roots = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-approval:{approval_id}:request"
            )
        )
    ).scalars().all()
    assert len(request_roots) == 1

    decision_body = {
        "approval_request_id": approval_id,
        "work_item_id": item.id,
        "dispatch_nonce": item.dispatch_nonce,
        "decision": "approved",
        "reason": "Approved bounded continuation",
    }
    decided = await client.post(
        "/api/v1/agent-mail/continuation-decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json=decision_body,
    )
    decision_replay = await client.post(
        "/api/v1/agent-mail/continuation-decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json=decision_body,
    )

    assert decided.status_code == 200
    assert decision_replay.status_code == 200
    assert decision_replay.json()["id"] == decided.json()["id"]
    await db.refresh(approval)
    await db.refresh(revision)
    await db.refresh(item)
    assert approval.status == "approved"
    assert revision.status == "approved"
    assert revision.approved_at is not None
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert approval.decision_message_id == decided.json()["id"]
    assert revision.delivery_message_id is not None
    assert revision.delivered_at is not None
    decisions = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-approval:{approval_id}:decision"
            )
        )
    ).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].sender_member_id == members[0].id
    late_replay = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json=_continuation_request_body(item),
    )
    assert late_replay.status_code == 409
    assert late_replay.json()["detail"] == "request_not_pending"
    assert len(
        (
            await db.execute(
                select(GithubAttemptScopeRevision).where(
                    GithubAttemptScopeRevision.work_item_id == item.id
                )
            )
        ).scalars().all()
    ) == 1
    activated = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions/"
        f"{revision.revision}/ack",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "dispatch_nonce": item.dispatch_nonce,
            "lease_token": "lease-secret",
        },
    )
    activation_replay = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions/"
        f"{revision.revision}/ack",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "dispatch_nonce": item.dispatch_nonce,
            "lease_token": "lease-secret",
        },
    )
    assert activated.status_code == 200
    assert activation_replay.status_code == 200
    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "dispatched"
    assert item.active_scope_revision == revision.revision
    assert item.attempt_phase == "implementation"
    assert item.escalation_reason is None
    assert item.continuation_activated_at is not None
    assert item.pr_number == 52
    assert item.dispatch_nonce == "0123456789abcdef"
    assert item.retry_count == 7
    assert item.last_verified_sha == "f" * 40
    assert revision.status == "active"
    assert revision.acknowledged_at is not None
    receipt = (
        await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == revision.delivery_message_id,
                MailReceipt.member_id == members[1].id,
            )
        )
    ).scalar_one()
    assert receipt.acked_at is not None


@pytest.mark.asyncio
async def test_continuation_decision_refuses_initial_plan_authority(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    requested = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "initial plan",
        },
    )

    refused = await client.post(
        "/api/v1/agent-mail/continuation-decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "approval_request_id": requested.json()["id"],
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "decision": "approved",
            "reason": "wrong route",
        },
    )

    assert refused.status_code == 404
    assert refused.json()["detail"] == "approval_request_not_found"


@pytest.mark.asyncio
async def test_continuation_requester_cancels_without_operator_impersonation(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _scope, _members, tokens, _workspace = (
        await _continuation_approval_fixture(db)
    )
    _stub_continuation_github(monkeypatch)
    proposed = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json=_continuation_request_body(item),
    )
    approval_id = proposed.json()["approval"]["id"]
    revision_id = proposed.json()["revision"]["id"]

    refused = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests/"
        f"{approval_id}/cancel",
        headers={"X-Deck-Session-Token": tokens[0]},
    )
    cancelled = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests/"
        f"{approval_id}/cancel",
        headers={"X-Deck-Session-Token": tokens[1]},
    )
    repeated = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests/"
        f"{approval_id}/cancel",
        headers={"X-Deck-Session-Token": tokens[1]},
    )

    assert refused.status_code == 403
    assert refused.json()["detail"] == "not_approval_requester"
    assert cancelled.status_code == 200
    assert repeated.status_code == 200
    assert cancelled.json()["status"] == "superseded"
    revision = await db.get(GithubAttemptScopeRevision, revision_id)
    approval = await db.get(GithubApprovalRequest, approval_id)
    root = await db.get(MailMessage, approval.request_message_id)
    assert revision.status == "superseded"
    assert root.request_status == "superseded"


@pytest.mark.asyncio
async def test_continuation_decision_guard_uses_database_current_escalation(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _scope, _members, tokens, _workspace = (
        await _continuation_approval_fixture(db)
    )
    _stub_continuation_github(monkeypatch)
    proposed = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json=_continuation_request_body(item),
    )
    approval_id = proposed.json()["approval"]["id"]
    revision_id = proposed.json()["revision"]["id"]
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as concurrent_db:
        await concurrent_db.execute(
            update(GithubWorkItem)
            .where(GithubWorkItem.id == item.id)
            .values(dispatch_status="ready_for_review")
        )
        await concurrent_db.commit()

    refused = await client.post(
        "/api/v1/agent-mail/continuation-decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "approval_request_id": approval_id,
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "decision": "approved",
            "reason": "must not commit",
        },
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == "stale_continuation_context"
    approval = await db.get(GithubApprovalRequest, approval_id)
    revision = await db.get(GithubAttemptScopeRevision, revision_id)
    await db.refresh(approval)
    await db.refresh(revision)
    assert approval.status == "pending"
    assert revision.status == "proposed"


@pytest.mark.asyncio
async def test_continuation_ack_rejects_wrong_acquisition_and_changed_head(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _scope, _members, tokens, workspace = (
        await _continuation_approval_fixture(db)
    )
    _stub_continuation_github(monkeypatch)
    proposed = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/continuation-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json=_continuation_request_body(item),
    )
    approval_id = proposed.json()["approval"]["id"]
    revision_number = proposed.json()["revision"]["revision"]
    decided = await client.post(
        "/api/v1/agent-mail/continuation-decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "approval_request_id": approval_id,
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "decision": "approved",
            "reason": "approved",
        },
    )
    assert decided.status_code == 200

    wrong_token = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions/"
        f"{revision_number}/ack",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={"dispatch_nonce": item.dispatch_nonce, "lease_token": "wrong"},
    )

    async def changed_snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="d" * 40, tree_sha="e" * 40)

    monkeypatch.setattr(github_client, "get_commit_snapshot", changed_snapshot)
    changed_head = await client.post(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions/"
        f"{revision_number}/ack",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "dispatch_nonce": item.dispatch_nonce,
            "lease_token": "lease-secret",
        },
    )

    assert wrong_token.status_code == 403
    assert wrong_token.json()["detail"] == "lease_token_mismatch"
    assert changed_head.status_code == 409
    assert changed_head.json()["detail"] == "continuation_head_changed"
    await db.refresh(item)
    await db.refresh(workspace)
    revision = (
        await db.execute(
            select(GithubAttemptScopeRevision).where(
                GithubAttemptScopeRevision.work_item_id == item.id,
                GithubAttemptScopeRevision.revision == revision_number,
            )
        )
    ).scalar_one()
    assert item.dispatch_status == "escalated"
    assert revision.status == "approved"
    assert workspace.lease_token == "lease-secret"


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
async def test_initial_request_insert_refuses_database_current_escalation(db):
    item, members, _tokens = await _dispatch_approval_fixture(db)
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as other_db:
        current_item = await other_db.get(GithubWorkItem, item.id)
        current_item.dispatch_status = "escalated"
        current_item.escalation_reason = "owner_offline"
        await other_db.commit()

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.create_initial_request(
            db,
            item,
            authenticated_owner_member_id=members[1].id,
            summary="bounded plan",
        )

    assert exc_info.value.detail == "item_escalated"
    assert (await db.execute(select(GithubApprovalRequest))).scalars().all() == []


@pytest.mark.asyncio
async def test_initial_request_insert_refuses_terminal_decision_race(db, monkeypatch):
    item, members, _tokens = await _dispatch_approval_fixture(db)
    original_terminal_lookup = github_approval_service.current_terminal_for_attempt
    injected = False

    async def inject_terminal_after_lookup(*args, **kwargs):
        nonlocal injected
        terminal = await original_terminal_lookup(*args, **kwargs)
        if not injected and terminal is None:
            injected = True
            db.add(
                GithubApprovalRequest(
                    work_item_id=item.id,
                    request_kind="initial_plan",
                    dispatch_nonce=item.dispatch_nonce,
                    approval_round=item.approval_round_count,
                    owner_member_id=members[1].id,
                    leader_member_id=members[0].id,
                    request_fingerprint=(
                        github_approval_service.initial_request_fingerprint(
                            summary="approved plan",
                            plan_metadata=None,
                        )
                    ),
                    status="approved",
                    reason="Approved",
                    decided_at=datetime.utcnow(),
                )
            )
            await db.commit()
        return terminal

    monkeypatch.setattr(
        github_approval_service,
        "current_terminal_for_attempt",
        inject_terminal_after_lookup,
    )

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.create_initial_request(
            db,
            item,
            authenticated_owner_member_id=members[1].id,
            summary="different plan",
        )

    assert exc_info.value.detail == "approval_request_already_decided"
    requests = (await db.execute(select(GithubApprovalRequest))).scalars().all()
    assert len(requests) == 1
    assert requests[0].status == "approved"


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
async def test_approval_request_route_returns_stable_delivery_integrity_error(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)

    async def fail_delivery(*_args, **_kwargs):
        raise MailDeliveryIntegrityError("conflicting delivery")

    monkeypatch.setattr(agent_mail_service, "send_message", fail_delivery)
    response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "delivery_key_conflict"


@pytest.mark.asyncio
async def test_cancel_between_request_delivery_and_link_supersedes_mail(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    original_send = agent_mail_service.send_message
    nudges = []

    async def cancel_after_delivery(send_db, message, **kwargs):
        response = await original_send(send_db, message, **kwargs)
        approval = await github_approval_service.current_pending(send_db, item.id)
        await github_approval_service.cancel(
            send_db,
            approval,
            requester_member_id=members[1].id,
        )
        return response

    async def record_nudge(*_args, **_kwargs):
        nudges.append(True)

    monkeypatch.setattr(agent_mail_service, "send_message", cancel_after_delivery)
    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)
    response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "request_not_pending"
    approval = (
        await db.execute(select(GithubApprovalRequest))
    ).scalar_one()
    root = (
        await db.execute(select(MailMessage))
    ).scalar_one()
    assert approval.status == "superseded"
    assert approval.request_message_id is None
    assert root.request_status == "superseded"
    assert nudges == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["authority", "mail", "link"])
async def test_explicit_initial_approval_route_repairs_durable_boundaries(
    client, db, monkeypatch, stage
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    approval, _created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="bounded",
    )
    mail = None
    if stage in {"mail", "link"}:
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
    if stage == "link":
        approval.request_message_id = mail.id
        await db.commit()

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
    if mail is not None:
        assert response.json()["request_message_id"] == mail.id
    else:
        assert response.json()["request_message_id"] is not None
    assert len((await db.execute(select(MailMessage))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_migrated_keyless_approval_root_replays_without_redelivery(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, members, tokens = await _dispatch_approval_fixture(db)
    approval, _created = await github_approval_service.create_initial_request(
        db,
        item,
        authenticated_owner_member_id=members[1].id,
        summary="bounded plan",
    )
    legacy_root = await agent_mail_service.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=members[1].id,
            recipient_member_id=members[0].id,
            body_markdown="bounded plan",
            payload={
                "approval_round": approval.approval_round,
                "dispatch_nonce": approval.dispatch_nonce,
                "summary": "bounded plan",
                "work_item_id": approval.work_item_id,
            },
        ),
        authenticated_sender_member_id=members[1].id,
        auto_nudge=False,
    )
    approval.request_message_id = legacy_root.id
    await db.commit()

    async def unexpected_delivery(*_args, **_kwargs):
        raise AssertionError("a migrated linked root must not be redelivered")

    monkeypatch.setattr(agent_mail_service, "send_message", unexpected_delivery)
    response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )

    assert response.status_code == 200
    assert response.json()["id"] == approval.id
    assert response.json()["request_message_id"] == legacy_root.id
    assert (await db.get(MailMessage, legacy_root.id)).delivery_key is None


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
async def test_terminal_approval_request_replay_cannot_replace_approved_evidence(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    original = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )
    decision = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": original.json()["id"],
            "decision": "approved",
            "reason": "Approved",
        },
    )
    assert decision.status_code == 200

    identical = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )
    conflicting = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "different plan",
        },
    )

    assert identical.status_code == 200
    assert identical.json()["id"] == original.json()["id"]
    assert identical.json()["status"] == "approved"
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"] == "approval_request_already_decided"
    requests = (
        await db.execute(select(GithubApprovalRequest))
    ).scalars().all()
    assert [request.id for request in requests] == [original.json()["id"]]


@pytest.mark.asyncio
async def test_decision_route_returns_stable_delivery_integrity_error(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    approval = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )

    async def fail_delivery(*_args, **_kwargs):
        raise MailDeliveryIntegrityError("conflicting delivery")

    monkeypatch.setattr(
        agent_mail_service,
        "send_authoritative_decision",
        fail_delivery,
    )
    response = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval.json()["id"],
            "decision": "approved",
            "reason": "Approved",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "delivery_key_conflict"


@pytest.mark.asyncio
async def test_decision_update_refuses_database_current_escalation(
    client, db, monkeypatch
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
    approval = await db.get(
        GithubApprovalRequest, approval_response.json()["id"]
    )
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as other_db:
        current_item = await other_db.get(GithubWorkItem, item.id)
        current_item.dispatch_status = "escalated"
        current_item.escalation_reason = "owner_offline"
        await other_db.commit()

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.decide(
            db,
            item,
            authenticated_leader_member_id=members[0].id,
            decision="approved",
            reason="Approved",
            request_id=approval.id,
        )

    assert exc_info.value.detail == "item_escalated"
    await db.refresh(approval)
    assert approval.status == "pending"
    assert approval.decision_message_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("drift", "expected_detail"),
    [("nonce", "stale_nonce"), ("owner", "stale_approval_owner")],
)
async def test_decision_integration_refuses_attempt_drift_after_authority_commit(
    client, db, monkeypatch, drift, expected_detail
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)
    approval_response = await client.post(
        "/api/v1/agent-mail/approval-requests",
        headers={"X-Deck-Session-Token": tokens[1]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "summary": "bounded plan",
        },
    )
    original_send = agent_mail_service.send_authoritative_decision

    async def drift_after_delivery(send_db, message, **kwargs):
        response = await original_send(send_db, message, **kwargs)
        current_item = await send_db.get(GithubWorkItem, item.id)
        if drift == "nonce":
            current_item.dispatch_nonce = "fedcba9876543210"
        else:
            current_item.owner_slot_id = _members[0].team_slot_id
        await send_db.commit()
        return response

    monkeypatch.setattr(
        agent_mail_service,
        "send_authoritative_decision",
        drift_after_delivery,
    )
    response = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval_response.json()["id"],
            "decision": "rejected",
            "reason": "Revise the plan",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail
    await db.refresh(item)
    assert item.approval_round_count == 1
    approval = await db.get(
        GithubApprovalRequest, approval_response.json()["id"]
    )
    assert approval.status == "rejected"


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
@pytest.mark.parametrize("stage", ["authority", "mail", "link"])
async def test_decision_route_recovers_committed_authority(
    client, db, monkeypatch, stage
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
    if stage in {"mail", "link"}:
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
    if stage == "link":
        approval.decision_message_id = durable_message.id
        await db.commit()

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
async def test_approved_decision_replay_reapplies_item_integration(
    client, db, monkeypatch
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
    approval = await db.get(
        GithubApprovalRequest, approval_response.json()["id"]
    )
    approval, decided = await github_approval_service.decide(
        db,
        item,
        authenticated_leader_member_id=members[0].id,
        decision="approved",
        reason="Approved",
        request_id=approval.id,
    )
    assert decided is True
    decision_message = await agent_mail_service.send_authoritative_decision(
        db,
        MailMessageCreate(
            kind="answer",
            sender_member_id=members[0].id,
            thread_root_id=approval.request_message_id,
            body_markdown="Approved",
            payload={
                "approval_request_id": approval.id,
                "request_kind": approval.request_kind,
                "work_item_id": approval.work_item_id,
            },
            decision="approved",
        ),
        authenticated_sender_member_id=members[0].id,
        approval_round=approval.approval_round,
        delivery_key=f"github-approval:{approval.id}:decision",
    )
    approval.decision_message_id = decision_message.id
    await db.commit()
    integration_calls = []

    async def record_integration(
        integration_db,
        integration_item,
        integration_scope,
        *,
        decision,
        approval_round,
        dispatch_nonce,
        owner_member_id,
    ):
        integration_calls.append(
            (
                integration_db,
                integration_item.id,
                integration_scope.id,
                decision,
                approval_round,
                dispatch_nonce,
                owner_member_id,
            )
        )
        return True

    monkeypatch.setattr(
        github_dispatch_service,
        "apply_approval_decision",
        record_integration,
    )

    replay = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_request_id": approval.id,
            "decision": "approved",
            "reason": "Approved",
        },
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == decision_message.id
    assert integration_calls == [
        (
            db,
            item.id,
            item.scope_id,
            "approved",
            approval.approval_round,
            approval.dispatch_nonce,
            approval.owner_member_id,
        )
    ]


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
async def test_decision_route_requires_stable_approval_request_id(
    client, db, monkeypatch
):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    item, _members, tokens = await _dispatch_approval_fixture(db)

    response = await client.post(
        "/api/v1/agent-mail/decisions",
        headers={"X-Deck-Session-Token": tokens[0]},
        json={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "decision": "approved",
            "reason": "approved",
        },
    )

    assert response.status_code == 422
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
        "approval_request_id": 999,
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
    assert still_missing.json()["detail"] == "approval_request_not_found"
    assert (
        await db.execute(select(MailMessage).where(MailMessage.decision.is_not(None)))
    ).scalars().all() == []


@pytest.mark.asyncio
async def test_spa_404_handler_preserves_api_error_details():
    response = await spa_not_found_exception_handler(
        SimpleNamespace(url=SimpleNamespace(path="/api/v1/agent-mail/decisions")),
        HTTPException(status_code=404, detail="approval_request_not_found"),
    )

    assert response.status_code == 404
    assert response.body == b'{"detail":"approval_request_not_found"}'


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
