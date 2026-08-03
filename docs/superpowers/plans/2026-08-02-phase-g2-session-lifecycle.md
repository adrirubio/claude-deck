# Phase G2 — Session Lifecycle and Workspace Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace process-liveness with an explicit, attempt-scoped workspace release protocol, then flip dispatch to one-session-per-slot with a delivery guarantee for the brief.

**Architecture:** Two PRs, release protocol first. PR1 makes every workspace lease attempt-scoped via a per-acquisition `lease_token`, adds an agent-reported `workspace_released` status, and replaces `reclaim_stale`'s single liveness gate with a five-condition conjunction whose signals cannot be true-by-design. PR2 flips `reuse_existing=True` and closes the three delivery defects that flip would otherwise expose. Sequencing is mandatory: flipping first creates Finding 19's permanent wedge with no releaser in place.

**Tech Stack:** FastAPI, async SQLAlchemy 2.0 (`Mapped`/`mapped_column`), aiosqlite, pydantic-settings, pytest + pytest-asyncio. Frontend React 19 + TS (one small change in PR1).

**Spec:** `docs/superpowers/specs/2026-08-02-phase-g2-session-lifecycle-design.md` — read §1 and §3 before starting. Every task below cites the spec section it implements; where this plan and the spec disagree, the spec wins and you should stop and report the disagreement.

---

## Global Constraints

These apply to **every** task. They are not negotiable and several are safety rules earned from live incidents.

**Working environment — you are on the SAME machine as the live soak**

This is the single most important section. Everything below is reachable from your shell; none of it is on another host.

- Work **only** in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
- **Never** touch `/home/juan/work/repos/juanrubio/claude-deck`. It holds `backend/claude_registry.db` — 1.1 MB, 28 work items, the evidence that made Findings 17/18/19 provable. It cannot be regenerated.
- **Never** touch `/home/juan/work/repos/tizonia/`. Five tmux sessions (`tizonia-openmax-il-{7845,afde,b19f,fd9c,fe2f}`) hold it as cwd right now, and workspace 1 is that checkout registered as `primary`.
- **`claude-deck-g1` is a git worktree of the live checkout, not a clone.** `cat .git` there reads `gitdir: .../claude-deck/.git/worktrees/claude-deck-g1`. They share one object store, one ref namespace, one stash, one index lock. Consequences you must respect:
  - Do **not** run `git worktree prune`, `git gc`, `git stash`, or any `git checkout`/`switch` of a branch already checked out in the other worktree.
  - Do **not** `git branch -f`, `git reset --hard`, or delete refs the other worktree may be on (`feature/autonomous-github-dispatch` is checked out live).
  - `git worktree list` will show `/tmp/pr303-verify` and `/tmp/pr305-review` as detached-HEAD worktrees. Leave them alone; they are the orchestrator's, pending cleanup.
- A backend process is running (one `uvicorn`). Do not restart, stop, or reload it. Note `database_url` defaults to `sqlite+aiosqlite:///./claude_registry.db` — **relative to the process CWD**, so anything you run from the live checkout's `backend/` directory touches the live DB. Run tests from `claude-deck-g1/backend` only.
- Autonomy is currently **OFF** (`agent_team_presets.autonomy_enabled = 0` for both presets, verified 2026-08-03). Leave it at 0.

