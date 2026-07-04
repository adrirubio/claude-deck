# Autonomous GitHub Dispatch — Phase A (Backend Schema + Core Services) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend schema and core (non-verify/merge, non-frontend) services for autonomous GitHub issue dispatch, so a watcher can poll labeled issues, route them to the right team slot, dispatch through the existing Agent Teams launch path, and monitor for stuck work — all up to (but not including) the PR verification/merge pipeline.

**Architecture:** New SQLAlchemy tables (`TeamGithubScope`, `GithubWorkItem`) plus additive columns on the existing `AgentTeamSlot`/`AgentTeamPreset` tables, migrated via the repo's existing SQLite compat-migration mechanism. New async service modules (`github_watcher_service`, `github_dispatch_service`) that reuse the existing `AgentTeamService` launch path (extended with a per-launch `repo_path_override`) and the existing Agent Mail `wake_state` machinery. One new MCP tool (`deck_report_dispatch_status`) added to the existing shim via its already-prefix-aware request helper. The GitHub API client and the actual scheduler wiring are stubbed/injected so services are unit-testable without network or a running scheduler.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (`Mapped`/`mapped_column`), aiosqlite, pytest + pytest-asyncio, `httpx` (already a dependency, used for the GitHub client), the `mcp` package's `FastMCP` (already used by the shim).

## Global Constraints

- **Python `>=3.11`**, backend deps managed in `backend/pyproject.toml` (copy exact version floors from there; do not add new runtime deps in Phase A — the GitHub client uses `httpx`, already present).
- **Schema migrations:** the repo has NO Alembic. `init_db()` (`backend/app/database.py:391`) calls `Base.metadata.create_all` (creates missing *tables* only, never missing *columns*) then `_run_sqlite_compat_migrations(conn)` for additive column changes on existing tables. **New tables** need only the ORM model (create_all handles them). **New columns on existing tables** (`AgentTeamSlot`, `AgentTeamPreset`) MUST also get an `ALTER TABLE ... ADD COLUMN` guard in `_run_sqlite_compat_migrations`, or existing databases silently lack the column and every query breaks. This is the single most important constraint in Phase A.
- **Async everywhere:** all service methods and DB access are `async`; DB sessions are `AsyncSession`. Follow the existing `agent_team_service.py` idioms (`await db.flush()`, `await db.commit()`, `await db.refresh(obj)`).
- **`GITHUB_TOKEN`** is a new `Settings` field in `backend/app/config.py` with a code-level default (empty string), env-overridable — per the "no `.env` required" convention. It is read only by the watcher/dispatch services, never injected into spawned sessions.
- **Machine-readable block codes / statuses** use the existing `block_code`-style string convention (see `AgentTeamLaunchPlanItem.block_code`). Escalation reasons are lowercase snake_case strings (`retry_count_exhausted`, `approval_rounds_exhausted`, `handoff_not_accepted`, `leader_offline`, `dispatch_label_removed`, `plan_blocked`).
- **Spec authority:** `docs/superpowers/specs/2026-07-02-autonomous-github-dispatch-design.md`. Where this plan and the spec disagree, the spec wins — but note Phase A implements only §3, §4, §5, §6 (schema, watcher, dispatch, monitoring). §7 (verify/merge) and §10 (frontend) are Phase B/C, explicitly out of scope here.

---

## File Structure

**New files:**
- `backend/app/services/github_client.py` — thin async `httpx` wrapper for the read-only GitHub REST calls the watcher/dispatch need (list labeled issues, list all open issues by number, read repo labels). Injectable so tests never hit the network.
- `backend/app/services/github_watcher_service.py` — polling logic: per-repo issue fetch, `issue_type` detection, `GithubWorkItem` upsert, escalated/failed recovery reset, active-item label recheck.
- `backend/app/services/github_dispatch_service.py` — routing (label match → classification fallback → leader fallback), per-slot concurrency check, dispatch via `AgentTeamService`, approval-round cap, two-phase handoff resolution, and the `wake_state`-gated monitoring pass.
- `backend/tests/agent_teams/test_github_scope_models.py` — model/migration tests.
- `backend/tests/agent_teams/test_github_watcher_service.py`
- `backend/tests/agent_teams/test_github_dispatch_service.py`
- `backend/tests/agent_teams/test_repo_path_override.py`
- `backend/tests/agent_mail/test_dispatch_status_tool.py` — MCP tool test (mirrors existing `tests/agent_mail/test_mcp_shim.py` if present, else new).

**Modified files:**
- `backend/app/models/database.py` — new `TeamGithubScope`/`GithubWorkItem` models + new columns on `AgentTeamSlot`/`AgentTeamPreset`.
- `backend/app/database.py` — add `ADD COLUMN` guards in `_run_sqlite_compat_migrations`.
- `backend/app/config.py` — add `github_token` setting.
- `backend/app/models/schemas.py` — `repo_path_override` on `AgentTeamLaunchRequest`; Pydantic response models for scopes/work items.
- `backend/app/services/agent_team_service.py` — thread `repo_path_override` through the launch path.
- `backend/mcp_shim/agent_mail_server.py` — `deck_report_dispatch_status` tool + `_dispatch_request` wrapper.

**Why this decomposition:** each service owns one responsibility (client = I/O, watcher = intake, dispatch = routing+lifecycle). The watcher and dispatch are split because a reviewer can meaningfully accept "polling correctly upserts work items" while rejecting "routing picks the wrong slot" — they fail independently. The GitHub client is separate so both services inject the same testable seam.

---

## Task 1: Schema — new tables, new columns, and compat migrations

**Files:**
- Modify: `backend/app/models/database.py` (append two models; add columns to `AgentTeamSlot`, `AgentTeamPreset`)
- Modify: `backend/app/database.py:290-389` (`_run_sqlite_compat_migrations`)
- Modify: `backend/app/config.py`
- Test: `backend/tests/agent_teams/test_github_scope_models.py`

**Interfaces:**
- Produces: `TeamGithubScope`, `GithubWorkItem` ORM classes; `AgentTeamSlot.area_labels` (`list | None`), `AgentTeamSlot.expertise` (`str | None`), `AgentTeamPreset.autonomy_enabled` (`bool`). `settings.github_token` (`str`).

- [ ] **Step 1: Write the failing test for the new tables + columns**

Create `backend/tests/agent_teams/test_github_scope_models.py`:

```python
"""Schema tests for the autonomous GitHub dispatch tables."""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import (
    AgentTeamPreset,
    AgentTeamSlot,
    TeamGithubScope,
    GithubWorkItem,
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


@pytest.mark.asyncio
async def test_team_github_scope_round_trips(db):
    preset = AgentTeamPreset(name="SnazzyEmail", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id,
        repo_owner="adrirubio",
        repo_name="snazzyemail",
        repo_path="/tmp/snazzyemail",
    )
    db.add(scope)
    await db.commit()
    await db.refresh(scope)
    assert scope.dispatch_label == "claude-deck-ready"
    assert scope.design_label == "claude-deck-design"
    assert scope.merge_policy == "human"
    assert scope.max_approval_rounds == 3
    assert scope.enabled is True


@pytest.mark.asyncio
async def test_github_work_item_defaults(db):
    preset = AgentTeamPreset(name="T", description="", created_by="test")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/r"
    )
    db.add(scope)
    await db.flush()
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=42,
        issue_title="bug",
        issue_url="https://github.com/o/r/issues/42",
        github_updated_at=__import__("datetime").datetime.utcnow(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    assert item.issue_type == "code"
    assert item.dispatch_status == "pending"
    assert item.pending_reason is None
    assert item.approval_round_count == 0
    assert item.retry_count == 0
    assert item.handoff_state is None


@pytest.mark.asyncio
async def test_new_columns_on_existing_tables(db):
    preset = AgentTeamPreset(name="T2", description="", created_by="test", autonomy_enabled=True)
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id, position=0, display_name="Backend SME",
        provider="codex-cli", repo_id="r", repo_path="/tmp/r", repo_name="r",
        launch_mode="plain", launch_options={}, enabled=True,
        area_labels=["area:backend"], expertise="owns the backend",
    )
    db.add(slot)
    await db.commit()
    await db.refresh(slot)
    await db.refresh(preset)
    assert preset.autonomy_enabled is True
    assert slot.area_labels == ["area:backend"]
    assert slot.expertise == "owns the backend"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_scope_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'TeamGithubScope'` (and `autonomy_enabled`/`area_labels` unknown kwargs).

