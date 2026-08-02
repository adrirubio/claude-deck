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

- **Dispatch flips to `reuse_existing=True`.** The brief is delivered as mail — and is *also*
  still passed as `slot_prompt_overrides`, which is load-bearing on the spawn fallback. See
  §4.0; the first draft of this line said the override is dropped, and that was a regression.
- **`slot_has_live_owner_session` is deleted**, along with the `queued_owner_session_live`
  pending reason and its gate in `dispatch_pending`. `slot_is_busy` remains as the logical
  one-item-per-slot guard — the guard that was always correct.
- **`reclaim_stale`'s liveness gate is replaced** by the release protocol (§3). This
  revises code PR A shipped; it does not extend it.
- **Every lease becomes attempt-scoped** via a per-acquisition `lease_token` (§3.1a), and
  release names the token rather than the item.
- **Dispatch refuses an ambiguous slot** (more than one nudgeable session) before acquiring a
  workspace (§4.2).

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

### 2.4 Finding 17's fix, stated as a rule

**Added 2026-08-02 after the second impl-agent review, which correctly noted that Finding 17
had a test obligation (§5.2) and an owner (PR1) but no stated implementation rule — so two
implementers could satisfy the test differently.**

The asymmetry is in `_effective_status` (`agent_mail_service.py:614-632`): for
`source == "mcp"` it consults `_pid_is_running(pid)` and returns `connected` on a live pid
*even past the TTL* (`:629-631`), while `source == "observed"` rows — which carry pids too —
get no such treatment and go `offline` the moment `OBSERVED_TTL_SECONDS` (300s) lapses. That
is why five live agents displayed as offline.

**The rule:** for `source == "observed"` past its TTL, resolve on the pid exactly as the mcp
branch already does:

| `last_seen_at` vs TTL | pid state | `_effective_status` |
|---|---|---|
| within TTL | any | `session.mailbox_status` (unchanged) |
| expired | live | **`connected`** (currently `offline`) |
| expired | dead | `offline` (unchanged) |
| expired | NULL / unreadable `/proc` | `offline` — **fail closed** |
| any | `mailbox_status == "offline"` | `offline` (unchanged; an explicit disconnect wins) |

Failing closed on an unreadable pid is the opposite choice from §3.2's backstop, and
deliberately so: here the consequence of guessing "alive" is a **UI** that claims an agent is
present when it may not be, and possibly a nudge into a dead pane. Nothing destructive hangs
off this predicate any more — §1.2 removed that — so the conservative direction is the honest
display, not the retained resource.

`_pid_is_running` is unchanged and stays the single implementation for both sources.

### 2.5 Finding 18 dissolves rather than being solved

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
`dispatch_status` values" constraint holds *for the report*.

**It does not hold for the design as a whole.** §3.1a-bis introduces one genuinely new status,
`retry_requested`, and that is flagged as a deliberate exception requiring approval — see there
for why `pending_reason` cannot carry it.

```python
elif report.status == "workspace_released":
    if report.reporting_slot_id != item.owner_slot_id:
        raise HTTPException(status_code=409, detail="only the owner slot may release its workspace")
    if report.lease_token is None:
        raise HTTPException(status_code=400, detail="lease_token required")
    await github_workspace_service.release_by_token(
        db, item.id, lease_token=report.lease_token
    )   # 409 on mismatch; idempotent 200 if already released
```

Four properties, each earned from a prior finding:

- **Owner-only.** A non-owner slot releasing someone else's lease is Finding 10's shape
  through a new door. Mismatched `reporting_slot_id` → 409. See §3.1b — this is
  *cooperative validation*, not an authenticated invariant.
- **Attempt-scoped** (§3.1a). The token names the *acquisition*, not the item.
- **Idempotent.** A repeat of the same token for an already-released lease is a 200, so a
  duplicated report is harmless.
- **Does not *move* `dispatch_status`, but is *gated* by it** (§3.1c). The two directions are
  not symmetric, and the draft conflated them by calling release "independent of
  `dispatch_status`". Reaching a terminal status must never auto-release — `escalate`
  broadcasts that "this item's owner session may still be working" — and releasing must never
  escalate. But a terminal status is a **precondition** for release, because a non-terminal
  item can still be sent back for more work.

`_dispatch_brief` gains the corresponding required step alongside the existing `triaging` /
`pr_opened` / `blocked` instructions, and must include the item's current `lease_token`
verbatim (the agent cannot derive it).

#### 3.1a The lease token — release must name the attempt, not the item

**Added 2026-08-02 after impl-agent review; this was a correctness hole in the draft above.**

`release(db, item_id)` keys on `leased_item_id` alone
(`github_workspace_service.py:107-111`), so it cannot distinguish one dispatch attempt of an
item from the next. That is exploitable **without any operator action**:
`github_watcher_service.py:74-78` calls `reset_for_retry` whenever an `escalated` or
`failed` item's GitHub `updated_at` advances — an issue comment suffices. So:

1. item escalates; its worktree stays leased
2. someone comments on the issue → watcher re-pends it → dispatch **re-acquires** and a new
   owner session starts work in the worktree
