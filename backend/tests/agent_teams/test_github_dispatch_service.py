"""Dispatch routing + concurrency tests."""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from io import StringIO

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base
from app.models.database import (
    AgentTeamLaunch,
    AgentTeamLaunchItem,
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
from app.services.agent_mail_service import agent_mail_service
from app.services.github_dispatch_service import (
    AttemptState,
    GithubAuthModeUnresolved,
    GithubDispatchService,
    PartiallyPreparedAttempt,
    attempt_state,
    github_dispatch_service,
)
from app.services.github_workspace_service import (
    GithubWorkspaceCredentialRevokeError,
    github_workspace_service,
)
from app.services.github_app_auth_service import github_app_auth_service
from app.services.github_approval_service import github_approval_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def host_has_enough_memory(monkeypatch):
    monkeypatch.setattr(
        github_dispatch_service,
        "_available_memory_mb",
        lambda: 999_999,
        raising=False,
    )

    async def reset_succeeds(*_args, **_kwargs):
        return None

    async def configure_succeeds(*_args, **_kwargs):
        return None

    async def config_runner_succeeds(_args):
        return 0, ""

    async def remote_succeeds(*_args, **_kwargs):
        return None

    monkeypatch.setattr(github_workspace_service, "reset_workspace", reset_succeeds)
    monkeypatch.setattr(
        github_workspace_service,
        "configure_dispatch_worktree",
        configure_succeeds,
    )
    monkeypatch.setattr(github_workspace_service, "_runner", config_runner_succeeds)
    monkeypatch.setattr(
        github_workspace_service,
        "validate_app_remote",
        remote_succeeds,
    )


@pytest.fixture(autouse=True)
def no_discovered_panes(monkeypatch):
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [],
    )


async def _team(db):
    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    architect = AgentTeamSlot(
        preset_id=preset.id,
        position=0,
        display_name="Architect",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        launch_mode="plain",
        launch_options={},
        enabled=True,
        area_labels=None,
        expertise="cross-cutting",
    )
    backend = AgentTeamSlot(
        preset_id=preset.id,
        position=1,
        display_name="Backend SME",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        launch_mode="plain",
        launch_options={},
        enabled=True,
        area_labels=["area:backend"],
        expertise="backend",
    )
    db.add_all([architect, backend])
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="o",
        repo_name="r",
        repo_path="/tmp/r",
        base_ref="origin/master",
    )
    db.add(scope)
    await db.flush()
    db.add_all(
        [
            GithubWorkspace(scope_id=scope.id, path=f"/tmp/r-ws-{index}")
            for index in range(1, 6)
        ]
    )
    await db.commit()
    return preset, [architect, backend], scope


async def _lease_for(db, scope, item, **overrides):
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(
                GithubWorkspace.scope_id == scope.id,
                GithubWorkspace.leased_item_id.is_(None),
            )
            .limit(1)
        )
    ).scalar_one()
    workspace.leased_item_id = item.id
    workspace.leased_at = datetime.utcnow()
    workspace.lease_token = "t1"
    for key, value in overrides.items():
        setattr(workspace, key, value)
    await db.commit()
    return workspace


def _isolate_agent_mail_nudges(monkeypatch):
    async def keep_synthetic_sessions(_db):
        return None

    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", keep_synthetic_sessions)
    monkeypatch.setattr(
        agent_mail_service,
        "_send_tmux_inbox_check",
        lambda session, nudge_prompt="check inbox": {
            "target": session.tmux_target,
            "prompt": nudge_prompt,
        },
    )


async def _leased_item_for_reminder(
    db,
    scope,
    *,
    issue_number: int,
    dispatch_status: str,
    owner_slot_id: int | None = None,
    retry_requested_at: datetime | None = None,
    reminded_at: datetime | None = None,
):
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=issue_number,
        issue_title=f"Issue {issue_number}",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status=dispatch_status,
        owner_slot_id=owner_slot_id,
        retry_requested_at=retry_requested_at,
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(
                GithubWorkspace.scope_id == scope.id,
                GithubWorkspace.leased_item_id.is_(None),
            )
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    workspace.lease_token = f"tok-{issue_number}"
    workspace.lease_release_reminded_at = reminded_at
    await db.commit()
    return item, workspace


class _LabelsClient:
    def __init__(self, labels):
        self._labels = labels

    async def list_repo_labels(self, owner, repo):
        return list(self._labels)


def _item(scope_id, number, labels):
    return (
        GithubWorkItem(
            scope_id=scope_id,
            issue_number=number,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="pending",
        ),
        [{"name": name} for name in labels],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "installation_id", "expected_mode", "expected_id"),
    [
        ("unknown", None, "ambient", None),
        ("unknown", 42, "ambient", None),
        ("ambient", None, "ambient", None),
        ("ambient", 42, "ambient", None),
    ],
)
async def test_auth_mode_normalizes_without_app_configuration(
    db,
    monkeypatch,
    mode,
    installation_id,
    expected_mode,
    expected_id,
):
    _, _, scope = await _team(db)
    scope.github_auth_mode = mode
    scope.github_app_installation_id = installation_id
    await db.commit()
    monkeypatch.setattr(settings, "github_app_id", "")
    monkeypatch.setattr(settings, "github_app_private_key_path", "")
    monkeypatch.setattr(settings, "github_app_bot_login", "")

    resolved = await github_dispatch_service._resolve_scope_auth_mode(db, scope)

    await db.refresh(scope)
    assert resolved == expected_mode
    assert scope.github_auth_mode == expected_mode
    assert scope.github_app_installation_id == expected_id


@pytest.mark.asyncio
async def test_stored_app_mode_does_not_re_resolve(db, monkeypatch):
    _, _, scope = await _team(db)
    scope.github_auth_mode = "app"
    scope.github_app_installation_id = 42
    await db.commit()
    calls = []

    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def unexpected_lookup(*_args):
        calls.append(True)
        return 99

    monkeypatch.setattr(
        github_app_auth_service,
        "resolve_installation",
        unexpected_lookup,
    )

    assert await github_dispatch_service._resolve_scope_auth_mode(db, scope) == "app"
    assert calls == []
    assert scope.github_app_installation_id == 42


@pytest.mark.asyncio
async def test_app_without_installation_id_refuses_without_lookup(db, monkeypatch):
    _, _, scope = await _team(db)
    scope.github_auth_mode = "app"
    scope.github_app_installation_id = None
    await db.commit()
    called = False

    async def unexpected_lookup(*_args):
        nonlocal called
        called = True
        return 99

    monkeypatch.setattr(
        github_app_auth_service,
        "resolve_installation",
        unexpected_lookup,
    )

    with pytest.raises(GithubAuthModeUnresolved):
        await github_dispatch_service._resolve_scope_auth_mode(db, scope)
    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("resolved_id", "expected"), [(55, "app"), (None, "ambient")])
async def test_unknown_mode_persists_lookup_answer(
    db, monkeypatch, resolved_id, expected
):
    _, _, scope = await _team(db)
    monkeypatch.setattr(settings, "github_app_id", "123")
    monkeypatch.setattr(settings, "github_app_private_key_path", "/tmp/app.pem")
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **_kwargs: None,
    )

    async def lookup(*_args):
        return resolved_id

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", lookup)

    assert await github_dispatch_service._resolve_scope_auth_mode(db, scope) == expected
    await db.refresh(scope)
    assert scope.github_auth_mode == expected
    assert scope.github_app_installation_id == resolved_id


@pytest.mark.asyncio
async def test_partial_app_configuration_refuses_without_lookup(db, monkeypatch):
    _, _, scope = await _team(db)
    monkeypatch.setattr(settings, "github_app_id", "123")
    monkeypatch.setattr(settings, "github_app_private_key_path", "")
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    called = False

    async def lookup(*_args):
        nonlocal called
        called = True
        return 55

    monkeypatch.setattr(github_app_auth_service, "resolve_installation", lookup)

    with pytest.raises(GithubAuthModeUnresolved):
        await github_dispatch_service._resolve_scope_auth_mode(db, scope)
    assert called is False
    assert scope.github_auth_mode == "unknown"


async def _create_registered_slot_member(db, slot: AgentTeamSlot) -> MailTeamMember:
    for index in range(2):
        db.add(
            MailTeamMember(
                identity_key=f"repo:offset:{slot.id}:{index}",
                repo_id="offset",
                repo_path="/tmp/offset",
                repo_name="offset",
                display_name=f"Offset {index}",
                participant_kind="repo",
            )
        )
    await db.flush()
    member = MailTeamMember(
        identity_key=f"slot:test:{slot.id}",
        repo_id=slot.repo_id,
        repo_path=slot.repo_path,
        repo_name=slot.repo_name,
        display_name=slot.display_name,
        participant_kind="team_slot",
        team_preset_id=slot.preset_id,
        team_slot_id=slot.id,
        role=slot.role,
        charter=slot.charter,
    )
    db.add(member)
    await db.commit()
    assert member.id != slot.id
    return member


async def _active_continuation(
    db,
    scope,
    owner_slot,
    *,
    issue_number,
    activated_at,
    owner_contact_at,
):
    owner_member = await _create_registered_slot_member(db, owner_slot)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=issue_number,
        issue_title="Continuation",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=owner_slot.id,
        dispatch_nonce=f"nonce-{issue_number}",
        dispatch_head_ref=f"deck/slot-{owner_slot.id}/issue-{issue_number}",
        dispatch_base_ref="origin/master",
        pr_number=issue_number,
        active_scope_revision=1,
        attempt_phase="implementation",
        continuation_activated_at=activated_at,
        dispatched_at=activated_at - timedelta(days=1),
        updated_at=activated_at - timedelta(days=1),
    )
    db.add(item)
    await db.flush()
    workspace = await _lease_for(
        db,
        scope,
        item,
        lease_last_owner_contact_at=owner_contact_at,
    )
    revision = GithubAttemptScopeRevision(
        work_item_id=item.id,
        dispatch_nonce=item.dispatch_nonce,
        revision=1,
        owner_slot_id=owner_slot.id,
        owner_member_id=owner_member.id,
        phase="implementation",
        execution_target="workspace",
        summary="Continue one bounded fix",
        allowed_paths=["src/fix.py"],
        allowed_actions=["push_pr_head", "request_verification"],
        allowed_commands=["pytest -q"],
        prohibited_actions=[],
        tool_fallbacks={},
        baseline_head_sha="base-head",
        baseline_tree_sha="base-tree",
        originating_escalation_reason="retry_count_exhausted",
        expected_workspace_id=workspace.id,
        expected_lease_token_hash="hash",
        max_failed_heads=2,
        status="active",
    )
    db.add(revision)
    await db.commit()
    return item, workspace, revision, owner_member


async def _create_live_slot_launch_session(
    db,
    preset: AgentTeamPreset,
    slot: AgentTeamSlot,
    *,
    target: str,
) -> tuple[AgentTeamLaunch, MailAgentSession]:
    launch = AgentTeamLaunch(
        preset_id=preset.id,
        plan_hash=f"plan:{target}",
        status="running",
    )
    db.add(launch)
    await db.flush()
    db.add(
        AgentTeamLaunchItem(
            launch_id=launch.id,
            slot_id=slot.id,
            action="spawn",
            status="started",
            provider=slot.provider,
            repo_path=slot.repo_path,
            tmux_target=target,
        )
    )
    member = await agent_mail_service.get_or_create_slot_member(db, slot)
    session = MailAgentSession(
        member_id=member.id,
        provider=slot.provider,
        source="observed",
        session_key=f"tmux:{target}",
        cwd=slot.repo_path,
        tmux_target=target,
        team_preset_id=preset.id,
        team_slot_id=slot.id,
        mailbox_status="observed",
        last_seen_at=datetime.utcnow(),
    )
    db.add(session)
    await db.commit()
    return launch, session


async def _seed_observed_panes(db, preset, slot, panes):
    member = await _create_registered_slot_member(db, slot)
    for pane_id, target in panes:
        db.add(
            MailAgentSession(
                member_id=member.id,
                provider=slot.provider,
                source="observed",
                session_key=f"tmux:{pane_id}",
                pane_id=pane_id,
                cwd=slot.repo_path,
                tmux_target=target,
                team_preset_id=preset.id,
                team_slot_id=slot.id,
                mailbox_status="observed",
                last_seen_at=datetime.utcnow(),
            )
        )
    await db.commit()
    return member


def _pane(*, pane_id, target, cwd):
    return {
        "provider": "codex-cli",
        "provider_display_name": "Codex",
        "tmux_target": target,
        "session_name": target.split(":")[0],
        "window_name": "main",
        "pane_id": pane_id,
        "cwd": cwd,
        "pid": "4242",
        "status": "active",
    }


async def _launcher_that_must_not_run(*_args, **_kwargs):
    raise AssertionError("dispatch launched despite an ambiguous slot")


def test_leader_unblock_instructions_text():
    text = github_dispatch_service._leader_unblock_instructions()
    assert "dependency map" in text.lower()
    assert "deck_retry_work_item" in text
    assert "github_dispatch_blocker_merged" in text
    assert "all" in text.lower()
    assert "deck_list_work_items" in text
    assert "start" in text.lower()


@pytest.mark.asyncio
async def test_bootstrap_prompt_appends_unblock_only_for_leader(db):
    from app.services.agent_team_service import agent_team_service

    preset, slots, scope = await _team(db)
    leader, non_leader = slots[0], slots[1]

    leader_text = await agent_team_service._bootstrap_prompt(db, preset, leader)
    non_leader_text = await agent_team_service._bootstrap_prompt(db, preset, non_leader)

    assert "deck_retry_work_item" in leader_text
    assert "dependency map" in leader_text.lower()
    assert "deck_retry_work_item" not in non_leader_text


@pytest.mark.asyncio
async def test_bootstrap_prompt_appends_unblock_even_with_custom_prompt(db):
    from app.services.agent_team_service import agent_team_service

    preset, slots, scope = await _team(db)
    leader = slots[0]
    leader.bootstrap_prompt = "CUSTOM standing prompt."
    await db.commit()

    text = await agent_team_service._bootstrap_prompt(db, preset, leader)

    assert text.startswith("CUSTOM standing prompt.")
    assert "deck_retry_work_item" in text


@pytest.mark.asyncio
async def test_notify_blocker_merged_sends_leader_message_with_escalated_items(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    from app.services.agent_mail_service import agent_mail_service

    leader_member = await agent_mail_service.get_or_create_slot_member(db, architect)
    await db.commit()
    merged = GithubWorkItem(
        scope_id=scope.id,
        issue_number=816,
        issue_title="baseline",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    dep1 = GithubWorkItem(
        scope_id=scope.id,
        issue_number=817,
        issue_title="build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        status_note="Blocked by #816",
    )
    dep2 = GithubWorkItem(
        scope_id=scope.id,
        issue_number=818,
        issue_title="gmusic",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        status_note="Blocked by #817",
    )
    other = GithubWorkItem(
        scope_id=scope.id,
        issue_number=828,
        issue_title="docs",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
    )
    db.add_all([merged, dep1, dep2, other])
    await db.commit()

    await github_dispatch_service.notify_blocker_merged(db, scope, merged, slots)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    hit = [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]
    assert len(hit) == 1
    message = hit[0]
    assert message.recipient_member_id == leader_member.id
    assert "816" in (message.subject or "")
    escalated = {entry["issue_number"] for entry in message.payload["escalated_items"]}
    assert escalated == {817, 818}
    work_item_ids = {
        entry["work_item_id"] for entry in message.payload["escalated_items"]
    }
    assert dep1.id in work_item_ids and dep2.id in work_item_ids
    assert message.payload["issue_number"] == 816


@pytest.mark.asyncio
async def test_notify_blocker_merged_noop_when_no_leader_registered(db):
    preset, slots, scope = await _team(db)
    merged = GithubWorkItem(
        scope_id=scope.id,
        issue_number=816,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(merged)
    await db.commit()

    await github_dispatch_service.notify_blocker_merged(db, scope, merged, slots)

    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]


@pytest.mark.asyncio
async def test_work_item_has_lifecycle_columns(db):
    preset, slots, scope = await _team(db)
    now = datetime.utcnow()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=900,
        issue_title="x",
        issue_url="u",
        github_updated_at=now,
        dispatch_status="dispatched",
        dispatched_at=now,
        ack_received_at=now,
        last_nudge_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    assert item.dispatched_at is not None
    assert item.ack_received_at is not None
    assert item.last_nudge_at is not None


def test_ack_lifecycle_settings_present():
    assert settings.github_leader_ack_timeout_seconds > 0
    assert settings.github_design_ack_multiplier >= 1
    assert settings.github_owner_idle_timeout_seconds > 0
    assert settings.github_nudge_grace_seconds > 0
    assert settings.github_continuation_proposal_expiry_seconds == 3600
    assert settings.github_continuation_leader_nudge_cooldown_seconds == 180
    assert settings.github_continuation_owner_ack_nudge_cooldown_seconds == 180
    assert settings.github_recovery_nudge_cooldown_seconds == 180


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (
            {
                "dispatch_nonce": None,
                "dispatch_head_ref": None,
                "approval_round_count": 0,
                "owner_slot_id": 9,
                "routing_method": "old-route",
            },
            AttemptState.UNPREPARED,
        ),
        (
            {
                "dispatch_nonce": "0123456789abcdef",
                "dispatch_head_ref": "deck/slot-9/issue-42-0123456789abcdef",
                "dispatch_base_ref": "origin/master",
                "approval_round_count": 1,
                "owner_slot_id": 9,
                "routing_method": "label",
            },
            AttemptState.PREPARED,
        ),
        (
            {
                "dispatch_nonce": None,
                "dispatch_head_ref": "head",
                "approval_round_count": 1,
                "owner_slot_id": 9,
                "routing_method": "label",
            },
            PartiallyPreparedAttempt,
        ),
        (
            {
                "dispatch_nonce": "0123456789abcdef",
                "dispatch_head_ref": None,
                "approval_round_count": 1,
                "owner_slot_id": 9,
                "routing_method": "label",
            },
            PartiallyPreparedAttempt,
        ),
        (
            {
                "dispatch_nonce": "0123456789abcdef",
                "dispatch_head_ref": "head",
                "approval_round_count": 0,
                "owner_slot_id": 9,
                "routing_method": "label",
            },
            PartiallyPreparedAttempt,
        ),
        (
            {
                "dispatch_nonce": "0123456789abcdef",
                "dispatch_head_ref": "head",
                "approval_round_count": 1,
                "owner_slot_id": None,
                "routing_method": "label",
            },
            PartiallyPreparedAttempt,
        ),
        (
            {
                "dispatch_nonce": "0123456789abcdef",
                "dispatch_head_ref": "head",
                "approval_round_count": 1,
                "owner_slot_id": 9,
                "routing_method": None,
            },
            PartiallyPreparedAttempt,
        ),
    ],
)
def test_attempt_state_requires_one_complete_identity(values, expected):
    item = GithubWorkItem(
        scope_id=1,
        issue_number=42,
        issue_title="attempt",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
        **values,
    )

    if isinstance(expected, AttemptState):
        assert attempt_state(item) is expected
    else:
        original_nonce = item.dispatch_nonce
        with pytest.raises(expected):
            attempt_state(item)
        assert item.dispatch_nonce == original_nonce


