"""Spec §3.7 test 22 — the force-release concurrency contract.

Every case here drives a mutation at the route's real suspension point: the
two `git` subprocesses `pending_work` awaits between the operator's inspection
and the release. A test that seeds the replacement *before* the request passes
against a route that compares at the top and writes at the bottom, which is
the exact defect this file exists to catch.
"""
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.database import (
    AgentTeamPreset,
    GithubWorkItem,
    GithubWorkspace,
    TeamGithubScope,
)
from app.services.github_workspace_service import github_workspace_service

OPERATOR_TOKEN = "test-operator-token-for-force-release"
OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN}

# The seven columns release() clears, plus the two timestamps that must agree.
RELEASE_STATE_COLUMNS = (
    "leased_item_id, lease_token, leased_owner_pid, leased_owner_proc_start,"
    " lease_last_owner_contact_at, lease_release_reminded_at, released_at, updated_at"
)


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


class InterleavingRunner:
    """A git runner that runs `hook` at the route's first await.

    `pending_work` awaits self._runner twice for a worktree -- `status
    --porcelain` then `rev-list --count`. Firing on the first call puts the
    mutation strictly between the operator's inspection and the release, which
    is where a real replacement acquisition lands.
    """

    def __init__(self, repo_path: Path, hook=None):
        self.repo_path = repo_path
        self.hook = hook
        self.calls: list[list[str]] = []
        self.status_output = ""
        self.rev_count = "0"

    async def __call__(self, args: list[str]):
        first = not self.calls
        self.calls.append(args)
        if first and self.hook is not None:
            await self.hook()
        path = Path(args[1])
        command = args[2]
        common = self.repo_path / ".git"
        if command == "rev-parse":
            linked = path != self.repo_path
            git_dir = common / "worktrees" / path.name if linked else common
            return 0, f"{git_dir}\n{common}\n{path}\n"
        if command == "status":
            return 0, self.status_output
        if command == "rev-list":
            return 0, f"{self.rev_count}\n"
        return 0, ""


async def _scope(db, repo_path: Path):
    repo_path.mkdir(parents=True, exist_ok=True)
    preset = AgentTeamPreset(name=f"FR {repo_path.name}", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="owner",
        repo_name=repo_path.name,
        repo_path=str(repo_path),
    )
    db.add(scope)
    await db.commit()
    return scope


async def _leased(db, scope, path: Path):
    """A worktree workspace with every liveness column populated.

    kind="worktree" is load-bearing: pending_work returns (None, None)
    immediately for kind == "primary" with no git call at all, so a primary
    workspace has no suspension point and none of these tests can interleave.
    """
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=1,
        issue_title="x",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
    )
    db.add(item)
    await db.flush()
    inspected_at = datetime.utcnow() - timedelta(seconds=90)
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(path),
        kind="worktree",
        leased_item_id=item.id,
        leased_at=inspected_at,
        lease_token="ACQ-1-aaa",
        leased_owner_pid=4242,
        leased_owner_proc_start="991122",
        lease_last_owner_contact_at=datetime.utcnow(),
        lease_release_reminded_at=datetime.utcnow(),
    )
    db.add(workspace)
    await db.commit()
    # Capture ids as plain ints. After the request, ORM attribute access on
    # these objects may hit the database from outside a greenlet context.
    return item.id, workspace.id, inspected_at


def _url(scope_id: int, workspace_id: int) -> str:
    return (
        f"/api/v1/agent-teams/github-scopes/{scope_id}/workspaces/"
        f"{workspace_id}/force-release"
    )


async def _row(db, workspace_id: int, columns: str = "leased_item_id, lease_token"):
    """Read the row back with raw SQL.

    Never assert on the ORM object: with expire_on_commit=False the identity
    map can report values the database does not hold, in both directions.
    """
    result = await db.execute(
        text(f"SELECT {columns} FROM github_workspaces WHERE id = :id"),
        {"id": workspace_id},
    )
    return result.one()