3. the *first* attempt's agent finally gets round to reporting `workspace_released`
4. the live lease is released, and the next `acquire` runs `reset --hard` under a working
   agent

That is Finding 10 again, through the very door §3.1 was written to close. Same family
once more: `work_item_id` answers *which item?* when the question is *which acquisition?*

**Fix.** `acquire` generates a fresh opaque token per acquisition (`secrets.token_hex(8)`)
and stores it on the workspace row. `release_by_token` releases only on an exact match:

| Situation | Result |
|---|---|
| token matches the current lease | released, 200 |
| token names a lease already released, nothing leased now | 200 (idempotent) |
| token does not match the **current** lease | **409**, lease retained, logged |

#### 3.1a-bis Retry must wait for release — the token alone does not fix this

**Added 2026-08-02 after the second impl-agent review, and it is right: §3.1a fixed the wrong
half.** The token makes a *stale release* harmless. It does not stop the **retry** from
overtaking the release, and combined with §3.1c the two amendments deadlock.

Trace it with both amendments in force:

1. item is `escalated`, lease held, token T1
2. watcher sees an advanced `updated_at` → `reset_for_retry` → `dispatch_status = "pending"`
3. the old owner now tries to release. **409** — §3.1c permits release only from a terminal
   status, and the item is no longer terminal. *The legitimate releaser has been locked out by
   a state transition it did not cause and cannot see.*
4. dispatch re-acquires. `acquire` returns the **existing** lease unchanged via its
   `held is not None` early return (`github_workspace_service.py:67-73`) — so **T2 is never
   minted, and `reset_workspace` never runs**. The new owner inherits the previous attempt's
   dirty tree, believing it has a clean one.
5. `reclaim_stale` cannot help either: `pending` is not in `_RECLAIMABLE_STATUSES`.

So the lease is stuck with a token nobody can use, and the *worst* outcome is not the wedge —
it is step 4 silently skipping the reset that isolation depends on.

**Fix: retry becomes a two-phase transition, and dispatch never re-acquires a leased
workspace.**

- `reset_for_retry` no longer jumps straight to `pending`. If the item still holds a lease it
  moves to a new durable state **`retry_requested`**, which is:
  - **terminal for release purposes** (§3.1c) — so the old owner can still release, and is
    reminded to (§6);
  - **added to `_RECLAIMABLE_STATUSES`** — so the crash backstop can clear it;
  - **not dispatchable** — `dispatch_pending` selects `pending` only, so it cannot be picked
    up while leased.
- Once the lease is released (by report or backstop), the item moves `retry_requested` →
  `pending` on the poll path, and the next dispatch acquires **fresh**, minting T2 and running
  `reset_workspace`.
- If the item holds no lease when retry is requested, it goes straight to `pending` as today —
  no behavioural change for the common case.

This is a **new `dispatch_status` value**, which the standing constraint forbids. The
constraint exists to stop values being invented for *reporting* convenience, and it was right
to block `workspace_released` (§3.1). Here the state is genuinely new: "wants re-dispatch, not
yet dispatchable, still owned". Encoding it in `pending_reason` would not work — `pending` is
exactly the status that makes it dispatchable. **This is called out as a deliberate exception
to be approved with the plan, not slipped through**, and it is confined to PR1.

Note the corrected test. The stale-replay test in §5.2 asserted a 409 on T1 after
re-acquisition — but with this fix **re-acquisition cannot happen while T1 is outstanding**,
so the test must instead assert that no second attempt starts until T1 is released: after the
watcher re-pend, the item is `retry_requested`, the lease is still held, `dispatch_pending`
dispatches nothing, and `reset_workspace` has not run. Then release with T1 → the item becomes
`pending` → the next dispatch mints T2 and *does* reset. The original 409 assertion survives
only for a genuinely stale token (release twice with T1 across a completed re-acquire).

Any disagreement retains the lease — the same safe-direction rule as §3.2's conjunction. A
third new column, `lease_token`, joins the two in §3.2.

#### 3.1b "Owner-only" is cooperative, not authenticated

`POST /dispatch-status` takes `reporting_slot_id` from the **request body**
(`app/api/v1/agent_teams.py:267-271`); there is no session binding on the endpoint. The MCP
shim derives it from the caller's own registration
(`mcp_shim/agent_mail_server.py:601-627`), so an agent going through `deck_*` tools cannot
spoof it — but a direct HTTP caller can pass any slot id.

So the owner check is **defence against a confused agent, not against a hostile one**, and
this spec does not claim otherwise. It is stated rather than fixed because the endpoint is
bound to localhost and every other report status on it has the same property — adding
authentication to one branch would imply the others are protected. Endpoint-wide
authentication for `/dispatch-status` is recorded in §9 as owed before autonomy runs
against anything but a trusted local team.

#### 3.1c When release is legal — and why the dirty-tree veto applies here too

**Added 2026-08-02 after impl-agent review.** §3.1 said *what* the report does and never said
*when* an owner may send it. That is not a documentation gap; two concrete flows break.

**Not at `pr_opened`.** `_record_failed_verification_attempt`
(`github_verification_service.py:471-478`) sets `dispatch_status` back to `dispatched` when a
check fails at an already-verified SHA, and an approval round
(`record_approval_round`) can likewise send an owner back for more work. An owner that
released at `pr_opened` would then need a workspace it no longer holds.

