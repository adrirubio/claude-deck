# Tizonia as Claude Deck E2E Testbed — Adapted Verification Plan

**Date:** 2026-07-05
**Status:** Verification runbook (tizonia-specific adaptation)
**Base plan:** `2026-07-05-autonomous-github-dispatch-e2e-verification-plan.md` (generic; that doc stays canonical — this one specializes it to a real repo)
**Testbed repo:** `tizonia/tizonia-openmax-il` (C/OpenMAX IL, v1 "Ubuntu 24.04 amd64 revival")
**Roadmap context:** PR #830 (merged) — added the `agent-roadmap-task` issue template + PR template + README revival banner.

---

## Why tizonia is a good testbed (better than a throwaway sandbox)

The generic plan called for a *throwaway* repo precisely because we had no real agent-shaped work to point at. Tizonia changes that: PR #830 already turned the revival roadmap into **agent-ready issues from a template**, which is exactly the input shape Claude Deck's dispatch loop consumes. Concretely, the fit is unusually clean:

- **`agent-ready` label already exists and is auto-applied** by the roadmap issue template → it *is* Claude Deck's `dispatch_label` with zero renaming.
- **`area:build` / `area:ci` / `area:docs` / `area:packaging` / `area:services` / `area:tests` labels already exist** → these are literally the `area_labels` Claude Deck's SME routing consumes.
- **The issue template is richer than a normal issue** — Goal / Context / Scope / Out-of-scope / Dependencies / Implementation notes / Acceptance criteria / **Verification (shell)**. A dispatched agent gets a self-directed brief *and* the exact per-issue verification commands, which feeds directly into the e2e "did it actually work" check.
- **The `[v1]` / `roadmap:v1` scoping + the PR template's "don't broaden beyond Ubuntu 24.04 amd64" guardrails** give agents crisp, enforceable boundaries — the kind of scope discipline that keeps unattended work from sprawling.

So this is a real testbed doing real work, not a toy. The tradeoff is that tizonia is a large C project, which shapes the two adaptations below.

## What must change from the generic plan

### 1. Prerequisite Phase 0 — land minimal CI first (BLOCKING)
Tizonia currently has **no GitHub Actions workflows** (`.github/workflows` is absent). The generic plan's code pipeline is CI-gated (S1/S2/S3/S7/S8 all assume real check-runs); without CI, every tizonia code PR would hit the "zero check-runs" grace/escalation path and the code pipeline would never be genuinely exercised.

**Before any code-pipeline e2e scenario**, land a lightweight CI workflow on tizonia `master`:
- A single GitHub Actions job on `ubuntu-24.04` (amd64) that configures + builds the v1 default path and runs whatever smoke/tests the revival currently has green.
- It must be able to go **green on a good PR and red on a broken one** — that's the signal the whole code pipeline gates on.
- Keep it minimal and reasonably fast; a multi-hour build makes the 60s-poll × 120s-grace timing untestable in practice. If a full build is unavoidably slow, gate e2e on a *subset* target (e.g. one component) and note it.
- This is genuinely useful to the revival independent of Claude Deck, so it's not throwaway scaffolding.

This is itself a good first **agent-ready issue** (label it `agent-ready` + `area:ci`) — but for the e2e gate, land it via the normal human PR flow first so the testbed has a known-good CI baseline before autonomy is pointed at it. (Using autonomy to build its own CI is a fun bootstrap, but don't make it the *first* thing tested — you'd be debugging two unknowns at once.)