**Git**
- Branch from and target `feature/autonomous-github-dispatch`. **One PR per phase** (PR1, then PR2).
- Never merge, self-merge, or push to `master`.
- **Starting state:** `claude-deck-g1` is currently on `feature/autonomous-github-dispatch-workspaces`, which is already merged (PR #305) and 10 commits behind the integration branch. Your first action is:
  ```bash
  cd /home/juan/work/repos/juanrubio/claude-deck-g1
  git fetch origin
  git checkout -b feature/autonomous-github-dispatch-phase-g2-release origin/feature/autonomous-github-dispatch
  ```
  Use `origin/feature/autonomous-github-dispatch` as the base, **not** the local branch of that name — the local one is checked out in the live worktree and a shared-worktree checkout of it would fail. PR2 branches separately, from the integration branch again after PR1 merges.

**Forbidden operations** (all of these have caused incidents)
- Do **not** add any new `dispatch_status` value. This design needs none — see spec §3.1 and §3.1a-bis.
- Do **not** enable or disable autonomy. It stays **OFF** for the whole of both PRs.
- Do **not** spawn or kill agent sessions.
- Do **not** hand-edit DB rows. Schema changes go through the migration ladder (Task 1).
- Do **not** restart the backend.
- Do **not** retry work item 23, or any other escalated item.

**Code style**
- Type hints throughout; `async`/`await` for all DB access.
- New settings go in `app/config.py` as pydantic-settings fields with defaults — no `.env` required.
- Datetimes: `datetime.utcnow()` to match every neighbouring call site. The suite emits deprecation warnings for this already; do **not** "fix" them here, it would be an unrelated cross-cutting change.
- New columns: `Mapped[X | None] = mapped_column(..., nullable=True)`.

**Testing**
- Baseline is **239 passed** in `backend/tests/agent_teams/` — verified 2026-08-03 *inside `claude-deck-g1` itself*, so it is your starting number, not a figure from another checkout. Run with:
  `cd /home/juan/work/repos/juanrubio/claude-deck-g1/backend && source venv/bin/activate && python -m pytest tests/agent_teams/ -q`
- **Use `venv`, not `.venv`.** Both directories exist in `claude-deck-g1/backend`; `.venv` has no pytest installed and will fail with `No module named pytest`. Do not try to fix `.venv` — just use `venv`.
- Always `cd` to the **g1** backend before running pytest. `database_url` is relative to CWD, so running from the live checkout's `backend/` would point the suite at the live soak DB.
- Every task ends green. If a test fails for a reason your task did not cause, **report it, do not rewrite it.**
- Known pre-existing failure **outside** this directory: `tests/test_multi_provider_smoke.py:54` (stale monkeypatch). Ignore it; an issue is owed separately.

**Stop and report** if a step's preconditions do not match what you find — a wrong line number is fine to adapt to, but a wrong *shape* (the function does something other than described) means the spec's reasoning may not hold.

---

## File Structure

No new files. Both PRs are edits to eight existing backend modules, and the responsibility boundaries already in place are the right ones — the release protocol is workspace-lifecycle logic, so it belongs in the workspace service, and dispatch only calls into it.

| File | Responsibility here | Tasks |
|---|---|---|
| `app/models/database.py` | The eight new nullable columns | 1 |
| `app/database.py` | Migration ladder entries (new `github_workspaces` block) | 1 |
| `app/config.py` | `github_stale_lease_backstop_seconds` | 1 |
| `app/services/github_workspace_service.py` | Owns the lease: token minting, pid liveness, the release conjunction, dirty-tree veto, owner-contact stamping | 2, 3, 4, 6 |
| `app/services/github_dispatch_service.py` | Owns dispatch: pid capture after launch, retry deferral + promotion, release reminders, delivery evidence, ambiguity refusal, the `reuse_existing` flip | 3, 4, 5, 8, 10, 12, 13 |
| `app/api/v1/agent_teams.py` | The `workspace_released` report branch, force-release, response fields | 5, 6, 9 |
| `app/models/schemas.py` | `lease_token` in, lease state and `retry_requested_at` out | 1, 3, 5, 6, 9 |
| `app/services/agent_mail_service.py` | Finding 17's rule; the non-throttled dispatch wake | 7, 11 |
| `app/services/github_watcher_service.py` | Calls the promotion sweep from `poll_scope` | 5 |
| `app/services/github_verification_service.py` | Clears `retry_requested_at` on legitimate recovery | 5 |
| `mcp_shim/agent_mail_server.py` | Forwards `lease_token` from the agent-facing tool | 6 |

`github_dispatch_service.py` is the one file taking most of the change, and it is already large. Do **not** split it as part of these PRs — it is the live soak's hottest file and a reorganisation would make the diff unreviewable against the spec. If it needs splitting, that is its own change on a quiet branch.

---

# PR1 — The release protocol

Nine tasks. After Task 9 the branch is ready for review; autonomy stays off.

Tasks 8 and 9 are §6's mitigations. They are **not optional trimming**: without them a lease held by a live-but-silent session is held *indefinitely*, which §6 states is not an acceptable ceiling. If you are running short, say so and stop — do not ship Tasks 1–7 alone and call PR1 done.

---

### Task 1: Schema — eight nullable columns and one setting

**Files:**
- Modify: `backend/app/models/database.py:285-311` (`GithubWorkspace`), `:240-282` (`GithubWorkItem`)
- Modify: `backend/app/database.py:419-432` (the `github_work_items` migration block), and add a new `github_workspaces` block after `:432`
- Modify: `backend/app/config.py:38-47`
- Test: `backend/tests/agent_teams/test_github_workspace_service.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GithubWorkspace.lease_token: str | None`, `.leased_owner_pid: int | None`, `.leased_owner_proc_start: str | None`, `.lease_last_owner_contact_at: datetime | None`, `.lease_release_reminded_at: datetime | None`; `GithubWorkItem.retry_requested_at: datetime | None`, `.brief_delivery_nudge_at: datetime | None`, `.brief_delivery_nudge_count: int | None`; `settings.github_stale_lease_backstop_seconds: int`.

Implements spec §3.2 (column inventory), §7 step 1 (migration mechanism).

**Why all eight land in one task:** they are one `ADD COLUMN` sweep against two tables plus one settings line. Splitting them would produce commits that add a column no code reads, and the migration ladder is the single riskiest step in the deployment (§7) — it deserves one reviewable diff. `brief_delivery_nudge_*` belong to PR2 but the columns are added here so PR2 needs no second migration.

**One deliberate delta from the spec.** §3.2 and §7 step 1 both inventory **seven** columns. This task adds an eighth, `lease_release_reminded_at`, needed by §6 mitigation 1 (release reminders, Task 8) — the spec specifies that mitigation without naming its clock. Do not substitute `last_nudge_at` for it: that field already multiplexes the leader-ack and owner-idle timers, `reset_for_retry` does **not** clear it, and `monitor_dispatched:645` reads `if item.last_nudge_at is None: nudge_leader` **else escalate**. A reminder timestamp surviving into a retried item would therefore escalate `leader_ack_timeout` without the leader ever being nudged. Putting it on the workspace row instead means `release` clears it for free, and it is exactly the field §6 mitigation 2 wants exposed. This is §4.1a's multiplexing lesson recurring one column over.

- [ ] **Step 1: Read the migration ladder before touching it**

Read `backend/app/database.py:290-449` (`_run_sqlite_compat_migrations`). Note the established pattern: `PRAGMA table_info` → a set of column names → `if <table>_columns and "<col>" not in <table>_columns: ALTER TABLE ... ADD COLUMN`. It is idempotent and runs from `init_db` (`:452-458`) on every startup.

**The spec was wrong about this once already** (§7 step 1 records the correction): `CLAUDE.md` claims "No database migration system — schema changes require deleting the db". That is false. Do not delete any database.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/agent_teams/test_github_workspace_service.py`:

```python
@pytest.mark.asyncio
async def test_lease_columns_default_to_null(db, tmp_path):
    """A lease predating G2 must read as 'no information', never as a false negative.

    Spec §3.2: a NULL pid makes backstop condition 3 unsatisfiable, so any
    lease that predates this migration is retained rather than reclaimed.

    Verified against the live DB 2026-08-03: both workspaces are currently
    UNLEASED (leased_item_id IS NULL), so no real row exercises this on the
    first migration. The test therefore constructs the state, and the guarantee
    still has to hold — the next acquire() after deployment writes a lease whose
    pid capture may fail, landing in exactly this shape.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
    )
    db.add(workspace)
    await db.commit()

    assert workspace.lease_token is None
    assert workspace.leased_owner_pid is None
    assert workspace.leased_owner_proc_start is None
    assert workspace.lease_last_owner_contact_at is None
    assert workspace.lease_release_reminded_at is None
    assert item.retry_requested_at is None
    assert item.brief_delivery_nudge_at is None
    assert item.brief_delivery_nudge_count is None
```

- [ ] **Step 3: Run it and watch it fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_workspace_service.py::test_lease_columns_default_to_null -v`
Expected: FAIL — `AttributeError: 'GithubWorkspace' object has no attribute 'lease_token'`

- [ ] **Step 4: Add the ORM columns**

In `backend/app/models/database.py`, inside `class GithubWorkspace`, after `released_at` (`:302`):

```python
    lease_token: Mapped[str | None] = mapped_column(String, nullable=True)
    leased_owner_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leased_owner_proc_start: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_last_owner_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_release_reminded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

`leased_owner_proc_start` is a **String**, not an Integer: it is field 22 of `/proc/<pid>/stat` compared only for equality, and storing it verbatim avoids any int-parse ambiguity.

Inside `class GithubWorkItem`, after `last_nudge_at` (`:273`):

```python
    retry_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brief_delivery_nudge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    brief_delivery_nudge_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`brief_delivery_nudge_count` is nullable rather than `default=0, nullable=False`: an `ADD COLUMN` on an existing SQLite table cannot backfill a NOT NULL column without a default, and treating NULL as "never nudged" is exactly right. PR2 reads it as `(item.brief_delivery_nudge_count or 0)`.

- [ ] **Step 5: Add the migration entries**

In `backend/app/database.py`, extend the existing `github_work_items` block (after `:432`):

```python
    if work_item_columns and "retry_requested_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN retry_requested_at DATETIME"))
    if work_item_columns and "brief_delivery_nudge_at" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_delivery_nudge_at DATETIME"))
    if work_item_columns and "brief_delivery_nudge_count" not in work_item_columns:
        await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN brief_delivery_nudge_count INTEGER"))
```

Then add a **new** block for `github_workspaces`, which has no entries yet:

```python
    workspace_columns = await _sqlite_columns(conn, "github_workspaces")
    if workspace_columns and "lease_token" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN lease_token VARCHAR"))
    if workspace_columns and "leased_owner_pid" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN leased_owner_pid INTEGER"))
    if workspace_columns and "leased_owner_proc_start" not in workspace_columns:
        await conn.execute(text("ALTER TABLE github_workspaces ADD COLUMN leased_owner_proc_start VARCHAR"))
    if workspace_columns and "lease_last_owner_contact_at" not in workspace_columns:
        await conn.execute(
            text("ALTER TABLE github_workspaces ADD COLUMN lease_last_owner_contact_at DATETIME")
        )
    if workspace_columns and "lease_release_reminded_at" not in workspace_columns:
        await conn.execute(
            text("ALTER TABLE github_workspaces ADD COLUMN lease_release_reminded_at DATETIME")
        )
```

Place it **before** the final `await conn.commit()` at `:449`. Use `_sqlite_columns` (the helper at `:64`) for the new block rather than an inline `PRAGMA`; both styles exist in the file and the helper is the better one.

All eight are nullable with no default — that is what makes `ADD COLUMN` legal on SQLite and what makes every pre-existing row read as "no information".

- [ ] **Step 6: Add the setting**

In `backend/app/config.py`, after `github_min_available_memory_mb` (`:47`):

```python
    github_stale_lease_backstop_seconds: int = 21600  # 6h; see G2 design §3.2, §6
```

A settings field, not a module constant — matching `github_leader_ack_timeout_seconds` and its four neighbours. 6h is explicitly a guess (spec §6) and needs an operator override. Condition 2 and condition 4's contact-ageing share this one number.

- [ ] **Step 7: Run the new test and the full suite**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_workspace_service.py::test_lease_columns_default_to_null -v`
Expected: PASS

Run: `python -m pytest tests/agent_teams/ -q`
Expected: **240 passed** (239 baseline + 1 new)

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/database.py backend/app/database.py backend/app/config.py \
        backend/tests/agent_teams/test_github_workspace_service.py
git commit -m "feat(g2): add lease-identity and retry-deferral columns

Eight nullable columns via the existing compat ladder (database.py:290), so
every checkout migrates itself on restart and no SQL is hand-applied to the
live soak DB. NULL on pre-existing rows means 'no information', which keeps
item 23's lease un-reclaimable — the correct outcome.

Adds github_stale_lease_backstop_seconds (6h) as a settings field, matching
the pattern of every other dispatch threshold."
```

---

### Task 2: `_owner_process_is_alive` — liveness that survives pid reuse

**Files:**
- Modify: `backend/app/services/github_workspace_service.py` (new private method + import)
- Test: `backend/tests/agent_teams/test_github_workspace_service.py`

**Interfaces:**
- Consumes: Task 1's columns.
- Produces: `GithubWorkspaceService._read_proc_start(self, pid: int) -> str | None` and `GithubWorkspaceService._owner_process_is_alive(self, workspace: GithubWorkspace) -> bool`. Task 4's conjunction calls `_owner_process_is_alive`; Task 3's dispatch capture calls `_read_proc_start`.

Implements spec §3.2 (the `/proc` parse, pid-reuse guard, and the unknown→alive rule).

**Why its own task:** it is a pure function with a nasty parse and a three-way error contract, and it is the one piece of PR1 whose failure mode is silent (a wrong parse yields plausible-but-wrong liveness). It deserves a reviewer's gate before anything depends on it.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/agent_teams/test_github_workspace_service.py`:

```python
def test_read_proc_start_handles_comm_containing_spaces_and_parens():
    """Field 2 of /proc/<pid>/stat is parenthesized and may contain spaces or parens.

    A naive split() puts starttime at the wrong index. Spec §3.2 pins the
    rindex(")") recipe; this fixture is the case that breaks the naive version.
    """
    service = GithubWorkspaceService(runner=FakeGitRunner())
    raw = "12345 (weird (proc) name) S 1 12345 12345 0 -1 4194560 " + " ".join(
        str(n) for n in range(100, 118)
    ) + " 987654321 " + " ".join(str(n) for n in range(200, 210))

    fields = raw[raw.rindex(")") + 2:].split()

    assert fields[19] == "987654321"
    assert service._parse_proc_start(raw) == "987654321"


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_when_pid_is_null(db, tmp_path):
    """Unknown liveness is treated as alive: the safe direction (spec §3.2)."""
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id, path=str(tmp_path / "ws"), leased_item_id=item.id
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_owner_process_alive_is_false_for_dead_pid(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=4194303,
        leased_owner_proc_start="123",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is False


@pytest.mark.asyncio
async def test_owner_process_alive_is_false_when_proc_start_differs(db, tmp_path, monkeypatch):
    """Pid reuse: same pid, different start time, is a DIFFERENT process.

    Spec §3.2 — Finding 18's trap one level down, an identifier whose
    uniqueness is assumed rather than guaranteed.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start="999999999",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    assert service._owner_process_is_alive(workspace) is False


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_for_this_process(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start=service._read_proc_start(os.getpid()),
    )
    db.add(workspace)
    await db.commit()

    assert service._owner_process_is_alive(workspace) is True


@pytest.mark.asyncio
async def test_owner_process_alive_is_true_when_proc_unreadable(db, tmp_path, monkeypatch):
    """An OSError that is not 'no such process' means UNKNOWN, so: alive, lease retained.

    Deliberately the opposite of _effective_status's fail-closed choice for the
    same error (spec §2.4 records why: the backstop retains a resource, the UI
    reports a status).
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    workspace = GithubWorkspace(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start="123",
    )
    db.add(workspace)
    await db.commit()
    service = GithubWorkspaceService(runner=FakeGitRunner())

    def _boom(_pid):
        raise PermissionError("denied")

    monkeypatch.setattr(service, "_read_proc_start", _boom)

    assert service._owner_process_is_alive(workspace) is True
```

Add `import os` to the test file's imports if absent.

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_workspace_service.py -k "proc_start or owner_process_alive" -v`
Expected: FAIL — `AttributeError: ... has no attribute '_parse_proc_start'`

- [ ] **Step 3: Implement**

In `backend/app/services/github_workspace_service.py`, add `import pathlib` at the top, then add these three methods to `GithubWorkspaceService` (put them after `_run_git`, before `acquire`):

```python
    def _parse_proc_start(self, raw: str) -> str | None:
        """Field 22 (starttime) of a /proc/<pid>/stat line.

        Field 2 (comm) is parenthesized and may contain spaces or parentheses,
        so the fields after it are located from the LAST ')' — a naive split()
        silently returns the wrong field. Index 19 is field 22 overall,
        counting from state (field 3) at index 0.
        """
        try:
            return raw[raw.rindex(")") + 2:].split()[19]
        except (ValueError, IndexError):
            return None

    def _read_proc_start(self, pid: int) -> str | None:
        """Raises FileNotFoundError/ProcessLookupError if the process is gone.

        Any other OSError propagates: the caller must treat it as UNKNOWN, not
        as death.
        """
        return self._parse_proc_start(
            pathlib.Path(f"/proc/{pid}/stat").read_text()
        )

    def _owner_process_is_alive(self, workspace: GithubWorkspace) -> bool:
        """Is the process that was briefed with this lease still running?

        Unknown counts as alive. A NULL pid (every pre-G2 lease, and any
        dispatch whose pid capture failed) is therefore never reclaimable —
        the safe direction, since guessing 'dead' risks a reset --hard under a
        working agent.
        """
        if workspace.leased_owner_pid is None:
            return True
        try:
            current_start = self._read_proc_start(workspace.leased_owner_pid)
        except (FileNotFoundError, ProcessLookupError):
            return False
        except OSError:
            return True
        if current_start is None or workspace.leased_owner_proc_start is None:
            return True
        return current_start == workspace.leased_owner_proc_start
```

Note `FileNotFoundError` is a subclass of `OSError`, so its `except` clause must come **first**. That ordering is the whole contract.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/agent_teams/test_github_workspace_service.py -k "proc_start or owner_process_alive" -v`
Expected: 6 PASS

Run: `python -m pytest tests/agent_teams/ -q`
Expected: **246 passed**

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/github_workspace_service.py \
        backend/tests/agent_teams/test_github_workspace_service.py
git commit -m "feat(g2): pid liveness that survives reuse and unreadable /proc

Parses field 22 from the last ')' — a naive split() lands on the wrong field
whenever comm contains a space or paren. Pairs pid with proc start time so
'alive' means THIS process, not A process.

Three-way error contract: no-such-process => dead; any other OSError or a NULL
pid => unknown, treated as alive so the lease is retained. Deliberately the
opposite of _effective_status's fail-closed choice for the same error; the
backstop retains a resource, the UI reports a status."
```

---

### Task 3: Mint the lease token and capture the owner pid

**Files:**
- Modify: `backend/app/services/github_workspace_service.py:61-105` (`acquire`)
- Modify: `backend/app/services/github_dispatch_service.py:276-293` (post-launch block)
- Modify: `backend/app/models/schemas.py:2336-2347` (`AgentTeamLaunchResultItem`)
- Modify: `backend/app/services/agent_team_service.py` (populate the new result field)
- Test: `backend/tests/agent_teams/test_github_workspace_service.py`, `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: Task 1's columns, Task 2's `_read_proc_start`.
- Produces: `acquire` now sets `workspace.lease_token` to a fresh `secrets.token_hex(8)` on every real acquisition; `AgentTeamLaunchResultItem.pane_pid: int | None`.

Implements spec §3.1a (token per acquisition), §3.2 (pid captured after launch, not at acquire).

**The ordering correction that makes this task non-obvious:** `acquire` runs at `github_dispatch_service.py:222`, **before** `launcher(...)` at `:251`. On the spawn path the owning pane does not exist yet, so the pid cannot be captured inside `acquire`. It is written in a second step where `dispatched_at` is already set (`:288`).

- [ ] **Step 1: Write the failing tests**

In `test_github_workspace_service.py`:

```python
@pytest.mark.asyncio
async def test_acquire_mints_a_fresh_token_each_acquisition(db, tmp_path):
    """The token names the ACQUISITION, not the item (spec §3.1a).

    Two acquisitions of the SAME item must not share a token, or a stale
    release from attempt 1 can return attempt 2's live lease — Finding 10
    through a new door.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    first = await service.acquire(db, scope, item)
    first_token = first.lease_token
    await service.release(db, item.id)
    second = await service.acquire(db, scope, item)

    assert first_token is not None
    assert second.lease_token is not None
    assert second.lease_token != first_token


@pytest.mark.asyncio
async def test_acquire_returning_held_lease_does_not_remint(db, tmp_path):
    """acquire()'s early return hands back the EXISTING lease unchanged.

    This is the step-4 hazard in spec §3.1a-bis: if a token were minted here
    without a reset, the caller would believe it had a fresh workspace. The
    retry deferral (Task 5) is what prevents this path being reached; this
    test pins that acquire itself does not lie about it.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    service = GithubWorkspaceService(runner=FakeGitRunner())
    workspace = GithubWorkspace(scope_id=scope.id, path=str(tmp_path / "ws"))
    db.add(workspace)
    await db.commit()

    first = await service.acquire(db, scope, item)
    token = first.lease_token
    again = await service.acquire(db, scope, item)

    assert again.id == first.id
    assert again.lease_token == token
```

In `test_github_dispatch_service.py`, find how existing dispatch tests build their fake launcher result (search for `tmux_target`), then add a test asserting that after a successful dispatch the leased workspace has `leased_owner_pid` set from the launch result's `pane_pid`, and that a launch result with `pane_pid=None` leaves it NULL while still reaching `dispatch_status == "dispatched"`.

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_workspace_service.py -k "token" -v`
Expected: FAIL — `assert None is not None`

- [ ] **Step 3: Mint the token in `acquire`**

Add `import secrets` to `github_workspace_service.py`. In `acquire`, in the block that claims a free workspace (`:90-95`), add the token beside the other lease fields:

```python
        now = datetime.utcnow()
        workspace.leased_item_id = item.id
        workspace.leased_at = now
        workspace.released_at = None
        workspace.lease_token = secrets.token_hex(8)
        workspace.leased_owner_pid = None
        workspace.leased_owner_proc_start = None
        workspace.lease_last_owner_contact_at = None
        workspace.lease_release_reminded_at = None
        workspace.updated_at = now
        await db.commit()
```

The four explicit `None` assignments matter: a workspace row is **reused** across leases, so a previous lease's pid and contact timestamp must be cleared or the backstop would evaluate the new lease against the old owner's evidence. Same defect family as everything else in this design.

Leave the `held is not None` early return (`:67-73`) **exactly as it is**. It must not mint a token, because it does not reset the workspace.

- [ ] **Step 4: Clear the same fields in `release`**

In `release` (`:107-119`), alongside `leased_item_id = None`:

```python
        workspace.leased_item_id = None
        workspace.released_at = now
        workspace.lease_token = None
        workspace.leased_owner_pid = None
        workspace.leased_owner_proc_start = None
        workspace.lease_last_owner_contact_at = None
        workspace.lease_release_reminded_at = None
        workspace.updated_at = now
```

`release` clearing the reminder stamp is why it lives on the workspace row rather than the item: a lease that is released and later re-acquired starts its reminder clock fresh with no extra code.

- [ ] **Step 5: Add `pane_pid` to the launch result**

In `backend/app/models/schemas.py`, in `AgentTeamLaunchResultItem` (`:2336-2347`), after `tmux_target`:

```python
    pane_pid: Optional[int] = None
```

Then populate it in `agent_team_service.py` wherever `tmux_target` is set on a result item — for both the spawn and reuse branches. Search for `tmux_target=` in that file. The pane pid is already available from `agent_bridge/discovery.py` (`pane_pid`, `:20`/`:92`); prefer whatever value the launch path already has in hand over a fresh discovery call, because a second tmux round-trip can race the pane's own startup (spec §3.2).

If the launch path genuinely has no pid available without a discovery call, leave `pane_pid=None` and **report this** — a NULL pid is a supported outcome (the lease simply stays un-reclaimable), and adding a racy discovery call to avoid it would be the worse trade.

- [ ] **Step 6: Capture the pid after launch**

In `github_dispatch_service.py`, in the `else` branch where dispatch succeeds (`:286-290`):

```python
            else:
                item.dispatch_status = "dispatched"
                item.dispatched_at = datetime.utcnow()
                pane_pid = getattr(launch_item, "pane_pid", None)
                if pane_pid is not None:
                    workspace.leased_owner_pid = pane_pid
                    try:
                        workspace.leased_owner_proc_start = (
                            github_workspace_service._read_proc_start(pane_pid)
                        )
                    except OSError:
                        workspace.leased_owner_proc_start = None
                    workspace.updated_at = datetime.utcnow()
                slots_dispatched_this_batch.add(owner_slot_id)
                scope_dispatched_this_batch += 1
```

A failed pid capture must **never** fail a dispatch that otherwise succeeded (spec §3.2) — hence the bare `except OSError` and the absence of any re-raise.

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: all pass, count = 246 + the tests you added.

- [ ] **Step 8: Commit**

```bash
git add -A backend/app backend/tests
git commit -m "feat(g2): mint a per-acquisition lease token, capture the owner pid

acquire() mints secrets.token_hex(8) per real acquisition and clears the
previous lease's pid/contact fields — a workspace row outlives its leases, so
stale owner evidence would otherwise be evaluated against a new lease.

The early-return path (held is not None) deliberately does NOT mint: it
performs no reset, so a fresh token there would be a lie. Task 5's retry
deferral is what keeps that path from being reached.

Pid is captured after launch, not in acquire: acquire runs before launcher(),
so on the spawn path the pane does not exist yet. A failed capture leaves NULL
and never fails the dispatch."
```

---

### Task 4: The backstop conjunction

**Files:**
- Modify: `backend/app/services/github_workspace_service.py:121-146` (`reclaim_stale`)
- Modify: `backend/app/services/github_dispatch_service.py:114-...` (delete `slot_has_live_owner_session`), `:215-221` (delete its dispatch gate)
- Test: `backend/tests/agent_teams/test_github_workspace_service.py:210-260` (rewrite two tests), `test_github_dispatch_service.py:1299` (delete one)

**Interfaces:**
- Consumes: Task 1's columns, Task 2's `_owner_process_is_alive`, Task 3's token.
- Produces: `reclaim_stale` returns the count of leases released under the five-condition conjunction.

Implements spec §3.2 (the conjunction), §3.2a (owner-contact recency), §2.2 (deleting the predicate).

**Read spec §1.2 before starting this task.** The predicate being deleted is not merely wrong — it is *permanently true* under one-session-per-slot, which is why `reclaim_stale` released 0 forever. Do not replace it with anything that asks "is the slot's session alive?"; that is the trap §3.2a documents.

- [ ] **Step 1: Rewrite the two tests that monkeypatch the deleted predicate**

`test_reclaim_releases_non_working_item_without_live_owner` (`:211`) and `test_reclaim_retains_non_working_item_with_live_owner` (`:236`) both `monkeypatch.setattr(github_dispatch_service, "slot_has_live_owner_session", ...)`. That attribute will not exist. Rewrite them as the five cases of the conjunction:

```python
def _stale_lease(scope, tmp_path, item, **overrides):
    """A lease that satisfies every RELEASE condition unless overridden."""
    fields = dict(
        scope_id=scope.id,
        path=str(tmp_path / "ws"),
        leased_item_id=item.id,
        leased_at=datetime.utcnow() - timedelta(seconds=25000),  # > 6h
        lease_token="t1",
        leased_owner_pid=4194303,       # dead
        leased_owner_proc_start="123",
        lease_last_owner_contact_at=None,  # never spoke
    )
    fields.update(overrides)
    return GithubWorkspace(**fields)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["escalated", "failed", "merged", "completed"])
async def test_reclaim_releases_dead_silent_clean_lease(db, tmp_path, status):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = status
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    count = await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope)

    assert count == 1


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_live_owner_process(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    service = GithubWorkspaceService(runner=FakeGitRunner())
    db.add(_stale_lease(
        scope, tmp_path, item,
        leased_owner_pid=os.getpid(),
        leased_owner_proc_start=service._read_proc_start(os.getpid()),
    ))
    await db.commit()

    assert await service.reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_within_threshold(db, tmp_path):
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(
        scope, tmp_path, item, leased_at=datetime.utcnow() - timedelta(seconds=60)
    ))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_dirty_tree(db, tmp_path):
    """Git-quiescence is a VETO, never a cause (spec §3.2).

    Deck must not discard uncommitted work its own sweep can see.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    runner = FakeGitRunner()
    runner.statuses[str(tmp_path / "ws")] = " M src/foo.c\n"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=runner).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_retains_lease_with_recent_owner_contact(db, tmp_path):
    """A REPLACEMENT owner must not be mistaken for a dead one (spec §3.2a).

    The recorded pid is dead because the session restarted; the agent resumed
    the item under a new process and is still reporting. Releasing here would
    reset --hard under a live agent — the backstop as the weapon.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(
        scope, tmp_path, item,
        lease_last_owner_contact_at=datetime.utcnow() - timedelta(seconds=60),
    ))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_reclaim_releases_when_owner_contact_has_aged_out(db, tmp_path):
    """The complement of the test above: contact older than the threshold ages out."""
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(
        scope, tmp_path, item,
        lease_last_owner_contact_at=datetime.utcnow() - timedelta(seconds=25000),
    ))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 1


@pytest.mark.asyncio
async def test_reclaim_never_touches_a_leased_primary_workspace(db, tmp_path):
    """The conjunction is defined for WORKTREE workspaces (spec §3.2).

    A primary checkout is a human's working tree; git status there says nothing
    about Deck's leases.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "escalated"
    db.add(_stale_lease(scope, tmp_path, item, kind="primary"))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0


