# Autonomous Dispatch — Hardening Phase & Unattended Soak (Design)

**Status:** Approved design — ready for implementation planning.
**Date:** 2026-07-06
**Branch:** `feature/autonomous-github-dispatch` (continue hardening the integration branch; do NOT merge to master until the soak clears).
**Depends on:** the e2e gate (all hard gates + edge scenarios PASS; 8 bugs fixed). Supersedes the "defer" disposition of the three findings below.

## Purpose

Two workstreams, gated in sequence:

1. **Code hardening** — resolve the three deferred dispatch findings so the loop is safe under *unattended, auto-merging* operation.
2. **Unattended soak** — gather real-world evidence, against tizonia's live `roadmap:v1` issues, that autonomy is ready for prime time on master.

The auto-merge target (below) is why all three findings are in scope now: under `merge_policy=auto`, leader-ack + CI become the *only* gates before an irreversible public merge, so each finding moves onto the safety-critical path.

## Deferred findings being resolved (tracked in issue #280)

- **#1 Leader-ack gate brittleness** — `docs/superpowers/specs/2026-07-06-dispatch-open-finding-leader-ack-timeout.md`
- **#2 §6 reachable-but-idle monitor** (stub since Phase A)
- **#3 Stale `ready_for_review` on post-promotion red head** — `docs/superpowers/specs/2026-07-05-dispatch-open-finding-stale-ready-state.md`

Findings #1 and #2 are the **same subsystem** (the §6 monitor's liveness/idle/ack lifecycle) and are designed together in §2. Finding #3 is a **separate merge-boundary guard** (§3).

---

## Key decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Soak merge mode | **Both, in sequence** — human-merge window first, then auto-merge window. |
| Leader-ack timeout behavior | **Nudge-then-escalate, uniform for both pipelines.** Only the timeout *duration* differs (design gets a generous multiplier). Never auto-proceed without ack (would reopen the C1 no-unreviewed-design gate under auto-merge). |
| Owner-idle behavior | Same nudge-then-escalate lifecycle as ack (identical structure). Nudge is a **question, not a kill** (T-S4 lesson). |
| Finding #3 scope | **Option B only** — re-confirm head-green at the merge boundary. NOT option A (general re-verify-on-head-change). |
| Soak finish line | **Loop reliability across all `roadmap:v1` issues**, not solving every issue. Easy issues merge; hard ones escalate cleanly and recoverably. |
| Design-pipeline coverage | **Seed 1–2 real design issues** as prerequisites for the hardest v1 issues (only way to get live soak evidence for the design-tier ack hardening). |

### Explicitly out of scope (YAGNI)

- Finding #3 **option A** (general re-verify-on-head-change every poll). Revisit only if the human-merge soak shows the cosmetic "reads ready but is red" wrinkle actually causes confusion.
- Growing the team beyond the current 2 slots (Leader + Generalist). If the soak shows specific issues need specialist slots, that's a *next* cycle with evidence.
- The interview-mode conversational team/autonomy setup (separate spec).

---

## §2 — The §6 monitor: unified wait / nudge / escalate lifecycle (findings #1 + #2)

### Problem

`GithubDispatchService.monitor_dispatched` today knows only one thing: `wake_state == "offline"` (heartbeat stale = dead) → `escalate("leader_offline"|"owner_offline")`, subject to a post-dispatch registration grace. It has **no concept of "waiting on something with a deadline."**

The *wait-for-ack* logic lives entirely in the **owner's prompt** (`_leader_ack_instruction`: "...wait for acknowledgment before {before}"). The owner improvises how long to wait and when to give up — which is why T-S8 (owner gave up after ~1.5 min, self-reported `blocked` → misleading `plan_blocked` escalation) behaved differently from other runs. Wait-authority is in the wrong place.

### Design — move wait-authority into the brain's monitor

