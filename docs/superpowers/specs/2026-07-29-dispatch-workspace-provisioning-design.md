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

It also bounds disk. Per-item creation is unbounded (the soak already accumulated 6 stale build dirs, 2.4 GB); a pool of N is N × repo size, known in advance.

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
        UniqueConstraint("scope_id", "path", name="uix_scope_workspace_path"),
        UniqueConstraint("leased_item_id", name="uix_workspace_leased_item"),
    )
```

**There is deliberately no `lease_state` column.** State is derived, so it cannot contradict itself:

| Derived state | Condition |
|---|---|
| available | `enabled` AND `leased_item_id IS NULL` |
| leased | `leased_item_id IS NOT NULL` |
| unavailable | NOT `enabled` |

`UniqueConstraint("leased_item_id")` is the important one. SQLite permits many NULLs in a unique index but only one non-NULL of each value, so this constraint means **one item can hold at most one workspace and one workspace can hold at most one item, enforced by the database**. Finding 10 was a duplicate-owner bug that got through because the invariant lived only in query logic. This time it lives in the schema.

`kind` takes `"primary"` or `"worktree"`. It is not decoration — see §2.6.

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

If the launcher raises `ValueError`, the existing `except` branch escalates `plan_blocked`. Release the workspace there — the session never started, so nothing is in the directory.

### 2.4 Where the lease is released

The lease must survive as long as an agent might still write to the directory. Tracing the status machine:

- `dispatched` — agent is editing. Needs it.
- `verifying` — CI is running, but `_record_failed_verification_attempt` sends the item **back to `dispatched`** (`github_verification_service.py:477,505`) so the agent can push a fix. Needs it.
- `ready_for_review` — `record_approval_round` exists precisely because reviewers request changes and the agent revises. Needs it.
- `merged` / `completed` — done. Release.
- `failed` / `escalated` — ambiguous. See below.

So: **two explicit releases plus one reclaim sweep.**

Explicit, unconditional:

| Call site | File:line | Why safe |
|---|---|---|
| `_mark_merged` | `github_verification_service.py:413` | PR is merged; no further work exists |
| `_complete_and_notify` | `github_watcher_service.py:152` | issue closed outside the pipeline |

The reclaim sweep handles `failed` and `escalated`, and it is the subtle part.

### 2.5 Reclaim — why escalation must not release unconditionally

Escalation does **not** mean the agent stopped. `_send_escalation_broadcast` already carries an `owner_may_be_active` flag and warns the team in prose:

```
- NOTE: this item's owner session may still be working. Do NOT
  retry it — retrying clears any PR it has opened.
```

Releasing a lease on escalation would hand the directory to a second item while a live agent is still editing it. That is Finding 10 reproduced by the very mechanism meant to prevent it.

But never releasing is equally fatal: the soak currently holds **11 escalated items** (#821-#829, #834, #858). Eleven permanently-held leases against a pool of two is a permanent wedge — and a wedge is exactly how Finding 14 masked Finding 15 for a week.

The resolution is to release on the *physical* condition rather than the *logical* one:

> A lease held by a terminal-ish item (`escalated`, `failed`) is reclaimable **iff the owner slot has no live session.**

Deck already computes this: `slot_has_live_owner_session(db, slot_id)` (`github_dispatch_service.py:106-130`). Reusing it means the reclaim rule is grounded in an observed tmux/heartbeat fact, not a guess. No new endpoint, no human intervention, no wedge — and it cannot steal a directory from a running agent.

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
git -C <ws> switch --detach <base_ref>
git -C <ws> reset --hard
git -C <ws> clean -fd          # NOT -fdx
```

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
| `build_dir_template` | `None` | e.g. `build-issue-{issue_number}` |
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

---

## 5. Explicitly out of scope

- **3b.** Designed in §3 for the record; not built.
- **Phase G2** (Finding 13): `slot_has_live_owner_session` deletion, `reuse_existing`, `prompt_override` on the reuse path. This design *calls* `slot_has_live_owner_session` read-only and must not modify it. See the coupling note in §2.5.
- **Gating `mark_pull_ready_for_review` on `merge_policy`** (`github_verification_service.py:383` is ungated while line 394 is gated). Real, separate, tracked elsewhere.
- **Finding 6** (distinct agent commit identity).
- **G1c** (`2026-07-28-sweep-request-budget-design.md`) — different file, no overlap.
- **New `dispatch_status` values.** `queued_no_workspace` is a `pending_reason`, not a status.
- **Deleting worktrees.** Deck never removes a workspace. Cleaning up the 6 stale build dirs is a human chore.
- **Deleting or resetting the primary checkout.** Never, under any circumstance.