@pytest.mark.asyncio
async def test_prepare_attempt_commits_exact_identity_and_reuses_it(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=42,
        issue_title="attempt",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    calls = 0

    def fixed_nonce(size):
        nonlocal calls
        calls += 1
        assert size == 8
        return "0123456789abcdef"

    monkeypatch.setattr(
        "app.services.github_dispatch_service.secrets.token_hex", fixed_nonce
    )
    prepared = await github_dispatch_service.prepare_attempt(
        db,
        item,
        owner_slot_id=slots[1].id,
        routing_method="label",
        base_ref=scope.base_ref,
    )

    assert prepared.dispatch_head_ref == (
        f"deck/slot-{slots[1].id}/issue-42-0123456789abcdef"
    )
    assert calls == 1
    maker = async_sessionmaker(db.bind, expire_on_commit=False)
    async with maker() as second:
        persisted = await second.get(GithubWorkItem, item.id)
        assert persisted.owner_slot_id == slots[1].id
        assert persisted.routing_method == "label"
        assert persisted.dispatch_nonce == "0123456789abcdef"
        assert persisted.dispatch_head_ref == prepared.dispatch_head_ref
        assert persisted.approval_round_count == 1

    reused = await github_dispatch_service.prepare_attempt(
        db,
        item,
        owner_slot_id=slots[0].id,
        routing_method="leader_fallback",
        base_ref="origin/other",
    )
    assert reused == prepared
    assert calls == 1


@pytest.mark.asyncio
async def test_reset_for_retry_clears_ack_received_at(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=819,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        issue_type="code",
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        ack_approver_member_id=11,
        ack_evidence_message_id=12,
        ack_enforcement_epoch=1,
        ack_approval_round=2,
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref="deck/slot-1/issue-819-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=2,
        dispatched_at=datetime(2026, 7, 24, 17, 12, 0),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.reset_for_retry(db, item)

    assert item.ack_received_at is None
    assert item.ack_approver_member_id is None
    assert item.ack_evidence_message_id is None
    assert item.ack_enforcement_epoch is None
    assert item.ack_approval_round is None
    assert item.dispatch_nonce is None
    assert item.dispatch_head_ref is None


@pytest.mark.asyncio
async def test_reset_for_retry_defers_while_a_lease_is_held(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=909,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref="deck/slot-1/issue-909-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=1,
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    await db.commit()

    await github_dispatch_service.reset_for_retry(db, item)
    await db.commit()

    assert item.dispatch_status == "escalated"
    assert item.retry_requested_at is not None
    assert workspace.leased_item_id == item.id
    assert item.escalation_reason == "plan_blocked"
    assert item.dispatch_nonce == "0123456789abcdef"
    assert item.dispatch_head_ref == "deck/slot-1/issue-909-0123456789abcdef"


@pytest.mark.asyncio
async def test_reset_for_retry_without_a_lease_is_unchanged(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=910,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        ack_received_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.reset_for_retry(db, item)

    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None
    assert item.escalation_reason is None
    assert item.ack_received_at is None


@pytest.mark.asyncio
async def test_promote_deferred_retry_after_release(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=911,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        retry_requested_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    promoted = await github_dispatch_service.promote_deferred_retries(db, scope)

    assert promoted == 1
    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_promote_deferred_retry_waits_for_the_lease(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=912,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        retry_requested_at=datetime.utcnow(),
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    await db.commit()

    assert await github_dispatch_service.promote_deferred_retries(db, scope) == 0
    assert item.dispatch_status == "escalated"


@pytest.mark.asyncio
async def test_promote_deferred_retry_never_resets_released_pr_attempt(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=915,
        issue_title="preserved PR",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="retry_count_exhausted",
        retry_requested_at=datetime.utcnow(),
        pr_number=88,
        dispatch_nonce="preserved-nonce",
        retry_count=5,
        approval_round_count=2,
    )
    db.add(item)
    await db.commit()

    promoted = await github_dispatch_service.promote_deferred_retries(db, scope)

    assert promoted == 0
    assert item.dispatch_status == "escalated"
    assert item.retry_requested_at is not None
    assert item.pr_number == 88
    assert item.dispatch_nonce == "preserved-nonce"
    assert item.retry_count == 5
    assert item.approval_round_count == 2


@pytest.mark.asyncio
async def test_retry_does_not_overtake_release_end_to_end(db, monkeypatch):
    _, _, scope = await _team(db)
    resets: list[str] = []

    async def spy_reset(db_, scope_, workspace_):
        resets.append(workspace_.path)

    monkeypatch.setattr(github_workspace_service, "reset_workspace", spy_reset)

    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=913,
        issue_title="retry flow",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    workspace = await github_workspace_service.acquire(db, scope, item)
    first_token = workspace.lease_token
    assert first_token is not None
    assert resets == [workspace.path]

    item.dispatch_status = "escalated"
    item.escalation_reason = "plan_blocked"
    await db.commit()

    await github_dispatch_service.reset_for_retry(db, item)
    await db.commit()

    assert item.dispatch_status == "escalated"
    assert item.retry_requested_at is not None
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == first_token
    assert await github_dispatch_service.promote_deferred_retries(db, scope) == 0
    assert resets == [workspace.path]

    await github_workspace_service.release(db, item.id)
    assert await github_dispatch_service.promote_deferred_retries(db, scope) == 1
    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None

    reacquired = await github_workspace_service.acquire(db, scope, item)
    assert reacquired.lease_token != first_token
    assert len(resets) == 2


@pytest.mark.asyncio
async def test_deferred_retry_preserves_escalation_context_on_reescalation(db):
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=914,
        issue_title="retry context",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        status_note="original context",
    )
    db.add(item)
    await db.flush()
    workspace = (
        await db.execute(
            select(GithubWorkspace)
            .where(GithubWorkspace.scope_id == scope.id)
            .order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    workspace.leased_item_id = item.id
    await db.commit()

    await github_dispatch_service.reset_for_retry(db, item)
    deferred_note = item.status_note
    changed = github_dispatch_service._apply_escalation(
        item, "owner_offline", "replacement note"
    )

    assert item.escalation_reason == "plan_blocked"
    assert changed is False
    assert item.status_note == deferred_note


def test_ack_not_satisfied_by_ack_older_than_current_dispatch():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="dispatched",
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
    )

    assert github_dispatch_service._ack_satisfied(item) is False


def test_ack_satisfied_when_ack_follows_dispatch():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="dispatched",
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
        ack_received_at=datetime(2026, 7, 24, 18, 40, 0),
    )

    assert github_dispatch_service._ack_satisfied(item) is True


def test_pr_number_satisfies_ack_regardless_of_stale_ack():
    item = GithubWorkItem(
        scope_id=1,
        issue_number=819,
        issue_type="code",
        dispatch_status="dispatched",
        pr_number=865,
        ack_received_at=datetime(2026, 7, 24, 17, 30, 5),
        dispatched_at=datetime(2026, 7, 24, 18, 35, 56),
    )

    assert github_dispatch_service._ack_satisfied(item) is True


@pytest.mark.asyncio
async def test_dispatch_pending_stamps_dispatched_at(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=910,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 910
        items = []

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={910: [scope.dispatch_label, "area:backend"]},
        issue_details_by_number={910: {"body": "do the thing"}},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.dispatched_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("issue_labels", "issue_details", "queue_blocker"),
    [
        (["area:backend"], {911: {"body": "label removed"}}, "repo_cap"),
        (["area:backend"], {911: {"body": "label removed"}}, "low_memory"),
        ([], {}, "repo_cap"),
        ([], {}, "low_memory"),
    ],
)
async def test_dispatch_pending_escalates_when_dispatch_label_is_not_verified(
    db,
    monkeypatch,
    issue_labels,
    issue_details,
    queue_blocker,
):
    _, slots, scope = await _team(db)
    if queue_blocker == "repo_cap":
        scope.max_concurrent_dispatched = 0
    else:
        monkeypatch.setattr(
            github_dispatch_service,
            "_available_memory_mb",
            lambda: 0,
        )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=911,
        issue_title="stale pending item",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def unexpected_launcher(*_args, **_kwargs):
        raise AssertionError("an unverified pending item must not launch")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=unexpected_launcher,
        issue_labels_by_number={911: issue_labels},
        issue_details_by_number=issue_details,
    )

    await db.refresh(item)
    leased_workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one_or_none()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"
    assert leased_workspace is None


@pytest.mark.asyncio
async def test_dispatch_label_removal_preserves_and_warns_about_prepared_attempt(db):
    _, slots, scope = await _team(db)
    owner = slots[1]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=912,
        issue_title="prepared stale item",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.flush()
    workspace = await github_workspace_service.acquire(db, scope, item)
    await github_dispatch_service.prepare_attempt(
        db,
        item,
        owner_slot_id=owner.id,
        routing_method="label",
        base_ref="origin/master",
    )

    async def unexpected_launcher(*_args, **_kwargs):
        raise AssertionError("a prepared item without the dispatch label must not launch")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=unexpected_launcher,
        issue_labels_by_number={912: ["area:backend"]},
        issue_details_by_number={912: {"body": "label removed after preparation"}},
    )

    await db.refresh(item)
    await db.refresh(workspace)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"
    assert "pane may still be live" in item.status_note
    assert "Do NOT retry or release" in item.status_note
    assert workspace.leased_item_id == item.id


@pytest.mark.asyncio
async def test_ack_prompt_has_no_owner_side_timeout(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    leader_member = await _create_registered_slot_member(db, architect)
    instruction = github_dispatch_service._leader_ack_instruction(
        architect, leader_member, before="editing files"
    )
    assert "ack_received" in instruction
    assert "minute" not in instruction.lower()
    assert "give up" not in instruction.lower()


@pytest.mark.asyncio
async def test_report_ack_received_records_approved_leader_evidence(
    db, monkeypatch
):
    preset, slots, scope = await _team(db)
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    leader_member = await _create_registered_slot_member(db, slots[0])
    owner_member = await _create_registered_slot_member(db, slots[1])
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=911,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=datetime.utcnow(),
        last_nudge_at=datetime.utcnow(),
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{slots[1].id}/issue-911-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=1,
    )
    db.add(item)
    await db.flush()
    root = MailMessage(
        kind="context_request",
        sender_member_id=owner_member.id,
        recipient_member_id=leader_member.id,
        body_markdown="plan",
        payload={
            "work_item_id": item.id,
            "dispatch_nonce": item.dispatch_nonce,
            "approval_round": 1,
        },
        approval_round=1,
        request_status="answered",
    )
    db.add(root)
    await db.flush()
    approval = GithubApprovalRequest(
        work_item_id=item.id,
        request_kind="initial_plan",
        dispatch_nonce=item.dispatch_nonce,
        approval_round=1,
        owner_member_id=owner_member.id,
        leader_member_id=leader_member.id,
        request_message_id=root.id,
        request_fingerprint="approved-plan",
        status="approved",
        reason="approved",
        decided_at=datetime.utcnow(),
    )
    db.add(approval)
    await db.flush()
    answer = MailMessage(
        kind="answer",
        thread_root_id=root.id,
        sender_member_id=leader_member.id,
        body_markdown="approved",
        payload={"approval_request_id": approval.id},
        approval_round=1,
        decision="approved",
        delivery_key=f"github-approval:{approval.id}:decision",
        created_at=datetime.utcnow(),
    )
    later_answer = MailMessage(
        kind="answer",
        thread_root_id=root.id,
        sender_member_id=leader_member.id,
        body_markdown="approved again",
        approval_round=1,
        decision="approved",
        created_at=datetime.utcnow() + timedelta(seconds=1),
    )
    db.add_all([answer, later_answer])
    await db.flush()
    approval.decision_message_id = answer.id
    await db.commit()

    evidence = await github_dispatch_service.record_ack_received(db, item, scope)

    await db.refresh(item)
    assert evidence.ok is True
    assert item.ack_received_at is not None
    assert item.ack_approver_member_id == leader_member.id
    assert item.ack_evidence_message_id == answer.id
    assert item.ack_enforcement_epoch == 1
    assert item.ack_approval_round == 1
    assert item.last_nudge_at is None
    assert item.dispatch_status == "dispatched"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("self_ack", "self_ack"),
        ("non_leader", "not_designated_approver"),
        ("slotless", "not_designated_approver"),
        ("no_linkage", "no_linkage"),
        ("missing_round", "no_linkage"),
        ("stale_nonce", "stale_nonce"),
        ("null_item_nonce", "stale_nonce"),
        ("stale_round", "stale_round"),
        ("no_leader", "no_leader"),
        ("no_owner", "no_owner"),
        ("rejected", "rejected"),
        ("no_decision", "no_decision"),
        ("wrong_delivery_key", "no_decision"),
    ],
)
async def test_ack_evidence_refusal_matrix(
    db, monkeypatch, case, expected_reason
):
    _preset, slots, scope = await _team(db)
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)
    leader_member = (
        None
        if case == "no_leader"
        else await _create_registered_slot_member(db, slots[0])
    )
    if case == "self_ack":
        owner_slot = slots[0]
        owner_member = leader_member
    else:
        owner_slot = slots[1]
        owner_member = (
            None
            if case == "no_owner"
            else await _create_registered_slot_member(db, owner_slot)
        )
    item_round = 2 if case == "stale_round" else 1
    item_nonce = None if case == "null_item_nonce" else "0123456789abcdef"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=912,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=owner_slot.id,
        dispatched_at=datetime.utcnow(),
        dispatch_nonce=item_nonce,
        dispatch_head_ref=f"deck/slot-{owner_slot.id}/issue-912-head",
        dispatch_base_ref="origin/master",
        approval_round_count=item_round,
    )
    db.add(item)
    await db.flush()

    root = None
    approval = None
    if case not in {"self_ack", "no_linkage", "no_leader", "no_owner"}:
        payload = {
            "work_item_id": item.id,
            "dispatch_nonce": item_nonce,
            "approval_round": item_round,
        }
        if case == "missing_round":
            payload.pop("approval_round")
        elif case == "stale_nonce":
            payload["dispatch_nonce"] = "previous-attempt"
        elif case == "null_item_nonce":
            payload["dispatch_nonce"] = None
        elif case == "stale_round":
            payload["approval_round"] = 1
        root = MailMessage(
            kind="context_request",
            sender_member_id=owner_member.id,
            recipient_member_id=leader_member.id,
            body_markdown="plan",
            payload=payload,
            approval_round=payload.get("approval_round"),
            request_status="answered",
        )
        db.add(root)
        await db.flush()

    answer = None
    if case in {
        "non_leader",
        "slotless",
        "rejected",
        "no_decision",
        "wrong_delivery_key",
    }:
        sender = leader_member
        decision = "approved"
        if case == "non_leader":
            sender = owner_member
        elif case == "slotless":
            sender = MailTeamMember(
                identity_key="repo:slotless-reviewer",
                repo_id="r",
                repo_path="/tmp/r",
                repo_name="r",
                display_name="Slotless",
                participant_kind="repo",
            )
            db.add(sender)
            await db.flush()
        elif case == "rejected":
            decision = "rejected"
        elif case == "no_decision":
            decision = None
        if decision is not None:
            answer = MailMessage(
                kind="answer",
                thread_root_id=root.id,
                sender_member_id=sender.id,
                body_markdown="review",
                approval_round=item_round,
                decision=decision,
            )
            db.add(answer)
            await db.flush()
    if case not in {
        "self_ack",
        "no_linkage",
        "missing_round",
        "no_leader",
        "no_owner",
    }:
        request_nonce = (
            "previous-attempt"
            if case in {"stale_nonce", "null_item_nonce"}
            else item_nonce
        )
        request_round = 1 if case == "stale_round" else item_round
        request_status = (
            "rejected"
            if case == "rejected"
            else "approved"
            if case in {"non_leader", "slotless", "wrong_delivery_key"}
            else "pending"
        )
        approval = GithubApprovalRequest(
            work_item_id=item.id,
            request_kind="initial_plan",
            dispatch_nonce=request_nonce,
            approval_round=request_round,
            owner_member_id=owner_member.id,
            leader_member_id=leader_member.id,
            request_message_id=root.id,
            decision_message_id=answer.id if answer is not None else None,
            request_fingerprint=f"case:{case}",
            status=request_status,
            reason="review" if request_status != "pending" else None,
            decided_at=(
                datetime.utcnow() if request_status != "pending" else None
            ),
        )
        db.add(approval)
    await db.commit()

    evidence = await github_dispatch_service.record_ack_received(db, item, scope)

    assert evidence.ok is False
    assert evidence.reason == expected_reason
    stored = (
        await db.execute(
            text(
                "SELECT ack_received_at, ack_approver_member_id, "
                "ack_evidence_message_id, ack_enforcement_epoch, "
                "ack_approval_round FROM github_work_items WHERE id = :id"
            ),
            {"id": item.id},
        )
    ).one()
    assert tuple(stored) == (None, None, None, None, None)


