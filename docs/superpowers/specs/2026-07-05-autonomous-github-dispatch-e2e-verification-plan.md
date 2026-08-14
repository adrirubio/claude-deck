# Autonomous GitHub Dispatch — End-to-End Verification Plan

**Date:** 2026-07-05
**Status:** Verification runbook (gate before merging the integration branch to master)
**Applies to:** `feature/autonomous-github-dispatch` integration branch (Phases A + B + C)
**Spec:** `2026-07-02-autonomous-github-dispatch-design.md`

---

## Why this exists

Every phase so far has been tested with **injected stubs** — fake GitHub clients, fake launchers, in-memory SQLite. No test, in any phase, has run the *actual* loop against a *real* GitHub repo with real credentials, a real spawned agent, and real CI. That's the single largest unverified risk in the feature, and it's exactly the class of failure unit tests can't catch: credential wiring, GitHub API response shapes that differ from our stubs, tmux/agent-spawn interaction under the scheduler, and timing (the 60s poll × 120s check-grace against real CI latency).

**This plan is the gate before `feature/autonomous-github-dispatch` → `master`.** It must pass before the phase issues (#272/#275/#277) close. It is deliberately a *manual, observed* runbook, not an automated suite — the point is to watch the real system do the real thing once, end to end, on a throwaway target where mistakes are cheap.

**Non-goal:** this is not a load test, a multi-repo test, or a soak test. One team, one repo, a handful of deliberately-shaped issues, observed by a human. Breadth comes later; correctness-in-reality comes now.

---

## Preconditions & setup

1. **A throwaway target repo** you own with write access — NOT a production repo, NOT SnazzyEmail or Claude Deck itself. Create `e2e-dispatch-sandbox` (or similar). It should have:
   - A trivial buildable project with a **real CI workflow** (a GitHub Actions job that runs a test/lint and can go green *and* be made to fail). A one-file Python or Node project with a single passing test is enough.
   - Branch protection **off** initially (we test the auto-merge-succeeds path first; we turn protection *on* later to exercise the durable-failure→human fallback).
   - The `claude-deck-ready` and `claude-deck-design` labels created.
   - Optionally `area:backend` / `area:frontend` labels if testing SME routing.

2. **`GITHUB_TOKEN`** configured (`backend/app/config.py` / env) — a PAT or GitHub App token with `repo` scope on the sandbox. Confirm it can read issues/checks and create/merge PRs on the sandbox repo *before* starting (a `curl` against the issues API is enough). This is the credential the Phase 0 spike could not exercise; verifying it here is a primary objective.

3. **A local checkout** of the sandbox repo at a known path, matching the `repo_path` you'll configure on the scope.

4. **An agent provider that actually runs** on this machine — codex-cli or claude-code, whichever you have working creds for. The spawned team member has to be able to do real work (read the issue, write code, run local checks, push, open a PR). Confirm a manual Agent Team launch into the sandbox works *before* turning on autonomy — that isolates "does dispatch work" from "does an agent work."

5. **Run the backend with the scheduler active** (`./scripts/dev.sh` or the backend alone). Consider temporarily lowering `github_dispatch_interval_seconds` (e.g. 20s) and `github_check_signal_grace_seconds` (e.g. 30s) so cycles are observable without long waits — note this in the run log, and test at least one scenario at the real defaults (60/120) to confirm timing assumptions hold.

6. **Observability ready:** the Autonomy tab (Phase C) open on the team, backend logs tailing, and the sandbox repo's Issues/PRs/Actions tabs open. You want to watch the same event from all three vantage points.

---

## Scenario matrix

Run these in order — each builds confidence for the next, and early ones isolate failures the later ones would confound. For each, record: what you did, what the activity feed showed, what the backend logged, what appeared on GitHub, and pass/fail with any deviation.

### S1 — Code issue, human merge policy (the happy path)
**The baseline. If this doesn't work, nothing else matters.**
1. Team with one code-capable slot (`area:backend` or leader-fallback), scope with `merge_policy=human`, autonomy ON.
2. Open a sandbox issue describing a trivial, real change (e.g. "add a `hello()` function returning 'hi'"). Label it `claude-deck-ready`.
3. **Watch for:** watcher creates a `pending` work item → dispatch routes it (check `routing_method`) → an agent session actually spawns in the right repo path → the agent triages, messages the leader, works the change → pushes a branch, opens a **draft PR** → item goes `verifying` → CI runs and goes green → item goes `ready_for_review`, draft flipped to ready → Agent Mail broadcast + "ready for review" notification fires → item stops (human merges manually).
4. **Pass criteria:** the item reaches `ready_for_review` with a real green PR, entirely unattended, and the brain did **not** merge it. Merge it yourself; confirm the watcher then marks it `merged`.

### S2 — Code issue, auto-merge, checks green
1. Same, but scope `merge_policy=auto`, branch protection still off.
2. **Watch for:** same up to green, then the **brain** merges via `PUT .../merge` → item `merged`, `auto_merged_at` set.
3. **Pass criteria:** the PR is auto-merged by Deck, once, and the daily-auto-merge counter increments. Open a second auto issue and confirm it also merges (counter > 1).

### S3 — Code issue, CI fails then is fixed (the retry loop — a Phase B fix)
**This exercises the exact dead-end the Phase B review caught and the fix closed.**
1. Open an issue whose obvious implementation will **fail CI** (e.g. "add a function" where the repo's test asserts a specific wrong-on-purpose contract), OR intervene to push a failing commit.
2. **Watch for:** item `verifying` → CI red → failure detail sent to the owner via Agent Mail → `retry_count` increments → item returns to `dispatched` → **and critically, is re-picked-up and re-verified on a later cycle** (this is the fix for the abandoned-item bug). The agent pushes a fix, CI goes green, item promotes.
3. **Pass criteria:** a CI-failed item does NOT get stranded in `dispatched` — it re-enters verification and can recover. If it stalls, that's a regression of the Phase B fix.

### S4 — Retry-budget exhaustion → escalation + notification
1. Issue that keeps failing CI past `max_verification_retries`.
2. **Watch for:** after the budget, item → `escalated` with `escalation_reason="retry_count_exhausted"` + an Agent Mail broadcast (§8). The activity feed shows the escalated row.
3. **Then test the retry action (Phase C):** click **Retry** on the escalated row → confirm it returns to `pending` and re-dispatches. **Also verify finding #1 from the Phase C review is fixed:** if that item ever had a pending handoff, confirm retry doesn't leave it wedged busy — ideally construct an escalation-during-handoff case and confirm retry recovers cleanly.

### S5 — Design issue (the design pipeline — Phase B §7b)
1. Issue labeled `claude-deck-ready` **+** `claude-deck-design`.
2. **Watch for:** item detected as `issue_type=design` → dispatched → owner writes a **doc** (not code) → opens a PR (not draft) → item goes straight to `awaiting_human_review` (**NOT** `verifying`) → **no CI polling happens** → "design PR ready for human review" notification → **no auto-merge even under `merge_policy=auto`**.
3. **Pass criteria:** design issues never touch CI or auto-merge, regardless of scope policy.

### S6 — Label removed mid-flight (UC11 / §4 step 3b)
1. During an in-flight `dispatched`/`verifying` item, **remove the `claude-deck-ready` label** on GitHub.
2. **Watch for:** next poll detects the removal → item `escalated` with `dispatch_label_removed` → a **direct** Agent Mail message to the current owner ("wind down, don't merge without re-confirming"). The running agent is *notified, not killed* (accepted design limitation).
3. **Pass criteria:** the human's "stop" gesture is honored — the item is escalated and the owner is told to wind down. Confirm a subsequent late `pr_opened` from that owner is **rejected** (409, the Phase C guard) rather than resurrecting the item.

### S7 — Auto-merge durable failure → human fallback (branch protection)
1. Turn branch protection **on** (require 1 review) on the sandbox. Scope `merge_policy=auto`.
2. Run a code issue to green.
3. **Watch for:** the brain attempts `PUT .../merge` → GitHub returns 403/durable → item falls back to the **human** path (notification, `ready_for_review`) with **no `escalation_reason` set** (this is a normal outcome, not a pipeline failure — per §7a).
4. **Pass criteria:** a protected branch that rejects auto-merge results in "waiting for a human," not an escalation.

### S8 — Zero check-runs / non-Actions timing (Phase B fix)
1. Momentarily: open a code PR-producing issue on a repo path where CI is slow to start, OR a repo whose CI is a classic commit-status (not a check-run).
2. **Watch for:** the brain does **not** immediately escalate on zero check-runs — it waits out the grace window and/or reads the combined-status API. Only after the grace window with genuinely no signal does it escalate.
3. **Pass criteria:** a not-yet-started CI does not cause a false `no-check-signal` escalation.

---

## Cross-cutting things to watch throughout

- **Credential wiring (primary objective):** confirm the watcher/verification calls actually authenticate against real GitHub — no silent 401s degrading to "no issues found." Watch the first poll's logs specifically.
- **Scheduler behavior:** with `max_instances=1`/`coalesce`, confirm a slow cycle doesn't stack — no double-dispatch of the same issue. Leave it running across several idle cycles and confirm it doesn't leak or error on empty polls.
- **Per-slot concurrency:** open two `claude-deck-ready` issues routing to the same slot at once; confirm the second is queued (`pending_reason=queued_slot_busy`), not double-dispatched into one session.
- **The two Phase A review bugs that were fixed:** same-batch busy-guard (two issues, one slot, one poll cycle) and the closed-issue-vs-label-removed distinction (let an issue auto-close via a merged PR and confirm it's marked `merged`, not escalated as `dispatch_label_removed`).
- **DB state sanity:** after each scenario, spot-check the `github_work_items` row's terminal state matches what GitHub shows.

## Exit criteria

- **S1, S2, S3, S5 must pass** — these are the core code + design happy paths and the retry loop. A failure here blocks the master merge.
- **S4, S6, S7, S8 should pass** — these are the guardrail/edge behaviors; a failure here is a bug to file and fix before merge unless it's clearly a test-setup artifact (record the judgment).
- **No credential/auth surprises** — the whole reason this gate exists.
- Every scenario's observations recorded in a run log (append to this doc or a linked issue) so the master-merge PR can cite "e2e verified: <link>."

## If something fails

File it against the integration branch (not a phase issue — those are closed-on-merge trackers). A blocking failure (S1/S2/S3/S5) means the integration branch does **not** merge to master until fixed and the failing scenario re-run green. A non-blocking failure gets a follow-up issue and an explicit "known limitation" note in the master-merge PR if you choose to ship around it.

## Out of scope for this pass (later, post-master)

- Multi-repo teams and same-slot-across-repos concurrency at scale.
- Long-running soak (rate-limit behavior over hours/days).
- The conversational setup flow (separate spec, not yet built).
- External-mode brain (hosted-mode only is what ships).
