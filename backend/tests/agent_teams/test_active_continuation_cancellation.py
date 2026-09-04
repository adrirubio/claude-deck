"""Operator cancellation of an active continuation preserves the attempt."""

from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubApprovalRequest,
    GithubAttemptScopeRevision,
    GithubWorkItem,
    GithubWorkspace,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.github_approval_service import (
    GithubApprovalError,
    github_approval_service,
)
from app.services.github_client import GithubCommitSnapshot
from app.services.github_dispatch_service import github_dispatch_service


OPERATOR_TOKEN = "test-operator-token-for-active-continuation-cancel"
OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN}


@pytest.fixture(autouse=True)
def operator_token(monkeypatch):
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)


@pytest_asyncio.fixture
async def client(db):
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _active_continuation(db, tmp_path):
    preset = AgentTeamPreset(
        name=f"Cancel {tmp_path.name}",
        description="",
        created_by="test",
        autonomy_enabled=True,
    )
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name="repo",
        repo_path=str(tmp_path / "repo"),
        github_auth_mode="ambient",
        continuation_enabled=True,
    )
    db.add(scope)
    await db.flush()
    leader_slot = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Leader",
        provider="codex-cli",
        repo_id="repo",
        repo_path=scope.repo_path,
        repo_name=scope.repo_name,
        launch_mode="plain",
        launch_options={},
    )
    owner_slot = AgentTeamSlot(
        preset_id=preset.id,
        position=1,
        display_name="Specialist",
        provider="codex-cli",
        repo_id="repo",
        repo_path=scope.repo_path,
        repo_name=scope.repo_name,
        launch_mode="plain",
        launch_options={},
    )
    db.add_all([leader_slot, owner_slot])
    await db.flush()
    leader = MailTeamMember(
        identity_key=f"slot:{leader_slot.id}",
        repo_id="repo",
        repo_path=scope.repo_path,
        repo_name=scope.repo_name,
        display_name="Leader",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=leader_slot.id,
    )
    owner = MailTeamMember(
        identity_key=f"slot:{owner_slot.id}",
        repo_id="repo",
        repo_path=scope.repo_path,
        repo_name=scope.repo_name,
        display_name="Specialist",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=owner_slot.id,
    )
    db.add_all([leader, owner])
    await db.flush()
    activated_at = datetime.utcnow() - timedelta(minutes=5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=821,
        issue_title="Preserved attempt",
        issue_url="https://example.test/issues/821",
        github_updated_at=activated_at,
        dispatch_status="dispatched",
        attempt_phase="implementation",
        owner_slot_id=owner_slot.id,
        dispatch_nonce="cancel-active-nonce",
        dispatch_head_ref="deck/slot-2/issue-821-cancel-active-nonce",
        dispatch_base_ref="origin/master",
        pr_number=875,
        active_scope_revision=1,
        continuation_activated_at=activated_at,
        retry_count=3,
        diagnostic_retry_count=2,
        last_verified_sha="product-head",
        diagnostic_last_verified_sha="diagnostic-head",
        status_note="Active continuation revision 1",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "workspace"),
        kind="worktree",
        leased_item_id=item.id,
        leased_at=activated_at,
        lease_token="lease-secret",
        leased_owner_pid=1234,
        leased_owner_proc_start="5678",
        lease_last_owner_contact_at=activated_at,
    )
    db.add(workspace)
    await db.flush()
    revision = GithubAttemptScopeRevision(
        work_item_id=item.id,
        dispatch_nonce=item.dispatch_nonce,
        revision=1,
        owner_slot_id=owner_slot.id,
        owner_member_id=owner.id,
        phase="implementation",
        execution_target="hosted_ci",
        summary="Collect hosted logs",
        allowed_paths=["tests/playback_smoke.py.in"],
        allowed_actions=["collect_hosted_logs"],
        allowed_commands=[],
        prohibited_actions=["Do not push"],
        tool_fallbacks={},
        baseline_head_sha="baseline-head",
        baseline_tree_sha="baseline-tree",
        originating_escalation_reason="retry_count_exhausted",
        expected_workspace_id=workspace.id,
        expected_lease_token_hash=github_approval_service.lease_token_hash(
            workspace.lease_token
        ),
        max_failed_heads=1,
        status="active",
        approved_at=activated_at - timedelta(minutes=2),
        delivered_at=activated_at - timedelta(minutes=1),
        acknowledged_at=activated_at,
    )
    db.add(revision)
    await db.flush()
    request_root = MailMessage(
        kind="context_request",
        sender_member_id=owner.id,
        recipient_member_id=leader.id,
        body_markdown=revision.summary,
        request_status="answered",
        delivery_key="github-approval:cancel-test:request",
    )
    db.add(request_root)
    await db.flush()
    decision = MailMessage(
        kind="answer",
        thread_root_id=request_root.id,
        sender_member_id=leader.id,
        recipient_member_id=owner.id,
        body_markdown="Approved",
        request_status="answered",
        decision="approved",
        delivery_key="github-approval:cancel-test:decision",
    )
    db.add(decision)
    await db.flush()
    approval = GithubApprovalRequest(
        work_item_id=item.id,
        request_kind="continuation",
        dispatch_nonce=item.dispatch_nonce,
        approval_round=1,
        owner_member_id=owner.id,
        leader_member_id=leader.id,
        request_message_id=request_root.id,
        decision_message_id=decision.id,
        scope_revision_id=revision.id,
        request_fingerprint="f" * 64,
        status="approved",
        reason="Approved exact scope",
        decided_at=activated_at - timedelta(minutes=2),
    )
    db.add(approval)
    await db.flush()
    revision.approval_request_id = approval.id
    await db.commit()
    return preset, [leader_slot, owner_slot], scope, item, workspace, revision, approval, owner


