import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text, update

from app.models.database import (
    AgentPaneBinding, AgentTeamPreset, AgentTeamSlot, GithubAttemptScopeRevision,
    GithubDeliveryPolicyEvent, GithubWorkItem, GithubWorkspace, MailAgentSession,
    MailPaneLifecycle, MailTeamMember, TeamGithubScope,
)
from app.models.schemas import FactoryDeliveryPolicy
from app.services.factory_delivery_policy import (
    adopt_attempt_policy, effective_policy, required_check_blockers, update_scope_policy,
)
from app.services.github_approval_service import github_approval_service
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_verification_service import github_verification_service
from app.services import native_owner_contact as native


def observed_work(state, reason, observed_at, identity, settlement_id, *, binding_identity=None):
    return SimpleNamespace(state=state, reason=reason, observed_at=observed_at,
                           identity=identity, settlement_id=settlement_id, binding_identity=binding_identity)


async def scope_and_item(db, name="one", **kwargs):
    preset = AgentTeamPreset(name=name, description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="fixture", repo_name=name,
                            repo_path="/tmp/repo")
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="Fixture",
                          issue_url="https://example.test/1", github_updated_at=datetime.utcnow(),
                          **kwargs)
    db.add(item)
    await db.commit()
    return scope, item


@pytest.mark.asyncio
async def test_direct_scope_insert_uses_database_policy_defaults(db):
    scope, _ = await scope_and_item(db)
    await db.execute(text(
        "INSERT INTO team_github_scopes (preset_id, repo_owner, repo_name, repo_path, "
        "dispatch_label, design_label, merge_policy, github_auth_mode, base_ref, "
        "max_approval_rounds, max_concurrent_dispatched, max_verification_retries, "
        "max_auto_merges_per_day, max_build_parallelism, builds_out_of_tree, "
        "continuation_enabled, max_continuation_revisions, max_continuation_failed_heads, "
        "max_failed_heads_per_revision, max_scope_paths, max_scope_commands, enabled, "
        "created_at, updated_at) VALUES (:preset, 'fixture', 'direct', '/tmp/direct', "
        "'ready', 'design', 'human', 'ambient', 'origin/main', 3, 1, 1, 0, 1, 0, "
        "0, 6, 8, 2, 32, 16, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ), {"preset": scope.preset_id})
    row = (await db.execute(select(TeamGithubScope).where(
        TeamGithubScope.repo_name == "direct"))).scalar_one()
    assert row.delivery_policy == {} and row.delivery_policy_revision == 1


@pytest.mark.asyncio
async def test_scope_defaults_do_not_change_other_teams_or_active_attempts(db):
    first, item = await scope_and_item(db, dispatch_nonce="active")
    second, other = await scope_and_item(db, name="two", dispatch_nonce="other")
    policy = FactoryDeliveryPolicy(required_checks=[{"name": "Project tests"}])
    assert await update_scope_policy(db, first, expected_revision=1, policy=policy, reason="Fixture")
    assert first.delivery_policy_revision == 2
    assert second.delivery_policy_revision == 1
    assert not effective_policy(item, first).required_checks
    assert not effective_policy(other, second).required_checks
    events = (await db.execute(select(GithubDeliveryPolicyEvent))).scalars().all()
    assert len(events) == 1 and events[0].scope_id == first.id and events[0].work_item_id is None
    assert not await update_scope_policy(db, first, expected_revision=1, policy=policy, reason="Stale")


@pytest.mark.asyncio
async def test_dispatch_records_policy_and_later_defaults_do_not_change_it(db):
    scope, item = await scope_and_item(db)
    policy = FactoryDeliveryPolicy(required_checks=[{"name": "First project tests"}])
    await update_scope_policy(db, scope, expected_revision=1, policy=policy, reason="Initial")
    await github_dispatch_service.prepare_attempt(db, item, owner_slot_id=10,
                                                   routing_method="fixture", base_ref="origin/master")
    assert item.delivery_policy_revision == 2
    await update_scope_policy(db, scope, expected_revision=2,
                               policy=FactoryDeliveryPolicy(), reason="New defaults")
    assert effective_policy(item, scope).required_checks[0].name == "First project tests"


@pytest.mark.asyncio
async def test_attempt_adoption_is_explicit_and_preserves_authority(db):
    scope, item = await scope_and_item(db, dispatch_nonce="active", active_scope_revision=2,
                                       dispatch_status="dispatched", retry_count=3)
    policy = FactoryDeliveryPolicy(required_checks=[{"name": "Project tests"}])
    await update_scope_policy(db, scope, expected_revision=1, policy=policy, reason="New default")
    fields = dict(expected_dispatch_nonce="active", expected_scope_revision=2,
                  expected_policy_revision=None, target_policy_revision=2, reason="Adopt")
    assert not await adopt_attempt_policy(db, item, scope, **(fields | {"expected_dispatch_nonce": "stale"}))
    assert await adopt_attempt_policy(db, item, scope, **fields)
    assert (item.dispatch_nonce, item.active_scope_revision, item.retry_count, item.dispatch_status) == (
        "active", 2, 3, "dispatched")
    assert item.delivery_policy_revision == 2
    assert effective_policy(item, scope).required_checks[0].name == "Project tests"
    events = (await db.execute(select(GithubDeliveryPolicyEvent).where(
        GithubDeliveryPolicyEvent.work_item_id == item.id))).scalars().all()
    assert len(events) == 1
    item.dispatch_status = "verifying"
    await db.commit()
    assert not await adopt_attempt_policy(db, item, scope, **(fields | {"expected_policy_revision": 2}))


@pytest.mark.parametrize("policy", [
    {"required_checks": [{"name": " "}]},
    {"required_checks": [{"name": "Tests"}, {"name": "Tests"}]},
    {"owner_idle_seconds": 1}, {"owner_contact": "always"}, {"broad_checks": "hosted"},
    {"unknown_option": True},
])
def test_policy_rejects_invalid_or_ambiguous_choices(policy):
    with pytest.raises(ValidationError):
        FactoryDeliveryPolicy.model_validate(policy)


@pytest.mark.parametrize("state", ["missing", "pending", "cancelled", "failure", "skipped", "neutral", "wrong_head", "wrong_app"])
@pytest.mark.asyncio
async def test_required_job_blocks_exact_head_merge(state):
    policy = FactoryDeliveryPolicy(required_checks=[{"name": "Full project tests"}, {"name": "Static checks"}])
    row = {"name": "Full project tests", "head_sha": "candidate", "app": {"slug": "github-actions"},
           "status": "completed", "conclusion": "success"}
    checks = [dict(row, name="Static checks")]
    if state != "missing":
        if state == "pending":
            row.update(status="in_progress", conclusion=None)
        elif state == "wrong_head":
            row["head_sha"] = "old"
        elif state == "wrong_app":
            row["app"] = {"slug": "other-app"}
        else:
            row["conclusion"] = state
        checks.append(row)
    assert required_check_blockers(policy, checks, "candidate")

    async def observed(*_args):
        return checks
    scope = SimpleNamespace(repo_owner="fixture", repo_name="repo", delivery_policy=policy.model_dump())
    client = SimpleNamespace(list_check_runs_for_ref=observed)
    assert not await github_verification_service._head_is_green(scope, client, "candidate")


@pytest.mark.asyncio
async def test_required_jobs_accept_success_on_the_candidate_only():
    policy = FactoryDeliveryPolicy(required_checks=[{"name": "Full project tests"}])
    checks = [{"name": "Full project tests", "head_sha": "candidate", "app": {"slug": "github-actions"},
               "status": "completed", "conclusion": "success"}]
    assert required_check_blockers(policy, checks, "candidate") == []
    assert required_check_blockers(policy, checks, "other")


async def native_fixture(db, monkeypatch, tmp_path):
    now = datetime.utcnow()
    scope, item = await scope_and_item(db, dispatch_nonce="active", active_scope_revision=2,
                                       dispatch_status="dispatched", retry_count=3,
                                       pr_number=5,
                                       continuation_activated_at=now - timedelta(minutes=2))
    slot = AgentTeamSlot(preset_id=scope.preset_id, position=0, display_name="Owner",
                         provider="claude-code", repo_id="fixture", repo_path=str(tmp_path),
                         repo_name="fixture", launch_options={"session_id": "fixture-native"})
    db.add(slot)
    await db.flush()
    member = MailTeamMember(identity_key="fixture-owner", repo_id="fixture", repo_path=str(tmp_path),
                            repo_name="fixture", display_name="Owner", participant_kind="team_slot",
                            team_slot_id=slot.id, team_preset_id=scope.preset_id)
    db.add(member)
    await db.flush()
    session = MailAgentSession(member_id=member.id, provider=slot.provider, source="mcp", session_key="fixture-session",
                               pid=10010,
                               cwd=str(tmp_path), team_slot_id=slot.id, team_preset_id=scope.preset_id,
                               bound_pane_pid=10000, bound_pane_proc_start="1000", capability_token_hash="fixture-hash")
    binding = AgentPaneBinding(preset_id=scope.preset_id, slot_id=slot.id, pane_pid=10000, pane_proc_start="1000")
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path), leased_item_id=item.id,
                                lease_token="fixture-lease", leased_at=now - timedelta(minutes=2),
                                leased_owner_pid=10000, leased_owner_proc_start="1000",
                                lease_last_owner_contact_at=now - timedelta(minutes=2))
    db.add_all([session, binding, workspace])
    await db.flush()
    revision = GithubAttemptScopeRevision(work_item_id=item.id, dispatch_nonce="active", revision=2,
        owner_slot_id=slot.id, owner_member_id=member.id, phase="implementation", execution_target="workspace",
        summary="Fixture", allowed_paths=["source.py"], allowed_actions=[], allowed_commands=[],
        prohibited_actions=[], tool_fallbacks={}, baseline_head_sha="old", baseline_tree_sha="tree",
        originating_escalation_reason="retry_count_exhausted", expected_workspace_id=workspace.id,
        expected_lease_token_hash=github_approval_service.lease_token_hash("fixture-lease"),
        max_failed_heads=2, status="active", acknowledged_at=now - timedelta(minutes=2),
        expires_at=now - timedelta(days=1))
    db.add(revision)
    item.owner_slot_id = slot.id
    item.delivery_policy = FactoryDeliveryPolicy(owner_contact="native").model_dump()
    item.delivery_policy_revision = 2
    await db.commit()
    expected_binding = hashlib.sha256(json.dumps(
        [slot.provider, 10000, "1000", str(tmp_path.resolve()), None, None], separators=(",", ":")
    ).encode()).hexdigest()
    observed = observed_work("working", "native_progress", datetime.now(timezone.utc) - timedelta(seconds=1),
                               "fixture-private-identity", None,
                               binding_identity=expected_binding)
    async def observe(*_args, **_kwargs):
        return {slot.id: observed}
    monkeypatch.setattr(native.activity, "observe_private_team", observe)
    monkeypatch.setattr(native.activity, "_process", lambda _pid: ("S", "1000"))
    monkeypatch.setattr(native.activity, "_process_started_at", lambda _start: datetime.now(timezone.utc) - timedelta(minutes=2))
    return scope, item, workspace, revision, slot, member, session, observed


