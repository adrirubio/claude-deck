# Implementation plan — dispatch workspace provisioning (Finding 16, **PR A**)

Design: `../specs/2026-07-29-dispatch-workspace-provisioning-design.md` — **read it first**, especially §2.4 (why nothing releases on terminal status), §2.5 (reclaim) and §2.6 (`clean -fd`, not `-fdx`, and the forced switch). Those three are where this task can do real damage.

**This is the fifth version, and it has been through three reviews plus one design pass.** The first judged it unsafe (`/tmp/dispatch-workspace-provisioning-plan-review.md`, 11 findings); the second judged the lease design "sound enough to implement" with 4 findings + a contract clarification (`/tmp/dispatch-workspace-provisioning-plan-rereview.md`); the third found 2 further safety blockers, 3 contract inconsistencies and 1 stale instruction (`/tmp/dispatch-workspace-provisioning-plan-rereview-2.md`). Every finding from all three is adopted or explicitly deferred. The fifth version then added machine-readable rejection codes (Task 5b-v), because all three reviews and the plan itself had read "operator" as "human" throughout, while Deck's Agent Team surface is already driven by agents. Four things follow:

- **Where this plan and any review disagree, this plan wins** — it was written after all three, and each finding was verified against the code before being adopted (see the three "what changed" tables at the end). In four places a review's own proposed fix was incomplete or unsafe, and the plan says which and why.
- First-review finding 6 ("no supported way to populate the pool") was already fixed before that review, in a commit that had not been pushed. That is why the first reviewed copy still said "no new endpoints."
- The endpoint count went "none" → two → **four**. Each addition is derived from a traced deadlock, not from convenience; Task 5b shows the traces.
- **Three of the third review's six findings are the same mistake in different clothes:** a check that proves a path *belongs* to the repo, used as if it proved *what the path is*. Registration therefore validates `kind` in both directions (Task 2f). If you find yourself writing a validator that answers "is this in the repo?", ask what it is being trusted to answer.
- **"The operator" in this plan means a human *or* an agent.** Deck already exposes 18 `deck_*` MCP tools and its Agent Team surface is routinely driven by agents, so every rejection these endpoints emit carries a machine-readable `block_code` (Task 5b-v). Reasoning that ends "the operator will see the error and retry" is only valid for one of the two.

Scope: backend service + schema + four endpoints + four small frontend edits. Tasks 1-3 are the substance; Task 4 is a **deliberate non-change** and must be read, not skipped; Task 5 is surface area.

**This is a staging PR.** Autonomy stays off when it merges, until PR B lands (design §4.1a). Every mechanism that frees a workspace in PR A needs either an offline session or an operator, and a size-1 dispatchable pool can stall indefinitely on that. Nothing in this PR should be written as if it were ready for unattended dispatch.

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
| `app/services/github_dispatch_service.py` | gate 6, brief rewrite, release on **every** launch-failure shape |
| `app/models/schemas.py` | 5 scope fields; 3 workspace models; `GithubWorkItemAbandonRequest`; `workspace_path` on the work-item response |
| `app/api/v1/agent_teams.py` | scope fields; 3 workspace endpoints + 1 work-item endpoint; `workspace_path` on the work-items query |
| `frontend/src/features/agent-teams/AutonomyPanel.tsx` | 3 pending reasons, 1 `<dl>` row, 1 label fix |
| `frontend/src/types/agentTeams.ts` | `workspace_path` on `GithubWorkItem` |
| `tests/agent_teams/*` | per the design's §6 |

`github_verification_service.py` and `github_watcher_service.py` are **not** in that table, and their absence is the single biggest change from the reviewed draft. See Task 4.

---

## Task 1 — schema

**File:** `app/models/database.py`

Add `GithubWorkspace` exactly as written in design §2.2. Place it **after** `GithubWorkItem` (it has an FK to it). Style-match `AgentTeamSlot` (`:137-162`) — `Mapped[...]` annotations, explicit `nullable=`, `datetime.utcnow` defaults.

Three details in that model are load-bearing and each has a finding behind it:

- **`UniqueConstraint("leased_item_id")`** — the Finding 10 guard. SQLite allows many NULLs in a unique index but only one non-NULL per value, which is exactly the one-item-one-workspace invariant. Do not "fix" it into a composite.
- **`UniqueConstraint("path")` is global, not `(scope_id, path)`.** A lease is an exclusivity claim on a *physical directory*, so the constraint must be at the granularity of the directory. Per-scope uniqueness would let scope A and scope B each register `/home/juan/work/repos/tizonia/tizonia-openmax-il-ws1` and each `reset --hard` it out from under the other.
- **`dispatchable: Mapped[bool]`**, defaulting `True` in the column but set `False` for `kind="primary"` at registration (Task 5b). Without it, `acquire`'s `order_by(id)` hands the *first-registered* workspace to the first item — and deployment registers the primary first, so the very first autonomous dispatch would land in the human's shared checkout. That is the exact outcome this design exists to prevent, reintroduced by the ordering rule.

`dispatchable` is deliberately **separate from `enabled`**: `enabled=False` means "broken, do not use", `dispatchable=False` means "healthy, deliberately not for autonomous work". Collapsing them makes a reserved primary indistinguishable from a workspace whose `fetch` failed.

Then add five columns to `TeamGithubScope` (`:206-232`), after `max_auto_merges_per_day`:

```python
    base_ref: Mapped[str] = mapped_column(String, default="origin/HEAD", nullable=False)
    builds_out_of_tree: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    build_dir_template: Mapped[str | None] = mapped_column(String, default="build", nullable=True)
    build_command_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    max_build_parallelism: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
```

`builds_out_of_tree` defaults **False** and `max_build_parallelism` defaults **4**. Both defaults are deliberate (design §2.8) — do not raise them.

`build_dir_template` defaults to the constant `"build"`, **not** `"build-issue-{issue_number}"`. Design §2.1 has the measurement: `git clean -fd` preserves ignored directories on purpose, so a per-issue template deposits another ~1.1 GB inside a fixed workspace on every issue and nothing ever collects it. Per-issue templating remains *possible* for repos that need it; it is not the default and the live scope will not use it.

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
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN build_dir_template VARCHAR DEFAULT 'build'")
        )
    if scope_columns and "build_command_hint" not in scope_columns:
        await conn.execute(text("ALTER TABLE team_github_scopes ADD COLUMN build_command_hint VARCHAR"))
    if scope_columns and "max_build_parallelism" not in scope_columns:
        await conn.execute(
            text("ALTER TABLE team_github_scopes ADD COLUMN max_build_parallelism INTEGER DEFAULT 4 NOT NULL")
        )
```

`github_workspaces` needs **no** ladder entry — `create_all` in `init_db` creates whole tables. Only added columns need the ladder.

Tests: design §6 items **1-5**, in `tests/agent_teams/test_github_scope_models.py`. Items 2 and 3 assert `IntegrityError` — the file already imports what you need and has a `db` fixture on `sqlite+aiosqlite:///:memory:`.

Item 3 must register the duplicate path under **two different scopes**. A same-scope duplicate test would pass against the wrong (composite) constraint and prove nothing.

Item 5 is the one that is easy to skip and shouldn't be: extend the **existing** `test_compat_migration_adds_new_columns_to_legacy_db` (`test_github_scope_models.py:100-139`) to cover all five new columns. Item 4 asserts ORM defaults on a fresh `create_all` database, which does not exercise the `ALTER TABLE` ladder at all — and the ladder is the code path that will run against the live soak DB. The test already exists and already builds a legacy table; you are adding assertions to it, not writing a new harness.

Run. Then run the whole suite; nothing should break.

---

## Task 2 — `GithubWorkspaceService`

**New file:** `app/services/github_workspace_service.py`

Module-level singleton at the bottom (`github_workspace_service = GithubWorkspaceService()`), matching every other service in this directory.

### 2a. Git must be injectable

Tests must not shell out to real git. Take the runner as a constructor arg:

```python
GIT_TIMEOUT_SECONDS = 300

_GIT_ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class GithubWorkspaceService:
    def __init__(self, runner=None):
        self._runner = runner or self._run_git

    async def _run_git(self, args: list[str]) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_GIT_ENV,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(), timeout=GIT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return 124, f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s"
        return process.returncode, stdout.decode("utf-8", "replace")
```

`asyncio.create_subprocess_exec` — **not** `subprocess.run`. This runs inside the APScheduler event loop; a blocking `git fetch` would stall every other poll. `mcp_service.py:585` is the existing async-subprocess precedent in this codebase.

The timeout and the env are **not** boilerplate; both are review findings. `git fetch` against an unreachable host blocks indefinitely, and without `GIT_TERMINAL_PROMPT=0` a credential prompt makes the subprocess wait forever for input that will never arrive — indistinguishable from a hang, inside the scheduler loop. Kill on timeout and `await process.wait()`, or the child is left orphaned.

### 2b. `acquire`

```python
async def acquire(self, db, scope, item) -> GithubWorkspace | None:
```

1. Already-held check first: `select` where `leased_item_id == item.id`. If found, return it (design §2.5, retry keeps its lease). No reset — the agent's work is in there.
2. Otherwise pick the oldest available: `scope_id == scope.id`, `enabled.is_(True)`, **`dispatchable.is_(True)`**, `leased_item_id.is_(None)`, `order_by(GithubWorkspace.id)`. `None` → return `None`.
3. Stamp `leased_item_id = item.id`, `leased_at = utcnow()`, `released_at = None`, `updated_at`. Commit.
4. If `kind != "primary"`, call `reset_workspace`. Failure handling depends on **which** git step failed — see 2e; a `fetch` failure must not disable the workspace. In both failure cases release the lease, commit, and **return `None`** — a workspace that failed reset is not usable this poll. Do not raise; `dispatch_pending` treats `None` as "no capacity" and queues the item, which is the correct outcome.
5. On success, clear any previous `provision_error` so a recovered workspace heals itself without operator action.

**The `dispatchable.is_(True)` filter in step 2 is the finding-1 fix and it is one clause.** Omitting it means the primary — registered first, lowest `id` — wins the first dispatch and an autonomous agent starts editing the human's checkout on a branch they are using. Write design §6 item 10 first and watch it fail: a `dispatchable=False` primary at `id=1` and an available worktree at `id=2` must yield the worktree.