**Decision (user, 2026-08-02): hold until terminal, with a dirty-tree veto.**

- Release is legal **only** once the item is in a terminal state for that owner —
  `merged`, `completed`, `escalated`, `failed`, or `retry_requested` (§3.1a-bis). Reporting
  `workspace_released` while `dispatch_status` is `dispatched`, `verifying`,
  `ready_for_review` or `awaiting_human_review` is a **409**, naming the current status.

  **`failed` is in that list deliberately** (second impl-agent review). Dispatch releases the
  lease on a failed launch *only when `tmux_target is None`*
  (`github_dispatch_service.py:282-285`) — when a pane **was** created, the lease is retained on
  purpose, because something may be running in it. Under the amended protocol that state would
  otherwise have no release path at all: `failed` is reclaimable by the backstop, but the
  backstop needs 6h and a dead pid, and the agent in that pane is the one entity that knows
  whether it is doing anything. So it must be able to report. The release reminders in §6 cover
  `failed` for the same reason.
- Release is **refused (409) when `git status --porcelain` is non-empty.** The response names
  the dirty paths and instructs the agent to commit and push, or to say so in its
  `status_note` and leave the lease held for an operator.

The veto matters most exactly where the draft was weakest: `blocked` → `escalate` is the
*likeliest* moment for an agent to release, and the likeliest moment for uncommitted work to
exist. §3.2 already vetoes a dirty tree for the **backstop**; applying it only there would
mean Deck protects uncommitted work from its own sweep but lets an agent discard it by
reporting. That asymmetry has no justification, so it goes.

**Accepted cost:** on a size-1 pool, a workspace stays leased across the whole
verify-and-review window. That is throughput, and §6 already offers the cheap fix (more
worktrees at ~2.4 GB each). It buys the elimination of any re-acquire path — nothing in G2
ever needs to hand a worktree back to an owner mid-item.

### 3.2 The backstop

`reclaim_stale`'s gate changes from `slot_has_live_owner_session` to a conjunction. **All**
must hold to release:

1. item in `_RECLAIMABLE_STATUSES` (now including `retry_requested`, §3.1a-bis), **and**
2. `leased_at` older than `STALE_LEASE_BACKSTOP_SECONDS` (6h), **and**
3. the recorded owner process is dead, **and**
4. the lease's `lease_token` is still the one the *current* owner was briefed with
   (§3.2a), **and**
5. `git status --porcelain` on the worktree is empty.

Condition 5 applies only where it is meaningful: `reset_workspace` already no-ops on
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

So the pid is captured **onto the lease** at dispatch and read back from `/proc`. Four new
nullable columns on `github_workspaces`:

- `lease_token` — per-acquisition token (§3.1a)
- `leased_owner_pid` — the owner session's pid
- `leased_owner_proc_start` — field 22 of `/proc/<pid>/stat`, guarding pid reuse
- `lease_last_owner_contact_at` — last owner status report on this lease (§3.2a)

Plus two on `github_work_items` for delivery tracking (§4.1a): `brief_delivery_nudge_at` and
`brief_delivery_nudge_count`.

`pid_max` on this host is 4194304, so reuse is unlikely; the pairing makes "alive" mean
*this* process rather than *a* process. This is Finding 18's trap one level down — an
identifier whose uniqueness is assumed rather than guaranteed.

**Correction (2026-08-02, impl-agent review): the pid cannot be captured "at acquire time".**
`acquire` runs at `github_dispatch_service.py:222`, **before** `launcher(...)` at `:251`. On
the spawn path the owning pane does not exist yet, so there is no pid to record; the draft's
wording was simply wrong about the ordering.

The pid is therefore written in a **second step, after the launch result is known** — the
same place `dispatched_at` is already set (`:288`). Note `AgentTeamLaunchResultItem`
(`schemas.py:2336-2349`) carries `tmux_target` but **no pid**, so implementation must either
add a pid field to the launch result or resolve `tmux_target` → `pane_pid` through
`agent_bridge/discovery.py:92`. Adding it to the result is preferred: discovery is a second
tmux round-trip that can race the pane's own startup.

Required behaviour when the pid is unavailable (launch returned no target, discovery found no
match, or `/proc` is unreadable):

- `leased_owner_pid` stays **NULL**, and dispatch proceeds — a missing pid must never fail a
  dispatch that otherwise succeeded.
- A NULL pid makes backstop condition 3 **unsatisfiable**, so the lease is retained and only
  an operator can clear it. Unknown liveness is treated as "alive", which is the safe
  direction.
- The same holds for every lease that exists *before* this migration: the new columns are
  NULL on all of them, so no pre-existing lease can be auto-reclaimed. Item 23's lease is in
  exactly this state, and retaining it is correct.

**Parsing `/proc/<pid>/stat` must not use a naive `split()`.** Field 2 (`comm`) is
parenthesized and may itself contain spaces or parentheses. Field 22 is located by splitting
the remainder **after the last `)`** in the line:

```python
raw = pathlib.Path(f"/proc/{pid}/stat").read_text()
fields = raw[raw.rindex(")") + 2:].split()
starttime = fields[19]          # field 22 overall = index 19 after state
```

`FileNotFoundError` / `ProcessLookupError` → the process is dead (condition 3 satisfied). Any
*other* `OSError` → **unknown**, treated as alive, lease retained.

#### 3.2a A replacement owner must not be mistaken for a dead one

**Added 2026-08-02 after the second impl-agent review; the finding is correct and the fix
needs care, because the obvious fix relapses into Finding 19.**

The hole: the recorded pid can be dead while the *item* is very much alive. A slot's standing
session is restarted (host reboot, `codex` reconnect, an operator killing a hung pane), the
replacement session re-registers against the same durable member id, and the agent resumes the
item. Now the lease records attempt N's pid — dead — while attempt N's *work* continues under a
new process. Dead pid + clean tree at a quiescent moment → the backstop releases the lease → the
next `acquire` runs `reset --hard` under a live agent. Finding 10 once more, and this time the
backstop itself is the weapon.

**Why the reviewer's proposed fix cannot be used as stated.** It asks for "fresh confirmation
that no current live/nudgeable owner-slot session exists". That is `slot_has_live_owner_session`
rebuilt under a new name — the predicate **Finding 19 proved is permanently true** under
one-session-per-slot. Adding it as a conjunct would make the backstop unfireable and restore the
wedge this entire design exists to remove. The finding is real; that mechanism would undo §1.2.

**Fix: bind the *lease* to the owner session's identity, not to the slot's liveness.** The brief
already carries `lease_token`, and only the briefed owner has it. So:

- When an owner reports **any** status for the item (`triaging`, `in_progress`, `ack_received`,
  `pr_opened`, …), the endpoint stamps `lease_last_owner_contact_at` on the workspace row.
- Backstop condition 4: release only if there has been **no owner contact** on this lease since
  `leased_at`, or the last contact is itself older than the 6h threshold.

That distinguishes the two cases the pid cannot. A replacement owner that resumed the item is,
by definition, an owner that *reports* — the §3.3 evidence is that every one of 28 items
reported. A genuinely crashed owner stops reporting, and its contact timestamp ages out. Where
the pid asks "is a process alive?", this asks "has the thing holding this lease spoken
recently?" — which is the question the backstop actually needs, and it stays false-under-crash
rather than true-by-design.

A fourth column, `lease_last_owner_contact_at`, joins the three in §3.2. It is *cheap* — the
report endpoints already write to the item on every status — and it does not depend on session
discovery, tmux, or `last_seen_at`, so Finding 17's staleness cannot corrupt it.

**Residual risk, stated rather than fixed:** an owner that resumes work after a restart and then
does 6h of silent work with a clean tree at the sampling moment is still reclaimable. That
requires simultaneous pid death, 6h silence, and a clean tree — and the operator-visible
staleness in §6 is the intended detector. Narrowing further means asking the agent to heartbeat,
which is a bigger change than this design should carry.

**Why the conjunction, not either signal alone.** The two conditions fail in opposite
directions. A stale pid resolving to an unrelated live process says "alive" → the lease is
held too long → throughput lost. A clean tree says "idle" → release → possible
`reset --hard` under a working agent → corruption. Requiring both means the **safe** error
dominates: any disagreement retains the lease.

Note what condition 5 is really doing. Git-quiescence was declined as the *primary*
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
reported `blocked` and stopped" — and an agent that is still reporting can be *asked* to
release. Note the asymmetry §3.1c introduces: the `blocked` report itself does **not**
release, because that is the likeliest moment for uncommitted work to exist. It escalates,
and the *subsequent* `workspace_released` (dirty-tree veto satisfied) returns the lease. So
one report becomes two, which is a real cost in agent compliance — mitigated by §6's repeated
reminders and, if an agent simply stops, the force-release path.

The backstop therefore covers the **uncommon** case (host OOM as in Finding 11, or a crash
mid-work), which is why its threshold can be generous rather than aggressive. That is the
safe direction: an early release under a live agent is Finding 10 again.

---

## 4. Delivery guarantee (PR2)

Dispatch passes `reuse_existing=True` and keeps `acquire` plus the brief naming the leased
worktree path.

It does **not** drop `slot_prompt_overrides` — see §4.0, which corrects the draft.

Three delivery defects must close in the same PR, or the flip makes brief delivery **less**
reliable than the spawn path it replaces.

### 4.0 `slot_prompt_overrides` must be retained for the spawn fallback

**Corrected 2026-08-02 after impl-agent review. As drafted, this PR would have shipped a
regression, and §7 step 4 walks straight into it.**

`reuse_existing=True` does not mean "a session will be reused" — it means "reuse one **if a
match exists**". When the slot has no wakeable session, `plan_launch` still yields
`action=spawn`, and `_execute_plan_item`'s spawn branch computes
`bootstrap_prompt = prompt_override or await self._bootstrap_prompt(...)`
(`agent_team_service.py:606-608`). With the override dropped, the new agent starts with the
generic team prompt: **no issue number, no worktree path, no reporting instructions, no lease
token.**