@pytest.mark.asyncio
async def test_fresh_work_updates_contact_only_and_does_not_expire_acked_revision(db, monkeypatch, tmp_path):
    scope, item, workspace, revision, *_rest = await native_fixture(db, monkeypatch, tmp_path)
    def authority():
        return {row.__tablename__: {column.name: getattr(row, column.name) for column in row.__table__.columns
                                   if column.name != "lease_last_owner_contact_at"}
                for row in (item, workspace, revision)}
    before = authority()
    assert await native.renew_native_owner_contact(db, scope, item, workspace, revision)
    assert authority() == before
    contact = workspace.lease_last_owner_contact_at
    await native.renew_native_owner_contact(db, scope, item, workspace, revision)
    assert workspace.lease_last_owner_contact_at == contact


@pytest.mark.parametrize("state", ["unknown", "idle", "stopped", "stale", "future", "missing_identity"])
@pytest.mark.asyncio
async def test_unproven_native_work_does_not_renew(db, monkeypatch, tmp_path, state):
    scope, item, workspace, revision, slot, _member, _session, observed = await native_fixture(db, monkeypatch, tmp_path)
    when = observed.observed_at
    if state == "stale":
        when = datetime.now(timezone.utc) - timedelta(minutes=4)
    elif state == "future":
        when = datetime.now(timezone.utc) + timedelta(minutes=1)
    value = observed_work(state if state in {"unknown", "idle", "stopped"} else "working", "fixture", when,
                            None if state == "missing_identity" else observed.identity, None,
                            binding_identity=observed.binding_identity)
    async def observe(*_args, **_kwargs):
        return {slot.id: value}
    monkeypatch.setattr(native.activity, "observe_private_team", observe)
    before = workspace.lease_last_owner_contact_at
    assert not await native.renew_native_owner_contact(db, scope, item, workspace, revision)
    assert workspace.lease_last_owner_contact_at == before