`order_by(id)` gives deterministic assignment — tests can assert *which* workspace was picked, and repeat dispatches favour the same warm workspace.

Tests for `acquire`: design §6 items **6-11**.

### 2c. `release`

```python
async def release(self, db, item_id: int) -> None:
```

Clear `leased_item_id`, stamp `released_at` and `updated_at`. Idempotent — no row found is not an error. Called from paths that may run twice.

### 2d. `reclaim_stale` — read design §2.5 before writing this

```python
async def reclaim_stale(self, db, scope) -> int:
```

Join workspaces to their leasing item. For each whose item is in a **non-working** status — `escalated`, `failed`, `merged`, `completed`:

```python
from app.services.github_dispatch_service import github_dispatch_service

if item.owner_slot_id is not None and await github_dispatch_service.slot_has_live_owner_session(
    db, item.owner_slot_id
):
    continue          # a live agent may still be writing in there — DO NOT take it
await self.release(db, workspace.leased_item_id)
```

Import inside the function: `github_dispatch_service` imports this module, so a top-level import is circular. The existing code does exactly this dance (`github_dispatch_service.py:438`, `:512`).

`merged` and `completed` are in that list because **nothing else releases them** — this PR adds no terminal release at all (Task 4). The reclaim sweep is the only releaser in PR A, so its status list has to cover every non-working status or those leases are permanent.

Never reclaim `dispatched`, `verifying`, `ready_for_review` or `awaiting_human_review`. In all four an agent is legitimately still expected to be working: `_record_failed_verification_attempt` sends `verifying` back to `dispatched` for a fix, and `record_approval_round` exists precisely because reviewers request changes.

`slot_has_live_owner_session` is **read-only here.** Do not modify it, do not "improve" it — Phase G2 owns it. It is keyed on `slot_id` rather than on the item's own launch, so an unrelated live session on the same slot holds a lease longer than strictly necessary. That imprecision is **known and accepted**: it errs toward retention, and retention is the safe direction. Per-item liveness is PR B.

Return the count released, for logging.

Tests: design §6 items **18-23**. Items 18/19 are the pair that matters — same non-working status, live session versus dead session, opposite outcomes.

### 2e. `reset_workspace` — the dangerous one

```python
async def reset_workspace(self, db, scope, workspace) -> None:
    if workspace.kind == "primary":
        return                      # NEVER touch the human's checkout
```

That early return is not an optimisation, it is a safety property. Then, in order:

```python
["-C", path, "fetch", "origin", "--prune"]
["-C", path, "switch", "--detach", "--force", scope.base_ref]
["-C", path, "reset", "--hard", scope.base_ref]
["-C", path, "clean", "-fd"]
```

**`--force` on the switch is required, and the earlier draft of this plan omitted it.** Verified empirically against a scratch repo:

```
$ git switch --detach origin/main          # one dirty tracked file present
error: Your local changes to the following files would be overwritten by checkout:
        f.txt
Aborting                                    # exit 1
```

Step 2 fails, so step 3 never runs, so the tree is handed over still dirty — or, with this plan's error handling, the workspace is disabled. And a `failed`/`escalated` item is *precisely* the case most likely to have left tracked modifications behind, so the sequence broke exactly where reclaim needs it to work. Re-verified with `--force`: the switch succeeds, the tree lands clean at the base ref, and a self-ignoring `build/` directory survives.

`reset --hard <base_ref>` names the ref rather than relying on bare `reset --hard`, so the post-condition is explicit rather than positional.

**`clean -fd`. NEVER `-fdx`.** Meson build directories self-ignore (each holds a `.gitignore` containing `*`, which is why `git check-ignore -v build/` reports `build/.gitignore:2:*`), so `-fd` preserves the 1.1 GB build dir and its incremental-build value while `-fdx` would delete it and reintroduce the from-scratch compile that OOM'd this host. 90 seconds versus 40 minutes. If you find yourself typing `-x`, stop and re-read design §2.6.

**Failure handling distinguishes transient from local, and this is review finding 7:**

| Failing step | Meaning | `enabled` | `provision_error` |
|---|---|---|---|
| `fetch` | transient — network, DNS, auth, GitHub outage | **stays `True`** | recorded |
| `switch` / `reset` / `clean` | the working tree is broken | set `False` | recorded |

Disabling on *any* failure — which the earlier draft did — converts a network blip into a permanent wedge: reset runs on acquire, acquire walks the pool oldest-first, so one blip disables one workspace per poll until the pool is empty, and nothing clears `provision_error` or re-enables a row. The cure was worse than the disease. Signal the distinction to the caller however you prefer (two exception types, or a returned outcome) — but `acquire` must be able to tell them apart, and both paths return `None` so the item queues as `queued_no_workspace` and retries next poll.

A successful reset clears `provision_error` (2b step 5). Recovery must not need an operator.

### 2f. `register_workspace` — provision, adopt, or register the primary

**Renamed, and it takes `kind`.** Third-review finding 3: the previous signature had no `kind` parameter while Task 5b called it for both kinds and said "the method decides" — which it could not do, since the one input it needed was the one not passed. Renaming rather than bolting `kind` onto `provision_worktree` is the honest fix: two of the three paths provision nothing, and a method named `provision_*` that sometimes runs no mutating git command at all is a name that will mislead the next reader exactly the way this one misled the plan.

```python
async def register_workspace(
    self,
    db,
    scope,
    path: str,
    *,
    kind: str = "worktree",
    dispatchable: bool = True,
    enabled: bool = True,
) -> GithubWorkspace:
```

Three paths, chosen after the probes below:

| `kind` | Path state | Action |
|---|---|---|
| `worktree` | does not exist / empty dir | `_provision_worktree(...)` — the private helper that runs `git worktree add` |
| `worktree` | existing linked worktree of this repo | adopt: insert a row, **no** `worktree add` |
| `primary` | existing primary checkout of this repo | register: insert a row, zero mutating git commands |

Keep `_provision_worktree` private and let it hold only the `worktree add` call, so the one mutating git command in this service has exactly one call site. Everything else — probing, validation, the row insert — belongs to `register_workspace`.

Two cases, decided by probing the path **before** running anything mutating. This is re-review finding 1, and without it **the documented rollout cannot succeed** — verified against the real target:

```
$ git worktree add --detach ../ws1 HEAD      # path is already a worktree
Preparing worktree (detached HEAD 35ca9e2)
fatal: '../ws1' already exists
exit=128
```

**Case A — fresh provisioning.** Path does not exist (or exists and is an empty directory, which `worktree add` accepts — verified, exit 0):

```python
["-C", scope.repo_path, "worktree", "add", "--detach", path, scope.base_ref]
```

**Case B — adoption.** Path already exists and is a git worktree of *this* repo. Register the row and run **no** `worktree add`. `tizonia-openmax-il-issue-818` is exactly this case: it holds #818's history, it is already a valid pool member, and design §7 says register rather than delete it.

Adoption must be **validated, not assumed** — a path that exists is not necessarily a worktree of this repo, and even if it is, it may be the *primary*. Three probe values, all required:

```python
["-C", path, "rev-parse", "--path-format=absolute",
 "--git-dir", "--git-common-dir", "--show-toplevel"]
# line 1 (--git-dir):        == line 2 → primary checkout;  != line 2 → linked worktree
# line 2 (--git-common-dir): must equal the scope's own --git-common-dir
# line 3 (--show-toplevel):  must equal `path`
```

One `rev-parse` invocation returns all three, one per line, in the order requested — no reason to spend three subprocesses.

| Probe result | Meaning | Action |
|---|---|---|
| all three match, `--git-dir` **differs** from `--git-common-dir` | a **linked worktree** of this repo, at its root | adopt as `kind="worktree"` |
| all three match, `--git-dir` **equals** `--git-common-dir` | the **primary checkout** | adopt only as `kind="primary"` — reject for `worktree` (§2.9, third-review finding 2) |
| `--git-common-dir` differs | belongs to **another repository** | reject, 409 |
| exit 128 / "not a git repository" | plain directory with content in it | reject, 409 — `worktree add` would fail anyway |
| common-dir matches, `--show-toplevel` differs | a **subdirectory** of a worktree | reject, 409 |

That last row is a real trap and the reason `--show-toplevel` is not optional. Verified: `git -C ws1/sub rev-parse --git-common-dir` returns the *same* common dir as `ws1` itself, so a common-dir-only check happily adopts `ws1/sub` as an independent workspace — two rows, one physical tree, the exact defect the global path constraint exists to prevent, arriving through the validator.

Second trap, also verified: **`--git-common-dir` is relative when run from the primary** (`.git`, not `/abs/path/.git`), so comparing raw output would never match. `--path-format=absolute` on *both* sides, or resolve before comparing.

```
$ git -C ws1  rev-parse --git-common-dir   → /tmp/wtprobe/main/.git
$ git -C main rev-parse --git-common-dir   → .git                     # relative!
```

The real rollout target checks out clean under this rule:

```
$ git -C .../tizonia-openmax-il-issue-818 rev-parse --show-toplevel
/home/juan/work/repos/tizonia/tizonia-openmax-il-issue-818
$ git -C .../tizonia-openmax-il-issue-818 rev-parse --path-format=absolute --git-common-dir
/home/juan/work/repos/tizonia/tizonia-openmax-il/.git
```

**The third probe exists because the first two do not distinguish the primary from a worktree.** Third-review finding 2, verified and serious: the human checkout satisfies *both* the common-dir and `--show-toplevel` conditions, so `{"path": scope.repo_path, "kind": "worktree"}` would have been accepted — and since worktrees default `dispatchable=True`, that registers the human's checkout as an autonomous work target. It re-opens the *first* review's finding 1 through the validator that was written to make adoption safe. The discriminator is `--git-dir` vs `--git-common-dir`, verified on the real rollout target:

