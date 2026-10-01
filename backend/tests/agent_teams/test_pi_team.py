from datetime import datetime
import hashlib
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.models.database import MailAgentSession, MailTeamMember
from app.models.schemas import AgentTeamPresetCreate, AgentTeamSlotCreate, AgentTeamSlotUpdate, MailAgentRegisterRequest
from app.services.agent_mail_service import agent_mail_service
from app.services.agent_team_service import agent_team_service
from app.services.providers.base import ProviderLaunchError


@pytest.mark.parametrize("platform", ["", "  ", "openrouter"])
@pytest.mark.asyncio
async def test_pi_slot_create_update_defaults(db, tmp_path, platform):
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="Pi fixture", slots=[
        AgentTeamSlotCreate(display_name="Owner", provider="pi-cli", repo_path=str(tmp_path), launch_options={"platform": platform}),
    ]))
    assert preset.slots[0].provider == "pi-cli"
    updated = await agent_team_service.update_slot(db, preset.slots[0].id, AgentTeamSlotUpdate(launch_options={"model": "moonshotai/kimi-k3"}))
    assert updated.slots[0].launch_options["model"] == "moonshotai/kimi-k3"


@pytest.mark.parametrize("options", [{"platform": "anthropic"}, {"platform": "bedrock"}, {"aws_profile": ""}, {"aws_region": "eu-west-1"}, {"bedrock_model": "model"}, {"platform": None}])
def test_pi_team_rejects_aws_invalid_platform_and_null(options):
    with pytest.raises(ValueError):
        agent_team_service._validate_slot_options("pi-cli", "plain", options)


@pytest.mark.asyncio
async def test_pi_same_repo_manual_sessions_are_not_adopted(db, tmp_path):
    from app.models.database import AgentTeamSlot

    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="Pi reuse", slots=[
        AgentTeamSlotCreate(display_name="Owner", provider="pi-cli", repo_path=str(tmp_path)),
    ]))
    slot = await db.get(AgentTeamSlot, preset.slots[0].id)
    manual = {"provider": "pi-cli", "cwd": str(tmp_path), "session_name": "Owner", "tmux_target": "manual:0.0", "pane_id": "%99", "pid": "99"}
    result = await agent_team_service._matching_session(db, slot, [manual], set(), requires_disambiguation=False, attached_sessions=[], pane_bindings=[])
    assert result is None
    assert (await db.execute(select(MailAgentSession))).scalars().all() == []


def test_pi_readiness_is_not_generic_success():
    assert agent_team_service._agent_mail_ready_reason("pi-cli", SimpleNamespace()) is not None
    assert agent_team_service._agent_mail_ready_reason("pi-cli", SimpleNamespace(pi_mail_ready=True)) is None


@pytest.mark.asyncio
async def test_provider_migration_preserves_slot_member_identity_and_retires_old_authority(db, tmp_path):
    from app.models.database import AgentTeamSlot, TeamGithubScope, GithubWorkItem, GithubWorkspace

    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="Migration", slots=[
        AgentTeamSlotCreate(display_name="Owner", provider="codex-cli", repo_path=str(tmp_path)),
    ]))
    slot = await db.get(AgentTeamSlot, preset.slots[0].id)
    original_creation = slot.created_at
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="fixture", repo_name="fixture", repo_path=str(tmp_path), continuation_enabled=True)
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="Preserved", issue_url="https://invalid/fixture/1", github_updated_at=datetime.utcnow(), owner_slot_id=slot.id, pr_number=9, dispatch_status="escalated", dispatch_nonce="fixture-nonce", dispatch_head_ref="fixture-branch", retry_count=2, diagnostic_retry_count=1)
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "leased"), leased_item_id=item.id, leased_at=datetime.utcnow(), lease_token="synthetic-private-capability")
    db.add(workspace)
    await db.commit()
    def snapshot():
        values = tuple(tuple(getattr(row, column.name) for column in row.__table__.columns) for row in (scope, item, workspace))
        return hashlib.sha256(repr(values).encode()).hexdigest()
    preserved = snapshot()
    old_member, old_session = await agent_mail_service.register_session(db, MailAgentRegisterRequest(
        source="mcp", provider="codex-cli", cwd=str(tmp_path), session_key="mcp:old",
        team_preset_id=preset.id, team_slot_id=slot.id,
    ))
    member_id = old_member.id
    old_session.closed_at = datetime.utcnow()
    old_session.mailbox_status = "offline"
    await db.commit()
    await agent_team_service.update_slot(db, slot.id, AgentTeamSlotUpdate(provider="pi-cli", launch_options={"platform": "openrouter"}))
    await db.refresh(slot)
    current_member = await agent_mail_service.get_or_create_slot_member(db, slot)
    assert current_member.id == member_id
    assert slot.created_at == original_creation and slot.preset_id == preset.id
    await db.refresh(old_session)
    assert old_session.closed_at is not None and old_session.team_slot_id is None
    await agent_team_service.update_slot(db, slot.id, AgentTeamSlotUpdate(provider="codex-cli", launch_options={}))
    await db.refresh(slot)
    rolled_back_member = await agent_mail_service.get_or_create_slot_member(db, slot)
    assert rolled_back_member.id == member_id and slot.created_at == original_creation
    for row in (scope, item, workspace):
        await db.refresh(row)
    assert snapshot() == preserved


