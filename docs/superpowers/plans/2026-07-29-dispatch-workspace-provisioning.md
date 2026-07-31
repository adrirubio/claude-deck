# Implementation plan — dispatch workspace provisioning (Finding 16, Steps 1+2+3a)

Design: `../specs/2026-07-29-dispatch-workspace-provisioning-design.md` — **read it first**, especially §2.5 (reclaim) and §2.6 (`clean -fd`, not `-fdx`). Those two are where this task can do real damage.

Scope: backend service + schema + two endpoints + four small frontend edits. Tasks 1-4 are the substance; Task 5 is surface area.

Work TDD: write the failing test, run it, confirm it fails for the *expected reason*, then implement.

**New sub-branch off `feature/autonomous-github-dispatch`: `feature/autonomous-github-dispatch-workspaces`.** ONE PR back into `feature/autonomous-github-dispatch`. Do not merge it yourself.

Baseline before you start:

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
# expect: 290 passed (or 294 if the G1c PR merged first — report which you saw)
```

Files that change:

| File | Change |
|---|---|
| `app/models/database.py` | new `GithubWorkspace`; 5 new `TeamGithubScope` columns |
| `app/database.py` | compat-migration ladder entries for the 5 scope columns |
| `app/services/github_workspace_service.py` | **new** |
| `app/services/github_dispatch_service.py` | gate 6, brief rewrite, release on `ValueError` |
| `app/services/github_verification_service.py` | release in `_mark_merged` |
| `app/services/github_watcher_service.py` | release in `_complete_and_notify` |
| `app/models/schemas.py` | 5 scope fields; 3 workspace models; `workspace_path` on the work-item response |
| `app/api/v1/agent_teams.py` | scope fields; 2 workspace endpoints; `workspace_path` on the work-items query |
| `frontend/src/features/agent-teams/AutonomyPanel.tsx` | 3 pending reasons, 1 `<dl>` row, 1 label fix |
| `frontend/src/types/agentTeams.ts` | `workspace_path` on `GithubWorkItem` |
| `tests/agent_teams/*` | per the design's §6 |

---

## Task 1 — schema

**File:** `app/models/database.py`

Add `GithubWorkspace` exactly as written in design §2.2. Place it **after** `GithubWorkItem` (it has an FK to it). Style-match `AgentTeamSlot` (`:137-162`) — `Mapped[...]` annotations, explicit `nullable=`, `datetime.utcnow` defaults.

Both `UniqueConstraint`s are required. `uix_workspace_leased_item` on `leased_item_id` alone is the Finding 10 guard — SQLite allows many NULLs but only one non-NULL per value, which is precisely the invariant wanted. Do not "fix" it into a composite.

Then add five columns to `TeamGithubScope` (`:206-232`), after `max_auto_merges_per_day`:

```python
    base_ref: Mapped[str] = mapped_column(String, default="origin/HEAD", nullable=False)
    builds_out_of_tree: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    build_dir_template: Mapped[str | None] = mapped_column(String, nullable=True)
    build_command_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    max_build_parallelism: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
```

`builds_out_of_tree` defaults **False** and `max_build_parallelism` defaults **4**. Both defaults are deliberate (design §2.8) — do not raise them.

**File:** `app/database.py`

In `_run_sqlite_compat_migrations`, extend the existing `team_github_scopes` block (`:384-397`). Follow the established shape exactly:

```python
    if scope_columns and "base_ref" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN base_ref VARCHAR DEFAULT 'origin/HEAD' NOT NULL")
        )
    if scope_columns and "builds_out_of_tree" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN builds_out_of_tree BOOLEAN DEFAULT 0 NOT NULL")
        )
    if scope_columns and "build_dir_template" not in scope_columns:
        await conn.execute(text("ALTER TABLE team_github_scopes ADD COLUMN build_dir_template VARCHAR"))
    if scope_columns and "build_command_hint" not in scope_columns:
        await conn.execute(text("ALTER TABLE team_github_scopes ADD COLUMN build_command_hint VARCHAR"))
    if scope_columns and "max_build_parallelism" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN max_build_parallelism INTEGER DEFAULT 4 NOT NULL")
        )
```

`github_workspaces` needs **no** ladder entry — `create_all` in `init_db` creates whole tables. Only added columns need the ladder.

Tests: design §6 items 1-4, in `tests/agent_teams/test_github_scope_models.py`. Item 2 and 3 assert `IntegrityError` — the file already imports what you need and has a `db` fixture on `sqlite+aiosqlite:///:memory:`.

Run. Then run the whole suite; nothing should break.

---

## Task 2 — `GithubWorkspaceService`

**New file:** `app/services/github_workspace_service.py`

Module-level singleton at the bottom (`github_workspace_service = GithubWorkspaceService()`), matching every other service in this directory.

### 2a. Git must be injectable

Tests must not shell out to real git. Take the runner as a constructor arg:

```python
class GithubWorkspaceService:
    def __init__(self, runner=None):
        self._runner = runner or self._run_git

    async def _run_git(self, args: list[str]) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await process.communicate()
        return process.returncode, stdout.decode("utf-8", "replace")
```

`asyncio.create_subprocess_exec` — **not** `subprocess.run`. This runs inside the APScheduler event loop; a blocking `git fetch` would stall every other poll. `mcp_service.py:585` is the existing async-subprocess precedent in this codebase.

### 2b. `acquire`

```python
async def acquire(self, db, scope, item) -> GithubWorkspace | None:
```

1. Already-held check first: `select` where `leased_item_id == item.id`. If found, return it (design §2.5, retry keeps its lease). No reset — the agent's work is in there.
2. Otherwise pick the oldest available: `scope_id == scope.id`, `enabled.is_(True)`, `leased_item_id.is_(None)`, `order_by(GithubWorkspace.id)`. `None` → return `None`.
3. Stamp `leased_item_id = item.id`, `leased_at = utcnow()`, `released_at = None`, `updated_at`. Commit.
4. If `kind != "primary"`, call `reset_workspace`. On failure: set `provision_error`, `enabled=False`, release the lease, commit, and **return `None`** — a workspace that failed reset is not usable. Do not raise; `dispatch_pending` treats `None` as "no capacity" and queues the item, which is the correct outcome.

`order_by(id)` gives deterministic assignment — tests can assert *which* workspace was picked, and repeat dispatches favour the same warm workspace.

### 2c. `release`

```python
async def release(self, db, item_id: int) -> None:
```

Clear `leased_item_id`, stamp `released_at` and `updated_at`. Idempotent — no row found is not an error. Called from paths that may run twice.

### 2d. `reclaim_stale` — read design §2.5 before writing this

```python
async def reclaim_stale(self, db, scope) -> int:
```

Join workspaces to their leasing item. For each whose item is `escalated` or `failed`:

```python
from app.services.github_dispatch_service import github_dispatch_service

if item.owner_slot_id is not None and await github_dispatch_service.slot_has_live_owner_session(
    db, item.owner_slot_id
):
    continue          # a live agent may still be writing in there — DO NOT take it
await self.release(db, workspace.leased_item_id)
```

Import inside the function: `github_dispatch_service` imports this module, so a top-level import is circular. The existing code does exactly this dance (`github_dispatch_service.py:438`, `:512`).

`slot_has_live_owner_session` is **read-only here.** Do not modify it, do not "improve" it — Phase G2 owns it.

Return the count released, for logging.

### 2e. `reset_workspace` — the dangerous one

```python
async def reset_workspace(self, db, scope, workspace) -> None:
    if workspace.kind == "primary":
        return                      # NEVER touch the human's checkout
```

That early return is not an optimisation, it is a safety property. Then, in order:

```python
["-C", path, "fetch", "origin", "--prune"]
["-C", path, "switch", "--detach", scope.base_ref]
["-C", path, "reset", "--hard"]
["-C", path, "clean", "-fd"]
```

**`clean -fd`. NEVER `-fdx`.** Meson build directories self-ignore (each holds a `.gitignore` containing `*`), so `-fd` preserves the 1.1 GB build dir and its incremental-build value while `-fdx` would delete it and reintroduce the from-scratch compile that OOM'd this host. If you find yourself typing `-x`, stop and re-read design §2.6.

Non-zero exit from any step → raise; `acquire` catches and records `provision_error`.

### 2f. `provision_worktree`

```python
async def provision_worktree(self, db, scope, path: str) -> GithubWorkspace:
```

`["-C", scope.repo_path, "worktree", "add", "--detach", path, scope.base_ref]`, then insert the row with `kind="worktree"`.

`--detach` is required (design §2.6): git refuses the same branch in two worktrees, and Deck cannot know the agent's branch name. Detached HEAD leaves branch naming to the agent.

For `kind="primary"`, `provision_worktree` is **not** called — the path already exists and is the human's. Register the row and issue no git commands at all (test 26).

This method gets an HTTP caller in Task 5 (design §2.9). It is not dead code and it is not driven from a REPL.

Tests: design §6 items 17-20, in a new `tests/agent_teams/test_github_workspace_service.py`. Inject a fake runner that records `args` lists.

**Item 18 must assert the absence of `-x`**, e.g.:

```python
assert ["-fd"] == [a for call in calls for a in call if a.startswith("-f")]
assert not any("-x" in arg or "-fdx" == arg for call in calls for arg in call)
```

**Item 19 must assert zero git calls** for `kind="primary"` — not "no destructive calls", *zero*.

---

## Task 3 — wire the lease into dispatch

**File:** `app/services/github_dispatch_service.py`

### 3a. Reclaim at the top of `dispatch_pending`

Before `scope_active = await self.scope_active_count(...)` (`:163`):

```python
from app.services.github_workspace_service import github_workspace_service

await github_workspace_service.reclaim_stale(db, scope)
```

Before the capacity read, because `dispatch_pending` is the only consumer of workspace capacity and stale leases would otherwise under-report it.

### 3b. Gate 6

**After** the `slot_has_live_owner_session` check (`:206-212`), immediately before the `try:` at `:213`:

```python
            workspace = await github_workspace_service.acquire(db, scope, item)
            if workspace is None:
                item.owner_slot_id = owner_slot_id
                item.routing_method = method
                item.pending_reason = "queued_no_workspace"
                item.updated_at = datetime.utcnow()
                await db.commit()
                continue
```

Last gate, deliberately (design §2.3): acquiring earlier would burn a workspace on an item that then fails a later gate.

Match the shape of the four gates above it exactly — same field order, same `commit`, same `continue`. `queued_no_workspace` is a `pending_reason`. **It is not a new `dispatch_status`.**

### 3c. Use the workspace path

In the `launcher(...)` call (`:240`):

```python
                        repo_path_override=workspace.path,
```

### 3d. Release on launcher failure

In the `except ValueError:` block (`:244-250`), before `continue`:

```python
                await github_workspace_service.release(db, item.id)
```

The session never started; nothing is in the directory. Holding the lease here would leak it on every routing failure — and `plan_blocked` is currently the most common escalation reason in the live soak (10 of 11 items), so this leak would be immediate and total.

### 3e. `_dispatch_brief` takes a workspace

Change the signature to accept `workspace: GithubWorkspace`, and replace line `:299`:

```python
            f"- Local checkout: {scope.repo_path}",
```

For `kind == "worktree"`:

```python
            f"- Workspace: {workspace.path}",
            "- This workspace is leased exclusively to this work item. No other "
            "dispatched agent will be working in it.",
            f"- It is a git worktree on a detached HEAD at {scope.base_ref}. Create "
            "your own branch with `git switch -c <branch>` before committing.",
            "- Do NOT create, move or remove git worktrees yourself. Claude Deck "
            "provisions the workspace; you work inside the one you were given.",
            "- Do NOT work in any other checkout of this repository.",
```

For `kind == "primary"`, keep lines 1, 2 and 5 and replace 3-4 with:

```python
            "- This is a shared human checkout, not a Deck-managed worktree. Its "
            "current branch is not Deck's to change; confirm with the team leader "
            "before switching branches.",
```

The explicit prohibition is the point. The agents inferred a worktree contract from one hand-made directory and now refuse to work without one (design §1.1). Silence in the brief reads as an invitation to infer.

### 3f. Build hints

Append to the "Code pipeline instructions" block (`:343-357`) when `scope.build_command_hint`:

- if `builds_out_of_tree` and `build_dir_template`: render the template with `issue_number=item.issue_number`, render `build_command_hint` with `build_dir=<rendered>` and `parallelism=scope.max_build_parallelism`, and emit both.
- if not `builds_out_of_tree`: emit the hint with `build_dir=""` plus "Only one build may run in this workspace at a time; this project's build system does not support out-of-tree builds."

Always emit, whenever `max_build_parallelism` is set:

```python
                    f"- Cap build parallelism at -j{scope.max_build_parallelism}. "
                    "Higher values have OOM-killed this host.",
```

That last line is the highest-value sentence in the brief. `ninja` defaults to `-j18` here and `cc1plus` peaks near 1 GB — one unconstrained build can exhaust 15.6 GB by itself.

Use `str.format` with explicit kwargs, and catch `KeyError`/`IndexError` around it: these templates are operator-supplied and a bad one must not take down the poll loop. On failure, log and omit the build lines.

Tests: design §6 items 5-11, 21-22.

---

## Task 4 — release on the terminal paths

Two one-line additions. Both need a function-local import to avoid a cycle.

**`app/services/github_verification_service.py`** — `_mark_merged` (`:413`) is sync; make it async or release at its call sites. Prefer making it async and awaiting — there are few callers and an async release keeps the release adjacent to the state change it belongs to.

**`app/services/github_watcher_service.py`** — `_complete_and_notify`, after `item.dispatch_status = "completed"` (`:152`).

**Do NOT add a release to:**

- `reset_for_retry` (`github_dispatch_service.py:30-41`) — retry keeps its lease so the build dir stays warm.
- `escalate` / `_apply_escalation` — escalation does not mean the agent stopped. `_send_escalation_broadcast` already warns the team that the owner may still be working. Releasing here recreates Finding 10.
- `_record_failed_verification_attempt` — it sends the item back to `dispatched` for a fix.
- `_fallback_to_human_merge` — reviewers may request changes.

Tests: design §6 items 12-16. **Item 13** (live session → NOT reclaimed) is the Finding 10 regression guard; it must fail if reclaim is unconditional. Write it before the reclaim implementation and watch it fail.

---

## Task 5 — API and schemas

### 5a. Scope fields

**`app/models/schemas.py`** (`:2154-2199`) — add all five fields to `TeamGithubScopeCreate` (with the design's defaults), `TeamGithubScopeUpdate` (`Optional`, default `None`), and `TeamGithubScopeResponse`. Use `Field(default=4, ge=1)` for `max_build_parallelism`; `ge=1` matters, `-j0` is meaningless.

**`app/api/v1/agent_teams.py`** — five `if request.X is not None:` lines in `_apply_scope_create` (after `:151`), five kwargs in `_scope_response` (after `:85`). Match the surrounding style exactly.

### 5b. Two workspace endpoints — read design §2.9 first

An earlier draft of this plan said "no new endpoints." That was copy-forwarded boilerplate from two earlier plans where it was actually derived, and it is wrong here: without an endpoint, `provision_worktree` has no caller and workspace registration can only happen by hand-editing the live database, which is forbidden. §2.9 has the full reasoning.

**`app/models/schemas.py`** — three new models beside the scope ones:

```python
class GithubWorkspaceCreate(BaseModel):
    path: str
    kind: str = "worktree"
    enabled: bool = True


class GithubWorkspaceResponse(BaseModel):
    id: int
    scope_id: int
    path: str
    kind: str
    lease_state: str
    leased_item_id: Optional[int] = None
    leased_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    provision_error: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class GithubWorkspaceListResponse(BaseModel):
    workspaces: List[GithubWorkspaceResponse] = Field(default_factory=list)
```

`lease_state` is **derived in the response builder**, never stored (design §2.2 — state that cannot contradict itself):

```python
def _workspace_lease_state(workspace: GithubWorkspace) -> str:
    if workspace.leased_item_id is not None:
        return "leased"
    if not workspace.enabled:
        return "disabled"
    return "available"
```

Order matters: a leased workspace that was then disabled reports `leased`, because something may still be writing in it. Add a `_workspace_response(workspace)` helper next to `_scope_response` (`:72`).

**`app/api/v1/agent_teams.py`** — two routes, placed after `delete_github_scope` (`:367`) to keep the scope-scoped routes together:

```python
@router.get(
    "/github-scopes/{scope_id}/workspaces",
    response_model=GithubWorkspaceListResponse,
)
async def list_github_workspaces(scope_id: int, db: AsyncSession = Depends(get_db)):
```

404 if the scope is missing — follow the `delete_github_scope` idiom, which does `db.get` then raises. Order by `GithubWorkspace.id` to match `acquire`'s ordering, so the list reads in the order workspaces will be handed out.

```python
@router.post(
    "/github-scopes/{scope_id}/workspaces",
    response_model=GithubWorkspaceResponse,
    status_code=201,
)
async def create_github_workspace(
    scope_id: int,
    request: GithubWorkspaceCreate,
    db: AsyncSession = Depends(get_db),
):
```

Behaviour, in order:

1. `db.get(TeamGithubScope, scope_id)`; `None` → 404.
2. Validate `kind` in `{"primary", "worktree"}` → 400 otherwise. Do not accept arbitrary strings; `reset_workspace`'s safety property is a `kind == "primary"` comparison, and a typo'd `"Primary"` would make it reset the human's checkout.
3. Normalise `path` with `agent_team_service.normalize_repo_path` — the same call `_apply_scope_create` uses for `repo_path` (`:135-137`). Registering `~/foo` and `/home/juan/foo` as two pool members must be impossible.
4. `kind == "worktree"` → `await github_workspace_service.provision_worktree(db, scope, path)`. `kind == "primary"` → insert the row directly, **zero git commands**.
5. `IntegrityError` → 409 `"Workspace already registered for this scope"`, mirroring `create_github_scope` (`:337-339`). Without this the duplicate-path `UniqueConstraint` surfaces as a 500.

**No `DELETE`.** Design §5 forbids Deck removing worktrees, and a delete whose lease check was wrong would pull the directory out from under a running agent.

Tests: design §6 items 23-28.

### 5c. `workspace_path` on the work-item response

**`app/models/schemas.py`** — add to `GithubWorkItemResponse` (`:2209-2234`):

```python
    workspace_path: Optional[str] = None
```

**`app/api/v1/agent_teams.py`** — `_work_item_response` (`:93`) takes `(item, scope)` and so cannot reach the workspace table. Add a third optional parameter rather than a relationship:

```python
def _work_item_response(
    item: GithubWorkItem,
    scope: TeamGithubScope,
    workspace_path: str | None = None,
) -> GithubWorkItemResponse:
```

Default `None` keeps `retry_github_work_item` (`:435`) and any other caller working unchanged.

In `list_github_work_items` (`:378-402`), extend the existing join. Note this codebase declares **no ORM `relationship()` anywhere** — every join is explicit in the query — so use an outer join, not `selectinload`:

```python
        select(GithubWorkItem, TeamGithubScope, GithubWorkspace.path)
        .join(TeamGithubScope, TeamGithubScope.id == GithubWorkItem.scope_id)
        .outerjoin(GithubWorkspace, GithubWorkspace.leased_item_id == GithubWorkItem.id)
```

**`outerjoin`, not `join`.** An inner join would silently drop every item without a lease — which is every `pending` item, i.e. most of the list. If the work-items table suddenly shows only 1-2 rows, this is why.

The join cannot multiply rows: `UniqueConstraint("leased_item_id")` from Task 1 means at most one workspace references any item. The schema constraint that guards Finding 10 is the same one that keeps this query honest — worth noting in the PR, because an outer join into a lease table normally *would* need a `DISTINCT` and a reviewer will look for one.

Test: design §6 item 29.

### 5d. Frontend — bounded (design §2.10)

The earlier "do not touch the frontend" is withdrawn. Three changes, no more:

**`frontend/src/features/agent-teams/AutonomyPanel.tsx`** — `pendingReasonLabel` (`:85-91`) currently handles 2 of 4 reasons and returns `null` otherwise, so a queued workspace shortage renders as blank space. Add the new reason and the two that already render blank:

```typescript
  if (item.pending_reason === 'queued_no_workspace') return 'queued · no free workspace'
  if (item.pending_reason === 'queued_low_memory') return 'queued · low memory'
  if (item.pending_reason === 'queued_owner_session_live') {
    return `queued · ${ownerName ?? 'owner'} session still live`
  }
```

Leave the fallthrough as `null`: `retry_github_work_item` writes free prose into `pending_reason` (`"retry requested: ..."`, `agent_teams.py:431`), and that must not be rendered as a queue reason.

**Same file** — one row in the detail `<dl>` (`:369-388`), matching the existing `grid-cols-[150px_1fr]` shape, before the PR row:

```tsx
                  <div className="grid grid-cols-[150px_1fr] border-b p-3">
                    <dt className="text-muted-foreground">Workspace</dt>
                    <dd className="truncate">{item.workspace_path ?? 'None leased'}</dd>
                  </div>
```

**Same file** — the scope card at `:548-550` reads `Local checkout: {scope.repo_path}`, which is the exact wording design §2.7 identifies as misleading. Change the label to `Worktree parent: {scope.repo_path}`.

**`frontend/src/types/agentTeams.ts`** — add `workspace_path?: string | null` to `GithubWorkItem` (`:211-222`). Nothing else; the five scope fields stay out (design §5).

**Not in this task:** the pool summary on the scope card (`Workspaces: 1/2 leased`). It needs a second fetch and its own loading/error state in a component that currently fetches scopes and items only. Design §2.10 lists it as worth doing; it is a follow-up, and `GET .../workspaces` plus `curl` covers deployment.

Run `cd frontend && npm run lint` — TypeScript strict mode with `noUnusedLocals` will fail the build on a stray import.

---

## Task 6 — verify and open the PR

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
pytest tests/ -q            # full suite; report any pre-existing failure, do not fix it
cd ../frontend && npm run lint && npx tsc --noEmit
```

Expected: baseline + ~29 new tests. Report the actual number.

Sanity checks — all five must hold:

```bash
grep -rn "fdx\|'-x'\|\"-x\"" app/services/github_workspace_service.py    # must be EMPTY
grep -n "repo_path_override" app/services/github_dispatch_service.py     # must show workspace.path, NOT scope.repo_path
git diff --stat app/services/github_client.py app/services/github_watcher_service.py
# github_client.py: EMPTY. github_watcher_service.py: the ONE release line only.
grep -n "outerjoin" app/api/v1/agent_teams.py        # must exist in list_github_work_items
grep -n "router.delete" app/api/v1/agent_teams.py    # must NOT mention workspaces
```

The `outerjoin` check is not pedantry: an inner join there drops every unleased item from the work-items list, which is most of them, and the UI would look empty rather than broken.

Open ONE PR into `feature/autonomous-github-dispatch` describing:

- the phantom-contract diagnosis, and that the brief now states the contract explicitly including the prohibitions;
- the lease invariant and that `UniqueConstraint("leased_item_id")` enforces it in the schema rather than in query logic (the Finding 10 lesson);
- the reclaim rule, and **why escalation alone does not release** — cite the live-session check;
- `clean -fd` vs `-fdx` and the 1.1 GB build dir;
- that the primary checkout is never reset;
- `builds_out_of_tree=False` / `max_build_parallelism=4` as deliberately conservative defaults;
- that 3b (host-wide build semaphore) is **not** in this PR and is a documented prerequisite for a second scope (design §3.2);
- the two new endpoints and why registration needs one — a service method with no caller would force hand-edited DB rows (design §2.9);
- that there is deliberately **no `DELETE`**;
- the three bounded frontend changes, and that `queued_no_workspace` rendering as blank space would have made a correctly-working pool look like the Finding 14 wedge;
- the final test count and the five sanity checks above.

Then STOP and report. Do not merge. Do not restart the backend. Do not register workspaces or edit any DB row — the orchestrator does that on the live soak after merge, through the endpoint you just built.

---

## Hard constraints

- Work **only** in `/home/juan/work/repos/juanrubio/claude-deck-g1`. Never touch `/home/juan/work/repos/juanrubio/claude-deck` (live soak, live DB) or `/home/juan/work/repos/tizonia/` (5 live agent sessions hold it as cwd).
- ONE PR into `feature/autonomous-github-dispatch`. Never merge, self-merge, or merge to master.
- NO new `dispatch_status` values. `queued_no_workspace` is a `pending_reason`.
- Do not touch `slot_has_live_owner_session`, `reuse_existing`, or the launch path beyond the single `repo_path_override` argument (Phase G2 owns those).
- Do not touch `github_client.py`, `_reconcile_closed_issues`, `escalate`, `_apply_escalation`, or any status constant.
- No new dependencies.
- **Exactly two new endpoints** — `GET` and `POST` on `/github-scopes/{scope_id}/workspaces` (Task 5b). No `DELETE`, no `PATCH`, no workspace routes anywhere else. (An earlier draft said "no new endpoints"; that was withdrawn for the reason in design §2.9. It does not license further endpoints.)
- **Frontend changes are limited to Task 5d's four edits.** No new components, no new pages, no scope-form fields.
- Do not enable/disable autonomy, spawn or kill agent sessions, hand-edit DB rows, or restart the backend.
- Report — do not rewrite — any pre-existing failing test.
- **If a step looks wrong, STOP and report rather than improvising.** Two places in particular: if `clean -fd` seems insufficient, or if reclaiming unconditionally on escalation seems simpler. Both are traps with a soak finding behind them.