- [ ] **Step 3: Add the new columns to existing models**

In `backend/app/models/database.py`, in `class AgentTeamPreset` (after `updated_at`, before the class ends around line 133), add:

```python
    autonomy_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

In `class AgentTeamSlot` (after `launch_options`, around line 156), add:

```python
    area_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expertise: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Add the two new models**

Append to `backend/app/models/database.py` (after `AgentTeamLaunchItem`, before `BridgeSessionAttachment` or at end of the agent-team model group):

```python
class TeamGithubScope(Base):
    """A GitHub repo an Agent Team watches for labeled issues."""

    __tablename__ = "team_github_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)
    dispatch_label: Mapped[str] = mapped_column(String, default="claude-deck-ready", nullable=False)
    design_label: Mapped[str] = mapped_column(String, default="claude-deck-design", nullable=False)
    merge_policy: Mapped[str] = mapped_column(String, default="human", nullable=False)
    max_approval_rounds: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("preset_id", "repo_owner", "repo_name", name="uix_preset_repo_scope"),
    )


class GithubWorkItem(Base):
    """A labeled GitHub issue the dispatch pipeline is tracking."""

    __tablename__ = "github_work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("team_github_scopes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_title: Mapped[str] = mapped_column(String, nullable=False)
    issue_url: Mapped[str] = mapped_column(String, nullable=False)
    github_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issue_type: Mapped[str] = mapped_column(String, default="code", nullable=False)
    dispatch_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    pending_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    launch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_launches.id", ondelete="SET NULL"), nullable=True
    )
    owner_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    routing_method: Mapped[str | None] = mapped_column(String, nullable=True)
    handoff_state: Mapped[str | None] = mapped_column(String, nullable=True)
    handoff_target_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    approval_round_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    escalation_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_id", "issue_number", name="uix_scope_issue"),
    )
```

- [ ] **Step 5: Run the model test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_scope_models.py -v`
Expected: PASS (all three tests — the in-memory `create_all` builds new tables and adds the new columns fresh).

- [ ] **Step 6: Write the failing compat-migration test**

The above passes for a *fresh* db, but existing databases won't get the new columns on `agent_team_slots`/`agent_team_presets`. Add this test to the same file:

```python
from sqlalchemy import text
from app.database import _run_sqlite_compat_migrations


