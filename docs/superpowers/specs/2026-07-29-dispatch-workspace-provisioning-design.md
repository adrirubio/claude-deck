# Dispatch workspace provisioning design (Finding 16)

**Status:** design, ready to implement
**Found by:** tizonia soak, 2026-07-28 (see `2026-07-06-tizonia-roadmap-v1-soak-run-log.md`, **Finding 16**)
**Scope:** new `github_workspaces` table + lease; worktree provisioning; per-scope build hints
**Depends on:** nothing. Independent of G1c (`2026-07-28-sweep-request-budget-design.md`), which touches only the watcher.
**Blocks:** resuming dispatch on tizonia. Every `agent-ready` issue is currently stalled behind this.

---

## 1. The problem

Deck has **no workspace provisioning of any kind**. `grep -rn worktree app/services/github_*` returns nothing.

The dispatch brief offers exactly one line about where to work (`github_dispatch_service.py:299`):

```python
f"- Local checkout: {scope.repo_path}",
```

and the launcher passes that same single path as the session's cwd (`github_dispatch_service.py:240`):

```python
repo_path_override=scope.repo_path,
```

So **every dispatched agent, for every issue, is pointed at one shared directory** — in the live soak, `/home/juan/work/repos/tizonia/tizonia-openmax-il`. That directory is also the human's working checkout, currently sitting on `codex/issue-819-remove-libspotify` with 2.4 GB of build output in it.