@pytest.mark.asyncio
async def test_slot_member_resolution_uses_id_as_timestamp_tiebreak(db):
    preset, slots, _scope = await _team(db)
    tied_at = datetime.utcnow()
    older = MailTeamMember(
        identity_key="slot:tied:older",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Older",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
        updated_at=tied_at,
    )
    current = MailTeamMember(
        identity_key="slot:tied:current",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Current",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
        updated_at=tied_at,
    )
    db.add_all([older, current])
    await db.commit()

    resolved = await github_dispatch_service._slot_member(db, slots[1].id)

    assert current.id > older.id
    assert resolved.id == current.id


@pytest.mark.asyncio
async def test_route_by_label_match(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    owner_id, method = await github_dispatch_service.route_item(
        db,
        item,
        slots,
        issue_labels=["area:backend"],
    )
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    assert owner_id == backend.id
    assert method == "label"


@pytest.mark.asyncio
async def test_route_classification_fallback(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=2,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")

    async def fake_classify(it, candidate_slots):
        return backend.id

    owner_id, method = await github_dispatch_service.route_item(
        db,
        item,
        slots,
        issue_labels=["no-area-label"],
        classify=fake_classify,
    )
    assert owner_id == backend.id
    assert method == "classified"


@pytest.mark.asyncio
async def test_route_leader_fallback_when_no_expertise(db):
    preset, slots, scope = await _team(db)
    for slot in slots:
        slot.expertise = None
    await db.commit()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=3,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    owner_id, method = await github_dispatch_service.route_item(db, item, slots, ["nothing"])
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    assert owner_id == architect.id
    assert method == "leader_fallback"


@pytest.mark.asyncio
async def test_slot_busy_when_dispatched_item_exists(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=10,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=backend.id,
        )
    )
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is True


@pytest.mark.asyncio
async def test_slot_free_when_only_awaiting_human_review(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=11,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="awaiting_human_review",
            owner_slot_id=backend.id,
        )
    )
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is False


@pytest.mark.asyncio
async def test_slot_busy_during_pending_handoff_on_both_sides(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=12,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=architect.id,
            handoff_state="pending",
            handoff_target_slot_id=backend.id,
        )
    )
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, architect.id) is True
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is True


@pytest.mark.asyncio
async def test_dispatch_pending_launches_and_marks_dispatched(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=20,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 99

    async def fake_launcher(db_, preset_id, request):
        launched["preset_id"] = preset_id
        launched["override"] = request.repo_path_override
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        classify=None,
        launcher=fake_launcher,
        issue_labels_by_number={20: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id
    assert item.routing_method == "label"
    assert item.launch_id == 99
    assert item.pending_reason is None
    assert launched["override"] == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_dispatch_captures_pane_pid_from_launch_result(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=201,
        issue_title="Capture pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:1.0"
        pane_pid = 4242

    class _Result:
        launch_id = 201
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(github_workspace_service, "_read_proc_start", lambda _pid: "9001")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={201: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert item.dispatch_status == "dispatched"
    assert workspace.leased_owner_pid == 4242
    assert workspace.leased_owner_proc_start == "9001"


@pytest.mark.asyncio
async def test_dispatch_resolves_pane_pid_from_tmux_target(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=202,
        issue_title="Resolve pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:2.0"
        pane_pid = None

    class _Result:
        launch_id = 202
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(github_dispatch_service, "_resolve_pane_pid", lambda _target: 5252)
    monkeypatch.setattr(github_workspace_service, "_read_proc_start", lambda _pid: "9002")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={202: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert workspace.leased_owner_pid == 5252
    assert workspace.leased_owner_proc_start == "9002"


@pytest.mark.asyncio
async def test_dispatch_without_resolvable_pane_pid_still_dispatches(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=203,
        issue_title="Missing pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:3.0"
        pane_pid = None

    class _Result:
        launch_id = 203
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(github_dispatch_service, "_resolve_pane_pid", lambda _target: None)

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={203: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert item.dispatch_status == "dispatched"
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None


@pytest.mark.asyncio
async def test_dispatch_keeps_pid_pair_null_when_proc_start_is_unreadable(db, monkeypatch):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=204,
        issue_title="Unreadable pid",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "pending_registration"
        tmux_target = "deck:4.0"
        pane_pid = 6262

    class _Result:
        launch_id = 204
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    def unreadable(_pid):
        raise PermissionError("denied")

    monkeypatch.setattr(github_workspace_service, "_read_proc_start", unreadable)

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={204: ["area:backend"]},
    )

    workspace = (
        await db.execute(select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id))
    ).scalar_one()
    assert item.dispatch_status == "dispatched"
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None


@pytest.mark.asyncio
async def test_dispatch_pending_passes_issue_specific_owner_brief(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    nudge_prompts = []

    async def capture_nudge_prompt(_db, _member_ids, **kwargs):
        nudge_prompts.append(kwargs.get("nudge_prompt"))
        return []

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", capture_nudge_prompt)
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    leader_member = await _create_registered_slot_member(db, architect)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=833,
        issue_title="Add agent docs",
        issue_url="https://github.com/o/r/issues/833",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
        brief_delivery_nudge_at=datetime.utcnow(),
        brief_delivery_nudge_count=2,
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 833

    async def fake_launcher(db_, preset_id, request):
        launched["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={833: [scope.dispatch_label, "area:backend"]},
        issue_details_by_number={
            833: {
                "body": "Acceptance criteria and verification steps.",
                "labels": [
                    {"name": "area:backend"},
                    {"name": scope.dispatch_label},
                ],
            }
        },
    )

    prompt = launched["request"].slot_prompt_overrides[backend.id]
    assert "autonomous GitHub dispatch" in prompt
    assert "Work item ID:" in prompt
    assert "Issue: #833 — Add agent docs" in prompt
    assert "https://github.com/o/r/issues/833" in prompt
    assert "Acceptance criteria and verification steps." in prompt
    assert "deck_report_dispatch_status" in prompt
    assert "deck_request_work_item_approval" in prompt
    assert f"Agent Mail member_id={leader_member.id}" in prompt
    assert f"work_item_id={item.id}" in prompt
    assert f"slot_id={architect.id}" not in prompt
    assert f"to_member_id={architect.id}" not in prompt
    assert "wait for the explicit decision before starting implementation" in prompt
    assert "A prose reply is not approval" in prompt
    assert "deck_approve_work_item" in prompt
    assert "open a draft PR" in prompt
    assert "Workspace: /tmp/r-ws-1" in prompt
    assert "leased exclusively" in prompt
    assert "Do NOT create, move or remove git worktrees" in prompt

    member = (
        await db.execute(select(MailTeamMember).where(MailTeamMember.team_slot_id == backend.id))
    ).scalar_one()
    message = (
        await db.execute(
            select(MailMessage).where(MailMessage.recipient_member_id == member.id)
        )
    ).scalar_one()
    assert message.subject == "Autonomous dispatch: issue #833"
    assert "Issue: #833 — Add agent docs" in message.body_markdown
    assert "Acceptance criteria and verification steps." in message.body_markdown
    assert f"Agent Mail member_id={leader_member.id}" in message.body_markdown
    assert f"work_item_id={item.id}" in message.body_markdown
    assert f"slot_id={architect.id}" not in message.body_markdown
    assert "wait for the explicit decision before starting implementation" in message.body_markdown
    assert item.brief_message_id == message.id
    assert item.brief_delivery_nudge_at is None
    assert item.brief_delivery_nudge_count is None
    assert len(nudge_prompts) == 1
    assert f"work item {item.id}" in nudge_prompts[0]
    assert "issue #833" in nudge_prompts[0]
    assert "execute that assignment now" in nudge_prompts[0]


@pytest.mark.asyncio
async def test_every_report_instruction_carries_the_lease_token(db):
    _, slots, scope = await _team(db)
    workspace = (
        await db.execute(select(GithubWorkspace).order_by(GithubWorkspace.id))
    ).scalars().first()
    workspace.lease_token = "tok-brief"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=94,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
    )
    db.add(item)
    await db.commit()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    call_lines = [
        line
        for line in brief.splitlines()
        if "deck_report_dispatch_status(work_item_id=" in line
    ]
    assert len(call_lines) >= 4
    for line in call_lines:
        assert 'lease_token="tok-brief"' in line, f"missing token: {line}"


@pytest.mark.asyncio
async def test_app_brief_uses_persisted_head_and_deck_owned_pr_contract(db):
    _, slots, scope = await _team(db)
    scope.github_auth_mode = "app"
    workspace = (
        await db.execute(select(GithubWorkspace).order_by(GithubWorkspace.id))
    ).scalars().first()
    workspace.lease_token = "tok-app-brief"
    owner = slots[1]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=95,
        issue_title="App PR",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=owner.id,
        dispatch_head_ref=f"deck/slot-{owner.id}/issue-95-persisted",
        dispatch_base_ref="origin/master",
    )
    db.add(item)
    await db.commit()
    scope.base_ref = "origin/release"
    await db.commit()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=owner.id,
        preset_slots=slots,
    )

    assert item.dispatch_head_ref in brief
    assert "detached HEAD at origin/master" in brief
    assert "detached HEAD at origin/release" not in brief
    assert f"Deck-Agent-Slot: {owner.id} ({owner.display_name})" in brief
    assert f"Deck-Work-Item: {item.id}" in brief
    assert f"git push -u origin {item.dispatch_head_ref}" in brief
    assert f'head_ref="{item.dispatch_head_ref}"' in brief
    assert 'status="pr_ready"' in brief
    assert "pr_opened" not in brief
    assert "Deck owns the PR title and body" in brief


@pytest.mark.asyncio
async def test_design_dispatch_brief_uses_design_pipeline_language(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    leader_member = await _create_registered_slot_member(db, architect)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=835,
        issue_title="Write design note",
        issue_url="https://github.com/o/r/issues/835",
        github_updated_at=datetime.utcnow(),
        issue_type="design",
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 835

    async def fake_launcher(db_, preset_id, request):
        launched["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={835: [scope.dispatch_label, "area:backend"]},
        issue_details_by_number={835: {"body": "Capture design rationale."}},
    )

    prompt = launched["request"].slot_prompt_overrides[backend.id]
    assert "Pipeline: design" in prompt
    assert "Design pipeline instructions" in prompt
    assert "do not rely on CI or auto-merge" in prompt
    assert "human-reviewed PR" in prompt
    assert f"Agent Mail member_id={leader_member.id}" in prompt
    assert f"work_item_id={item.id}" in prompt
    assert f"slot_id={architect.id}" not in prompt


@pytest.mark.asyncio
async def test_dispatch_brief_uses_discovery_when_leader_member_missing(db):
    preset, slots, scope = await _team(db)
    architect = next(slot for slot in slots if slot.display_name == "Architect")
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=837,
        issue_title="Small docs follow-up",
        issue_url="https://github.com/o/r/issues/837",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 837

    async def fake_launcher(db_, preset_id, request):
        launched["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={837: [scope.dispatch_label, "area:backend"]},
        issue_details_by_number={837: {"body": "Tiny docs follow-up."}},
    )

    prompt = launched["request"].slot_prompt_overrides[backend.id]
    assert "Team leader / approver: Architect" in prompt
    assert "Leader Agent Mail member is not registered yet" in prompt
    assert "derives the current designated Leader server-side" in prompt
    assert "do not guess or supply a member id" in prompt
    assert f"slot_id={architect.id}" not in prompt
    assert f"to_member_id={architect.id}" not in prompt


@pytest.mark.asyncio
async def test_dispatch_pending_reuses_and_still_passes_the_repo_override(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=23,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    launched = {}

    class _Result:
        launch_id = 100

    async def fake_launcher(db_, preset_id, request):
        launched["reuse_existing"] = request.reuse_existing
        launched["override"] = request.repo_path_override
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient([]),
        launcher=fake_launcher,
        issue_labels_by_number={23: []},
    )

    assert launched["reuse_existing"] is True
    assert launched["override"] == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_dispatch_pending_queues_same_batch_items_for_same_slot(db):
    preset, slots, scope = await _team(db)
    first = GithubWorkItem(
        scope_id=scope.id,
        issue_number=24,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    second = GithubWorkItem(
        scope_id=scope.id,
        issue_number=25,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add_all([first, second])
    await db.commit()
    launches = []

    class _Result:
        launch_id = 101

    async def fake_launcher(db_, preset_id, request):
        launches.append(request.slot_ids[0])
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher,
        issue_labels_by_number={24: ["area:backend"], 25: ["area:backend"]},
    )
    await db.refresh(first)
    await db.refresh(second)
    assert len(launches) == 1
    assert first.dispatch_status == "dispatched"
    assert second.dispatch_status == "pending"
    assert second.pending_reason == "queued_slot_busy"


@pytest.mark.asyncio
async def test_dispatch_pending_commits_success_before_later_plan_block(db):
    preset, slots, scope = await _team(db)
    first = GithubWorkItem(
        scope_id=scope.id,
        issue_number=26,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    second = GithubWorkItem(
        scope_id=scope.id,
        issue_number=27,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add_all([first, second])
    await db.commit()
    calls = 0

    class _Result:
        launch_id = 102

    async def fake_launcher(db_, preset_id, request):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("plan is blocked")
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher,
        issue_labels_by_number={26: [], 27: ["area:backend"]},
    )
    await db.refresh(first)
    await db.refresh(second)
    assert first.dispatch_status == "dispatched"
    assert second.dispatch_status == "escalated"
    assert second.escalation_reason == "plan_blocked"


@pytest.mark.asyncio
async def test_escalate_sets_reason_for_active_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=62,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.escalate(db, item, "plan_blocked", "needs a human plan")

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    assert item.status_note == "needs a human plan"


@pytest.mark.asyncio
async def test_escalation_broadcast_flags_active_owner(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=65,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.escalate(db, item, "owner_idle_timeout")

    message = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.kind == "broadcast",
                MailMessage.payload["kind"].as_string() == "github_dispatch_escalation",
            )
        )
    ).scalar_one()
    assert message.payload["owner_may_be_active"] is True
    assert "Do NOT retry" in message.body_markdown


@pytest.mark.asyncio
async def test_escalation_broadcast_no_active_owner_for_pending_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=66,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.escalate(db, item, "plan_blocked")

    message = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.kind == "broadcast",
                MailMessage.payload["kind"].as_string() == "github_dispatch_escalation",
            )
        )
    ).scalar_one()
    assert message.payload["owner_may_be_active"] is False


@pytest.mark.asyncio
async def test_escalate_preserves_first_reason_for_already_escalated_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=63,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="dispatch_label_removed",
        status_note="The dispatch label was removed.",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    message_count = len((await db.execute(select(MailMessage))).scalars().all())

    await github_dispatch_service.escalate(db, item, "plan_blocked", "owner also blocked")

    await db.refresh(item)
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"
    assert item.status_note == "The dispatch label was removed."
    assert len(messages) == message_count


@pytest.mark.asyncio
async def test_escalate_same_reason_is_idempotent_for_already_escalated_item(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=64,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="owner_offline",
        status_note="Owner heartbeat expired.",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    message_count = len((await db.execute(select(MailMessage))).scalars().all())

    await github_dispatch_service.escalate(db, item, "owner_offline", "duplicate poll")

    await db.refresh(item)
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_offline"
    assert item.status_note == "Owner heartbeat expired."
    assert len(messages) == message_count


@pytest.mark.asyncio
async def test_dispatch_pending_marks_failed_launch_result_failed(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=28,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Item:
        status = "failed"
        error = "spawn failed"

    class _Result:
        launch_id = 103
        status = "completed_with_errors"
        items = [_Item()]

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient([]),
        launcher=fake_launcher,
        issue_labels_by_number={28: []},
    )
    await db.refresh(item)
    assert item.dispatch_status == "failed"
    assert item.launch_id == 103


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_slot_busy(db):
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=21,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=backend.id,
        )
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=22,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("should not launch a busy slot")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher,
        issue_labels_by_number={22: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_slot_busy"


@pytest.mark.asyncio
async def test_dispatch_proceeds_with_only_standing_session(db, monkeypatch):
    async def keep_synthetic_session(_db, *, strict=False):
        return None

    monkeypatch.setattr(agent_mail_service, "sync_observed_sessions", keep_synthetic_session)
    monkeypatch.setattr(
        agent_mail_service,
        "_send_tmux_inbox_check",
        lambda session, nudge_prompt="check inbox": {
            "target": session.tmux_target,
            "prompt": nudge_prompt,
        },
    )
    preset, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    _, standing_session = await _create_live_slot_launch_session(
        db,
        preset,
        backend,
        target="standing:0.0",
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=42,
        issue_title="new work",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    launches = []

    class _Result:
        launch_id = 104

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={42: ["area:backend"]},
    )

    await db.refresh(item)
    assert len(launches) == 1
    assert launches[0].reuse_existing is True
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id
    assert item.pending_reason is None
    receipts = (
        await db.execute(
            select(MailReceipt).where(
                MailReceipt.member_id == standing_session.member_id
            )
        )
    ).scalars().all()
    assert len(receipts) == 1
    sessions = (
        await db.execute(
            select(MailAgentSession).where(MailAgentSession.team_slot_id == backend.id)
        )
    ).scalars().all()
    assert len(sessions) == 1


@pytest.mark.asyncio
async def test_dispatch_without_wakeable_session_keeps_issue_brief_for_spawn(db):
    _, slots, scope = await _team(db)
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=43,
        issue_title="spawn fallback",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    launches = []

    class _Result:
        launch_id = 105

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={43: ["area:backend"]},
    )

    assert len(launches) == 1
    prompt = launches[0].slot_prompt_overrides[backend.id]
    assert "Issue: #43 — spawn fallback" in prompt
    assert "Workspace: /tmp/r-ws-1" in prompt


@pytest.mark.asyncio
async def test_ambiguous_slot_blocks_and_leases_nothing(db, monkeypatch):
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _seed_observed_panes(
        db,
        preset,
        owner,
        [("%1", "w:0.1"), ("%2", "w:0.2")],
    )
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [
            _pane(pane_id="%1", target="w:0.1", cwd=owner.repo_path),
            _pane(pane_id="%2", target="w:0.2", cwd=owner.repo_path),
        ],
    )
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, owner.id)) == 2
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=950,
        issue_title="ambiguous",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=_launcher_that_must_not_run,
        issue_labels_by_number={950: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.owner_slot_id == owner.id
    assert item.pending_reason == "queued_ambiguous_sessions"
    assert "w:0.1" in item.status_note and "w:0.2" in item.status_note
    leased = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalars().all()
    assert leased == []


@pytest.mark.asyncio
async def test_ambiguous_check_resyncs_before_counting(db, monkeypatch):
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    member = await _seed_observed_panes(db, preset, owner, [("%1", "w:0.1")])
    db.add(
        MailAgentSession(
            member_id=member.id,
            provider=owner.provider,
            source="hook",
            session_key="hook:owner",
            cwd=owner.repo_path,
            pid=4242,
            team_preset_id=preset.id,
            team_slot_id=owner.id,
            mailbox_status="connected",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, owner.id)) == 1
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [
            _pane(pane_id="%1", target="w:0.1", cwd=owner.repo_path),
            _pane(pane_id="%2", target="w:0.2", cwd=owner.repo_path),
        ],
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=951,
        issue_title="fresh ambiguity",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=_launcher_that_must_not_run,
        issue_labels_by_number={951: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.pending_reason == "queued_ambiguous_sessions"
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, owner.id)) == 2


