# Open Design Finding — stale `ready_for_review` when a promoted PR's head goes red

**Status:** Open design question — NON-BLOCKING for the integration→master gate. Recorded during the tizonia e2e run (2026-07-05); deliberately deferred, not fixed.
**Surfaced by:** the (inverted) first T-S3 attempt on tizonia issue #834.

## Observation
When a code-pipeline PR goes green → is promoted to `dispatch_status="ready_for_review"` → and then a **new commit is pushed to the PR branch that turns CI red**, Deck leaves the work item in `ready_for_review` with a stale `status_note="PR #N is ready for review."`. `process_scope` selects `ready_for_review` items but routes them only to `_process_review_item` (the merge path), never back to `_verify_item` (the CI re-check path). So a post-promotion red head is not detected; `retry_count` stays 0.

## Is it a bug?
Not against the current spec. Spec §7a defines the CI-failure retry loop for the **`verifying`** state; for a `merge_policy=human` repo, `ready_for_review` means "stop here, a human merges." The spec never contemplated a push landing *after* promotion. So current behavior is spec-conformant — but the spec has a gap.

## Why it's non-blocking now
On the initial gate we run **`merge_policy=human` only** (tizonia decision #2). The human is the actual merge gate and sees the red PR on GitHub, so the stale Deck state can't cause a bad *merge* — it's a UX/trust wrinkle (Deck's activity feed says "ready" while GitHub shows red), not a path to auto-merging a broken PR. The dangerous version (auto-merge trusting a stale green) only exists once `merge_policy=auto` is enabled — which is itself deferred until after this gate.

## The question to decide (post-gate)
Should a `ready_for_review` (or, later, an auto-merge-eligible) item **re-check the PR head/check-runs on change** and demote/re-verify if the head went red? Options, roughly:
- **A. Re-verify on head change:** `process_scope` re-checks the head SHA of `ready_for_review` items; if the checked SHA differs from the current head, re-run verification (demote to `verifying`). Closes the gap generally; adds polling cost + a new transition.
- **B. Guard only at the merge boundary:** before an `auto` merge, re-confirm CI green on the *current* head (cheap, targeted) — enough to prevent the dangerous auto-merge-a-red-PR case without a general re-verify loop. Leaves the human-merge UX wrinkle as-is.
- **C. Accept as-is:** document that Deck's `ready_for_review` reflects the state *at promotion*, and the human/GitHub is the source of truth for the live head. Cheapest; relies on the human.

**Recommendation to revisit before enabling `merge_policy=auto`:** at minimum option B (re-confirm head-green immediately before an auto-merge), since that's the case where stale state becomes consequential. Full option A is a nice-to-have for UI honesty but not safety-critical.

## Explicitly not being done in the e2e run
The corrected T-S3 re-run tests the **verifying-stage** first-attempt-failure retry loop (the actual §7a mechanism). It does NOT add re-verification-on-head-change; that's this open question, for a later deliberate decision.
