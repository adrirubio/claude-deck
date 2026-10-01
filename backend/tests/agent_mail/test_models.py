"""Agent Mail and normalized approval model invariants."""
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

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


async def _approval_fixture(db):
    preset = AgentTeamPreset(name="approval-models")
    db.add(preset)
    await db.flush()
    leader_slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Leader",
        provider="codex-cli",
        repo_id="repo-models",
        repo_path="/tmp/repo-models",
        repo_name="repo-models",
    )
    owner_slot = AgentTeamSlot(
        preset_id=preset.id,
        position=1,
        display_name="Owner",
        provider="codex-cli",
        repo_id="repo-models",
        repo_path="/tmp/repo-models",
        repo_name="repo-models",
    )
    db.add_all([leader_slot, owner_slot])
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo-models",
        repo_path="/tmp/repo-models",
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="Approval model",
        issue_url="https://example.test/issues/1",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=owner_slot.id,
        dispatch_nonce="nonce-models",
        approval_round_count=1,
    )
    owner = MailTeamMember(
        identity_key="slot:owner-models",
        repo_id="repo-models",
        repo_path="/tmp/repo-models",
        repo_name="repo-models",
        display_name="Owner",
        team_preset_id=preset.id,
        team_slot_id=owner_slot.id,
    )
    leader = MailTeamMember(
        identity_key="slot:leader-models",
        repo_id="repo-models",
        repo_path="/tmp/repo-models",
        repo_name="repo-models",
        display_name="Leader",
        team_preset_id=preset.id,
        team_slot_id=leader_slot.id,
    )
    db.add_all([item, owner, leader])
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/repo-models-worktree",
        leased_item_id=item.id,
        lease_token="lease-models",
    )
    db.add(workspace)
    await db.flush()
    return item, owner, leader, owner_slot, workspace


@pytest.mark.asyncio
async def test_delivery_key_is_nullable_and_unique_when_present(db):
    db.add_all(
        [
            MailMessage(kind="message", body_markdown="one", delivery_key=None),
            MailMessage(kind="message", body_markdown="two", delivery_key=None),
            MailMessage(kind="message", body_markdown="three", delivery_key="stable"),
        ]
    )
    await db.commit()

    db.add(MailMessage(kind="message", body_markdown="duplicate", delivery_key="stable"))
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_one_pending_approval_request_per_work_item(db):
    item, owner, leader, _owner_slot, _workspace = await _approval_fixture(db)
    db.add(
        GithubApprovalRequest(
            work_item_id=item.id,
            request_kind="initial_plan",
            dispatch_nonce=item.dispatch_nonce,
            approval_round=1,
            owner_member_id=owner.id,
            leader_member_id=leader.id,
            request_fingerprint="a" * 64,
        )
    )
    await db.commit()

    db.add(
        GithubApprovalRequest(
            work_item_id=item.id,
            request_kind="initial_plan",
            dispatch_nonce=item.dispatch_nonce,
            approval_round=1,
            owner_member_id=owner.id,
            leader_member_id=leader.id,
            request_fingerprint="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_terminal_approval_requests_can_repeat_for_work_item(db):
    item, owner, leader, _owner_slot, _workspace = await _approval_fixture(db)
    for status in ("approved", "rejected", "superseded", "expired"):
        db.add(
            GithubApprovalRequest(
                work_item_id=item.id,
                request_kind="initial_plan",
                dispatch_nonce=item.dispatch_nonce,
                approval_round=1,
                owner_member_id=owner.id,
                leader_member_id=leader.id,
                request_fingerprint=status * 8,
                status=status,
            )
        )
    await db.commit()


@pytest.mark.asyncio
async def test_scope_revision_schema_accepts_complete_inert_row(db):
    item, owner, _leader, owner_slot, workspace = await _approval_fixture(db)
    revision = GithubAttemptScopeRevision(
        work_item_id=item.id,
        dispatch_nonce=item.dispatch_nonce,
        revision=1,
        owner_slot_id=owner_slot.id,
        owner_member_id=owner.id,
        phase="implementation",
        execution_target="workspace",
        summary="Apply one bounded correction",
        allowed_paths=["src/example.py"],
        allowed_actions=["edit_production"],
        allowed_commands=["pytest -q"],
        prohibited_actions=["edit_ci_workflow"],
        tool_fallbacks={},
        baseline_head_sha="a" * 40,
        baseline_tree_sha="b" * 40,
        originating_escalation_reason="retry_count_exhausted",
        expected_workspace_id=workspace.id,
        expected_lease_token_hash="c" * 64,
        max_failed_heads=2,
    )
    db.add(revision)
    await db.commit()

    assert revision.id is not None
    assert revision.status == "proposed"
    assert revision.failed_head_count == 0
    assert revision.delivery_attempt_count == 0