@pytest.mark.asyncio
async def test_ambiguous_check_holds_when_discovery_loses_known_session(db, monkeypatch):
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _seed_observed_panes(db, preset, owner, [("%1", "w:0.1")])
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [],
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=952,
        issue_title="lost pane",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=_launcher_that_must_not_run,
        issue_labels_by_number={952: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.pending_reason == "queued_ambiguous_sessions"
    leased = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalars().all()
    assert leased == []


@pytest.mark.asyncio
async def test_ambiguity_gate_is_stable_when_discovery_blips(db, monkeypatch):
    """Two consecutive failed discoveries must not become permission to dispatch."""
    preset, slots, scope = await _team(db)
    slot = slots[0]
    member = await agent_mail_service.get_or_create_slot_member(db, slot)
    db.add(
        MailAgentSession(
            member_id=member.id,
            team_preset_id=slot.preset_id,
            team_slot_id=slot.id,
            source="observed",
            provider=slot.provider,
            session_key="tmux:%1",
            pane_id="%1",
            tmux_target="live:0.0",
            cwd=slot.repo_path,
            pid=os.getpid(),
            mailbox_status="observed",
            last_seen_at=datetime.utcnow(),
        )
    )
    await db.commit()

    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions", lambda: []
    )

    first = await github_dispatch_service._session_ambiguity_note(db, slot.id)
    second = await github_dispatch_service._session_ambiguity_note(db, slot.id)

    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, slot.id)) == 1
    assert first is None
    assert second == first


@pytest.mark.asyncio
async def test_ambiguous_check_holds_when_discovery_raises(db, monkeypatch):
    """strict=True converts a discovery exception into a hold, not a dispatch."""
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _seed_observed_panes(db, preset, owner, [("%1", "w:0.1")])

    def raises_like_a_failed_fork():
        raise OSError(12, "Cannot allocate memory")

    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        raises_like_a_failed_fork,
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=954,
        issue_title="discovery exploded",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=_launcher_that_must_not_run,
        issue_labels_by_number={954: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.pending_reason == "queued_ambiguous_sessions"
    assert len(await agent_mail_service.nudgeable_sessions_for_slot(db, owner.id)) == 1


@pytest.mark.asyncio
async def test_ambiguous_check_allows_one_nudgeable_pane(db, monkeypatch):
    preset, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    await _seed_observed_panes(db, preset, owner, [("%1", "w:0.1")])
    monkeypatch.setattr(
        "app.services.agent_mail_service.discover_agent_sessions",
        lambda: [_pane(pane_id="%1", target="w:0.1", cwd=owner.repo_path)],
    )
    monkeypatch.setattr(
        agent_mail_service,
        "_send_tmux_inbox_check",
        lambda session, nudge_prompt="check inbox": {
            "target": session.tmux_target,
            "prompt": nudge_prompt,
        },
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=953,
        issue_title="one pane",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 953

    async def successful_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=successful_launcher,
        issue_labels_by_number={953: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_ambiguous_check_allows_empty_slot_to_spawn(db):
    _, slots, scope = await _team(db)
    owner = next(slot for slot in slots if slot.display_name == "Backend SME")
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=954,
        issue_title="empty slot",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 954

    async def successful_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=successful_launcher,
        issue_labels_by_number={954: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.owner_slot_id == owner.id
    assert item.dispatch_status == "dispatched"
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_scope_concurrency_cap_reached(db):
    preset, slots, scope = await _team(db)
    scope.max_concurrent_dispatched = 1
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add(
        GithubWorkItem(
            scope_id=scope.id,
            issue_number=29,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=slots[0].id,
        )
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=31,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("repo cap should queue before launch")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={31: ["area:backend"]},
    )
    await db.refresh(item)
    assert backend.id != slots[0].id
    assert item.owner_slot_id is None
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_repo_cap"


def test_available_memory_mb_reads_memavailable(monkeypatch):
    meminfo = "MemTotal:       16384000 kB\nMemAvailable:    6144000 kB\n"
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: StringIO(meminfo))

    assert GithubDispatchService()._available_memory_mb() == 6000


@pytest.mark.asyncio
async def test_dispatch_queues_when_available_memory_below_floor(db, monkeypatch):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=45,
        issue_title="memory-heavy work",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 2999)

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("should not launch below the memory floor")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={45: ["area:backend"]},
    )

    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_low_memory"


@pytest.mark.asyncio
async def test_dispatch_proceeds_when_available_memory_above_floor(db, monkeypatch):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=46,
        issue_title="memory-safe work",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: 3001)
    launches = []

    class _Result:
        launch_id = 106

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={46: ["area:backend"]},
    )

    await db.refresh(item)
    assert len(launches) == 1
    assert item.dispatch_status == "dispatched"
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_dispatch_fails_open_when_available_memory_unknown(db, monkeypatch):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=47,
        issue_title="portable dispatch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()
    monkeypatch.setattr(github_dispatch_service, "_available_memory_mb", lambda: None)
    launches = []

    class _Result:
        launch_id = 107

    async def fake_launcher(db_, preset_id, request):
        launches.append(request)
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={47: ["area:backend"]},
    )

    await db.refresh(item)
    assert len(launches) == 1
    assert item.dispatch_status == "dispatched"
    assert item.pending_reason is None


@pytest.mark.asyncio
async def test_scope_concurrency_ignores_human_review_and_escalated_items(db):
    preset, slots, scope = await _team(db)
    scope.max_concurrent_dispatched = 1
    backend = next(slot for slot in slots if slot.display_name == "Backend SME")
    db.add_all(
        [
            GithubWorkItem(
                scope_id=scope.id,
                issue_number=32,
                issue_title="x",
                issue_url="u",
                github_updated_at=datetime.utcnow(),
                dispatch_status="awaiting_human_review",
                owner_slot_id=backend.id,
            ),
            GithubWorkItem(
                scope_id=scope.id,
                issue_number=33,
                issue_title="x",
                issue_url="u",
                github_updated_at=datetime.utcnow(),
                dispatch_status="ready_for_review",
                owner_slot_id=backend.id,
            ),
            GithubWorkItem(
                scope_id=scope.id,
                issue_number=34,
                issue_title="x",
                issue_url="u",
                github_updated_at=datetime.utcnow(),
                dispatch_status="escalated",
                owner_slot_id=backend.id,
            ),
        ]
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=35,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _Result:
        launch_id = 104

    async def fake_launcher(db_, preset_id, request):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={35: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id


@pytest.mark.asyncio
async def test_approval_round_cap_escalates(db, monkeypatch):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 3
    owner = MailTeamMember(
        identity_key="slot:approval-owner",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
    )
    db.add(owner)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=30,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatch_nonce="approval-round-nonce",
        approval_round_count=1,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.apply_approval_decision(
        db,
        item,
        scope,
        decision="rejected",
        approval_round=1,
        dispatch_nonce=item.dispatch_nonce,
        owner_member_id=owner.id,
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.approval_round_count == 2
    await github_dispatch_service.apply_approval_decision(
        db,
        item,
        scope,
        decision="rejected",
        approval_round=2,
        dispatch_nonce=item.dispatch_nonce,
        owner_member_id=owner.id,
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.approval_round_count == 3
    await github_dispatch_service.apply_approval_decision(
        db,
        item,
        scope,
        decision="rejected",
        approval_round=3,
        dispatch_nonce=item.dispatch_nonce,
        owner_member_id=owner.id,
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "approval_rounds_exhausted"
    assert item.approval_round_count == 3


@pytest.mark.asyncio
async def test_escalation_creates_agent_mail_broadcast(db, monkeypatch):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 1
    owner = MailTeamMember(
        identity_key="slot:approval-owner-broadcast",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
    )
    db.add_all(
        [
            owner,
            MailTeamMember(
            identity_key="slot:1",
            repo_id="r",
            repo_path="/tmp/r",
            repo_name="r",
            display_name="Architect",
            participant_kind="team_slot",
            team_preset_id=preset.id,
            team_slot_id=slots[0].id,
            ),
        ]
    )
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=36,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatch_nonce="approval-broadcast-nonce",
        approval_round_count=1,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.apply_approval_decision(
        db,
        item,
        scope,
        decision="rejected",
        approval_round=1,
        dispatch_nonce=item.dispatch_nonce,
        owner_member_id=owner.id,
    )

    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any(message.kind == "broadcast" for message in messages)
    assert any("approval_rounds_exhausted" in (message.subject or "") for message in messages)


@pytest.mark.asyncio
async def test_escalation_state_persists_when_notification_fails(db, monkeypatch):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 1
    owner = MailTeamMember(
        identity_key="slot:approval-owner-failure",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
    )
    db.add(owner)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=37,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatch_nonce="approval-failure-nonce",
        approval_round_count=1,
    )
    db.add(item)
    await db.commit()

    async def fail_broadcast(
        db_, item_, reason, note, *, owner_may_be_active=False
    ):
        raise RuntimeError("mail down")

    monkeypatch.setattr(
        github_dispatch_service,
        "_send_escalation_broadcast",
        fail_broadcast,
    )

    await github_dispatch_service.apply_approval_decision(
        db,
        item,
        scope,
        decision="rejected",
        approval_round=1,
        dispatch_nonce=item.dispatch_nonce,
        owner_member_id=owner.id,
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "approval_rounds_exhausted"


@pytest.mark.asyncio
async def test_two_phase_handoff(db, monkeypatch):
    config_calls = []
    revoked = []

    async def config_runner(args):
        config_calls.append(args)
        return 0, ""

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)

    async def revoke(scope, workspace, *, owner_slot_id):
        revoked.append((workspace.lease_token, owner_slot_id))
        return True

    monkeypatch.setattr(github_workspace_service, "revoke_push_token", revoke)
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=40,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=architect.id,
        routing_method="label",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{architect.id}/issue-40-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=2,
        ack_received_at=datetime.utcnow(),
        ack_approver_member_id=55,
        ack_evidence_message_id=56,
        ack_enforcement_epoch=1,
        ack_approval_round=2,
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/handoff-workspace",
        leased_item_id=item.id,
        lease_token="lease-kept",
        leased_owner_pid=101,
        leased_owner_proc_start="1001",
    )
    db.add(workspace)
    await db.commit()

    await github_dispatch_service.initiate_handoff(
        db,
        item,
        scope,
        initiating_slot_id=architect.id,
        target_slot_id=backend.id,
    )
    await db.refresh(item)
    assert item.handoff_state == "pending"
    assert item.handoff_target_slot_id == backend.id
    assert item.owner_slot_id == architect.id

    with pytest.raises(ValueError):
        await github_dispatch_service.accept_handoff(
            db,
            item,
            architect.id,
            accepting_pane_pid=101,
            accepting_pane_proc_start="1001",
        )

    await github_dispatch_service.accept_handoff(
        db,
        item,
        backend.id,
        accepting_pane_pid=202,
        accepting_pane_proc_start="2002",
    )
    await db.refresh(item)
    assert item.owner_slot_id == backend.id
    assert item.handoff_state == "accepted"
    assert item.handoff_target_slot_id is None
    assert item.routing_method == "reassigned"
    assert item.dispatch_nonce == "0123456789abcdef"
    assert item.dispatch_head_ref.endswith("0123456789abcdef")
    assert item.approval_round_count == 2
    assert item.ack_received_at is None
    assert item.ack_approver_member_id is None
    assert item.ack_evidence_message_id is None
    assert item.ack_enforcement_epoch is None
    assert item.ack_approval_round is None
    await db.refresh(workspace)
    assert workspace.lease_token == "lease-kept"
    assert workspace.leased_owner_pid == 202
    assert workspace.leased_owner_proc_start == "2002"
    assert workspace.lease_last_owner_contact_at is not None
    assert revoked == [("lease-kept", architect.id)]
    assert any(
        call[-2:] == ["user.name", "Backend SME (Deck agent)"]
        for call in config_calls
    )
    target_member = (
        await db.execute(
            select(MailTeamMember).where(MailTeamMember.team_slot_id == backend.id)
        )
    ).scalar_one()
    handoff_message = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.recipient_member_id == target_member.id,
                MailMessage.subject.like("GitHub dispatch handoff:%"),
            )
        )
    ).scalar_one()
    assert "Do not work" in handoff_message.body_markdown
    assert "wait for a 200 response" in handoff_message.body_markdown


@pytest.mark.asyncio
async def test_handoff_supersedes_active_continuation_and_requires_fresh_scope(
    db, monkeypatch
):
    async def config_runner(_args):
        return 0, ""

    async def revoke(*_args, **_kwargs):
        return True

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    monkeypatch.setattr(github_workspace_service, "revoke_push_token", revoke)
    _preset, slots, scope = await _team(db)
    old_owner, target = slots[:2]
    item, workspace, revision, _member = await _active_continuation(
        db,
        scope,
        old_owner,
        issue_number=45,
        activated_at=datetime.utcnow(),
        owner_contact_at=datetime.utcnow(),
    )
    item.handoff_state = "pending"
    item.handoff_target_slot_id = target.id
    await db.commit()

    await github_dispatch_service.accept_handoff(
        db,
        item,
        target.id,
        accepting_pane_pid=202,
        accepting_pane_proc_start="2002",
    )

    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    assert item.owner_slot_id == target.id
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert item.active_scope_revision == 1
    assert item.pr_number == 45
    assert item.dispatch_nonce == "nonce-45"
    assert "fresh revision" in item.status_note
    assert revision.status == "superseded"
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "t1"
    assert workspace.leased_owner_pid == 202


@pytest.mark.asyncio
async def test_handoff_supersedes_pending_continuation_authority(db, monkeypatch):
    async def config_runner(_args):
        return 0, ""

    async def revoke(*_args, **_kwargs):
        return True

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    monkeypatch.setattr(github_workspace_service, "revoke_push_token", revoke)
    _preset, slots, scope = await _team(db)
    old_owner, target = slots[:2]
    item, workspace, revision, owner_member = await _active_continuation(
        db,
        scope,
        old_owner,
        issue_number=46,
        activated_at=datetime.utcnow(),
        owner_contact_at=datetime.utcnow(),
    )
    target_member = await _create_registered_slot_member(db, target)
    item.dispatch_status = "escalated"
    item.escalation_reason = "retry_count_exhausted"
    item.active_scope_revision = 0
    item.handoff_state = "pending"
    item.handoff_target_slot_id = target.id
    revision.status = "proposed"
    root = MailMessage(
        kind="context_request",
        sender_member_id=owner_member.id,
        recipient_member_id=target_member.id,
        body_markdown=revision.summary,
        payload={"request_kind": "continuation"},
        request_status="pending",
    )
    db.add(root)
    await db.flush()
    approval = GithubApprovalRequest(
        work_item_id=item.id,
        request_kind="continuation",
        dispatch_nonce=item.dispatch_nonce,
        approval_round=item.approval_round_count,
        owner_member_id=owner_member.id,
        leader_member_id=target_member.id,
        request_message_id=root.id,
        scope_revision_id=revision.id,
        request_fingerprint="pending-continuation",
        status="pending",
    )
    db.add(approval)
    await db.flush()
    revision.approval_request_id = approval.id
    await db.commit()

    await github_dispatch_service.accept_handoff(
        db,
        item,
        target.id,
        accepting_pane_pid=202,
        accepting_pane_proc_start="2002",
    )

    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    await db.refresh(approval)
    await db.refresh(root)
    assert item.owner_slot_id == target.id
    assert item.dispatch_status == "escalated"
    assert revision.status == "superseded"
    assert approval.status == "superseded"
    assert root.request_status == "superseded"
    assert await github_approval_service.current_pending(db, item.id) is None
    assert workspace.lease_token == "t1"
    assert workspace.leased_owner_pid == 202


