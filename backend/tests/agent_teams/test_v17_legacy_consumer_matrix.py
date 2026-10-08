"""V17: real consumer behavior over migrated legacy authority scenarios."""
import pytest
from datetime import datetime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, _run_sqlite_compat_migrations
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubBacklogCoordination,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.agent_mail_service import agent_mail_service
from app.services.agent_team_service import agent_team_service
from app.services.github_approval_service import GithubApprovalError, github_approval_service
from app.services.github_coordination_service import CoordinationError, github_coordination_service
from app.services.github_dispatch_service import github_dispatch_service
from app.services.github_verification_service import github_verification_service

pytestmark = pytest.mark.asyncio


async def _migrated_store():
    """Build a legacy store, run the real migration, and record explicit changes.

    Scenarios: tied positions, a disabled first slot with an enabled successor,
    an all-disabled roster, an invalid preserved assignment, and reordered
    explicit authority away from first position.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    conn = await engine.connect()
    await conn.run_sync(Base.metadata.create_all)
    await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
    await conn.execute(text(
        "INSERT INTO agent_team_presets (id, name, created_at, updated_at, autonomy_enabled) VALUES "
        "(1, 'tied', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
        "(2, 'disabled-first', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
        "(3, 'invalid', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0), "
        "(4, 'all-disabled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
    ))
    await conn.execute(text(
        "INSERT INTO agent_team_slots (id, preset_id, position, display_name, provider, repo_id, "
        "repo_path, repo_name, launch_mode, enabled, created_at, updated_at) VALUES "
        "(10, 1, 0, 'tied-a', 'codex-cli', 'a', '/a', 'a', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(11, 1, 0, 'tied-b', 'codex-cli', 'b', '/b', 'b', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(20, 2, 0, 'disabled-first', 'codex-cli', 'c', '/c', 'c', 'plain', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(21, 2, 1, 'enabled-successor', 'codex-cli', 'd', '/d', 'd', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(30, 3, 0, 'invalid-owner', 'codex-cli', 'e', '/e', 'e', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(40, 4, 0, 'off', 'codex-cli', 'f', '/f', 'f', 'plain', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ))
    for scope_id, preset_id, repo in ((1, 1, "a"), (3, 3, "e")):
        await conn.execute(text(
            "INSERT INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path, dispatch_label, "
            "design_label, merge_policy, github_auth_mode, base_ref, max_approval_rounds, "
            "max_concurrent_dispatched, max_verification_retries, max_auto_merges_per_day, "
            "max_build_parallelism, builds_out_of_tree, continuation_enabled, max_continuation_revisions, "
            "max_continuation_failed_heads, max_failed_heads_per_revision, max_scope_paths, "
            "max_scope_commands, enabled, created_at, updated_at) "
            "VALUES (:scope, :preset, 'example', :repo, :path, 'ready', 'design', 'human', 'ambient', "
            "'origin/main', 3, 1, 1, 0, 1, 0, 0, 6, 8, 2, 32, 16, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"scope": scope_id, "preset": preset_id, "repo": repo, "path": f"/{repo}"})
    await conn.execute(text(
        "INSERT INTO mail_team_members (id, identity_key, repo_id, repo_path, repo_name, display_name, "
        "participant_kind, team_preset_id, team_slot_id, created_at, updated_at) VALUES "
        "(7, 'slot:7', 'a', '/a', 'a', 'owner-member', 'team_slot', 1, 10, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(8, 'slot:8', 'b', '/b', 'b', 'leader-member', 'team_slot', 1, 11, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
        "(9, 'slot:9', 'e', '/e', 'e', 'invalid-member', 'team_slot', 3, 30, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    ))
    for item_id, scope_id, owner_slot in ((1, 1, 10), (2, 1, 11), (3, 3, 30)):
        await conn.execute(text(
            "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url, "
            "github_updated_at, issue_type, dispatch_status, attempt_phase, owner_slot_id, "
            "active_scope_revision, approval_round_count, retry_count, diagnostic_retry_count, "
            "created_at, updated_at) VALUES (:id, :scope, :id, 'title', :url, "
            "CURRENT_TIMESTAMP, 'code', 'pending', 'implementation', :owner, 0, 0, 0, 0, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"id": item_id, "scope": scope_id, "owner": owner_slot, "url": f"https://example.invalid/{item_id}"})
    await conn.commit()
    await _run_sqlite_compat_migrations(conn)
    # Tied positions resolve to the lower id in the one-time backfill.
    migrated = {row[0]: row[1] for row in (await conn.execute(text(
        "SELECT id, leader_slot_id FROM agent_team_presets ORDER BY id"
    ))).all()}
    assert migrated == {1: 10, 2: 21, 3: 30, 4: None}
    # Reordered explicit authority and an invalid preserved assignment.
    await conn.execute(text("UPDATE agent_team_presets SET leader_slot_id = 11 WHERE id = 1"))
    await conn.execute(text("UPDATE agent_team_presets SET leader_slot_id = 999999 WHERE id = 3"))
    await conn.commit()
    await conn.close()
    return engine


async def _slots(session, preset_id):
    return list((await session.scalars(
        select(AgentTeamSlot).where(AgentTeamSlot.preset_id == preset_id)
        .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
    )).all())


async def test_v17_resolver_selects_explicit_enabled_id_across_migrated_scenarios():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            tied = await _slots(session, 1)
            successor = await _slots(session, 2)
            invalid = await _slots(session, 3)
            disabled_only = await _slots(session, 4)
            # Reordered explicit authority wins over first position.
            assert github_dispatch_service._leader_slot(tied, 11).id == 11
            # Tied-position assignment resolves by explicit id.
            assert github_dispatch_service._leader_slot(tied, 10).id == 10
            # Disabled and invalid assignments fail closed.
            assert github_dispatch_service._leader_slot(successor, 20) is None
            assert github_dispatch_service._leader_slot(successor, 21).id == 21
            assert github_dispatch_service._leader_slot(invalid, 999999) is None
            assert github_dispatch_service._leader_slot(disabled_only, None) is None
    finally:
        await engine.dispose()


async def test_v17_routing_fails_closed_without_valid_leader():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            item = await session.get(GithubWorkItem, 1)
            tied = await _slots(session, 1)
            successor = await _slots(session, 2)
            invalid = await _slots(session, 3)
            disabled_only = await _slots(session, 4)
            # Reordered explicit authority is the routed fallback.
            assert await github_dispatch_service.route_item(
                session, item, tied, [], leader_slot_id=11) == (11, "leader_fallback")
            # Disabled, invalid, and absent assignments fail closed.
            assert await github_dispatch_service.route_item(
                session, item, successor, [], leader_slot_id=20) == (None, "leader_unavailable")
            assert await github_dispatch_service.route_item(
                session, item, invalid, [], leader_slot_id=999999) == (None, "leader_unavailable")
            assert await github_dispatch_service.route_item(
                session, item, disabled_only, [], leader_slot_id=None) == (None, "leader_fallback")
    finally:
        await engine.dispose()


async def test_v17_participant_resolution_uses_explicit_assignment():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            item = await session.get(GithubWorkItem, 1)
            owner, leader = await agent_mail_service._dispatch_participants(session, item)
            assert owner is not None and owner.id == 7
            assert leader is not None and leader.id == 8
            # An invalid preserved assignment resolves no leader participant.
            broken = await session.get(GithubWorkItem, 3)
            owner_broken, leader_broken = await agent_mail_service._dispatch_participants(session, broken)
            assert leader_broken is None
    finally:
        await engine.dispose()


async def test_v17_initial_sql_decision_refuses_self_approval_and_invalid_assignment():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            self_owned = await session.get(GithubWorkItem, 2)
            with pytest.raises(GithubApprovalError) as refused:
                await github_approval_service._current_participants(session, self_owned)
            assert refused.value.status_code == 409
            broken = await session.get(GithubWorkItem, 3)
            with pytest.raises(GithubApprovalError) as missing:
                await github_approval_service._current_participants(session, broken)
            assert missing.value.status_code == 409
    finally:
        await engine.dispose()


async def test_v17_coordination_refuses_invalid_assignment(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            scope = await session.get(TeamGithubScope, 3)
            with pytest.raises(CoordinationError) as refused:
                await github_coordination_service.current_leader(session, scope)
            assert str(refused.value) == "leader_unavailable"
    finally:
        await engine.dispose()


async def test_v17_verification_gate_requires_enforced_identity(monkeypatch):
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            scope = await session.get(TeamGithubScope, 1)
            item = await session.get(GithubWorkItem, 1)
            monkeypatch.setattr(settings, "mail_capability_tokens_required", False)
            reason = await github_verification_service._approval_gate_reason(session, scope, item)
            assert reason == "capability token enforcement is disabled"
            monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
            reason = await github_verification_service._approval_gate_reason(session, scope, item)
            assert reason is not None
    finally:
        await engine.dispose()


async def test_v17_prompt_leader_check_uses_explicit_assignment():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            preset_one = await session.get(AgentTeamPreset, 1)
            preset_two = await session.get(AgentTeamPreset, 2)
            preset_three = await session.get(AgentTeamPreset, 3)
            slots = {slot.id: slot for slot in await _slots(session, 1)}
            all_slots = {slot.id: slot for slot in await _slots(session, 2)}
            invalid_slots = {slot.id: slot for slot in await _slots(session, 3)}
            # Reordered authority: first position is not the Leader.
            assert await agent_team_service._slot_is_leader(session, preset_one, slots[10]) is False
            assert await agent_team_service._slot_is_leader(session, preset_one, slots[11]) is True
            # The enabled successor is the Leader; the disabled slot never is.
            assert await agent_team_service._slot_is_leader(session, preset_two, all_slots[20]) is False
            assert await agent_team_service._slot_is_leader(session, preset_two, all_slots[21]) is True
            assert await agent_team_service._slot_is_leader(session, preset_three, invalid_slots[30]) is False
    finally:
        await engine.dispose()


async def test_v17_dispatch_ack_evidence_refuses_invalid_and_self_ack(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            slots_one = await _slots(session, 1)
            slots_three = await _slots(session, 3)
            item_one = await session.get(GithubWorkItem, 1)
            item_two = await session.get(GithubWorkItem, 2)
            item_three = await session.get(GithubWorkItem, 3)
            # Invalid preserved assignment: no Leader participant exists.
            broken = await github_dispatch_service._ack_evidence(session, item_three, slots_three)
            assert (broken.ok, broken.reason) == (False, "no_leader")
            # Owner on the Leader slot is a self-acknowledgement.
            self_ack = await github_dispatch_service._ack_evidence(session, item_two, slots_one)
            assert (self_ack.ok, self_ack.reason) == (False, "self_ack")
            # Capability enforcement off is refused explicitly.
            monkeypatch.setattr(settings, "mail_capability_tokens_required", False)
            unenforced = await github_dispatch_service._ack_evidence(session, item_one, slots_one)
            assert (unenforced.ok, unenforced.reason) == (False, "tokens_not_enforced")
    finally:
        await engine.dispose()


async def test_v17_monitoring_notification_fails_closed_without_valid_leader():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            scope_three = await session.get(TeamGithubScope, 3)
            item_one = await session.get(GithubWorkItem, 1)
            slots_three = await _slots(session, 3)
            slots_two = await _slots(session, 2)
            async def message_count():
                return (await session.execute(text("SELECT COUNT(*) FROM mail_messages"))).scalar_one()
            before = await message_count()
            # Invalid preserved assignment: no notification is sent.
            await github_dispatch_service.notify_blocker_merged(
                session, scope_three, item_one, slots_three)
            # A Leader slot without a registered member sends nothing.
            scope_two = TeamGithubScope(id=99, preset_id=2, repo_owner="example", repo_name="c",
                                        repo_path="/c")
            session.add(scope_two)
            await session.flush()
            await github_dispatch_service.notify_blocker_merged(
                session, scope_two, item_one, slots_two)
            assert await message_count() == before == 0
    finally:
        await engine.dispose()


async def test_v17_verification_gate_refuses_wrong_approver_and_self_approval(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            scope_one = await session.get(TeamGithubScope, 1)
            scope_three = await session.get(TeamGithubScope, 3)
            item_one = await session.get(GithubWorkItem, 1)
            item_two = await session.get(GithubWorkItem, 2)
            item_three = await session.get(GithubWorkItem, 3)
            for item in (item_one, item_two, item_three):
                item.ack_enforcement_epoch = 1
                item.ack_approval_round = item.approval_round_count
            # Invalid preserved assignment: no enabled leader slot exists.
            item_three.ack_approver_member_id = 9
            assert await github_verification_service._approval_gate_reason(
                session, scope_three, item_three) == "no enabled leader slot exists"
            # The owner is not the current designated leader member.
            item_one.ack_approver_member_id = 7
            assert await github_verification_service._approval_gate_reason(
                session, scope_one, item_one) == "approver is not the current designated leader"
            # Owner and approver are not distinct.
            item_two.ack_approver_member_id = 8
            assert await github_verification_service._approval_gate_reason(
                session, scope_one, item_two) == "owner and approver are not distinct"
            # A distinct current designated approver passes the gate.
            item_one.ack_approver_member_id = 8
            assert await github_verification_service._approval_gate_reason(
                session, scope_one, item_one) is None
    finally:
        await engine.dispose()


async def _seed_continuation_request(conn, *, request_id, revision_id, item_id, owner_member_id,
                                     leader_member_id, nonce, owner_slot_id):
    await conn.execute(text(
        "INSERT INTO github_approval_requests (id, work_item_id, request_kind, dispatch_nonce, "
        "approval_round, owner_member_id, leader_member_id, request_fingerprint, status, "
        "scope_revision_id, request_message_id, created_at) VALUES (:rid, :item, 'continuation', :nonce, "
        "0, :owner, :leader, :fp, 'pending', :revid, 100, CURRENT_TIMESTAMP)"
    ), {"rid": request_id, "item": item_id, "nonce": nonce, "owner": owner_member_id,
        "leader": leader_member_id, "fp": f"fp-{request_id}", "revid": revision_id})
    await conn.execute(text(
        "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision, "
        "owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths, allowed_actions, "
        "allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha, baseline_tree_sha, "
        "originating_escalation_reason, expected_workspace_id, expected_lease_token_hash, max_failed_heads, "
        "failed_head_count, status, delivery_attempt_count, approval_request_id, created_at) "
        "VALUES (:revid, :item, :nonce, 0, :slot, :owner, 'implementation', '/work', 'cont revision', '[]', "
        "'[]', '[]', '[]', '{}', :head, :tree, 'fixture', 0, 'cont-hash', 2, 0, 'active', 0, :rid, "
        "CURRENT_TIMESTAMP)"
    ), {"revid": revision_id, "item": item_id, "nonce": nonce, "slot": owner_slot_id,
        "owner": owner_member_id, "rid": request_id, "head": "c" * 40, "tree": "d" * 40})


async def test_v17_continuation_sql_decision_binds_to_migrated_assignment(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    engine = await _migrated_store()
    try:
        conn = await engine.connect()
        await _seed_continuation_request(
            conn, request_id=50, revision_id=2, item_id=1,
            owner_member_id=7, leader_member_id=8, nonce="v17-cont", owner_slot_id=10)
        await _seed_continuation_request(
            conn, request_id=51, revision_id=3, item_id=3,
            owner_member_id=9, leader_member_id=10, nonce="v17-cont-broken", owner_slot_id=30)
        await conn.execute(text(
            "UPDATE github_work_items SET dispatch_nonce = CASE id WHEN 1 THEN 'v17-cont' "
            "ELSE 'v17-cont-broken' END, approval_round_count = 0 WHERE id IN (1, 3)"))
        await conn.commit()
        await conn.close()

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            item_one = await session.get(GithubWorkItem, 1)
            item_three = await session.get(GithubWorkItem, 3)
            # A non-designated member cannot decide the continuation.
            with pytest.raises(GithubApprovalError) as wrong_leader:
                await github_approval_service.decide_continuation(
                    session, item_one, authenticated_leader_member_id=7,
                    decision="approve", reason="v17 migrated check", request_id=50)
            assert wrong_leader.value.status_code == 403
            # A stale recorded owner is refused even for the designated leader.
            await session.execute(text(
                "UPDATE github_approval_requests SET owner_member_id = 6 WHERE id = 50"))
            await session.commit()
            with pytest.raises(GithubApprovalError) as stale_owner:
                await github_approval_service.decide_continuation(
                    session, item_one, authenticated_leader_member_id=8,
                    decision="approve", reason="v17 migrated check", request_id=50)
            assert stale_owner.value.status_code == 409
            # An invalid preserved assignment refuses all continuation decisions.
            with pytest.raises(GithubApprovalError) as broken:
                await github_approval_service.decide_continuation(
                    session, item_three, authenticated_leader_member_id=9,
                    decision="approve", reason="v17 migrated check", request_id=51)
            assert broken.value.status_code == 409
    finally:
        await engine.dispose()


async def test_v17_dispatch_brief_names_reordered_designated_leader(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    monkeypatch.setattr("app.services.agent_mail_service.agent_mail_service.send_message",
                        lambda *args, **kwargs: None)
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(text(
                "UPDATE agent_team_presets SET autonomy_enabled = 1 WHERE id = 1"))
            await session.commit()
            scope = await session.get(TeamGithubScope, 1)
            item = await session.get(GithubWorkItem, 1)
            slots = await _slots(session, 1)
            launched = {}

            class _Result:
                launch_id = 991

            async def fake_launcher(db_ignored, preset_id, request):
                launched["request"] = request
                return _Result()

            workspace = GithubWorkspace(scope_id=1, path="/tmp/v17-brief-work", kind="worktree")
            session.add(workspace)
            await session.flush()

            async def fake_acquire(_db, _scope, _item):
                # The dispatch authority gate requires a committed acquisition.
                workspace.leased_item_id = _item.id
                workspace.leased_at = datetime.utcnow()
                workspace.lease_token = "v17-brief-lease"
                await _db.commit()
                return workspace

            async def fake_configure(_workspace, *_args, **_kwargs):
                return None

            async def fake_base_ref(*_args, **_kwargs):
                return "origin/main"

            monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda *args, **kwargs: None)
            monkeypatch.setattr("app.services.github_workspace_service.github_workspace_service.acquire",
                                fake_acquire)
            monkeypatch.setattr("app.services.github_workspace_service.github_workspace_service.reclaim_stale",
                                fake_configure)
            monkeypatch.setattr(
                "app.services.github_workspace_service.github_workspace_service.configure_dispatch_worktree",
                fake_configure)
            monkeypatch.setattr(
                "app.services.github_workspace_service.github_workspace_service.resolve_attempt_base_ref",
                fake_base_ref)

            await github_dispatch_service.dispatch_pending(
                session, scope, slots,
                launcher=fake_launcher,
                issue_labels_by_number={1: [scope.dispatch_label]},
                issue_details_by_number={1: {"body": "migrated brief"}},
            )
            request = launched.get("request")
            assert request is not None, (item.dispatch_status, item.pending_reason,
                                        item.escalation_reason, item.status_note)
            prompts = getattr(request, "slot_prompt_overrides", {}) or {}
            joined = "\n".join(str(value) for value in prompts.values())
            # The brief names the reordered designated Leader, not first position.
            assert "tied-b" in joined
            assert "tied-a" not in joined.split("Team leader / approver:")[-1].splitlines()[0]
    finally:
        await engine.dispose()


@pytest.mark.parametrize(("stored", "expected", "matches"), [
    ("2026-10-08 11:00:00", "2026-10-08 11:00:00.000000", True),
    ("2026-10-08 11:00:00.000000", "2026-10-08 11:00:00", True),
    ("2026-10-08 11:00:00.000001", "2026-10-08 11:00:00", False),
    ("2026-10-08 11:00:00", "2026-10-08 11:00:00.000001", False),
    ("2026-10-08 11:00:00.123456", "2026-10-08 11:00:00.123456", True),
    ("2026-10-08 11:00:01", "2026-10-08 11:00:00", False),
])
async def test_v17_start_identity_preserves_legacy_timestamp_precision(stored, expected, matches):
    from app.services.github_dispatch_service import _identity_value_clause

    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(text(
                "UPDATE github_work_items SET created_at = :stamp, dispatched_at = :stamp WHERE id = 1"
            ), {"stamp": stored})
            workspace = GithubWorkspace(scope_id=1, path="/tmp/v17-time-lease", kind="worktree")
            session.add(workspace)
            await session.flush()
            await session.execute(text(
                "UPDATE github_workspaces SET leased_at = :stamp WHERE id = :id"
            ), {"stamp": stored, "id": workspace.id})
            await session.commit()
            for model, column, row_id in (
                (GithubWorkItem, GithubWorkItem.created_at, 1),
                (GithubWorkItem, GithubWorkItem.dispatched_at, 1),
                (GithubWorkspace, GithubWorkspace.leased_at, workspace.id),
            ):
                found = await session.scalar(select(model.id).where(
                    model.id == row_id,
                    _identity_value_clause(column, datetime.fromisoformat(expected)),
                ))
                assert (found is not None) == matches
    finally:
        await engine.dispose()


async def test_v17_cold_start_monitor_selection_preserves_authority_on_invalid_assignment():
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(text(
                "UPDATE github_work_items SET dispatch_status = 'dispatched', "
                "dispatched_at = CURRENT_TIMESTAMP WHERE id = 3"))
            await session.commit()
            scope = await session.get(TeamGithubScope, 3)
            slots = await _slots(session, 3)
            # The monitor runs on a cold-start dispatched item with an invalid
            # preserved assignment and must never invent Leader authority.
            await github_dispatch_service.monitor_dispatched(
                session, scope, preset_slots=slots,
                wake_state_by_slot={slots[0].id: "wakeable"})
            item = await session.get(GithubWorkItem, 3)
            assert item.dispatch_status == "dispatched"
            assert item.ack_approver_member_id is None
            approvals = (await session.execute(text(
                "SELECT COUNT(*) FROM github_approval_requests"))).scalar_one()
            assert approvals == 0
            leader_actions = (await session.execute(text(
                "SELECT COUNT(*) FROM github_attempt_scope_revisions WHERE status = 'active'"
            ))).scalar_one()
            assert leader_actions == 0
    finally:
        await engine.dispose()


async def test_v17_completion_watch_refuses_invalid_assignment(monkeypatch):
    """V17: the completion-watch Leader consumer fails closed on migrated stores."""
    from app.services.github_owner_followup_service import github_owner_followup_service

    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    engine = await _migrated_store()
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            # Automation and coordination policy on: the watch must reach the
            # Leader consumer and fail closed on the invalid assignment.
            await session.execute(text(
                "UPDATE agent_team_presets SET autonomy_enabled = 1 WHERE id = 3"))
            session.add(GithubBacklogCoordination(scope_id=3, enabled=True, issue_numbers=[3]))
            await session.commit()
            with pytest.raises(CoordinationError) as refused:
                await github_owner_followup_service.context(session, 3, 3, [])
            assert refused.value.code == "leader_unavailable"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def _authority_references(connection):
    """Full authority reference snapshot for migration and decision comparisons."""

    async def rows(sql):
        return [dict(row) for row in (await connection.execute(text(sql))).mappings().all()]

    columns = {row[1] for row in (await connection.execute(text("PRAGMA table_info(agent_team_presets)"))).all()}
    explicit = None
    if "leader_slot_id" in columns:
        explicit = {row[0]: row[1] for row in (await connection.execute(text(
            "SELECT id, leader_slot_id FROM agent_team_presets ORDER BY id"
        ))).all()}
    return {
        "presets": await rows("SELECT id, name, autonomy_enabled FROM agent_team_presets ORDER BY id"),
        "slots": await rows("SELECT id, preset_id, position, enabled FROM agent_team_slots ORDER BY id"),
        "members": await rows("SELECT id, identity_key, display_name, participant_kind, team_preset_id, team_slot_id "
                              "FROM mail_team_members ORDER BY id"),
        "sessions": await rows("SELECT id, member_id, provider, source, session_key, mailbox_status, "
                               "team_preset_id, team_slot_id, bound_pane_pid, bound_pane_proc_start, "
                               "capability_token_hash FROM mail_agent_sessions ORDER BY id"),
        "pane_bindings": await rows("SELECT pane_pid, pane_proc_start, slot_id, preset_id "
                                    "FROM agent_pane_bindings ORDER BY pane_pid"),
        "items": await rows("SELECT id, scope_id, dispatch_status, attempt_phase, owner_slot_id, "
                            "handoff_target_slot_id, ack_approver_member_id, active_scope_revision, "
                            "approval_round_count, dispatch_nonce FROM github_work_items ORDER BY id"),
        "workspaces": await rows("SELECT id, scope_id, leased_item_id, lease_token, leased_owner_pid, "
                                 "leased_owner_proc_start FROM github_workspaces ORDER BY id"),
        "approval_requests": await rows(
            "SELECT id, work_item_id, request_kind, dispatch_nonce, approval_round, owner_member_id, "
            "leader_member_id, request_fingerprint, status, request_message_id, scope_revision_id "
            "FROM github_approval_requests ORDER BY id"),
        "revisions": await rows(
            "SELECT id, work_item_id, dispatch_nonce, approval_request_id, revision, owner_slot_id, "
            "owner_member_id, phase, execution_target, baseline_head_sha, baseline_tree_sha, "
            "expected_workspace_id, expected_lease_token_hash, status "
            "FROM github_attempt_scope_revisions ORDER BY id"),
        "explicit": explicit,
        "legacy": await rows(
            "SELECT p.id, (SELECT s.id FROM agent_team_slots s WHERE s.preset_id = p.id AND s.enabled = 1 "
            " ORDER BY s.position, s.id LIMIT 1) AS legacy_id FROM agent_team_presets p ORDER BY p.id"),
    }


async def test_v17_populated_decisions_through_real_entries_on_migrated_store():
    """V17: populated pre-migration approvals survive migration and real decisions.

    Initial_plan and continuation approvals, members, sessions, items and leases
    are seeded before the real migration. Successful decisions change authorized
    decision fields only; stable identity is compared separately.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("ALTER TABLE agent_team_presets DROP COLUMN leader_slot_id"))
            await conn.execute(text(
                "INSERT INTO agent_team_presets (id, name, created_at, updated_at, autonomy_enabled) VALUES "
                "(1, 'decisions', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0)"
            ))
            await conn.execute(text(
                "INSERT INTO agent_team_slots (id, preset_id, position, display_name, provider, repo_id, "
                "repo_path, repo_name, launch_mode, enabled, created_at, updated_at) VALUES "
                "(10, 1, 0, 'leader-slot', 'codex-cli', 'a', '/a', 'a', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(11, 1, 0, 'owner-slot', 'codex-cli', 'b', '/b', 'b', 'plain', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO mail_team_members (id, identity_key, repo_id, repo_path, repo_name, display_name, "
                "participant_kind, team_preset_id, team_slot_id, created_at, updated_at) VALUES "
                "(7, 'slot:7', 'b', '/b', 'b', 'owner-member', 'team_slot', 1, 11, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(8, 'slot:8', 'a', '/a', 'a', 'leader-member', 'team_slot', 1, 10, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO mail_agent_sessions (id, member_id, provider, source, session_key, wake_enabled, "
                "mailbox_status, last_seen_at, team_preset_id, team_slot_id, bound_pane_pid, "
                "bound_pane_proc_start, capability_token_hash, created_at) VALUES "
                "(21, 7, 'codex-cli', 'mcp', 'mcp:21', 1, 'connected', CURRENT_TIMESTAMP, 1, 11, 1001, '1', "
                "'test-cap-owner', CURRENT_TIMESTAMP), "
                "(22, 8, 'codex-cli', 'mcp', 'mcp:22', 1, 'connected', CURRENT_TIMESTAMP, 1, 10, 1002, '1', "
                "'test-cap-leader', CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO agent_pane_bindings (pane_pid, pane_proc_start, slot_id, preset_id, "
                "created_at) VALUES "
                "(1001, '1', 11, 1, CURRENT_TIMESTAMP), "
                "(1002, '1', 10, 1, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO mail_messages (id, kind, sender_member_id, recipient_member_id, subject, body_markdown, "
                "created_at) VALUES "
                "(100, 'question', 7, 8, 'Plan', 'Fixture plan', CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO team_github_scopes (id, preset_id, repo_owner, repo_name, repo_path, dispatch_label, "
                "design_label, merge_policy, github_auth_mode, base_ref, max_approval_rounds, "
                "max_concurrent_dispatched, max_verification_retries, max_auto_merges_per_day, "
                "max_build_parallelism, builds_out_of_tree, continuation_enabled, max_continuation_revisions, "
                "max_continuation_failed_heads, max_failed_heads_per_revision, max_scope_paths, "
                "max_scope_commands, enabled, created_at, updated_at) "
                "VALUES (1, 1, 'example', 'a', '/a', 'ready', 'design', 'human', 'ambient', 'origin/main', "
                "3, 1, 1, 0, 1, 0, 0, 6, 8, 2, 32, 16, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url, "
                "github_updated_at, issue_type, dispatch_status, attempt_phase, owner_slot_id, "
                "active_scope_revision, approval_round_count, retry_count, diagnostic_retry_count, "
                "dispatch_nonce, created_at, updated_at) VALUES "
                "(1, 1, 7, 'title', 'https://example.invalid/7', CURRENT_TIMESTAMP, 'code', "
                "'pending', 'implementation', 11, 0, 0, 0, 0, 'v17d', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_work_items (id, scope_id, issue_number, issue_title, issue_url, "
                "github_updated_at, issue_type, dispatch_status, attempt_phase, owner_slot_id, "
                "active_scope_revision, approval_round_count, retry_count, diagnostic_retry_count, "
                "dispatch_nonce, escalation_reason, pr_number, created_at, updated_at) VALUES "
                "(2, 1, 8, 'title-2', 'https://example.invalid/8', CURRENT_TIMESTAMP, 'code', "
                "'escalated', 'implementation', 11, 0, 0, 0, 0, 'v17d', 'plan_blocked', 25, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_approval_requests (id, work_item_id, request_kind, dispatch_nonce, "
                "approval_round, owner_member_id, leader_member_id, request_fingerprint, status, "
                "request_message_id, scope_revision_id, created_at) VALUES "
                "(50, 1, 'initial_plan', 'v17d', 0, 7, 8, 'fp-initial', 'pending', 100, NULL, CURRENT_TIMESTAMP), "
                "(51, 2, 'continuation', 'v17d', 0, 7, 8, 'fp-cont', 'pending', 100, 2, CURRENT_TIMESTAMP)"
            ))
            await conn.execute(text(
                "INSERT INTO github_attempt_scope_revisions (id, work_item_id, dispatch_nonce, revision, "
                "owner_slot_id, owner_member_id, phase, execution_target, summary, allowed_paths, allowed_actions, "
                "allowed_commands, prohibited_actions, tool_fallbacks, baseline_head_sha, baseline_tree_sha, "
                "originating_escalation_reason, expected_workspace_id, expected_lease_token_hash, max_failed_heads, "
                "failed_head_count, status, delivery_attempt_count, approval_request_id, created_at) "
                "VALUES (2, 2, 'v17d', 0, 11, 7, 'implementation', '/work', 'cont revision', '[]', '[]', '[]', "
                "'[]', '{}', :head, :tree, 'plan_blocked', 1, :lease_hash, 2, 0, 'proposed', 0, 51, CURRENT_TIMESTAMP)"
            ), {"head": "a" * 40, "tree": "b" * 40,
                "lease_hash": github_approval_service.lease_token_hash("hash-2")})
            await conn.execute(text(
                "INSERT INTO github_workspaces (id, scope_id, path, kind, dispatchable, enabled, leased_item_id, "
                "lease_token, created_at, updated_at) VALUES "
                "(1, 1, '/work/1', 'worktree', 1, 1, 2, 'hash-2', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ))
            await conn.commit()

            before = await _authority_references(conn)
            await _run_sqlite_compat_migrations(conn)
            await conn.rollback()
            after_migration = await _authority_references(conn)
            # Populated pre-migration authority is preserved by the migration.
            for key in ("presets", "slots", "members", "sessions", "pane_bindings", "items",
                        "workspaces", "approval_requests", "revisions"):
                assert after_migration[key] == before[key], key
            # A real tied roster resolves through the migration to the lower id.
            assert after_migration["explicit"] == {1: 10}
            assert after_migration["legacy"] == [{"id": 1, "legacy_id": 10}]

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            item = await session.get(GithubWorkItem, 1, populate_existing=True)
            # Negative case retained: a non-designated member cannot decide.
            # The precise refusal code is asserted and complete authority is
            # unchanged after the refusal.
            with pytest.raises(GithubApprovalError) as refused:
                await github_approval_service.decide(
                    session, item, authenticated_leader_member_id=7,
                    decision="approved", reason="v17 decision", request_id=50)
            assert refused.value.status_code == 403
            assert refused.value.detail == "not_designated_leader"
            session.expire_all()
            after_refusal = await _authority_references(session)
            for key in ("presets", "slots", "members", "sessions", "pane_bindings",
                        "items", "workspaces", "approval_requests", "revisions"):
                assert after_refusal[key] == after_migration[key], key
            # Reattach the item after the snapshot read.
            item = await session.get(GithubWorkItem, 1, populate_existing=True)

            # Successful real initial-plan decision.
            request, applied = await github_approval_service.decide(
                session, item, authenticated_leader_member_id=8,
                decision="approved", reason="v17 decision", request_id=50)
            assert applied is True
            assert request.status == "approved"

            # Successful real continuation decision on its own work item.
            item_two = await session.get(GithubWorkItem, 2, populate_existing=True)
            cont_request, _cont_revision, cont_applied = await github_approval_service.decide_continuation(
                session, item_two, authenticated_leader_member_id=8,
                decision="approved", reason="v17 continuation", request_id=51)
            assert cont_applied is True
            assert cont_request.status == "approved"

            # Authorized decision fields changed; stable identity did not.
            session.expire_all()
            stable = await _authority_references(session)
            assert stable["slots"] == before["slots"]
            assert stable["members"] == before["members"]
            assert stable["sessions"] == before["sessions"]
            assert stable["workspaces"] == before["workspaces"]
            # Authorized decision fields change; stable revision identity does not.
            stable_revisions = [{k: v for k, v in row.items() if k != "status"} for row in stable["revisions"]]
            before_revisions = [{k: v for k, v in row.items() if k != "status"} for row in before["revisions"]]
            assert stable_revisions == before_revisions
            revision_statuses = {row["id"]: row["status"] for row in stable["revisions"]}
            assert revision_statuses == {2: "approved"}
            stable_items = [{k: v for k, v in row.items() if k in (
                "id", "scope_id", "owner_slot_id", "handoff_target_slot_id", "active_scope_revision",
                "dispatch_nonce")}
                for row in stable["items"]]
            before_items = [{k: v for k, v in row.items() if k in (
                "id", "scope_id", "owner_slot_id", "handoff_target_slot_id", "active_scope_revision",
                "dispatch_nonce")}
                for row in before["items"]]
            assert stable_items == before_items
            # Pane bindings are unchanged after both successful decisions.
            assert stable["pane_bindings"] == after_migration["pane_bindings"]
            # The explicit Leader map equals the migrated baseline; the
            # pre-migration map is None and the migration change is intended.
            assert stable["explicit"] == after_migration["explicit"]
            assert after_refusal["explicit"] == after_migration["explicit"]
            authorized_fields = {"status", "reason", "decision_message_id", "decided_at"}
            stable_approvals = [
                {k: v for k, v in row.items() if k not in authorized_fields}
                for row in stable["approval_requests"]]
            before_approvals = [
                {k: v for k, v in row.items() if k not in authorized_fields}
                for row in before["approval_requests"]]
            assert stable_approvals == before_approvals
            statuses = {row["id"]: row["status"] for row in stable["approval_requests"]}
            assert statuses == {50: "approved", 51: "approved"}
    finally:
        await engine.dispose()