This is not theoretical. All six live slots have `bootstrap_prompt = NULL`, so
`_bootstrap_prompt` returns the generic three-line text — and §7 step 4 deliberately
dispatches to *a slot with no standing session*, which is precisely the spawn path.

The generic prompt does end with "check your inbox with `deck_check_inbox`", so a spawned
agent may find the brief anyway. That is a **mitigation, not a guarantee** — it races the
session's own startup and depends on the model choosing to comply — and PR2 exists to replace
a guarantee with something at least as strong.

**So:** dispatch keeps passing `slot_prompt_overrides={owner_slot_id: brief}`. It is
*ignored* on the reuse branch (which is Finding 13, and why the mail path exists) and
*load-bearing* on the spawn branch. The brief is sent as mail **and** passed as the spawn
prompt; the two paths are complementary, not redundant, and neither is removed.

A test must pin this: dispatch to a slot with no wakeable session must still spawn with a
prompt containing the issue number and the leased worktree path.

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

**A nudge is not a delivery guarantee** (impl-agent review, and correct). A successful
`tmux send-keys` proves keystrokes were written to a pane — not that the agent read the
brief. So the non-throttled wake is paired with a **delivery check**, specified in §4.1a.

**One part of that review comment is declined.** It also proposed not starting acknowledgment
timing until the receipt is read. `dispatched_at` is set at
`github_dispatch_service.py:288` and drives `_nudge_leader_for_ack` → `leader_ack_timeout`
(`:689, :650`). Gating that clock on a read receipt means an **unread brief produces silence
instead of an escalation** — it converts a loud, already-implemented failure into a quiet one.
The clock stays where it is; the unread receipt gets its *own* escalation reason, so an unread
brief is now detected by two independent mechanisms rather than neither. §4.1a states how the
two timers coexist without masking each other.

#### 4.1a Delivery evidence: three corrections to the receipt check above

**Added 2026-08-02 after the second impl-agent review. All three sub-claims verified and all
three hold.**

**(1) The receipt is the wrong signal on the spawn path, so it must not be the only one.** A
spawned owner receives the brief as its *prompt* (§4.0) and may act on the issue correctly while
never opening its mailbox — `MailReceipt.read_at` stays NULL and `brief_unread` fires against an
agent that is working. **So delivery is proven by either of two things: the receipt's `read_at`,
or any owner status report for the item.** A report is strictly stronger evidence than a read
receipt — it proves comprehension, not just retrieval — so it must count. This reuses the same
timestamp §3.2a introduces (`lease_last_owner_contact_at`), which is not a coincidence: "has the
owner spoken?" is the question in both places.

**(2) `last_nudge_at` cannot carry a third timer.** One column already multiplexes the leader-ack
nudge and the owner-idle nudge (`github_dispatch_service.py:645-663`), with the ack branch
`continue`-ing before the idle branch is reached. Adding a delivery timer to it would make the
three interfere: whichever fires first resets the shared clock, and `escalate` then reports
whichever reason its branch happened to be in. **Delivery gets dedicated fields** on
`github_work_items`: `brief_delivery_nudge_at` and `brief_delivery_nudge_count`. The bounded
retry is then countable rather than inferred from a timestamp comparison.

**(3) `leader_ack_timeout` can mask `brief_unread`, permanently.** The ack branch escalates first
and `escalate` is terminal, so an undelivered brief is reported as *the leader failing to ack* —
a wrong diagnosis pointing at the wrong actor, which is precisely the Finding 14 cost (two
findings spent on a misattributed stall). Fix, and this is the narrow form of the review's
"anchor leader-ack timing to receipt/first owner activity":

- **Delivery is evaluated before ack.** If the brief is undelivered by test (1) and the delivery
  retries are exhausted, escalate `brief_unread` and skip the ack branch for that item on that
  pass.
- The ack clock keeps its `dispatched_at` anchor, so it still fires when delivery *succeeded* and
  the leader is simply silent. Nothing becomes quieter; the two failures just stop being
  confused for one another.

The declined half of the earlier comment stands: neither timer is gated on the other's evidence,
because that is how a loud failure becomes a silent one.

### 4.2 `_nudge_session_for_member` picks an arbitrary pane

It orders by `last_seen_at desc` and takes the first nudgeable session (`:1081-1085`).
Slot 6 currently carries three sessions under one `member_id`, all stamped within
microseconds of each other by `sync_observed_sessions` one line earlier — so which pane
receives the prompt is effectively a coin flip today.

Converging to one session per slot fixes this by construction, but the **migration** starts
from three. PR2 must converge the slot explicitly rather than assume it.

**And convergence must be enforced in code, not just performed once at deployment**
(impl-agent review, and correct). A deployment step is a one-time act; duplicates return the
next time codex auto-reconnects to a durable member id — which is exactly the respawn-hygiene
failure already recorded in memory. A slot silently back at two sessions restores the coin
flip with nothing detecting it.

**Decision (user, 2026-08-02): dispatch blocks on ambiguity.** Before briefing, dispatch
counts the owner slot's *nudgeable* sessions (the `_session_can_nudge` predicate,
`agent_mail_service.py:595`). If more than one qualifies, the item is **not** dispatched: it
takes a new `pending_reason` of `queued_ambiguous_sessions` and a `status_note` naming the
competing tmux targets, so the UI shows which panes to converge.