def _cancel_url(item, revision_number=1):
    return (
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions/"
        f"{revision_number}/cancel"
    )


def _cancel_body(item, reason="The approved revision cannot complete"):
    return {
        "cancel": True,
        "dispatch_nonce": item.dispatch_nonce,
        "reason": reason,
    }


@pytest.mark.asyncio
async def test_operator_cancels_active_revision_without_destroying_attempt_state(
    client, db, tmp_path
):
    _preset, _slots, _scope, item, workspace, revision, approval, owner = (
        await _active_continuation(db, tmp_path)
    )
    preserved_item = (
        item.pr_number,
        item.owner_slot_id,
        item.dispatch_nonce,
        item.dispatch_head_ref,
        item.dispatch_base_ref,
        item.retry_count,
        item.diagnostic_retry_count,
        item.last_verified_sha,
        item.diagnostic_last_verified_sha,
    )
    preserved_workspace = (
        workspace.leased_item_id,
        workspace.lease_token,
        workspace.leased_at,
        workspace.leased_owner_pid,
        workspace.leased_owner_proc_start,
        workspace.lease_last_owner_contact_at,
    )
    preserved_approval = (
        approval.status,
        approval.reason,
        approval.decided_at,
        approval.request_message_id,
        approval.decision_message_id,
    )

    response = await client.post(
        _cancel_url(item),
        json=_cancel_body(item),
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert response.json()["dispatch_status"] == "escalated"
    assert response.json()["active_scope_revision"] == 0
    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    await db.refresh(approval)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert item.active_scope_revision == 0
    assert item.attempt_phase == "implementation"
    assert item.continuation_nudged_at is None
    assert item.continuation_activated_at is None
    assert "fresh bounded proposal" in item.status_note
    assert preserved_item == (
        item.pr_number,
        item.owner_slot_id,
        item.dispatch_nonce,
        item.dispatch_head_ref,
        item.dispatch_base_ref,
        item.retry_count,
        item.diagnostic_retry_count,
        item.last_verified_sha,
        item.diagnostic_last_verified_sha,
    )
    assert preserved_workspace == (
        workspace.leased_item_id,
        workspace.lease_token,
        workspace.leased_at,
        workspace.leased_owner_pid,
        workspace.leased_owner_proc_start,
        workspace.lease_last_owner_contact_at,
    )
    assert preserved_approval == (
        approval.status,
        approval.reason,
        approval.decided_at,
        approval.request_message_id,
        approval.decision_message_id,
    )
    assert revision.status == "superseded"
    assert revision.cancelled_at is not None
    assert revision.cancellation_reason == _cancel_body(item)["reason"]
    notices = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled"
            )
        )
    ).scalars().all()
    assert len(notices) == 1
    assert notices[0].recipient_member_id == owner.id
    assert "superseded" in notices[0].body_markdown
    assert "lease-secret" not in notices[0].body_markdown
    assert "lease-secret" not in str(notices[0].payload)
    listed = await client.get(
        f"/api/v1/agent-teams/github-work-items/{item.id}/scope-revisions",
        headers=OPERATOR_HEADERS,
    )
    assert listed.status_code == 200, listed.text
    listed_revision = next(
        entry for entry in listed.json() if entry["id"] == revision.id
    )
    assert listed_revision["cancelled_at"] is not None
    assert listed_revision["cancellation_reason"] == _cancel_body(item)["reason"]