@pytest.mark.parametrize("mismatch", ["workspace", "process", "session", "owner", "revision", "phase", "expired", "retired", "policy"])
@pytest.mark.asyncio
async def test_wrong_or_expired_owner_context_does_not_renew(db, monkeypatch, tmp_path, mismatch):
    scope, item, workspace, revision, slot, member, session, _observed = await native_fixture(db, monkeypatch, tmp_path)
    if mismatch == "workspace":
        workspace.lease_token = "another-lease"
    elif mismatch == "process":
        monkeypatch.setattr(native.activity, "_process", lambda _pid: ("S", "reused"))
    elif mismatch == "session":
        session.cwd = str(tmp_path / "other")
    elif mismatch == "owner":
        revision.owner_member_id = member.id + 1
    elif mismatch == "revision":
        revision.status = "expired"
    elif mismatch == "phase":
        revision.phase = "diagnostic"
    elif mismatch == "expired":
        workspace.lease_last_owner_contact_at = datetime.utcnow() - timedelta(hours=1)
        item.continuation_activated_at = workspace.lease_last_owner_contact_at
    elif mismatch == "retired":
        db.add(MailPaneLifecycle(pane_pid=10000, pane_proc_start="1000", retired_at=datetime.utcnow()))
    elif mismatch == "policy":
        item.delivery_policy = FactoryDeliveryPolicy().model_dump()
    await db.commit()
    before = workspace.lease_last_owner_contact_at
    assert not await native.renew_native_owner_contact(db, scope, item, workspace, revision)
    assert workspace.lease_last_owner_contact_at == before