@pytest.mark.asyncio
async def test_matching_acquisition_is_released_and_state_fully_cleared(
    client, db, tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", InterleavingRunner(repo))

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
            "requested_by": "operator",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["released_item_id"] == item_id
    # The response must reflect the post-release row, not the object the
    # request inspected.
    assert body["workspace"]["leased_item_id"] is None
    assert body["workspace"]["lease_state"] == "available"

    row = await _row(db, workspace_id, RELEASE_STATE_COLUMNS)
    (
        leased_item_id,
        lease_token,
        owner_pid,
        owner_proc_start,
        owner_contact_at,
        reminded_at,
        released_at,
        updated_at,
    ) = row
    # All seven columns release() clears, enumerated. The ones an implementer
    # drops are the liveness ones, and a NULL leased_item_id beside a stale
    # leased_owner_pid is the row shape §4.6b exists to prevent.
    assert leased_item_id is None
    assert lease_token is None
    assert owner_pid is None
    assert owner_proc_start is None
    assert owner_contact_at is None
    assert reminded_at is None
    assert released_at is not None
    assert released_at == updated_at


@pytest.mark.asyncio
async def test_stale_expected_leased_at_refuses_without_touching_the_lease(
    client, db, tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, _ = await _leased(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", InterleavingRunner(repo))

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": "2020-01-01T00:00:00",
            "reason": "stale value",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert await _row(db, workspace_id) == (item_id, "ACQ-1-aaa")


@pytest.mark.asyncio
async def test_a_replacement_acquired_during_the_inspection_survives(
    client, db, tmp_path, monkeypatch, caplog
):
    """The ABA case. Measured against the pre-Task-9 route: 200, replacement destroyed."""
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    # Written explicitly rather than taken from utcnow() inside the hook: the
    # assertion below compares against this value's isoformat(), and a
    # microsecond of exactly 0 would make SQLite's stored '.000000' and
    # Python's suffix-less isoformat() disagree.
    replacement_leased_at = inspected_at + timedelta(seconds=30)

    async def replace():
        # The owner released and the item was dispatched again while the
        # operator's request sat in `git status`.
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_at = :now,"
                " lease_token = 'ACQ-2-bbb' WHERE id = :id"
            ),
            {"now": replacement_leased_at, "id": workspace_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service, "_runner", InterleavingRunner(repo, replace)
    )

    with caplog.at_level("WARNING", logger="app.api.v1.agent_teams"):
        response = await client.post(
            _url(scope.id, workspace_id),
            json={
                "force": True,
                "expected_leased_at": inspected_at.isoformat(),
                "reason": "owner is unavailable",
            },
            headers=OPERATOR_HEADERS,
        )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["block_code"] == "lease_changed"
    # §4.6a: the refusal names both timestamps. The second one has to be the
    # REPLACEMENT's, read fresh -- a message built from the stale ORM object
    # names the operator's own value twice and reads as "your value matched".
    assert inspected_at.isoformat() in detail["message"]
    assert replacement_leased_at.isoformat() in detail["message"]
    # The replacement acquisition is intact -- both the pointer and the token.
    assert await _row(db, workspace_id) == (item_id, "ACQ-2-bbb")
    # And nothing was logged as released. The success line must sit AFTER the
    # write; before it, a force-release that did not happen is recorded as one.
    assert "force-release workspace" not in caplog.text


@pytest.mark.asyncio
async def test_a_replacement_sharing_the_leased_at_still_survives(
    client, db, tmp_path, monkeypatch
):
    """The same-timestamp case: the only one that fails a token-less predicate.

    utcnow() self-collides -- measured 59 612 times in 200 000 back-to-back
    pairs -- and leased_at has neither a UNIQUE constraint nor any
    monotonicity guarantee, so two acquisitions sharing one is not contrived.
    The timestamp is written explicitly rather than waited for.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    async def replace_with_same_timestamp():
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_at = :same,"
                " lease_token = 'ACQ-2-bbb' WHERE id = :id"
            ),
            {"same": inspected_at, "id": workspace_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service,
        "_runner",
        InterleavingRunner(repo, replace_with_same_timestamp),
    )

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert await _row(db, workspace_id) == (item_id, "ACQ-2-bbb")
    # Microseconds survive the round trip, so the refusal above is the token
    # doing the work rather than a truncated comparison failing for its own
    # unrelated reason.
    (stored_leased_at,) = await _row(db, workspace_id, "leased_at")
    assert stored_leased_at.endswith(f"{inspected_at.microsecond:06d}")


@pytest.mark.asyncio
async def test_an_owner_release_during_the_inspection_refuses_honestly(
    client, db, tmp_path, monkeypatch
):
    """The other refusal branch: the owner released it before the operator's write.

    release() does not clear leased_at, so the row still reports the exact
    timestamp the operator confirmed. A message that names it says "your value
    did not match" while showing a value that did. This asserts the branch.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    _, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    async def owner_releases():
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_item_id = NULL,"
                " lease_token = NULL WHERE id = :id"
            ),
            {"id": workspace_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service, "_runner", InterleavingRunner(repo, owner_releases)
    )

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert response.json()["detail"]["block_code"] == "lease_changed"
    assert "no longer leased" in message
    # leased_at survives release(), so the honest message must NOT present it
    # as the current state.
    assert f"now reports leased_at {inspected_at.isoformat()}" not in message
    (stored_leased_at,) = await _row(db, workspace_id, "leased_at")
    assert stored_leased_at is not None  # the trap this assertion guards


@pytest.mark.asyncio
async def test_a_lease_that_moved_to_another_workspace_survives(
    client, db, tmp_path, monkeypatch
):
    """The cross-workspace case: release()'s selector names no workspace.

    The lease has to MOVE rather than duplicate -- UNIQUE(leased_item_id)
    refuses a second acquisition of the same item outright (measured,
    IntegrityError), so X releases before Y acquires. Y deliberately reuses
    the timestamp and token so the workspace row is the only discriminating
    predicate; otherwise the id/scope deletion mutant remains green.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    item_id, x_id, inspected_at = await _leased(db, scope, tmp_path / "ws-x")
    y = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws-y"), kind="worktree")
    db.add(y)
    await db.commit()
    y_id = y.id

    async def move_lease_to_y():
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_item_id = NULL,"
                " lease_token = NULL WHERE id = :id"
            ),
            {"id": x_id},
        )
        await db.execute(
            text(
                "UPDATE github_workspaces SET leased_item_id = :item,"
                " leased_at = :now, lease_token = 'ACQ-1-aaa' WHERE id = :id"
            ),
            {"item": item_id, "now": inspected_at, "id": y_id},
        )
        await db.commit()

    monkeypatch.setattr(
        github_workspace_service, "_runner", InterleavingRunner(repo, move_lease_to_y)
    )

    response = await client.post(
        _url(scope.id, x_id),
        json={
            "force": True,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "owner is unavailable",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["block_code"] == "lease_changed"
    # The operator inspected X and confirmed X. Y is a lease they never saw.
    assert await _row(db, y_id) == (item_id, "ACQ-1-aaa")


@pytest.mark.asyncio
async def test_the_conflict_body_discloses_no_token(client, db, tmp_path, monkeypatch):
    """Spec test 22's disclosure assertion, over the whole serialised body.

    The live disclosure reaches the wire through _conflict's detail.message
    nesting, so an assertion that reads only a top-level "message" misses it.
    Both the stored token and the value the caller supplied are asserted: an
    attacker's own guess echoed back confirms nothing, but an operator's
    mistyped paste of a real token is still a secret in a log.
    """
    repo = tmp_path / "repo"
    scope = await _scope(db, repo)
    _, workspace_id, _ = await _leased(db, scope, tmp_path / "ws")
    monkeypatch.setattr(github_workspace_service, "_runner", InterleavingRunner(repo))

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            "force": True,
            "expected_leased_at": "2020-01-01T00:00:00",
            "reason": "ACQ-3-ccc",  # a token-shaped value in a field that is echoed
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 409
    assert "ACQ-1-aaa" not in response.text
    assert "ACQ-3-ccc" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "force_field",
    [{"force": False}, {}],
    ids=["force_false", "force_omitted"],
)
async def test_force_must_be_true_and_the_lease_is_untouched(
    client, db, tmp_path, force_field
):
    """Literal[True] pins the schema, so a route that ignores `force` still fails."""
    scope = await _scope(db, tmp_path / "repo")
    item_id, workspace_id, inspected_at = await _leased(db, scope, tmp_path / "ws")

    response = await client.post(
        _url(scope.id, workspace_id),
        json={
            **force_field,
            "expected_leased_at": inspected_at.isoformat(),
            "reason": "unconfirmed",
        },
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 422
    assert await _row(db, workspace_id) == (item_id, "ACQ-1-aaa")