@pytest.mark.asyncio
async def test_compat_migration_adds_new_columns_to_legacy_db():
    """Simulate a pre-existing db missing the new columns, then migrate."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Legacy agent_team_presets WITHOUT autonomy_enabled
        await conn.execute(text(
            "CREATE TABLE agent_team_presets (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name VARCHAR NOT NULL, description VARCHAR, created_by VARCHAR, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
        # Legacy agent_team_slots WITHOUT area_labels/expertise
        await conn.execute(text(
            "CREATE TABLE agent_team_slots (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "preset_id INTEGER NOT NULL, position INTEGER NOT NULL, display_name VARCHAR NOT NULL, "
            "provider VARCHAR NOT NULL, repo_id VARCHAR NOT NULL, repo_path VARCHAR NOT NULL, "
            "repo_name VARCHAR NOT NULL, role VARCHAR, charter VARCHAR, bootstrap_prompt VARCHAR, "
            "ui_color VARCHAR, launch_mode VARCHAR NOT NULL, launch_options JSON, "
            "enabled BOOLEAN NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        ))
    async with engine.connect() as conn:
        await _run_sqlite_compat_migrations(conn)
    async with engine.connect() as conn:
        preset_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_presets)"))).fetchall()}
        slot_cols = {row[1] for row in (await conn.execute(text("PRAGMA table_info(agent_team_slots)"))).fetchall()}
    assert "autonomy_enabled" in preset_cols
    assert "area_labels" in slot_cols
    assert "expertise" in slot_cols
    await engine.dispose()
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_scope_models.py::test_compat_migration_adds_new_columns_to_legacy_db -v`
Expected: FAIL — `autonomy_enabled`/`area_labels`/`expertise` not in the column sets.

- [ ] **Step 8: Add ADD COLUMN guards to `_run_sqlite_compat_migrations`**

In `backend/app/database.py`, inside `_run_sqlite_compat_migrations`, after the existing `agent_team_slots` `bootstrap_prompt`/`ui_color` guards (around line 320), add:

```python
    if slot_columns and "area_labels" not in slot_columns:
        await conn.execute(text("ALTER TABLE agent_team_slots ADD COLUMN area_labels JSON"))
    if slot_columns and "expertise" not in slot_columns:
        await conn.execute(text("ALTER TABLE agent_team_slots ADD COLUMN expertise VARCHAR"))

    result = await conn.execute(text("PRAGMA table_info(agent_team_presets)"))
    preset_columns = {row[1] for row in result.fetchall()}
    if preset_columns and "autonomy_enabled" not in preset_columns:
        await conn.execute(
            text("ALTER TABLE agent_team_presets ADD COLUMN autonomy_enabled BOOLEAN DEFAULT 0 NOT NULL")
        )
```

Note: `team_github_scopes` and `github_work_items` are brand-new tables — `create_all` builds them, so they need NO compat-migration entry. Only pre-existing tables gaining columns do.

- [ ] **Step 9: Run the compat test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_scope_models.py -v`
Expected: PASS (all four tests).

- [ ] **Step 10: Add the `github_token` setting**

In `backend/app/config.py`, in `class Settings`, after the Agent Bridge settings block, add:

```python
    # GitHub integration (autonomous dispatch)
    github_token: str = ""
```

- [ ] **Step 11: Run the full agent_teams suite to confirm no regressions**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/ -v`
Expected: PASS — new tests pass, all pre-existing agent-team tests still pass (the additive columns don't break existing model construction since they're nullable/defaulted).

- [ ] **Step 12: Commit**

```bash
git add backend/app/models/database.py backend/app/database.py backend/app/config.py backend/tests/agent_teams/test_github_scope_models.py
git commit -m "feat(dispatch): add TeamGithubScope/GithubWorkItem schema + compat migrations"
```

---

## Task 2: `repo_path_override` on the launch path

**Files:**
- Modify: `backend/app/models/schemas.py:2174` (`AgentTeamLaunchRequest`)
- Modify: `backend/app/services/agent_team_service.py` (`launch`, `_execute_plan_item`, `_spawn_options_for_slot`)
- Test: `backend/tests/agent_teams/test_repo_path_override.py`

**Interfaces:**
- Consumes: `AgentTeamService.launch(db, preset_id, request)` (existing).
- Produces: `AgentTeamLaunchRequest.repo_path_override: Optional[str]`; when set, the spawned slot's working directory (and its `AgentTeamLaunchResultItem.repo_path`) use the override instead of `slot.repo_path`. Slot's saved `repo_path` is never mutated.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/agent_teams/test_repo_path_override.py`:

```python
"""repo_path_override threads through the launch path to spawn options."""
import pytest
import pytest_asyncio
from unittest.mock import patch
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import AgentTeamPreset, AgentTeamSlot
from app.models.schemas import AgentTeamLaunchRequest
from app.services.agent_team_service import agent_team_service


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_launch_request_accepts_repo_path_override():
    req = AgentTeamLaunchRequest(repo_path_override="/tmp/other-repo", skip_plan_confirmation=True)
    assert req.repo_path_override == "/tmp/other-repo"


@pytest.mark.asyncio
async def test_override_directory_used_in_spawn(db, tmp_path):
    override_dir = tmp_path / "override-repo"
    override_dir.mkdir()
    slot_dir = tmp_path / "slot-repo"
    slot_dir.mkdir()

    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    slot = AgentTeamSlot(
        preset_id=preset.id, position=0, display_name="Dev", provider="claude-code",
        repo_id="r", repo_path=str(slot_dir), repo_name="slot-repo",
        launch_mode="plain", launch_options={}, enabled=True,
    )
    db.add(slot)
    await db.commit()

    captured = {}

    def fake_spawn(provider, options, extra_env=None):
        captured["directory"] = options.directory
        return {"session_name": "s", "tmux_target": "s:0.0"}

    with patch("app.services.agent_team_service.spawn_session", side_effect=fake_spawn):
        req = AgentTeamLaunchRequest(
            skip_plan_confirmation=True,
            repo_path_override=str(override_dir),
        )
        await agent_team_service.launch(db, preset.id, req)

    assert captured["directory"] == str(override_dir)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_repo_path_override.py -v`
Expected: FAIL — `repo_path_override` is not a field on `AgentTeamLaunchRequest`.

- [ ] **Step 3: Add the schema field**

In `backend/app/models/schemas.py`, in `class AgentTeamLaunchRequest` (line 2174), add after `skip_plan_confirmation`:

```python
    repo_path_override: Optional[str] = None
```

- [ ] **Step 4: Thread the override through `_spawn_options_for_slot`**

In `backend/app/services/agent_team_service.py`, change `_spawn_options_for_slot` (line 1037) to accept an optional override. Current signature:

```python
    def _spawn_options_for_slot(self, slot: AgentTeamSlot, prompt: str | None) -> SpawnCommandOptions:
```

Change to:

```python
    def _spawn_options_for_slot(
        self, slot: AgentTeamSlot, prompt: str | None, repo_path_override: str | None = None
    ) -> SpawnCommandOptions:
```

And in its body, where `values["directory"] = slot.repo_path` is set (line 1046), change to:

```python
            "directory": repo_path_override or slot.repo_path,
```

- [ ] **Step 5: Pass the override from the spawn call site in `_execute_plan_item`**

`_execute_plan_item` (line 519) doesn't currently receive the request. The minimal thread-through: add a `repo_path_override` parameter to `_execute_plan_item` and pass it from `launch`'s loop. In `launch` (around line 498), change:

```python
            result_item = await self._execute_plan_item(db, launch.id, preset, slot, item)
```
to:
```python
            result_item = await self._execute_plan_item(
                db, launch.id, preset, slot, item, request.repo_path_override
            )
```

Change `_execute_plan_item`'s signature (line 519) to add `repo_path_override: str | None = None` as the last parameter, and in its spawn branch (around line 580) change:

```python
            options = self._spawn_options_for_slot(slot, self._bootstrap_prompt(preset, slot))
```
to:
```python
            options = self._spawn_options_for_slot(
                slot, self._bootstrap_prompt(preset, slot), repo_path_override
            )
```

Also update the spawned `AgentTeamLaunchResultItem.repo_path` in that branch to reflect the override (around line 599 where `repo_path=slot.repo_path` is set for the spawn result): change to `repo_path=repo_path_override or slot.repo_path`. Leave the `reuse`/`skip`/`blocked` branches unchanged — override only applies to fresh spawns (spec §3.3: "applies to the slot the brain dispatches to").

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_repo_path_override.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full agent_teams suite for regressions**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/ -v`
Expected: PASS — override defaults to `None`, so every existing launch path is unaffected.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/schemas.py backend/app/services/agent_team_service.py backend/tests/agent_teams/test_repo_path_override.py
git commit -m "feat(dispatch): thread repo_path_override through Agent Team launch"
```

---

## Task 3: GitHub client (injectable I/O seam)

**Files:**
- Create: `backend/app/services/github_client.py`
- Test: `backend/tests/agent_teams/test_github_watcher_service.py` (client tested via the watcher's use of it; a direct unit test of URL construction is included here)

**Interfaces:**
- Produces: `class GithubClient` with async methods:
  - `async def list_issues_with_label(self, owner: str, repo: str, label: str) -> list[dict]` — `GET /repos/{owner}/{repo}/issues?labels={label}&state=open`; each dict has at least `number: int`, `title: str`, `html_url: str`, `updated_at: str` (ISO), `labels: list[dict]` (each with `name`).
  - `async def get_open_issues_by_number(self, owner: str, repo: str, numbers: list[int]) -> dict[int, dict]` — fetches current state of specific open issues; returns `{number: issue_dict}` (missing/closed numbers absent from the dict).
  - `async def list_repo_labels(self, owner: str, repo: str) -> list[str]` — label names in use on the repo.
  - A module-level `github_client = GithubClient()` singleton, plus the class is constructable with an injected `httpx.AsyncClient` for tests.

- [ ] **Step 1: Write the failing test for URL/param construction**

Add to a new `backend/tests/agent_teams/test_github_watcher_service.py` (this file grows across Tasks 3–4):

```python
"""GitHub client + watcher service tests."""
import pytest
import httpx

from app.services.github_client import GithubClient


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    async def handle_async_request(self, request):
        self.requests.append(request)
        return self.handler(request)


@pytest.mark.asyncio
async def test_list_issues_with_label_builds_request():
    def handler(request):
        return httpx.Response(200, json=[
            {"number": 42, "title": "bug", "html_url": "u",
             "updated_at": "2026-07-04T00:00:00Z",
             "labels": [{"name": "claude-deck-ready"}]}
        ])
    transport = _RecordingTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as http:
        client = GithubClient(http=http, token="tok")
        issues = await client.list_issues_with_label("o", "r", "claude-deck-ready")

    req = transport.requests[0]
    assert req.url.path == "/repos/o/r/issues"
    assert req.url.params["labels"] == "claude-deck-ready"
    assert req.url.params["state"] == "open"
    assert req.headers["Authorization"] == "Bearer tok"
    assert issues[0]["number"] == 42
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_watcher_service.py::test_list_issues_with_label_builds_request -v`
Expected: FAIL — `github_client` module does not exist.

- [ ] **Step 3: Implement the client**

Create `backend/app/services/github_client.py`:

```python
"""Read-only GitHub REST client for autonomous dispatch (watcher + dispatch)."""
from __future__ import annotations

import httpx

from app.config import settings

_GITHUB_API = "https://api.github.com"


class GithubClient:
    """Thin async wrapper over the read-only GitHub calls dispatch needs.

    Injectable: pass an httpx.AsyncClient for tests; defaults to a lazily
    created client against the real API using settings.github_token.
    """

    def __init__(self, http: httpx.AsyncClient | None = None, token: str | None = None):
        self._http = http
        self._token = token if token is not None else settings.github_token

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        return httpx.AsyncClient(base_url=_GITHUB_API, timeout=30.0)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def list_issues_with_label(self, owner: str, repo: str, label: str) -> list[dict]:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/issues",
                params={"labels": label, "state": "open", "per_page": 100},
                headers=self._headers(),
            )
            resp.raise_for_status()
            # /issues includes PRs; exclude anything with a pull_request key.
            return [i for i in resp.json() if "pull_request" not in i]
        finally:
            if self._http is None:
                await client.aclose()

    async def get_open_issues_by_number(
        self, owner: str, repo: str, numbers: list[int]
    ) -> dict[int, dict]:
        if not numbers:
            return {}
        client = self._client()
        result: dict[int, dict] = {}
        try:
            for number in numbers:
                resp = await client.get(
                    f"/repos/{owner}/{repo}/issues/{number}",
                    headers=self._headers(),
                )
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                issue = resp.json()
                if issue.get("state") == "open" and "pull_request" not in issue:
                    result[number] = issue
            return result
        finally:
            if self._http is None:
                await client.aclose()

    async def list_repo_labels(self, owner: str, repo: str) -> list[str]:
        client = self._client()
        try:
            resp = await client.get(
                f"/repos/{owner}/{repo}/labels",
                params={"per_page": 100},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return [lbl["name"] for lbl in resp.json()]
        finally:
            if self._http is None:
                await client.aclose()


github_client = GithubClient()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_watcher_service.py::test_list_issues_with_label_builds_request -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_client.py backend/tests/agent_teams/test_github_watcher_service.py
git commit -m "feat(dispatch): add injectable read-only GitHub client"
```

---

## Task 4: Watcher service — intake, issue_type, recovery, label recheck

**Files:**
- Create: `backend/app/services/github_watcher_service.py`
- Test: `backend/tests/agent_teams/test_github_watcher_service.py` (extend)

**Interfaces:**
- Consumes: `GithubClient` (Task 3); `TeamGithubScope`/`GithubWorkItem` (Task 1).
- Produces: `class GithubWatcherService` with:
  - `async def poll_scope(self, db, scope: TeamGithubScope, client: GithubClient) -> None` — one poll cycle for one scope: upsert `pending` items, apply `failed`/`escalated` recovery, apply active-item label recheck.
  - Module singleton `github_watcher_service`.
- Escalation reason constant `dispatch_label_removed`. Recovery resets `escalated`/`failed` → `pending` clearing `escalation_reason`, `pending_reason`, `retry_count`, `approval_round_count`.

- [ ] **Step 1: Write failing tests for intake + issue_type**

Add to `backend/tests/agent_teams/test_github_watcher_service.py`:

```python
import pytest_asyncio
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import AgentTeamPreset, TeamGithubScope, GithubWorkItem
from app.services.github_watcher_service import github_watcher_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


class _FakeClient:
    def __init__(self, labeled=None, by_number=None):
        self._labeled = labeled or []
        self._by_number = by_number or {}
    async def list_issues_with_label(self, owner, repo, label):
        return list(self._labeled)
    async def get_open_issues_by_number(self, owner, repo, numbers):
        return {n: self._by_number[n] for n in numbers if n in self._by_number}
    async def list_repo_labels(self, owner, repo):
        return []


async def _make_scope(db, **kw):
    preset = AgentTeamPreset(name=kw.pop("preset_name", "T"), description="", created_by="t")
    db.add(preset)
    await db.flush()
    scope = TeamGithubScope(
        preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/r", **kw
    )
    db.add(scope)
    await db.commit()
    await db.refresh(scope)
    return scope


def _issue(number, labels, updated="2026-07-04T00:00:00Z"):
    return {"number": number, "title": f"issue {number}",
            "html_url": f"https://github.com/o/r/issues/{number}",
            "updated_at": updated, "labels": [{"name": n} for n in labels]}


@pytest.mark.asyncio
async def test_poll_creates_pending_code_item(db):
    scope = await _make_scope(db)
    client = _FakeClient(labeled=[_issue(1, ["claude-deck-ready"])])
    await github_watcher_service.poll_scope(db, scope, client)
    items = (await db.execute(select(GithubWorkItem))).scalars().all()
    assert len(items) == 1
    assert items[0].issue_number == 1
    assert items[0].issue_type == "code"
    assert items[0].dispatch_status == "pending"


@pytest.mark.asyncio
async def test_poll_detects_design_type(db):
    scope = await _make_scope(db)
    client = _FakeClient(labeled=[_issue(2, ["claude-deck-ready", "claude-deck-design"])])
    await github_watcher_service.poll_scope(db, scope, client)
    item = (await db.execute(select(GithubWorkItem))).scalars().one()
    assert item.issue_type == "design"


@pytest.mark.asyncio
async def test_poll_is_idempotent(db):
    scope = await _make_scope(db)
    client = _FakeClient(labeled=[_issue(1, ["claude-deck-ready"])])
    await github_watcher_service.poll_scope(db, scope, client)
    await github_watcher_service.poll_scope(db, scope, client)
    items = (await db.execute(select(GithubWorkItem))).scalars().all()
    assert len(items) == 1  # unique (scope_id, issue_number) — no duplicate
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_watcher_service.py -k poll -v`
Expected: FAIL — `github_watcher_service` module does not exist.

- [ ] **Step 3: Implement intake in the watcher**

Create `backend/app/services/github_watcher_service.py`:

```python
"""Polling watcher for autonomous GitHub dispatch (spec §4)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import GithubWorkItem, TeamGithubScope
from app.services.github_client import GithubClient, github_client