@pytest.mark.asyncio
async def test_exact_cancel_replay_is_idempotent_but_a_changed_reason_is_not(
    client, db, tmp_path
):
    _preset, _slots, _scope, item, _workspace, revision, _approval, _owner = (
        await _active_continuation(db, tmp_path)
    )
    body = _cancel_body(item)

    first = await client.post(_cancel_url(item), json=body, headers=OPERATOR_HEADERS)
    replay = await client.post(_cancel_url(item), json=body, headers=OPERATOR_HEADERS)
    changed = await client.post(
        _cancel_url(item),
        json={**body, "reason": "A different reason"},
        headers=OPERATOR_HEADERS,
    )
    item.attempt_phase = "diagnostic"
    await db.commit()
    corrupted_replay = await client.post(
        _cancel_url(item),
        json=body,
        headers=OPERATOR_HEADERS,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert changed.status_code == 409
    assert changed.json()["detail"] == "active_continuation_cancel_conflict"
    assert corrupted_replay.status_code == 409
    assert corrupted_replay.json()["detail"] == "active_continuation_cancel_conflict"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MailMessage)
            .where(MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled")
        )
    ) == 1


@pytest.mark.asyncio
async def test_cancel_selects_the_revision_from_the_current_attempt(
    client, db, tmp_path
):
    _preset, _slots, _scope, item, _workspace, revision, _approval, _owner = (
        await _active_continuation(db, tmp_path)
    )
    db.add(
        GithubAttemptScopeRevision(
            work_item_id=item.id,
            dispatch_nonce="historical-attempt-nonce",
            revision=revision.revision,
            owner_slot_id=revision.owner_slot_id,
            owner_member_id=revision.owner_member_id,
            phase="implementation",
            execution_target="hosted_ci",
            summary="Historical completed scope",
            allowed_paths=[],
            allowed_actions=[],
            allowed_commands=[],
            prohibited_actions=[],
            tool_fallbacks={},
            baseline_head_sha="historical-head",
            baseline_tree_sha="historical-tree",
            originating_escalation_reason="retry_count_exhausted",
            expected_workspace_id=revision.expected_workspace_id,
            expected_lease_token_hash=revision.expected_lease_token_hash,
            max_failed_heads=1,
            status="completed",
            completed_at=datetime.utcnow(),
        )
    )
    await db.commit()

    response = await client.post(
        _cancel_url(item),
        json=_cancel_body(item),
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200, response.text
    await db.refresh(revision)
    assert revision.status == "superseded"


@pytest.mark.asyncio
async def test_stale_or_submitted_active_cancel_refuses_before_mutation(
    client, db, tmp_path
):
    _preset, _slots, _scope, item, workspace, revision, approval, _owner = (
        await _active_continuation(db, tmp_path)
    )
    original_item = (item.dispatch_status, item.active_scope_revision, item.status_note)
    original_revision = (revision.status, revision.cancelled_at, revision.cancellation_reason)
    original_approval = approval.status
    original_lease = (workspace.leased_item_id, workspace.lease_token)

    stale = await client.post(
        _cancel_url(item),
        json={**_cancel_body(item), "dispatch_nonce": "wrong-nonce"},
        headers=OPERATOR_HEADERS,
    )
    missing = await client.post(
        _cancel_url(item, 999),
        json=_cancel_body(item),
        headers=OPERATOR_HEADERS,
    )
    revision.status = "submitted"
    item.dispatch_status = "verifying"
    await db.commit()
    submitted = await client.post(
        _cancel_url(item),
        json=_cancel_body(item),
        headers=OPERATOR_HEADERS,
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "stale_nonce"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "scope_revision_not_found"
    assert submitted.status_code == 409
    assert submitted.json()["detail"] == "active_continuation_not_cancellable"
    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    await db.refresh(approval)
    assert (item.dispatch_status, item.active_scope_revision, item.status_note) == (
        "verifying",
        original_item[1],
        original_item[2],
    )
    assert (revision.status, revision.cancelled_at, revision.cancellation_reason) == (
        "submitted",
        original_revision[1],
        original_revision[2],
    )
    assert approval.status == original_approval
    assert (workspace.leased_item_id, workspace.lease_token) == original_lease


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "expected_detail"),
    [
        ("owner", "active_continuation_not_cancellable"),
        ("handoff", "active_continuation_not_cancellable"),
        ("workspace", "workspace_lease_changed"),
        ("lease_token", "workspace_lease_changed"),
    ],
)
async def test_owner_handoff_or_workspace_change_refuses_before_mutation(
    client, db, tmp_path, mutation, expected_detail
):
    _preset, slots, _scope, item, workspace, revision, approval, _owner = (
        await _active_continuation(db, tmp_path)
    )
    if mutation == "owner":
        item.owner_slot_id = slots[0].id
    elif mutation == "handoff":
        item.handoff_state = "pending"
        item.handoff_target_slot_id = slots[0].id
    elif mutation == "workspace":
        workspace.leased_item_id = None
    else:
        workspace.lease_token = "replacement-lease-secret"
    expected_lease_token = workspace.lease_token
    await db.commit()

    response = await client.post(
        _cancel_url(item),
        json=_cancel_body(item),
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail
    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    await db.refresh(approval)
    assert item.dispatch_status == "dispatched"
    assert item.active_scope_revision == revision.revision
    assert revision.status == "active"
    assert revision.cancelled_at is None
    assert revision.cancellation_reason is None
    assert approval.status == "approved"
    assert workspace.lease_token == expected_lease_token
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MailMessage)
            .where(MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled")
        )
    ) == 0