This is chosen over persisting the briefed session on the lease, which would work but would
re-introduce a per-item session reference — the identity §2.5 deliberately withdrew (Finding
18). Refusing to guess costs a stalled queue until an operator acts; guessing costs a brief
delivered to the wrong pane, which is undetectable. Note the failure mode this replaces is
*silent*, so blocking is strictly more visible even though it stalls.

The ambiguity check must be a **precondition, not a post-hoc reconciliation**: it runs before
`acquire`, so an ambiguous slot never leases a workspace it cannot be briefed about.

**And it must read fresh evidence, or it is Finding 17 rebuilt** (second impl-agent review, and
this one is sharp). `dispatch_pending` never calls `sync_observed_sessions` — confirmed by grep
across `github_dispatch_service.py` and `github_watcher_service.py`. So the check would count
rows last refreshed whenever a human opened the Agent Mail page, and a slot that has *since*
grown a second pane would read as unambiguous. Dispatch would then proceed and hand the brief to
`auto_nudge_members`, which **does** call `sync_observed_sessions` first (`:1131`) and so nudges
an arbitrary pane from the freshly-discovered set. The stale check would pass and the live
delivery would coin-flip — the exact skew that made Finding 17 worth recording.

So the ambiguity check **calls `sync_observed_sessions` itself, immediately before counting**,
and **fails closed**: `sync_observed_sessions` swallows discovery failures with an early return
(`:354-356`), so "the sync did not raise" is not evidence that discovery worked. If discovery
yields no observed sessions at all for a slot that mail believes has some, the item is held with
`queued_ambiguous_sessions` rather than dispatched on the assumption that zero means zero.

This is the concrete instance of the memory rule: *for any predicate gating a destructive or
irreversible action, confirm at least one writer of its input runs on the same schedule as the
consumer.* Here the consumer is dispatch, so dispatch must do the writing.

---

## 5. Testing

The strategy is shaped by *why* the existing suite passed while the code was broken. 239
tests pass in `tests/agent_teams/` today (baseline, 2026-08-02). Finding 13 lived under a
green suite, and its canary asserted the bug as the requirement.

### 5.1 Rewritten, not extended

| Test | Why it is wrong now |
|---|---|
| `test_dispatch_proceeds_with_only_standing_session` (`test_github_dispatch_service.py:1256`) | Asserts a second session is spawned when a standing one exists — encodes Finding 13. Becomes: **the brief reached the standing session** (a `MailReceipt` for the owner member, `reuse_existing=True`, exactly one session after dispatch). |
| `test_reclaim_releases_non_working_item_without_live_owner` (`test_github_workspace_service.py:211`) | Monkeypatches the deleted predicate. Becomes the **five**-condition conjunction (§3.2, incl. owner-contact recency). |
| `test_reclaim_retains_non_working_item_with_live_owner` (`:236`) | Same. Becomes: retained because the pid is alive, **or** the owner reported recently, **or** the tree is dirty. |
| `test_queued_owner_session_dispatches_after_session_goes_offline` (`:1299`) | Tests a queue state that no longer exists (`queued_owner_session_live`). Deleted. |

### 5.2 New tests, each pinned to a finding

- **The skew test (Finding 17; owed from PR A §6).** Live pid + `last_seen_at` past TTL —
  a deliberately constructed *skew*, not a plainly-live or plainly-offline fixture. This is
  the class of defect fixtures hide by construction, since every test supplies its own
  timestamps.
- **Backstop conjunction, five cases.** dead+silent+clean → release; alive+clean → retain;
  dead+dirty → retain; dead+clean+recent-contact → retain (§3.2a); within-threshold → retain. The three *retain* cases are the ones
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

Added after the impl-agent review, one per amendment above:

- **Retry does not overtake release (§3.1a-bis) — the highest-value test in this PR.** Acquire
  for item X → token T1 → escalate → drive a watcher re-pend with an advanced
  `github_updated_at` (`github_watcher_service.py:74-78`) → assert **all** of: item is
  `retry_requested`, the lease is **still held with T1**, `dispatch_pending` dispatches nothing,
  and **`reset_workspace` has not run**. Then release with T1 → item becomes `pending` → next
  dispatch mints a **different** token and *does* reset. The `reset_workspace`-not-run assertion
  is the load-bearing one: that is the silent isolation loss.
- **Via the watcher, not the operator.** The re-pend above must go through watcher reconcile
  rather than calling `reset_for_retry` directly — the point of the finding is that no human is
  involved. A second case covers the manual `POST .../retry` endpoint reaching the same state.
- **Genuinely stale token still 409s (§3.1a).** After a *completed* release-then-reacquire
  cycle, a replay of T1 → 409, lease retained. This is what remains of the original replay test.
- **Replacement owner defeats nothing (§3.2a).** Lease with a **dead** recorded pid, clean tree,
  past threshold, but `lease_last_owner_contact_at` recent → **retained**. Its complement:
  same fixture with contact older than the threshold → released. This pair is the whole of
  §3.2a.