@pytest.mark.parametrize("race", ["release", "generation", "owner", "revision", "conversation", "auxiliary_rebind", "registered_at"])
@pytest.mark.asyncio
async def test_contact_update_rechecks_identity_after_native_observation(db, monkeypatch, tmp_path, race):
    scope, item, workspace, revision, slot, _member, session, observed = await native_fixture(db, monkeypatch, tmp_path)
    async def observe(*_args, **_kwargs):
        if race == "release":
            await db.execute(update(GithubWorkspace).where(GithubWorkspace.id == workspace.id).values(
                leased_item_id=None).execution_options(synchronize_session=False))
        elif race == "generation":
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == session.id).values(
                closed_at=datetime.utcnow()).execution_options(synchronize_session=False))
        elif race == "owner":
            await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(
                owner_slot_id=None).execution_options(synchronize_session=False))
        elif race == "revision":
            await db.execute(update(GithubAttemptScopeRevision).where(GithubAttemptScopeRevision.id == revision.id).values(
                status="superseded").execution_options(synchronize_session=False))
        elif race == "conversation":
            await db.execute(update(AgentTeamSlot).where(AgentTeamSlot.id == slot.id).values(
                launch_options={"session_id": "different-native"}).execution_options(synchronize_session=False))
        elif race == "auxiliary_rebind":
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == session.id).values(
                pid=10020).execution_options(synchronize_session=False))
        else:
            await db.execute(update(MailAgentSession).where(MailAgentSession.id == session.id).values(
                created_at=datetime.utcnow()).execution_options(synchronize_session=False))
        await db.commit()
        return {slot.id: observed}
    monkeypatch.setattr(native.activity, "observe_private_team", observe)
    before = workspace.lease_last_owner_contact_at
    assert not await native.renew_native_owner_contact(db, scope, item, workspace, revision)
    await db.refresh(workspace)
    assert workspace.lease_last_owner_contact_at == before


@pytest.mark.asyncio
async def test_dead_newest_auxiliary_cannot_use_older_live_work(db, monkeypatch, tmp_path):
    scope, item, workspace, revision, slot, member, session, observed = await native_fixture(db, monkeypatch, tmp_path)
    dead = MailAgentSession(member_id=member.id, provider=slot.provider, source="mcp", session_key="new-dead-session",
        pid=10020, cwd=session.cwd, team_slot_id=slot.id, team_preset_id=scope.preset_id,
        bound_pane_pid=10000, bound_pane_proc_start="1000", capability_token_hash="fixture-new-hash")
    db.add(dead)
    await db.commit()
    def process(pid):
        if pid == 10020:
            raise FileNotFoundError("Fixture dead auxiliary")
        return "S", "1000"
    monkeypatch.setattr(native.activity, "_process", process)
    assert not await native.renew_native_owner_contact(db, scope, item, workspace, revision)