Two agents in there at once means two agents sharing one `HEAD`, one index, one working tree. `git switch` in one yanks the source files out from under a compile in the other. This is Finding 10 (duplicate owner on #819) restated as a physical fact rather than a status-machine bug.

### 1.1 The phantom contract

During the #818 recovery a human (the orchestrator) created a worktree by hand:

```
/home/juan/work/repos/tizonia/tizonia-openmax-il-issue-818   3da181ef [codex/issue-818-remove-gmusic-v2]
```

The agents saw an isolated per-issue worktree, correctly inferred that this was the working contract, and now **refuse to write without one**. They are right to refuse. But nothing in Deck ever promised them a worktree, and nothing in Deck creates one. An underspecified brief plus one hand-made artefact produced a self-sustaining policy that Deck cannot satisfy.

This is the deepest lesson in the finding: **the brief is an API.** An omission in it does not read as "unspecified" to a competent agent — it reads as an invitation to infer, and the inference sticks.

### 1.2 Why `max_concurrent_dispatched=1` is hiding this

`max_concurrent_dispatched` was set to 1 for RAM reasons (Finding 11, OOM). It happens to also serialize checkout access, which is why the collision has surfaced only once. **That is accidental correctness.** Raise the cap for throughput and the collision returns immediately, with no error message — just a corrupted build or a lost commit.

### 1.3 The unifying defect

Findings 10, 11, 13, 15 and 16 are one defect wearing five hats:

> **Deck models logical work and ignores physical resources.**

Corollary, and the reason status bugs keep becoming outages: **capacity is inferred from status**, so any status bug is automatically a capacity bug.

Finding 16 is the last and largest of the physical resources: the checkout itself.

---

## 2. Design

### 2.1 A workspace is a leased, pooled, long-lived directory

Three properties, each load-bearing:

- **Leased** — at most one work item may hold a workspace at a time, enforced in the database, not by convention.
- **Pooled** — a fixed set of workspaces per scope, reused across items. *Not* created and destroyed per issue.
- **Long-lived** — never deleted by Deck.

Pooling is what makes this affordable. A built tizonia worktree is ~2.4 GB, of which 1.1 GB is the Meson build directory. Creating a worktree per issue means a from-scratch C++ build every single time — the most expensive thing on this host, and the thing that OOM'd it. Reusing a warm workspace preserves the build directory and `ccache`, so the second issue through a workspace compiles incrementally.

It also bounds the number of *checkouts*: a pool of N is N, known in advance, where per-item creation is unbounded.

**It does not by itself bound disk, and an earlier draft of this section wrongly claimed it did.** `git clean -fd` deliberately preserves ignored directories (§2.6), which is what keeps build caches warm — so anything the build system leaves behind accumulates *inside* a fixed workspace and is never collected. Pairing a fixed pool with a per-issue `build_dir_template` like `build-issue-{issue_number}` therefore bounds the directory count while leaving disk unbounded: every issue through a workspace deposits another ~1.1 GB that nothing will ever delete.

The live soak already demonstrates this, measured rather than predicted:

```
1.1G  tizonia-openmax-il/build-issue-820
1.1G  tizonia-openmax-il/build.pre-issue-820-verification
1.1G  tizonia-openmax-il-issue-818/build-compat
126M  tizonia-openmax-il/build-soundcloud
116M  tizonia-openmax-il/build-soundcloud-audit
 34M  tizonia-openmax-il-issue-818/build
 13M  tizonia-openmax-il/build-core
5.5M  tizonia-openmax-il/build
                                    → 3.5 GB across 2 checkouts
```

So the build directory must be **stable per workspace**, not per issue: `build_dir_template` defaults to a constant (`"build"`) and per-issue templating is the exception, not the recommendation. The lease already serialises access to a workspace, so a single build dir has no concurrency problem — and reusing it is what makes the incremental build fast, which was the point of pooling. Disk then really is bounded at N × (repo + one build dir), ~2.4 GB per workspace for tizonia.

`{issue_number}` remains available for repos that genuinely need per-issue build isolation, but choosing it is choosing unbounded growth, and §7 no longer sets it on scope 1.

### 2.2 Schema — `github_workspaces`

```python
class GithubWorkspace(Base):
    """A checkout a dispatched work item may exclusively occupy."""

    __tablename__ = "github_workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("team_github_scopes.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    path: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, default="worktree", nullable=False)
    dispatchable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    leased_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("github_work_items.id", ondelete="SET NULL"), nullable=True
    )
    leased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provision_error: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("path", name="uix_workspace_path"),
        UniqueConstraint("leased_item_id", name="uix_workspace_leased_item"),
    )
```

**There is deliberately no `lease_state` column.** State is derived, so it cannot contradict itself:

| Derived state | Condition |
|---|---|
| available | `enabled` AND `dispatchable` AND `leased_item_id IS NULL` |
| leased | `leased_item_id IS NOT NULL` |
| disabled | NOT `enabled` — broken tree |
| disabled_for_dispatch | `enabled` AND NOT `dispatchable` — healthy but reserved, e.g. the primary |

`UniqueConstraint("leased_item_id")` is the important one. SQLite permits many NULLs in a unique index but only one non-NULL of each value, so this constraint means **one item can hold at most one workspace and one workspace can hold at most one item, enforced by the database**. Finding 10 was a duplicate-owner bug that got through because the invariant lived only in query logic. This time it lives in the schema.

`UniqueConstraint("path")` is **global, not `(scope_id, path)`.** An earlier draft scoped it per scope, which does not protect the resource it is meant to protect: a lease is an exclusivity claim on a *physical directory*, so the same path registered under scope A and scope B yields two rows that each believe they own it exclusively, and each would reset it out from under the other. The constraint must live at the same granularity as the thing being protected. Paths are canonicalised through `agent_team_service.normalize_repo_path` before insert (§2.10), which calls `os.path.realpath` — so symlink aliases and `~` forms collapse to one string before the constraint sees them.

`dispatchable` exists because of `kind="primary"`. `acquire` picks the oldest available workspace by `id`, and the deployment plan registers the primary checkout first — so the primary would take the lowest `id` and **win the very first dispatch**, putting an autonomous agent straight into the human's shared checkout. That is the exact behaviour this whole design exists to eliminate, reintroduced by the ordering rule. Registration therefore defaults `kind="primary"` rows to `dispatchable=False`, and `acquire` filters on `dispatchable.is_(True)`.

The flag is separate from `enabled` because they mean different things: `enabled=False` is "broken, do not use," while `dispatchable=False` is "healthy, visible, deliberately not for autonomous work." Collapsing them would make a deliberately-reserved primary indistinguishable from a workspace whose `git fetch` failed.

`kind` takes `"primary"` or `"worktree"` and is validated on write — an unconstrained string is unsafe here, because `reset_workspace`'s entire safety property is a `kind == "primary"` equality test and a typo'd `"Primary"` would silently make Deck `reset --hard` the human's checkout.

### 2.3 Where the lease is taken

`dispatch_pending` (`github_dispatch_service.py:174-212`) already walks a five-gate ladder per pending item:

1. repo concurrency cap
2. available memory
3. routing resolves an owner slot
4. slot not busy
5. slot has no live owner session

Workspace acquisition becomes **gate 6, last**. Ordering matters: acquiring earlier would burn a workspace on an item that then fails a later gate, and the release path for that is easy to get wrong. Last means acquisition and use are adjacent.

```python
workspace = await workspace_service.acquire(db, scope, item)
if workspace is None:
    item.owner_slot_id = owner_slot_id
    item.routing_method = method
    item.pending_reason = "queued_no_workspace"
    item.updated_at = datetime.utcnow()
    await db.commit()
    continue
```

`pending_reason="queued_no_workspace"` follows the existing vocabulary (`queued_repo_cap`, `queued_low_memory`, `queued_slot_busy`, `queued_owner_session_live`) and is a *reason string*, not a new `dispatch_status`. No new statuses.

The acquired path then replaces the scope path in both places it is used:

```python
repo_path_override=workspace.path,     # was scope.repo_path
```

and the brief is built from `workspace`, not `scope` (§2.7).

**Launch failure must release, and `ValueError` is not the common shape.** An earlier draft released only in the existing `except ValueError:` branch (`:244`) that escalates `plan_blocked`. That misses the ordinary case: `agent_team_service._launch_slot` wraps spawning in `except Exception` and **returns** `AgentTeamLaunchResultItem(status="failed")` rather than raising (`agent_team_service.py:638-648`), and dispatch handles that by setting `dispatch_status="failed"` with no release (`github_dispatch_service.py:250-262`). So the most likely real failure — tmux or the provider CLI refusing to start — leaks the lease until a reclaim sweep, and can leak it indefinitely if the half-started session makes the slot-scoped liveness predicate true.

Release on every outcome where no usable session was established:

| Outcome | Where | Release? |
|---|---|---|
| `ValueError` raised | `except ValueError` → `plan_blocked` | yes |
| returned `status="failed"` | `:250-262` → `dispatch_status="failed"` | **yes** |
| returned `status="blocked"` / `blocked_provider_unavailable` / `blocked_agent_mail_not_configured` | same block | **yes** |
| any other exception | no handler today | release, then re-raise |
| returned `status="pending_registration"` | **the success path** | no |
| returned `status="reused"` | a session was reused | no |
| any status not listed above | unknown | **no — fail closed** |

In all releasing cases the session never took, so nothing is in the directory and the reset-on-next-acquire is safe.

The success row matters more than it looks. An earlier draft of this table wrote `status="launched"`, which **does not exist** — `_execute_plan_item` returns `pending_registration` (`agent_team_service.py:631`), and the full vocabulary is a `Literal` at `schemas.py:2039-2050`. An implementation matching the table literally would find no match on the real success status, fall into its unknown branch, and release a workspace under a session that had just spawned. So the condition must be a **positive list of failure statuses with a fail-closed default**, not a negation of a success status.

Two reinforcing reasons for the fail-closed default. `"spawned"` is declared in that `Literal` with no producer anywhere, so an unrecognised status is a live possibility rather than a hypothetical. And the asymmetry is decisive: retaining wrongly costs latency and reclaim collects it later anyway, while releasing wrongly resets a directory under a live agent. As a second signal, a result item carrying a non-`None` `tmux_target` (`schemas.py:2297`) is direct evidence a session exists and must veto release regardless of status.

Note for anyone reading the surrounding code: dispatch's own `dispatch_status` branch is **fail-open** — its `else` sets `dispatch_status="dispatched"` (`:250-262`), so an unknown status is recorded as a successful dispatch. That is left alone (Phase G2 owns the launch path) and it is safe in that direction, because an item wrongly marked `dispatched` *keeps* its lease. The release branch must not copy that shape.

### 2.4 Where the lease is released

The lease must survive as long as an agent might still write to the directory. Tracing the status machine:

- `dispatched` — agent is editing. Needs it.
- `verifying` — CI is running, but `_record_failed_verification_attempt` sends the item **back to `dispatched`** (`github_verification_service.py:477,505`) so the agent can push a fix. Needs it.
- `ready_for_review` — `record_approval_round` exists precisely because reviewers request changes and the agent revises. Needs it.
- `merged` / `completed` — done. Release.
- `failed` / `escalated` — ambiguous. See below.

An earlier draft concluded from this that `merged` and `completed` were safe points for an **unconditional** release. That was wrong, and it was wrong for the reason this whole finding is about: it reasoned from *logical* state and ignored the *physical* process.

Deck launches agents with `tmux new-session -d` (`agent_bridge/spawn.py:78-84`) — a detached, persistent interactive CLI. **Merging a PR does not terminate it.** Neither does closing the issue. The tmux session keeps running, can still receive input, and can still write files. So releasing on `merged` hands the directory to the next item, whose `acquire` then runs `reset --hard` and `clean -fd` underneath a live process. `_complete_and_notify` is worse: a human closing an issue manually marks the item `completed` while its agent is mid-edit.

That is Finding 10's mechanism — two owners on one directory — recreated through the release path instead of the dispatch path.

**Resolution: this design ships with NO release on terminal status at all.** Capacity is freed by the reclaim sweep (§2.5), which is gated on observed process liveness rather than on status. One mechanism, one gate, physically grounded.

| Call site | Releases? | Why |
|---|---|---|
| `_mark_merged` | **no** | the agent's tmux session outlives the merge |
| `_complete_and_notify` | **no** | a human can close an issue mid-edit |
| `reset_for_retry` | no | retry keeps its lease so the build dir stays warm |
| `escalate` / `_apply_escalation` | no | escalation does not mean the agent stopped |
| operator `abandon` (§2.10b) | **no** | an HTTP request is not evidence about a process |
| launch failure, before any session exists | **yes** | nothing is in the directory (§2.3) |
| reclaim sweep | **yes** | the only status-driven releaser; gated on liveness |

The launch-failure release is not an exception to the rule — it is the same rule. The rule is *never release while a process might be writing*; a launch that failed produced no process. Every release in this design is licensed by a physical fact, never by a status.

The `abandon` row is worth reading twice, because "the operator said so" is the most tempting exception of all. An operator clicking abandon knows the item should stop; they do **not** know whether its tmux session is still alive, and neither does the HTTP handler. So `abandon` sets a status and reclaim's liveness gate still decides. This keeps the number of releasers at exactly two — launch failure and reclaim — no matter how many lifecycle actions get added later.

The launch-failure release also needs the *right* success status to fall through on: `_execute_plan_item` returns `status="pending_registration"` on success (`agent_team_service.py:631`), and there is no `"launched"`. A release condition matching an invented status would release under a session that had just spawned, so the condition is a positive list of failure statuses with a fail-closed default (§6, items 17a/17b).

The cost is latency: a merged item holds its workspace until its session goes offline, so with only one dispatchable workspace at rollout (§7) the pool can *look* stuck while it is merely waiting. That is the correct direction to be wrong in — a lease held too long costs throughput, a lease released too early corrupts a working tree. It is also observable, which is what §2.10's `GET .../workspaces` is for.

Prompt release on terminal status is deferred to a follow-up (**PR B**), because doing it safely needs *per-item* liveness — `MailAgentSession` joined through `item.launch_id` — and the existing predicate is slot-scoped, so it can be held true by an unrelated session on the same slot. Phase G2 (Finding 13) is already scheduled to rewrite that predicate; building a second one now would leave two similarly-named liveness checks to reconcile. See §4.

The reclaim sweep therefore carries the entire release burden, which makes it the subtle part.

### 2.5 Reclaim — why escalation must not release unconditionally

Escalation does **not** mean the agent stopped. `_send_escalation_broadcast` already carries an `owner_may_be_active` flag and warns the team in prose:

```
- NOTE: this item's owner session may still be working. Do NOT
  retry it — retrying clears any PR it has opened.
```

Releasing a lease on escalation would hand the directory to a second item while a live agent is still editing it. That is Finding 10 reproduced by the very mechanism meant to prevent it.

But never releasing is equally fatal: the soak currently holds **11 escalated items** (#821-#829, #834, #858). Eleven permanently-held leases against a one- or two-workspace pool is a permanent wedge — and a wedge is exactly how Finding 14 masked Finding 15 for a week.

The resolution is to release on the *physical* condition rather than the *logical* one:

> A lease is reclaimable **iff its item is in a non-working status AND the owner slot has no live session.**

Non-working statuses are `escalated`, `failed`, `merged` and `completed` — the last two arriving here rather than releasing promptly, per §2.4. `dispatched`, `verifying`, `ready_for_review` and `awaiting_human_review` are never reclaimed, because in all four an agent is legitimately expected to still be working.

That last exclusion has a consequence that must not be closed by widening this list: an item stuck in `ready_for_review` behind a PR nobody will merge is never reclaimed, and PR A has no automatic detection for it (§4.2). The exit is `abandon` (§2.10b), which moves the item to `escalated` — a status this list *does* cover — and then lets the liveness gate release it as usual. Adding `ready_for_review` here instead would reclaim workspaces from reviews that are legitimately in progress.

Deck already computes this: `slot_has_live_owner_session(db, slot_id)` (`github_dispatch_service.py:106-130`). Reusing it means the reclaim rule is grounded in an observed tmux/heartbeat fact, not a guess. No human intervention, no wedge — and it cannot steal a directory from a running agent.

**Known imprecision, deliberately accepted.** The predicate is keyed on `slot_id`, not on the item's own launch, so an unrelated live session on the same slot keeps a lease held longer than strictly necessary. It errs toward retention, which is the safe direction, and the fix (per-item liveness via `item.launch_id`) belongs with PR B and Phase G2 rather than here (§2.4).

Run the sweep once at the top of `dispatch_pending`, before `scope_active_count`. `dispatch_pending` is the only consumer of workspace capacity and runs every poll, so that is the one place capacity must be accurate.

**Retry keeps its lease.** `reset_for_retry` must *not* release. The same item returning to `pending` should get the same workspace back — its build directory is warm, which on this host is worth more than any scheduling flexibility. The `UniqueConstraint` makes re-acquisition a no-op for an item that still holds one.

> **Coupling to note:** Phase G2 (Finding 13) plans to *delete* `slot_has_live_owner_session`. The reclaim rule depends on it. G2 must therefore either keep a liveness predicate under some name, or replace this rule. Flagged here so G2 does not silently remove the only thing preventing a workspace wedge.

### 2.6 The primary checkout is special and must never be reset

`scope.repo_path` is the human's checkout. It has their branch checked out, their build dirs, possibly their uncommitted work. Deck may lease it — but Deck must **never** clean or reset it.

Worktrees, by contrast, must be reset on acquisition, or each item inherits the previous item's mess.

Hence `kind`:

| `kind` | Deck may reset? | Notes |
|---|---|---|
| `primary` | **never** | the human's checkout; leasable so Deck at least knows it is occupied |
| `worktree` | yes, on acquire | Deck created it and owns its contents |

The reset-on-acquire sequence, and one hazard:

```bash
git -C <ws> fetch origin --prune
git -C <ws> switch --detach --force <base_ref>
git -C <ws> reset --hard <base_ref>
git -C <ws> clean -fd          # NOT -fdx
```

**`--force` on the switch, and an explicit ref on the reset, are both required.** An earlier draft omitted them and the sequence aborted on the very case reclaim exists to handle. Verified empirically:

```
$ git switch --detach origin/main          # dirty tracked file present
error: Your local changes to the following files would be overwritten by checkout:
        f.txt
Aborting                                    # exit 1
```

Step 2 fails, so `reset --hard` at step 3 is never reached and the workspace is handed over still dirty — or, with the plan's error handling, disabled. A `failed`/`escalated` item is *precisely* the case most likely to leave tracked modifications behind, so the sequence broke exactly where it was needed. Re-verified with the fix: `switch --detach --force` succeeds, the tree lands clean at the base ref, and a `build/` directory containing a self-ignoring `.gitignore` **survives** — the `-fd`/`-fdx` invariant below still holds.

`reset --hard <base_ref>` rather than bare `reset --hard` because after a forced detach the two are equivalent only if the switch fully succeeded; naming the ref makes the post-condition explicit rather than positional.

**`-x` is forbidden.** `git clean -fd` removes untracked files but leaves *ignored* ones. Meson build directories are self-ignoring — each contains a `.gitignore` holding `*`, which is why `git check-ignore -v build/` reports `build/.gitignore:2:*`. So plain `clean -fd` preserves the 1.1 GB build dir and the incremental-build win; `clean -fdx` would delete it and reintroduce the from-scratch compile that OOM'd the host. The flag difference is the difference between a 90-second build and a 40-minute one.

`--detach` rather than a branch is deliberate. Git refuses to check the same branch out in two worktrees — a genuinely useful safety property, but it breaks the moment Deck has to *guess* the agent's branch name, and Deck cannot know it (`codex/issue-819-remove-libspotify` is the agent's convention, not Deck's). Detached HEAD at a base ref lets the agent run its own `git switch -c` and keeps naming entirely on the agent's side of the interface.

`base_ref` is new scope config, defaulting to `origin/HEAD`. Dependent/stacked work is explicitly out of scope: the leader already sequences via the dependency map, so blockers merge before dependents dispatch, so `origin/HEAD` is the correct base.

### 2.7 The brief must stop lying by omission

Replace the single `- Local checkout:` line with an explicit statement of the contract. The purpose is to kill the phantom contract by making the real one unambiguous — including, crucially, what the agent must *not* do.

```
- Workspace: /home/juan/work/repos/tizonia/tizonia-openmax-il-ws1
- This workspace is leased exclusively to this work item. No other dispatched
  agent will be working in it.
- It is a git worktree on a detached HEAD at origin/HEAD. Create your own
  branch with `git switch -c <branch>` before committing.
- Do NOT create, move or remove git worktrees yourself. Claude Deck provisions
  the workspace; you work inside the one you were given.
- Do NOT work in any other checkout of this repository.
```

For `kind == "primary"` the second and third lines change to say the workspace is a shared human checkout, that its current branch is not Deck's to change, and that the agent must confirm with the leader before switching branches.

### 2.8 Step 3a — build hints as per-scope config

Deck does not run builds; agents do. So Deck's contribution is to *tell* the agent the host's constraints, in the brief. Four new scope columns:

| Column | Default | Purpose |
|---|---|---|
| `builds_out_of_tree` | `False` | whether two builds can share one checkout |
| `build_dir_template` | `"build"` | stable per workspace; `{issue_number}` available but discouraged (§2.1) |
| `build_command_hint` | `None` | e.g. `meson compile -C {build_dir} -j{parallelism}` |
| `max_build_parallelism` | `4` | the `-j` cap |

`max_build_parallelism=4` is the single highest-value number in this document. `ninja` defaults to `-j$(nproc)+2` = **`-j18`** on this 16-core host, and `cc1plus` on tizonia's C++ peaks around 1 GB. 18 × 1 GB against 15.6 GB of RAM means **one build can OOM this host by itself.** `max_concurrent_dispatched=1` therefore never fixed Finding 11 — it reduced exposure roughly 3× when the real multiplier was 18 × 3. The `-j` cap addresses the actual multiplier.

`builds_out_of_tree` defaults to `False` — the conservative answer — because getting it wrong in the unsafe direction corrupts a build with no error message, while getting it wrong in the safe direction only costs throughput.

| Build system | Out-of-tree | Two builds, one checkout? |
|---|---|---|
| Meson, CMake, Bazel, Cargo (`--target-dir`), Gradle | yes | safe — `-C build-A` / `-C build-B` |
| Autotools in-source (`./configure && make` at top level) | no | **corrupts** — `.o`, `.lo`, `.deps`, `config.h` land in source |
| plain `make` in-tree | no | corrupts |
| npm `node_modules`, Python `build/`, `setup.py` | partial | frequently collides |

tizonia ships **both** `configure.ac`/`Makefile.am` *and* `meson.build`, so even one repo is either, depending on which path the agent takes. Deck cannot infer this. It is config.

The flag changes what a lease has to *cover*, not whether leases are needed:

- out-of-tree → the lease covers **edits and branch state**; builds are exempt, so concurrent compiles in one workspace are safe
- in-tree → the lease covers **everything**, because a build mutates the tree; even a read-only reviewer cannot compile while the owner edits

**3a is advisory, not enforced.** These values reach the agent as brief text. An agent that ignores `-j4` still OOMs the host. Enforcement is 3b (§3).

Templates are **operator-supplied strings passed to `str.format`**, so rendering must be defensive. An earlier draft caught `KeyError`/`IndexError`; that is insufficient, verified directly:

```
'build-{issue_number}'    → 'build-819'
'build-{issue_number'     → ValueError: expected '}' before end of string
'build-{0}'               → IndexError
'build-{bogus}'           → KeyError
'build-{issue_number!z}'  → ValueError: Unknown conversion specifier z
```

An unmatched brace — the single most likely typo — raises `ValueError` and would propagate out of `_dispatch_brief` into the poll loop, taking down autonomy for the whole scope. So: catch `(KeyError, IndexError, ValueError)`, log, and omit the build lines. Validate templates at scope create/update time as well, so the operator learns at write time rather than at dispatch time. Allowed placeholders are exactly `{issue_number}` for `build_dir_template` and `{build_dir}` / `{parallelism}` for `build_command_hint`.

Define the degenerate combination explicitly: `builds_out_of_tree=True` with a `build_command_hint` but no `build_dir_template` renders `{build_dir}` as the default `"build"` rather than silently omitting the command.

### 2.9 Registration: provision **or adopt**

Registering a workspace has two cases, and an earlier draft of this design only had one. `git worktree add` **fails** when the path is already a worktree — verified, exit 128:

```
$ git worktree add --detach ../ws1 HEAD
Preparing worktree (detached HEAD 35ca9e2)
fatal: '../ws1' already exists
```

§7 step 2 registers the *existing* `tizonia-openmax-il-issue-818`, so with provisioning as the only path **the documented rollout could not have succeeded.** Registration must therefore probe first and adopt an existing valid worktree without touching it.

| Path state | Action |
|---|---|
| does not exist | `git worktree add --detach <path> <base_ref>` |
| exists, empty directory | `git worktree add` — accepted by git, verified exit 0 |
| exists, is a worktree of **this** repo, at its root | **adopt** — register the row, run no `worktree add` |
| exists, is a worktree/clone of another repo | reject |
| exists, is a subdirectory of a worktree | reject |
| exists, not a git tree at all | reject |

"A worktree of this repo, at its root" is two conditions and both are load-bearing:

```bash
git -C <path> rev-parse --path-format=absolute --git-common-dir   # == scope's common dir
git -C <path> rev-parse --show-toplevel                           # == <path>
```

Two traps found while verifying this, both of which would have made a single-condition check wrong:

- **`--git-common-dir` is relative when run from the primary** — it returns `.git`, not an absolute path. Without `--path-format=absolute` on both sides the comparison never matches and every adoption is rejected.
- **A nested subdirectory of a worktree reports the same common dir.** So a common-dir-only check would happily register `ws1/sub` as an independent workspace: two rows, one physical tree — the precise defect §2.2's global `UniqueConstraint("path")` exists to prevent, reintroduced through the validator. `--show-toplevel` equality is what closes it.

The same repo-identity check applies to `kind="primary"`. Canonicalising a path (§2.10) proves *directory* identity, not *repository* membership; without the check an unrelated repo could be registered as this scope's primary and silently accepted. `rev-parse` is read-only, so this does not violate "Deck issues no commands against the primary" — that rule is about **mutation**, and it should be written that way wherever it is asserted, including in the tests.

Deck does **not** run `git worktree prune` automatically. A stale registration (a worktree whose directory was deleted) makes `worktree add` fail with an error that names the problem and the remedy; surface it. `prune` rewrites the primary's worktree metadata for every worktree, and the primary is not Deck's to mutate.

### 2.9a Provisioning failure, and why a fetch failure must not disable a workspace

Two failure modes look alike and must not be treated alike:

| Failure | Meaning | Correct response |
|---|---|---|
| `git fetch` fails | transient — network, DNS, auth, GitHub outage | record, leave enabled, retry next poll |
| `switch` / `reset` / `clean` fails | the working tree is broken | disable, record `provision_error` |

An earlier draft disabled the workspace on *any* reset failure. Since reset runs on acquire and acquire walks the pool oldest-first, a single network blip during `fetch` would disable one workspace per poll until the pool was empty — converting a transient outage into a permanent autonomy wedge with no way back, because nothing clears `provision_error` and nothing re-enables a row. The failure mode is worse than the one it guards against.

So `fetch` failure is **non-fatal**: record it in `provision_error`, leave `enabled=True`, return `None` from `acquire` so the item queues as `queued_no_workspace`, and try again next poll. Only local tree operations disable. A successful reset clears `provision_error`, so a recovered workspace heals itself without operator action.

Two more properties of the git runner, both absent from the earlier draft:

- **A timeout.** `git fetch` against an unreachable host can block indefinitely, and this runs inside the APScheduler event loop.
- **`GIT_TERMINAL_PROMPT=0`** (and `GIT_ASKPASS=`/`SSH_ASKPASS=`). Without it a credential prompt makes the subprocess wait forever for input that will never come — indistinguishable from a hang.

`provision_worktree` has an ordering subtlety worth stating, because it is the one place the earlier test obligations contradicted themselves: `git worktree add` runs **before** any row exists, so a failure there has nowhere to record `provision_error`. Resolution: the API surfaces that failure to the caller as an error response and persists **no row**. Registration is a synchronous operator action, so the operator sees the git error directly and can retry — which is better than a disabled row they must then discover and clean up. `provision_error` is therefore only ever written for *reset* failures on an existing row.

### 2.10 API surface — four new endpoints, and why the "no new endpoints" habit had to go

Earlier plans in this series carried a blanket **"NO new endpoint"** line. It was earned on 2026-07-23, where a suitable endpoint already existed and adding one would have been duplication, and it was defensible on 07-26 for three guards inside a single service. It was then copy-forwarded without being re-derived. For this change it is not merely unnecessary — it is incoherent:

- `provision_worktree` (§2.6) with no endpoint is a service method **with no caller**. It is reachable only from a Python REPL against the live database.
- §7 step 2 requires registering scope 1's workspaces. With no endpoint, "operator action" resolves to hand-writing `INSERT` statements — which violates the standing, well-founded constraint that DB rows are never hand-edited. Hand-edited state is state the code never produced, so it drifts from what the code *can* produce and every later diagnosis is against a fiction.
- The design's whole premise is that Deck must stop inferring physical capacity from logical status. Shipping a workspace table with no way to read it means the **operator** keeps making exactly that inference. That coupling is what turned Findings 10, 11, 13 and 14 each from a status bug into a capacity bug.

So this change adds four endpoints, all scoped to workspaces:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/agent-teams/github-scopes/{scope_id}/workspaces` | list the pool with derived lease state |
| `POST` | `/api/v1/agent-teams/github-scopes/{scope_id}/workspaces` | register a workspace: provision via `git worktree add`, or **adopt** an existing valid worktree (§2.9); `kind="primary"` registers an existing path without mutating it |
| `POST` | `.../workspaces/{workspace_id}/reprobe` | **repair** a disabled workspace: re-run reset, re-enable only on success |
| `POST` | `.../github-work-items/{item_id}/abandon` | **operator release**: move a wedged item to a non-working status so reclaim can free its lease |

The last two exist because the first two are not sufficient to *operate* the pool, and each closes a deadlock found on re-review. They are argued for individually below.

`DELETE` is deliberately **absent**. §5 already forbids Deck removing worktrees, and a delete endpoint whose lease-holder check was wrong would silently orphan a running agent's directory. Pool shrinkage is a human chore, as with the stale build dirs.

#### 2.10a `reprobe` — a disabled workspace can currently never come back

A local tree failure (`switch`/`reset`/`clean`) sets `enabled=False` (§2.9a). Trace what happens next and there is no path out:

- `acquire` filters `enabled.is_(True)`, so the row is never selected again;
- reset only runs from `acquire`, so it never re-runs;
- `provision_error` is only cleared by a successful reset, so it never clears;
- `POST .../workspaces` on the same canonical path hits the global `UniqueConstraint("path")` → 409;
- there is no `PATCH` and no `DELETE`.

The row is therefore **permanently** dead, and on a size-1 dispatchable pool that means autonomy is permanently dead, recoverable only by hand-editing the database — which is exactly what the standing constraints forbid. §2.9a's careful separation of transient from local failure was built to avoid a permanent wedge, and then the local branch reintroduced one.

`POST .../workspaces/{id}/reprobe` runs the §2.9 identity probes and the §2.6 reset sequence against the row, then:

| Outcome | `enabled` | `provision_error` | Response |
|---|---|---|---|
| reset succeeds | set `True` | cleared | 200, the row |
| reset fails again | stays `False` | overwritten with the new error | 409 with the git output |
| the row is currently leased | untouched | untouched | 409 — never reset under a lease |
| `kind="primary"` | untouched | untouched | 409 — the primary is never reset (§2.6) |

Two properties matter. It **re-enables only on success**, so it is a probe rather than an override — an operator cannot flip a broken tree back into the pool by asserting it is fine. And it **refuses while leased**, because reprobe *is* the reset sequence and running it under a live agent is the very collision this design exists to prevent. That makes it strictly narrower than a general `PATCH {enabled: true}`, which is why it is a named action and not a field write.

#### 2.10b `abandon` — an abandoned review item can otherwise hold the only workspace forever

§4.2 defers the closed-unmerged-PR path to PR B and claimed the interim escape hatch was "retry or manual issue closure." **That claim was wrong**, and re-review finding 4 is right to reject it. For a code item sitting in `ready_for_review`, all four exits are closed:

| Exit | Why it fails |
|---|---|
| `POST .../retry` | 409s unless `dispatch_status == "escalated"`, and 409s again if `pr_number is not None` (`agent_teams.py:405-435`) |
| closing the issue by hand | `_reconcile_closed_issues` only considers `_CLOSED_ISSUE_RECONCILABLE_STATUSES = ("escalated", "failed")` (`github_watcher_service.py:18`) — and `continue`s outright when `pr_number is not None` (`:117-147`) |
| the watcher noticing | `_ACTIVE_STATUSES` (`:14`) excludes `ready_for_review` |
| the reclaim sweep | its status list excludes `ready_for_review` deliberately (§2.5) — a reviewer may legitimately still be requesting changes |

So the wedge is real, it is reachable from the normal flow, and `GET .../workspaces` makes it *visible* without making it *clearable*. Adding `ready_for_review` to any of those status sets is not the fix — each exclusion is individually correct.

`POST .../github-work-items/{item_id}/abandon` takes an explicit operator decision and records it:

1. Accept only from a non-terminal status where no further automatic progress is possible: `ready_for_review`, `awaiting_human_review`, `dispatched`, `verifying`. 409 otherwise (`merged`, `completed`, `failed`, `escalated` are already reclaimable).
2. Set `dispatch_status = "escalated"` with `escalation_reason = "abandoned_by_operator"` and the operator's note. **No new `dispatch_status` value** — `escalated` already means "a human must look at this", which is precisely true here.
3. Do **not** release the lease, and do **not** kill the session. Reclaim picks it up on the next poll *if* the owner's session is offline (§2.5). The liveness gate stays the single arbiter of release.

Point 3 is the whole safety argument. The endpoint changes the item's *status*, which is Deck's to change; it does not assert anything about the *process*, which Deck cannot observe from an HTTP request. An operator who abandons an item whose agent is still live gets exactly the right outcome: the item is marked for human attention, and the lease is held until the agent actually goes away. This keeps the §2.4 invariant — release is licensed by the absence of a process, never by a status — intact, and it is why `abandon` is not "an operator force-release endpoint." A force-release would break that invariant, and it is deliberately not being built.

`abandon` also subsumes the general case §4.2 worried about: any item wedged in a status the automation will never advance can be cleared by an operator without touching the database.

`GET` returns derived state rather than a stored column, consistent with §2.2's decision to have no `lease_state` field. Note it must reflect **both** disable flags, or the primary — registered `dispatchable=False` per §7 — reads as `available` and the operator concludes there are two usable workspaces when there is one:

```
lease_state = "leased" if leased_item_id is not None
              else "disabled" if not enabled                     # broken tree
              else "disabled_for_dispatch" if not dispatchable   # e.g. the primary
              else "available"
```

The registration `POST` accepts `path`, `kind`, and optional `dispatchable` and `enabled`. `dispatchable` defaults by kind — `False` for `primary` (§2.6), `True` for `worktree` — but an **explicit** value in the request wins in both directions, so a worktree can be staged non-dispatchable and a primary can be made dispatchable deliberately. Both values are applied at the single point where the row is inserted; the endpoint resolves them and passes them down rather than the service assuming defaults, or the request fields would be accepted and silently ignored.

It is the only endpoint that mutates the **filesystem**, and it must be synchronous with the `git worktree add` it triggers: a 202-style "queued" response would hide provisioning failure behind a second lookup, and provisioning failure is the case that most needs to be visible (§2.9a). `reprobe` also touches the filesystem, but only ever on a row that already exists and is unleased (§2.10a).

### 2.11 UI surface — one required change, two worth doing

The plan's original "do not touch the frontend" was a diff-size decision, not an analysis. Reading `AutonomyPanel.tsx` shows one part of it does not survive.

**Required — a queued workspace shortage currently renders as nothing.** `pendingReasonLabel` (`AutonomyPanel.tsx:85-91`) handles two of the four existing `pending_reason` values and returns `null` otherwise. `queued_low_memory` and `queued_owner_session_live` already display as blank; `queued_no_workspace` would join them.

That matters more here than for the existing two, because **a workspace shortage is this design's expected steady state, not an exception.** One dispatchable workspace against 11 retried items (§7) means the normal picture is ten items at `pending` with no owner, no badge and no explanation — visually identical to the Finding 14 wedge, which this soak has already spent two findings learning to diagnose. The mechanism working correctly must not look like the mechanism being stuck.

**Worth doing with it:**

- A **Workspace** row in the work-item detail `<dl>` (`:369-388`, currently exactly four rows: Status, Owner, Retries, PR). This needs a backend field: `GithubWorkItemResponse` (`schemas.py:2209-2234`) has no workspace field, and `_work_item_response` (`agent_teams.py:93`) takes `(item, scope)` and so cannot reach a third table. Add a nullable `workspace_path`, derived — not stored — for the same reason §2.2 has no `lease_state`.
- The scope card's `Local checkout: {scope.repo_path}` (`:548-550`) is **the same sentence as the brief line this whole design exists to correct** (§2.7). After this change `scope.repo_path` is the worktree parent, not where agents work. Leaving it tells the operator the thing the brief has just stopped telling the agents.
- A pool summary on the scope card, now that `GET .../workspaces` exists: `Workspaces: 1 dispatchable, 1 leased`. Count **dispatchable** rows, not rows — a summary that includes the primary reports twice the capacity that exists. This is the observability §2.9a argues for, at the point where the queue depth is already visible.

**Deferrable:** the five new scope fields in `types/agentTeams.ts:150-197` (three interfaces enumerate scope fields explicitly) and in the `ScopeDialog` form. Every field has a server-side default and all five are set on scope 1 via the API during deployment, so the UI is not on the critical path for them. Same for adding `max_build_parallelism` to the scope config summary line (`:551-553`).

**Deliberately absent: UI for `reprobe` and `abandon`** (§2.10a, §2.10b). Both are exceptional-path operator actions, both are one `curl` away, and an `abandon` button beside the existing retry button would invite clicking it on an item that is merely queued — which is the exact confusion the required `pendingReasonLabel` fix above exists to prevent. Revisit after PR B, when abandonment is detected automatically and the manual action is rare rather than routine.

---

## 3. Multi-scope / multi-repo — documented for later

> This section exists because the immediate work is single-scope and will *look* finished. It is not finished for multi-repo, and the failure mode is silent.

### 3.1 Every concurrency control in Deck, and its true scope

| Control | Implementation | Actually scoped to | Physical resource it proxies |
|---|---|---|---|
| `max_concurrent_dispatched` | `scope_active_count` filters `scope_id` (`github_dispatch_service.py:92-104`) | **per scope** | agent slots, and implicitly RAM |
| `slot_is_busy` | filters `owner_slot_id` only, **no `scope_id`** (`:70-90`) | per slot, **across all scopes sharing the preset** | one agent's attention |
| `slot_has_live_owner_session` | filters `team_slot_id` | per slot, cross-scope | the tmux session |
| `github_min_available_memory_mb` | `settings`, read from `/proc/meminfo` (`:132-145`) | **host-wide** | RAM, sampled at dispatch |
| workspace lease (this design) | `github_workspaces.scope_id` | per scope | the checkout |
| build slot (3b, unbuilt) | — | **must be host-wide** | RAM during compilation |

Two things fall out of that table.

**(a) Slots are already cross-scope; caps are not.** `slot_is_busy` has no `scope_id` filter, so two scopes on the *same* preset already serialize per slot — accidentally correct. Two scopes on *different* presets have disjoint slots and serialize on nothing but their own independent `max_concurrent_dispatched`.

**(b) A per-scope limit can never bound a host-wide resource.** Add a second watched repo and each scope independently believes it may run `max_concurrent_dispatched` items. Nothing anywhere sums them. Two scopes × 2 workspaces × `-j4` ≈ 16 GB on a 15.6 GB box: every individual limit respected, host dead. That is Finding 11 arriving through a door the `-j` cap does not close, because the `-j` cap bounds one build and the missing bound is on the *number* of builds.

`github_min_available_memory_mb` is the only host-wide gate that exists today, and it has three structural defects: it **samples** rather than reserves; it is **checked once at dispatch and never again** (exactly one caller, line 180); and it **guards the wrong event** — dispatch, not compilation, and those can be forty minutes apart. It is the seed of 3b, not a substitute for it.

### 3.2 Consequence: 3b is a prerequisite, not an optimisation

3b — a **host-wide build semaphore**, leased for the duration of a compile and exposed to agents as an MCP tool — was previously deferred as "probably never needed on this host." That judgement was made in a single-scope world and is wrong for a generic Deck.

**A build slot is the only proposed mechanism that is host-wide rather than scope-scoped.** That, not serialization and not corruption prevention, is its justification: it is the only place a global constraint can live.

It stays last in sequence. With one scope, `-j4` genuinely suffices. But it is promoted from "probably never" to:

> **Gate: do not add a second `TeamGithubScope` — or a second autonomy-enabled preset — until 3b exists.**

Otherwise the first person to add a second scope silently re-creates Finding 11, and the symptom will be an OOM-killed team overnight with no error in any log, exactly as on 2026-07-27.

### 3.3 What multi-scope will need beyond 3b

Recorded now while the reasoning is fresh; none of it is in scope for the immediate work.

- **Workspace pools stay per-scope.** A checkout belongs to a repo; this is correct as designed and needs no change.
- **Build slots must be global.** Not `scope_id`-keyed. A singleton resource table, or `settings`-level like `github_min_available_memory_mb`.
- **`max_concurrent_dispatched` needs a host-wide ceiling above it**, or scopes must draw from a shared pool rather than each holding a private allowance.
- **Disk becomes a real limit.** Workspaces are N × repo size per scope; tizonia is 2.4 GB built. Two scopes × 3 workspaces × 2.4 GB ≈ 15 GB. Fine against 890 GB free today, but it is the second resource that scales with scope count and nothing tracks it.
- **`derive_repo_identity` hashes `--git-common-dir`**, so a worktree and its primary produce the **same `repo_id`** (verified: both `4532704bf856d362`). Slot-matching and Agent Mail identity therefore cannot distinguish a worktree from its parent. That is exactly why session reuse collided on a shared checkout in Finding 13, and it will matter again for any per-workspace identity work.
- **A remote/outsourced builder** (deferred decision A) plugs in at `max_build_parallelism` — that is the seam where "build capacity" stops meaning "this host's RAM."

---

## 4. Sequencing

| Step | What | Generic? | When |
|---|---|---|---|
| **1** | `github_workspaces` table, lease/release/reclaim, truthful brief | yes | now |
| **2** | `git worktree add` provisioning + reset-on-acquire | yes | now |
| **3a** | `-j` cap, build-dir template, `builds_out_of_tree` as scope config | yes, safe default | now |
| **3b** | **host-wide** build semaphore + MCP lease tool | **required for multi-scope** | before a 2nd scope |

Steps 1, 2 and 3a ship together — they are one coherent change and splitting them leaves the brief either lying or unimplementable.

### 4.1 PR A / PR B

Steps 1+2+3a ship as **PR A**, with one capability held back:

| | PR A (now) | PR B (after Phase G2) |
|---|---|---|
| schema, provisioning **and adoption**, reset, gate 6, brief, API, UI | yes | — |
| lease released by reclaim sweep | yes | — |
| operator repair of a disabled workspace (`reprobe`, §2.10a) | yes | — |
| operator clearing of a wedged item (`abandon`, §2.10b) | yes | — |
| **prompt release on `merged` / `completed`** | **no** | yes |
| per-item liveness via `item.launch_id` | no | yes |
| **automatic** closed-unmerged-PR detection (§4.2) | no | yes |
| Deck winding down an owner session | no | yes |

The split exists because prompt terminal release requires a liveness predicate that does not exist yet and that Phase G2 is already scheduled to rewrite (§2.4). Building an interim one would leave two similarly-named predicates to reconcile, in the exact area where Finding 13 showed that identity confusion causes collisions.

**The cost of the split, stated plainly:** with a pool this small, a merged item keeps its workspace until its tmux session goes offline. The pool can therefore look wedged when it is only waiting, and on a quiet host a session can idle for a long time. Three mitigations, all in PR A: the reclaim sweep runs every poll, `GET .../workspaces` shows exactly which item holds what, and `abandon` + `reprobe` give the operator a supported way to clear the two dead ends that would otherwise need DB surgery. If the latency proves too slow in practice, the fix is to bring PR B forward, not to release on status.

#### 4.1a Autonomy stays off until PR B lands

**PR A is a staging PR. Do not resume the soak's autonomous dispatch on it.** This is an explicit deployment gate, not a suggestion, and re-review finding 4 is right to demand it be stated rather than implied.

The reason is not that PR A is unsafe — its unsafe paths are the ones it exists to close. It is that PR A's *recovery* is entirely manual. Every mechanism that frees a workspace in PR A requires either an offline session (reclaim) or an operator (`abandon`, `reprobe`). With a size-1 dispatchable pool, one long-lived tmux session is enough to stall the queue indefinitely, and the queue stalling looks — on the UI, before §2.11's label fix is exercised — exactly like the Finding 14 wedge that cost two findings to diagnose. Running unattended autonomy on a mechanism whose only prompt releaser is a human is how a design that is correct becomes an incident that is confusing.

So the rollout is:

| Step | Autonomy | Purpose |
|---|---|---|
| PR A merged, backend restarted | **off** | §7 steps 1-4: migrate, register the pool, verify `GET .../workspaces` |
| one item dispatched by hand | **off** | prove the lease, the brief, the reset and the release on one real issue |
| PR B merged | **on** | prompt terminal release exists; the pool recovers without a human |

Adding a second dispatchable worktree (a one-`POST` change) reduces the stall risk but does not remove it, so it is not a substitute for this gate.

### 4.2 Deferred to PR B: *automatic* detection of abandoned review items

`_process_review_item` (`github_verification_service.py:217-230`) branches only on `pull.get("merged")`. A PR **closed without merging** matches no branch and returns silently, so the item stays in `ready_for_review` or `awaiting_human_review` indefinitely — and those statuses deliberately retain their lease (§2.4). Two abandoned reviews would therefore consume a two-workspace pool permanently — and at rollout, where only one workspace is dispatchable, one abandoned review is enough.

This is a pre-existing lifecycle gap that the lease turns from an untidiness into a capacity leak. **Automatic** detection — poll the PR, notice closed-unmerged, notify, escalate, wind down the session — stays in PR B, because it needs the same per-item session-liveness machinery.

What does **not** stay deferred is the operator's ability to clear it. An earlier version of this section claimed the interim escape hatch was "retry or manual issue closure." That was wrong; §2.10b traces all four exits and every one of them is closed for a code item in `ready_for_review`. `GET .../workspaces` made the wedge visible without making it clearable, which is not an escape hatch — it is a better view of a dead end.

So PR A ships `POST .../github-work-items/{item_id}/abandon` (§2.10b). The division is:

| | PR A | PR B |
|---|---|---|
| operator can clear a wedged review item | **yes** — `abandon` | — |
| Deck notices a closed-unmerged PR by itself | no | yes |
| Deck winds down the owner session | no | yes |

`abandon` deliberately does not release the lease itself — it sets the status and lets the reclaim sweep's liveness gate decide, so PR A gains a recovery path without gaining a second releaser (§2.4).

**Interaction with `escalate`'s broadcast, worth knowing before implementing:** `escalate` computes `owner_may_be_active` as `item.dispatch_status == "dispatched"` (`github_dispatch_service.py:650-652`), so abandoning from `ready_for_review` will *not* emit the built-in "the owner may still be working" warning — even though that is exactly the situation. Pass that caution in `abandon`'s own `note` instead of widening the condition; the condition belongs to `escalate` and Phase G2 owns that area.

---

## 5. Explicitly out of scope

- **3b.** Designed in §3 for the record; not built.
- **Phase G2** (Finding 13): `slot_has_live_owner_session` deletion, `reuse_existing`, `prompt_override` on the reuse path. This design *calls* `slot_has_live_owner_session` read-only and must not modify it. See the coupling note in §2.5.
- **Gating `mark_pull_ready_for_review` on `merge_policy`** (`github_verification_service.py:383` is ungated while line 394 is gated). Real, separate, tracked elsewhere.
- **Finding 6** (distinct agent commit identity).
- **G1c** (`2026-07-28-sweep-request-budget-design.md`) — different file, no overlap.
- **New `dispatch_status` values.** `queued_no_workspace` is a `pending_reason`, not a status.
- **Deleting worktrees.** Deck never removes a workspace. Cleaning up the eight stale build dirs (§7) is a human chore. No `DELETE` endpoint (§2.10).
- **Deleting or resetting the primary checkout.** Never, under any circumstance. The two read-only `rev-parse` probes of §2.9 are not an exception — that rule is about mutation.
- **`git worktree prune`.** Deck never runs it (§2.9); it rewrites the primary's metadata for every worktree.
- **An operator force-release endpoint.** `abandon` (§2.10b) changes an item's status and lets the liveness gate decide; a direct lease-clearing endpoint would break §2.4's invariant and is deliberately not built.
- **A general `PATCH` on workspaces.** `reprobe` (§2.10a) re-enables only on a successful reset. Writing `enabled=true` by hand would let an operator assert a broken tree is healthy.
- **Resuming autonomous dispatch on PR A.** See §4.1a — that is a PR B gate.
- **The five new scope fields in the frontend** — `types/agentTeams.ts` interfaces and the `ScopeDialog` form (§2.10, deferrable tier). Server-side defaults cover them and deployment sets them via the API.
- **A workspaces management page.** The scope card and detail dialog are enough for a pool this small.
- **Prompt release on `merged`/`completed`, per-item session liveness, and the closed-unmerged-PR path.** All PR B (§4.1, §4.2).
- **Deck terminating agent sessions.** Winding down a session to free a workspace is PR B's mechanism, and it needs its own safety argument — the standing rule is that a dispatched session is never killed unless positively confirmed dead.

---

## 6. Test obligations

Baseline to preserve: **290 passing** (`pytest tests/agent_teams tests/agent_mail -q`), or 294 if G1c has merged first. This list grew from 22 → 37 → **51** across three revisions (API/UI, then the plan review, then the re-review); expect ~51 new tests.

Items marked **★** are regression guards for a defect that has already occurred or was caught in review. They must be written *before* the code and observed to fail.

**Schema** (`tests/agent_teams/test_github_scope_models.py`)
1. `GithubWorkspace` round-trips with expected defaults (`kind="worktree"`, `enabled=True`, `dispatchable=True`, `leased_item_id=None`).
2. ★ Two workspaces cannot hold the same `leased_item_id` — `IntegrityError`. *The Finding 10 guard.*
3. ★ Two workspaces cannot share a `path` **even in different scopes** — `IntegrityError`. *The constraint is global; a per-scope constraint would let two scopes reset one directory.*
4. New scope columns default to `builds_out_of_tree=False`, `max_build_parallelism=4`, `build_dir_template="build"`, `build_command_hint=None`, `base_ref="origin/HEAD"`.
5. ★ The compat-migration ladder adds all five scope columns to a legacy table and backfills defaults. *Extend `test_compat_migration_adds_new_columns_to_legacy_db` (`:100`), which already exists — ORM defaults on a fresh DB do not prove the live `ALTER TABLE` path.*

**Lease mechanics** (`tests/agent_teams/test_github_dispatch_service.py`)
6. Acquire returns an available workspace and stamps `leased_item_id` + `leased_at`.
7. Acquire returns `None` when every workspace is leased; item gets `pending_reason="queued_no_workspace"` and stays `pending`.
8. Acquire is idempotent for an item that already holds a workspace (the retry-keeps-its-lease path).
9. Disabled workspaces are never acquired.
10. ★ **A `dispatchable=False` workspace is never acquired, even when it has the lowest `id` and is the only unleased row.** *Without this, the primary registered first wins the first dispatch and autonomous work lands in the human's checkout.*
11. ★ A `kind="primary"`, `dispatchable=True` worktree loses to an available `kind="worktree"` row regardless of `id` ordering — or, if preference is implemented purely via `dispatchable`, assert that registration defaults primary rows to `dispatchable=False`.
12. `repo_path_override` receives the **workspace** path, not `scope.repo_path`. *Extend the existing `test_repo_path_override.py` idiom.*
13. The brief contains the workspace path and the "leased exclusively" and "do NOT create worktrees" lines.

**Launch failure — every shape, not just `ValueError`**
14. ★ Launcher raises `ValueError` → item escalates `plan_blocked` **and** the workspace is released.
15. ★ Launcher **returns** a launch item with `status="failed"` → item becomes `failed` **and** the workspace is released. *`agent_team_service.py:638-648` catches `Exception` and returns `status="failed"`; it does not raise, so a `ValueError`-only release leaks the lease on the most common real failure.*
16. ★ Each blocked status (`blocked`, `blocked_provider_unavailable`, `blocked_agent_mail_not_configured`) also releases.
17. ★ An unexpected non-`ValueError` exception releases and re-raises rather than leaking the lease.
17a. ★ A launch returning **`status="pending_registration"`** — the real success status (`agent_team_service.py:631`) — **retains** the lease. *An earlier draft named a non-existent `"launched"`, so an implementation matching it literally would have fallen through to the unknown branch and released the workspace under a session that had just spawned.*
17b. ★ A launch returning an **unrecognised** status retains the lease (fail-closed), and so does one carrying a non-`None` `tmux_target`. *`"spawned"` is in the `AgentTeamLaunchStatus` Literal (`schemas.py:2039-2050`) with no producer; an unknown status is not evidence that no process exists.*

**Reclaim** — the subtle ones
18. A workspace leased by an `escalated` item whose owner slot has **no** live session is reclaimed.
19. ★ A workspace leased by an `escalated` item whose owner slot **has** a live session is **NOT** reclaimed. *The Finding 10 regression guard; must fail if someone reclaims unconditionally on escalation.*
20. ★ `_mark_merged` does **not** release. *PR A has no prompt terminal release — the tmux session outlives the merge (§2.4).*
21. ★ `_complete_and_notify` does **not** release.
22. `reset_for_retry` does **not** release.
23. A `merged` item whose owner slot has no live session **is** reclaimed by the sweep — capacity is recovered, just not promptly.

**Provisioning, adoption and reset** (new `tests/agent_teams/test_github_workspace_service.py`)
24. Provisioning a worktree invokes `git worktree add --detach <path> <base_ref>` — assert on a fake runner, do not shell out.
24a. ★ **Adoption**: a path whose `--git-common-dir` matches the scope's *and* whose `--show-toplevel` equals the path is registered with **no `worktree add`** call. *Verified: `worktree add` exits 128 on an existing worktree, so without this §7 step 2 cannot register `tizonia-openmax-il-issue-818` at all.*
24b. ★ A path whose `--git-common-dir` belongs to **another repo** is rejected and persists no row.
24c. ★ A path that is a **subdirectory** of a valid worktree is rejected — same `--git-common-dir`, different `--show-toplevel`. *Verified; a common-dir-only check registers two rows for one physical tree.*
24d. A path that is not a git tree at all is rejected. An **empty** existing directory takes the provisioning path (`worktree add` accepts it, verified exit 0).
24e. The common-dir comparison uses `--path-format=absolute`. *Verified: `rev-parse --git-common-dir` returns the relative `.git` when run from the primary, so a raw string comparison rejects every adoption.*
24f. ★ `kind="primary"` registration also validates repo identity — a path belonging to a different repository is rejected. *Canonicalisation proves directory identity, not repository membership.*
25. ★ Reset-on-acquire issues `clean -fd` and **never** `-fdx`. *Assert the absence of `-x`.* Guards the 1.1 GB build dir.
26. ★ Reset issues `switch --detach --force` and `reset --hard <base_ref>`. *Verified empirically: without `--force`, `switch` exits 1 on a dirty tracked file and `reset --hard` is never reached — on exactly the `escalated`/`failed` path reclaim exists to recover.*
27. ★ A `kind="primary"` workspace is **never** reset or cleaned — **zero** git mutation commands, not merely no destructive ones.
28. ★ A `fetch` failure leaves the workspace `enabled=True`, records the error, and returns `None` from `acquire`. *A transient outage must not disable one workspace per poll until the pool is empty.*
29. A local tree failure (`switch`/`reset`/`clean`) **does** set `enabled=False` and records `provision_error`.
30. A successful reset clears a previously-set `provision_error` — recovery needs no operator action.
31. The git runner passes a timeout and `GIT_TERMINAL_PROMPT=0`; a credential prompt cannot hang the poll loop.

**Config → brief** (`test_github_dispatch_service.py`)
32. With `builds_out_of_tree=True` + template + hint, the brief renders the build dir and the `-j{max_build_parallelism}` command.
33. With `builds_out_of_tree=False`, the brief states one build at a time in this workspace and omits the build-dir template.
34. ★ A malformed template with an unmatched `{` (raises `ValueError`) is contained: build lines are omitted, the brief is still produced, the poll loop survives. *`KeyError`/`IndexError` alone do not cover the most likely typo.*

**API** (`tests/agent_teams/test_github_workspace_api.py`, new — §2.10)
35. `GET .../workspaces` returns the pool with `lease_state` derived over **all four** cases: `available`, `leased` (with `leased_item_id`), `disabled`, and ★ `disabled_for_dispatch` for a `dispatchable=False` row. *Without the fourth, the primary reads as `available` and the operator over-counts capacity.* `GET` on an unknown `scope_id` → 404.
36. `POST .../workspaces` with `kind="worktree"` invokes `git worktree add --detach` and returns the created row; with `kind="primary"` it issues **zero mutating** git commands and defaults `dispatchable=False`; an invalid `kind` → 400; a duplicate canonical `path` → 409 not 500; a `worktree add` failure surfaces the error and persists **no row**.
36a. ★ `POST .../workspaces` with **explicit non-default** `dispatchable=False` on a `kind="worktree"`, and explicit `enabled=False`, persists both on the created row. *The request model exposes both fields; an earlier `provision_worktree` signature accepted neither, so the endpoint would have silently ignored its own input.*
36b. ★ `POST .../workspaces/{id}/reprobe` on a **disabled** row whose reset now succeeds sets `enabled=True` and clears `provision_error`; a reset that fails again leaves it disabled and returns 409. *Without this, §2.9a's local-failure branch is a permanent wedge — `acquire` filters on `enabled`, so reset never re-runs and nothing clears the error (§2.10a).*
36c. ★ `reprobe` on a **leased** row → 409 and **no** git mutation. *Reprobe is the reset sequence; running it under a live agent is the collision this design exists to prevent.*
36d. `reprobe` on a `kind="primary"` row → 409, zero mutating git commands.
36e. ★ `POST .../github-work-items/{id}/abandon` on a `ready_for_review` item with a `pr_number` sets `dispatch_status="escalated"` / `escalation_reason="abandoned_by_operator"` and does **not** release the lease; the next reclaim sweep releases it **only** once the owner session is offline. *All four pre-existing exits are closed for this item — retry 409s on both status and `pr_number`, and the watcher's reconcilable set excludes `ready_for_review` and skips items with a PR (§2.10b).*
36f. `abandon` on an already-terminal item (`merged`, `completed`) → 409; those are already reclaimable.
37. `GithubWorkItemResponse.workspace_path` is the leased workspace's path, and `None` for an item holding no lease.

---

## 7. Deployment on the live soak

The schema change needs **no hand-surgery**. `_run_sqlite_compat_migrations` (`app/database.py:290-429`) is an idempotent `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` ladder that already migrated `max_concurrent_dispatched` (line 386), and `init_db` runs `create_all` for the new table. A backend restart migrates the live DB. (CLAUDE.md's "no migration system — schema changes require deleting the db" is stale for this table family.)

Order of operations after the PR merges. **Autonomy stays off throughout — see §4.1a.**

1. Restart the backend — `create_all` adds `github_workspaces`, the ladder adds the five scope columns.
2. Register scope 1's workspaces **via `POST .../workspaces`** (§2.10) — not by hand-writing rows:
   - `kind="primary", dispatchable=false` for `/home/juan/work/repos/tizonia/tizonia-openmax-il`. The endpoint validates repo identity (§2.9) and issues no mutating git command.
   - `kind="worktree"` for the existing `tizonia-openmax-il-issue-818`. This takes the **adoption** path, not `worktree add` — the directory is already a worktree, and `worktree add` on it exits 128. Verified that it passes the identity probes:

     ```
     $ git -C .../tizonia-openmax-il-issue-818 rev-parse --show-toplevel
     /home/juan/work/repos/tizonia/tizonia-openmax-il-issue-818
     $ git -C .../tizonia-openmax-il-issue-818 rev-parse --path-format=absolute --git-common-dir
     /home/juan/work/repos/tizonia/tizonia-openmax-il/.git
     ```
3. Set scope 1's real values via `PATCH /github-scopes/{id}`: `builds_out_of_tree=True`, `build_dir_template="build"`, `build_command_hint="meson compile -C {build_dir} -j{parallelism}"`, `max_build_parallelism=4`. Conservative defaults are for unknown repos; tizonia via Meson is known.
4. `GET .../workspaces` to confirm 2 rows — the primary `disabled_for_dispatch`, the worktree `available`, neither with a `provision_error`. This is the check that step 2 actually took, and it is the reason the endpoint exists.
5. Retry **one** escalated item, by hand, with autonomy still off. Confirm on that single item: the lease appears in `GET .../workspaces`, the brief names the worktree path, the reset ran, and the lease is released once the session goes offline. Do not retry the other ten yet — one item exercises every mechanism, and ten make a diagnosis ambiguous.
6. After PR B lands: enable autonomy and retry the rest.

Note what step 2 means for capacity: **the pool that can actually be dispatched into is size 1**, because the primary is registered non-dispatchable. Combined with PR A having no terminal release (§2.4), a merged item holds its lease until the reclaim sweep sees its owner session gone — which is the substance of the §4.1a gate, not merely a latency annoyance. Read `GET .../workspaces` rather than guessing. Adding a second real worktree is a one-`POST` fix and is the recommended follow-up once PR A is observed working, but it reduces the stall risk rather than removing it.

Two supported recovery actions exist if step 5 goes wrong, and neither needs DB surgery: `POST .../workspaces/{id}/reprobe` if a reset failure disabled the worktree (§2.10a), and `POST .../github-work-items/{id}/abandon` if the item wedges in a review status (§2.10b). If either is needed, record it in the run log — it is the first real exercise of both.

Step 3's `build_dir_template="build"` is deliberate and is the correction from finding 5. The live checkouts already show why:

| checkout | build dirs present |
|---|---|
| `tizonia-openmax-il` | `build`, `build-core`, `build-issue-820`, `build-soundcloud`, `build-soundcloud-audit`, `build.pre-issue-820-verification` |
| `tizonia-openmax-il-issue-818` | `build`, `build-compat` |

Eight build trees across two checkouts, accumulated by hand over the soak, none of them reachable by `git clean -fd`. A per-issue template would have Deck reproduce that pattern automatically and unboundedly. One stable `build` per workspace is both bounded and faster — the lease already serialises the workspace, so there is no contention to avoid, and the incremental cache survives every reset (90 seconds instead of 40 minutes).

Cleaning up the existing eight is separate operational work, not part of this PR.

One caution on step 2, from Finding 13: `derive_repo_identity` hashes `--git-common-dir`, so the primary and the `issue-818` worktree share `repo_id` `4532704bf856d362` (§3.3). Registering both is correct and necessary, but slot matching cannot tell them apart — so a `kind="primary"` lease and a `kind="worktree"` lease look identical to routing. That is fine here because the *lease*, not the `repo_id`, is what enforces exclusivity; it is recorded because it will mislead anyone debugging routing against these two rows.

The existing hand-made `tizonia-openmax-il-issue-818` worktree is **registered rather than deleted** — it holds #818's history and is already a valid pool member. Adoption (§2.9) exists precisely so that this is expressible through the API instead of requiring the directory be destroyed and recreated, which would throw away its 34 MB `build` and 1.1 GB `build-compat` caches for nothing.

Expected behaviour on the single hand-retried item of step 5: it dispatches into the real workspace with a truthful brief. With autonomy off, nothing else moves. If it dispatches with `scope.repo_path` as its cwd, the change did not take. Once autonomy is enabled after PR B, the rest of the queue should sit at `pending_reason="queued_no_workspace"` or `queued_repo_cap` — visibly queued, per §2.11, rather than blank.