- **Delivery proven by report, not only by receipt (§4.1a).** Spawned owner, `MailReceipt.read_at`
  NULL, but a `triaging` report recorded → **no** `brief_unread` escalation. Complement: no
  receipt and no report past the bounded retries → `brief_unread`.
- **`brief_unread` is not masked by `leader_ack_timeout` (§4.1a).** Fixture where both are
  overdue → the escalation reason must be `brief_unread`. Guards the misattribution that cost
  two findings in Finding 14.
- **Delivery counters are independent (§4.1a).** A leader-ack nudge must not reset
  `brief_delivery_nudge_at` / `_count`, and vice versa.
- **Ambiguity check syncs first and fails closed (§4.2).** With a second pane present in
  discovery but **not** in the DB, dispatch must still block — proving the check re-synced rather
  than trusting stale rows. Second case: discovery returning nothing for a slot mail believes is
  populated → held, not dispatched.
- **`failed` with a live pane can release (§3.1c).** Launch fails with a non-None `tmux_target`
  → lease retained by dispatch → owner reports `workspace_released` → 200, released.
- **Force-release is compare-and-swap (§6).** Wrong/stale token → 409 naming both; correct
  token → released.
- **Finding 17's table (§2.4), one case per row.** Expired TTL + live pid → `connected`;
  expired + dead → `offline`; expired + NULL pid → `offline`; expired + unreadable `/proc` →
  `offline`; `mailbox_status == "offline"` + live pid → `offline`. The skew test above is the
  second row's live-pid case stated as a defect; this pins the rest so the rule cannot be
  satisfied differently by two implementers.
- **Release refused before terminal (§3.1c).** `workspace_released` while `dispatch_status`
  is `dispatched` / `verifying` / `ready_for_review` → 409, lease held.
- **Release refused on a dirty tree (§3.1c).** `escalated` + non-empty
  `git status --porcelain` → 409, lease held, response names the dirty paths. Pair it with
  the clean-tree case → 200.
- **Spawn fallback keeps the brief (§4.0).** Dispatch with `reuse_existing=True` to a slot
  with **no** wakeable session: the spawn prompt must contain the issue number and the leased
  worktree path. Guards the regression PR2 would otherwise ship.
- **Ambiguous slot blocks (§4.2).** Two nudgeable sessions on the owner slot → item stays
  `pending` with `pending_reason="queued_ambiguous_sessions"`, **no workspace leased**, and
  the note names both targets. The "no workspace leased" assertion is the load-bearing half.