@pytest.mark.asyncio
async def test_handoff_config_failure_keeps_old_owner_and_identity(db, monkeypatch):
    _, slots, scope = await _team(db)
    old_owner, target = slots[:2]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=41,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=old_owner.id,
        handoff_state="pending",
        handoff_target_slot_id=target.id,
        dispatch_nonce="nonce",
        dispatch_head_ref="deck/preserved",
        dispatch_base_ref="origin/master",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/handoff-failure",
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="lease-kept",
    )
    db.add(workspace)
    await db.commit()
    item_id = item.id
    workspace_id = workspace.id
    old_owner_id = old_owner.id
    target_id = target.id
    restored = False

    async def snapshot(_workspace):
        return object()

    async def fail_identity(*args, **kwargs):
        raise RuntimeError("config failed")

    async def restore(_workspace, _snapshot):
        nonlocal restored
        restored = True

    monkeypatch.setattr(github_workspace_service, "snapshot_worktree_config", snapshot)
    monkeypatch.setattr(github_workspace_service, "apply_slot_identity", fail_identity)
    monkeypatch.setattr(github_workspace_service, "restore_worktree_config", restore)

    with pytest.raises(ValueError, match="handoff identity update failed"):
        await github_dispatch_service.accept_handoff(
            db,
            item,
            target_id,
            accepting_pane_pid=202,
            accepting_pane_proc_start="2002",
        )

    fresh_item = await db.get(GithubWorkItem, item_id)
    fresh_workspace = await db.get(GithubWorkspace, workspace_id)
    assert fresh_item.owner_slot_id == old_owner_id
    assert fresh_item.handoff_state == "pending"
    assert fresh_item.dispatch_head_ref == "deck/preserved"
    assert fresh_workspace.lease_token == "lease-kept"
    assert restored is True


@pytest.mark.asyncio
async def test_handoff_cas_loss_does_not_revoke_the_current_lease(db, monkeypatch):
    _, slots, scope = await _team(db)
    old_owner, target = slots[:2]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=43,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=old_owner.id,
        handoff_state="pending",
        handoff_target_slot_id=target.id,
        dispatch_nonce="nonce",
        dispatch_head_ref="deck/preserved",
        dispatch_base_ref="origin/master",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/handoff-race",
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="lease-kept",
    )
    db.add(workspace)
    await db.commit()
    revoked = []

    async def config_runner(_args):
        return 0, ""

    async def revoke(*args, **kwargs):
        revoked.append((args, kwargs))
        return True

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    monkeypatch.setattr(github_workspace_service, "revoke_push_token", revoke)
    await db.execute(
        update(GithubWorkItem)
        .where(GithubWorkItem.id == item.id)
        .values(owner_slot_id=target.id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()

    with pytest.raises(ValueError, match="handoff state changed"):
        await github_dispatch_service.accept_handoff(
            db,
            item,
            target.id,
            accepting_pane_pid=202,
            accepting_pane_proc_start="2002",
        )

    await db.refresh(workspace)
    assert workspace.lease_token == "lease-kept"
    assert revoked == []


@pytest.mark.asyncio
async def test_handoff_refreshes_quarantine_after_waiting_for_config_lock(
    db, monkeypatch
):
    _, slots, scope = await _team(db)
    scope.github_auth_mode = "app"
    scope.github_app_installation_id = 55
    old_owner, target = slots[:2]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=44,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=old_owner.id,
        handoff_state="pending",
        handoff_target_slot_id=target.id,
        dispatch_nonce="nonce",
        dispatch_head_ref="deck/preserved",
        dispatch_base_ref="origin/master",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/handoff-quarantine-race",
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="lease-kept",
    )
    db.add(workspace)
    await db.commit()
    item_id = item.id
    old_owner_id = old_owner.id
    future_expiry = datetime.utcnow() + timedelta(minutes=30)
    await db.execute(
        update(GithubWorkspace)
        .where(GithubWorkspace.id == workspace.id)
        .values(push_token_expires_at=future_expiry)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    assert workspace.push_token_expires_at is None

    async def config_runner(_args):
        return 0, ""

    async def cache_miss(*_args, **_kwargs):
        return False

    monkeypatch.setattr(github_workspace_service, "_runner", config_runner)
    monkeypatch.setattr(
        "app.services.github_workspace_service.github_app_auth_service."
        "revoke_cached_repository_token",
        cache_miss,
    )

    with pytest.raises(GithubWorkspaceCredentialRevokeError):
        await github_dispatch_service.accept_handoff(
            db,
            item,
            target.id,
            accepting_pane_pid=202,
            accepting_pane_proc_start="2002",
        )

    await db.refresh(item)
    await db.refresh(workspace)
    assert item.id == item_id
    assert item.owner_slot_id == old_owner_id
    assert item.handoff_state == "pending"
    assert workspace.lease_token == "lease-kept"
    assert workspace.push_token_expires_at == future_expiry


@pytest.mark.asyncio
async def test_handoff_cancellation_restores_identity_and_keeps_the_old_owner(
    db, monkeypatch
):
    _, slots, scope = await _team(db)
    old_owner, target = slots[:2]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=42,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=old_owner.id,
        handoff_state="pending",
        handoff_target_slot_id=target.id,
        dispatch_nonce="nonce",
        dispatch_head_ref="deck/preserved",
        dispatch_base_ref="origin/master",
    )
    db.add(item)
    await db.flush()
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/handoff-cancelled",
        leased_item_id=item.id,
        leased_at=datetime.utcnow(),
        lease_token="lease-kept",
    )
    db.add(workspace)
    await db.commit()
    old_owner_id = old_owner.id
    restored = []
    snapshot = object()

    async def take_snapshot(_workspace):
        return snapshot

    async def cancel_identity(*args, **kwargs):
        raise asyncio.CancelledError

    async def restore(_workspace, restored_snapshot):
        restored.append(restored_snapshot)

    monkeypatch.setattr(
        github_workspace_service, "snapshot_worktree_config", take_snapshot
    )
    monkeypatch.setattr(
        github_workspace_service, "apply_slot_identity", cancel_identity
    )
    monkeypatch.setattr(github_workspace_service, "restore_worktree_config", restore)

    with pytest.raises(asyncio.CancelledError):
        await github_dispatch_service.accept_handoff(
            db,
            item,
            target.id,
            accepting_pane_pid=202,
            accepting_pane_proc_start="2002",
        )

    await db.refresh(item)
    await db.refresh(workspace)
    assert item.owner_slot_id == old_owner_id
    assert item.handoff_state == "pending"
    assert workspace.leased_owner_pid is None
    assert workspace.lease_token == "lease-kept"
    assert restored == [snapshot]


@pytest.mark.asyncio
async def test_terminal_item_holding_a_lease_is_reminded(db):
    _, slots, scope = await _team(db)
    await _create_registered_slot_member(db, slots[1])
    _, workspace = await _leased_item_for_reminder(
        db,
        scope,
        issue_number=920,
        dispatch_status="merged",
        owner_slot_id=slots[1].id,
    )

    reminded = await github_dispatch_service.remind_held_leases(db, scope)

    assert reminded == 1
    assert workspace.lease_release_reminded_at is not None


@pytest.mark.asyncio
async def test_lease_release_reminder_quotes_token(db):
    _, slots, scope = await _team(db)
    await _create_registered_slot_member(db, slots[1])
    await _leased_item_for_reminder(
        db,
        scope,
        issue_number=921,
        dispatch_status="completed",
        owner_slot_id=slots[1].id,
    )

    await github_dispatch_service.remind_held_leases(db, scope)

    message = (await db.execute(select(MailMessage))).scalars().one()
    assert 'lease_token="tok-921"' in message.body_markdown


@pytest.mark.asyncio
async def test_lease_release_reminders_are_throttled(db):
    _, slots, scope = await _team(db)
    await _create_registered_slot_member(db, slots[1])
    now = datetime.utcnow()
    _, recent = await _leased_item_for_reminder(
        db,
        scope,
        issue_number=922,
        dispatch_status="merged",
        owner_slot_id=slots[1].id,
        reminded_at=now,
    )
    _, expired = await _leased_item_for_reminder(
        db,
        scope,
        issue_number=923,
        dispatch_status="merged",
        owner_slot_id=slots[1].id,
        reminded_at=now
        - timedelta(seconds=settings.github_nudge_grace_seconds + 60),
    )
    old_expired_stamp = expired.lease_release_reminded_at

    reminded = await github_dispatch_service.remind_held_leases(db, scope)

    assert reminded == 1
    assert recent.lease_release_reminded_at == now
    assert expired.lease_release_reminded_at > old_expired_stamp


@pytest.mark.asyncio
async def test_pending_retry_changes_release_reminder_wording(db):
    _, slots, scope = await _team(db)
    await _create_registered_slot_member(db, slots[1])
    await _leased_item_for_reminder(
        db,
        scope,
        issue_number=924,
        dispatch_status="escalated",
        owner_slot_id=slots[1].id,
        retry_requested_at=datetime.utcnow(),
    )

    await github_dispatch_service.remind_held_leases(db, scope)

    message = (await db.execute(select(MailMessage))).scalars().one()
    assert "re-dispatch of this issue is queued behind this release" in message.body_markdown


@pytest.mark.asyncio
async def test_recoverable_escalation_does_not_receive_release_reminder(db):
    preset, slots, scope = await _team(db)
    preset.autonomy_enabled = True
    scope.continuation_enabled = True
    await _create_registered_slot_member(db, slots[1])
    item, workspace = await _leased_item_for_reminder(
        db,
        scope,
        issue_number=928,
        dispatch_status="escalated",
        owner_slot_id=slots[1].id,
    )
    item.escalation_reason = "retry_count_exhausted"
    item.pr_number = 928
    item.dispatch_nonce = "preserved-attempt"
    await db.commit()

    assert await github_dispatch_service.remind_held_leases(db, scope) == 0

    await db.refresh(workspace)
    assert workspace.lease_release_reminded_at is None
    assert (await db.execute(select(MailMessage))).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "pr_number", "dispatch_nonce"),
    [
        ("dispatch_label_removed", 929, "attempt"),
        ("retry_count_exhausted", None, "attempt"),
        ("retry_count_exhausted", 929, None),
    ],
)
async def test_non_recoverable_escalation_still_receives_release_reminder(
    db,
    reason,
    pr_number,
    dispatch_nonce,
):
    preset, slots, scope = await _team(db)
    preset.autonomy_enabled = True
    scope.continuation_enabled = True
    await _create_registered_slot_member(db, slots[1])
    item, workspace = await _leased_item_for_reminder(
        db,
        scope,
        issue_number=929,
        dispatch_status="escalated",
        owner_slot_id=slots[1].id,
    )
    item.escalation_reason = reason
    item.pr_number = pr_number
    item.dispatch_nonce = dispatch_nonce
    await db.commit()

    assert await github_dispatch_service.remind_held_leases(db, scope) == 1

    await db.refresh(workspace)
    assert workspace.lease_release_reminded_at is not None
    release_messages = (
        await db.execute(
            select(MailMessage).where(MailMessage.subject.like("Release needed:%"))
        )
    ).scalars().all()
    assert len(release_messages) == 1


@pytest.mark.asyncio
async def test_non_terminal_item_holding_a_lease_is_not_reminded(db):
    _, slots, scope = await _team(db)
    await _leased_item_for_reminder(
        db,
        scope,
        issue_number=925,
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )

    assert await github_dispatch_service.remind_held_leases(db, scope) == 0


@pytest.mark.asyncio
async def test_unleased_terminal_item_is_not_reminded(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=926,
        issue_title="done",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    assert await github_dispatch_service.remind_held_leases(db, scope) == 0


@pytest.mark.asyncio
async def test_repeated_lease_release_reminders_never_escalate(db):
    _, slots, scope = await _team(db)
    await _create_registered_slot_member(db, slots[1])
    item, workspace = await _leased_item_for_reminder(
        db,
        scope,
        issue_number=927,
        dispatch_status="merged",
        owner_slot_id=slots[1].id,
    )

    for _ in range(3):
        workspace.lease_release_reminded_at = datetime.utcnow() - timedelta(
            seconds=settings.github_nudge_grace_seconds + 60
        )
        await db.commit()
        assert await github_dispatch_service.remind_held_leases(db, scope) == 1

    assert item.dispatch_status == "merged"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_initial_monitor_excludes_pr_bearing_active_continuation(db):
    preset, slots, scope = await _team(db)
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds
        + settings.github_nudge_grace_seconds
        + 60
    )
    item, _workspace, revision, _member = await _active_continuation(
        db,
        scope,
        slots[1],
        issue_number=940,
        activated_at=old,
        owner_contact_at=old,
    )

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[0].id: "wakeable", slots[1].id: "wakeable"},
    )

    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None
    assert item.continuation_nudged_at is None
    assert revision.status == "active"


@pytest.mark.asyncio
async def test_continuation_monitor_uses_activation_and_owner_contact_clocks(db):
    _preset, slots, scope = await _team(db)
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 60
    )
    recent = datetime.utcnow()
    item, _workspace, revision, _member = await _active_continuation(
        db,
        scope,
        slots[1],
        issue_number=941,
        activated_at=recent,
        owner_contact_at=old,
    )
    item.continuation_nudged_at = old
    await db.commit()

    await github_dispatch_service.monitor_continuation(db, scope, slots)

    await db.refresh(item)
    await db.refresh(revision)
    assert item.dispatch_status == "dispatched"
    assert item.continuation_nudged_at == old
    assert revision.status == "active"


@pytest.mark.asyncio
async def test_continuation_monitor_nudges_once_then_escalates_without_reset(
    db, caplog
):
    caplog.set_level("DEBUG", logger="app.services.github_dispatch_service")
    _preset, slots, scope = await _team(db)
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 60
    )
    item, workspace, revision, member = await _active_continuation(
        db,
        scope,
        slots[1],
        issue_number=942,
        activated_at=old,
        owner_contact_at=old,
    )

    await github_dispatch_service.monitor_continuation(db, scope, slots)

    await db.refresh(item)
    assert item.continuation_nudged_at is not None
    assert item.dispatch_status == "dispatched"
    messages = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.recipient_member_id == member.id,
                MailMessage.subject.like("Continuation progress check:%"),
            )
        )
    ).scalars().all()
    assert len(messages) == 1

    item.continuation_nudged_at = datetime.utcnow() - timedelta(
        seconds=settings.github_nudge_grace_seconds + 5
    )
    await db.commit()
    await github_dispatch_service.monitor_continuation(db, scope, slots)

    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_idle_timeout"
    assert item.pr_number == 942
    assert item.dispatch_nonce == "nonce-942"
    assert item.active_scope_revision == 1
    assert item.retry_count == 0
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "t1"
    assert revision.status == "superseded"
    actions = [
        record.monitor_action
        for record in caplog.records
        if hasattr(record, "monitor_action")
    ]
    assert actions == ["nudge_owner", "escalate_idle"]
    for record in caplog.records:
        if hasattr(record, "monitor_action"):
            assert record.monitor_name == "monitor_continuation"
            assert record.work_item_id == item.id
            assert record.active_scope_revision == 1
    assert "t1" not in caplog.text
    assert "pytest -q" not in caplog.text


@pytest.mark.asyncio
async def test_continuation_monitor_nudge_recovers_after_mail_commit_crash(
    db, monkeypatch
):
    _preset, slots, scope = await _team(db)
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 60
    )
    item, _workspace, _revision, member = await _active_continuation(
        db,
        scope,
        slots[1],
        issue_number=943,
        activated_at=old,
        owner_contact_at=old,
    )
    original_notify = github_dispatch_service.notify_owner
    crashed = False

    async def commit_mail_then_crash(*args, **kwargs):
        nonlocal crashed
        await original_notify(*args, **kwargs)
        if not crashed:
            crashed = True
            raise RuntimeError("crash after durable nudge")

    monkeypatch.setattr(
        github_dispatch_service,
        "notify_owner",
        commit_mail_then_crash,
    )

    with pytest.raises(RuntimeError, match="crash after durable nudge"):
        await github_dispatch_service.monitor_continuation(db, scope, slots)
    await db.refresh(item)
    assert item.continuation_nudged_at is None

    await github_dispatch_service.monitor_continuation(db, scope, slots)

    await db.refresh(item)
    assert item.continuation_nudged_at is not None
    messages = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.recipient_member_id == member.id,
                MailMessage.subject.like("Continuation progress check:%"),
            )
        )
    ).scalars().all()
    assert len(messages) == 1


