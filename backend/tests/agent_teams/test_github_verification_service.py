"""GitHub PR verification and merge pipeline tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.config import settings
from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    GithubWorkItem,
    GithubWorkspace,
    MailMessage,
    MailTeamMember,
    TeamGithubScope,
)
from app.services.github_verification_service import github_verification_service
from app.services.github_app_auth_service import (
    GithubAppNotInstalled,
    github_app_auth_service,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _scope(db, **kwargs):
    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    values = {
        "preset_id": preset.id,
        "repo_owner": "o",
        "repo_name": "r",
        "repo_path": "/tmp/r",
    }
    values.update(kwargs)
    scope = TeamGithubScope(
        **values,
    )
    db.add(scope)
    await db.flush()
    return scope


async def _item(db, scope, **kwargs):
    values = {
        "scope_id": scope.id,
        "issue_number": 1,
        "issue_title": "x",
        "issue_url": "u",
        "github_updated_at": datetime.utcnow(),
        "dispatch_status": "dispatched",
        "dispatch_head_ref": "deck/slot-1/issue-1/attempt",
    }
    values.update(kwargs)
    if scope.merge_policy == "auto" and "ack_approver_member_id" not in values:
        slots = (
            await db.execute(
                select(AgentTeamSlot)
                .where(AgentTeamSlot.preset_id == scope.preset_id)
                .order_by(AgentTeamSlot.position, AgentTeamSlot.id)
            )
        ).scalars().all()
        if len(slots) < 2:
            slots = []
            for position, name in enumerate(("Leader", "Owner")):
                slot = AgentTeamSlot(
                    preset_id=scope.preset_id,
                    position=position,
                    display_name=name,
                    provider="codex-cli",
                    repo_id="r",
                    repo_path="/tmp/r",
                    repo_name="r",
                    enabled=True,
                )
                db.add(slot)
                slots.append(slot)
            await db.flush()
        leader_slot, owner_slot = slots[:2]
        members = {}
        for slot in (leader_slot, owner_slot):
            member = (
                await db.execute(
                    select(MailTeamMember)
                    .where(MailTeamMember.team_slot_id == slot.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if member is None:
                member = MailTeamMember(
                    identity_key=f"auto:{slot.id}",
                    repo_id="r",
                    repo_path="/tmp/r",
                    repo_name="r",
                    display_name=slot.display_name,
                    participant_kind="team_slot",
                    team_preset_id=scope.preset_id,
                    team_slot_id=slot.id,
                )
                db.add(member)
                await db.flush()
            members[slot.id] = member
        leader_member = members[leader_slot.id]
        values.update(
            owner_slot_id=owner_slot.id,
            approval_round_count=1,
            ack_approver_member_id=leader_member.id,
            ack_enforcement_epoch=1,
            ack_approval_round=1,
        )
    item = GithubWorkItem(
        **values,
    )
    db.add(item)
    await db.commit()
    return item


@pytest.fixture(autouse=True)
def capability_enforcement(monkeypatch):
    monkeypatch.setattr(settings, "mail_capability_tokens_required", True)


async def _owner(db, scope):
    slot = AgentTeamSlot(
        preset_id=scope.preset_id,
        position=0,
        display_name="Owner",
        provider="codex-cli",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
    )
    db.add(slot)
    await db.flush()
    member = MailTeamMember(
        identity_key=f"slot:{slot.id}",
        repo_id="r",
        repo_path="/tmp/r",
        repo_name="r",
        display_name="Owner",
        participant_kind="team_slot",
        team_preset_id=scope.preset_id,
        team_slot_id=slot.id,
    )
    db.add(member)
    await db.flush()
    return slot, member


@pytest.mark.asyncio
async def test_mark_merged_does_not_release_workspace(db):
    scope = await _scope(db)
    item = await _item(db, scope)
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path="/tmp/r-ws-1",
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()

    github_verification_service._mark_merged(item)
    await db.commit()

    assert item.dispatch_status == "merged"
    assert workspace.leased_item_id == item.id


class _Client:
    def __init__(
        self,
        *,
        pull=None,
        check_runs=None,
        combined_status=None,
        merge_result=None,
        merge_error: httpx.HTTPStatusError | None = None,
        ready_error: httpx.HTTPStatusError | None = None,
    ):
        self.pull = dict(
            pull
            or {
                "number": 5,
                "node_id": "node",
                "draft": True,
                "merged": False,
                "mergeable_state": "clean",
                "head": {"sha": "sha"},
            }
        )
        merged = bool(self.pull.get("merged"))
        self.pull.setdefault("state", "closed" if merged else "open")
        self.pull.setdefault(
            "merged_at", "2026-08-14T12:00:00Z" if merged else None
        )
        self.check_runs = check_runs if check_runs is not None else []
        self.combined_status = (
            combined_status
            if combined_status is not None
            else {"state": "pending", "statuses": []}
        )
        self.merge_result = merge_result or {"merged": True}
        self.merge_error = merge_error
        self.ready_error = ready_error
        self.ready_calls = 0
        self.merge_calls = 0
        self.pull_calls = 0

    async def get_pull(self, owner, repo, pr_number):
        self.pull_calls += 1
        return dict(self.pull)

    async def list_check_runs_for_ref(self, owner, repo, ref):
        return list(self.check_runs)

    async def get_combined_status_for_ref(self, owner, repo, ref):
        return dict(self.combined_status)

    async def mark_pull_ready_for_review(self, pull_node_id):
        self.ready_calls += 1
        if self.ready_error is not None:
            raise self.ready_error
        return {"ok": True}

    async def merge_pull(self, owner, repo, pr_number):
        self.merge_calls += 1
        if self.merge_error is not None:
            raise self.merge_error
        return self.merge_result


def _reported_client(scope, item, pr_number):
    full_name = f"{scope.repo_owner}/{scope.repo_name}"
    return _Client(
        pull={
            "number": pr_number,
            "node_id": f"node-{pr_number}",
            "draft": True,
            "merged": False,
            "state": "open",
            "merged_at": None,
            "mergeable_state": "clean",
            "head": {
                "sha": "sha",
                "ref": item.dispatch_head_ref,
                "repo": {"full_name": full_name},
            },
            "base": {"repo": {"full_name": full_name}},
            "user": {"login": "human"},
        }
    )


def _attempt_pull(scope, item, number, *, state="open", merged_at=None, author="deck[bot]"):
    full_name = f"{scope.repo_owner}/{scope.repo_name}"
    return {
        "number": number,
        "state": state,
        "merged_at": merged_at,
        "draft": item.issue_type != "design",
        "head": {
            "sha": f"sha-{number}",
            "ref": item.dispatch_head_ref,
            "repo": {"full_name": full_name},
        },
        "base": {"repo": {"full_name": full_name}},
        "user": {"login": author},
    }


class _PrReadyClient:
    def __init__(self, scope, item, *, pulls=None, created=None, create_error=None):
        self.scope = scope
        self.item = item
        self.pull_batches = list(pulls or [[]])
        self.created = created or _attempt_pull(scope, item, 21, author="unexpected")
        self.create_error = create_error
        self.calls = []
        self.create_calls = 0

    async def get_ref(self, owner, repo, head, *, token):
        self.calls.append(("ref", token, head))
        return {"ref": f"refs/heads/{head}"}

    async def get_repository(self, owner, repo, *, token):
        self.calls.append(("repository", token))
        return {"default_branch": "master"}

    async def list_pulls_for_head(self, owner, repo, *, head, base, state, token):
        self.calls.append(("list", token, head, base, state))
        return list(self.pull_batches.pop(0) if self.pull_batches else [])

    async def create_pull(self, owner, repo, **kwargs):
        self.create_calls += 1
        self.calls.append(("create", kwargs["token"], kwargs))
        if self.create_error is not None:
            raise self.create_error
        return dict(self.created)


async def _pr_ready_item(db, *, issue_type="code", base_ref="origin/master"):
    scope = await _scope(
        db,
        github_auth_mode="app",
        github_app_installation_id=55,
        base_ref=base_ref,
    )
    owner, _ = await _owner(db, scope)
    item = await _item(
        db,
        scope,
        issue_type=issue_type,
        owner_slot_id=owner.id,
        dispatch_nonce="nonce",
    )
    db.add(
        GithubWorkspace(
            scope_id=scope.id,
            path=f"/tmp/pr-ready-{item.id}",
            leased_item_id=item.id,
            lease_token="lease",
        )
    )
    await db.commit()
    return scope, owner, item


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("PUT", "https://api.github.com/repos/o/r/pulls/5/merge")
    response = httpx.Response(status_code, request=request, json={"message": "blocked"})
    return httpx.HTTPStatusError("blocked", request=request, response=response)


@pytest.mark.parametrize(
    ("pull", "expected"),
    [
        ({"state": "open", "merged_at": None}, "open"),
        ({"state": "closed", "merged_at": "2026-08-14T12:00:00Z"}, "merged"),
        ({"state": "closed", "merged_at": None}, "closed_unmerged"),
        ({"state": "open", "merged_at": "2026-08-14T12:00:00Z"}, None),
        ({"state": "unknown", "merged_at": None}, None),
        ({"merged_at": None}, None),
        ({"state": "closed"}, None),
    ],
)
def test_pull_classifier_uses_only_state_and_merged_at(pull, expected):
    poisoned = {
        **pull,
        "merged": expected != "merged",
        "merge_commit_sha": "looks-merged-but-is-not-authoritative",
    }

    assert github_verification_service._classify_pull(poisoned) == expected


@pytest.mark.asyncio
async def test_pr_ready_creates_with_one_explicit_token_and_records_response(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **kwargs: None,
    )

    async def mint(installation_id, owner, repo):
        assert (installation_id, owner, repo) == (55, "o", "r")
        return "installation-token"

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", mint)
    scope, owner, item = await _pr_ready_item(db, base_ref="origin/HEAD")
    client = _PrReadyClient(scope, item)

    number = await github_verification_service.report_pr_ready(
        db,
        item,
        scope,
        item.dispatch_head_ref,
        "lease",
        client,
    )

    assert number == 21
    assert item.pr_number == 21
    assert item.dispatch_status == "verifying"
    assert client.create_calls == 1
    assert {call[1] for call in client.calls} == {"installation-token"}
    create = next(call[2] for call in client.calls if call[0] == "create")
    assert create["head"] == item.dispatch_head_ref
    assert create["base"] == "master"
    assert create["draft"] is True
    assert create["title"] == f"[{owner.display_name}] x (#1)"
    assert "Work item" in create["body"]


@pytest.mark.asyncio
async def test_pr_ready_mint_404_preserves_persisted_app_mode(db, monkeypatch):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **kwargs: None,
    )

    async def missing(installation_id, owner, repo):
        raise GithubAppNotInstalled(owner, repo, installation_id)

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", missing)
    scope, _, item = await _pr_ready_item(db)
    client = _PrReadyClient(scope, item)

    with pytest.raises(ValueError, match="app_not_installed"):
        await github_verification_service.report_pr_ready(
            db, item, scope, item.dispatch_head_ref, "lease", client
        )

    await db.refresh(scope)
    assert scope.github_auth_mode == "app"
    assert scope.github_app_installation_id == 55
    assert client.calls == []


@pytest.mark.asyncio
async def test_pr_ready_cheap_return_still_authorizes_head_and_lease(
    db, monkeypatch
):
    scope, _, item = await _pr_ready_item(db)
    item.pr_number = 31
    item.dispatch_status = "verifying"
    await db.commit()
    client = _PrReadyClient(scope, item)

    async def should_not_mint(*args, **kwargs):
        raise AssertionError("cheap return must not mint")

    monkeypatch.setattr(
        github_app_auth_service,
        "mint_repository_token",
        should_not_mint,
    )

    assert await github_verification_service.report_pr_ready(
        db, item, scope, item.dispatch_head_ref, "lease", client
    ) == 31
    with pytest.raises(ValueError, match="prepared dispatch head"):
        await github_verification_service.report_pr_ready(
            db, item, scope, "deck/wrong", "lease", client
        )
    with pytest.raises(ValueError, match="workspace_lease_changed"):
        await github_verification_service.report_pr_ready(
            db, item, scope, item.dispatch_head_ref, "stale", client
        )
    assert client.calls == []


@pytest.mark.asyncio
async def test_pr_ready_reconciliation_precedence_and_diagnostics(db, monkeypatch):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    scope, _, item = await _pr_ready_item(db)
    open_pull = _attempt_pull(scope, item, 8)
    closed_irrelevant_author = _attempt_pull(
        scope, item, 7, state="closed", author="someone-else"
    )

    selected = await github_verification_service._reconcile_attempt_pulls(
        db,
        scope,
        item,
        [closed_irrelevant_author, open_pull],
        verify_author=True,
    )

    assert selected == 8
    assert item.pr_number == 8
    assert item.dispatch_status == "verifying"

    scope2, _, item2 = await _pr_ready_item(db)
    first = _attempt_pull(scope2, item2, 10)
    second = _attempt_pull(scope2, item2, 11)
    with pytest.raises(ValueError, match="#10, #11"):
        await github_verification_service._reconcile_attempt_pulls(
            db, scope2, item2, [first, second], verify_author=True
        )
    assert item2.pr_number is None
    assert item2.dispatch_status == "dispatched"
    assert item2.status_note.endswith("#10, #11")


@pytest.mark.asyncio
async def test_pr_ready_rejects_any_unclassifiable_result_without_writes(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    scope, _, item = await _pr_ready_item(db)
    valid = _attempt_pull(scope, item, 8)
    invalid = {**_attempt_pull(scope, item, 9), "state": "mystery"}
    before = {
        column.name: getattr(item, column.name)
        for column in GithubWorkItem.__table__.columns
    }

    with pytest.raises(ValueError, match="unclassifiable.*9"):
        await github_verification_service._reconcile_attempt_pulls(
            db, scope, item, [valid, invalid], verify_author=True
        )

    after = {
        column.name: getattr(item, column.name)
        for column in GithubWorkItem.__table__.columns
    }
    assert after == before


@pytest.mark.asyncio
async def test_pr_ready_timeout_reconciles_without_blind_create(db, monkeypatch):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **kwargs: None,
    )

    async def mint(*args):
        return "installation-token"

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", mint)
    scope, _, item = await _pr_ready_item(db)
    timeout = httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("POST", "https://api.github.com"),
    )
    client = _PrReadyClient(
        scope,
        item,
        pulls=[[], [_attempt_pull(scope, item, 33)]],
        create_error=timeout,
    )

    number = await github_verification_service.report_pr_ready(
        db, item, scope, item.dispatch_head_ref, "lease", client
    )

    assert number == 33
    assert client.create_calls == 1
    assert [call[0] for call in client.calls].count("list") == 2


@pytest.mark.asyncio
async def test_pr_ready_terminal_history_uses_precedence_and_keeps_diagnostics(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    scope, _, item = await _pr_ready_item(db)
    closed = _attempt_pull(scope, item, 12, state="closed")
    merged_low = _attempt_pull(
        scope,
        item,
        13,
        state="closed",
        merged_at="2026-08-14T12:00:00Z",
    )
    merged_high = _attempt_pull(
        scope,
        item,
        15,
        state="closed",
        merged_at="2026-08-14T12:01:00Z",
    )

    selected = await github_verification_service._reconcile_attempt_pulls(
        db,
        scope,
        item,
        [closed, merged_low, merged_high],
        verify_author=True,
    )

    assert selected == 15
    assert item.dispatch_status == "merged"
    assert item.pr_number == 15
    assert item.status_note.endswith("#13, #15")

    scope2, _, item2 = await _pr_ready_item(db)
    only_closed = _attempt_pull(scope2, item2, 18, state="closed")
    with pytest.raises(ValueError, match="#18"):
        await github_verification_service._reconcile_attempt_pulls(
            db, scope2, item2, [only_closed], verify_author=True
        )
    assert item2.dispatch_status == "escalated"
    assert item2.escalation_reason == "pr_closed_unmerged"
    assert item2.pr_number is None


@pytest.mark.asyncio
async def test_pr_ready_serializes_same_item_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    monkeypatch.setattr(
        github_app_auth_service,
        "require_configuration",
        lambda **kwargs: None,
    )

    async def mint(*args):
        return "installation-token"

    monkeypatch.setattr(github_app_auth_service, "mint_repository_token", mint)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pr-ready.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as setup:
        scope, _, item = await _pr_ready_item(setup)
        scope_id = scope.id
        item_id = item.id

    create_entered = asyncio.Event()
    allow_create = asyncio.Event()

    class YieldingClient(_PrReadyClient):
        async def create_pull(self, owner, repo, **kwargs):
            self.create_calls += 1
            self.calls.append(("create", kwargs["token"], kwargs))
            create_entered.set()
            await allow_create.wait()
            return dict(self.created)

    async with maker() as first_db, maker() as second_db:
        first_scope = await first_db.get(TeamGithubScope, scope_id)
        first_item = await first_db.get(GithubWorkItem, item_id)
        second_scope = await second_db.get(TeamGithubScope, scope_id)
        second_item = await second_db.get(GithubWorkItem, item_id)
        client = YieldingClient(first_scope, first_item)

        first = asyncio.create_task(
            github_verification_service.report_pr_ready(
                first_db,
                first_item,
                first_scope,
                first_item.dispatch_head_ref,
                "lease",
                client,
            )
        )
        await create_entered.wait()
        second = asyncio.create_task(
            github_verification_service.report_pr_ready(
                second_db,
                second_item,
                second_scope,
                second_item.dispatch_head_ref,
                "lease",
                client,
            )
        )
        await asyncio.sleep(0)
        allow_create.set()
        assert await asyncio.gather(first, second) == [21, 21]

    assert client.create_calls == 1
    assert [call[0] for call in client.calls].count("list") == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_report_pr_opened_enforces_app_repo_head_and_author(
    db, monkeypatch
):
    monkeypatch.setattr(settings, "github_app_bot_login", "deck[bot]")
    scope = await _scope(
        db,
        github_auth_mode="app",
        github_app_installation_id=55,
    )
    item = await _item(db, scope)
    client = _reported_client(scope, item, 7)

    client.pull["base"]["repo"]["full_name"] = "other/repo"
    with pytest.raises(ValueError, match="repository"):
        await github_verification_service.report_pr_opened(
            db, item, scope, 7, client
        )
    assert item.pr_number is None

    client = _reported_client(scope, item, 7)
    client.pull["head"]["ref"] = "deck/wrong-attempt"
    with pytest.raises(ValueError, match="head"):
        await github_verification_service.report_pr_opened(
            db, item, scope, 7, client
        )
    assert item.pr_number is None

    client = _reported_client(scope, item, 7)
    with pytest.raises(ValueError, match="author"):
        await github_verification_service.report_pr_opened(
            db, item, scope, 7, client
        )
    assert item.pr_number is None

    client.pull["user"]["login"] = "deck[bot]"
    await github_verification_service.report_pr_opened(db, item, scope, 7, client)
    assert item.pr_number == 7


@pytest.mark.asyncio
async def test_report_pr_opened_app_mode_requires_bot_login(db, monkeypatch):
    monkeypatch.setattr(settings, "github_app_bot_login", "")
    scope = await _scope(
        db,
        github_auth_mode="app",
        github_app_installation_id=55,
    )
    item = await _item(db, scope)

    with pytest.raises(ValueError, match="app_mode_bot_login_unset"):
        await github_verification_service.report_pr_opened(
            db, item, scope, 7, _reported_client(scope, item, 7)
        )
    assert item.pr_number is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["ambient", "unknown"])
async def test_report_pr_opened_non_app_modes_skip_author(db, mode):
    scope = await _scope(db, github_auth_mode=mode)
    item = await _item(db, scope)

    await github_verification_service.report_pr_opened(
        db, item, scope, 7, _reported_client(scope, item, 7)
    )

    assert item.pr_number == 7
    assert item.dispatch_status == "verifying"


@pytest.mark.asyncio
async def test_report_pr_opened_merged_design_skips_review_mail(db):
    scope = await _scope(db)
    item = await _item(db, scope, issue_type="design")
    client = _reported_client(scope, item, 8)
    client.pull.update(
        state="closed",
        merged=True,
        merged_at="2026-08-14T12:00:00Z",
    )

    await github_verification_service.report_pr_opened(db, item, scope, 8, client)

    assert item.pr_number == 8
    assert item.dispatch_status == "merged"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not any(message.subject == "Design PR ready for review" for message in messages)


@pytest.mark.asyncio
async def test_report_pr_opened_closed_unmerged_is_silent(db):
    scope = await _scope(db)
    item = await _item(db, scope, issue_type="design")
    client = _reported_client(scope, item, 9)
    client.pull.update(
        state="closed",
        merged=False,
        merged_at=None,
        merge_commit_sha="not-proof-of-merge",
    )

    await github_verification_service.report_pr_opened(db, item, scope, 9, client)

    assert item.pr_number is None
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "pr_closed_unmerged"
    assert "#9" in item.status_note
    assert (await db.execute(select(MailMessage))).scalars().all() == []


@pytest.mark.asyncio
async def test_verifier_classifies_closed_before_checks(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        pull={
            "number": 5,
            "state": "closed",
            "merged_at": None,
            "merge_commit_sha": "not-proof-of-merge",
            "draft": True,
            "head": {"sha": "sha"},
        },
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}],
    )

    await github_verification_service.process_scope(db, scope, client=client)

    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "pr_closed_unmerged"
    assert client.ready_calls == 0


@pytest.mark.asyncio
async def test_unclassifiable_pull_consumes_retry_budget(db):
    scope = await _scope(db, max_verification_retries=2)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client()
    del client.pull["merged_at"]

    for _ in range(3):
        item.dispatch_status = "verifying"
        await db.commit()
        await github_verification_service.process_scope(db, scope, client=client)

    assert item.retry_count == 3
    assert item.last_verified_sha is None
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"


@pytest.mark.asyncio
async def test_outer_http_failure_preserves_human_merge_reservation(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(
        db,
        scope,
        dispatch_status="ready_for_review",
        pr_number=5,
        status_note="Auto-merge blocked: human owns this merge.",
    )

    class _FailOnce(_Client):
        async def get_pull(self, owner, repo, pr_number):
            if self.pull_calls == 0:
                self.pull_calls += 1
                raise _http_error(503)
            return await super().get_pull(owner, repo, pr_number)

    client = _FailOnce()
    expected = item.status_note

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)

    assert item.status_note == expected
    assert client.merge_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("base_ref", "expected", "default_branch", "expected_calls"),
    [
        ("origin/main", "main", "unused", 0),
        ("release/v2", "release/v2", "unused", 0),
        ("origin/HEAD", "trunk", "trunk", 1),
    ],
)
async def test_base_ref_normalization(
    db, base_ref, expected, default_branch, expected_calls
):
    scope = await _scope(db, base_ref=base_ref)

    class _RepositoryClient:
        calls = 0

        async def get_repository(self, owner, repo, *, token):
            self.calls += 1
            assert token == "app-token"
            return {"default_branch": default_branch}

    client = _RepositoryClient()

    assert await github_verification_service.normalize_base_ref(
        scope, client, token="app-token"
    ) == expected
    assert client.calls == expected_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("base_ref", ["HEAD", "refs/heads/main", "origin/", "bad ref"])
async def test_base_ref_normalization_refuses_unsupported_values(db, base_ref):
    scope = await _scope(db, base_ref=base_ref)

    class _NoNetwork:
        async def get_repository(self, *_args, **_kwargs):
            raise AssertionError("invalid static refs must refuse before network")

    with pytest.raises(ValueError):
        await github_verification_service.normalize_base_ref(
            scope, _NoNetwork(), token="app-token"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(("issue_type", "draft"), [("code", True), ("design", False)])
async def test_pull_presentation_is_deterministic(db, issue_type, draft):
    scope = await _scope(db)
    owner, _ = await _owner(db, scope)
    item = await _item(
        db,
        scope,
        owner_slot_id=owner.id,
        issue_number=42,
        issue_title="Make identity explicit",
        issue_type=issue_type,
        dispatch_nonce="0123456789abcdef",
    )
    head = "deck/slot-1/issue-42/0123456789abcdef"

    assert github_verification_service.pull_title(item, owner) == (
        "[Owner] Make identity explicit (#42)"
    )
    assert github_verification_service.pull_body(item, head_ref=head) == (
        "Closes #42\n\n"
        "Make identity explicit\n\n"
        "---\n"
        "Claude Deck provenance\n"
        f"- Work item: {item.id}\n"
        f"- Owner slot: {owner.id}\n"
        "- Dispatch nonce: 0123456789abcdef\n"
        f"- Head ref: {head}"
    )
    assert github_verification_service.pull_is_draft(item) is draft


async def _ready_review_messages(db):
    messages = (await db.execute(select(MailMessage))).scalars().all()
    return [message for message in messages if message.subject == "Code PR ready for review"]


async def _blocker_merged_messages(db):
    messages = (await db.execute(select(MailMessage))).scalars().all()
    return [
        message
        for message in messages
        if (message.payload or {}).get("kind") == "github_dispatch_blocker_merged"
    ]


async def _auto_ready_item(
    db,
    *,
    last_verified_sha: str,
    current_head: str,
    head_checks: list[dict],
):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(
        db,
        scope,
        dispatch_status="ready_for_review",
        issue_type="code",
        pr_number=1,
        last_verified_sha=last_verified_sha,
    )
    client = _Client(
        pull={
            "number": 1,
            "node_id": "node",
            "draft": False,
            "merged": False,
            "mergeable_state": "clean",
            "head": {"sha": current_head},
        },
        check_runs=head_checks,
    )
    return scope, item, client


@pytest.mark.asyncio
async def test_auto_merge_demotes_when_head_moved(db):
    scope, item, client = await _auto_ready_item(
        db,
        last_verified_sha="aaa111",
        current_head="bbb222",
        head_checks=[{"status": "completed", "conclusion": "success"}],
    )
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_auto_merge_demotes_when_head_red(db):
    scope, item, client = await _auto_ready_item(
        db,
        last_verified_sha="aaa111",
        current_head="aaa111",
        head_checks=[{"status": "completed", "conclusion": "failure"}],
    )
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_auto_merge_proceeds_when_head_unchanged_and_green(db):
    scope, item, client = await _auto_ready_item(
        db,
        last_verified_sha="aaa111",
        current_head="aaa111",
        head_checks=[{"status": "completed", "conclusion": "success"}],
    )
    await _owner(db, scope)
    await github_verification_service._process_review_item(db, scope, item, client)
    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert client.merge_calls == 1
    assert len(await _blocker_merged_messages(db)) == 1


@pytest.mark.asyncio
async def test_verifying_merged_pull_fires_blocker_merged_notification(db):
    scope = await _scope(db, merge_policy="human")
    await _owner(db, scope)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        pull={
            "number": 5,
            "node_id": "node",
            "draft": False,
            "merged": True,
            "mergeable_state": "clean",
            "head": {"sha": "sha"},
        }
    )

    await github_verification_service._verify_item(db, scope, item, client)

    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert len(await _blocker_merged_messages(db)) == 1


@pytest.mark.asyncio
async def test_human_merge_fires_blocker_merged_notification(db):
    scope = await _scope(db, merge_policy="human")
    await _owner(db, scope)
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client(
        pull={
            "number": 5,
            "node_id": "node",
            "draft": False,
            "merged": True,
            "mergeable_state": "clean",
            "head": {"sha": "sha"},
        }
    )

    await github_verification_service._process_review_item(db, scope, item, client)

    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert len(await _blocker_merged_messages(db)) == 1


@pytest.mark.asyncio
async def test_report_pr_opened_routes_code_and_design(db):
    code_scope = await _scope(db)
    design_scope = await _scope(db, repo_name="design")
    code_item = await _item(db, code_scope, issue_type="code")
    design_item = await _item(db, design_scope, issue_type="design")

    await github_verification_service.report_pr_opened(
        db, code_item, code_scope, 10, _reported_client(code_scope, code_item, 10)
    )
    await github_verification_service.report_pr_opened(
        db,
        design_item,
        design_scope,
        11,
        _reported_client(design_scope, design_item, 11),
    )

    await db.refresh(code_item)
    await db.refresh(design_item)
    assert code_item.pr_number == 10
    assert code_item.dispatch_status == "verifying"
    assert design_item.pr_number == 11
    assert design_item.dispatch_status == "awaiting_human_review"


@pytest.mark.asyncio
async def test_pr_opened_accepted_from_recoverable_escalation(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        issue_type="code",
    )

    await github_verification_service.report_pr_opened(
        db, item, scope, 865, _reported_client(scope, item, 865)
    )

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert item.pr_number == 865
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_pr_opened_accepted_from_brief_unread_escalation(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason="brief_unread",
        issue_type="code",
    )

    await github_verification_service.report_pr_opened(
        db, item, scope, 867, _reported_client(scope, item, 867)
    )

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert item.pr_number == 867
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_pr_opened_recovery_clears_deferred_retry_stamp(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        retry_requested_at=datetime.utcnow(),
        issue_type="code",
    )

    await github_verification_service.report_pr_opened(
        db, item, scope, 866, _reported_client(scope, item, 866)
    )

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert item.escalation_reason is None
    assert item.retry_requested_at is None


@pytest.mark.asyncio
async def test_pr_opened_accepted_from_recoverable_escalation_design_item(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
        issue_type="design",
    )

    await github_verification_service.report_pr_opened(
        db, item, scope, 865, _reported_client(scope, item, 865)
    )

    await db.refresh(item)
    assert item.dispatch_status == "awaiting_human_review"
    assert item.pr_number == 865
    assert item.escalation_reason is None


@pytest.mark.asyncio
async def test_pr_opened_rejected_after_label_removed(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason="dispatch_label_removed",
    )

    with pytest.raises(ValueError):
        await github_verification_service.report_pr_opened(
            db, item, scope, 865, _reported_client(scope, item, 865)
        )


@pytest.mark.asyncio
async def test_pr_opened_rejected_after_retry_budget_exhausted(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason="retry_count_exhausted",
    )

    with pytest.raises(ValueError):
        await github_verification_service.report_pr_opened(
            db, item, scope, 865, _reported_client(scope, item, 865)
        )


@pytest.mark.asyncio
async def test_pr_opened_rejected_from_unattributed_escalation(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="escalated",
        escalation_reason=None,
    )

    with pytest.raises(ValueError):
        await github_verification_service.report_pr_opened(
            db, item, scope, 865, _reported_client(scope, item, 865)
        )


@pytest.mark.asyncio
async def test_pr_opened_still_rejected_from_merged(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="merged")

    with pytest.raises(ValueError):
        await github_verification_service.report_pr_opened(
            db, item, scope, 865, _reported_client(scope, item, 865)
        )


@pytest.mark.asyncio
async def test_verify_green_code_pr_marks_ready_for_review(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}])

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert client.ready_calls == 1
    assert client.pull_calls == 2
    messages = await _ready_review_messages(db)
    assert len(messages) == 1
    assert "Code PR #5 is ready for human review" in messages[0].body_markdown
    assert "Auto-merge fell back" not in messages[0].body_markdown


@pytest.mark.asyncio
async def test_draft_ready_failure_keeps_item_verifying_for_retry(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}],
        ready_error=_http_error(403),
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert item.last_verified_sha is None
    assert "GitHub verification failed; will retry" in item.status_note
    assert client.ready_calls == 1
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert not any(message.subject == "Code PR ready for review" for message in messages)


@pytest.mark.asyncio
async def test_verify_zero_check_runs_escalates(db):
    scope = await _scope(db)
    item = await _item(
        db,
        scope,
        dispatch_status="verifying",
        pr_number=5,
        updated_at=datetime.utcnow() - timedelta(minutes=5),
    )

    await github_verification_service.process_scope(db, scope, client=_Client(check_runs=[]))

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert "No GitHub check-runs or commit statuses" in item.status_note


@pytest.mark.asyncio
async def test_zero_check_runs_waits_during_grace_window(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)

    await github_verification_service.process_scope(db, scope, client=_Client(check_runs=[]))

    await db.refresh(item)
    assert item.dispatch_status == "verifying"
    assert "Waiting for GitHub check-runs" in item.status_note


@pytest.mark.asyncio
async def test_combined_status_success_verifies_without_check_runs(db):
    scope = await _scope(db)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[],
        combined_status={"state": "success", "statuses": [{"context": "ci"}]},
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert client.ready_calls == 1
    assert client.pull_calls == 2


@pytest.mark.asyncio
async def test_unrecognized_check_conclusion_counts_as_failed(db):
    scope = await _scope(db, max_verification_retries=0)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "startup_failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"


@pytest.mark.asyncio
async def test_failed_check_returns_to_dispatched_until_budget_exhausted(db):
    scope = await _scope(db, max_verification_retries=2)
    slot, member = await _owner(db, scope)
    item = await _item(
        db,
        scope,
        dispatch_status="verifying",
        pr_number=5,
        retry_count=0,
        owner_slot_id=slot.id,
    )
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 1
    assert item.last_verified_sha == "sha"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    assert any(
        message.kind == "message"
        and message.recipient_member_id == member.id
        and "GitHub checks failed" in (message.subject or "")
        for message in messages
    )

    client.pull["head"]["sha"] = "sha-2"
    item.dispatch_status = "verifying"
    await db.commit()
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 2
    assert item.last_verified_sha == "sha-2"

    client.pull["head"]["sha"] = "sha-3"
    item.dispatch_status = "verifying"
    await db.commit()
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "retry_count_exhausted"
    assert item.retry_count == 3
    assert item.last_verified_sha == "sha-3"


@pytest.mark.asyncio
async def test_failed_check_counts_same_head_once_until_new_sha(db):
    scope = await _scope(db, max_verification_retries=2)
    slot, member = await _owner(db, scope)
    item = await _item(
        db,
        scope,
        dispatch_status="verifying",
        pr_number=5,
        owner_slot_id=slot.id,
    )
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)

    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 1
    assert item.escalation_reason is None
    assert item.last_verified_sha == "sha"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    failure_messages = [
        message
        for message in messages
        if message.kind == "message"
        and message.recipient_member_id == member.id
        and "GitHub checks failed" in (message.subject or "")
    ]
    assert len(failure_messages) == 1

    client.pull["head"]["sha"] = "sha-2"
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)

    assert item.dispatch_status == "dispatched"
    assert item.retry_count == 2
    assert item.escalation_reason is None
    assert item.last_verified_sha == "sha-2"
    messages = (await db.execute(select(MailMessage))).scalars().all()
    failure_messages = [
        message
        for message in messages
        if message.kind == "message"
        and message.recipient_member_id == member.id
        and "GitHub checks failed" in (message.subject or "")
    ]
    assert len(failure_messages) == 2


@pytest.mark.asyncio
async def test_failed_check_dispatched_item_with_pr_is_reverified(db):
    scope = await _scope(db, max_verification_retries=2)
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "failure"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"

    client.check_runs = [{"name": "ci", "status": "completed", "conclusion": "success"}]
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"


@pytest.mark.asyncio
async def test_auto_merge_success_sets_merged_and_budget_timestamp(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(
        db,
        scope,
        dispatch_status="ready_for_review",
        pr_number=5,
        last_verified_sha="sha",
    )
    client = _Client(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert item.auto_merged_at is not None
    assert client.merge_calls == 1


@pytest.mark.asyncio
async def test_auto_merge_without_current_approval_falls_back_stickily(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(
        db,
        scope,
        dispatch_status="ready_for_review",
        pr_number=5,
        last_verified_sha="sha",
    )
    item.ack_approval_round = None
    await db.commit()
    client = _Client(
        pull={
            "number": 5,
            "node_id": "node",
            "draft": False,
            "merged": False,
            "mergeable_state": "clean",
            "head": {"sha": "sha"},
        },
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}],
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)
    await db.refresh(item)

    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert item.status_note.startswith("Auto-merge blocked")
    assert client.merge_calls == 0


@pytest.mark.asyncio
async def test_auto_merge_cap_falls_back_to_human_review(db):
    scope = await _scope(db, merge_policy="auto", max_auto_merges_per_day=1)
    await _item(
        db,
        scope,
        issue_number=2,
        dispatch_status="merged",
        pr_number=4,
        auto_merged_at=datetime.utcnow() - timedelta(minutes=5),
    )
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client()

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert "Auto-merge budget exhausted" in item.status_note
    assert client.merge_calls == 0
    messages = await _ready_review_messages(db)
    assert len(messages) == 1
    assert "Auto-merge fell back to human merge" in messages[0].body_markdown
    assert "Auto-merge budget exhausted" in messages[0].body_markdown


@pytest.mark.asyncio
async def test_durable_merge_failure_falls_back_to_human_without_escalation(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(
        db,
        scope,
        dispatch_status="ready_for_review",
        pr_number=5,
        last_verified_sha="sha",
    )
    client = _Client(
        merge_error=_http_error(403),
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}],
    )

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert "requires human merge" in item.status_note
    assert client.merge_calls == 1
    messages = await _ready_review_messages(db)
    assert len(messages) == 1
    assert "Auto-merge fell back to human merge" in messages[0].body_markdown
    assert "requires human merge" in messages[0].body_markdown


@pytest.mark.asyncio
async def test_unexpected_merge_status_is_transient_and_does_not_abort_batch(db):
    scope = await _scope(db, merge_policy="auto", max_verification_retries=2)
    first = await _item(
        db,
        scope,
        issue_number=1,
        dispatch_status="ready_for_review",
        pr_number=5,
        last_verified_sha="sha-5",
    )
    second = await _item(
        db,
        scope,
        issue_number=2,
        dispatch_status="ready_for_review",
        pr_number=6,
        last_verified_sha="sha-6",
    )

    class _BatchClient(_Client):
        async def get_pull(self, owner, repo, pr_number):
            return {
                "number": pr_number,
                "merged": False,
                "state": "open",
                "merged_at": None,
                "mergeable_state": "clean",
                "head": {"sha": f"sha-{pr_number}"},
            }

        async def merge_pull(self, owner, repo, pr_number):
            self.merge_calls += 1
            if pr_number == 5:
                raise _http_error(422)
            return {"merged": True}

    client = _BatchClient(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(first)
    await db.refresh(second)
    assert first.dispatch_status == "ready_for_review"
    assert first.retry_count == 1
    assert "Transient merge failure" in first.status_note
    assert second.dispatch_status == "merged"


@pytest.mark.asyncio
async def test_draft_pr_is_refetched_before_auto_merge_decision(db):
    scope = await _scope(db, merge_policy="auto")
    item = await _item(db, scope, dispatch_status="verifying", pr_number=5)

    class _DraftClient(_Client):
        async def get_pull(self, owner, repo, pr_number):
            self.pull_calls += 1
            if self.pull_calls == 1:
                return {
                    "number": 5,
                    "node_id": "node",
                    "draft": True,
                    "merged": False,
                    "state": "open",
                    "merged_at": None,
                    "mergeable_state": "unknown",
                    "head": {"sha": "sha"},
                }
            return {
                "number": 5,
                "node_id": "node",
                "draft": False,
                "merged": False,
                "state": "open",
                "merged_at": None,
                "mergeable_state": "clean",
                "head": {"sha": "sha"},
            }

    client = _DraftClient(
        check_runs=[{"name": "ci", "status": "completed", "conclusion": "success"}]
    )

    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "merged"
    assert client.ready_calls == 1
    assert client.pull_calls == 2


@pytest.mark.asyncio
async def test_transient_merge_failure_falls_back_to_human_after_budget(db):
    scope = await _scope(db, merge_policy="auto", max_verification_retries=1)
    item = await _item(db, scope, dispatch_status="ready_for_review", pr_number=5)
    client = _Client(pull={"number": 5, "merged": False, "mergeable_state": "blocked"})

    await github_verification_service.process_scope(db, scope, client=client)
    await github_verification_service.process_scope(db, scope, client=client)

    await db.refresh(item)
    assert item.dispatch_status == "ready_for_review"
    assert item.escalation_reason is None
    assert "Auto-merge retry budget exhausted" in item.status_note
    assert client.merge_calls == 0
    messages = await _ready_review_messages(db)
    assert len(messages) == 1
    assert "Auto-merge fell back to human merge" in messages[0].body_markdown
    assert "Auto-merge retry budget exhausted" in messages[0].body_markdown