@pytest.mark.asyncio
async def test_cancel_cas_refuses_a_revision_submitted_after_admission(
    db, tmp_path, monkeypatch
):
    _preset, _slots, _scope, item, workspace, revision, approval, _owner = (
        await _active_continuation(db, tmp_path)
    )
    original_execute = db.execute
    raced = False

    async def execute_with_submission_race(statement, *args, **kwargs):
        nonlocal raced
        table = getattr(statement, "table", None)
        if (
            not raced
            and getattr(statement, "is_update", False)
            and getattr(table, "name", None)
            == GithubAttemptScopeRevision.__tablename__
        ):
            raced = True
            await original_execute(
                update(GithubAttemptScopeRevision)
                .where(GithubAttemptScopeRevision.id == revision.id)
                .values(status="submitted", submitted_at=datetime.utcnow())
                .execution_options(synchronize_session=False)
            )
            await original_execute(
                update(GithubWorkItem)
                .where(GithubWorkItem.id == item.id)
                .values(dispatch_status="verifying")
                .execution_options(synchronize_session=False)
            )
            await db.commit()
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute_with_submission_race)

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.cancel_active_continuation(
            db,
            item,
            revision_number=revision.revision,
            dispatch_nonce=item.dispatch_nonce,
            reason="The approved revision cannot complete",
        )

    assert exc_info.value.detail == "active_continuation_cancel_conflict"
    assert raced is True
    fresh_item = (
        await db.execute(
            select(GithubWorkItem)
            .where(GithubWorkItem.id == item.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    fresh_revision = (
        await db.execute(
            select(GithubAttemptScopeRevision)
            .where(GithubAttemptScopeRevision.id == revision.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    await db.refresh(workspace)
    await db.refresh(approval)
    assert fresh_item.dispatch_status == "verifying"
    assert fresh_item.active_scope_revision == revision.revision
    assert fresh_revision.status == "submitted"
    assert fresh_revision.cancelled_at is None
    assert fresh_revision.cancellation_reason is None
    assert approval.status == "approved"
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "lease-secret"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MailMessage)
            .where(MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled")
        )
    ) == 0


@pytest.mark.asyncio
async def test_cancel_cas_refuses_a_reacquired_lease_after_admission(
    db, tmp_path, monkeypatch
):
    _preset, _slots, _scope, item, workspace, revision, approval, _owner = (
        await _active_continuation(db, tmp_path)
    )
    original_execute = db.execute
    raced = False

    async def execute_with_lease_race(statement, *args, **kwargs):
        nonlocal raced
        table = getattr(statement, "table", None)
        if (
            not raced
            and getattr(statement, "is_update", False)
            and getattr(table, "name", None)
            == GithubAttemptScopeRevision.__tablename__
        ):
            raced = True
            await original_execute(
                update(GithubWorkspace)
                .where(GithubWorkspace.id == workspace.id)
                .values(lease_token="replacement-lease-secret")
                .execution_options(synchronize_session=False)
            )
            await db.commit()
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db, "execute", execute_with_lease_race)

    with pytest.raises(GithubApprovalError) as exc_info:
        await github_approval_service.cancel_active_continuation(
            db,
            item,
            revision_number=revision.revision,
            dispatch_nonce=item.dispatch_nonce,
            reason="The approved revision cannot complete",
        )

    assert exc_info.value.detail == "active_continuation_cancel_conflict"
    assert raced is True
    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    await db.refresh(approval)
    assert item.dispatch_status == "dispatched"
    assert item.active_scope_revision == revision.revision
    assert revision.status == "active"
    assert revision.cancelled_at is None
    assert revision.cancellation_reason is None
    assert approval.status == "approved"
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "replacement-lease-secret"
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MailMessage)
            .where(MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled")
        )
    ) == 0


@pytest.mark.asyncio
async def test_cancelled_revision_allows_the_next_monotonic_proposal(
    client, db, tmp_path, monkeypatch
):
    _preset, _slots, scope, item, _workspace, _revision, _approval, owner = (
        await _active_continuation(db, tmp_path)
    )
    owner_slot_id = item.owner_slot_id
    response = await client.post(
        _cancel_url(item),
        json=_cancel_body(item),
        headers=OPERATOR_HEADERS,
    )
    assert response.status_code == 200
    await db.refresh(item)

    async def read_token(_scope):
        return "token"

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "head": {"sha": "a" * 40}}

    async def get_commit_snapshot(*_args, **_kwargs):
        return GithubCommitSnapshot(sha="a" * 40, tree_sha="b" * 40)

    async def get_recursive_tree(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(github_approval_service, "github_read_token", read_token)
    monkeypatch.setattr(
        "app.services.github_approval_service.github_client.get_pull", get_pull
    )
    monkeypatch.setattr(
        "app.services.github_approval_service.github_client.get_commit_snapshot",
        get_commit_snapshot,
    )
    monkeypatch.setattr(
        "app.services.github_approval_service.github_client.get_recursive_tree",
        get_recursive_tree,
    )
    next_revision, _approval, created = (
        await github_approval_service.create_continuation_request(
            db,
            item,
            scope,
            authenticated_owner_member_id=owner.id,
            authenticated_owner_slot_id=owner_slot_id,
            dispatch_nonce=item.dispatch_nonce,
            phase="diagnostic",
            execution_target="hosted_ci",
            summary="Collect one bounded hosted diagnostic",
            allowed_paths=["tests/playback_smoke.py.in"],
            allowed_actions=["collect_hosted_logs", "revert_diagnostic_changes"],
            allowed_commands=[],
            prohibited_actions=["Do not build locally"],
            max_failed_heads=1,
            tool_fallbacks={},
            lease_token="lease-secret",
        )
    )

    assert created is True
    assert next_revision.revision == 2
    assert next_revision.status == "proposed"


@pytest.mark.asyncio
async def test_monitor_repairs_post_commit_cancellation_notice_before_new_proposal(
    db, tmp_path, monkeypatch
):
    preset, slots, scope, item, _workspace, revision, _approval, owner = (
        await _active_continuation(db, tmp_path)
    )
    original_send = agent_mail_service.send_direct_message

    async def fail_delivery(*_args, **_kwargs):
        raise RuntimeError("mail unavailable after authority commit")

    monkeypatch.setattr(agent_mail_service, "send_direct_message", fail_delivery)
    with pytest.raises(RuntimeError, match="mail unavailable"):
        await github_approval_service.cancel_active_continuation(
            db,
            item,
            revision_number=revision.revision,
            dispatch_nonce=item.dispatch_nonce,
            reason="The approved revision cannot complete",
        )

    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "escalated"
    assert revision.status == "superseded"
    assert revision.cancelled_at is not None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(MailMessage)
            .where(MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled")
        )
    ) == 0

    item.owner_slot_id = slots[0].id
    await db.commit()

    monkeypatch.setattr(agent_mail_service, "send_direct_message", original_send)
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    notice = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-scope:{revision.id}:cancelled"
            )
        )
    ).scalar_one()
    assert notice.recipient_member_id == owner.id
    await db.refresh(item)
    assert item.continuation_nudged_at is None
    assert preset.autonomy_enabled is True