async def _recoverable_escalated_item(db, *, autonomy=True, continuation=True):
    preset, slots, scope = await _team(db)
    preset.autonomy_enabled = autonomy
    scope.continuation_enabled = continuation
    await _create_registered_slot_member(db, slots[0])
    owner = await _create_registered_slot_member(db, slots[1])
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=950,
        issue_title="Recover the preserved attempt",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="retry_count_exhausted",
        status_note="Hosted playback check failed",
        owner_slot_id=slots[1].id,
        dispatch_nonce="recovery-nonce",
        dispatch_head_ref=f"deck/slot-{slots[1].id}/issue-950-recovery",
        dispatch_base_ref="origin/master",
        pr_number=950,
        approval_round_count=1,
        retry_count=3,
        last_verified_sha="failed-head",
    )
    db.add(item)
    await db.flush()
    workspace = await _lease_for(db, scope, item)
    observed_session = MailAgentSession(
        member_id=owner.id,
        provider=slots[1].provider,
        source="observed",
        session_key="tmux:recovery-owner",
        cwd=slots[1].repo_path,
        tmux_target="recovery:1.0",
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
        mailbox_status="observed",
        last_seen_at=datetime.utcnow(),
    )
    authenticated_session = MailAgentSession(
        member_id=owner.id,
        provider=slots[1].provider,
        source="mcp",
        session_key="mcp:recovery-owner",
        cwd=slots[1].repo_path,
        team_preset_id=preset.id,
        team_slot_id=slots[1].id,
        mailbox_status="connected",
        last_seen_at=datetime.utcnow(),
        capability_token_hash=agent_mail_service.hash_capability_token(
            "recovery-owner-token"
        ),
    )
    db.add_all([observed_session, authenticated_session])
    await db.commit()
    return preset, slots, scope, item, workspace, owner, observed_session


async def _continuation_transport_authority(
    db,
    item,
    workspace,
    owner,
    *,
    status="pending",
):
    _current_owner, leader = await agent_mail_service._dispatch_participants(db, item)
    revision = GithubAttemptScopeRevision(
        work_item_id=item.id,
        dispatch_nonce=item.dispatch_nonce,
        revision=1,
        owner_slot_id=item.owner_slot_id,
        owner_member_id=owner.id,
        phase="implementation",
        execution_target="workspace",
        summary="Apply one bounded recovery fix",
        allowed_paths=["src/fix.py"],
        allowed_actions=["edit_production", "push_pr_head"],
        allowed_commands=["pytest -q"],
        prohibited_actions=[],
        tool_fallbacks={},
        baseline_head_sha="a" * 40,
        baseline_tree_sha="b" * 40,
        originating_escalation_reason=item.escalation_reason,
        expected_workspace_id=workspace.id,
        expected_lease_token_hash=github_approval_service.lease_token_hash(
            workspace.lease_token
        ),
        max_failed_heads=1,
        status={"pending": "proposed", "approved": "approved", "rejected": "rejected"}[
            status
        ],
        approved_at=datetime.utcnow() if status == "approved" else None,
    )
    db.add(revision)
    await db.flush()
    request = GithubApprovalRequest(
        work_item_id=item.id,
        request_kind="continuation",
        dispatch_nonce=item.dispatch_nonce,
        approval_round=item.approval_round_count,
        owner_member_id=owner.id,
        leader_member_id=leader.id,
        scope_revision_id=revision.id,
        request_fingerprint="transport-fixture",
        status=status,
        reason=(
            "Approved bounded recovery"
            if status == "approved"
            else "Revise the recovery proposal"
            if status == "rejected"
            else None
        ),
        decided_at=datetime.utcnow() if status != "pending" else None,
    )
    db.add(request)
    await db.flush()
    revision.approval_request_id = request.id
    await db.commit()
    return request, revision, leader


async def _send_continuation_request_root(db, item, request, revision):
    return await agent_mail_service.send_message(
        db,
        MailMessageCreate(
            kind="context_request",
            sender_member_id=request.owner_member_id,
            recipient_member_id=request.leader_member_id,
            subject=(
                f"Continuation revision {revision.revision} for work item {item.id}"
            ),
            body_markdown=revision.summary,
            payload=github_approval_service.continuation_request_payload(
                request,
                revision,
            ),
        ),
        authenticated_sender_member_id=request.owner_member_id,
        delivery_key=f"github-approval:{request.id}:request",
        auto_nudge=False,
    )


async def _send_continuation_decision(db, request, revision):
    return await agent_mail_service.send_authoritative_decision(
        db,
        MailMessageCreate(
            kind="answer",
            sender_member_id=request.leader_member_id,
            thread_root_id=request.request_message_id,
            body_markdown=request.reason,
            payload=github_approval_service.continuation_decision_payload(
                request,
                revision,
            ),
            decision=request.status,
        ),
        authenticated_sender_member_id=request.leader_member_id,
        approval_round=request.approval_round,
        delivery_key=f"github-approval:{request.id}:decision",
    )


def _assert_actionable_owner_ack_nudge(
    nudges,
    *,
    owner,
    item,
    revision,
    workspace,
):
    assert len(nudges) == 1
    member_ids, kwargs = nudges[0]
    assert member_ids == {owner.id}
    assert kwargs["bypass_cooldown"] is True
    prompt = kwargs["nudge_prompt"]
    assert f"work item {item.id}" in prompt
    assert f"revision {revision.revision}" in prompt
    assert f"message {revision.delivery_message_id}" in prompt
    assert "`deck_check_inbox(unread_only=False)`" in prompt
    assert "`deck_ack_continuation`" in prompt
    assert "Do not execute" in prompt
    assert workspace.lease_token not in prompt


async def _create_replacement_slot_member(db, slot):
    member = MailTeamMember(
        identity_key=f"slot:replacement:{slot.id}",
        repo_id=slot.repo_id,
        repo_path=slot.repo_path,
        repo_name=slot.repo_name,
        display_name=f"Replacement {slot.display_name}",
        participant_kind="team_slot",
        team_preset_id=slot.preset_id,
        team_slot_id=slot.id,
        role=slot.role,
        charter=slot.charter,
    )
    db.add(member)
    await db.commit()
    return member


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_session_evidence",
    [
        "missing_mcp",
        "unauthenticated_mcp",
        "offline_mcp",
        "stale_mcp",
        "hook_only",
        "duplicate_observed",
    ],
)
async def test_recovery_monitor_requires_one_pane_and_fresh_authenticated_mcp(
    db,
    monkeypatch,
    invalid_session_evidence,
):
    _isolate_agent_mail_nudges(monkeypatch)
    _preset, slots, scope, item, _workspace, owner, observed_session = (
        await _recoverable_escalated_item(db)
    )
    authenticated_session = (
        await db.execute(
            select(MailAgentSession).where(
                MailAgentSession.member_id == owner.id,
                MailAgentSession.source == "mcp",
            )
        )
    ).scalar_one()
    if invalid_session_evidence == "missing_mcp":
        await db.delete(authenticated_session)
    elif invalid_session_evidence == "unauthenticated_mcp":
        authenticated_session.capability_token_hash = None
    elif invalid_session_evidence == "offline_mcp":
        authenticated_session.mailbox_status = "offline"
    elif invalid_session_evidence == "stale_mcp":
        authenticated_session.last_seen_at = datetime.utcnow() - timedelta(hours=2)
    elif invalid_session_evidence == "hook_only":
        authenticated_session.source = "hook"
        authenticated_session.session_key = "hook:recovery-owner"
    else:
        db.add(
            MailAgentSession(
                member_id=owner.id,
                provider=slots[1].provider,
                source="observed",
                session_key="tmux:recovery-owner-duplicate",
                cwd=slots[1].repo_path,
                tmux_target="recovery:1.1",
                team_preset_id=scope.preset_id,
                team_slot_id=slots[1].id,
                mailbox_status="observed",
                last_seen_at=datetime.utcnow(),
            )
        )
    await db.commit()

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "merged_at": None}

    monkeypatch.setattr(
        "app.services.github_dispatch_service.github_client.get_pull",
        get_pull,
    )

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    await db.refresh(observed_session)
    assert item.continuation_nudged_at is None
    assert (
        await db.execute(
            select(MailMessage).where(
                MailMessage.subject.like("Recovery proposal requested:%")
            )
        )
    ).scalars().all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_status", ["pending", "approved", "active"])
async def test_continuation_authority_suppresses_release_reminder(
    db,
    authority_status,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request_status = (
        "approved" if authority_status in {"approved", "active"} else "pending"
    )
    _request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status=request_status,
    )
    if authority_status == "active":
        revision.status = "active"
        item.dispatch_status = "dispatched"
        await db.commit()

    assert await github_dispatch_service.remind_held_leases(db, scope) == 0

    await db.refresh(workspace)
    assert workspace.lease_release_reminded_at is None
    release_messages = (
        await db.execute(
            select(MailMessage).where(MailMessage.subject.like("Release needed:%"))
        )
    ).scalars().all()
    assert release_messages == []


@pytest.mark.asyncio
async def test_recovery_monitor_sends_one_idempotent_owner_proposal_instruction(
    db, monkeypatch
):
    _isolate_agent_mail_nudges(monkeypatch)
    monkeypatch.setattr(settings, "github_nudge_grace_seconds", 0)
    monkeypatch.setattr(
        settings,
        "github_recovery_nudge_cooldown_seconds",
        3600,
    )
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    nudges = []

    async def record_nudge(_db, member_ids, **kwargs):
        nudges.append((set(member_ids), kwargs))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "merged_at": None}

    monkeypatch.setattr("app.services.github_dispatch_service.github_client.get_pull", get_pull)

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    first_nudge = item.continuation_nudged_at
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    await db.refresh(workspace)
    messages = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.recipient_member_id == owner.id,
                MailMessage.subject.like("Recovery proposal requested:%"),
            )
        )
    ).scalars().all()
    assert len(messages) == 1
    assert item.continuation_nudged_at == first_nudge
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "t1"
    assert await github_approval_service.current_pending(db, item.id) is None
    assert "Perform read-only diagnosis first" in messages[0].body_markdown
    assert "deck_request_continuation" in messages[0].body_markdown
    assert len(nudges) == 1
    member_ids, nudge_options = nudges[0]
    assert member_ids == {owner.id}
    assert nudge_options["bypass_cooldown"] is True
    nudge_prompt = nudge_options["nudge_prompt"]
    assert "deck_check_inbox(unread_only=False)" in nudge_prompt
    assert f"work item {item.id}" in nudge_prompt
    assert f"issue #{item.issue_number}" in nudge_prompt
    assert "Recovery proposal requested" in nudge_prompt
    assert "read-only diagnosis" in nudge_prompt
    assert "deck_request_continuation" in nudge_prompt
    assert "diagnostic" in nudge_prompt
    assert "revert_diagnostic_changes" in nudge_prompt
    assert "implementation" in nudge_prompt
    assert "push_pr_head" in nudge_prompt
    assert "request_verification" in nudge_prompt
    assert "diagnostic" in messages[0].body_markdown
    assert "revert_diagnostic_changes" in messages[0].body_markdown
    assert "implementation" in messages[0].body_markdown
    assert "push_pr_head" in messages[0].body_markdown
    assert "request_verification" in messages[0].body_markdown
    for prohibited_action in ("edit", "build", "push", "release", "retry"):
        assert prohibited_action in nudge_prompt.lower()
    assert messages[0].payload["failure_evidence"] == {
        "escalation_reason": "retry_count_exhausted",
        "status_note": "Hosted playback check failed",
        "retry_count": 3,
        "diagnostic_retry_count": 0,
        "last_verified_sha": "failed-head",
        "diagnostic_last_verified_sha": None,
    }
    assert "t1" not in str(messages[0].payload)


@pytest.mark.asyncio
async def test_recovery_monitor_uses_a_new_delivery_key_for_each_proposal_cycle(
    db, monkeypatch
):
    _isolate_agent_mail_nudges(monkeypatch)
    monkeypatch.setattr(settings, "github_nudge_grace_seconds", 0)
    monkeypatch.setattr(
        settings,
        "github_recovery_nudge_cooldown_seconds",
        3600,
    )
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    nudges = []

    async def record_nudge(_db, member_ids, **kwargs):
        nudges.append((set(member_ids), kwargs))

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "merged_at": None}

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)
    monkeypatch.setattr(
        "app.services.github_dispatch_service.github_client.get_pull",
        get_pull,
    )

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="rejected",
    )
    request.status = "expired"
    revision.status = "superseded"
    item.status_note = "The prior continuation was cancelled safely"
    item.continuation_nudged_at = None
    await db.commit()

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await db.refresh(item)
    item.continuation_nudged_at = None
    await db.commit()
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    messages = (
        await db.execute(
            select(MailMessage)
            .where(
                MailMessage.recipient_member_id == owner.id,
                MailMessage.subject.like("Recovery proposal requested:%"),
            )
            .order_by(MailMessage.id)
        )
    ).scalars().all()
    assert [message.delivery_key for message in messages] == [
        f"github-recovery:{item.id}:{item.dispatch_nonce}:proposal:1",
        f"github-recovery:{item.id}:{item.dispatch_nonce}:proposal:2",
    ]
    assert messages[0].payload["failure_evidence"]["status_note"] == (
        "Hosted playback check failed"
    )
    assert messages[1].payload["failure_evidence"]["status_note"] == (
        "The prior continuation was cancelled safely"
    )
    assert len(nudges) == 3
    assert all(member_ids == {owner.id} for member_ids, _options in nudges)
    await db.refresh(item)
    await db.refresh(workspace)
    await db.refresh(revision)
    assert item.dispatch_status == "escalated"
    assert item.pr_number == 950
    assert item.retry_count == 3
    assert item.diagnostic_retry_count == 0
    assert workspace.leased_item_id == item.id
    assert workspace.lease_token == "t1"
    assert revision.status == "superseded"


@pytest.mark.asyncio
async def test_recovery_monitor_replays_actionable_wake_after_post_mail_crash(
    db, monkeypatch
):
    _isolate_agent_mail_nudges(monkeypatch)
    _preset, slots, scope, item, _workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "merged_at": None}

    monkeypatch.setattr(
        "app.services.github_dispatch_service.github_client.get_pull",
        get_pull,
    )
    nudges = []

    async def crash_then_record(_db, member_ids, **kwargs):
        nudges.append((set(member_ids), kwargs))
        if len(nudges) == 1:
            raise RuntimeError("crash after durable recovery mail")

    monkeypatch.setattr(
        agent_mail_service,
        "auto_nudge_members",
        crash_then_record,
    )

    with pytest.raises(RuntimeError, match="crash after durable recovery mail"):
        await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    assert item.continuation_nudged_at is None

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    messages = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.recipient_member_id == owner.id,
                MailMessage.subject.like("Recovery proposal requested:%"),
            )
        )
    ).scalars().all()
    assert len(messages) == 1
    assert item.continuation_nudged_at is not None
    assert len(nudges) == 2
    assert nudges[0] == nudges[1]
    member_ids, nudge_options = nudges[1]
    assert member_ids == {owner.id}
    assert nudge_options["bypass_cooldown"] is True
    assert "deck_request_continuation" in nudge_options["nudge_prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("autonomy", "continuation", "remove_session", "reason", "pr_number"),
    [
        (False, True, False, "retry_count_exhausted", 950),
        (True, False, False, "retry_count_exhausted", 950),
        (True, True, True, "retry_count_exhausted", 950),
        (True, True, False, "abandoned_by_operator", 950),
        (True, True, False, "retry_count_exhausted", None),
    ],
)
async def test_recovery_monitor_refuses_disabled_offline_or_human_stop_items(
    db,
    monkeypatch,
    autonomy,
    continuation,
    remove_session,
    reason,
    pr_number,
):
    _isolate_agent_mail_nudges(monkeypatch)
    _preset, slots, scope, item, _workspace, _owner, session = (
        await _recoverable_escalated_item(
            db,
            autonomy=autonomy,
            continuation=continuation,
        )
    )
    item.escalation_reason = reason
    item.pr_number = pr_number
    if remove_session:
        await db.delete(session)
    await db.commit()

    async def get_pull(*_args, **_kwargs):
        return {"state": "open", "merged_at": None}

    monkeypatch.setattr("app.services.github_dispatch_service.github_client.get_pull", get_pull)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    assert item.continuation_nudged_at is None
    messages = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.subject.like("Recovery proposal requested:%")
            )
        )
    ).scalars().all()
    assert messages == []


@pytest.mark.asyncio
async def test_recovery_monitor_refuses_closed_pr(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    _preset, slots, scope, item, _workspace, _owner, _session = (
        await _recoverable_escalated_item(db)
    )

    async def get_pull(*_args, **_kwargs):
        return {"state": "closed", "merged_at": None}

    monkeypatch.setattr("app.services.github_dispatch_service.github_client.get_pull", get_pull)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    assert item.continuation_nudged_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mail_committed_before_link", [False, True])
async def test_recovery_monitor_repairs_pending_request_transport_once(
    db,
    monkeypatch,
    mail_committed_before_link,
):
    monkeypatch.setattr(settings, "github_nudge_grace_seconds", 0)
    monkeypatch.setattr(
        settings,
        "github_continuation_leader_nudge_cooldown_seconds",
        3600,
    )
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
    )
    durable_root = None
    if mail_committed_before_link:
        durable_root = await _send_continuation_request_root(
            db,
            item,
            request,
            revision,
        )
    nudges = []

    async def record_nudge(_db, member_ids, **kwargs):
        nudges.append((set(member_ids), kwargs))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    roots = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key
                == f"github-approval:{request.id}:request"
            )
        )
    ).scalars().all()
    receipts = (
        await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == request.request_message_id
            )
        )
    ).scalars().all()
    assert len(roots) == 1
    assert request.request_message_id == roots[0].id
    if durable_root is not None:
        assert request.request_message_id == durable_root.id
    assert [(receipt.member_id, receipt.read_at) for receipt in receipts] == [
        (leader.id, None)
    ]
    assert revision.delivery_attempt_count == 1
    assert revision.last_delivery_attempt_at is not None
    assert len(nudges) == 1
    member_ids, nudge_options = nudges[0]
    assert member_ids == {leader.id}
    assert nudge_options["bypass_cooldown"] is True
    leader_prompt = nudge_options["nudge_prompt"]
    assert "deck_check_inbox(unread_only=False)" in leader_prompt
    assert "deck_decide_continuation" in leader_prompt
    assert f"work item {item.id}" in leader_prompt
    assert f"revision {revision.revision}" in leader_prompt
    assert "diagnostic" in leader_prompt
    assert "revert_diagnostic_changes" in leader_prompt
    assert "implementation" in leader_prompt
    assert "push_pr_head" in leader_prompt
    assert "request_verification" in leader_prompt
    assert workspace.lease_token not in leader_prompt