```
# primary
$ git -C .../tizonia-openmax-il rev-parse --path-format=absolute --git-dir --git-common-dir
/home/juan/work/repos/tizonia/tizonia-openmax-il/.git
/home/juan/work/repos/tizonia/tizonia-openmax-il/.git          # equal → primary

# linked worktree
$ git -C .../tizonia-openmax-il-issue-818 rev-parse --path-format=absolute --git-dir --git-common-dir
/home/juan/work/repos/tizonia/tizonia-openmax-il/.git/worktrees/tizonia-openmax-il-issue-818
/home/juan/work/repos/tizonia/tizonia-openmax-il/.git          # differ → linked
```

**So validate `kind` semantics, not just repository membership** — both directions, because each protects something different:

| Request | Rule | Rejecting it prevents |
|---|---|---|
| `kind="worktree"` | `--git-dir` must **differ** from `--git-common-dir`, and `path != scope.repo_path` | the human checkout becoming a dispatchable work target |
| `kind="primary"` | `--git-dir` must **equal** `--git-common-dir`, and the common dir must match the scope's | an unrelated repo, or a linked worktree, being registered as this scope's primary |

Check `path != scope.repo_path` **as well as** the git-dir test even though they overlap. They fail differently: the string test is free and catches the ordinary case with a clear message, while the git-dir test catches the case where a scope's `repo_path` is itself a linked worktree — legal, and then the primary of that repo is some third directory the scope never names.

`rev-parse` is read-only, so this is not a violation of "the primary is not Deck's to mutate": the standing rule is zero *mutating* git commands on a primary, and three lines of `rev-parse` output are not a mutation. State the test that way (finding 6 below).

If `worktree add` fails because a *stale* registration exists for a path whose directory was deleted, the git error names it and tells the operator to run `git worktree prune`. Do **not** run `prune` automatically — it mutates the primary's metadata for all worktrees, and Deck's standing rule is that the primary is not Deck's to mutate. Surface the error.

**Adoption also needs an occupancy gate, which provisioning does not.** Third-review finding 4. A freshly provisioned worktree is known empty and known unoccupied; an adopted one is neither. Deck's *first* live action after this merges is adopting a hand-created soak worktree, so this is the one path where the guess is load-bearing. Two checks before an adopted row may be `dispatchable=True`:

```python
["-C", path, "status", "--porcelain"]        # must be empty
```

- **Clean tree.** Non-empty output → reject with 409 and the porcelain output. Note this is `--porcelain` *without* `--untracked-files=no`: untracked files matter here, because the next `acquire` runs `clean -fd` and will delete them. Ignored files are excluded by default, which is right — the whole point of §2.1 is that ignored build dirs survive.
- **No live session using the path.** `discover_agent_sessions()` (`app/services/agent_bridge/discovery.py:98`) returns a `cwd` per pane (`:88`); reject if any session's `cwd` resolves to `path`. Compare with `os.path.realpath` on both sides, not raw strings — the whole reason `normalize_repo_path` exists.

Both are advisory-strength rather than airtight — a pane can `cd` elsewhere and an agent can start writing a second after the check — and that is fine. This is a synchronous operator action, not an automated gate, and its job is to stop the obvious mistake of adopting a directory something is visibly working in.

**Measured on the real rollout target, which is why this gate is cheap:**

```
$ git -C .../tizonia-openmax-il-issue-818 status --porcelain | wc -l
0                                             # clean — adoption proceeds
$ tmux list-panes -a -F '#{pane_current_path}' | sort | uniq -c
      5 /home/juan/work/repos/tizonia/tizonia-openmax-il      # 5 live sessions — on the PRIMARY
```

Read those two together: the worktree Deck is about to adopt is clean and unoccupied, while the primary — the directory finding 2 would have let us register as dispatchable — has **five live agent sessions in it right now.** The gate passes for the intended target and would have caught the dangerous one. That is the argument for including it in PR A rather than deferring it.

The review's alternative was to default adopted rows to `dispatchable=False` pending a separate activation action. Not adopted: it adds a third endpoint to un-stage them, and §7 step 2 would then register a pool with zero dispatchable workspaces, so rollout would appear to succeed and dispatch nothing. Validate at adoption instead, and let an operator who *wants* a staged row pass `dispatchable=false` explicitly — which Task 5b step 4 already honours.

**Ordering, and the resolution of a contradiction the first review caught (finding 10):** `git worktree add` runs *before* any row exists, so a failure there has nowhere to write `provision_error`. On failure, raise, and **persist no row** — the API surfaces the git error to the operator, who is standing right there because registration is a synchronous human action. A half-registered disabled row would be worse: something they must then discover and clean up. So `provision_error` is only ever written for **reset** failures on an existing row, and the earlier "test 20" that said provisioning failure writes `provision_error` and returns quietly is withdrawn.

**`dispatchable` and `enabled` are parameters of this method**, applied to the row it inserts — the API resolves the defaults (Task 5b step 4) and passes them through. The earlier signature took neither while the request model exposed both, which would have let the endpoint silently ignore its own fields. There is exactly one place these are written, and it is here.

This method gets an HTTP caller in Task 5 (design §2.10). It is not dead code and it is not driven from a REPL.

Tests: design §6 items **24 through 31 inclusive of every lettered sub-item** — 24, 24a-24k, 25-31 — in a new `tests/agent_teams/test_github_workspace_service.py`. The lettered ones are not optional extras; 24g and 24i/24j are the third review's safety blockers. Inject a fake runner that records `args` lists and can be told which step fails.

**Item 25 must assert the absence of `-x`**, e.g.:

```python
assert ["-fd"] == [a for call in calls for a in call if a.startswith("-f")]
assert not any("-x" in arg or "-fdx" == arg for call in calls for arg in call)
```

**Item 26 must assert `--force` on the switch and an explicit ref on the reset** — the exact regression the review found.

**Item 27 must assert zero *mutating* git calls** for `kind="primary"` — and additionally that the calls which *do* happen are exactly the read-only identity probes. Third-review finding 6: this line used to say "zero git calls, not 'no destructive calls', *zero*", which the same task now contradicts by requiring `rev-parse` probes on the primary. An implementer following it literally would either skip the probes (re-opening finding 2) or write a test that cannot pass. Assert on mutation, not on call count:

```python
assert all(call[2] == "rev-parse" for call in calls)   # ["-C", path, "rev-parse", ...]
```

**Item 28 must assert `enabled is True` after a `fetch` failure.** This is the one whose absence let the earlier draft ship a pool-draining bug; it is worth writing first.

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

### 3d. Release on launch failure — **every** shape, not just `ValueError`

The earlier draft released only in the `except ValueError:` block. That is the *rare* path. Read `agent_team_service.py:606-649` before writing this: `_launch_slot` wraps spawning in `except Exception` and **returns** `AgentTeamLaunchResultItem(status="failed")` rather than raising. Dispatch then handles that at `:250-262` by setting `dispatch_status="failed"` — with no release. So the most likely real failure, tmux or the provider CLI refusing to start, leaks the lease.

Release on the *returned* failure statuses only. **No exception path releases** — third-review finding 1, and it goes further than that review proposed; see below.

| Where | Outcome | Action |
|---|---|---|
| `except ValueError:` (`:244-250`) | escalate `plan_blocked` | **do not release** — escalation + reclaim handles it (below) |
| `:250-262`, returned `status="failed"` | `dispatch_status="failed"` | **release**, then `continue` |
| same block, `status="blocked"` / `"blocked_provider_unavailable"` / `"blocked_agent_mail_not_configured"` | blocked statuses | **release**, then `continue` |
| returned `status="pending_registration"` | **success — this is what a successful spawn returns** | **do not release** |
| returned `status="reused"` | a session was reused (unreachable today — `reuse_existing=False`) | **do not release** |
| anything else | unknown | **do not release — fail closed** |
| **any exception escaping `launcher(...)`** | **unknown — may have spawned already** | **do not release**; escalate `launch_outcome_unknown`, re-raise (below) |

**There is no `"launched"` status.** An earlier draft of this table invented one, and re-review finding 3 is right that following the table literally would have been dangerous: an implementer matching on `"launched"` finds no match, falls into the unknown/else branch, and releases the workspace out from under a session that just spawned successfully. Verified — `_execute_plan_item` returns `status="pending_registration"` on the success path (`agent_team_service.py:627-638`) and the full status vocabulary is a `Literal` at `schemas.py:2039-2050`:

```
ready  blocked  skipped  skipped_disabled  reused  spawned
pending_registration  failed  blocked_provider_unavailable
blocked_agent_mail_not_configured
```

Of those, `_execute_plan_item` can actually return only `reused` (`:564`), `skipped_disabled` (`:581`), `pending_registration` (`:631`), `failed` (`:644`), and the two `blocked_*` values via `_blocked_result_status` (`:859-864`). `ready` / `skipped` / `blocked` belong to the *plan* item type, and **`"spawned"` is declared in the Literal but emitted nowhere** — which is exactly why the next paragraph matters.

**Write the release condition as a positive list plus a fail-closed default:**

```python
_LAUNCH_FAILED_STATUSES = {
    "failed",
    "blocked",
    "blocked_provider_unavailable",
    "blocked_agent_mail_not_configured",
}
```

Keep plain `"blocked"` in that set even though `_blocked_result_status` (`:859-864`) never returns it for a *result* item — it maps to the two `blocked_*` values or falls back to `"failed"`. The set mirrors the existing failure set at `:250-256` exactly, and having the two agree is worth more than pruning one unreachable string.

Release when `launch_status in _LAUNCH_FAILED_STATUSES`. Do **not** release for any other value — including one this plan has not enumerated. Two independent reasons:

- A status Deck does not recognise is not evidence that no process exists. `"spawned"` is already in the type awaiting a producer, and the safe reading of an unknown status is "something may be running in there."
- Reclaim will collect the lease later anyway if the item lands in a non-working status with no live session (Task 2d). Retaining wrongly costs latency; releasing wrongly resets a directory under a live agent. The asymmetry decides it.

Belt and braces, and cheap: **never release when the result item carries a real `tmux_target`** (`AgentTeamLaunchResultItem.tmux_target`, `schemas.py:2297`) — a tmux target is direct evidence a session was created, which outranks any status string. `getattr(launch_item, "tmux_target", None)` is non-`None` only on the `reused` and `pending_registration` paths, i.e. exactly the two that must keep the lease.

