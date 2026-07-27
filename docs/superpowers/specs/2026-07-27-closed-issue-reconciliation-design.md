# Phase G1b design — a closed issue must reconcile an escalated item

**Status:** design, ready to implement
**Found by:** tizonia soak, 2026-07-27 (see `2026-07-06-tizonia-roadmap-v1-soak-run-log.md`, **Finding 14**)
**Scope:** `backend/app/services/github_watcher_service.py` only
**Depends on:** nothing. Independent of Phase G1 (PR #301), which is already reviewed and passing.

## The problem

An escalated work item whose GitHub issue later closes is **stranded permanently**, and the dependents waiting on it are never notified. Proven on the live soak: item 26 (#818) stayed `escalated`/`plan_blocked` with `pr_number=None` across many 60s poll cycles after PR #866 merged and closed the issue (`updated_at` frozen at `19:39:37`, merge at `19:40:01`).

Both watcher paths structurally exclude it:

```python
_ACTIVE_STATUSES      = ("dispatched", "verifying", "awaiting_human_review")   # no "escalated"
_RECOVERABLE_STATUSES = ("failed", "escalated")
```

- `_recheck_active_items` is **the only code in the entire backend** that assigns `completed` (`github_watcher_service.py:97`) and the only watcher-side caller of `notify_blocker_merged`. It selects on `_ACTIVE_STATUSES`, which omits `escalated`.
- `_upsert_item`'s recoverable-retry path *does* accept `escalated`, but it only ever runs over `list_issues_with_label(...)`, which requests `state: "open"` (`github_client.py:34`, re-filtered at :50). A closed issue never appears there.

The two sets are disjoint in exactly the wrong way: **the path that notices "the issue is done" excludes escalated items, and the path that handles escalated items only sees open issues.** So an escalation is terminal precisely when the work *succeeded* — the good outcome is the one Deck cannot record.

**Blast radius.** This silently killed the soak. Counts: `escalated 12 / completed 10 / merged 6`, zero `pending`, zero `dispatched`. Slot 6 holds 8 items (#821–#827, #829) escalated `plan_blocked` whose `status_note`s name #817–#820 as open prerequisites; all four have merged and GitHub confirms #816–#820 CLOSED. The dependents were never told because `notify_blocker_merged` never fired.

Not fixed by Phase G1: G1 lets a *live owner* report `pr_opened` from a recoverable escalation. Finding 14 is the case where nobody reports anything and the issue simply closes, so G1's allow-list never comes into play.

## Design principle

**A closed issue is ground truth from GitHub and outranks Deck's stale inference about being stuck.** Same principle as G1 Change 1 ("late truth beats consistency"), applied to a different signal. `dispatch_status` is Deck's guess; issue state is fact.

## The fix, and the trap to avoid

The naive fix — add `escalated`/`failed` to `_ACTIVE_STATUSES` — is **wrong**. That tuple drives a loop with a *second* branch:

```python
still_labeled = issue is not None and any(...)
if not still_labeled:
    await github_dispatch_service.escalate(db, item, "dispatch_label_removed", ...)
```

A `failed` item on an open issue whose label a human removed would reach `escalate()`. `_apply_escalation`'s `preserve_existing_reason` guard only trips when the status is *already* `escalated`, so a `failed` item would be **silently laundered into `escalated`** — and only `escalated` items are retryable (`agent_teams.py:421`). That converts a dead item into a retryable one behind the operator's back.

So the closed-issue sweep must be **its own query with its own loop**, and must not inherit the label-removal branch.

Add a separate constant and a second pass:

```python
_CLOSED_ISSUE_RECONCILABLE_STATUSES = ("escalated", "failed")
```

The sweep selects items in those statuses for the scope, fetches them via `get_issues_by_number` (which fetches by number **regardless of state** — verified: it hits `/repos/{owner}/{repo}/issues/{number}` directly and only filters out PRs, `github_client.py:53-72`), and for any whose `state == "closed"` performs exactly the same reconciliation the active path already performs: set `completed`, clear `escalation_reason`, stamp `updated_at`, commit, then `notify_blocker_merged` inside the same try/except/rollback.

**Reuse, don't duplicate.** The reconciliation body in `_recheck_active_items` (lines 96–119) should be extracted into one helper (e.g. `_complete_and_notify(db, scope, item)`) called from both passes, so the two paths cannot drift. The `slots` query and the exception handling move with it.

### Guard: do not reconcile an item with an unresolved PR

If `item.pr_number is not None`, the item has an in-flight PR that Deck never verified, and its issue closing may mean something other than "our work merged" (e.g. closed as duplicate while the PR is still open). Item 13 (#858) is exactly this shape: `escalated`/`dispatch_label_removed` with `pr_number=860`. Its issue is currently OPEN so nothing happens today, but the guard must exist before that changes.

Decision: **reconcile only when `pr_number is None`**, otherwise leave the item alone. This keeps the change conservative and keeps PR-bearing items on the existing verification path, which is the one that understands PRs. Log the skip so it is not silent.

## Effect on the live soak

Of the 12 escalated items, exactly **one** changes: item 26 (#818) → `completed`, firing `notify_blocker_merged` to the Leader, whose body already lists the currently-escalated items as candidate dependents and tells the Leader to call `deck_retry_work_item` for those unblocked. That is the intended, legitimate restart of the cascade — no DB hand-editing, no forced retry.

Verified the other 11 are unaffected: #821–#829 and #834 are all still OPEN on GitHub; #858 is OPEN *and* carries `pr_number=860`, so it is doubly excluded.

## Explicitly out of scope

- Any change to `_ACTIVE_STATUSES` or to the label-removal branch.
- Any change to `escalate`/`_apply_escalation` semantics.
- Phase G2 (`slot_has_live_owner_session`, `reuse_existing`, the launch path).
- New statuses, endpoints, schema/migrations, dependencies.
- Auto-retrying the unblocked dependents. Deck notifies; the Leader decides. Do not add automatic re-dispatch.
- `get_open_issues_by_number` (`github_client.py:43`) is **dead code** — no production caller, only a `_FakeClient` stub. Leave it; removing it is unrelated cleanup.

## Test obligations

All in `backend/tests/agent_teams/test_github_watcher_service.py`. `_FakeClient.get_issues_by_number` already returns closed issues regardless of state, and `_issue(...)` defaults to `state: "open"` — set `["state"] = "closed"` as the existing closed-issue tests do.

1. `escalated` item + closed issue + `pr_number=None` → `completed`, `escalation_reason is None`.
2. Same, and a `github_dispatch_blocker_merged` notification is sent to the Leader member (mirror `test_watcher_completed_fires_blocker_merged_notification`).
3. `failed` item + closed issue → `completed`. Proves the sweep covers both statuses.
4. **`escalated` item + closed issue + `pr_number=865` → UNCHANGED** (still `escalated`, reason intact, no notification). The conservative guard.
5. **`failed` item + OPEN issue + dispatch label absent → still `failed`.** This is the regression guard for the laundering trap; it must fail if someone later widens `_ACTIVE_STATUSES` instead.
6. `escalated` item + issue still open and labeled → unchanged, no notification.

Baseline to preserve: **284 passing** on `feature/autonomous-github-dispatch-phase-g1` (`pytest tests/agent_teams tests/agent_mail -q`).
