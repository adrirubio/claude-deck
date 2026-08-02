# Phase G2 — Session lifecycle and workspace release

**Date:** 2026-08-02
**Status:** design approved, not implemented
**Branch:** `feature/autonomous-github-dispatch`
**Predecessor:** `2026-07-29-dispatch-workspace-provisioning-design.md` (PR A merged `c92b044`, deployed to step 4)
**Evidence base:** `2026-07-06-tizonia-roadmap-v1-soak-run-log.md`, Findings 10, 13, 16, 17, 18 (+ Finding 19, first recorded here)

---

## 1. Problem and scope

G2 exists because Finding 13 showed the Finding 10 guard cannot see the session it was
meant to block. Verifying that during PR A's deployment surfaced two further defects in
the same area (Findings 17 and 18). Investigating the session model chosen for G2
surfaced a fourth (Finding 19, below).

All five are one defect family: **a signal that answers a question it is no longer being
asked.**

| # | The signal | The question it answers | The question being asked |
|---|---|---|---|
| 13 | `slot_has_live_owner_session` | live session from a previous *dispatch*? | live session on this slot? |
| 17 | `mail_agent_sessions.last_seen_at` | when did a human last open the Agent Mail page? | is this agent alive now? |
| 18 | `item.launch_id` → `tmux_target` | which *launch* was this? | which session owns this *item*? |
| 19 | "is a process alive?" | is the slot's session running? | is anything mutating this workspace? |
| 10 | (the harm, not a signal) | — | are two processes writing one checkout? |

Each survived review because its *logic* was correct. What changed underneath was the
meaning of its inputs. This is the generalisation of the three lessons already recorded
in this design family — *membership is not identity*, *name the actor and confirm they
can do the thing*, and *an invariant is only as good as the freshness of the evidence it
reads*.

### 1.1 Scope

**One session per slot for its whole life**, with an explicit release protocol replacing
process-liveness as the workspace releaser. Two PRs, release protocol first.

Out of scope, deliberately:

- **Per-item mail identities.** Rejected in favour of the one-session-per-slot model.
- **Git-quiescence as the primary release signal.** Rejected in favour of agent-reported
  release; git-cleanliness survives only as a *veto* inside the backstop (§3.2).
- **Pool growth.** Available later if throughput needs it; it is not a correctness fix,
  because an unreleasable lease wedges a pool of any size.

### 1.2 Finding 19 (NEW — blocker, found while designing G2)

Under one-session-per-slot, PR A's reclaim sweep can never fire.

PR A's release invariant is *release is licensed by the absence of a process, never by a
status*. That was discriminating while dispatch spawned per item: the item's session
exited, the predicate went false, the lease came back. Under one session per slot for its
whole life, the slot's session is alive **permanently by design** — so the predicate is
permanently true, and the sweep that PR A made the *only* releaser returns 0 forever.

Verified by running the real code against a throwaway copy of the live DB, simulating
G2's end state (liveness fresh, reuse recording the standing session's `tmux_target`,
`item.launch_id` pointing at that launch, the worktree leased to terminal item 23):

```
slot 4: slot_has_live_owner_session=False  slot_is_busy=False
slot 5: slot_has_live_owner_session=False  slot_is_busy=False
slot 6: slot_has_live_owner_session=True   slot_is_busy=False
reclaim_stale released: 0
```

With `max_concurrent_dispatched=1` and one dispatchable workspace on this scope, the
first terminal item wedges the pool permanently.

This is the coupling §2.5 of the PR A design warned about, arriving from the opposite
direction. That note predicted G2 would *delete* the predicate and leave nothing
preventing a wedge. What actually happens is the predicate survives and *causes* the
wedge. **Lease release, not brief delivery, is the hard part of G2.**

---

## 2. What changes, and what each finding's fix actually is

### 2.1 Finding 13's recorded fix is not implemented

The run log's recorded fix shape was: make the reuse path deliver `prompt_override`, then
flip dispatch to `reuse_existing=True`. **The first half is unnecessary.**