### 2. Team roster — minimal for the first pass
Per decision: **1 leader + 1 code-capable generalist slot** (no `area_labels` → leader-fallback routing). This keeps the first e2e run about proving *the loop* works against a real repo, not about routing sophistication. The provider must be one that can realistically work a C/autotools/CMake codebase and run the build locally (codex-cli or claude-code with working creds). SME label-routing (using tizonia's `area:*` labels) gets its own dedicated scenario (T-S9 below) once the core loop is trusted — deferred, not dropped.

### 3. Issue selection — use real roadmap issues, shaped for safety
Pick **small, genuinely-scoped** roadmap issues for the first runs — the template's Out-of-scope and Acceptance-criteria fields make this easy. Good first candidates: a docs/packaging tweak, a single-file build fix, a warning cleanup. Avoid anything touching the OpenMAX core or cross-component behavior for the initial pass. The per-issue **Verification** field is your acceptance oracle — the agent should run exactly those commands, and you confirm they pass on the resulting PR.

### 4. Merge policy — start human, and mind that this is a public repo
Tizonia is a **real, public project**, not a sandbox. Start every scenario at `merge_policy=human` and only move to `auto` on a deliberately-chosen trivial issue once S1 is trusted. Auto-merging agent work into a public revival is a higher-stakes action than in a throwaway repo — the e2e run should build that confidence gradually, and branch protection on `master` (see T-S7) is a feature to test *with*, not an obstacle.

---

## Scenario matrix (tizonia-specialized)

Same spine as the generic plan; the substitutions are the repo, the `agent-ready`/`area:*` labels, the minimal roster, and tizonia-real issues. Record per scenario: action, activity-feed state, backend log, GitHub state, pass/fail + deviation.

- **T-Phase 0 (blocking prereq):** minimal CI green on `master` via human PR. Confirm a deliberately-broken PR turns it red. *Gate for all code scenarios.*
- **T-S1 — code issue, human merge (baseline):** a small `agent-ready` roadmap issue → dispatched to the generalist → leader ack → agent builds locally, opens draft PR → CI green → `ready_for_review` + notification → **you merge**. The whole loop, unattended, on real tizonia work. *Hard gate.*
- **T-S2 — auto-merge, checks green (DEFERRED for the initial gate — decision #2):** run this only *after* S1/S3/S5 are trusted human-merged, on a deliberately-trivial issue, with branch protection enabled as a backstop. When run: trivial `agent-ready` issue, scope `merge_policy=auto` → brain auto-merges once, `auto_merged_at` set. Not part of the first public-repo pass — the initial gate is human-merge-only.
- **T-S3 — CI fails then fixed (retry loop):** an issue whose first attempt fails the new CI → failure detail to owner → `retry_count` increments → item re-enters verification (not stranded in `dispatched`) → fix pushed → green → promotes. *Hard gate — this is the Phase B dead-end fix, verified against real CI.*
- **T-S4 — retry-budget escalation + Phase C retry action:** force repeated CI failure past `max_verification_retries` → `escalated` / `retry_count_exhausted` + Agent Mail broadcast → click **Retry** in the Autonomy tab → returns to `pending`, re-dispatches. Confirm the handoff-hygiene fix (Phase C review #1) if an escalation-during-handoff can be constructed.
- **T-S5 — design pipeline (docs/roadmap issue):** an `agent-ready` issue whose output is documentation (tizonia has many — README/build-doc updates fit the revival) → detected `issue_type=design` → doc PR (not draft) → straight to `awaiting_human_review`, **no CI polling, no auto-merge** even under auto policy. *Hard gate.* (Note: this scenario needs the `design_label` applied — decide whether tizonia adopts `claude-deck-design` or you map an existing label; see Open Questions.)
- **T-S6 — label removed mid-flight:** during an in-flight item, remove `agent-ready` on GitHub → escalated `dispatch_label_removed` + direct "wind down" message to owner → a late `pr_opened` is rejected (409). The human stop-signal honored on a real repo.
- **T-S7 — branch protection → human fallback:** enable branch protection on tizonia `master` (it should probably have this anyway) → auto-merge attempt hits 403 → falls back to human path, **no** `escalation_reason`. Confirms Deck respects the repo's own merge rules.
- **T-S8 — CI timing / grace window:** with the real (possibly slow) tizonia build, confirm the brain waits out `github_check_signal_grace_seconds` for checks to start rather than false-escalating on a not-yet-started build. *This is the scenario most affected by tizonia's build being heavier than a sandbox — tune the grace window against the real build-start latency and record the value.*
- **T-S9 — SME label routing (deferred, second pass):** once the core loop is trusted, add `area:build`/`area:tests` SME slots and confirm `area:*`-labeled issues route to the right slot (`routing_method=label`) vs. leader-fallback for unlabeled ones. Not part of the first gate.

## Cross-cutting watches (unchanged from generic plan, tizonia-flavored)
- **Credential wiring** against real GitHub (primary objective) — first poll's logs.
- **Scheduler** no-stacking across idle cycles; per-slot concurrency (two `agent-ready` issues at once → second queues).
- **Build reality:** does the spawned agent actually build tizonia locally within reasonable time/resources? If local build is impractical, the plan leans harder on CI as the sole gate — note which.
- **The Phase A/B/C review fixes** confirmed against reality: CI-fail-recovery (T-S3), retry-handoff hygiene (T-S4), label-removed guard (T-S6), zero-check-runs grace (T-S8).

## Exit criteria
- **T-Phase 0 + T-S1 + T-S3 + T-S5 must pass** (human-merged) — real CI baseline, code happy path, retry-recovery, design pipeline. These gate the Claude Deck integration-branch → master merge. **T-S2 (auto-merge) is NOT part of this initial gate** (decision #2, deferred) — the master merge can proceed on the human-merge-only proof; auto-merge on public tizonia is validated separately, later, once trusted.
- **T-S4/S6/S7/S8 should pass**; failures → follow-up issues on the Claude Deck integration branch, judged before merge.
- **No credential/auth surprises** and **no unintended writes to public tizonia** — the higher-stakes-repo watch.
- Results recorded in a run log the master-merge PR can cite.

## Decisions & open questions specific to tizonia
1. **`design_label` — DECIDED (2026-07-05).** A dedicated `agent-design` label was created on tizonia (not overloading `area:docs`, which would conflate routing and pipeline-selection — the C3 conflation the design spec warns about). Configure the scope's `design_label` = `agent-design`. Design/docs roadmap issues get labelled `agent-ready` + `agent-design` (+ any `area:*`); they take the design pipeline (no CI gating, human-merged) per §7b. Used in T-S5.
2. **Public-repo blast radius — DECIDED (2026-07-05).** Run the e2e passes against the **canonical public `tizonia/tizonia-openmax-il` repo** (not a fork), with **`merge_policy=human` on every scope until the loop is trusted**. Consequence: **T-S2 (auto-merge) is deferred** — do not set `merge_policy=auto` on tizonia during the initial gate; prove S1/S3/S5 human-merged first, and only introduce auto-merge on a deliberately-chosen trivial issue once confidence is established. This makes "no unintended/auto writes to public tizonia" a hard watch for the first passes, and means branch protection on `master` (T-S7) should be enabled as a backstop before any auto-merge is ever attempted.
3. **Build cost (still open — the biggest live risk):** the merged core-only CI (#831/#832) builds fast (~25-35s green), which de-risks the *CI-gate* side. Still to confirm: whether the **spawned agent can build tizonia core locally** within a dispatch cycle on the machine Claude Deck runs on (its local-checks-before-push step, §7a). If local build is impractical there, the code pipeline leans on CI as the sole gate — note which during the run. Determine the minimal local build target before T-S1.

## Relationship to the roadmap
This isn't just borrowing tizonia as a test target — a successful e2e run *is* forward progress on the tizonia revival (real roadmap issues get worked and merged). The two efforts reinforce: Claude Deck gets its real-world validation gate, and tizonia gets an autonomous team chewing through `agent-ready` v1 work. Once the gate passes and Claude Deck merges to master, tizonia becomes the first standing "intelligent Deck" deployment against a live roadmap — which is the whole point of the autonomy work.