**Note for the implementer, not a change to make:** the surrounding `dispatch_status` branch at `:250-262` is **fail-open** — its `else` sets `dispatch_status="dispatched"`, so an unrecognised status is recorded as a successful dispatch. Neither review raised this. Leave it exactly as it is (Phase G2 owns the launch path), but do not copy its shape: your release branch must fail *closed* while it fails open. They disagree deliberately, and the disagreement is safe in that direction — an item wrongly marked `dispatched` keeps its lease, which is the conservative outcome for the resource.

The unifying rule, and the reason this is not an exception to Task 4: **release is licensed by the absence of a process, never by a status.** A launch that failed produced no session, so nothing is in the directory and the next acquire's reset is safe. A merge does not produce that guarantee, which is why Task 4 releases nothing.

Holding the lease on the *returned* failure statuses would leak it constantly rather than occasionally — those paths carry positive evidence that no session exists, and with one dispatchable workspace at rollout a single leak wedges autonomy until the next sweep.

### 3d-i. No exception releases the lease — and `except ValueError` is not a safe carve-out

Third-review finding 1 is correct: an earlier draft of the table above ended "any other exception → release, then re-raise", which contradicts Task 4's own rule. Read design §2.3a for the full argument; the implementation consequences are these.

**Why an exception is different from a returned `failed`.** `_execute_plan_item` wraps spawning in `except Exception` and *returns* `status="failed"` (`:639-648`), so a failed spawn reports itself as data and the no-process fact is part of that report. An exception carries no position information — dispatch calls `launcher(...)` once and cannot tell whether it raised before or after `tmux new-session`. And it can raise after: because spawn exceptions are swallowed, anything escaping `launch()` comes from the post-loop code — `await db.commit()`, `await db.refresh(launch)`, and the `AgentTeamLaunchResult(...)` construction (`:527-542`) — all of which run after every slot has already spawned.

**The part to be careful about, which the review did not flag.** The review suggested `ValueError` from the pre-spawn plan gate "may remain a known-safe release path." **Do not implement that.** Two independent reasons, both verified:

- The existing `except ValueError:` at `:244-250` does not wrap only the plan gate — it wraps `_dispatch_brief`, `_send_dispatch_brief_to_slot` *and* the whole `launcher(...)` call (`:213-243`). A `ValueError` arriving there could have come from `:495` (pre-spawn) or from anywhere inside `launch()` (post-spawn). The handler cannot distinguish them.
- `ValueError` is not even a reliable proxy for "pre-spawn" inside `launch()`: `PlanConflictError` subclasses `ValueError` (`agent_team_service.py:54`) *and* `pydantic.ValidationError` subclasses `ValueError` (verified, pydantic 2.12.5) — and the `AgentTeamLaunchResult` construction that can raise the latter runs after every spawn.

So `except ValueError: release` fails for exactly the reason matching on `"launched"` failed: the discriminator looks sound and does not hold.

**What to do instead.** In the `except ValueError:` block, keep the existing `escalate(db, item, "plan_blocked")` untouched and simply **do not release**. In a new outer `except Exception:`, escalate with reason `launch_outcome_unknown` and re-raise. `launch_outcome_unknown` is a new **escalation reason string**, not a new `dispatch_status` — the hard constraints forbid new statuses and `escalated` already means what is needed.

**Why this costs almost nothing, which is the objection to answer.** `plan_blocked` is the most common escalation in the live soak (10 of 11 items) and arrives as a `ValueError`, so retaining on it sounds like a constant leak. It is not, structurally: the `"Launch plan is blocked"` raise at `agent_team_service.py:495` happens *before* `db.add(launch)` at `:509`, so no `AgentTeamLaunch` and no `AgentTeamLaunchItem` row exists. `slot_has_live_owner_session` joins `MailAgentSession` **through** `AgentTeamLaunchItem` (`:106-130`), so with no launch item it cannot return true. The item is `escalated`, which reclaim's status set covers (Task 2d), and the very next sweep releases it — one poll interval, not a wedge.

That is the general shape worth internalising: **a pre-spawn failure cannot fake liveness, so there is no need to guess about it.** Ask the liveness gate a question it can actually answer instead of encoding a guess in an exception type.

Tests: design §6 items **17** and **17c** — both **inverted** from what an earlier draft asserted. Item 17 now requires that an unexpected exception *retains* the lease; if you find yourself writing "asserts release on exception", you are implementing the version the third review rejected.

Tests: design §6 items 14, 15, 16, 17, 17a, 17b, 17c. Item 15 (returned `failed` releases) is the one that maps to the real-world failure; do not settle for the `ValueError` test alone — and note that 17/17c require the `ValueError` path *not* to release, which is the opposite of the earlier draft.

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

- if `builds_out_of_tree`: render `build_dir_template` with `issue_number=item.issue_number` (it defaults to the constant `"build"`, so this normally renders to `"build"` and no placeholder is involved), render `build_command_hint` with `build_dir=<rendered>` and `parallelism=scope.max_build_parallelism`, and emit both. If `build_dir_template` is somehow `None`, use `"build"` rather than omitting the command.
- if not `builds_out_of_tree`: emit the hint with `build_dir=""` plus "Only one build may run in this workspace at a time; this project's build system does not support out-of-tree builds."

Always emit, whenever `max_build_parallelism` is set:

```python
                    f"- Cap build parallelism at -j{scope.max_build_parallelism}. "
                    "Higher values have OOM-killed this host.",
```

That last line is the highest-value sentence in the brief. `ninja` defaults to `-j18` here and `cc1plus` peaks near 1 GB — one unconstrained build can exhaust 15.6 GB by itself.

Use `str.format` with explicit kwargs, and catch **`(KeyError, IndexError, ValueError)`** around it. `KeyError`/`IndexError` alone — what the earlier draft said — misses the most likely typo of all. Verified:

```
'build-{issue_number}'    → 'build-819'
'build-{issue_number'     → ValueError: expected '}' before end of string
'build-{0}'               → IndexError
'build-{bogus}'           → KeyError
'build-{issue_number!z}'  → ValueError: Unknown conversion specifier z
```

An unmatched brace propagates out of `_dispatch_brief` into the poll loop and takes down autonomy for the whole scope — which directly contradicts this plan's own stated requirement that a bad template must not do that. On failure: log, omit the build lines, **still produce the brief**. Also validate templates in the scope create/update path (Task 5a) so the operator learns at write time. Allowed placeholders are exactly `{issue_number}` for `build_dir_template` and `{build_dir}`/`{parallelism}` for `build_command_hint`.

Tests: design §6 items **12, 13** (the workspace path reaches `repo_path_override`; the brief carries the contract lines) and **32-34** (build hints, including the malformed-template containment).

---

## Task 4 — the terminal paths: **write no code, write two tests**

This task is a deliberate non-change, and it is the reviewed draft's biggest reversal. Read it before you decide it's a no-op and skip it.

**The earlier draft told you to release in `_mark_merged` and `_complete_and_notify`. Do not. That instruction was wrong.**

It reasoned from logical state — `merged` and `completed` mean the work is done, so the directory is free — and ignored the physical process. Deck launches agents with `tmux new-session -d` (`agent_bridge/spawn.py:78-84`): a **detached, persistent** interactive CLI. Merging a PR does not terminate it. Closing the issue does not terminate it. The session keeps running, can still receive input, and can still write files.

So releasing on `merged` hands the directory to the next item, whose `acquire` then runs `switch --force`, `reset --hard` and `clean -fd` underneath a live process. `_complete_and_notify` is worse: a human closing an issue by hand marks the item `completed` while its agent is mid-edit. That is Finding 10's mechanism — two owners, one directory — recreated through the release path instead of the dispatch path.

**In PR A the reclaim sweep is the only status-driven releaser** (Task 2d), because it is gated on observed process liveness rather than on status. One mechanism, one gate, physically grounded.

**Add no release to any of these:**

| Call site | Why not |
|---|---|
| `_mark_merged` (`github_verification_service.py:413`) | the tmux session outlives the merge |
| `_complete_and_notify` (`github_watcher_service.py:152`) | a human can close an issue mid-edit |
| `reset_for_retry` (`github_dispatch_service.py:30-41`) | retry keeps its lease so the build dir stays warm |
| `escalate` / `_apply_escalation` | escalation does not mean the agent stopped; `_send_escalation_broadcast` already warns the team the owner may still be working |
| `_record_failed_verification_attempt` | sends the item back to `dispatched` for a fix |
| `_fallback_to_human_merge` | reviewers may request changes |

Consequently **`github_verification_service.py` and `github_watcher_service.py` are not modified by this PR at all.** `_mark_merged` stays sync — the earlier instruction to make it async is withdrawn along with the release it existed to hold.

What you *do* write here is the two tests that pin the reversal, because a future reader will find "release when merged" obvious and helpfully add it:

- design §6 item 20 — `_mark_merged` does **not** release
- design §6 item 21 — `_complete_and_notify` does **not** release

Plus the reclaim guards: **item 19** (non-working status + live owner session → **NOT** reclaimed) is the Finding 10 regression guard. Write it before the reclaim implementation and watch it fail. Item 23 is its complement: a `merged` item whose session is gone **is** reclaimed, so capacity is genuinely recovered — just not promptly.

**Known cost, accepted by the user:** with one dispatchable workspace at rollout, a merged item keeps its workspace until its tmux session goes offline, so the pool can look wedged when it is only waiting. `GET .../workspaces` (Task 5b) shows exactly which item holds what. Prompt terminal release needs *per-item* liveness (`MailAgentSession` via `item.launch_id`), and the existing predicate is slot-scoped and is already scheduled for rewrite in Phase G2 — building a second one now would leave two similarly-named liveness checks to reconcile, in the exact area where Finding 13 showed that identity confusion causes collisions. That is **PR B**, after G2. Do not build it here, and do not build an interim version of it.

---

## Task 5 — API and schemas

### 5a. Scope fields