`_send_dispatch_brief_to_slot` (`github_dispatch_service.py:244`) already delivers the
brief as an Agent Mail message *before* `launcher(...)` is called, and
`_send_tmux_inbox_check` (`agent_mail_service.py:1088`) already types `INBOX_CHECK_PROMPT`
into the pane to make a standing session read its inbox.

Verified on live data: every one of the last 14 dispatch briefs carries a `read_at`.
Message 342 (issue #821) was read by member 17 six seconds after it was sent. The brief
already arrives at the standing session today. What is missing is only the *guarantee*
that it arrives, which is §4.

This is a re-derivation, not a reversal. Finding 13's fix shape was written before PR A
existed; PR A's worktree leasing made isolation structural rather than behavioral, which
**retired** the need for that fix rather than enabling it.

### 2.2 The changes

- **Dispatch flips to `reuse_existing=True`** and stops passing `slot_prompt_overrides`.
  The brief is mail, not a spawn prompt.
- **`slot_has_live_owner_session` is deleted**, along with the `queued_owner_session_live`
  pending reason and its gate in `dispatch_pending`. `slot_is_busy` remains as the logical
  one-item-per-slot guard — the guard that was always correct.
- **`reclaim_stale`'s liveness gate is replaced** by the release protocol (§3). This
  revises code PR A shipped; it does not extend it.

### 2.3 Accepted cost: isolation is behavioral under this model

A reused session's cwd is fixed at spawn (the primary checkout), and `repo_path_override`
is ignored on the reuse branch. Verified from the live host — all five panes report
`path=/home/juan/work/repos/tizonia/tizonia-openmax-il` even while their agents were
demonstrably working inside the `…-issue-818` worktree.

So under this model, worktree isolation is delivered by the brief's *instructions*, not by
the process's working directory. It held throughout the soak, but it is behavioral, not
structural. Accepted explicitly (user decision, 2026-08-02).

Two consequences worth recording:

1. **Deck cannot identify the owner session by asking "which pane sits in the leased
   workspace?"** `pane_current_path` does not follow the agent's `cd`. That closes an
   otherwise attractive route to per-item identity.
2. `_validate_adoption_is_available` (`github_workspace_service.py:280-286`) cannot see an
   agent working a worktree *from* a standing session — it only catches a session
   **spawned** there. Its occupancy check is weaker than it appears.

### 2.4 Finding 18 dissolves rather than being solved

G2's answer to "what identifies the session owning a work item" is: **nothing does, and
nothing needs to.** The lease identifies the workspace, `slot_is_busy` identifies the
slot, and the owner's own report identifies completion. `item.launch_id` stops being asked
a question its values cannot answer.

---

## 3. The release protocol (PR1)

### 3.1 The report

A new **report status** `workspace_released` on `POST /dispatch-status` and
`deck_report_dispatch_status`.

This adds **no new `dispatch_status` value**. The endpoint's `triaging`, `ack_received`
and `in_progress` branches (`app/api/v1/agent_teams.py:277-313`) already demonstrate
report statuses that do not move `dispatch_status`, so the standing "NO new
`dispatch_status` values" constraint holds.

```python
elif report.status == "workspace_released":
    if report.reporting_slot_id != item.owner_slot_id:
        raise HTTPException(status_code=409, detail="only the owner slot may release its workspace")
    await github_workspace_service.release(db, item.id)   # idempotent no-op if unleased
```

Three properties, each earned from a prior finding:

- **Owner-only.** A non-owner slot releasing someone else's lease is Finding 10's shape
  through a new door. Mismatched `reporting_slot_id` → 409.
- **Idempotent.** `release()` already no-ops when nothing is leased
  (`github_workspace_service.py:113-114`), so a repeated report is a 200.
- **Independent of `dispatch_status`.** Escalation must not release — `escalate` broadcasts
  that "this item's owner session may still be working" — and release must not escalate.
  They are orthogonal facts and stay orthogonal.

`_dispatch_brief` gains the corresponding required step alongside the existing `triaging` /
`pr_opened` / `blocked` instructions.

### 3.2 The backstop

`reclaim_stale`'s gate changes from `slot_has_live_owner_session` to a conjunction. **All**
must hold to release:

1. item in `_RECLAIMABLE_STATUSES` (unchanged), **and**
2. `leased_at` older than `STALE_LEASE_BACKSTOP_SECONDS` (6h), **and**
3. the recorded owner process is dead, **and**
4. `git status --porcelain` on the worktree is empty.

Condition 4 applies only where it is meaningful: `reset_workspace` already no-ops on
`kind == "primary"` (`github_workspace_service.py:154-155`), and the primary checkout is
`dispatchable=0` on this scope, so it is never leased. If a primary workspace is ever made
dispatchable, the backstop must not run `git status` against a human's working tree and
conclude anything about Deck's leases — the conjunction is defined for **worktree**
workspaces, and a leased primary is retained unconditionally.

**Where the pid comes from matters, and it is not where you would first look.** It cannot
be read from the observed `MailAgentSession`: `_remove_stale_observed_sessions`
(`agent_mail_service.py:530-542`) **deletes** the row when tmux stops reporting it, so on
process death the pid record vanishes rather than going false — and absence is
indistinguishable from a discovery failure, which `sync_observed_sessions` swallows with an
early return (`:354-356`).

So the pid is captured **onto the lease** at dispatch and read back from `/proc`. Two new
nullable columns on `github_workspaces`:

- `leased_owner_pid` — the owner session's pid at acquire time
- `leased_owner_proc_start` — field 22 of `/proc/<pid>/stat`, guarding pid reuse

`pid_max` on this host is 4194304, so reuse is unlikely; the pairing makes "alive" mean
*this* process rather than *a* process. This is Finding 18's trap one level down — an
identifier whose uniqueness is assumed rather than guaranteed.

**Why the conjunction, not either signal alone.** The two conditions fail in opposite
directions. A stale pid resolving to an unrelated live process says "alive" → the lease is
held too long → throughput lost. A clean tree says "idle" → release → possible
`reset --hard` under a working agent → corruption. Requiring both means the **safe** error
dominates: any disagreement retains the lease.

Note what condition 4 is really doing. Git-quiescence was declined as the *primary*
release signal and it is not one here — it is a veto. It can only prevent a release, never
cause one, so it grants Deck no new authority over the workspace.

### 3.3 Why agent-reported release is defensible here

Measured across all 28 work items in the soak:

- **Zero** reached a terminal state with no agent self-report. Every escalated item has a
  `status_note`; 9 of 11 have an `ack_received_at`.
- 25 of 28 needed no retry.
- All 11 escalations were `plan_blocked` or `dispatch_label_removed` — *plan* blockages,
  not silent agent deaths.

The soak's failure mode was never "agent vanished without reporting". It was "agent
reported `blocked` and stopped" — which is a report, and a report can release. The
backstop therefore covers the **uncommon** case (host OOM as in Finding 11, or a crash
mid-work), which is why its threshold can be generous rather than aggressive. That is the
safe direction: an early release under a live agent is Finding 10 again.

---

## 4. Delivery guarantee (PR2)

Dispatch passes `reuse_existing=True`, drops `slot_prompt_overrides`, and keeps `acquire`
plus the brief naming the leased worktree path.

Two delivery defects must close in the same PR, or the flip makes brief delivery **less**
reliable than the spawn path it replaces.

### 4.1 The nudge cooldown can silently drop a brief

`AUTO_NUDGE_COOLDOWN_SECONDS = 30` over an in-memory `_last_auto_nudge_at` dict
(`agent_mail_service.py:42, 1134-1146`).

Under per-item spawn the nudge was decorative — the prompt was passed at spawn. Under
one-session-per-slot the nudge is the **only** thing that makes the agent read the brief.
Any other message to that member within the prior 30s (an escalation broadcast, a
blocker-merged notification) skips the dispatch brief's nudge, and the brief sits unread
until something else happens to wake the agent.

Covered by tests today only as a throttle *feature*
(`test_send_message_auto_nudge_is_throttled`), never as a delivery risk. Dispatch briefs
get an explicit non-throttled wake path.

### 4.2 `_nudge_session_for_member` picks an arbitrary pane

It orders by `last_seen_at desc` and takes the first nudgeable session (`:1081-1085`).
Slot 6 currently carries three sessions under one `member_id`, all stamped within
microseconds of each other by `sync_observed_sessions` one line earlier — so which pane
receives the prompt is effectively a coin flip today.

Converging to one session per slot fixes this by construction, but the **migration** starts
from three. PR2 must converge the slot explicitly rather than assume it.

---

## 5. Testing

The strategy is shaped by *why* the existing suite passed while the code was broken. 239
tests pass in `tests/agent_teams/` today (baseline, 2026-08-02). Finding 13 lived under a
green suite, and its canary asserted the bug as the requirement.

### 5.1 Rewritten, not extended

| Test | Why it is wrong now |
|---|---|
| `test_dispatch_proceeds_with_only_standing_session` (`test_github_dispatch_service.py:1256`) | Asserts a second session is spawned when a standing one exists — encodes Finding 13. Becomes: **the brief reached the standing session** (a `MailReceipt` for the owner member, `reuse_existing=True`, exactly one session after dispatch). |
| `test_reclaim_releases_non_working_item_without_live_owner` (`test_github_workspace_service.py:211`) | Monkeypatches the deleted predicate. Becomes the four-condition conjunction. |
| `test_reclaim_retains_non_working_item_with_live_owner` (`:236`) | Same. Becomes: retained because the pid is alive **or** the tree is dirty. |
| `test_queued_owner_session_dispatches_after_session_goes_offline` (`:1299`) | Tests a queue state that no longer exists (`queued_owner_session_live`). Deleted. |

### 5.2 New tests, each pinned to a finding

- **The skew test (Finding 17; owed from PR A §6).** Live pid + `last_seen_at` past TTL —
  a deliberately constructed *skew*, not a plainly-live or plainly-offline fixture. This is
  the class of defect fixtures hide by construction, since every test supplies its own
  timestamps.
- **Backstop conjunction, four cases.** dead+clean → release; alive+clean → retain;
  dead+dirty → retain; within-threshold → retain. The three *retain* cases are the ones
  that matter: exclusion lists are systematically under-tested (M12), because nobody writes
  "X does **not** happen" unless the omission is understood as a decision.
- **Pid reuse.** Same pid, different `proc_start` → treated as dead.
- **Owner-only release.** Non-owner slot reporting `workspace_released` → 409.
- **Release idempotency.** Second report → 200, no error.
- **Cooldown bypass.** An unrelated message 5s before dispatch must not suppress the
  brief's nudge.
- **M12's guard (owed from PR A).** `ready_for_review` must not be reclaimable. It is a
  real `dispatch_status` (`github_verification_service.py:102`) and is correctly absent from
  `_RECLAIMABLE_STATUSES` (`github_workspace_service.py:24`) — the test pins that omission
  as a decision rather than an accident.

### 5.3 Mutation review

As on PR A. The 12-mutation pass caught M12's real gap there, and this diff touches the
same destructive path (`reset --hard` / `clean -fd` under a lease).

---

## 6. Risks and what stays unverified

- **The release is behavioral, twice over.** Isolation-by-brief (§2.3) and
  release-by-report (§3.1). The §3.3 evidence says agents report reliably; the backstop
  covers the crash case, not the common one.
- **The 6h threshold is a guess.** One dispatchable worktree and
  `max_concurrent_dispatched=1` mean one stuck lease stalls the scope for 6h. 890 GB free
  at ~2.4 GB per worktree makes a larger pool cheap if that bites — throughput tuning, not
  correctness.
- **PR A's dispatch half remains unexercised.** `acquire` under a real dispatch,
  `reset_workspace`'s four commands on a real worktree, `clean -fd` preserving the 1.1 GB
  meson cache, the brief naming the worktree path, release-on-launch-failure. §7 re-runs
  that as one deployment.
- **Autonomy stays OFF** until both PRs land and the deployment in §7 is verified. Window 2
  (auto-merge to the public repo) remains separately gated on finding #1 (Leader self-ack)
  and finding #6 (agent commit identity == human reviewer identity).

---

## 7. Deployment

Both PRs merge to `feature/autonomous-github-dispatch`. The master merge is unchanged and
later.

Re-arming order:

1. **Migrate the DB.** Two additive nullable columns. The project has no migration system
   ("schema changes require deleting the db", per `CLAUDE.md`), so this is a hand-applied
   `ALTER TABLE` on SQLite — **not** a recreate. The live DB holds the entire soak history
   and the 28 work items of evidence that made Findings 17, 18 and 19 provable; recreating
   it would destroy that record.
2. **Converge slot 6 to one session** (§4.2). Slot 6 currently carries three
   (`…-fe2f` standing, `…-7845` from #818, `…-fd9c` for #821). **Which one survives is not
   arbitrary:** the survivor must be the session with no unfinished work, and the others
   must be confirmed idle before being killed — a dispatched session must never be
   terminated, nor reported on, unless positively confirmed dead. `…-fd9c` was mid-work on
   #821 at last observation, so this step requires a live check at the time it is
   performed, not a decision recorded here. Kill the extra panes **before** restarting the
   backend, per the respawn-hygiene rule (codex auto-reconnects to durable member IDs and
   recreates duplicates otherwise).
3. **Register a second worktree** if throughput warrants it (optional).
4. **Dispatch one fresh work item** on a slot with no standing session — cleaner than
   retrying item 23, which stays escalated and must not be retried.
5. **Verify:** the brief lands in the owner's inbox and is read; the agent works inside the
   leased worktree; `workspace_released` returns the lease; a second identical report is a
   200.

---

## 8. Sequencing rationale

Chosen: **release protocol first, then the delivery flip** (user decision, 2026-08-02).

It is the only ordering in which no commit contains a known wedge. Flipping
`reuse_existing=True` first would create Finding 19's permanent wedge with no releaser in
place — measured at `reclaim_stale released: 0`. Autonomy being off makes that survivable
but not acceptable: a knowingly-broken repo state is the kind of thing that gets forgotten
and re-armed.

**Correction to the rationale given when this sequence was recommended.** PR1 was argued to
front-load Finding 17 because the backstop's pid check depends on it. Tracing the pid to
`/proc` rather than to `last_seen_at` (§3.2) shows it does not, and the two paths this
design *does* depend on already self-refresh: `plan_launch` calls `sync_observed_sessions`
before reuse matching (`agent_team_service.py:427`), and `auto_nudge_members` calls it
before nudging (`agent_mail_service.py:1131`). With the predicate deleted, Finding 17's
remaining victim is the **UI**, which displayed five live agents as offline. It stays in
PR1 — the skew test is owed from PR A §6 and the display is user-facing truth — but it is
an accuracy fix, not a blocker. Sequence A remains correct for the wedge reason alone.

---

## 9. Carried-forward obligations

From PR A's §6, still owed and now assigned to PR1:

- **M12's guard test** — `ready_for_review` must not be reclaimable.
- **The Finding 17 skew test** — live pid + expired TTL.

New from this design:

- **Finding 19** must be recorded in the soak run log alongside Findings 17 and 18.
- The **`_validate_adoption_is_available` blind spot** (§2.3, consequence 2) is recorded,
  not fixed. It weakens an occupancy check that no longer gates anything destructive under
  this design, but it will mislead a future reader.