@pytest.mark.asyncio
async def test_ready_for_review_is_not_reclaimable(db, tmp_path):
    """M12's guard, owed from PR A §6.

    ready_for_review is a real dispatch_status (github_verification_service.py:102)
    and is correctly absent from _RECLAIMABLE_STATUSES. This test pins that
    omission as a decision rather than an accident — exclusion lists are
    systematically under-tested.
    """
    scope, _, item = await _context(db, tmp_path / "repo")
    item.dispatch_status = "ready_for_review"
    db.add(_stale_lease(scope, tmp_path, item))
    await db.commit()

    assert await GithubWorkspaceService(runner=FakeGitRunner()).reclaim_stale(db, scope) == 0
```

Add `from datetime import datetime, timedelta` and `import os` to the test imports as needed.

- [ ] **Step 2: Delete the obsolete dispatch test**

Delete `test_queued_owner_session_dispatches_after_session_goes_offline` (`test_github_dispatch_service.py:1299`). It tests the `queued_owner_session_live` queue state, which ceases to exist in Step 4.

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_workspace_service.py -k reclaim -v`
Expected: FAIL — the parametrized release test finds `count == 1` only by accident of the old gate; the retain tests fail because no conjunction exists yet.

- [ ] **Step 4: Implement the conjunction**