---

## 6. Test obligations

Baseline to preserve: **290 passing** (`pytest tests/agent_teams tests/agent_mail -q`), or 294 if G1c has merged first.

**Schema** (`tests/agent_teams/test_github_scope_models.py`)
1. `GithubWorkspace` round-trips with expected defaults (`kind="worktree"`, `enabled=True`, `leased_item_id=None`).
2. Two workspaces cannot hold the same `leased_item_id` — `IntegrityError`. *This is the Finding 10 guard.*
3. Two workspaces in one scope cannot share a `path` — `IntegrityError`.
4. New scope columns default to `builds_out_of_tree=False`, `max_build_parallelism=4`, `build_dir_template=None`, `build_command_hint=None`, `base_ref="origin/HEAD"`.

**Lease mechanics** (`tests/agent_teams/test_github_dispatch_service.py`)
5. Acquire returns an available workspace and stamps `leased_item_id` + `leased_at`.
6. Acquire returns `None` when every workspace is leased; item gets `pending_reason="queued_no_workspace"` and stays `pending`.
7. Acquire is idempotent for an item that already holds a workspace (the retry-keeps-its-lease path).
8. Disabled workspaces are never acquired.
9. `repo_path_override` receives the **workspace** path, not `scope.repo_path`. *Extend the existing `test_repo_path_override.py` idiom.*
10. The brief contains the workspace path and the "leased exclusively" and "do NOT create worktrees" lines.
11. Launcher `ValueError` → item escalates `plan_blocked` **and** the workspace is released.

**Reclaim** — the subtle ones
12. A workspace leased by an `escalated` item whose owner slot has **no** live session is reclaimed.
13. A workspace leased by an `escalated` item whose owner slot **has** a live session is **NOT** reclaimed. *This is the Finding 10 regression guard; it must fail if someone reclaims unconditionally on escalation.*
14. `_mark_merged` releases.
15. `_complete_and_notify` releases.
16. `reset_for_retry` does **not** release.

**Provisioning** (new `tests/agent_teams/test_github_workspace_service.py`)
17. Provisioning a worktree invokes `git worktree add --detach <path> <base_ref>` — assert on a fake runner, do not shell out.
18. Reset-on-acquire issues `clean -fd` and **never** `-fdx`. *Assert the absence of `-x`.* Guards the 1.1 GB build dir.
19. A `kind="primary"` workspace is **never** reset or cleaned — no git mutation commands at all.
20. Provisioning failure records `provision_error`, sets `enabled=False`, and does not raise into the poll loop.

**Config → brief** (`test_github_dispatch_service.py`)
21. With `builds_out_of_tree=True` + template + hint, the brief renders the build dir and the `-j{max_build_parallelism}` command.
22. With `builds_out_of_tree=False`, the brief states one build at a time in this workspace and omits the build-dir template.

---

## 7. Deployment on the live soak

The schema change needs **no hand-surgery**. `_run_sqlite_compat_migrations` (`app/database.py:290-429`) is an idempotent `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` ladder that already migrated `max_concurrent_dispatched` (line 386), and `init_db` runs `create_all` for the new table. A backend restart migrates the live DB. (CLAUDE.md's "no migration system — schema changes require deleting the db" is stale for this table family.)

Order of operations after the PR merges:

1. Restart the backend — `create_all` adds `github_workspaces`, the ladder adds the five scope columns.
2. Register scope 1's workspaces. `kind="primary"` for `/home/juan/work/repos/tizonia/tizonia-openmax-il`; one `kind="worktree"`.
3. Set scope 1's real values: `builds_out_of_tree=True`, `build_dir_template="build-issue-{issue_number}"`, `build_command_hint="meson compile -C {build_dir} -j{parallelism}"`, `max_build_parallelism=4`. Conservative defaults are for unknown repos; tizonia via Meson is known.
4. Retry the 11 escalated items so they re-dispatch against real workspaces.

The existing hand-made `tizonia-openmax-il-issue-818` worktree should be **registered rather than deleted** — it holds #818's history and is already a valid pool member.

Expected first-poll behaviour: one item dispatches into a real workspace with a truthful brief; the rest sit at `pending_reason="queued_no_workspace"` or `queued_repo_cap`. If any item dispatches with `scope.repo_path` as its cwd, the change did not take.