# Statuses where an agent is actively working (used by recovery + label recheck).
_ACTIVE_STATUSES = ("dispatched", "verifying", "awaiting_human_review")
# Statuses eligible for github_updated_at-triggered recovery back to pending.
_RECOVERABLE_STATUSES = ("failed", "escalated")


def _parse_gh_ts(value: str) -> datetime:
    # GitHub ISO 8601, e.g. "2026-07-04T00:00:00Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


class GithubWatcherService:
    async def poll_scope(
        self, db: AsyncSession, scope: TeamGithubScope, client: GithubClient | None = None
    ) -> None:
        client = client or github_client
        labeled = await client.list_issues_with_label(
            scope.repo_owner, scope.repo_name, scope.dispatch_label
        )
        for issue in labeled:
            await self._upsert_item(db, scope, issue)
        await self._recheck_active_items(db, scope, client)
        scope.last_polled_at = datetime.utcnow()
        await db.commit()

    async def _upsert_item(self, db: AsyncSession, scope: TeamGithubScope, issue: dict) -> None:
        label_names = {lbl["name"] for lbl in issue.get("labels", [])}
        issue_type = "design" if scope.design_label in label_names else "code"
        gh_updated = _parse_gh_ts(issue["updated_at"])
        existing = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.issue_number == issue["number"],
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            db.add(GithubWorkItem(
                scope_id=scope.id,
                issue_number=issue["number"],
                issue_title=issue["title"],
                issue_url=issue["html_url"],
                github_updated_at=gh_updated,
                issue_type=issue_type,
                dispatch_status="pending",
            ))
            return

        # Recovery: failed/escalated + advanced timestamp -> reset to pending.
        if existing.dispatch_status in _RECOVERABLE_STATUSES and gh_updated > existing.github_updated_at:
            existing.dispatch_status = "pending"
            existing.escalation_reason = None
            existing.pending_reason = None
            existing.retry_count = 0
            existing.approval_round_count = 0
        # issue_type may still be corrected while pending (label added/removed pre-dispatch).
        if existing.dispatch_status == "pending":
            existing.issue_type = issue_type
        existing.github_updated_at = gh_updated
        existing.issue_title = issue["title"]
        existing.updated_at = datetime.utcnow()

    async def _recheck_active_items(
        self, db: AsyncSession, scope: TeamGithubScope, client: GithubClient
    ) -> None:
        active = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_ACTIVE_STATUSES),
                )
            )
        ).scalars().all()
        if not active:
            return
        current = await client.get_open_issues_by_number(
            scope.repo_owner, scope.repo_name, [i.issue_number for i in active]
        )
        for item in active:
            issue = current.get(item.issue_number)
            still_labeled = issue is not None and any(
                lbl["name"] == scope.dispatch_label for lbl in issue.get("labels", [])
            )
            if not still_labeled:
                item.dispatch_status = "escalated"
                item.escalation_reason = "dispatch_label_removed"
                item.updated_at = datetime.utcnow()


github_watcher_service = GithubWatcherService()
```

- [ ] **Step 4: Run the intake tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_watcher_service.py -k poll -v`
Expected: PASS.

- [ ] **Step 5: Write failing tests for recovery + label recheck**

Add to the same test file:

```python
@pytest.mark.asyncio
async def test_escalated_item_recovers_on_updated_timestamp(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id, issue_number=5, issue_title="x",
        issue_url="u", github_updated_at=datetime(2026, 7, 1),
        dispatch_status="escalated", escalation_reason="retry_count_exhausted",
        retry_count=2, approval_round_count=1,
    )
    db.add(item)
    await db.commit()
    # Same issue re-appears with a newer timestamp.
    client = _FakeClient(labeled=[_issue(5, ["claude-deck-ready"], updated="2026-07-04T00:00:00Z")])
    await github_watcher_service.poll_scope(db, scope, client)
    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.escalation_reason is None
    assert item.retry_count == 0
    assert item.approval_round_count == 0


@pytest.mark.asyncio
async def test_active_item_escalates_when_label_removed(db):
    scope = await _make_scope(db)
    item = GithubWorkItem(
        scope_id=scope.id, issue_number=7, issue_title="x",
        issue_url="u", github_updated_at=datetime(2026, 7, 1),
        dispatch_status="dispatched",
    )
    db.add(item)
    await db.commit()
    # Not returned by the labeled query; recheck finds it open but WITHOUT the label.
    client = _FakeClient(
        labeled=[],
        by_number={7: _issue(7, ["some-other-label"])},
    )
    await github_watcher_service.poll_scope(db, scope, client)
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "dispatch_label_removed"
```