Replace `reclaim_stale` (`:121-146`) with:

```python
    async def reclaim_stale(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        """Release leases whose owner is provably gone.

        Five conditions, ALL required. They fail in opposite directions — a
        stale pid resolving to an unrelated live process says 'alive' and costs
        throughput; a clean tree says 'idle' and could cost a working agent's
        checkout. Requiring all five means any disagreement retains the lease,
        so the safe error dominates.

        This replaces PR A's single slot_has_live_owner_session gate, which
        Finding 19 showed is permanently TRUE under one-session-per-slot — the
        sweep released 0 forever. See design §1.2 and §3.2.
        """
        threshold = datetime.utcnow() - timedelta(
            seconds=settings.github_stale_lease_backstop_seconds
        )
        leased = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem)
                .join(GithubWorkItem, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_RECLAIMABLE_STATUSES),
                )
                .order_by(GithubWorkspace.id)
            )
        ).all()
        released = 0
        for workspace, item in leased:
            # A leased primary is a human's working tree; git status there says
            # nothing about Deck's leases. Retain unconditionally.
            if workspace.kind == "primary":
                continue
            if workspace.leased_at is None or workspace.leased_at > threshold:
                continue
            if self._owner_process_is_alive(workspace):
                continue
            # A replacement owner reports; a crashed one goes quiet and ages out.
            if (
                workspace.lease_last_owner_contact_at is not None
                and workspace.lease_last_owner_contact_at > threshold
            ):
                continue
            if not await self._worktree_is_clean(workspace):
                continue
            await self.release(db, workspace.leased_item_id)
            released += 1
        return released

    async def _worktree_is_clean(self, workspace: GithubWorkspace) -> bool:
        """A veto, never a cause: it can only prevent a release.

        An unreadable worktree counts as dirty — same safe direction as an
        unknown pid.
        """
        return_code, output = await self._runner(
            ["-C", workspace.path, "status", "--porcelain"]
        )
        if return_code != 0:
            return False
        return not output.strip()
```

Add `from datetime import datetime, timedelta` and `from app.config import settings` to the module imports.

Note condition 4 as implemented is "no contact, **or** contact older than the threshold" — expressed as "skip if contact is *recent*". That matches spec §3.2a exactly.

- [ ] **Step 5: Delete the predicate and its dispatch gate**

In `github_dispatch_service.py`:
- Delete the `slot_has_live_owner_session` method (starts `:114`).
- Delete its gate in `dispatch_pending` (`:215-221`) — the whole `if await self.slot_has_live_owner_session(...)` block including the `queued_owner_session_live` assignment.

Keep `slot_is_busy` untouched. It is the logical one-item-per-slot guard and it was always correct (spec §2.2).

Grep for both names across `backend/` afterwards to catch any remaining reference:
`grep -rn "slot_has_live_owner_session\|queued_owner_session_live" backend/app backend/tests backend/mcp_shim frontend/src`

Frontend may reference the pending reason string for display; if so, remove that branch too.

- [ ] **Step 6: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green. Count changes — you deleted 1 test and the parametrized rewrite adds cases.

- [ ] **Step 7: Commit**

```bash
git add -A backend frontend
git commit -m "feat(g2)!: replace the liveness gate with a five-condition conjunction

Deletes slot_has_live_owner_session. Finding 19: under one-session-per-slot the
slot's session is alive permanently BY DESIGN, so the predicate PR A made the
only releaser was permanently true and reclaim_stale released 0 forever. The
first terminal item wedged the pool.

Release now requires all of: reclaimable status, lease older than the backstop
threshold, recorded owner process dead, no recent owner contact on this lease,
clean worktree. The signals fail in opposite directions, so requiring all five
makes the safe error (retain) dominate.

Condition 4 (owner contact) is what distinguishes a REPLACEMENT owner from a
dead one without asking 'is the slot alive?' — which would rebuild Finding 19
inside its own fix.

Also adds M12's owed guard test: ready_for_review is not reclaimable."
```

---

### Task 5: The deferred retry — `retry_requested_at`

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:38-49` (`reset_for_retry`), plus a new `promote_deferred_retries`
- Modify: `backend/app/services/github_watcher_service.py:28-45` (`poll_scope`)
- Modify: `backend/app/services/github_verification_service.py:60-61` (`report_pr_opened`'s recoverable branch)
- Modify: `backend/app/models/schemas.py:2255-2281` (`GithubWorkItemResponse`)
- Modify: `backend/app/api/v1/agent_teams.py:645-671` (retry endpoint), and `_work_item_response`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py:377`, plus new tests

**Interfaces:**
- Consumes: Task 1's `retry_requested_at`, Task 3's token.
- Produces: `github_dispatch_service.promote_deferred_retries(db, scope) -> int`, called from `poll_scope`.

Implements spec §3.1a-bis in full. **Read that section before starting — all of it.** It documents a trap that the obvious implementation walks into.

- [ ] **Step 1: Rewrite the test that asserts the old behaviour**

`test_reset_for_retry_does_not_release_workspace` (`test_github_dispatch_service.py:377`) currently asserts `item.dispatch_status == "pending"` **with the lease still held** — the exact state this task makes unreachable. Its name and its lease assertion stay true; only the status assertion inverts:

```python
@pytest.mark.asyncio
async def test_reset_for_retry_defers_while_a_lease_is_held(db):
    """Retry must not overtake release (spec §3.1a-bis).

    Flipping straight to 'pending' both locks the legitimate releaser out (a
    non-terminal item cannot release, §3.1c) and lets the next acquire() return
    the EXISTING lease via its early return — so no token is minted and
    reset_workspace never runs. The new owner silently inherits a dirty tree.
    That silent reset skip, not the wedge, is the real harm.
    """
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=909,
        issue_title="retry",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="escalated",
        escalation_reason="plan_blocked",
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

    github_dispatch_service.reset_for_retry(item)
    await db.commit()

    assert item.dispatch_status == "escalated"
    assert item.retry_requested_at is not None
    assert workspace.leased_item_id == item.id
    # escalation_reason is load-bearing while the item stays escalated
    assert item.escalation_reason == "plan_blocked"
```

- [ ] **Step 2: Write the new tests**

```python
@pytest.mark.asyncio
async def test_reset_for_retry_without_a_lease_is_unchanged(db):
    """The common path must not change (spec §3.1a-bis)."""
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

    github_dispatch_service.reset_for_retry(item)

    assert item.dispatch_status == "pending"
    assert item.retry_requested_at is None
    assert item.escalation_reason is None
    assert item.ack_received_at is None


@pytest.mark.asyncio
async def test_promote_deferred_retry_after_release(db):
    """Once the lease is gone the deferred reset applies in full."""
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
```