- **NULL pid retains (§3.2).** A lease with `leased_owner_pid IS NULL` (i.e. every
  pre-migration lease, including item 23's) is never auto-reclaimed, even when dead+clean
  would otherwise pass.
- **`/proc` stat parsing.** A `comm` containing a space and a `)` must still yield the right
  `starttime` — pins the `rindex(")")` parse against a naive `split()`.
- **Unread brief escalates (§4.1).** Receipt `read_at` stays NULL past the bounded retries →
  `brief_unread`. Its complement matters too: a brief read on the first nudge must **not**
  escalate.

### 5.3 Mutation review

As on PR A. The 12-mutation pass caught M12's real gap there, and this diff touches the
same destructive path (`reset --hard` / `clean -fd` under a lease).

---

## 6. Risks and what stays unverified

- **The release is behavioral, twice over.** Isolation-by-brief (§2.3) and
  release-by-report (§3.1). The §3.3 evidence says agents report reliably; the backstop
  covers the crash case, not the common one.
- **The 6h threshold is a guess** — but the real exposure is **unbounded, not 6h**
  (impl-agent review; the draft's "stalls the scope for 6h" was wrong). The backstop is a
  *conjunction* including "owner process is dead". The common failure here is a standing
  session that stays **alive** and simply never reports — under one-session-per-slot that is
  the normal state of every slot — so condition 3 never holds, the sweep never fires, and the
  lease is held **indefinitely**. 6h bounds only the crash case; nothing bounds the
  forgot-to-report case.

  Three mitigations, all in PR1, because "indefinitely" is not an acceptable ceiling:

  1. **Repeated release reminders.** While an item is terminal (`merged` / `completed` /
     `escalated`) and still holds a lease, the poll path re-notifies the owner at
     `github_nudge_grace_seconds` intervals, quoting the `lease_token` and the exact
     `deck_report_dispatch_status` call. Reuses the existing nudge machinery
     (`_nudge_owner_for_progress`, `github_dispatch_service.py:714`).
  2. **Operator-visible staleness.** `GET .../workspaces` reports lease age and whether the
     owner has been reminded, so a forgotten lease is visible rather than inferred from a
     stalled queue — the Finding 14 lesson.
  3. **Force-release tooling.** An explicit operator endpoint that releases a lease
     regardless of the conjunction, logging who did it. This is deliberately **not**
     automatic: `abandon` and `reprobe` (PR A §2.10a/b) exist for the same reason, and the
     pattern of "give the operator a supported way out instead of DB surgery" is already
     established.

     **It takes the expected `lease_token` as a compare-and-swap guard, not just the workspace
     id** (second impl-agent review, and correct). An operator acts from a UI page that was
     rendered some time ago; between render and click the lease may have been released and
     re-acquired by a *new* owner. Workspace-id-only force-release would then destroy a live
     lease — the same stale-identity failure as §3.1a, arriving through the operator instead of
     the agent. Mismatch → 409 showing both tokens, so the operator refreshes and re-decides.
     The token is displayed by `GET .../workspaces` for exactly this purpose.

  890 GB free at ~2.4 GB per worktree also makes a larger pool cheap, but that is throughput,
  and it does not fix an unbounded hold — only mitigation 1 and 3 do.
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

1. **Migrate the DB — via the existing compatibility ladder, not by hand.**

   **Corrected 2026-08-02 after impl-agent review; the draft was factually wrong here, on the
   riskiest step in this list.** The draft said the project has no migration system, quoting
   `CLAUDE.md`'s "schema changes require deleting the db", and prescribed hand-applied
   `ALTER TABLE`. There **is** a system: `_run_sqlite_compat_migrations`
   (`app/database.py:290`) is an idempotent `PRAGMA table_info` → `ALTER TABLE ... ADD COLUMN`
   ladder with roughly thirty existing entries, invoked from `init_db` at `:458` on every
   startup. `CLAUDE.md` describes an intent the code outgrew.

   So the four new `github_workspaces` columns (`lease_token`, `leased_owner_pid`,
   `leased_owner_proc_start`, `lease_last_owner_contact_at`) are added as a new
   `github_workspaces` block in that ladder — the table has no entries there yet — using the
   established `_sqlite_columns(conn, "github_workspaces")` guard, and the two
   `github_work_items` delivery columns (§4.1a) join that table's existing block. Migration
   then happens **automatically on backend restart**, with three consequences that all favour
   it over hand-applied SQL:

   - it is idempotent and re-runnable, so a second restart is a no-op;
   - every other checkout (including `claude-deck-g1`) migrates itself, instead of silently
     diverging from the live DB;
   - no manual SQL is ever run against the file holding all 28 work items of soak evidence,
     which is the outcome the draft's caution was actually reaching for.

   Still true and still the reason to care: the live DB must **not** be recreated. It holds the
   evidence that made Findings 17, 18 and 19 provable.
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
   leased worktree; `workspace_released` with the correct `lease_token` returns the lease; a
   repeat of that token is a 200; a *stale* token is a 409 with the lease retained.

Note step 4 exercises the **spawn** path (§4.0), not the reuse path — it dispatches to a slot
with no standing session. Both paths need one real dispatch before autonomy resumes, so a
sixth step is owed: dispatch a second item to a slot that **does** carry a standing session,
confirming reuse briefs by mail and that no second pane appears.

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

- ~~**Finding 19** must be recorded in the soak run log alongside Findings 17 and 18.~~
  **Done** (`b87be45`), together with the three PR A coupling notes it resolves (§2.4,
  §2.5a, §4.1b).
- The **`_validate_adoption_is_available` blind spot** (§2.3, consequence 2) is recorded,
  not fixed. It weakens an occupancy check that no longer gates anything destructive under
  this design, but it will mislead a future reader.

New from the impl-agent review (2026-08-02):

- **`/dispatch-status` has no authentication** (§3.1b). Owner-only release is cooperative
  validation. Endpoint-wide auth — binding a report to the calling session rather than
  trusting a body field — is owed **before autonomy runs against anything but a trusted local
  team**, and is out of scope here because fixing one branch would imply the other eight are
  protected.
- **`CLAUDE.md` is wrong about migrations.** It says "No database migration system — schema
  changes require deleting the db"; `app/database.py:290` has had an idempotent ladder for
  some time (§7 step 1). The line should be corrected in a separate `docs:` commit — not in a
  G2 PR, since it misleads every future reader of the repo, not just this design.
- **A sixth deployment step is owed** (§7): step 4 exercises only the spawn path, so one
  dispatch to a slot *with* a standing session is needed before autonomy resumes.

New from the second impl-agent review (2026-08-02) — approvals needed, not just work:

- **⚠️ `retry_requested` is a new `dispatch_status` value** (§3.1a-bis), which the standing
  impl-agent constraint forbids. It is the one deliberate exception in this design and must be
  **approved explicitly with the implementation plan**. If it is refused, the retry/release
  deadlock needs a different fix — the deadlock itself is not optional, since it silently skips
  `reset_workspace`.
- **PR A's §2.9 says a force-release endpoint is "deliberately not built"**
  (`2026-07-29-…-design.md:797`, and the invariant argument at `:569`). §6 mitigation 3 reverses
  that. The reversal is sound — PR A's reasoning was that release must be licensed by process
  absence, which Finding 19 retired — but PR A's text must be amended so the two documents do
  not contradict each other. Owed as a `docs:` amendment alongside PR1.
- **UI surface for the new columns.** `GET .../workspaces` must expose `lease_token`,
  `lease_last_owner_contact_at` and lease age (§6 mitigation 2, and the force-release
  compare-and-swap depends on the operator seeing the token). Frontend work is otherwise out of
  scope for both PRs; this is the exception.