- [ ] **Step 6: Run to verify they pass** (implementation from Step 3 already covers these)

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_watcher_service.py -v`
Expected: PASS (all watcher tests). If the recovery/recheck tests fail, fix the Step-3 implementation — do not weaken the tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/github_watcher_service.py backend/tests/agent_teams/test_github_watcher_service.py
git commit -m "feat(dispatch): add watcher service — intake, issue_type, recovery, label recheck"
```

---

## Task 5: Dispatch routing + per-slot concurrency

**Files:**
- Create: `backend/app/services/github_dispatch_service.py`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: `TeamGithubScope`/`GithubWorkItem`/`AgentTeamSlot` (Task 1); `AgentTeamService.launch` + `repo_path_override` (Task 2); `GithubClient.list_repo_labels` (Task 3).
- Produces: `class GithubDispatchService` with:
  - `async def route_item(self, db, item: GithubWorkItem, preset_slots: list[AgentTeamSlot], repo_labels: list[str], classify=None) -> tuple[int | None, str]` — returns `(owner_slot_id, routing_method)` where `routing_method ∈ {"label", "classified", "leader_fallback"}`. `classify` is an injectable async callable `(item, slots) -> slot_id` for the fallback (real one calls the model; tests inject a stub).
  - `async def slot_is_busy(self, db, slot_id: int) -> bool` — true if another `GithubWorkItem` has this slot as `owner_slot_id` in (`dispatched`,`verifying`) OR as `owner_slot_id`/`handoff_target_slot_id` with `handoff_state="pending"`.
  - `async def dispatch_pending(self, db, scope, client=None, classify=None) -> None` — route + concurrency-gate + launch each `pending` item for the scope.
  - Module singleton `github_dispatch_service`.
- `pending_reason` set to `"queued_slot_busy"` when gated, cleared to `None` on successful dispatch.

- [ ] **Step 1: Write failing tests for routing**