Also write, in `test_github_verification_service.py` (or wherever `report_pr_opened` is tested), a test that a recoverable escalated item with `retry_requested_at` set has it **cleared** by `report_pr_opened` — otherwise a stamp left behind re-pends the item the next time it escalates, weeks later, as a re-dispatch nobody requested.

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/agent_teams/test_github_dispatch_service.py -k retry -v`
Expected: FAIL

- [ ] **Step 4: Make `reset_for_retry` conditional**

It is currently synchronous and takes only the item. It now needs to know whether a lease is held, so it becomes async and takes the session:

```python
    async def reset_for_retry(self, db: AsyncSession, item: GithubWorkItem) -> None:
        """Request re-dispatch. Defers if the item still holds a workspace lease.

        While a lease is held this mutates NOTHING but retry_requested_at,
        status_note and updated_at. Clearing escalation_reason here would break
        two things, because that field is load-bearing while the item stays
        'escalated':

          1. report_pr_opened treats an escalated item as recoverable only when
             escalation_reason is in _PR_OPENED_RECOVERABLE_ESCALATIONS. A
             cleared reason makes the owner's pr_opened report raise instead of
             recovering — the retry request would destroy the very recovery
             path the owner was about to use.
          2. _apply_escalation's idempotence guard is
             `dispatch_status == "escalated" and escalation_reason`. A cleared
             reason turns a no-op re-escalation into one that overwrites
             status_note, discarding the operator's original context.

        See design §3.1a-bis.
        """
        held = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item.id)
            )
        ).scalar_one_or_none()
        now = datetime.utcnow()
        if held is not None:
            item.retry_requested_at = now
            item.status_note = (
                "Re-dispatch requested; waiting for the current owner to release "
                f"workspace {held.path}."
            )
            item.updated_at = now
            return
        item.dispatch_status = "pending"
        item.escalation_reason = None
        item.pending_reason = None
        item.handoff_state = None
        item.handoff_target_slot_id = None
        item.pr_number = None
        item.ack_received_at = None
        item.last_verified_sha = None
        item.retry_count = 0
        item.approval_round_count = 0
        item.retry_requested_at = None
        item.updated_at = now
```

Update both callers to `await`:
- `github_watcher_service.py:78` → `await github_dispatch_service.reset_for_retry(db, existing)`
- `agent_teams.py:666` → `await github_dispatch_service.reset_for_retry(db, item)`

- [ ] **Step 5: Add the promotion sweep**

Add to `GithubDispatchService`:

```python
    async def promote_deferred_retries(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        """Complete deferred retries whose lease has since been released."""
        candidates = (
            await db.execute(
                select(GithubWorkItem)
                .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkItem.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(("escalated", "failed")),
                    GithubWorkItem.retry_requested_at.is_not(None),
                    GithubWorkspace.id.is_(None),
                )
                .order_by(GithubWorkItem.id)
            )
        ).scalars().all()
        for item in candidates:
            await self.reset_for_retry(db, item)
        if candidates:
            await db.commit()
        return len(candidates)
```

Calling `reset_for_retry` here is deliberate: the lease is gone, so it takes the immediate branch and applies the full reset — one definition of "what a retry does", not two.

- [ ] **Step 6: Call the sweep from `poll_scope`, not from `dispatch_pending`**

In `github_watcher_service.py`, in `poll_scope`, before `scope.last_polled_at = ...` (`:44`):

```python
        await github_dispatch_service.promote_deferred_retries(db, scope)
```

**Not in `dispatch_pending`, and this matters.** `github_dispatch_scheduler.py:132` fetches issue labels and details for `pending` items **before** calling `dispatch_pending` at `:137`. An item promoted inside `dispatch_pending` would be routed with an empty label set — falling through `route_item`'s label branch to `leader_fallback` (`:64-76`) — and briefed with `issue_details=None`. A retried item would silently route worse than a fresh one. `poll_scope` runs at `:124`, before the label fetch.

Cost: a lease released by the *backstop* (which runs inside `dispatch_pending`, after the sweep) is promoted on the following poll. One interval of latency on a path that already waited 6h.

- [ ] **Step 7: Clear the stamp on legitimate recovery**

In `github_verification_service.py`, in `report_pr_opened`'s recoverable branch (`:60-61`):

```python
        if recoverable:
            item.escalation_reason = None
            item.retry_requested_at = None
```

- [ ] **Step 8: Surface it on the API**

Add `retry_requested_at: Optional[datetime] = None` to `GithubWorkItemResponse` (`schemas.py:2255-2281`) and populate it in `_work_item_response` in `agent_teams.py`. Without this, `POST .../retry` returns an item still reading `escalated` and looks like it did nothing.

- [ ] **Step 9: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add -A backend
git commit -m "feat(g2): defer retry until the workspace lease is released

reset_for_retry no longer flips straight to 'pending' when a lease is held.
Composed with terminal-only release, that deadlocked: the watcher re-pends an
escalated item on any issue comment, the item leaves terminal status, the
legitimate owner's release is refused, and acquire()'s early return hands back
the EXISTING lease — so no token is minted and reset_workspace never runs. The
new owner inherits the previous attempt's dirty tree. The silent reset skip,
not the wedge, is the harm.

Uses a nullable retry_requested_at rather than a new dispatch_status: escalated
is already terminal-for-release, already reclaimable, and already
non-dispatchable, so all three needed properties come free and no state-machine
or UI change is required.

While a lease is held the reset defers ENTIRELY — clearing escalation_reason
would break report_pr_opened's recovery path and _apply_escalation's
idempotence guard, both of which read that field while the item stays
escalated.

The promotion sweep runs in poll_scope, not dispatch_pending: the scheduler
fetches issue labels for pending items before calling dispatch_pending, so an
item promoted there would route by leader_fallback instead of by label."
```

---

### Task 6: The `workspace_released` report

**Files:**
- Modify: `backend/app/models/schemas.py:2327-2333` (`DispatchStatusReport`)
- Modify: `backend/app/api/v1/agent_teams.py:267-323` (`report_dispatch_status`)
- Modify: `backend/app/services/github_workspace_service.py` (new `release_by_token`)
- Modify: `backend/app/services/github_dispatch_service.py` (`_dispatch_brief`)
- Modify: `backend/mcp_shim/agent_mail_server.py` (the `deck_report_dispatch_status` docstring/params)
- Test: `backend/tests/agent_teams/` (API-level tests — find the file that exercises `/dispatch-status`)

**Interfaces:**
- Consumes: Task 3's token, Task 5's deferral.
- Produces: `github_workspace_service.release_by_token(db, item_id, *, lease_token) -> None`, raising `ValueError` on mismatch; report status `workspace_released`.

Implements spec §3.1 (the report), §3.1a (token matching), §3.1c (when release is legal), §3.2a (stamping owner contact).

- [ ] **Step 1: Write the failing tests**

Cover all six behaviours. Find the existing `/dispatch-status` test file first (`grep -rln "dispatch-status" backend/tests/`) and follow its client fixture pattern:

1. Owner slot releases a `merged` item with the correct token → 200, `leased_item_id` is None.
2. **Non-owner** slot reports `workspace_released` → 409, lease retained.
3. Wrong token → 409, lease retained, response names the mismatch.
4. Repeat of the same token after release → 200 (idempotent), no error.
5. Release while `dispatch_status == "dispatched"` → 409 naming the current status, lease retained. Repeat for `verifying` and `ready_for_review`.
6. Release with a **dirty** tree (`FakeGitRunner().statuses[...] = " M src/foo.c\n"`) on an `escalated` item → 409, lease retained, response names the dirty paths. Pair with the clean-tree case → 200.
7. A `failed` item **with a live pane** can release → 200. Dispatch retains the lease on a failed launch when `tmux_target` is not None (`github_dispatch_service.py:282-285`) precisely because something may be running in it, so that state must have a release path.
8. Any **other** report status (`triaging`) stamps `lease_last_owner_contact_at` on the workspace row.

- [ ] **Step 2: Run and watch them fail**

Expected: FAIL — `400 unknown status workspace_released`

- [ ] **Step 3: Add `lease_token` to the report schema**

```python
class DispatchStatusReport(BaseModel):
    work_item_id: int
    status: str
    pr_number: Optional[int] = None
    reassign_to_slot_id: Optional[int] = None
    note: Optional[str] = None
    reporting_slot_id: Optional[int] = None
    lease_token: Optional[str] = None
```

- [ ] **Step 4: Implement `release_by_token`**

In `github_workspace_service.py`:

```python
    async def release_by_token(
        self, db: AsyncSession, item_id: int, *, lease_token: str
    ) -> None:
        """Release only the acquisition the token names.

        release() keys on leased_item_id alone, so it cannot tell one dispatch
        attempt of an item from the next — a stale report from attempt 1 would
        return attempt 2's live lease, and the next acquire would reset --hard
        under a working agent (design §3.1a).

        Idempotent when nothing is leased: a duplicated report is harmless.
        """
        workspace = (
            await db.execute(
                select(GithubWorkspace).where(GithubWorkspace.leased_item_id == item_id)
            )
        ).scalar_one_or_none()
        if workspace is None:
            return
        if workspace.lease_token != lease_token:
            raise GithubWorkspaceLeaseTokenMismatch(
                f"lease_token does not match the current lease for item {item_id}"
            )
        await self.release(db, item_id)
```

Add the exception beside the existing ones at the top of the module:

```python
class GithubWorkspaceLeaseTokenMismatch(GithubWorkspaceError):
    def __init__(self, message: str):
        super().__init__(message, "lease_token_mismatch")
```

- [ ] **Step 5: Add the endpoint branch**

In `agent_teams.py`, in `report_dispatch_status`, before the final `else`:

```python
    elif report.status == "workspace_released":
        if report.reporting_slot_id != item.owner_slot_id:
            raise HTTPException(
                status_code=409,
                detail="only the owner slot may release its workspace",
            )
        if report.lease_token is None:
            raise HTTPException(status_code=400, detail="lease_token required")
        # Release is GATED BY dispatch_status but never MOVES it. A non-terminal
        # item can still be sent back for more work (a failed check reopens a
        # verified SHA, an approval round asks for changes), and an owner that
        # released early would need a workspace it no longer holds. §3.1c
        if item.dispatch_status not in _RELEASABLE_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"workspace cannot be released while the item is "
                    f"{item.dispatch_status}; release is legal only from "
                    f"{', '.join(_RELEASABLE_STATUSES)}"
                ),
            )
        workspace = await github_workspace_service.get_leased_workspace(db, item.id)
        if workspace is not None:
            dirty = await github_workspace_service.dirty_paths(workspace)
            if dirty:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "workspace has uncommitted changes and will not be "
                        f"released: {dirty}. Commit and push, or report the "
                        "situation in status_note and leave the lease held."
                    ),
                )
        try:
            await github_workspace_service.release_by_token(
                db, item.id, lease_token=report.lease_token
            )
        except GithubWorkspaceLeaseTokenMismatch as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Define at module scope in **`github_dispatch_service.py`**, beside `_BUSY_STATUSES` (`:25`), and import it into `agent_teams.py`:

```python
# Release is legal only from a state that is terminal FOR THE OWNER. `failed`
# is included deliberately: dispatch retains the lease on a failed launch when
# a pane was created (github_dispatch_service.py:282-285), and the agent in
# that pane is the one entity that knows whether it is doing anything.
_RELEASABLE_STATUSES = ("merged", "completed", "escalated", "failed")
```

It goes in the service, not the endpoint, because Task 8 also needs it and the API layer already imports from the service — defining it in `agent_teams.py` would force the reverse import.

Add the two small helpers to `github_workspace_service.py` — `get_leased_workspace(db, item_id)` returning the row or None, and `dirty_paths(workspace)` returning the stripped `git status --porcelain` output (empty string when clean, and `""` for a `kind == "primary"` workspace, which is never leased and must not be inspected).

- [ ] **Step 6: Stamp owner contact on every report**

Still in `report_dispatch_status`, after the branch chain and before `await db.refresh(item)`:

```python
    # "Has the thing holding this lease spoken recently?" — the question the
    # backstop actually needs (§3.2a). A replacement owner that resumed the item
    # reports; a crashed one goes quiet and ages out. Independent of tmux,
    # session discovery and last_seen_at, so Finding 17's staleness cannot
    # corrupt it.
    if report.status != "workspace_released" and report.reporting_slot_id == item.owner_slot_id:
        await github_workspace_service.touch_owner_contact(db, item.id)
```

`touch_owner_contact(db, item_id)` sets `lease_last_owner_contact_at = utcnow()` on the leased workspace if there is one, and commits. It must be a no-op when nothing is leased.

- [ ] **Step 7: Teach the brief to name the token**

In `_dispatch_brief` (`github_dispatch_service.py:295`), add a `workspace_released` instruction alongside the existing `triaging` / `pr_opened` / `blocked` ones. It **must** include `workspace.lease_token` verbatim — the agent cannot derive it. State that release is required once the item reaches a terminal state, that the tree must be committed and pushed first, and give the exact `deck_report_dispatch_status` call.

Update `deck_report_dispatch_status` in `backend/mcp_shim/agent_mail_server.py` to accept and forward `lease_token`.

- [ ] **Step 8: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add -A backend
git commit -m "feat(g2): agent-reported workspace release, scoped to the attempt

Adds report status workspace_released. No new dispatch_status value — the
endpoint's triaging/ack_received/in_progress branches already set the precedent
for reports that do not move status.

Release names the TOKEN, not the item: release() keys on leased_item_id alone
and cannot tell one dispatch attempt from the next, so a stale report from a
previous attempt would return a live lease and the next acquire would reset
--hard under a working agent.

Gated by dispatch_status but never moves it. Legal only from merged, completed,
escalated or failed; 'failed' included because dispatch deliberately retains
the lease when a pane was created, and that agent is the only entity that knows
whether it is still working. Refused on a dirty tree — the same veto §3.2
applies to the backstop, since protecting uncommitted work from Deck's own
sweep while letting an agent discard it has no justification.

Every other owner report stamps lease_last_owner_contact_at, which is backstop
condition 4."
```

---

### Task 7: Finding 17 — observed rows resolve on their pid

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:628-631`
- Test: `backend/tests/agent_mail/` (find the `_effective_status` tests)

**Interfaces:**
- Consumes: nothing from earlier tasks (independent; it is in PR1 because the skew test is owed from PR A §6).
- Produces: nothing consumed later.

Implements spec §2.4 — read it, including the two implementation notes at the end.

**Scope warning:** this is a display-accuracy fix. Nothing destructive hangs off the predicate any more (Task 4 removed that). Do not expand it.

- [ ] **Step 1: Write the failing tests — one per row of the table**

The load-bearing one is the **skew**: a live pid with an expired TTL. Fixtures hide this class of defect by construction, because every test supplies its own timestamps — so it must be built deliberately, not as a plainly-live or plainly-offline object.

```python
def test_observed_session_past_ttl_with_live_pid_reads_connected():
    """Finding 17: five live agents displayed as offline.

    last_seen_at is refreshed only by sync_observed_sessions, whose callers are
    all interactive — so the column reflects when a human last opened the Agent
    Mail page, not whether the agent is alive. Spec §2.4 row 2.
    """
    service = agent_mail_service
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        mailbox_status="observed",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert service._effective_status(session, now) == "observed"


def test_revived_observed_session_is_still_nudgeable():
    """The revived status must be the one _session_can_nudge accepts.

    _session_can_nudge requires _effective_status == "observed" EXACTLY
    (agent_mail_service.py:600). Reviving these rows as "connected" would make
    every one of them un-nudgeable — turning a display fix into a delivery
    outage, and silently defeating Task 13's ambiguity check.
    """
    service = agent_mail_service
    now = datetime.utcnow()
    session = MailAgentSession(
        member_id=1,
        source="observed",
        provider="claude",
        tmux_target="tizonia:1.0",
        mailbox_status="observed",
        pid=os.getpid(),
        last_seen_at=now - timedelta(seconds=OBSERVED_TTL_SECONDS + 60),
    )

    assert service._session_can_nudge(session, now) is True
```

Then one test each for: expired + dead pid → `offline`; expired + NULL pid → `offline`; expired + unreadable `/proc` → `offline` (fail closed); and `mailbox_status == "offline"` + **live** pid + observed source → `offline` (an explicit disconnect wins). Also one within-TTL case asserting the status is returned unchanged.

That last one is the trap: it is what fails if you edit the wrong branch.

**A correction to the spec you must apply here.** §2.4's table says the revived value is `connected`, borrowing the word from the mcp branch. For an **observed** row that is wrong. Observed sessions are written with `mailbox_status = "observed"` (`:317`, `:393`), and `_session_can_nudge` tests `_effective_status(...) == "observed"` exactly, so returning `connected` would make every revived row fail that test and stop being nudgeable. Return the row's own `mailbox_status` instead — which is what the within-TTL path already does (`:632`). The table's *intent* (row 2: not `offline`) is preserved; only the literal is corrected. Verify with `grep -n "_effective_status" app/ -r` that no other caller distinguishes the two values: at the time of writing all seven either compare against `"offline"` or accept `{"connected", "observed"}` together.

- [ ] **Step 2: Run and watch the skew test fail**

Expected: FAIL — `assert 'offline' == 'connected'`

- [ ] **Step 3: Make the one-line change**

In `_effective_status`, in the TTL-expiry branch (`:628-631`) **only**:

```python
        if session.last_seen_at < now - timedelta(seconds=ttl):
            # An observed row carries a pid too. Resolving on it is what the mcp
            # branch already does; the asymmetry is why five live agents read as
            # offline (Finding 17). Fails closed on a NULL or unreadable pid —
            # _pid_is_running returns False for both — because here the cost of
            # guessing "alive" is a UI that lies, and possibly a nudge into a
            # dead pane.
            #
            # Returns the row's own mailbox_status, not the literal "connected":
            # observed rows carry "observed", and _session_can_nudge tests for
            # that exact value, so reviving them as "connected" would make every
            # one of them un-nudgeable.
            if session.pid and self._pid_is_running(session.pid):
                return session.mailbox_status
            return "offline"
```

An explicit `mailbox_status == "offline"` never reaches this branch — it returned at `:620` — so returning the row's own status here cannot resurrect a disconnected session.

**Do not touch the first block (`:615-619`).** It gives mcp rows a pre-emptive live-pid check that overrides an explicit `mailbox_status == "offline"`. Extending it to observed rows would satisfy the table's rows 2–4 while silently inverting row 5. The only edit is inside the TTL-expiry branch.

`_pid_is_running` is unchanged and stays the single implementation for both sources; it already returns `False` for `None` (`:603-605`) and for an unreadable `/proc` (`except OSError`, `:611-612`), so rows 3 and 4 need no new guard.

- [ ] **Step 4: Run the mail suite and the full backend suite**

Run: `python -m pytest tests/agent_mail/ -q && python -m pytest tests/agent_teams/ -q`
Expected: both green. If a mail test asserted the old offline behaviour, read it before changing it — and report it rather than rewriting if its intent looks deliberate.

- [ ] **Step 5: Commit**

```bash
git add -A backend
git commit -m "fix(g2): observed sessions past TTL resolve on their pid

_effective_status consulted _pid_is_running for source='mcp' rows but not for
source='observed' rows, though observed rows carry pids too. On the live host
five agents with running pids all read 'offline' because last_seen_at is
refreshed only by sync_observed_sessions, whose callers are all interactive —
the column recorded when a human last opened the Agent Mail page.

Only the TTL-expiry branch changes. The earlier mcp block overrides an explicit
disconnect, and extending that to observed rows would invert the rule that an
explicit disconnect wins.