Add one lifecycle to `monitor_dispatched` that serves **both** the ack-wait (#1) and the idle-wait (#2), because they are structurally identical: *an alive owner is waiting on something; if it doesn't arrive within a tiered timeout, nudge once, then escalate (recoverably) if still stuck.*

| Wait kind | Applies when | Timeout | Nudge (once) | Escalate reason |
|---|---|---|---|---|
| **Leader-ack** (#1) | item `dispatched`, ack not yet observed | `ack_timeout` (code) / `ack_timeout × design_multiplier` (design) | brain pings the leader (wake/Agent Mail) | `leader_ack_timeout` |
| **Owner-idle** (#2) | owner alive (`wakeable`/`delivered_waiting`), `pr_number is None`, past a generous window | `owner_idle_timeout` | brain asks the owner "still progressing?" | `owner_idle_timeout` |

### Lifecycle semantics

- **Nudge-then-escalate, uniform.** On timeout, the monitor sends **one** nudge and records a nudge timestamp on the item. Only if still-unresolved after an additional `nudge_grace` window does it escalate. Both pipelines follow the same shape; design only stretches the ack duration via the multiplier. No "code proceeds without ack" branch.
- **Nudge is a question, not a kill.** The monitor never terminates a session. For owner-idle it *asks* ("making progress?"); an alive-but-slow owner that answers (heartbeat advances / any status report) **resets the clock** and is not escalated. This encodes the T-S4 lesson (never kill a working-but-slow agent) directly in code.
- **Escalation is recoverable.** `leader_ack_timeout` / `owner_idle_timeout` escalations follow the existing escalated→pending recovery + `POST /retry`. First-reason-wins guard (from `0ab472f`) still applies.
- **Truthful reasons.** `leader_ack_timeout` replaces the misleading `plan_blocked` seen in T-S8. Both new reasons join the canonical set (free-form strings today; used by `escalate()` and surfaced in the activity feed / dispatch-status API).

### "Ack received" detection (approved direction)

The monitor must know the owner's ack arrived, **without parsing mail bodies**. The owner already reports lifecycle via `deck_report_dispatch_status` (valid statuses today: `triaging`, `in_progress`, `pr_opened`, `blocked`, `handoff_initiated`, `handoff_accepted`, `revision_requested`).

- **Add an explicit `ack_received` status** the owner reports immediately after the leader acknowledges its plan. The endpoint records an `ack_received_at` timestamp (new nullable column on the work item) and clears the ack-wait. The monitor treats "`ack_received_at` set OR `pr_number` set OR status past triage" as *ack satisfied* (so a fast owner that jumps straight to `pr_opened` is not falsely flagged).
- The owner prompt (`_leader_ack_instruction`) is simplified: it still says "send the leader your plan and wait for acknowledgment, then report `ack_received`" — but it **no longer specifies a timeout or a give-up rule.** The brain owns timing.

### New settings (`backend/app/config.py`, generous defaults)

- `github_leader_ack_timeout_seconds` (e.g. 300)
- `github_design_ack_multiplier` (e.g. 3)
- `github_owner_idle_timeout_seconds` (e.g. 900)
- `github_nudge_grace_seconds` (e.g. 180 — the extra window after a nudge before escalating)

All are ceilings for the monitor; none live in the owner prompt.

### New/changed persistence

- `github_work_items.ack_received_at` (nullable timestamp) — set by the `ack_received` report.
- `github_work_items.last_nudge_at` (nullable timestamp) — set when the monitor sends a nudge; distinguishes "nudged, waiting out the grace" from "not yet nudged". (Reuse a single column for both wait kinds; only one wait is active on an item at a time — ack precedes any PR work, idle only applies pre-PR.)
- Both need `ALTER TABLE ADD COLUMN` guards in `_run_sqlite_compat_migrations` (the codebase's compat-migration mechanism; CLAUDE.md's "no migrations" note is inaccurate for added columns).

### Tests (representative)

- Ack not received, `now - dispatched_at > ack_timeout`, not yet nudged → nudge sent, `last_nudge_at` set, **not** escalated.
- Ack still not received, `now - last_nudge_at > nudge_grace` → escalate `leader_ack_timeout`.
- Design item uses `ack_timeout × design_multiplier` (a code item at the same age would nudge/escalate; the design item does not yet).
- Ack received (`ack_received_at` set) before timeout → no nudge, no escalation.
- Fast owner reports `pr_opened` without ever reporting `ack_received` → treated as ack-satisfied, no false ack escalation.
- Owner-idle: alive owner, no PR, past idle timeout → nudge; answers (heartbeat advances) → clock resets, not escalated; stays silent past nudge grace → escalate `owner_idle_timeout`.
- Registration grace (`147090b`) and offline (dead) escalation still hold; slow-but-alive owner (`wakeable`/`delivered_waiting`) is never escalated by the offline path.

---

## §3 — Finding #3: pre-auto-merge head re-confirm (Option B)

### Problem

In `GithubVerificationService._process_review_item`, under `merge_policy=auto`, Deck calls `client.merge_pull` trusting the earlier `ready_for_review` promotion. That promotion reflects `last_verified_sha` — the head *at promotion time*. A commit pushed after promotion can turn the head red, and Deck would merge a red PR. `process_scope` routes `ready_for_review` items only to `_process_review_item` (never back to `_verify_item`), so the post-promotion red head is invisible.

Non-critical under `merge_policy=human` (the human is the merge gate and sees the red PR on GitHub) — which is why it's only a cosmetic wrinkle there. It becomes **safety-critical** under `merge_policy=auto`.

### Design — a guard at the merge boundary

In `_process_review_item`, on the `merge_policy == "auto"` path **only**, immediately before `client.merge_pull` (currently ~line 202):

1. Re-fetch the PR's **current** head SHA.
2. **If head moved** (current head ≠ `item.last_verified_sha`) → do **not** merge. Demote to `verifying` (`dispatch_status="verifying"`, note why) and let the existing §7a loop re-check the new head next poll (green → re-promote; red → retry/escalate as normal).
3. **If head unchanged** → re-confirm check-runs on that head are still green (one API call). Green → merge as today. Not-green → demote to `verifying`.

### Why this shape

- Gated behind `merge_policy == "auto"` (line 181 already returns early for design / non-auto), so **human-merge is entirely untouched** — the cosmetic wrinkle stays, as decided.
- **Reuses `verifying` + `last_verified_sha`** — no new state, no new retry accounting. A demoted item re-enters the loop the e2e run already exercised.
- The guard is the last check before an irreversible public write — the correct place for it.

### Test

- Auto-eligible `ready_for_review` item, current head ≠ `last_verified_sha` → **not merged**, demoted to `verifying`.
- Auto-eligible item, head unchanged but check-runs now red → **not merged**, demoted to `verifying`.
- Auto-eligible item, head unchanged and green → **merged** (`auto_merged_at` set), unchanged from today.
- `merge_policy=human` path: guard is never reached (regression — behavior identical to today).

---

## §4 — The unattended soak protocol

### Finish line

**Readiness = loop reliability across every `roadmap:v1` issue Deck picks up**, NOT solving every issue. The bar:

- Easy issues (docs, small fixes) are worked and merged.
- Hard/blocked issues (e.g. #822 yt-dlp rewrite, #819 libspotify removal) escalate **cleanly and recoverably** — no silent stranding, no bad public write, correct escalation reason, monitor/guards all fire correctly.
- An agent failing to complete a hard issue is a **capability limit, not a loop defect**. The loop *misbehaving* — silent stranding, a bad write, a wrong-reason escalation, a guard that doesn't fire — is the only thing that fails the bar.

### Pre-soak cleanup (not soak work)

The current `roadmap:v1` open set includes **2 e2e artifacts**, not real work — clean these first:

- Leftover PR #857 / issue #856 (`agent-ready-e2e`, "CI signal grace-window validation rerun").
- Reconcile #834's state from prior runs.

The soak runs against the **14 real revival issues** (#816–#829, plus the seeded design issues below).

### Seeded design issues (design-pipeline coverage)

`roadmap:v1` currently has **zero `agent-design` issues**, so the soak would otherwise never exercise the design pipeline — where finding #1's hardest case lives (the C1 no-unreviewed-design gate + the design-tier ack timeout). Seed **1–2 real design issues** as **prerequisites for the hardest implementation issues**, so they do genuine de-risking work rather than being synthetic filler. Candidates:

- A design note for the **yt-dlp backend integration approach** (prerequisite for #822).
- A design note for the **libspotify removal blast-radius / v1 packaging strategy** (prerequisite for #819 / #824 / #825).

These flow through the design pipeline (`awaiting_human_review`, no CI, never auto-merged) and produce the design→implementation ordering the autonomous factory is meant to demonstrate.

### Window 1 — human-merge

`merge_policy=human`, `autonomy_enabled=true`, unattended, monitoring logs.

- Deck watches `agent-ready` + `roadmap:v1` issues, works them autonomously; a human merges after review.
- **Proves:** findings #1 (leader-ack nudge/escalate) and #2 (owner-idle nudge/escalate) under real load; clean label routing; clean recoverable escalation on hard issues; the seeded design issues exercise the design-tier ack timeout.
- **Per-issue outcome logged:** `merged` / `escalated(reason)` / `still-working`. Every escalation must be *explainable* (issue too hard, plan blocked, label removed, ack timeout with the leader genuinely absent). An **unexplained escalation or any silent stranding fails the window.**

### Window 2 — auto-merge

`merge_policy=auto`, only after Window 1 is clean.

- Flip the policy; Deck merges green PRs itself under `max_auto_merges_per_day`.
- **Proves:** finding #3 — the head re-confirm guard must fire **at least once** on a moved/red head. If the roadmap doesn't naturally produce one, inject a controlled "red commit after promotion" case (à la the original T-S3 inversion) to force the guard. Also proves the per-day auto-merge cap and per-slot concurrency queueing under real load.

### Safety invariants during the soak

- Autonomy toggled on deliberately, per window; reverted to `human` / off between windows.
- Branch protection on tizonia `master` remains enabled.
- No hand-editing of DB rows to steer scenarios — drive via labels/config only.
- Do not terminate a dispatched session or report on its behalf unless positively confirmed dead (process gone / `wake_state=offline`).

### Artifacts

- A soak **runbook** (structured like `2026-07-05-tizonia-e2e-testbed-plan.md`): pre-flight, cleanup steps, seeded-issue definitions, per-window enable/disable procedure, and the per-issue outcome table template.
- A live **run log** capturing each issue's outcome, every escalation with its reason and whether it was explainable, and the finding-#3 guard firing.

---

## Sequencing

1. Implement §2 (monitor lifecycle) + §3 (merge-boundary guard) with unit/integration tests; commit to `feature/autonomous-github-dispatch`.
2. Independent verification of the fixes against code + tests (orchestrator/verifier loop — don't trust "tests pass").
3. Pre-soak cleanup + seed the design issues.
4. Window 1 (human-merge) soak → clean per-issue log.
5. Window 2 (auto-merge) soak → guard fires, cap + concurrency hold.
6. Assess integration→master merge (closes #272/#275/#277 and #280) with the soak log as the citable evidence.

## Success criteria (phase exit)

- All three findings fixed, regression-covered, independently verified in code.
- Window 1: every `roadmap:v1` issue Deck touched ended in a merged PR or an *explainable, recoverable* escalation; zero silent stranding; zero bad public write.
- Window 2: finding-#3 guard demonstrably blocked at least one stale/red head; per-day cap and concurrency queueing observed; zero bad auto-merge.
- Soak run log written as the evidence artifact for the master-merge decision.