@pytest.mark.asyncio
async def test_pi_migration_claim_and_rollback_preserve_pending_authority_and_history(db, tmp_path, monkeypatch):
    from app.config import settings
    from app.database import get_db
    from app.main import app
    from app.models.database import AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, GithubApprovalRequest, GithubAttemptScopeRevision, GithubWorkItem, GithubWorkspace, TeamGithubScope
    from app.utils import peer_process

    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr(settings, "operator_token", "migration-operator")
    monkeypatch.setattr(peer_process, "pane_is_alive_strict", lambda *_: False)
    monkeypatch.setattr(peer_process, "pane_is_alive", lambda *_: True)
    preset = await agent_team_service.create_preset(db, AgentTeamPresetCreate(name="Full migration", slots=[
        AgentTeamSlotCreate(display_name="Leader", provider="codex-cli", repo_path=str(tmp_path)),
        AgentTeamSlotCreate(display_name="Owner", provider="codex-cli", repo_path=str(tmp_path)),
    ]))
    leader = await db.get(AgentTeamSlot, preset.slots[0].id)
    slot = await db.get(AgentTeamSlot, preset.slots[1].id)
    leader_member = await agent_mail_service.get_or_create_slot_member(db, leader)
    old_request = MailAgentRegisterRequest(source="mcp", provider="codex-cli", cwd=str(tmp_path), session_key="mcp:migrate-old", team_preset_id=preset.id, team_slot_id=slot.id)
    owner, old = await agent_mail_service.register_session(db, old_request, pane=peer_process.PeerPane(10001, "111", None, 1))
    old_token = await agent_mail_service.ensure_capability_token(db, old)
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="fixture", repo_name="fixture", repo_path=str(tmp_path), continuation_enabled=True, merge_policy="human", max_continuation_revisions=11)
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="Preserved", issue_url="https://example.invalid/1", github_updated_at=datetime.utcnow(), dispatch_status="escalated", escalation_reason="continuation_revision_exhausted", owner_slot_id=slot.id, pr_number=9, dispatch_nonce="migration-nonce", dispatch_head_ref="preserved-branch", dispatch_base_ref="origin/master", retry_count=5, diagnostic_retry_count=4, last_verified_sha="a" * 40)
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "preserved-worktree"), leased_item_id=item.id, leased_at=datetime.utcnow(), lease_token="synthetic-private-lease", leased_owner_pid=10001, leased_owner_proc_start="111")
    db.add(workspace)
    await db.flush()
    revisions = []
    for number, status in [(1, "exhausted"), (2, "proposed")]:
        revision = GithubAttemptScopeRevision(work_item_id=item.id, dispatch_nonce=item.dispatch_nonce, revision=number, owner_slot_id=slot.id, owner_member_id=owner.id, phase="implementation", execution_target="workspace", summary="Preserved authority", allowed_paths=["src/fix.c"], allowed_actions=["edit_production"], allowed_commands=["git diff --check"], prohibited_actions=["Do not change CI"], tool_fallbacks={}, baseline_head_sha="a" * 40, baseline_tree_sha="b" * 40, originating_escalation_reason=item.escalation_reason, expected_workspace_id=workspace.id, expected_lease_token_hash="synthetic-private-hash", max_failed_heads=2, failed_head_count=2 if number == 1 else 0, last_failed_head_sha="c" * 40 if number == 1 else None, status=status, recovery_checkpoint_stage="decision_hold" if number == 2 else None)
        db.add(revision)
        revisions.append(revision)
    await db.flush()
    approval = GithubApprovalRequest(work_item_id=item.id, request_kind="continuation", dispatch_nonce=item.dispatch_nonce, approval_round=1, owner_member_id=owner.id, leader_member_id=leader_member.id, scope_revision_id=revisions[1].id, request_fingerprint="preserved-fingerprint", status="pending")
    db.add(approval)
    await db.flush()
    revisions[1].approval_request_id = approval.id
    await db.commit()
    rows = [await db.get(AgentTeamPreset, preset.id), scope, item, workspace, *revisions, approval]
    def snapshot():
        values = [[getattr(row, column.name) for column in row.__table__.columns if not (
            row is workspace and column.name in {"leased_owner_pid", "leased_owner_proc_start", "lease_last_owner_contact_at", "updated_at"}
        ) and not (isinstance(row, AgentTeamPreset) and column.name == "updated_at")] for row in rows]
        return hashlib.sha256(repr(values).encode()).hexdigest()
    before = snapshot()
    slot_identity = (slot.id, slot.preset_id, slot.created_at)
    async def override():
        yield db
    app.dependency_overrides[get_db] = override
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            retired = await client.post("/api/v1/agent-mail/sessions/retire-dead-pane", headers={"X-Deck-Operator-Token": "migration-operator"}, json={"pane_pid": 10001, "pane_proc_start": "111"})
            assert retired.status_code == 200 and retired.json()["retired_count"] == 1
            assert (await client.post(f"/api/v1/agent-teams/github-work-items/{item.id}/claim-continuation", headers={"X-Deck-Session-Token": old_token})).status_code == 401
            await agent_team_service.update_slot(db, slot.id, AgentTeamSlotUpdate(provider="pi-cli", launch_options={"platform": "openrouter"}))
            db.add(AgentPaneBinding(pane_pid=10002, pane_proc_start="112", slot_id=slot.id, preset_id=preset.id))
            await db.commit()
            replacement_owner, replacement = await agent_mail_service.register_session(db, old_request.model_copy(update={"provider": "pi-cli", "session_key": "mcp:migrate-pi"}), pane=peer_process.PeerPane(10002, "112", None, 1))
            new_token = await agent_mail_service.ensure_capability_token(db, replacement)
            assert replacement_owner.id == owner.id and new_token != old_token
            claimed = await client.post(f"/api/v1/agent-teams/github-work-items/{item.id}/claim-continuation", headers={"X-Deck-Session-Token": new_token})
            assert claimed.status_code == 200 and claimed.headers["Cache-Control"] == "no-store"
            assert claimed.json()["pending_revision"]["recovery_checkpoint_stage"] == "decision_hold"
            await db.refresh(workspace)
            assert workspace.leased_owner_pid == 10002 and workspace.leased_owner_proc_start == "112"
            assert workspace.lease_last_owner_contact_at is not None
            assert (await client.post("/api/v1/agent-mail/agent/close", headers={"X-Deck-Session-Token": new_token})).status_code == 200
            await agent_team_service.update_slot(db, slot.id, AgentTeamSlotUpdate(provider="codex-cli", launch_options={}))
            assert (await client.post(f"/api/v1/agent-teams/github-work-items/{item.id}/claim-continuation", headers={"X-Deck-Session-Token": new_token})).status_code == 401
    finally:
        app.dependency_overrides.clear()
    for row in rows:
        await db.refresh(row)
    await db.refresh(slot)
    assert snapshot() == before
    assert (slot.id, slot.preset_id, slot.created_at) == slot_identity
    assert (await agent_mail_service.get_or_create_slot_member(db, slot)).id == owner.id