Fails closed on a NULL or unreadable pid: the cost of guessing 'alive' here is
a UI that lies. That is deliberately the opposite of the backstop's treatment
of the same error, which retains a resource instead."
```

---

### Task 8: Release reminders — bound the forgot-to-report hold

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py` (new `remind_held_leases`, called from `monitor_dispatched`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

**Interfaces:**
- Consumes: Task 1's `lease_release_reminded_at`, Task 3's token, Task 5's `retry_requested_at`, Task 6's `_RELEASABLE_STATUSES`.
- Produces: `github_dispatch_service.remind_held_leases(db, scope) -> int`.

Implements spec §6 mitigation 1. **This is PR1 scope, not a nice-to-have.** §6 is explicit that the exposure is *unbounded*, not 6h: the backstop is a conjunction requiring the owner process to be **dead**, and under one-session-per-slot a standing session that simply never reports stays **alive** — so condition 3 never holds and the lease is held indefinitely. 6h bounds only the crash case. Nothing bounds the forgot-to-report case except this reminder and the Task 9 force-release.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_terminal_item_holding_a_lease_is_reminded(db):
    """The only bound on a forgot-to-report hold (spec §6 mitigation 1).

    The backstop cannot help: it requires a DEAD owner process, and the whole
    point of one-session-per-slot is that the session stays alive.
    """
    _, _, scope = await _team(db)
    item = GithubWorkItem(
        scope_id=scope.id,
        issue_number=920,
        issue_title="merged but not released",
        issue_url="u",
        github_updated_at=datetime.utcnow(),
        dispatch_status="merged",
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
    workspace.lease_token = "tok-abc"
    await db.commit()

    reminded = await github_dispatch_service.remind_held_leases(db, scope)

    assert reminded == 1
    assert workspace.lease_release_reminded_at is not None
```

Then, following that same fixture shape, one test each for:

2. **The reminder quotes the token.** Assert the sent message body contains `"tok-abc"`. The agent cannot derive it, and a reminder it cannot act on is not a mitigation.
3. **Throttled by `github_nudge_grace_seconds`.** A workspace with `lease_release_reminded_at = utcnow()` is not reminded again; one stamped `grace + 60` seconds ago is. Two assertions, two workspaces, one test.
4. **A pending retry changes the wording.** With `item.retry_requested_at` set, the body says the re-dispatch is queued behind this release. Assert on a distinctive substring. §6: under a column rather than a new status **nothing about the item's visible status changes**, so this reminder is the *only* notification the previous owner ever gets that its item was re-pended.
5. **A non-terminal item is not reminded.** `dispatch_status = "dispatched"` holding a lease → 0. Release is illegal there (§3.1c), so a reminder would ask for something the endpoint refuses.
6. **An unleased terminal item is not reminded.** → 0.
7. **The reminder never escalates.** After enough passes to exceed any grace window, `dispatch_status` is still `merged` and `escalation_reason` is still None. This is the trap: `monitor_dispatched`'s two existing timers both escalate on their second pass (`:647`, `:660`), and copying that shape here would escalate items whose work is *finished and merged*.

- [ ] **Step 2: Run and watch them fail**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/agent_teams/test_github_dispatch_service.py -k remind -v`
Expected: FAIL — `AttributeError: ... has no attribute 'remind_held_leases'`

- [ ] **Step 3: Implement**

```python
    async def remind_held_leases(self, db: AsyncSession, scope: TeamGithubScope) -> int:
        """Re-notify owners of terminal items that still hold a workspace lease.

        Never escalates, unlike the two timers in monitor_dispatched. The item's
        work is done — merged, completed, escalated or failed — and escalating
        finished work would be noise. This only asks for the release.

        Clock is lease_release_reminded_at on the WORKSPACE row, not
        item.last_nudge_at: that field already multiplexes the ack and idle
        timers, reset_for_retry does not clear it, and monitor_dispatched reads
        `last_nudge_at is None` to mean 'not yet nudged' before escalating. A
        reminder stamp surviving a retry would escalate leader_ack_timeout
        without the leader ever being nudged. On the workspace row, release()
        clears it for free.
        """
        grace = timedelta(seconds=settings.github_nudge_grace_seconds)
        now = datetime.utcnow()
        held = (
            await db.execute(
                select(GithubWorkspace, GithubWorkItem)
                .join(GithubWorkItem, GithubWorkspace.leased_item_id == GithubWorkItem.id)
                .where(
                    GithubWorkspace.scope_id == scope.id,
                    GithubWorkItem.dispatch_status.in_(_RELEASABLE_STATUSES),
                )
                .order_by(GithubWorkspace.id)
            )
        ).all()
        reminded = 0
        for workspace, item in held:
            if (
                workspace.lease_release_reminded_at is not None
                and now - workspace.lease_release_reminded_at < grace
            ):
                continue
            if item.retry_requested_at is not None:
                urgency = (
                    "\n\n**A re-dispatch of this issue is queued behind this "
                    "release.** It cannot start until you release the workspace."
                )
            else:
                urgency = ""
            await self.notify_owner(
                db,
                item,
                subject=f"Release needed: issue #{item.issue_number}",
                body_markdown=(
                    f"Issue #{item.issue_number} ({item.issue_title}) is "
                    f"`{item.dispatch_status}` but still holds workspace "
                    f"`{workspace.path}`. Commit and push anything you want to "
                    "keep, then release it:\n\n"
                    "```\n"
                    "deck_report_dispatch_status(\n"
                    f"    work_item_id={item.id},\n"
                    '    status="workspace_released",\n'
                    f'    lease_token="{workspace.lease_token}",\n'
                    ")\n"
                    "```"
                    f"{urgency}"
                ),
                payload={
                    "kind": "github_lease_release_reminder",
                    "work_item_id": item.id,
                    "issue_number": item.issue_number,
                    "workspace_path": workspace.path,
                },
            )
            workspace.lease_release_reminded_at = now
            workspace.updated_at = now
            reminded += 1
        if reminded:
            await db.commit()
        return reminded
```

`_RELEASABLE_STATUSES` is already at module scope in this file from Task 6.

- [ ] **Step 4: Call it from `monitor_dispatched`**

At the end of `monitor_dispatched`, immediately before its final `await db.commit()` (`:663`):

```python
        await self.remind_held_leases(db, scope)
```

`monitor_dispatched` selects `dispatch_status == "dispatched"` items only (`:614-621`), so its existing loop can never see a terminal item — the reminder is a separate pass over a disjoint set, not a branch inside that loop.

- [ ] **Step 5: Run everything**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "feat(g2): remind owners holding a lease on terminal work

The backstop bounds only the CRASH case: its conjunction requires the owner
process to be dead, and under one-session-per-slot a standing session that
simply never reports stays alive forever. Nothing bounded the
forgot-to-report hold. This does.

Quotes the lease_token, which the agent cannot derive. When a retry is pending
it says so — under a retry_requested_at column nothing about the item's visible
status changes, so this reminder is the only notification the previous owner
gets that its item was re-pended.

Never escalates, unlike the two timers it sits beside: the work is already
merged or completed. Clocked on the workspace row rather than
item.last_nudge_at, which is already multiplexed and survives reset_for_retry —
a stamp leaking into a retried item would escalate leader_ack_timeout without
the leader ever being nudged."
```

---

### Task 9: Operator visibility and force-release

**Files:**
- Modify: `backend/app/models/schemas.py:2235-2249` (`GithubWorkspaceResponse`)
- Modify: `backend/app/api/v1/agent_teams.py:160-175` (`_workspace_response`), plus a new force-release endpoint
- Test: `backend/tests/agent_teams/` (the workspace API tests)

**Interfaces:**
- Consumes: Tasks 1, 3, 6, 8.
- Produces: `POST /github-scopes/{scope_id}/workspaces/{workspace_id}/force-release`.

Implements spec §6 mitigations 2 and 3, and §9's owed UI surface.

- [ ] **Step 1: Write the failing tests**

Find the existing workspace-endpoint tests (`grep -rln "workspaces" backend/tests/agent_teams/`) and follow their client fixture. Cover:

1. `GET .../workspaces` exposes `lease_token`, `lease_last_owner_contact_at`, `lease_release_reminded_at` and a computed `lease_age_seconds` for a leased workspace, and nulls for an unleased one.
2. Force-release with the **matching** token → 200, lease returned.
3. Force-release with a **stale** token → 409 whose detail shows **both** tokens.
4. Force-release with a **dirty** tree → 200 and the lease still released. This is the deliberate difference from agent-reported release: the operator endpoint exists precisely for the case where the normal path refuses, so a dirty-tree veto here would make it useless. The response must name the discarded paths.
5. Force-release on an **unleased** workspace → 409, not a 500.

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Extend the response schema**

Add to `GithubWorkspaceResponse` (`schemas.py:2235-2249`):

```python
    lease_token: Optional[str] = None
    lease_last_owner_contact_at: Optional[datetime] = None
    lease_release_reminded_at: Optional[datetime] = None
    lease_age_seconds: Optional[int] = None
```

and populate them in `_workspace_response` (`agent_teams.py:160-175`), computing `lease_age_seconds` from `leased_at` when a lease is held and leaving it None otherwise. §6 mitigation 2: a forgotten lease should be *visible*, not inferred from a stalled queue — the Finding 14 lesson.

`lease_token` is exposed deliberately. §6 mitigation 3 needs the operator to have it in hand to pass it back as the compare-and-swap guard. Note this widens who can read a token: §3.1b already records that `/dispatch-status` has no authentication, so a token read here could be replayed there. That is the same pre-existing gap, not a new one, and it is listed below as owed.

- [ ] **Step 4: Add the force-release endpoint**

Model it on `reprobe_github_workspace` (`agent_teams.py:569-607`) — same 404 checks, same `_conflict` helper, same `_workspace_response` return. Take the expected token in the request body.

```python
    if workspace.leased_item_id is None:
        raise _conflict(
            "Workspace is not leased",
            block_code="workspace_not_leased",
        )
    if workspace.lease_token != body.expected_lease_token:
        raise _conflict(
            f"Lease token mismatch: expected {body.expected_lease_token}, "
            f"current {workspace.lease_token}. Refresh and re-check before forcing.",
            block_code="lease_token_mismatch",
        )
```

The compare-and-swap is the point (§6 mitigation 3). An operator clicks from a page rendered some time ago; between render and click the lease may have been released and re-acquired by a **new** owner. A workspace-id-only force-release would then destroy a live lease — the same stale-identity failure as §3.1a, arriving through the operator instead of the agent.

Log who forced it and what was discarded, at `logger.warning`. Do **not** call `reset_workspace` here — release only. The next `acquire` resets, and doing it twice would discard the operator's chance to inspect the tree first.

- [ ] **Step 5: Run the suite**

Run: `python -m pytest tests/agent_teams/ -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "feat(g2): expose lease staleness, add force-release with a CAS guard

Mitigation 2: GET .../workspaces reports the token, owner-contact and
reminder timestamps, and lease age, so a forgotten lease is visible rather than
inferred from a stalled queue.

Mitigation 3: force-release takes the EXPECTED token, not just the workspace
id. An operator acts from a page rendered some time ago; between render and
click the lease may have been released and re-acquired by a new owner, and an
id-only force-release would destroy a live lease — §3.1a's stale-identity
failure arriving through the operator instead of the agent. Mismatch returns
409 showing both tokens.

Unlike agent-reported release this does NOT veto on a dirty tree: the endpoint
exists for the case where the normal path refuses, so vetoing would make it
useless. It names the discarded paths and logs the force."
```

---

### PR1 gate

