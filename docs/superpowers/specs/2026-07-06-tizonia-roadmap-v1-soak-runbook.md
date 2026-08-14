# Tizonia roadmap:v1 Unattended Soak — Runbook

**Design:** `docs/superpowers/specs/2026-07-06-autonomous-dispatch-hardening-and-soak-design.md`
**Testbed:** `tizonia/tizonia-openmax-il` (public). Branch protection on `master` stays enabled.
**Finish line:** loop reliability across every `roadmap:v1` issue Deck picks up — NOT solving every issue. Easy issues merge; hard/blocked ones escalate cleanly and recoverably. A capability failure (agent can't do a hard issue) is acceptable; a *loop* failure (silent stranding, bad write, wrong-reason escalation, guard not firing) is not.

## Pre-flight

- [ ] Backend on `feature/autonomous-github-dispatch` at the post-hardening commit; `pytest tests/agent_teams tests/agent_mail -q` green.
- [ ] `GITHUB_TOKEN` exported with `repo`+`workflow` scope (`gh auth token`).
- [ ] Real default timing: `GITHUB_DISPATCH_INTERVAL_SECONDS=60`, `GITHUB_CHECK_SIGNAL_GRACE_SECONDS=120`. Leave the new ack/idle/nudge settings at code defaults (300 / ×3 / 900 / 180) unless a run shows they need tuning — record any change here.
- [ ] Team preset `tizonia-v1` (Leader + Generalist), both slots have fresh, actively-heartbeating sessions before enabling autonomy.
- [ ] Local tizonia checkout clean on `master`.

## Cleanup (spent e2e artifacts — do first, not soak work)

- [ ] Close leftover PR #857 and issue #856 (`agent-ready-e2e`, "CI signal grace-window validation rerun").
- [ ] Reconcile the local work-item state for #834 from prior runs.
- [ ] Confirm no `agent-ready-e2e` issues remain open: `gh issue list --repo tizonia/tizonia-openmax-il --label agent-ready-e2e --state open` → empty.

## Seed design issues (design-pipeline coverage — prerequisites for the hardest work)

Create 1–2 `agent-design` + `roadmap:v1` issues that genuinely de-risk implementation issues:

- [ ] Design note: yt-dlp backend integration approach (prerequisite for #822).
- [ ] Design note: libspotify removal blast-radius / v1 packaging strategy (prerequisite for #819 / #824 / #825).

These flow through the design pipeline (`awaiting_human_review`, no CI, never auto-merged) and exercise the design-tier ack timeout (× multiplier).

## Window 1 — human-merge

- [ ] Set scope `merge_policy=human`; `autonomy_enabled=true`. Leave running unattended, monitoring backend logs.
- [ ] Deck watches `agent-ready` + `roadmap:v1` (and the seeded `agent-design`) issues, works them, a human merges after review.
- [ ] For each issue Deck touches, record a row in the outcome table below.
- **Pass:** every touched issue ends `merged` OR `escalated(explainable reason)` OR `still-working`; ZERO silent stranding; ZERO unintended public write. At least one leader-ack lifecycle and (if it arises naturally) one idle lifecycle observed behaving correctly.
- [ ] On completion: `autonomy_enabled=false`, revert to a clean baseline.

## Window 2 — auto-merge (only after Window 1 is clean)

- [ ] Set scope `merge_policy=auto`; `autonomy_enabled=true`. Monitor logs.
- **Must observe:** the finding-#3 head re-confirm guard fires at least once on a moved/red head. If the roadmap doesn't produce one naturally, inject a controlled "red commit after promotion" on one scoped issue's PR to force it (like the original T-S3 inversion), and record it.
- **Also observe:** `max_auto_merges_per_day` cap enforced; per-slot concurrency queueing under real load.
- **Pass:** guard demonstrably blocked ≥1 stale/red head; cap + concurrency held; ZERO bad auto-merge.
- [ ] On completion: `autonomy_enabled=false`, `merge_policy` reverted.

## Safety invariants (both windows)

- No hand-editing DB rows to steer scenarios — drive via labels/config only.
- Do not terminate a dispatched session or report on its behalf unless positively confirmed dead (process gone / `wake_state=offline`).
- Branch protection on `master` stays enabled throughout.

## Per-issue outcome log

| Issue | Type | Owner | Outcome (merged / escalated(reason) / still-working) | Escalation explainable? | Notes |
|---|---|---|---|---|---|
| | | | | | |

## Verdict

- Window 1 clean (no silent stranding / bad write): <yes/no>
- Window 2: #3 guard fired ≥1×; cap + concurrency held; no bad auto-merge: <yes/no>
- **Cleared for integration→master merge (closes #272 / #275 / #277 / #280):** <yes/no>