**`app/models/schemas.py`** (`:2154-2199`) — add all five fields to `TeamGithubScopeCreate` (with the design's defaults, i.e. `build_dir_template: str = "build"`), `TeamGithubScopeUpdate` (`Optional`, default `None`), and `TeamGithubScopeResponse`. Use `Field(default=4, ge=1)` for `max_build_parallelism`; `ge=1` matters, `-j0` is meaningless.

**Validate the two templates on write** (Task 3f): reject a `build_dir_template` or `build_command_hint` that `str.format` cannot render with the allowed placeholders, → 400. A pydantic `field_validator` that attempts the render and catches `(KeyError, IndexError, ValueError)` is enough. The operator should learn at write time, not discover it as a silently missing brief section at dispatch time.

**`app/api/v1/agent_teams.py`** — five `if request.X is not None:` lines in `_apply_scope_create` (after `:151`), five kwargs in `_scope_response` (after `:85`). Match the surrounding style exactly.

### 5b. Four workspace/lifecycle endpoints — read design §2.10 first

An earlier draft of this plan said "no new endpoints." That was copy-forwarded boilerplate from two earlier plans where it was actually derived, and it is wrong here: without an endpoint, `register_workspace` has no caller and workspace registration can only happen by hand-editing the live database, which is forbidden. §2.10 has the full reasoning. (The first review copy you may have seen still carried the prohibition — it was written against a commit that had not been pushed.)

The count then went from two to **four** on re-review, because two endpoints register a pool but cannot *operate* one. Both additions close a deadlock, and each is derived, not preferred:

| Endpoint | Deadlock it closes |
|---|---|
| `POST .../workspaces/{id}/reprobe` | a workspace disabled by a local reset failure can never be re-enabled — `acquire` filters on `enabled`, so reset never re-runs, so `provision_error` never clears; duplicate `POST` 409s; no `PATCH`, no `DELETE` (design §2.10a) |
| `POST .../github-work-items/{id}/abandon` | an item wedged in `ready_for_review` holds the only dispatchable workspace forever — retry 409s, the watcher ignores the status, reclaim excludes it by design (design §2.10b) |

Build them (5b-iii and 5b-iv below). Do **not** substitute a general `PATCH` on workspaces or a direct force-release: design §5 rules both out, and the reasons are safety reasons, not taste.

**`app/models/schemas.py`** — three new models beside the scope ones:

```python
class GithubWorkspaceCreate(BaseModel):
    path: str
    kind: str = "worktree"
    dispatchable: Optional[bool] = None      # None → defaulted by kind
    enabled: bool = True


class GithubWorkspaceResponse(BaseModel):
    id: int
    scope_id: int
    path: str
    kind: str
    lease_state: str
    dispatchable: bool
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
    if not workspace.dispatchable:
        return "disabled_for_dispatch"
    return "available"
```

**Four states, not three.** The earlier draft had three and would report the primary — registered `dispatchable=False` — as `available`, so the operator reads two usable workspaces where there is one. The whole argument for adding these endpoints (design §2.10) is that the operator must stop inferring physical capacity; a `lease_state` that over-counts it defeats the purpose.

Order matters: a leased workspace that was then disabled reports `leased`, because something may still be writing in it. Add a `_workspace_response(workspace)` helper next to `_scope_response` (`:72`).

**`app/api/v1/agent_teams.py`** — four routes, placed after `delete_github_scope` (`:367`) to keep the scope-scoped routes together:

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
2. Validate `kind` in `{"primary", "worktree"}` → 400 otherwise. Do not accept arbitrary strings; `reset_workspace`'s entire safety property is a `kind == "primary"` equality test, and a typo'd `"Primary"` would make Deck `reset --hard` the human's checkout.
3. Normalise `path` with `agent_team_service.normalize_repo_path` — the same call `_apply_scope_create` uses for `repo_path` (`:135-137`). It runs `os.path.realpath`, so `~/foo`, `/home/juan/foo` and a symlink to either collapse to one string *before* the global `UniqueConstraint("path")` sees them. Without this the constraint is trivially bypassable and the exclusivity claim is fiction.
4. **Resolve `dispatchable` and `enabled` here, then pass both to the service.** `dispatchable` when the request leaves it `None`: **`False` for `kind="primary"`**, `True` for `kind="worktree"`. That is the finding-1 fix at the registration end — it must not be possible to register the human's checkout as dispatchable by accident, only deliberately. An **explicit** `dispatchable` in the request wins over the default in both directions: `dispatchable=false` on a worktree (staging a workspace before putting it in service) and `dispatchable=true` on a primary (a deliberate, unusual choice) must both be honoured. `enabled` passes through as given, defaulting `True`.

   This is the second review's contract clarification, and it is a real bug in the earlier draft, not a documentation gap: the request model exposed both fields while `provision_worktree(db, scope, path)` accepted neither, so the endpoint would have accepted `dispatchable=false` and silently produced a dispatchable row. Task 2f's signature now takes both keyword-only. There is exactly **one** place either value is written — the insert inside `register_workspace` — for both the provisioning and adoption paths and for `kind="primary"`.
5. **Query for the canonical `path` and 409 if a row already exists — before calling the service at all.** Third-review finding 5, and it is a real orphan-producing ordering bug, not just a nicer error: for a path that is registered in the DB but *missing on disk*, the earlier flow reached `git worktree add`, succeeded, and then failed the row insert on the global `UniqueConstraint("path")`. The `IntegrityError` handler returns a clean 409 and the request looks correctly rejected — while a **new git worktree now exists on disk that Deck has no row for.** Nothing will ever reset it, reclaim it, or tell the operator it is there. Do the `select` first; a mutating git command must not run on a path Deck already knows about.

   Keep the `IntegrityError` handler anyway (step 8) for the concurrent-request race. Check-then-act is not atomic, and the constraint is the only thing that actually enforces uniqueness — the pre-check exists to protect the *filesystem*, the constraint to protect the *table*.
6. `await github_workspace_service.register_workspace(db, scope, path, kind=kind, dispatchable=..., enabled=...)` for **both** kinds. The method decides provision vs. adopt vs. primary-register (Task 2f); the endpoint does not branch on `kind` beyond validating it and defaulting `dispatchable`. Keeping the branch inside the service is what guarantees the identity probes run for `kind="primary"` too — an endpoint-level `if kind == "primary": db.add(...)` shortcut is how an earlier draft skipped them.
7. Provisioning/adoption failure → surface the git error (409 with the git output) and persist **no row** (Task 2f). This covers `worktree add` failing, a foreign repo, a nested subdir, a non-git directory, a `kind`/git-dir mismatch either way, and an adopted tree that is dirty or occupied.
8. `IntegrityError` → 409 `"Workspace path already registered"`, mirroring `create_github_scope` (`:337-339`). Note the message is not "for this scope" — the constraint is global, and the conflicting row may belong to a different scope, which is exactly the case worth telling the operator about. Without this handler the duplicate-path constraint surfaces as a 500.

**No `DELETE`.** Design §5 forbids Deck removing worktrees, and a delete whose lease check was wrong would pull the directory out from under a running agent.

Tests: design §6 items 35, **35a**, 36, **36a**. Item 35a is the pre-check ordering test — a registered-but-missing path must 409 with zero mutating git commands.

### 5b-iii. `POST .../workspaces/{workspace_id}/reprobe` — the repair path

```python
@router.post(
    "/github-scopes/{scope_id}/workspaces/{workspace_id}/reprobe",
    response_model=GithubWorkspaceResponse,
)
```

Without this, a workspace disabled by a local reset failure is dead forever. Walk the trace before you write it, because it is not obvious from any single file: `acquire` filters `enabled.is_(True)` (Task 2b), reset runs **only** from `acquire` (Task 2e), `provision_error` is cleared **only** by a successful reset (Task 2b step 5), a duplicate `POST` 409s on the global path constraint, and there is no `PATCH` and no `DELETE`. Five separate correct decisions compose into an inescapable state. On a size-1 dispatchable pool that is autonomy dead until someone edits the database — which the hard constraints forbid, correctly.

Behaviour:

1. 404 if the scope or the workspace is missing, or if the workspace's `scope_id` does not match the path's `scope_id` (do not let a workspace be reprobed through another scope's URL).
2. **409 if `workspace.leased_item_id is not None`** — and make this the first check after lookup. Reprobe *is* the reset sequence; running it under a live agent is the exact collision this design exists to prevent. No git command may run on this path.
3. 409 if `kind == "primary"` — the primary is never reset (design §2.6).
4. Otherwise call `reset_workspace`. On success set `enabled=True`, clear `provision_error`, commit, return 200 with the row. On failure leave `enabled=False`, overwrite `provision_error` with the new error, commit, and return 409 with the git output.

**It re-enables only on success.** That is the whole reason this is a named action rather than `PATCH {enabled: true}`: an operator must not be able to assert a broken tree is healthy. The probe decides.

Note the `fetch`-vs-local distinction from Task 2e still applies inside `reset_workspace`, so a reprobe that fails only at `fetch` leaves `enabled` alone — meaning a *transiently* failing reprobe on an already-disabled row does not "re-disable" it, it just does not re-enable it. That is correct and needs no special case.

Tests: design §6 items **36b, 36c, 36d**.

### 5b-iv. `POST .../github-work-items/{item_id}/abandon` — the operator's escape hatch

```python
@router.post(
    "/github-work-items/{work_item_id}/abandon",
    response_model=GithubWorkItemResponse,
)
async def abandon_github_work_item(
    work_item_id: int,
    request: GithubWorkItemAbandonRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
```

Place it immediately after `retry_github_work_item` (`:405-435`) and mirror its shape exactly: `work_item_id` (not `item_id`) to match the existing route, an optional request body defaulting to `None`, `db.get` for both item and scope with 404s, 409s for wrong state, then `await db.commit()`, `await db.refresh(item)`, `return _work_item_response(item, scope)`. Add `GithubWorkItemAbandonRequest` beside `GithubWorkItemRetryRequest` in `schemas.py` with a single optional `reason: Optional[str] = None`.

Design §4.2 used to claim retry or manual issue closure could clear a wedged review item. It cannot, and re-review finding 4 is right. Verified, all four exits closed for a code item in `ready_for_review` holding a PR:

| Exit | Why it fails |
|---|---|
| `POST .../retry` | 409s unless `dispatch_status == "escalated"`, then 409s again on `pr_number is not None` (`agent_teams.py:405-435`) |
| closing the issue | `_CLOSED_ISSUE_RECONCILABLE_STATUSES = ("escalated", "failed")` (`github_watcher_service.py:18`), and `_reconcile_closed_issues` `continue`s on `pr_number is not None` (`:117-147`) — **two** independent reasons, so adding the status alone would not have helped |
| the watcher | `_ACTIVE_STATUSES = ("dispatched", "verifying", "awaiting_human_review")` (`:14`) omits `ready_for_review` |
| reclaim | excludes `ready_for_review` deliberately (Task 2d) — a reviewer may legitimately be requesting changes |

Do **not** "fix" this by adding `ready_for_review` to any of those sets. Each exclusion is individually correct, and the watcher and verification services are off-limits in this PR anyway (Task 4).

Behaviour:

1. `db.get(GithubWorkItem, item_id)`; `None` → 404.
2. Accept only `ready_for_review`, `awaiting_human_review`, `dispatched`, `verifying` → 409 otherwise. `merged`, `completed`, `failed` and `escalated` are already reclaimable, so abandoning them is a no-op that would only obscure the original reason.
3. `await github_dispatch_service.escalate(db, item, "abandoned_by_operator", note=...)`. Reuse `escalate` — do not write `dispatch_status` by hand. It handles the team broadcast, the `preserve_existing_reason` guard and the rollback path (`github_dispatch_service.py:643-694`). **No new `dispatch_status` value:** `escalated` already means "a human must look at this", which is exactly true.
4. Pass `request.reason` through as the note when present — `escalate` writes it to `status_note`. When absent, use an explicit default such as `"Abandoned by operator; workspace lease will be reclaimed once the owner session is offline."` Note this differs from `retry`, which writes its reason into `pending_reason` (`:431`); here the reason belongs in `status_note` because `escalate` clears `pending_reason` (`:690`).
5. **Do not release the lease. Do not kill the session.** Return the item; the reclaim sweep frees the workspace on a later poll *if* the owner session is offline.

Step 5 is the safety argument, and it is why this endpoint does not violate Task 4. `abandon` changes the item's **status**, which is Deck's to change. It asserts nothing about the **process**, which Deck cannot observe from an HTTP request. An operator who abandons an item whose agent is still live gets exactly the right outcome: the item is flagged for human attention and the lease is held until the agent actually goes away. The invariant survives intact — *release is licensed by the absence of a process, never by a status.*

One thing to know rather than change: `escalate` computes `owner_may_be_active` as `item.dispatch_status == "dispatched"` (`:650-652`), so abandoning from `ready_for_review` will **not** emit the built-in "the owner session may still be working — do NOT retry" warning, even though that is precisely the situation. Put that caution in your default `note` instead of widening the condition. `escalate` belongs to Phase G2's area and the hard constraints say not to touch it.

Tests: design §6 items **36e, 36f**.

### 5b-v. Every rejection carries a `block_code` — the operator may be an agent

Read design §2.10c before writing this. The short version: Deck has two classes of operator, and everything written above about "the operator" assumed the human one. `mcp_shim/agent_mail_server.py` already exposes 18 `deck_*` tools including `deck_create_team`, `deck_plan_team_launch`, `deck_launch_team`, `deck_list_work_items` and `deck_retry_work_item` — so an agent driving Deck's Agent Team surface is the existing pattern, not a future idea. These four endpoints are the first significant operator surface that does not extend it.

**Do not add MCP tools in this PR** (design §2.10d — they are additive over REST and the external-supervisor identity question needs its own design pass). **Do** add the codes, because they are the wire contract those tools would speak and retrofitting one after something parses prose is a breaking change.

Use the format that already exists — do not invent one. `_bad_request` at `agent_teams.py:45-51` raises `detail={"message": str(exc), "block_code": exc.block_code}` for `ProviderLaunchError`, and the shim's `_http_error_result` reads a dict `detail`, taking `message` for humans and surfacing `block_code` on the error object. A plain-string `detail` still becomes the message, so the ~40 existing string-detail raises in this file are unaffected.

Add a small helper next to `_bad_request` rather than inlining dicts at eight call sites:

```python
def _conflict(message: str, block_code: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": message, "block_code": block_code},
    )
```

The eight codes, and the endpoint step each replaces:

| Code | Raised from | Caller's correct response |
|---|---|---|
| `workspace_path_registered` | 5b step 5 (pre-check) **and** step 8 (`IntegrityError`) | read `GET .../workspaces`; may need `reprobe`, not registration |
| `workspace_not_a_worktree` | 5b step 7 — path exists, is not a worktree of this scope | fix the path; never retry unchanged |
| `workspace_is_primary` | 5b step 7 — `kind="worktree"` resolved to `scope.repo_path` | **never** retry; this is the ★★ guard |
| `workspace_dirty` | 5b step 7 — adopted tree unclean | commit or stash, **then** retry |
| `workspace_occupied` | 5b step 7 — a live session's `cwd` is that path | wait, then retry — transient |
| `workspace_leased` | 5b-iii step 2 | wait for reclaim, then retry |
| `workspace_reset_failed` | 5b-iii step 4 | escalate to a human; the tree needs hands |
| `work_item_not_abandonable` | 5b-iv step 2 | re-read status; may already be reclaimable |

Two of these carry the argument for the whole subsection: `workspace_dirty` and `workspace_occupied` are 409s on the same request with the same English shape ("adoption refused") and **opposite** correct handling — one requires an action before retrying, the other requires only patience. A human reads the sentence and knows. An agent given only prose must match on wording that no test pins, so the first reword silently turns "wait and retry" into "give up" or the reverse.

Note `workspace_path_registered` is deliberately the same code from both the pre-check and the race-losing `IntegrityError`: the caller's situation is identical and it has no way to tell them apart, so distinct codes would imply a distinction it cannot act on.

Keep `kind` validation (5b step 2) a **400** with its existing string detail — it is a malformed request, not a state conflict, and it is the one rejection where the caller's bug is in the request itself.

Tests: design §6 items **36g, 36h**. 36g is table-driven over all eight codes; 36h asserts the dict shape stays compatible with `_http_error_result`.

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

Test: design §6 item 37.

### 5d. Frontend — bounded (design §2.11)

The earlier "do not touch the frontend" is withdrawn. Four edits, no more — three in `AutonomyPanel.tsx`, one in `agentTeams.ts`:

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

**Not in this task:** the pool summary on the scope card. It needs a second fetch and its own loading/error state in a component that currently fetches scopes and items only. Design §2.11 lists it as worth doing; it is a follow-up, and `GET .../workspaces` plus `curl` covers deployment. If someone does build it later, it must count **dispatchable** rows — a summary that includes the primary reports twice the capacity that exists.

**Also not in this task: any UI for `reprobe` or `abandon`.** Both are operator-recovery actions on an exceptional path, both are one `curl` away, and both are things it should be slightly inconvenient to do. A button for `abandon` next to the existing retry button would invite clicking it on an item that is merely slow — the design's whole position is that a queued pool must not be mistaken for a stuck one (§2.11). Revisit after PR B, when abandonment is detected automatically and the manual action becomes rare rather than routine.

Run `cd frontend && npm run lint` — TypeScript strict mode with `noUnusedLocals` will fail the build on a stray import.

---

## Task 6 — verify and open the PR

```bash
cd backend && source venv/bin/activate && pytest tests/agent_teams tests/agent_mail -q
pytest tests/ -q            # full suite; report any pre-existing failure, do not fix it
cd ../frontend && npm run lint && npx tsc --noEmit
```

Expected: baseline + ~60 new tests. Report the actual number.

Sanity checks — all nineteen must hold:

```bash
grep -rn "fdx\|'-x'\|\"-x\"" app/services/github_workspace_service.py    # must be EMPTY
grep -n "repo_path_override" app/services/github_dispatch_service.py     # must show workspace.path, NOT scope.repo_path
grep -n "dispatchable" app/services/github_workspace_service.py          # must appear in acquire's filter
grep -n '"--force"' app/services/github_workspace_service.py             # must appear on the switch
git diff --stat app/services/github_client.py app/services/github_watcher_service.py app/services/github_verification_service.py
# ALL THREE must be EMPTY — Task 4 changes no production code
grep -n "outerjoin" app/api/v1/agent_teams.py        # must exist in list_github_work_items
grep -n "router.delete" app/api/v1/agent_teams.py    # must NOT mention workspaces
grep -rn "release" app/services/github_verification_service.py app/services/github_watcher_service.py
# must find NO call to github_workspace_service.release
grep -n "launched" app/services/github_dispatch_service.py app/services/github_workspace_service.py
# must be EMPTY — there is no such launch status; success is "pending_registration"
grep -n "path-format=absolute" app/services/github_workspace_service.py  # must appear in the identity probe
grep -n "show-toplevel" app/services/github_workspace_service.py         # must appear beside it
grep -rn "worktree.*prune\|\"prune\"" app/services/github_workspace_service.py
# must show ONLY "--prune" on the fetch; NO "git worktree prune"
grep -n "git-dir" app/services/github_workspace_service.py
# must appear in the identity probe, beside --git-common-dir — this is the primary/linked discriminator
grep -n "repo_path" app/services/github_workspace_service.py
# must show the kind="worktree" guard: path must NOT equal scope.repo_path
grep -n "status.*porcelain" app/services/github_workspace_service.py     # must appear in the adoption gate
grep -n "except ValueError" app/services/github_dispatch_service.py
# the existing handler stays, but must NOT contain a release call
grep -n "provision_worktree" app/services/*.py app/api/v1/*.py
# must be EMPTY or private-only — the public method is register_workspace(kind=...)
grep -c "block_code" app/api/v1/agent_teams.py
# must be >= 9 — the existing _bad_request one, plus the eight of Task 5b-v
grep -n "workspace_dirty\|workspace_occupied" app/api/v1/agent_teams.py
# BOTH must appear — same 409, opposite recovery; prose alone cannot tell them apart
```

The third and fourth are the two findings the first review caught that a passing test suite would not have caught on its own. The fifth is the Task 4 inversion in one command: if either file shows a diff, the terminal release went back in.

The next four are the second review's findings in the same form. `grep launched` catches the invented status: if it appears anywhere, a release condition is matching a string the launcher never emits. The two `rev-parse` greps catch an identity check that compiles and passes a naive test but rejects every real adoption (relative common-dir) or accepts a nested subdir. And the `prune` grep catches an implementer helpfully "fixing" a stale worktree registration by mutating the primary's metadata.

The final two are the agent-operator pass. Deck's other class of operator cannot read an English sentence, and `workspace_dirty` / `workspace_occupied` are the pair that proves it: same endpoint, same 409, and opposite correct handling (act-then-retry vs. wait-and-retry). If only one of them appears, an agent operator has no way to choose.

The five before those are the third review's. `grep git-dir` is the important one: without that probe the identity check still passes every test written for the *second* review's findings while accepting `{"path": scope.repo_path, "kind": "worktree"}` — the human checkout, registered dispatchable. `grep except ValueError` catches the release that must not be there; if a release call sits in that handler, a `ValidationError` raised after tmux spawned will reset a directory under a live agent. And `grep provision_worktree` catches a half-applied rename, where the endpoint still calls a method that never learned about `kind`.

The `outerjoin` check is not pedantry: an inner join there drops every unleased item from the work-items list, which is most of them, and the UI would look empty rather than broken.

Open ONE PR into `feature/autonomous-github-dispatch` describing:

- the phantom-contract diagnosis, and that the brief now states the contract explicitly including the prohibitions;
- the lease invariant and that `UniqueConstraint("leased_item_id")` enforces it in the schema rather than in query logic (the Finding 10 lesson);
- `UniqueConstraint("path")` being **global**, and why a per-scope constraint does not protect a physical directory;
- `dispatchable`, and that without it the primary checkout would have won the first dispatch;
- the reclaim rule, that it is the **only** status-driven releaser, and **why escalation alone does not release** — cite the live-session check;
- **that nothing releases on `merged`/`completed`, and why** — `tmux new-session -d` outlives the merge. Name this as the PR's main deliberate limitation, with the latency cost stated, and point at PR B;
- **that autonomy must stay off until PR B lands** (design §4.1a) — PR A is a staging PR whose only prompt releaser is a human, so unattended dispatch on a size-1 pool can stall indefinitely and will look like the Finding 14 wedge;
- that launch failure *does* release, in every shape including the returned `status="failed"` — and that the unifying rule is "release is licensed by the absence of a process, never by a status";
- **that no *exception* releases**, including `ValueError` — an exception says nothing about whether tmux already spawned, and `ValidationError` subclasses `ValueError` and can be raised post-spawn (design §2.3a);
- that registration validates `kind` in **both** directions via `--git-dir` vs `--git-common-dir`, and that without it the human's checkout could be registered as a dispatchable worktree — the first review's finding 1 reopened through the adoption validator;
- that adoption additionally requires a clean tree and no live session on the path, because a fresh worktree is known unoccupied and an adopted one is not;
- that the duplicate-path check runs **before** any mutating git command, so a rejected request cannot leave an unregistered worktree on disk;
- that the success status is **`pending_registration`**, that the release condition is a positive list with a **fail-closed** default, and that a non-`None` `tmux_target` vetoes release regardless of status;
- **adoption** — `worktree add` exits 128 on an existing worktree, so registering `issue-818` requires it; and the three probe values it needs (`--git-dir`, `--git-common-dir` under `--path-format=absolute`, and `--show-toplevel`), naming all three traps: the relative common-dir from the primary, a nested subdir sharing a common-dir, and the primary satisfying every check that only tests repo membership;
- the two operability endpoints and the deadlock each closes: `reprobe` (a disabled workspace can otherwise never be re-enabled) and `abandon` (a `ready_for_review` item holds the only workspace forever — all four pre-existing exits closed);
- that `abandon` deliberately **does not** release the lease or kill the session — it changes status only, leaving the liveness gate as the single arbiter of release;
- `clean -fd` vs `-fdx` and the 1.1 GB build dir; `switch --detach --force` and the dirty-tree abort it fixes;
- that a `fetch` failure does **not** disable a workspace, and why the alternative drains the pool;
- that the primary checkout is never reset;
- `builds_out_of_tree=False`, `max_build_parallelism=4` and `build_dir_template="build"` as deliberately conservative defaults, the last one because `clean -fd` preserves ignored dirs;
- that 3b (host-wide build semaphore) is **not** in this PR and is a documented prerequisite for a second scope (design §3.2);
- the four new endpoints and why registration needs one at all — a service method with no caller would force hand-edited DB rows (design §2.10);
- that there is deliberately **no `DELETE`**, no `PATCH` on workspaces, and no force-release;
- the four bounded frontend changes, and that `queued_no_workspace` rendering as blank space would have made a correctly-working pool look like the Finding 14 wedge;
- **that every rejection carries a `block_code`, because Deck's operator may be an agent** — the Agent Team surface is already driven by 18 `deck_*` MCP tools, and `workspace_dirty` vs `workspace_occupied` are two 409s with opposite correct recovery that prose cannot distinguish (design §2.10c). Note the format reuses the existing `_bad_request` / `_http_error_result` contract rather than inventing one;
- that MCP tools for these four endpoints are deliberately **not** in this PR, and that the reason is a real open question rather than scope-trimming: today's agent-operator tools derive authority from the caller's own team membership, which cannot express an external supervising agent (design §2.10d);
- the final test count and the nineteen sanity checks above.

Then STOP and report. Do not merge. Do not restart the backend. Do not register workspaces or edit any DB row — the orchestrator does that on the live soak after merge, through the endpoints you just built.

---

## Hard constraints

- Work **only** in `/home/juan/work/repos/juanrubio/claude-deck-g1`. Never touch `/home/juan/work/repos/juanrubio/claude-deck` (live soak, live DB) or `/home/juan/work/repos/tizonia/` (5 live agent sessions hold it as cwd).
- ONE PR into `feature/autonomous-github-dispatch`. Never merge, self-merge, or merge to master.
- NO new `dispatch_status` values. `queued_no_workspace` is a `pending_reason`.
- Do not touch `slot_has_live_owner_session`, `reuse_existing`, or the launch path beyond the single `repo_path_override` argument (Phase G2 owns those).
- Do not touch `github_client.py`, `_reconcile_closed_issues`, `_apply_escalation`, `_ACTIVE_STATUSES`, `_CLOSED_ISSUE_RECONCILABLE_STATUSES`, or any status constant. You may **call** `escalate` (Task 5b-iv) but not modify it — in particular do not widen its `owner_may_be_active` condition.
- **Do not modify `github_verification_service.py` or `github_watcher_service.py` at all** (Task 4). No terminal release, no per-item liveness predicate, no closed-unmerged-PR handling — all PR B.
- No new dependencies.
- **Exactly four new endpoints**, no more (Task 5b):
  - `GET` and `POST` `/github-scopes/{scope_id}/workspaces`
  - `POST` `/github-scopes/{scope_id}/workspaces/{workspace_id}/reprobe`
  - `POST` `/github-work-items/{work_item_id}/abandon`

  No `DELETE` anywhere. No `PATCH` on workspaces — `reprobe` re-enables only on a successful reset, and a field write would let an operator assert a broken tree is healthy. No force-release endpoint — `abandon` changes status and leaves release to the liveness gate. No workspace *activation* endpoint either: the third review suggested defaulting adopted rows to `dispatchable=False` pending one, and adoption validates instead (Task 2f). (The count went "none" → two → **four** and stayed there across the third review. Each addition was derived from a traced deadlock, and the number is not a budget to spend.)
- **`register_workspace` is the only public entry point** to the service's registration path, and `_provision_worktree` — the one method that runs `git worktree add` — stays private with exactly one call site. Do not add a second caller of `worktree add`, and do not reintroduce a public `provision_worktree`.
- **No release call inside `except ValueError`** (`github_dispatch_service.py:244-250`). The existing `escalate(db, item, "plan_blocked")` stays exactly as it is; the lease is released by the reclaim sweep, not there. Task 3d-i has the reasoning, and it is the third review's blocker 1.
- **Frontend changes are limited to Task 5d's four edits.** No new components, no new pages, no scope-form fields.
- **No `deck_*` MCP tools, and do not touch `mcp_shim/agent_mail_server.py`** (design §2.10d). The eight `block_code` values of Task 5b-v are required; the tools that would consume them are a separate design pass, and adding them here would implicitly settle a trust-boundary question about external agent operators. Read the shim if it helps you match the error format — do not edit it.
- Do not enable/disable autonomy, spawn or kill agent sessions, hand-edit DB rows, or restart the backend.
- Report — do not rewrite — any pre-existing failing test. `tests/test_multi_provider_smoke.py:54` is known-failing on the base branch (stale monkeypatch target); it is not yours.
- Do not run `git worktree prune`, and do not add it as a fallback when `worktree add` fails on a stale registration. It rewrites the primary's worktree metadata for every worktree. Surface the error (Task 2f).
- **Autonomy stays off after this PR merges** (design §4.1a). Deployment is the orchestrator's job, but do not write anything in the PR description implying PR A is ready to run unattended.
- **If a step looks wrong, STOP and report rather than improvising.** Twelve traps in particular, each with a soak finding or a review finding behind it: if `clean -fd` seems insufficient; if reclaiming unconditionally on escalation seems simpler; if releasing on `merged` seems obviously correct; if disabling a workspace on any git failure seems safer; if `git worktree add` seems like it should handle an existing worktree; if comparing `--git-common-dir` alone seems sufficient to identify a worktree; if `abandon` seems like it should release the lease directly; if an exception from the launcher seems like proof that nothing spawned; if `except ValueError` seems like a safe "pre-spawn only" release path; if adopting a worktree seems as safe as creating one; if catching `IntegrityError` seems like enough to reject a duplicate path; or if a prose error message seems like enough for a caller that may be an agent. All twelve are wrong, and the reasoning is in the design section each one cites.

## What changed from the thrice-reviewed draft (agent-operator pass)

Not a review finding — a design principle the three reviews and this plan had all silently dropped. Deck is operated by humans **and** by agents; the roadmap's intent is that team configuration, autonomy start, and supervision can all be delegated to a non-human operator. Checked against the code rather than assumed:

| Question | Answer |
|---|---|
| Does Deck already treat agents as operators? | **Yes, extensively.** `mcp_shim/agent_mail_server.py` exposes 18 `deck_*` tools; the Agent Team ones are the same configure-and-supervise surface these endpoints belong to (`deck_create_team`, `deck_plan_team_launch` → `deck_launch_team`, `deck_list_work_items`, `deck_retry_work_item`) |
| Did this design consider it? | **No.** `MCP` appeared twice in the design, both inside the deferred build-semaphore entry 3b (§5), and once in the plan as an async-subprocess precedent. Zero of the four new endpoints had an agent-facing contract |
| Where did the omission show? | Three arguments that only hold for humans: `reprobe`/`abandon` need no UI because they are "one `curl` away"; pool shrinkage is "a human chore"; on provisioning failure "the operator sees the git error directly and can retry" |

What that costs, concretely: the new 409s are exactly the ones an agent operator hits, and **`workspace_dirty` and `workspace_occupied` require opposite handling** — commit/stash then retry, versus simply wait and retry. Same endpoint, same status, indistinguishable in prose. So the eight `block_code` values of Task 5b-v are in this PR, using the format that already exists (`_bad_request` at `agent_teams.py:45-51` → the shim's `_http_error_result`), not a new one.

What is deliberately **not** in this PR, and why it is a question rather than a chore: MCP tools are additive over REST and settle nothing, but the natural next step runs straight into a trust boundary. `deck_list_work_items` calls `_ensure_registered()` and reads `team_preset_id` off the **caller's own membership** — it is documented "Leader-only" and returns `no_team_preset` otherwise. That models an agent inside a team acting on its own team; it cannot express an *external* supervising agent with no slot and no preset, which is the operator the roadmap wants. Whether such a caller may `abandon` an item or register a directory as an autonomous work target deserves deciding on purpose. Related and pre-existing: `autonomy_enabled` exists only on the REST scope endpoints and appears **zero** times in the shim, so delegating "turn autonomy on" is not expressible today either.

The generalisation, which is the same shape as the membership-vs-identity lesson below: **"the operator will see the error and retry" names an actor whose capabilities were never checked.** When a design's safety or recoverability argument rests on an actor, say which actor, and confirm they can actually do the thing.

## What changed from the twice-reviewed draft (third review)

The amended plan was reviewed a third time (`/tmp/dispatch-workspace-provisioning-plan-rereview-2.md`): 2 safety blockers, 3 contract inconsistencies, 1 stale instruction. **All six verified against the code before adoption**; all six were real, and two are worse than the review states.

| Third-review finding | Verified? | Resolution | Where |
|---|---|---|---|
| 1 — an exception is not proof no process exists | **yes, and the fix goes further** — the review would have kept `except ValueError` as a safe release; that handler wraps the whole `launcher(...)` call, and `PlanConflictError` *and* `pydantic.ValidationError` both subclass `ValueError`, the latter raisable post-spawn | **no** exception path releases; escalate `launch_outcome_unknown` and re-raise | Task 3d-i, design §2.3a, items 17/17c |
| 2 — adoption can register the primary as a dispatchable worktree | **yes — the most dangerous finding of all three reviews.** The primary satisfies both existing probes, and worktrees default `dispatchable=True`, so the fix for the *second* review's finding 1 reopened the *first* review's finding 1 | third probe `--git-dir` vs `--git-common-dir`, plus `path != scope.repo_path`; `kind` validated in **both** directions | Task 2f, design §2.9, items 24g/24h |
| 3 — `provision_worktree` has no `kind` parameter | yes — Task 5b said "the method decides" and did not pass the deciding input | renamed **`register_workspace(..., kind=...)`**; `_provision_worktree` kept private as the single `worktree add` call site | Task 2f, item 24k |
| 4 — adopted worktrees need dirty-tree and occupancy checks | yes; and measured — the adoption target is clean with **0** sessions while the primary has **5** | clean `status --porcelain` + no live session `cwd` on the path, before an adopted row may be dispatchable | Task 2f, design §2.9, items 24i/24j |
| 5 — duplicate paths must be checked before mutating git | **yes, and it silently orphans a worktree** — for a path in the table but missing on disk, `worktree add` succeeds, the insert then 409s, and the request *looks* correctly rejected while an unregistered worktree sits on disk forever | canonical-path `select` before any mutating git command; constraint retained for the race | Task 5b step 5, design §2.10, item 35a |
| 6 — stale "zero git calls" instruction | yes — contradicted by the probes the same task requires | reworded to zero **mutating** calls + assert the calls are exactly `rev-parse` | Task 2f, item 27 |

One review recommendation **not** adopted as written: defaulting adopted rows to `dispatchable=False` pending a separate activation action. It needs a fifth endpoint, and §7 step 2 would then register a pool with no dispatchable workspaces — a rollout that appears to succeed and dispatches nothing. Validating at adoption keeps the staged case available to anyone who passes `dispatchable=false` explicitly.

The finding worth generalising is 2, because it is the third time this plan has made the same class of error: **a check that proves a path belongs to the repo, trusted to prove what the path is.** Membership is not identity. The `--git-common-dir` check answered "is this in the repo?" for both the second review's foreign-repo case and this one, and only the second needed a different question. When a validator's output is used to make a *safety* decision, state which question it answers and check that it is the question being asked.

## What changed from the re-reviewed draft (second review)

The revised plan was reviewed again (`/tmp/dispatch-workspace-provisioning-plan-rereview.md`), which found four remaining issues plus a contract clarification. **All five were independently verified against the code before being adopted** — none was taken on trust, and two of the review's own proposed fixes turned out to need correcting.

| Re-review finding | Verified? | Resolution | Where |
|---|---|---|---|
| 1 — `issue-818` cannot be registered; `worktree add` rejects an existing worktree | **yes**, exit 128 reproduced, and on the real target | adoption path with identity probes; primary validated too (a third probe was added by the next review — see above) | Task 2f, design §2.9 |
| 2 — a disabled workspace has no repair path | **yes**, traced five composing decisions into an inescapable state | `POST .../workspaces/{id}/reprobe`, re-enables only on success | Task 5b-iii, design §2.10a |
| 3 — `launched` is not a real status | **yes**, success is `pending_registration` (`agent_team_service.py:631`) | positive status list + fail-closed default + `tmux_target` veto | Task 3d |
| 4 — PR A cannot recover an abandoned `ready_for_review` item | **yes, doubly** — the watcher also skips any item with a `pr_number`, so adding the status alone would not have helped | `POST .../github-work-items/{id}/abandon` **and** an explicit autonomy-off gate | Task 5b-iv, design §2.10b, §4.1a, §4.2 |
| contract — `enabled`/`dispatchable` exposed but not accepted | **yes**, `provision_worktree(db, scope, path)` took neither | both are keyword-only params of `register_workspace`; endpoint resolves defaults and passes them | Tasks 2f, 5b step 4 |

Three things found while verifying, which the reviews did not raise and which the plan now carries:

- **`--git-common-dir` is relative when run from the primary.** The review's proposed fix ("verify `--git-common-dir` matches `scope.repo_path`") compared a relative `.git` against an absolute path and would have rejected every adoption. `--path-format=absolute` is required.
- **A nested subdirectory of a worktree reports the same `--git-common-dir`**, so the review's single-condition check would have registered `ws1/sub` as an independent workspace — two rows for one physical tree, which is the exact defect the global path constraint exists to prevent. `--show-toplevel` equality closes it.
- **The existing `dispatch_status` branch is fail-open** (`else → "dispatched"`, `github_dispatch_service.py:250-262`): an unrecognised launch status is recorded as a successful dispatch. Left unchanged (Phase G2 owns it), but the new release branch deliberately fails *closed*, and Task 3d says why the disagreement is safe in that direction.

Two review recommendations were **not** adopted as written:

- The review offered "do not deploy autonomy with PR A alone" **or** "add an operator cancel action" as alternatives. Both are in: the endpoint, because a wedge needs a supported exit; and the gate, because an endpoint an operator must remember to press is not a substitute for not running unattended.
- "Define duplicate POST on a disabled row as an explicit repair operation" was rejected in favour of a named `reprobe` action. Overloading `POST` would make the same request mean "create" or "repair" depending on hidden state, and the 409 that currently protects the path constraint would become ambiguous.

## What changed from the first reviewed draft

For the reviewer's benefit, and so nothing silently reverts. First-review findings 1, 3, 4, 5, 8, 10, 11 are resolved here; 2 is deferred to PR B by decision; **9 is now partly resolved** (the operator can clear an abandoned item via `abandon`; automatic detection stays PR B); 6 was already fixed pre-review; 7 is resolved in Task 2e.

| Review finding | Resolution | Where |
|---|---|---|
| 1 — primary wins first dispatch | `dispatchable` column; `acquire` filters on it; registration defaults primary to `False` | Tasks 1, 2b, 5b |
| 2 — release while tmux alive | **no terminal release at all in PR A**; reclaim is the only status-driven releaser | Task 4 |
| 3 — per-scope path uniqueness | `UniqueConstraint("path")` global + `normalize_repo_path` before insert | Tasks 1, 5b |
| 4 — reset order fails on dirty tree | `switch --detach --force` + `reset --hard <base_ref>` | Task 2e |
| 5 — unbounded disk via per-issue build dirs | `build_dir_template` defaults to `"build"`; deployment no longer sets a per-issue template | Task 1, design §7 |
| 6 — no way to operate the pool | four endpoints (two predated the review; the reviewed copy was stale) | Task 5b |
| 7 — transient fetch drains the pool | `fetch` failure does not disable; timeout + `GIT_TERMINAL_PROMPT=0`; success clears `provision_error` | Tasks 2a, 2b, 2e |
| 8 — only `ValueError` releases | release on returned `failed`/`blocked*` and on unexpected exceptions | Task 3d |
| 9 — closed-unmerged PR holds a lease | *automatic* detection deferred to PR B; the operator can clear it with `abandon`. **The earlier "retry or manual issue closure" escape hatch was false** and is withdrawn | Task 5b-iv, design §4.2 |
| 10 — provisioning-failure contradiction | `worktree add` failure persists **no row** and surfaces the git error; `provision_error` is reset-only | Task 2f |
| 11 — template errors miss `ValueError` | catch `(KeyError, IndexError, ValueError)`; validate at scope write time | Tasks 3f, 5a |