- [ ] Run `python -m pytest tests/agent_teams/ tests/agent_mail/ -q` — green.
- [ ] `grep -rn "slot_has_live_owner_session\|queued_owner_session_live" backend/ frontend/src` returns nothing.
- [ ] `grep -rn "retry_requested\"" backend/` returns nothing — no new `dispatch_status` value was added.
- [ ] Open **one** PR into `feature/autonomous-github-dispatch`. Do not merge it.
- [ ] In the PR body, list anything you had to adapt (line numbers that moved, a helper that already existed) and anything you could not do as specified.

---

# PR2 — The delivery guarantee

Open only after PR1 is merged. Autonomy stays off throughout.

Read spec §4 in full first. The ordering is not cosmetic: flipping `reuse_existing=True` before PR1's releaser exists creates Finding 19's permanent wedge, measured at `reclaim_stale released: 0`.

---

### Task 10: Keep `slot_prompt_overrides`, flip `reuse_existing`

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:251-261`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py:1256`

Implements spec §4.0 and §2.2.

**The correction that makes this task subtle:** `reuse_existing=True` does not mean "a session will be reused" — it means "reuse one **if a match exists**". With no wakeable session, `plan_launch` still yields `action=spawn`, and `_execute_plan_item` computes `bootstrap_prompt = prompt_override or await self._bootstrap_prompt(...)` (`agent_team_service.py:606-608`). Dropping the override would start a spawned agent with the generic team prompt: no issue number, no worktree path, no reporting instructions, no lease token. All six live slots have `bootstrap_prompt = NULL`, so this is the live behaviour, not a hypothetical.

- [ ] **Step 1: Rewrite the test that encodes Finding 13**

`test_dispatch_proceeds_with_only_standing_session` (`:1256`) asserts a second session **is spawned** when a standing one exists — it encodes the bug as the requirement. Rewrite it to assert the brief *reached* the standing session: a `MailReceipt` exists for the owner member, the launch request carried `reuse_existing=True`, and exactly one session exists for the slot afterwards.

- [ ] **Step 2: Add the spawn-fallback test**

Dispatch to a slot with **no** wakeable session must still spawn with `slot_prompt_overrides` containing the issue number and the leased worktree path. This is the regression §4.0 caught in review, and §7 step 4 walks straight into the path it guards.

- [ ] **Step 3: Run and watch them fail**

- [ ] **Step 4: Flip the flag, keep the override**

```python
                    AgentTeamLaunchRequest(
                        slot_ids=[owner_slot_id],
                        reuse_existing=True,
                        skip_plan_confirmation=True,
                        repo_path_override=workspace.path,
                        slot_prompt_overrides={owner_slot_id: brief},
                    ),
```

One word changes. The override stays: it is *ignored* on the reuse branch (which is Finding 13, and why the mail path exists) and *load-bearing* on the spawn branch. Complementary, not redundant.

- [ ] **Step 5: Run the suite, then commit**

```bash
git add -A backend
git commit -m "feat(g2): dispatch reuses the slot's standing session

reuse_existing=True. The brief already arrives as mail before launcher() is
called — verified on live data, all 14 recent briefs carry a read_at — so the
reuse path does not need prompt delivery.

slot_prompt_overrides is KEPT. reuse_existing=True means 'reuse if a match
exists'; with no wakeable session plan_launch still yields action=spawn, and
that branch uses prompt_override or falls back to the generic three-line team
prompt. All six live slots have bootstrap_prompt=NULL, so dropping the override
would have shipped a spawned agent with no issue number, no worktree path and
no lease token.

Rewrites the canary that asserted a second session is spawned — it encoded
Finding 13 as the requirement."
```

---

### Task 11: A non-throttled wake for dispatch briefs

**Files:**
- Modify: `backend/app/services/agent_mail_service.py:42, 1127-1146`
- Test: `backend/tests/agent_mail/`

Implements spec §4.1.

`AUTO_NUDGE_COOLDOWN_SECONDS = 30` over an in-memory `_last_auto_nudge_at` dict. Under per-item spawn the nudge was decorative — the prompt was passed at spawn. Under one-session-per-slot it is the **only** thing that makes the agent read the brief, so any unrelated message to that member within the prior 30s (an escalation broadcast, a blocker-merged notification) silently drops the brief's wake.

- [ ] **Step 1: Write the failing test** — an unrelated message 5s before dispatch must not suppress the brief's nudge. The existing coverage (`test_send_message_auto_nudge_is_throttled`) tests the throttle as a *feature*, never as a delivery risk; keep it passing.
- [ ] **Step 2: Run and watch it fail.**
- [ ] **Step 3: Add a bypass parameter** to the auto-nudge path so dispatch-brief sends skip the cooldown. Do not remove or weaken the general throttle — it exists to stop nudge storms.
- [ ] **Step 4: Run both tests, then the full suite.**
- [ ] **Step 5: Commit.**

---

### Task 12: Delivery evidence and the `brief_unread` escalation

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:625-663` (the nudge/timer block), `monitor_dispatched`
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

Implements spec §4.1a — all three corrections. Uses Task 1's `brief_delivery_nudge_at` / `_count`.

Three rules, each with a test:

1. **Delivery is proven by the receipt's `read_at` OR any owner status report.** A spawned owner gets the brief as its *prompt* and may work correctly while never opening its mailbox, so `read_at` alone yields a false `brief_unread`. A report is *stronger* evidence than a read receipt — it proves comprehension, not retrieval.
2. **Delivery gets its own columns.** `last_nudge_at` already multiplexes the leader-ack and owner-idle timers (`:645-663`), with the ack branch `continue`-ing before the idle branch. A third tenant would make them interfere: whichever fires first resets the shared clock, and `escalate` then reports whichever branch it happened to be in.
3. **Delivery is evaluated BEFORE ack.** `leader_ack_timeout` currently masks `brief_unread` permanently — the ack branch escalates first and `escalate` is terminal, so an undelivered brief is misdiagnosed as *the leader failing to ack*. That is the Finding 14 misattribution cost, exactly.

The ack clock keeps its `dispatched_at` anchor. Gating it on delivery evidence was **declined twice**: it converts a loud, already-implemented failure into silence.

- [ ] **Step 1: Write the failing tests** — the four from spec §5.2: delivery proven by report not only receipt; `brief_unread` not masked by `leader_ack_timeout` (fixture where both are overdue → reason must be `brief_unread`); delivery counters independent of the ack nudge in both directions; no receipt and no report past the bounded retries → `brief_unread`.
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement**, with `brief_unread` as a new **escalation reason** (not a new `dispatch_status`).
- [ ] **Step 4: Run the suite.**
- [ ] **Step 5: Commit.**

---

### Task 13: Refuse an ambiguous slot before acquiring

**Files:**
- Modify: `backend/app/services/github_dispatch_service.py:198-222` (before `acquire`)
- Test: `backend/tests/agent_teams/test_github_dispatch_service.py`

Implements spec §4.2.

`_nudge_session_for_member` orders by `last_seen_at desc` and takes the first nudgeable session (`:1081-1085`). Slot 6 currently carries three sessions under one `member_id`, all stamped within microseconds by `sync_observed_sessions` one line earlier — so which pane receives the prompt is a coin flip today.

- [ ] **Step 1: Write the failing tests** — both from spec §5.2:
  - A second pane present **in discovery but not in the DB** must still block dispatch. This proves the check re-synced rather than trusting stale rows.
  - Discovery returning nothing for a slot mail believes is populated → held, not dispatched.
- [ ] **Step 2: Run and watch them fail.**
- [ ] **Step 3: Implement.** Count the owner slot's *nudgeable* sessions (`_session_can_nudge`, `agent_mail_service.py:595`). More than one → do not dispatch; set `pending_reason = "queued_ambiguous_sessions"` and a `status_note` naming the competing tmux targets.

  Two constraints:
  - It runs **before** `acquire`, so an ambiguous slot never leases a workspace it cannot be briefed about.
  - It **calls `sync_observed_sessions` itself, immediately before counting, and fails closed.** `dispatch_pending` never calls it — so the check would otherwise count rows last refreshed whenever a human opened the Agent Mail page, while the live nudge goes through `auto_nudge_members`, which *does* sync first (`:1131`). The stale check would pass and the delivery would coin-flip: Finding 17 rebuilt. And because `sync_observed_sessions` swallows discovery failures with an early return (`:354-356`), "the sync did not raise" is not evidence that discovery worked — zero observed sessions for a slot mail believes is populated means **hold**, not dispatch.

  This is the concrete instance of the memory rule: for any predicate gating a destructive or irreversible action, at least one writer of its input must run on the same schedule as the consumer. Here the consumer is dispatch, so dispatch does the writing.
- [ ] **Step 4: Run the suite.**
- [ ] **Step 5: Commit.**

---

### PR2 gate

- [ ] Full suite green: `python -m pytest tests/agent_teams/ tests/agent_mail/ -q`
- [ ] One PR into `feature/autonomous-github-dispatch`. Do not merge.
- [ ] Report anything adapted or omitted.

---

## Owed alongside, not inside, these PRs

These are recorded in spec §9 and must **not** be folded into PR1 or PR2:

- **`CLAUDE.md` is wrong about migrations.** It says "No database migration system — schema changes require deleting the db"; the ladder has existed at `app/database.py:290` for some time. Separate `docs:` commit — it misleads every reader of the repo, not just this design.
- **PR A's §2.9/§2.10b** describe a force-release endpoint as "deliberately not built" and the liveness gate as "the single arbiter of release". G2 §6 reverses both. Already amended in the spec docs; no code owed.
- **`/dispatch-status` has no authentication** (§3.1b). Owner-only release is *cooperative* validation — the MCP shim derives `reporting_slot_id` from the caller's registration, but a direct HTTP caller can pass any slot id. Endpoint-wide auth is owed **before autonomy runs against anything but a trusted local team**, and is out of scope here because fixing one branch would imply the other eight are protected.
- **§6's three mitigations are Tasks 8 and 9 — they are in PR1, not owed.** What remains owed is the *frontend* surface: nothing in `frontend/src` currently reads `lease_state`, `leased_at` or the reprobe endpoint (verified by grep), so the whole workspace-lease UI is unbuilt. Task 9 makes the API expose lease age, reminder state and the token; the React page that shows them is a separate frontend change and is out of scope for both PRs.
- **A pre-existing failure** at `tests/test_multi_provider_smoke.py:54` (stale monkeypatch on `agent_bridge_api.discover_agent_sessions`) needs its own issue.

## Deployment (operator, not implementer)

Spec §7 owns this. The implementer does **not** deploy, restart the backend, converge slot 6, or re-enable autonomy. Item 23 stays escalated and must not be retried.