Create `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
"""Dispatch routing + concurrency tests."""
import pytest
import pytest_asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.database  # noqa: F401
from app.database import Base
from app.models.database import (
    AgentTeamPreset, AgentTeamSlot, TeamGithubScope, GithubWorkItem,
)
from app.services.github_dispatch_service import github_dispatch_service


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _team(db):
    preset = AgentTeamPreset(name="T", description="", created_by="t")
    db.add(preset)
    await db.flush()
    architect = AgentTeamSlot(
        preset_id=preset.id, position=0, display_name="Architect", provider="codex-cli",
        repo_id="r", repo_path="/tmp/r", repo_name="r", launch_mode="plain",
        launch_options={}, enabled=True, area_labels=None, expertise="cross-cutting",
    )
    backend = AgentTeamSlot(
        preset_id=preset.id, position=1, display_name="Backend SME", provider="codex-cli",
        repo_id="r", repo_path="/tmp/r", repo_name="r", launch_mode="plain",
        launch_options={}, enabled=True, area_labels=["area:backend"], expertise="backend",
    )
    db.add_all([architect, backend])
    await db.flush()
    scope = TeamGithubScope(preset_id=preset.id, repo_owner="o", repo_name="r", repo_path="/tmp/r")
    db.add(scope)
    await db.commit()
    return preset, [architect, backend], scope


def _item(scope_id, number, labels):
    return GithubWorkItem(
        scope_id=scope_id, issue_number=number, issue_title="x", issue_url="u",
        github_updated_at=datetime.utcnow(), dispatch_status="pending",
    ), [{"name": n} for n in labels]


@pytest.mark.asyncio
async def test_route_by_label_match(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow())
    db.add(item)
    await db.commit()
    owner_id, method = await github_dispatch_service.route_item(
        db, item, slots, repo_labels=["area:backend"],
        issue_labels=["area:backend"],
    )
    backend = next(s for s in slots if s.display_name == "Backend SME")
    assert owner_id == backend.id
    assert method == "label"


@pytest.mark.asyncio
async def test_route_classification_fallback(db):
    preset, slots, scope = await _team(db)
    item = GithubWorkItem(scope_id=scope.id, issue_number=2, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow())
    db.add(item)
    await db.commit()
    backend = next(s for s in slots if s.display_name == "Backend SME")

    async def fake_classify(it, candidate_slots):
        return backend.id

    owner_id, method = await github_dispatch_service.route_item(
        db, item, slots, repo_labels=["area:backend"],
        issue_labels=["no-area-label"], classify=fake_classify,
    )
    assert owner_id == backend.id
    assert method == "classified"


@pytest.mark.asyncio
async def test_route_leader_fallback_when_no_expertise(db):
    preset, slots, scope = await _team(db)
    for s in slots:
        s.expertise = None
    await db.commit()
    item = GithubWorkItem(scope_id=scope.id, issue_number=3, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow())
    db.add(item)
    await db.commit()
    owner_id, method = await github_dispatch_service.route_item(
        db, item, slots, repo_labels=[], issue_labels=["nothing"],
    )
    architect = next(s for s in slots if s.display_name == "Architect")
    assert owner_id == architect.id  # first enabled slot by position
    assert method == "leader_fallback"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k route -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement routing + concurrency**

Create `backend/app/services/github_dispatch_service.py`:

```python
"""Routing + dispatch lifecycle for autonomous GitHub dispatch (spec §5)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AgentTeamSlot, GithubWorkItem, TeamGithubScope

_BUSY_STATUSES = ("dispatched", "verifying")


class GithubDispatchService:
    async def route_item(
        self,
        db: AsyncSession,
        item: GithubWorkItem,
        preset_slots: list[AgentTeamSlot],
        repo_labels: list[str],
        issue_labels: list[str],
        classify=None,
    ) -> tuple[int | None, str]:
        enabled = [s for s in preset_slots if s.enabled]
        enabled.sort(key=lambda s: s.position)
        if not enabled:
            return None, "leader_fallback"

        # 1. Mechanical label match.
        issue_label_set = set(issue_labels)
        for slot in enabled:
            slot_areas = set(slot.area_labels or [])
            if slot_areas & issue_label_set:
                return slot.id, "label"

        # 2. Classification fallback (only if some slot has expertise + a classifier is available).
        classifiable = [s for s in enabled if s.expertise]
        if classifiable and classify is not None:
            chosen = await classify(item, classifiable)
            if chosen is not None:
                return chosen, "classified"

        # 3. Leader fallback: first enabled slot by position.
        return enabled[0].id, "leader_fallback"

    async def slot_is_busy(self, db: AsyncSession, slot_id: int) -> bool:
        active = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.owner_slot_id == slot_id,
                    GithubWorkItem.dispatch_status.in_(_BUSY_STATUSES),
                )
            )
        ).first()
        if active is not None:
            return True
        pending_handoff = (
            await db.execute(
                select(GithubWorkItem.id).where(
                    GithubWorkItem.handoff_state == "pending",
                    (GithubWorkItem.owner_slot_id == slot_id)
                    | (GithubWorkItem.handoff_target_slot_id == slot_id),
                )
            )
        ).first()
        return pending_handoff is not None


github_dispatch_service = GithubDispatchService()
```

- [ ] **Step 4: Run the routing tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k route -v`
Expected: PASS.

- [ ] **Step 5: Write failing tests for `slot_is_busy`**

Add to the dispatch test file:

```python
@pytest.mark.asyncio
async def test_slot_busy_when_dispatched_item_exists(db):
    preset, slots, scope = await _team(db)
    backend = next(s for s in slots if s.display_name == "Backend SME")
    db.add(GithubWorkItem(scope_id=scope.id, issue_number=10, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(),
                          dispatch_status="dispatched", owner_slot_id=backend.id))
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is True


@pytest.mark.asyncio
async def test_slot_free_when_only_awaiting_human_review(db):
    preset, slots, scope = await _team(db)
    backend = next(s for s in slots if s.display_name == "Backend SME")
    db.add(GithubWorkItem(scope_id=scope.id, issue_number=11, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(),
                          dispatch_status="awaiting_human_review", owner_slot_id=backend.id))
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is False


@pytest.mark.asyncio
async def test_slot_busy_during_pending_handoff_on_both_sides(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    db.add(GithubWorkItem(scope_id=scope.id, issue_number=12, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(),
                          dispatch_status="dispatched",
                          owner_slot_id=architect.id,
                          handoff_state="pending", handoff_target_slot_id=backend.id))
    await db.commit()
    assert await github_dispatch_service.slot_is_busy(db, architect.id) is True
    assert await github_dispatch_service.slot_is_busy(db, backend.id) is True
```

- [ ] **Step 6: Run to verify they pass** (Step 3 implementation covers these)

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add routing (label/classify/leader) + per-slot concurrency"
```

---

## Task 6: Dispatch execution — launch + approval-round cap + two-phase handoff

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py` (extend)

**Interfaces:**
- Consumes: routing/concurrency from Task 5; `AgentTeamService.launch` + `repo_path_override` from Task 2.
- Produces, added to `GithubDispatchService`:
  - `async def dispatch_pending(self, db, scope, preset_slots, client=None, classify=None, launcher=None) -> None` — for each `pending` item: route, gate on `slot_is_busy` (set `pending_reason="queued_slot_busy"` and skip if busy), else launch via `launcher` (injectable; defaults to `AgentTeamService.launch`), set `owner_slot_id`/`routing_method`/`launch_id`/`dispatch_status="dispatched"`, clear `pending_reason`.
  - `async def record_approval_round(self, db, item, scope) -> None` — increments `approval_round_count`; if it reaches `scope.max_approval_rounds`, sets `dispatch_status="escalated"`, `escalation_reason="approval_rounds_exhausted"`.
  - `async def initiate_handoff(self, db, item, target_slot_id) -> None` — sets `handoff_state="pending"`, `handoff_target_slot_id=target_slot_id` (owner_slot_id NOT changed yet).
  - `async def accept_handoff(self, db, item, accepting_slot_id) -> None` — validates `accepting_slot_id == item.handoff_target_slot_id` (raises `ValueError` if mismatch), then sets `owner_slot_id=accepting_slot_id`, `handoff_state="accepted"`, `handoff_target_slot_id=None`, `routing_method="reassigned"`.

- [ ] **Step 1: Write failing tests for dispatch_pending + approval cap + handoff**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_pending_launches_and_marks_dispatched(db):
    preset, slots, scope = await _team(db)
    backend = next(s for s in slots if s.display_name == "Backend SME")
    item = GithubWorkItem(scope_id=scope.id, issue_number=20, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="pending")
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
        db, scope, slots, client=_LabelsClient(["area:backend"]),
        classify=None, launcher=fake_launcher,
        issue_labels_by_number={20: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    assert item.owner_slot_id == backend.id
    assert item.routing_method == "label"
    assert item.launch_id == 99
    assert item.pending_reason is None
    assert launched["override"] == scope.repo_path


@pytest.mark.asyncio
async def test_dispatch_pending_queues_when_slot_busy(db):
    preset, slots, scope = await _team(db)
    backend = next(s for s in slots if s.display_name == "Backend SME")
    # Backend already busy on another item.
    db.add(GithubWorkItem(scope_id=scope.id, issue_number=21, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(),
                          dispatch_status="dispatched", owner_slot_id=backend.id))
    item = GithubWorkItem(scope_id=scope.id, issue_number=22, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="pending")
    db.add(item)
    await db.commit()

    async def fake_launcher(db_, preset_id, request):
        raise AssertionError("should not launch a busy slot")

    await github_dispatch_service.dispatch_pending(
        db, scope, slots, client=_LabelsClient(["area:backend"]),
        launcher=fake_launcher, issue_labels_by_number={22: ["area:backend"]},
    )
    await db.refresh(item)
    assert item.dispatch_status == "pending"
    assert item.pending_reason == "queued_slot_busy"


@pytest.mark.asyncio
async def test_approval_round_cap_escalates(db):
    preset, slots, scope = await _team(db)
    scope.max_approval_rounds = 2
    item = GithubWorkItem(scope_id=scope.id, issue_number=30, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="dispatched",
                          approval_round_count=0)
    db.add(item)
    await db.commit()
    await github_dispatch_service.record_approval_round(db, item, scope)  # 1
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"
    await github_dispatch_service.record_approval_round(db, item, scope)  # 2 -> cap
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "approval_rounds_exhausted"


@pytest.mark.asyncio
async def test_two_phase_handoff(db):
    preset, slots, scope = await _team(db)
    architect, backend = slots[0], slots[1]
    item = GithubWorkItem(scope_id=scope.id, issue_number=40, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="dispatched",
                          owner_slot_id=architect.id)
    db.add(item)
    await db.commit()

    await github_dispatch_service.initiate_handoff(db, item, backend.id)
    await db.refresh(item)
    assert item.handoff_state == "pending"
    assert item.handoff_target_slot_id == backend.id
    assert item.owner_slot_id == architect.id  # not changed yet

    # Wrong slot cannot claim it.
    with pytest.raises(ValueError):
        await github_dispatch_service.accept_handoff(db, item, architect.id)

    await github_dispatch_service.accept_handoff(db, item, backend.id)
    await db.refresh(item)
    assert item.owner_slot_id == backend.id
    assert item.handoff_state == "accepted"
    assert item.handoff_target_slot_id is None
    assert item.routing_method == "reassigned"
```

Add this small labels-client stub near the top of the file (below `_team`):

```python
class _LabelsClient:
    def __init__(self, labels):
        self._labels = labels
    async def list_repo_labels(self, owner, repo):
        return list(self._labels)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k "dispatch_pending or approval or handoff" -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement the lifecycle methods**

Append to `class GithubDispatchService` in `backend/app/services/github_dispatch_service.py` (add imports at top: `from app.models.schemas import AgentTeamLaunchRequest` and `from app.services.agent_team_service import agent_team_service`):

```python
    async def dispatch_pending(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        client=None,
        classify=None,
        launcher=None,
        issue_labels_by_number: dict[int, list[str]] | None = None,
    ) -> None:
        from app.services.github_client import github_client as _default_client
        client = client or _default_client
        launcher = launcher or agent_team_service.launch
        issue_labels_by_number = issue_labels_by_number or {}
        repo_labels = await client.list_repo_labels(scope.repo_owner, scope.repo_name)

        pending = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "pending",
                )
            )
        ).scalars().all()

        for item in pending:
            issue_labels = issue_labels_by_number.get(item.issue_number, [])
            owner_slot_id, method = await self.route_item(
                db, item, preset_slots, repo_labels, issue_labels, classify=classify
            )
            if owner_slot_id is None:
                item.dispatch_status = "escalated"
                item.escalation_reason = "plan_blocked"
                continue
            if await self.slot_is_busy(db, owner_slot_id):
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_slot_busy"
                continue
            result = await launcher(
                db,
                scope.preset_id,
                AgentTeamLaunchRequest(
                    slot_ids=[owner_slot_id],
                    skip_plan_confirmation=True,
                    repo_path_override=scope.repo_path,
                ),
            )
            item.owner_slot_id = owner_slot_id
            item.routing_method = method
            item.launch_id = getattr(result, "launch_id", None)
            item.dispatch_status = "dispatched"
            item.pending_reason = None
            item.updated_at = datetime.utcnow()
        await db.commit()

    async def record_approval_round(
        self, db: AsyncSession, item: GithubWorkItem, scope: TeamGithubScope
    ) -> None:
        item.approval_round_count += 1
        if item.approval_round_count >= scope.max_approval_rounds:
            item.dispatch_status = "escalated"
            item.escalation_reason = "approval_rounds_exhausted"
        item.updated_at = datetime.utcnow()
        await db.commit()

    async def initiate_handoff(
        self, db: AsyncSession, item: GithubWorkItem, target_slot_id: int
    ) -> None:
        item.handoff_state = "pending"
        item.handoff_target_slot_id = target_slot_id
        item.updated_at = datetime.utcnow()
        await db.commit()

    async def accept_handoff(
        self, db: AsyncSession, item: GithubWorkItem, accepting_slot_id: int
    ) -> None:
        if item.handoff_target_slot_id != accepting_slot_id:
            raise ValueError(
                f"slot {accepting_slot_id} cannot accept a handoff targeted at "
                f"{item.handoff_target_slot_id}"
            )
        item.owner_slot_id = accepting_slot_id
        item.handoff_state = "accepted"
        item.handoff_target_slot_id = None
        item.routing_method = "reassigned"
        item.updated_at = datetime.utcnow()
        await db.commit()
```

- [ ] **Step 4: Run the lifecycle tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -v`
Expected: PASS (all dispatch tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add dispatch execution, approval-round cap, two-phase handoff"
```

---

## Task 7: `deck_report_dispatch_status` MCP tool

**Files:**
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Modify: `backend/app/api/v1/agent_teams.py` (add the REST endpoint the tool posts to) + `backend/app/models/schemas.py` (request model)
- Test: `backend/tests/agent_mail/test_dispatch_status_tool.py`

**Interfaces:**
- Consumes: dispatch lifecycle methods (Task 6); the shim's existing `_deck_request` prefix-aware helper (`backend/mcp_shim/agent_mail_server.py:79`).
- Produces:
  - REST: `POST /api/v1/agent-teams/dispatch-status` accepting `DispatchStatusReport` (`work_item_id: int`, `status: str`, `pr_number: int | None`, `reassign_to_slot_id: int | None`, `note: str | None`); dispatches to the right lifecycle method by `status`.
  - MCP tool `deck_report_dispatch_status(work_item_id, status, pr_number=None, reassign_to_slot_id=None, note=None)` in the shim, using a new `_dispatch_request` wrapper (`_deck_request(method, "agent-teams", ...)`).
- Status → action mapping (Phase A subset; `pr_opened` verification handoff is Phase B, so here `pr_opened` only records `pr_number` and leaves status advancement to Phase B):
  - `"triaging"` / `"revision_requested"` → `record_approval_round`
  - `"handoff_initiated"` (needs `reassign_to_slot_id`) → `initiate_handoff`
  - `"handoff_accepted"` → `accept_handoff` (accepting slot resolved from the reporting member's `team_slot_id`)
  - `"blocked"` → set `escalated` + `escalation_reason="agent_blocked"`, store `note`
  - `"pr_opened"` / `"in_progress"` → record only (`pr_number` stored if present); no status transition in Phase A

- [ ] **Step 1: Write the failing REST endpoint test**

Create `backend/tests/agent_mail/test_dispatch_status_tool.py`:

```python
"""Tests for the dispatch-status REST endpoint backing the MCP tool."""
import httpx
import pytest
import pytest_asyncio
from datetime import datetime

from app.database import get_db
from app.main import app
from app.models.database import AgentTeamPreset, AgentTeamSlot, TeamGithubScope, GithubWorkItem
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.database import Base


@pytest_asyncio.fixture
async def client_and_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, maker
    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_item(maker, **overrides):
    async with maker() as db:
        preset = AgentTeamPreset(name="T", description="", created_by="t")
        db.add(preset); await db.flush()
        scope = TeamGithubScope(preset_id=preset.id, repo_owner="o", repo_name="r",
                                repo_path="/tmp/r", max_approval_rounds=2)
        db.add(scope); await db.flush()
        item = GithubWorkItem(scope_id=scope.id, issue_number=1, issue_title="x", issue_url="u",
                              github_updated_at=datetime.utcnow(), dispatch_status="dispatched",
                              **overrides)
        db.add(item); await db.commit(); await db.refresh(item)
        return item.id


@pytest.mark.asyncio
async def test_triaging_increments_and_caps(client_and_db):
    ac, maker = client_and_db
    item_id = await _seed_item(maker, approval_round_count=1)
    resp = await ac.post("/api/v1/agent-teams/dispatch-status",
                         json={"work_item_id": item_id, "status": "triaging"})
    assert resp.status_code == 200
    async with maker() as db:
        item = await db.get(GithubWorkItem, item_id)
        assert item.dispatch_status == "escalated"
        assert item.escalation_reason == "approval_rounds_exhausted"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -v`
Expected: FAIL — 404 (endpoint doesn't exist).

- [ ] **Step 3: Add the request schema**

In `backend/app/models/schemas.py`, near the other agent-team request models, add:

```python
class DispatchStatusReport(BaseModel):
    work_item_id: int
    status: str
    pr_number: Optional[int] = None
    reassign_to_slot_id: Optional[int] = None
    note: Optional[str] = None
    reporting_slot_id: Optional[int] = None  # resolved server-side for handoff_accepted
```

- [ ] **Step 4: Add the REST endpoint**

In `backend/app/api/v1/agent_teams.py`, add (import `DispatchStatusReport`, `github_dispatch_service`, `GithubWorkItem`, `TeamGithubScope` as needed):

```python
@router.post("/dispatch-status")
async def report_dispatch_status(
    report: DispatchStatusReport,
    db: AsyncSession = Depends(get_db),
):
    item = await db.get(GithubWorkItem, report.work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="work item not found")
    scope = await db.get(TeamGithubScope, item.scope_id)

    if report.status in ("triaging", "revision_requested"):
        await github_dispatch_service.record_approval_round(db, item, scope)
    elif report.status == "handoff_initiated":
        if report.reassign_to_slot_id is None:
            raise HTTPException(status_code=400, detail="reassign_to_slot_id required")
        await github_dispatch_service.initiate_handoff(db, item, report.reassign_to_slot_id)
    elif report.status == "handoff_accepted":
        if report.reporting_slot_id is None:
            raise HTTPException(status_code=400, detail="reporting_slot_id required")
        try:
            await github_dispatch_service.accept_handoff(db, item, report.reporting_slot_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    elif report.status == "blocked":
        item.dispatch_status = "escalated"
        item.escalation_reason = "agent_blocked"
        item.updated_at = __import__("datetime").datetime.utcnow()
        await db.commit()
    elif report.status in ("pr_opened", "in_progress"):
        if report.pr_number is not None:
            item.pr_number = report.pr_number
            item.updated_at = __import__("datetime").datetime.utcnow()
            await db.commit()
    else:
        raise HTTPException(status_code=400, detail=f"unknown status {report.status}")

    await db.refresh(item)
    return {"work_item_id": item.id, "dispatch_status": item.dispatch_status,
            "escalation_reason": item.escalation_reason, "handoff_state": item.handoff_state}
```

- [ ] **Step 5: Run the endpoint test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -v`
Expected: PASS.

- [ ] **Step 6: Add the MCP tool + `_dispatch_request` wrapper**

In `backend/mcp_shim/agent_mail_server.py`, after `_bridge_request` (line 109), add:

```python
def _dispatch_request(method: str, path: str, **kwargs) -> dict:
    return _deck_request(method, "agent-teams", path, **kwargs)
```

And after the existing team tools (near `deck_launch_team`), add:

```python
@mcp.tool()
def deck_report_dispatch_status(
    work_item_id: int,
    status: str,
    pr_number: int = None,
    reassign_to_slot_id: int = None,
    note: str = None,
) -> dict:
    """Report progress on a Claude-Deck-dispatched GitHub issue back to the brain.

    status is one of: triaging, revision_requested, in_progress, pr_opened,
    handoff_initiated (with reassign_to_slot_id), handoff_accepted, blocked.
    Called by the owner slot the brain dispatched the issue to. Include
    work_item_id from your bootstrap prompt.
    """
    identity = _ensure_registered()
    payload = {
        "work_item_id": work_item_id,
        "status": status,
        "pr_number": pr_number,
        "reassign_to_slot_id": reassign_to_slot_id,
        "note": note,
        "reporting_slot_id": identity.get("team_slot_id"),
    }
    return _dispatch_request("POST", "/dispatch-status", json=payload)
```

(Confirm `_ensure_registered()` returns a dict including `team_slot_id`; if the key differs, use the actual identity key that carries the reporting session's slot id — check `deck_whoami`'s payload shape.)

- [ ] **Step 7: Write + run a shim smoke test**

Add to `backend/tests/agent_mail/test_dispatch_status_tool.py`:

```python
def test_shim_exposes_dispatch_status_tool():
    import importlib
    shim = importlib.import_module("mcp_shim.agent_mail_server")
    assert hasattr(shim, "deck_report_dispatch_status")
    assert hasattr(shim, "_dispatch_request")
```

Run: `cd backend && source venv/bin/activate && pytest tests/agent_mail/test_dispatch_status_tool.py -v`
Expected: PASS. (If `mcp_shim` isn't importable as a package, mirror however existing `tests/agent_mail/` imports the shim — check an existing shim test for the exact import path.)

- [ ] **Step 8: Commit**

```bash
git add backend/mcp_shim/agent_mail_server.py backend/app/api/v1/agent_teams.py backend/app/models/schemas.py backend/tests/agent_mail/test_dispatch_status_tool.py
git commit -m "feat(dispatch): add deck_report_dispatch_status MCP tool + REST endpoint"
```

---

## Task 8: Monitoring — wake_state-gated leader-offline detection

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py` (extend)

**Interfaces:**
- Consumes: `agent_mail_service.list_team(db)` → `list[MailMemberResponse]` (each has `team_slot_id`, `wake_state ∈ {"wakeable","delivered_waiting","offline"}`); `GithubWorkItem` (Task 1).
- Produces, added to `GithubDispatchService`:
  - `async def monitor_dispatched(self, db, scope, now=None, idle_threshold_seconds=..., wake_state_by_slot=None) -> None` — for each `dispatched` item in the scope with no PR yet: resolve the owner slot's leader wake_state; if the **leader** slot's wake_state is `offline`, escalate immediately (`escalation_reason="leader_offline"`); otherwise apply idle-timeout nudge/escalate. `wake_state_by_slot` is injectable (`{slot_id: wake_state}`) so tests don't need the full agent-mail stack; when None, it's built from `agent_mail_service.list_team`.
- Escalation reason `leader_offline`.

- [ ] **Step 1: Write the failing test for immediate offline escalation**

Add to `backend/tests/agent_teams/test_github_dispatch_service.py`:

```python
@pytest.mark.asyncio
async def test_monitor_escalates_when_leader_offline(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]  # first-by-position = leader
    item = GithubWorkItem(scope_id=scope.id, issue_number=50, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="dispatched",
                          owner_slot_id=slots[1].id)
    db.add(item)
    await db.commit()

    # Leader (architect) is offline.
    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "offline", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "escalated"
    assert item.escalation_reason == "leader_offline"


@pytest.mark.asyncio
async def test_monitor_leaves_item_when_leader_reachable(db):
    preset, slots, scope = await _team(db)
    architect = slots[0]
    item = GithubWorkItem(scope_id=scope.id, issue_number=51, issue_title="x", issue_url="u",
                          github_updated_at=datetime.utcnow(), dispatch_status="dispatched",
                          owner_slot_id=slots[1].id)
    db.add(item)
    await db.commit()
    await github_dispatch_service.monitor_dispatched(
        db, scope, preset_slots=slots,
        wake_state_by_slot={architect.id: "wakeable", slots[1].id: "wakeable"},
    )
    await db.refresh(item)
    assert item.dispatch_status == "dispatched"  # still healthy
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k monitor -v`
Expected: FAIL — `monitor_dispatched` not defined.

- [ ] **Step 3: Implement the monitor pass**

Append to `class GithubDispatchService`:

```python
    async def monitor_dispatched(
        self,
        db: AsyncSession,
        scope: TeamGithubScope,
        preset_slots: list[AgentTeamSlot],
        wake_state_by_slot: dict[int, str] | None = None,
    ) -> None:
        # Leader = first enabled slot by position (spec §5a convention).
        enabled = sorted([s for s in preset_slots if s.enabled], key=lambda s: s.position)
        if not enabled:
            return
        leader = enabled[0]

        if wake_state_by_slot is None:
            from app.services.agent_mail_service import agent_mail_service
            members = await agent_mail_service.list_team(db)
            wake_state_by_slot = {
                m.team_slot_id: m.wake_state for m in members if m.team_slot_id is not None
            }
        leader_wake = wake_state_by_slot.get(leader.id, "offline")

        dispatched = (
            await db.execute(
                select(GithubWorkItem).where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status == "dispatched",
                    GithubWorkItem.pr_number.is_(None),
                )
            )
        ).scalars().all()

        for item in dispatched:
            if leader_wake == "offline":
                item.dispatch_status = "escalated"
                item.escalation_reason = "leader_offline"
                item.updated_at = datetime.utcnow()
            # else: leader reachable — idle-timeout nudge/escalate is Phase A-deferred
            # to a follow-up (needs agent-mail last-activity plumbing); the offline
            # fast-path is the load-bearing V7 fix and is implemented here.
        await db.commit()
```

Note: the idle-timeout nudge branch (leader reachable but owner idle) requires last-activity timestamps from the agent-mail layer that are heavier to wire and test. Per spec §6 the **offline fast-path is the primary V7 fix**; the reachable-but-idle nudge is implemented as a thin follow-up. This task delivers the offline detection (the highest-value, cleanly-testable half) and explicitly defers the idle-nudge half rather than faking it. Record this in the PR description as a known scoped-down item, not a silent omission.

- [ ] **Step 4: Run the monitor tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/agent_teams/test_github_dispatch_service.py -k monitor -v`
Expected: PASS.

- [ ] **Step 5: Run the entire backend suite for regressions**

Run: `cd backend && source venv/bin/activate && pytest tests/ -q`
Expected: PASS — no pre-existing tests broken by any Phase A change.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/github_dispatch_service.py backend/tests/agent_teams/test_github_dispatch_service.py
git commit -m "feat(dispatch): add wake_state-gated leader-offline monitoring"
```

---

## Self-Review

**1. Spec coverage (§3–§6 only; §7 verify/merge and §10 frontend are Phase B/C):**

| Spec section | Task |
|---|---|
| §3.1 `TeamGithubScope` | Task 1 |
| §3.1a `area_labels`/`expertise` on slot | Task 1 |
| §3.2 `GithubWorkItem` (incl. `pending_reason`, `handoff_state`, `handoff_target_slot_id`, `approval_round_count`, `escalation_reason`) | Task 1 |
| §3 `autonomy_enabled` on preset | Task 1 |
| §3.3 `repo_path_override` | Task 2 |
| §4 watcher polling + `issue_type` (step 2) | Task 4 |
| §4 step 3a escalated recovery | Task 4 |
| §4 step 3b active-item label recheck | Task 4 |
| §4 `GITHUB_TOKEN` setting | Task 1 |
| §5a routing (label/classify/leader) | Task 5 |
| §5b per-slot concurrency + `pending_reason` | Tasks 5, 6 |
| §5c approval-round cap | Task 6 |
| §5c two-phase handoff | Task 6 |
| §5d `deck_report_dispatch_status` tool | Task 7 |
| §6 wake_state leader-offline detection | Task 8 |

Gaps deliberately scoped out of Phase A (each will be a Phase B task, flagged so they're not forgotten): §6 reachable-but-idle nudge branch (Task 8 note); §7 entire verify/merge pipeline incl. `pr_opened` status advancement (Task 7 records `pr_number` but doesn't advance status); the APScheduler wiring that *calls* `poll_scope`/`dispatch_pending`/`monitor_dispatched` on an interval (these services are built and unit-tested; wiring them into a running background loop is deferred — see note below). No §3–§6 requirement is un-tasked.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". Every code step shows complete code; every test step shows the full test.

**3. Type consistency:** `route_item` returns `(slot_id, method)` consistently used by `dispatch_pending`; `slot_is_busy` statuses (`dispatched`,`verifying` + pending-handoff) match `_BUSY_STATUSES` and Task 8's `dispatched` query; `escalation_reason` strings match the Global Constraints list; `dispatch_status` values are consistent across watcher (`_ACTIVE_STATUSES`/`_RECOVERABLE_STATUSES`), dispatch, and monitor.

**One scoping call-out surfaced by self-review:** the plan builds three services with a `poll_scope`/`dispatch_pending`/`monitor_dispatched` shape ready to be driven on a schedule, but does NOT add the APScheduler job that calls them on an interval (spec §4/§9 hosted mode). That's intentional — the scheduler is a single small integration task best done once all three services exist and are individually proven, and it's the natural first task of Phase B (or a Phase A "Task 9" if you want autonomy actually *running* at the end of Phase A rather than just callable). Flagging it as an explicit decision for you rather than silently including or omitting it.