@pytest.mark.asyncio
async def test_recovery_monitor_logs_structured_redacted_transport_action(
    db,
    monkeypatch,
    caplog,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    _request, revision, leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
    )

    async def record_nudge(_db, member_ids, **_kwargs):
        assert set(member_ids) == {leader.id}

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    with caplog.at_level(
        logging.DEBUG,
        logger="app.services.github_dispatch_service",
    ):
        await github_dispatch_service.monitor_recovery(db, scope, slots)

    record = next(
        record
        for record in caplog.records
        if getattr(record, "monitor_name", None) == "monitor_recovery"
    )
    assert record.work_item_id == item.id
    assert record.scope_revision == revision.revision
    assert record.revision_phase == "implementation"
    assert record.revision_status == "proposed"
    assert record.monitor_action == "nudge_leader"
    assert record.block_code is None
    assert record.grace_anchor is not None
    serialized = str(record.__dict__)
    assert workspace.lease_token not in serialized
    assert revision.summary not in serialized
    assert revision.allowed_commands[0] not in serialized


@pytest.mark.asyncio
async def test_concurrent_recovery_monitors_create_one_root_receipt_and_nudge(
    tmp_path,
    monkeypatch,
):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'recovery-race.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup_db:
        _preset, _slots, scope, item, workspace, owner, _session = (
            await _recoverable_escalated_item(setup_db)
        )
        request, revision, leader = await _continuation_transport_authority(
            setup_db,
            item,
            workspace,
            owner,
        )
        scope_id = scope.id
        request_id = request.id
        revision_id = revision.id
        leader_id = leader.id

    both_workers_ready = asyncio.Event()
    arrival_lock = asyncio.Lock()
    arrivals = 0

    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    async def run_monitor():
        nonlocal arrivals
        async with arrival_lock:
            arrivals += 1
            if arrivals == 2:
                both_workers_ready.set()
        await both_workers_ready.wait()
        async with maker() as worker_db:
            worker_scope = await worker_db.get(TeamGithubScope, scope_id)
            worker_slots = (
                await worker_db.execute(
                    select(AgentTeamSlot)
                    .where(AgentTeamSlot.preset_id == worker_scope.preset_id)
                    .order_by(AgentTeamSlot.position)
                )
            ).scalars().all()
            await github_dispatch_service.monitor_recovery(
                worker_db,
                worker_scope,
                worker_slots,
            )

    await asyncio.gather(run_monitor(), run_monitor())

    async with maker() as verify_db:
        stored_request = await verify_db.get(GithubApprovalRequest, request_id)
        stored_revision = await verify_db.get(
            GithubAttemptScopeRevision,
            revision_id,
        )
        roots = (
            await verify_db.execute(
                select(MailMessage).where(
                    MailMessage.delivery_key
                    == f"github-approval:{request_id}:request"
                )
            )
        ).scalars().all()
        receipts = (
            await verify_db.execute(
                select(MailReceipt).where(
                    MailReceipt.message_id == stored_request.request_message_id
                )
            )
        ).scalars().all()
        assert len(roots) == 1
        assert len(receipts) == 1
        assert receipts[0].member_id == leader_id
        assert stored_revision.delivery_attempt_count == 1
        assert nudges == [{leader_id}]
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    ["authority", "decision_mail", "decision_link", "delivery_mail"],
)
async def test_recovery_monitor_repairs_approved_transport_boundaries_once(
    db,
    monkeypatch,
    stage,
):
    monkeypatch.setattr(settings, "github_nudge_grace_seconds", 0)
    monkeypatch.setattr(
        settings,
        "github_continuation_owner_ack_nudge_cooldown_seconds",
        3600,
    )
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved",
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    await db.commit()
    durable_decision = None
    durable_delivery = None
    if stage in {"decision_mail", "decision_link", "delivery_mail"}:
        durable_decision = await _send_continuation_decision(db, request, revision)
    if stage in {"decision_link", "delivery_mail"}:
        request.decision_message_id = durable_decision.id
        await db.commit()
    if stage == "delivery_mail":
        durable_delivery = await agent_mail_service.send_direct_message(
            db,
            recipient_member_id=revision.owner_member_id,
            subject=(
                f"Approved continuation revision {revision.revision} for work item "
                f"{item.id}"
            ),
            body_markdown=(
                f"Continuation revision {revision.revision} is approved. "
                "Acknowledge it before making changes.\n\n"
                f"{revision.summary}"
            ),
            payload=github_approval_service.continuation_delivery_payload(
                request,
                revision,
            ),
            auto_nudge=False,
            delivery_key=f"github-scope:{revision.id}:delivery",
        )
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    decisions = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key
                == f"github-approval:{request.id}:decision"
            )
        )
    ).scalars().all()
    deliveries = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key
                == f"github-scope:{revision.id}:delivery"
            )
        )
    ).scalars().all()
    assert len(decisions) == 1
    assert len(deliveries) == 1
    assert request.decision_message_id == decisions[0].id
    assert revision.delivery_message_id == deliveries[0].id
    if durable_decision is not None:
        assert request.decision_message_id == durable_decision.id
    if durable_delivery is not None:
        assert revision.delivery_message_id == durable_delivery.id
    assert revision.delivered_at is not None
    assert revision.last_ack_nudge_at is not None
    assert nudges == [{owner.id}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    [
        "proposal_authority",
        "request_mail",
        "decision_authority",
        "decision_mail",
        "delivery_mail",
    ],
)
async def test_recovery_transport_freezes_with_autonomy_off_then_resumes_once(
    db,
    monkeypatch,
    stage,
):
    monkeypatch.setattr(
        settings,
        "github_continuation_leader_nudge_cooldown_seconds",
        3600,
    )
    monkeypatch.setattr(
        settings,
        "github_continuation_owner_ack_nudge_cooldown_seconds",
        3600,
    )
    preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db, autonomy=False)
    )
    approved = stage in {"decision_authority", "decision_mail", "delivery_mail"}
    request, revision, leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved" if approved else "pending",
    )
    if stage != "proposal_authority":
        root = await _send_continuation_request_root(db, item, request, revision)
        if stage != "request_mail":
            request.request_message_id = root.id
            await db.commit()
    if stage in {"decision_mail", "delivery_mail"}:
        decision = await _send_continuation_decision(db, request, revision)
        if stage == "delivery_mail":
            request.decision_message_id = decision.id
            await db.commit()
            await agent_mail_service.send_direct_message(
                db,
                recipient_member_id=revision.owner_member_id,
                subject=(
                    f"Approved continuation revision {revision.revision} for work item "
                    f"{item.id}"
                ),
                body_markdown=(
                    f"Continuation revision {revision.revision} is approved. "
                    "Acknowledge it before making changes.\n\n"
                    f"{revision.summary}"
                ),
                payload=github_approval_service.continuation_delivery_payload(
                    request,
                    revision,
                ),
                auto_nudge=False,
                delivery_key=f"github-scope:{revision.id}:delivery",
            )
    before = {
        "request_message_id": request.request_message_id,
        "decision_message_id": request.decision_message_id,
        "delivery_message_id": revision.delivery_message_id,
        "delivery_attempt_count": revision.delivery_attempt_count,
        "last_delivery_attempt_at": revision.last_delivery_attempt_at,
        "last_ack_nudge_at": revision.last_ack_nudge_at,
        "mail_count": await db.scalar(select(func.count()).select_from(MailMessage)),
        "receipt_count": await db.scalar(select(func.count()).select_from(MailReceipt)),
    }
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    after_disabled = {
        "request_message_id": request.request_message_id,
        "decision_message_id": request.decision_message_id,
        "delivery_message_id": revision.delivery_message_id,
        "delivery_attempt_count": revision.delivery_attempt_count,
        "last_delivery_attempt_at": revision.last_delivery_attempt_at,
        "last_ack_nudge_at": revision.last_ack_nudge_at,
        "mail_count": await db.scalar(select(func.count()).select_from(MailMessage)),
        "receipt_count": await db.scalar(select(func.count()).select_from(MailReceipt)),
    }
    assert after_disabled == before
    assert nudges == []

    preset.autonomy_enabled = True
    await db.commit()
    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    roots = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-approval:{request.id}:request"
            )
        )
    ).scalars().all()
    decisions = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-approval:{request.id}:decision"
            )
        )
    ).scalars().all()
    deliveries = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-scope:{revision.id}:delivery"
            )
        )
    ).scalars().all()
    assert len(roots) == 1
    assert request.request_message_id == roots[0].id
    if approved:
        assert len(decisions) == 1
        assert len(deliveries) == 1
        assert request.decision_message_id == decisions[0].id
        assert revision.delivery_message_id == deliveries[0].id
        assert nudges == [{owner.id}]
    else:
        assert decisions == []
        assert deliveries == []
        assert nudges == [{leader.id}]


@pytest.mark.asyncio
async def test_recovery_monitor_repairs_rejected_decision_without_owner_delivery(
    db,
    monkeypatch,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="rejected",
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    assert request.decision_message_id is not None
    assert revision.delivery_message_id is None
    assert revision.status == "rejected"
    assert nudges == []


@pytest.mark.asyncio
async def test_approved_continuation_delivery_wake_is_actionable_and_secret_free(
    db,
    monkeypatch,
):
    _preset, _slots, _scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved",
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    decision = await _send_continuation_decision(db, request, revision)
    request.decision_message_id = decision.id
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **kwargs):
        nudges.append((set(member_ids), kwargs))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    delivered_revision, delivered = (
        await github_approval_service.deliver_approved_continuation(
            db,
            item,
            request,
            revision,
        )
    )

    assert delivered is True
    assert delivered_revision.delivery_message_id is not None
    _assert_actionable_owner_ack_nudge(
        nudges,
        owner=owner,
        item=item,
        revision=delivered_revision,
        workspace=workspace,
    )


@pytest.mark.asyncio
async def test_recovery_monitor_nudges_only_current_owner_after_delivery_cooldown(
    db,
    monkeypatch,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved",
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    await db.commit()
    decision = await _send_continuation_decision(db, request, revision)
    request.decision_message_id = decision.id
    await db.commit()
    await github_approval_service.deliver_approved_continuation(
        db,
        item,
        request,
        revision,
    )
    revision.last_ack_nudge_at = datetime.utcnow() - timedelta(minutes=10)
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **kwargs):
        nudges.append((set(member_ids), kwargs))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    _assert_actionable_owner_ack_nudge(
        nudges,
        owner=owner,
        item=item,
        revision=revision,
        workspace=workspace,
    )


@pytest.mark.asyncio
async def test_approved_delivery_wake_failure_repairs_without_duplicate_mail(
    db,
    monkeypatch,
):
    _preset, _slots, _scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved",
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    decision = await _send_continuation_decision(db, request, revision)
    request.decision_message_id = decision.id
    await db.commit()
    failed_nudges = []

    async def fail_after_delivery(_db, member_ids, **kwargs):
        failed_nudges.append((set(member_ids), kwargs))
        raise RuntimeError("simulated wake failure")

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", fail_after_delivery)

    with pytest.raises(RuntimeError, match="simulated wake failure"):
        await github_approval_service.deliver_approved_continuation(
            db,
            item,
            request,
            revision,
        )

    await db.refresh(revision)
    durable_delivery_id = revision.delivery_message_id
    assert durable_delivery_id is not None
    _assert_actionable_owner_ack_nudge(
        failed_nudges,
        owner=owner,
        item=item,
        revision=revision,
        workspace=workspace,
    )
    revision.last_ack_nudge_at = datetime.utcnow() - timedelta(minutes=10)
    await db.commit()
    repaired_nudges = []

    async def record_repair_nudge(_db, member_ids, **kwargs):
        repaired_nudges.append((set(member_ids), kwargs))

    monkeypatch.setattr(
        agent_mail_service,
        "auto_nudge_members",
        record_repair_nudge,
    )

    action = await github_approval_service.repair_continuation_transport(
        db,
        item,
        request,
        revision,
        leader_nudge_cooldown=timedelta(hours=1),
        owner_ack_nudge_cooldown=timedelta(minutes=3),
    )

    deliveries = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key == f"github-scope:{revision.id}:delivery"
            )
        )
    ).scalars().all()
    assert action == "nudge_owner_ack"
    assert [message.id for message in deliveries] == [durable_delivery_id]
    _assert_actionable_owner_ack_nudge(
        repaired_nudges,
        owner=owner,
        item=item,
        revision=revision,
        workspace=workspace,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "approved", "rejected"])
@pytest.mark.parametrize("drift", ["nonce", "owner", "leader"])
async def test_recovery_monitor_supersedes_stale_transport_without_delivery(
    db,
    monkeypatch,
    status,
    drift,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status=status,
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    if drift == "nonce":
        item.dispatch_nonce = "replacement-nonce"
    elif drift == "owner":
        await _create_replacement_slot_member(db, slots[1])
    else:
        await _create_replacement_slot_member(db, slots[0])
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    root = await db.get(MailMessage, root.id)
    assert request.status == "superseded"
    assert revision.status == "superseded"
    assert root.request_status == "superseded"
    assert request.decision_message_id is None
    assert revision.delivery_message_id is None
    assert nudges == []


@pytest.mark.asyncio
async def test_recovery_monitor_expires_pending_authority_and_mail_atomically(
    db,
    monkeypatch,
):
    preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db, autonomy=False)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    revision.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await db.refresh(request)
    await db.refresh(revision)
    root_row = await db.get(MailMessage, root.id)
    assert request.status == "pending"
    assert revision.status == "proposed"
    assert root_row.request_status == "pending"
    assert revision.last_delivery_attempt_at is None

    preset.autonomy_enabled = True
    await db.commit()
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    await db.refresh(root_row)
    assert request.status == "expired"
    assert revision.status == "expired"
    assert root_row.request_status == "superseded"
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert nudges == []


@pytest.mark.asyncio
async def test_recovery_monitor_expires_approved_unacked_revision_without_delivery(
    db,
    monkeypatch,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved",
    )
    root = await _send_continuation_request_root(db, item, request, revision)
    request.request_message_id = root.id
    revision.expires_at = datetime.utcnow() - timedelta(seconds=1)
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(request)
    await db.refresh(revision)
    assert request.status == "approved"
    assert request.decision_message_id is not None
    assert revision.status == "expired"
    assert revision.delivery_message_id is None
    assert revision.acknowledged_at is None
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert nudges == []
    decisions = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.delivery_key
                == f"github-approval:{request.id}:decision"
            )
        )
    ).scalars().all()
    assert len(decisions) == 1


@pytest.mark.asyncio
async def test_pending_expiry_never_changes_active_revision(db):
    _preset, _slots, _scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="approved",
    )
    revision.status = "active"
    revision.acknowledged_at = datetime.utcnow()
    revision.expires_at = datetime.utcnow() - timedelta(hours=1)
    await db.commit()

    result = await github_approval_service.expire_continuation_if_needed(
        db,
        request,
        revision,
    )

    await db.refresh(request)
    await db.refresh(revision)
    assert result is None
    assert request.status == "approved"
    assert revision.status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", ["revisions", "failed_heads"])
async def test_recovery_monitor_hard_stops_exhausted_attempt_budget(
    db,
    monkeypatch,
    budget,
):
    _preset, slots, scope, item, workspace, owner, _session = (
        await _recoverable_escalated_item(db)
    )
    request, revision, _leader = await _continuation_transport_authority(
        db,
        item,
        workspace,
        owner,
        status="rejected",
    )
    request.status = "expired"
    revision.status = "expired"
    if budget == "revisions":
        scope.max_continuation_revisions = 1
        scope.max_continuation_failed_heads = 8
    else:
        scope.max_continuation_revisions = 6
        scope.max_continuation_failed_heads = 2
        revision.failed_head_count = 2
        revision.last_failed_head_sha = "failed-head-2"
    await db.commit()
    nudges = []

    async def record_nudge(_db, member_ids, **_kwargs):
        nudges.append(set(member_ids))

    monkeypatch.setattr(agent_mail_service, "auto_nudge_members", record_nudge)

    await github_dispatch_service.monitor_recovery(db, scope, slots)
    await github_dispatch_service.monitor_recovery(db, scope, slots)

    await db.refresh(item)
    broadcasts = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.kind == "broadcast",
                MailMessage.subject
                == "Autonomy escalation: continuation_budget_exhausted",
            )
        )
    ).scalars().all()
    recovery_messages = (
        await db.execute(
            select(MailMessage).where(
                MailMessage.subject.like("Recovery proposal requested:%")
            )
        )
    ).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "continuation_budget_exhausted"
    assert len(broadcasts) == 1
    assert recovery_messages == []