@pytest.mark.asyncio
async def test_private_evidence_must_match_selected_native_lifetime(db, monkeypatch, tmp_path):
    scope, item, workspace, revision, slot, _member, _session, observed = await native_fixture(db, monkeypatch, tmp_path)
    wrong = observed_work("working", "native_progress", observed.observed_at, observed.identity, None,
                             binding_identity="different-native-lifetime")
    async def observe(*_args, **_kwargs):
        return {slot.id: wrong}
    monkeypatch.setattr(native.activity, "observe_private_team", observe)
    assert not await native.renew_native_owner_contact(db, scope, item, workspace, revision)


@pytest.mark.asyncio
async def test_native_read_has_a_response_deadline(db, monkeypatch, tmp_path):
    scope, item, workspace, revision, *_rest = await native_fixture(db, monkeypatch, tmp_path)
    async def observe(*_args, **_kwargs):
        await asyncio.sleep(5)
    monkeypatch.setattr(native, "_NATIVE_RESPONSE_SECONDS", .02, raising=False)
    monkeypatch.setattr(native.activity, "observe_private_team", observe)
    before = workspace.lease_last_owner_contact_at
    try:
        result = await asyncio.wait_for(native.renew_native_owner_contact(db, scope, item, workspace, revision), .3)
    except TimeoutError:
        result = "native_read_has_no_response_deadline"
    assert result is False
    assert workspace.lease_last_owner_contact_at == before


@pytest.mark.parametrize("race", ["policy", "terminal", "revision"])
@pytest.mark.asyncio
async def test_continuation_monitor_discards_changed_context_after_native_await(db, monkeypatch, tmp_path, race):
    scope, item, workspace, revision, slot, _member, _session, _observed = await native_fixture(db, monkeypatch, tmp_path)
    old = datetime.utcnow() - timedelta(minutes=16)
    item.continuation_activated_at = old
    workspace.lease_last_owner_contact_at = old
    await db.commit()
    async def renew(*_args, **_kwargs):
        if race == "policy":
            value = FactoryDeliveryPolicy(owner_contact="native", owner_idle_seconds=3600).model_dump()
            await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(
                delivery_policy=value, delivery_policy_revision=3).execution_options(synchronize_session=False))
        elif race == "terminal":
            await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(
                dispatch_status="completed").execution_options(synchronize_session=False))
        else:
            await db.execute(update(GithubAttemptScopeRevision).where(GithubAttemptScopeRevision.id == revision.id).values(
                status="superseded").execution_options(synchronize_session=False))
        await db.commit()
        return False
    notices = []
    async def notice(*_args, **_kwargs):
        notices.append(True)
    monkeypatch.setattr(native, "renew_native_owner_contact", renew)
    monkeypatch.setattr(github_dispatch_service, "notify_owner", notice)
    await github_dispatch_service.monitor_continuation(db, scope, [slot])
    await db.refresh(item)
    assert notices == [] and item.continuation_nudged_at is None
    assert item.dispatch_status != "escalated" and item.retry_count == 3


@pytest.mark.parametrize("race", ["policy", "terminal"])
@pytest.mark.asyncio
async def test_initial_monitor_discards_changed_context_after_native_await(db, monkeypatch, tmp_path, race):
    scope, item, workspace, _revision, slot, *_rest = await native_fixture(db, monkeypatch, tmp_path)
    item.active_scope_revision = 0
    item.pr_number = None
    item.dispatched_at = datetime.utcnow() - timedelta(minutes=16)
    item.updated_at = item.dispatched_at
    item.ack_received_at = item.dispatched_at
    workspace.lease_last_owner_contact_at = item.dispatched_at
    await db.commit()
    async def brief(*_args):
        return True
    async def renew(*_args, **_kwargs):
        values = ({"delivery_policy": FactoryDeliveryPolicy(owner_contact="native", owner_idle_seconds=3600).model_dump(),
                   "delivery_policy_revision": 3} if race == "policy" else {"dispatch_status": "completed"})
        await db.execute(update(GithubWorkItem).where(GithubWorkItem.id == item.id).values(**values)
                         .execution_options(synchronize_session=False))
        await db.commit()
        return False
    notices = []
    async def notice(*_args, **_kwargs):
        notices.append(True)
    monkeypatch.setattr(native, "renew_native_owner_contact", renew)
    monkeypatch.setattr(github_dispatch_service, "_brief_delivered", brief)
    monkeypatch.setattr(github_dispatch_service, "_nudge_owner_for_progress", notice)
    await github_dispatch_service.monitor_dispatched(db, scope, [slot], wake_state_by_slot={slot.id: "ready"})
    await db.refresh(item)
    assert notices == [] and item.last_nudge_at is None and item.dispatch_status != "escalated"