@pytest.mark.asyncio
async def test_delivery_proven_by_report_not_only_receipt(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    preset, slots, scope = await _team(db)
    stale = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_registration_grace_seconds + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=90,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=stale,
        updated_at=datetime.utcnow(),
        ack_received_at=datetime.utcnow(),
        brief_delivery_nudge_count=settings.github_brief_delivery_max_nudges,
        brief_delivery_nudge_at=stale,
    )
    db.add(item)
    await db.commit()
    member = await agent_mail_service.get_or_create_slot_member(db, slots[1])
    message = await agent_mail_service.send_direct_message(
        db,
        recipient_member_id=member.id,
        subject="brief",
        body_markdown="b",
        auto_nudge=False,
    )
    item.brief_message_id = message.id
    await _lease_for(
        db,
        scope,
        item,
        lease_last_owner_contact_at=datetime.utcnow(),
    )

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[0].id: "wakeable", slots[1].id: "wakeable"},
    )

    await db.refresh(item)
    assert item.escalation_reason != "brief_unread"
    assert item.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_brief_unread_escalates_after_delivery_retries_exhausted(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    preset, slots, scope = await _team(db)
    stale = datetime.utcnow() - timedelta(
        seconds=max(
            settings.github_owner_registration_grace_seconds,
            settings.github_nudge_grace_seconds,
        )
        + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=91,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=stale,
        updated_at=stale,
        brief_delivery_nudge_count=settings.github_brief_delivery_max_nudges,
        brief_delivery_nudge_at=stale,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item)

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[0].id: "wakeable", slots[1].id: "wakeable"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "brief_unread"


@pytest.mark.asyncio
async def test_brief_unread_is_not_masked_by_leader_ack_timeout(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    preset, slots, scope = await _team(db)
    stale = datetime.utcnow() - timedelta(
        seconds=max(
            settings.github_owner_registration_grace_seconds,
            settings.github_leader_ack_timeout_seconds,
            settings.github_nudge_grace_seconds,
        )
        + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=92,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=stale,
        updated_at=stale,
        ack_received_at=None,
        last_nudge_at=stale,
        brief_delivery_nudge_count=settings.github_brief_delivery_max_nudges,
        brief_delivery_nudge_at=stale,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item)

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[0].id: "wakeable", slots[1].id: "wakeable"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "brief_unread"


@pytest.mark.asyncio
async def test_delivery_and_ack_nudge_counters_are_independent(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    preset, slots, scope = await _team(db)
    leader, owner = slots
    await agent_mail_service.get_or_create_slot_member(db, leader)
    owner_member = await agent_mail_service.get_or_create_slot_member(db, owner)
    stale = datetime.utcnow() - timedelta(
        seconds=max(
            settings.github_owner_registration_grace_seconds,
            settings.github_leader_ack_timeout_seconds,
        )
        + 1
    )
    unread_item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=93,
        issue_title="unread",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=owner.id,
        dispatched_at=stale,
        updated_at=stale,
    )
    delivered_item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=94,
        issue_title="delivered",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=owner.id,
        dispatched_at=stale,
        updated_at=stale,
    )
    db.add_all([unread_item, delivered_item])
    await db.commit()
    unread_message = await agent_mail_service.send_direct_message(
        db,
        recipient_member_id=owner_member.id,
        subject="brief",
        body_markdown="b",
        auto_nudge=False,
    )
    unread_item.brief_message_id = unread_message.id
    await _lease_for(db, scope, unread_item)
    await _lease_for(
        db,
        scope,
        delivered_item,
        lease_last_owner_contact_at=datetime.utcnow(),
    )

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={leader.id: "wakeable", owner.id: "wakeable"},
    )

    await db.refresh(unread_item)
    await db.refresh(delivered_item)
    assert unread_item.brief_delivery_nudge_count == 1
    assert unread_item.last_nudge_at is None
    assert delivered_item.last_nudge_at is not None
    assert delivered_item.brief_delivery_nudge_at is None


@pytest.mark.asyncio
async def test_brief_read_after_first_nudge_does_not_escalate(db, monkeypatch):
    _isolate_agent_mail_nudges(monkeypatch)
    preset, slots, scope = await _team(db)
    stale = datetime.utcnow() - timedelta(
        seconds=max(
            settings.github_owner_registration_grace_seconds,
            settings.github_nudge_grace_seconds,
        )
        + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=95,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        dispatched_at=stale,
        updated_at=datetime.utcnow(),
        ack_received_at=datetime.utcnow(),
        brief_delivery_nudge_count=settings.github_brief_delivery_max_nudges,
        brief_delivery_nudge_at=stale,
    )
    db.add(item)
    await db.commit()
    member = await agent_mail_service.get_or_create_slot_member(db, slots[1])
    message = await agent_mail_service.send_direct_message(
        db,
        recipient_member_id=member.id,
        subject="brief",
        body_markdown="b",
        auto_nudge=False,
    )
    item.brief_message_id = message.id
    receipt = (
        await db.execute(
            select(MailReceipt).where(
                MailReceipt.message_id == message.id,
                MailReceipt.member_id == member.id,
            )
        )
    ).scalar_one()
    receipt.read_at = datetime.utcnow()
    await _lease_for(db, scope, item)

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[0].id: "wakeable", slots[1].id: "wakeable"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_when_leader_offline(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    past_registration_grace = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_registration_grace_seconds + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=50,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
        updated_at=past_registration_grace,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "offline", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "leader_offline"


@pytest.mark.asyncio
async def test_monitor_leaves_newly_dispatched_item_when_leader_offline(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=53,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "offline", slots[1].id: "wakeable"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_when_owner_offline(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    past_registration_grace = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_registration_grace_seconds + 1
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=51,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        updated_at=past_registration_grace,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "offline"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_offline"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any("owner_offline" in (message.subject or "") for message in messages)


@pytest.mark.asyncio
async def test_monitor_leaves_newly_dispatched_item_when_owner_offline(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=54,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", backend.id: "offline"},
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_does_not_escalate_slow_live_owner(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    for wake_state in ("wakeable", "delivered_waiting"):
        item = GithubWorkItem(
            scope_id=scope.id,
            issue_number=60 if wake_state == "wakeable" else 61,
            issue_title="x",
            issue_url="u",
            github_updated_at=datetime.utcnow(),
            dispatch_status="dispatched",
            owner_slot_id=backend.id,
        )
        db.add(item)
        await db.commit()

        await github_dispatch_service.monitor_dispatched(
            db,
            scope,
            preset_slots=slots,
            wake_state_by_slot={architect.id: "wakeable", backend.id: wake_state},
        )

        await db.refresh(item)
        assert item.dispatch_status == "dispatched"
        assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_nudges_leader_on_ack_timeout(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=920,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item, lease_last_owner_contact_at=old)

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_retried_item_still_nudged_when_leader_never_acks_again(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    dispatched_at = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=819,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=dispatched_at,
        ack_received_at=dispatched_at - timedelta(hours=1),
        updated_at=dispatched_at,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item, lease_last_owner_contact_at=dispatched_at)

    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={
            architect.id: "wakeable",
            backend.id: "wakeable",
        },
    )

    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_leader_ack_after_nudge_grace(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    nudged = datetime.utcnow() - timedelta(seconds=settings.github_nudge_grace_seconds + 5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=921,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
        last_nudge_at=nudged,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item, lease_last_owner_contact_at=old)

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "leader_ack_timeout"


@pytest.mark.asyncio
async def test_monitor_design_item_uses_ack_multiplier(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    age = (
        settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    assert age < settings.github_leader_ack_timeout_seconds * settings.github_design_ack_multiplier
    old = datetime.utcnow() - timedelta(seconds=age)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=922,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        issue_type="design",
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None


@pytest.mark.asyncio
async def test_monitor_no_ack_action_when_ack_received(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=923,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=datetime.utcnow(),
        ack_received_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_ack_timeout_uses_dispatched_at_not_recent_activity(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_leader_ack_timeout_seconds
        + settings.github_owner_registration_grace_seconds
        + 10
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=924,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item, lease_last_owner_contact_at=old)

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_nudges_idle_owner_after_ack(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 30
    )
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=930,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        updated_at=old,
        ack_received_at=old,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item, lease_last_owner_contact_at=old)

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.last_nudge_at is not None
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_idle_owner_activity_resets_clock(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 30
    )
    nudged = old + timedelta(seconds=1)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=931,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        ack_received_at=old,
        last_nudge_at=nudged,
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    await db.commit()

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_monitor_escalates_idle_owner_after_nudge_grace(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    old = datetime.utcnow() - timedelta(
        seconds=settings.github_owner_idle_timeout_seconds + 60
    )
    nudged = datetime.utcnow() - timedelta(seconds=settings.github_nudge_grace_seconds + 5)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=932,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=backend.id,
        dispatched_at=old,
        ack_received_at=old,
        updated_at=old,
        last_nudge_at=nudged,
    )
    db.add(item)
    await db.commit()
    await _lease_for(db, scope, item, lease_last_owner_contact_at=old)

    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots, wake_state_by_slot={architect.id: "wakeable", backend.id: "wakeable"}
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "owner_idle_timeout"


@pytest.mark.asyncio
async def test_monitor_leaves_item_when_leader_reachable(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=51,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_monitor_leaves_item_when_leader_not_registered_yet(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=52,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="dispatched",
        owner_slot_id=slots[1].id,
    )
    db.add(item)
    await db.commit()
    await github_dispatch_service.monitor_dispatched(
        db,
        scope,
        preset_slots=slots,
        wake_state_by_slot={slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_no_workspace_is_available(db):
    preset, slots, scope = await _team(db)
    await db.execute(delete(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id))
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=950,
        issue_title="No workspace",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(*_args, **_kwargs):
        raise AssertionError("launcher must not run without a workspace")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={950: ["area:backend"]},
    )

    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_no_workspace"
    assert item.owner_slot_id == slots[1].id
    assert item.routing_method == "label"


@pytest.mark.asyncio
async def test_prepared_dispatch_reuses_persisted_owner_head_and_route(db, monkeypatch):
    _, slots, scope = await _team(db)
    owner = slots[1]
    nonce = "0123456789abcdef"
    head = f"deck/slot-{owner.id}/issue-960-{nonce}"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=960,
        issue_title="Prepared",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
        owner_slot_id=owner.id,
        routing_method="label",
        dispatch_nonce=nonce,
        dispatch_head_ref=head,
        dispatch_base_ref="origin/master",
        approval_round_count=1,
    )
    db.add(item)
    await db.commit()

    async def forbidden_route(*_args, **_kwargs):
        raise AssertionError("prepared attempts must not be re-routed")

    monkeypatch.setattr(github_dispatch_service, "route_item", forbidden_route)
    captured = {}

    class _Result:
        launch_id = 960
        items = []

    async def fake_launcher(db_, preset_id, request):
        captured["request"] = request
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={960: ["changed-label"]},
    )

    request = captured["request"]
    assert request.slot_ids == [owner.id]
    assert request.slot_prompt_overrides[owner.id].count(head) >= 1
    assert item.owner_slot_id == owner.id
    assert item.routing_method == "label"
    assert item.dispatch_nonce == nonce
    assert item.dispatch_head_ref == head


@pytest.mark.asyncio
async def test_torn_attempt_escalates_without_aborting_next_item(db):
    _, slots, scope = await _team(db)
    torn = GithubWorkItem(
        scope_id=scope.id,
        issue_number=961,
        issue_title="Torn",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
        owner_slot_id=slots[1].id,
        routing_method="label",
        dispatch_nonce="0123456789abcdef",
        approval_round_count=1,
    )
    healthy = GithubWorkItem(
        scope_id=scope.id,
        issue_number=962,
        issue_title="Healthy",
        issue_url="u",
        github_updated_at=datetime.utcnow() + timedelta(microseconds=1),
        dispatch_status="pending",
    )
    db.add_all([torn, healthy])
    await db.commit()

    class _Result:
        launch_id = 962
        items = []

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={962: ["area:backend"]},
    )

    assert torn.dispatch_status == "escalated"
    assert torn.escalation_reason == "plan_blocked"
    assert torn.dispatch_nonce == "0123456789abcdef"
    assert torn.dispatch_head_ref is None
    assert healthy.dispatch_status == "dispatched"


@pytest.mark.asyncio
async def test_disabled_prepared_owner_keeps_attempt_and_lease(db):
    _, slots, scope = await _team(db)
    owner = slots[1]
    owner.enabled = False
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=963,
        issue_title="Unavailable owner",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
        owner_slot_id=owner.id,
        routing_method="label",
        dispatch_nonce="0123456789abcdef",
        dispatch_head_ref=f"deck/slot-{owner.id}/issue-963-0123456789abcdef",
        dispatch_base_ref="origin/master",
        approval_round_count=1,
    )
    db.add(item)
    await db.flush()
    workspace = await github_workspace_service.acquire(db, scope, item)
    await db.commit()

    async def forbidden_launcher(*_args, **_kwargs):
        raise AssertionError("unavailable prepared owners must not launch")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=forbidden_launcher,
    )

    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "prepared_owner_unavailable"
    assert "Do not retry" in item.status_note
    assert item.dispatch_head_ref in item.status_note
    assert workspace.leased_item_id == item.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "launch_status",
    [
        "failed",
        "blocked",
        "blocked_provider_unavailable",
        "blocked_agent_mail_not_configured",
        "skipped_disabled",
    ],
)
async def test_known_launch_failure_releases_workspace(db, launch_status):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=951,
        issue_title="Launch failure",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = launch_status
        tmux_target = None

    class _Result:
        launch_id = 951
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={951: ["area:backend"]},
    )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()
    assert item.dispatch_status == "failed"
    assert workspace.leased_item_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("launch_status", ["pending_registration", "reused", "spawned"])
async def test_success_or_unknown_launch_status_retains_workspace(db, launch_status):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=952,
        issue_title="Launch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = launch_status
        tmux_target = "deck:0.0" if launch_status != "spawned" else None

    class _Result:
        launch_id = 952
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={952: ["area:backend"]},
    )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one()
    assert workspace.path == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_tmux_target_vetoes_release_for_failure_status(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=953,
        issue_title="Ambiguous launch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    class _LaunchItem:
        status = "failed"
        tmux_target = "deck:0.0"

    class _Result:
        launch_id = 953
        items = [_LaunchItem()]

    async def fake_launcher(*_args, **_kwargs):
        return _Result()

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={953: ["area:backend"]},
    )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one()
    assert workspace.path == "/tmp/r-ws-1"


@pytest.mark.asyncio
async def test_value_error_releases_lease_immediately(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=954,
        issue_title="Plan blocked",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(*_args, **_kwargs):
        raise ValueError("blocked plan")

    await github_dispatch_service.dispatch_pending(
        db,
        scope,
        slots,
        launcher=fake_launcher,
        issue_labels_by_number={954: ["area:backend"]},
    )

    workspaces = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id)
        )
    ).scalars().all()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "plan_blocked"
    assert all(workspace.leased_item_id != item.id for workspace in workspaces)
    assert await github_workspace_service.reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_unexpected_launch_exception_retains_lease_and_escalates(db):
    _, slots, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=955,
        issue_title="Unknown launch",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="pending",
    )
    db.add(item)
    await db.commit()

    async def fake_launcher(*_args, **_kwargs):
        raise RuntimeError("commit failed after spawn")

    with pytest.raises(RuntimeError, match="commit failed after spawn"):
        await github_dispatch_service.dispatch_pending(
            db,
            scope,
            slots,
            launcher=fake_launcher,
            issue_labels_by_number={955: ["area:backend"]},
        )

    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
        )
    ).scalar_one()
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "launch_outcome_unknown"
    assert workspace.leased_item_id == item.id


@pytest.mark.asyncio
async def test_dispatch_brief_renders_out_of_tree_build_hints(db):
    _, slots, scope = await _team(db)
    scope.builds_out_of_tree = True
    scope.build_dir_template = "build-{issue_number}"
    scope.build_command_hint = "meson compile -C {build_dir} -j{parallelism}"
    scope.max_build_parallelism = 4
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=956,
        issue_title="Build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    assert "build-956" in brief
    assert "meson compile -C build-956 -j4" in brief
    assert "Cap build parallelism at -j4" in brief


@pytest.mark.asyncio
async def test_dispatch_brief_describes_in_tree_build_limit(db):
    _, slots, scope = await _team(db)
    scope.builds_out_of_tree = False
    scope.build_command_hint = "make -C {build_dir} -j{parallelism}"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=957,
        issue_title="Build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    assert "Only one build may run in this workspace at a time" in brief
    assert "build-957" not in brief


@pytest.mark.asyncio
async def test_dispatch_brief_contains_malformed_build_template(db):
    _, slots, scope = await _team(db)
    scope.builds_out_of_tree = True
    scope.build_dir_template = "build-{issue_number"
    scope.build_command_hint = "make -C {build_dir} -j{parallelism}"
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=958,
        issue_title="Build",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
    )
    workspace = (
        await db.execute(
            select(GithubWorkspace).where(GithubWorkspace.scope_id == scope.id).order_by(GithubWorkspace.id)
        )
    ).scalars().first()

    brief = github_dispatch_service._dispatch_brief(
        item,
        scope,
        workspace,
        owner_slot_id=slots[1].id,
        preset_slots=slots,
    )

    assert "Issue: #958" in brief
    assert "make -C" not in brief
