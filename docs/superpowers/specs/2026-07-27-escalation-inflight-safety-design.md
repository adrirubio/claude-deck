# Phase G1 design — escalation must not wedge or destroy in-flight work

**Status:** design, ready to implement
**Found by:** tizonia soak, 2026-07-27 (see `2026-07-06-tizonia-roadmap-v1-soak-run-log.md`, Finding 13 secondary defect)
**Scope:** `backend/app/services/github_dispatch_service.py`, `backend/app/api/v1/agent_teams.py`

## The problem

`escalated` currently means two incompatible things:

1. *"This item is stuck; a human should look at it."* — the intended meaning.
2. *"This item's owner is alive and working right now."* — what it accidentally meant on 2026-07-27.

On the soak, work item 26 (#818) was escalated `plan_blocked` while its dispatched owner was mid-edit with 140 dirty files in an isolated worktree. Two independent consequences followed:

**(a) The owner could not report its own success.** `github_verification_service.report_pr_opened` rejects any item whose `dispatch_status != "dispatched"`:

```python
if item.dispatch_status != "dispatched":
    raise ValueError(f"pr_opened is only valid for dispatched work items; current status is {item.dispatch_status}")
```

So the owner's eventual `deck_report_dispatch_status(status="pr_opened", pr_number=N)` would have failed **HTTP 409**. The work existed, the PR existed, and Deck had no way to accept the news. Recovery required a human to route the PR number around Deck via Agent Mail.

**(b) A retry would have silently destroyed the work.** `reset_for_retry` clears `pr_number` and `ack_received_at`. The Leader is *instructed* to call `deck_retry_work_item` on escalated items whose blockers have resolved. Had it done so here, the in-flight PR would have been orphaned from its work item — exactly the loss recorded on 2026-07-26 ("the recovery orphaned a real PR from its work item"), which we already know happens in practice.

Both are data-loss paths that only bite unattended, which is precisely the Window 2 target state.

## Design principles

- **Escalation is a signal, not a state transition that discards context.** Reporting "a human should look" must never make the item unable to receive good news.
- **Late truth beats consistency.** If an owner reports a real PR, Deck should record it regardless of how the item got into its current state. A PR number is ground truth from GitHub; `dispatch_status` is Deck's guess.
- **Retry must be refused when it would destroy something.** Not silently adjusted — refused loudly, so the caller learns why.
- **No new status values.** The state machine is already the thing that is over-loaded; adding `escalated_but_working` would deepen the same mistake. (The impl agent has previously invented statuses — explicitly out of scope.)

## Change 1 — `pr_opened` is accepted from `escalated`, **except when a human said stop**

> **Revised 2026-07-27 after an impl-agent objection.** The first draft of this design said "accept from `escalated`" unconditionally. That was wrong: it would have silently repealed the T-S6 human stop-signal guarantee (`2026-07-05-tizonia-e2e-testbed-plan.md`, T-S6), which is enforced by `tests/agent_mail/test_dispatch_status_tool.py::test_pr_opened_rejected_after_item_escalated` and was validated on a real repo. The impl agent stopped and asked instead of rewriting the test — correct call. The distinction below is the fix.

Not all escalations are equal. Sorting the reasons by **who** decided:

| Reason | Decided by | A late PR means |
|---|---|---|
| `dispatch_label_removed` | **a human**, on GitHub | The human's stop-signal must win. **Reject.** |
| `plan_blocked` | the agent itself | It un-blocked itself. Accept. |
| `owner_idle_timeout`, `owner_offline`, `leader_offline`, `leader_ack_timeout` | Deck's inference from timers | The inference was wrong — the owner was alive. Accept. |
| `retry_count_exhausted`, `approval_rounds_exhausted` | Deck's budget policy | Budget is spent; a new PR should not silently reopen the loop. **Reject.** |

So `report_pr_opened` accepts from `dispatched`, and from `escalated` **only** when `escalation_reason` appears in an explicit **allow-list**:

```python
# Escalations that a late PR legitimately resolves: the item was stuck because
# the agent said so, or because Deck *inferred* it from a timer. A real PR is
# evidence that inference was wrong. Anything NOT listed here — including an
# unattributed escalation (reason=None) — stays rejected: default-deny.
_PR_OPENED_RECOVERABLE_ESCALATIONS = frozenset({
    "plan_blocked",
    "owner_idle_timeout",
    "owner_offline",
    "leader_offline",
    "leader_ack_timeout",
})
```

Allow-list, not block-list, for two reasons: an unattributed escalation (`escalation_reason=None`) must reject — which is exactly what the existing 409 test seeds — and any *future* escalation reason should default to rejecting rather than silently inheriting permission from a set nobody remembered to update.

When it accepts, it clears `escalation_reason` and proceeds as before into `verifying` / `awaiting_human_review`. Any other `dispatch_status` (e.g. `merged`, `completed`) stays rejected.

Rationale: the original insight still holds — a PR is ground truth from GitHub, and Deck's *inference* about being stuck should yield to it. But a human removing the label is not an inference; it is an instruction. An exhausted retry budget is a deliberate policy stop. Both outrank the PR.

**Consequence for the soak's actual case:** item 26 (#818) is escalated `plan_blocked`, which is on the allow-list — so the fix still solves the incident that motivated it.

## Change 2 — retry refuses to discard in-flight work

`retry_github_work_item` must reject with **409** when `item.pr_number is not None`, because `reset_for_retry` would orphan that PR. The message must name the PR so the caller can act:

> Work item has PR #865 already open; retry would orphan it. Resolve or close the PR first.

This is a guard at the endpoint, not inside `reset_for_retry` — the watcher's automatic recovery path (`_upsert_item`, which calls `reset_for_retry` when a *recoverable* item's issue is edited on GitHub) is a separate concern and stays as-is for now. Narrow, reviewable change.

## Change 3 — escalation records that an owner may still be live

When escalating an item that is currently `dispatched` and has an owner, the broadcast body should say so explicitly, so the Leader does not read "escalated" as "abandoned, safe to retry". This is a message-text change plus one extra payload key (`owner_may_be_active: bool`) — **no schema change**; `payload` is already a JSON column.

The Leader's standing instruction ("retry escalated dependents whose blockers resolved") is then qualified by visible information rather than by hoping the Leader infers it.

## Explicitly out of scope

- Any change to `slot_has_live_owner_session`, `reuse_existing`, or the launch path. That is Phase G2 (Finding 13 proper) and must not be mixed in.
- New `dispatch_status` values, new endpoints, schema/migration changes, new dependencies.
- Changing `_apply_escalation`'s `preserve_existing_reason` semantics.
- Touching the live soak, the tizonia checkout, or any agent session.

## Test obligations

1. `pr_opened` from `escalated` + `plan_blocked` → `verifying`, `pr_number` set, `escalation_reason` cleared.
2. `pr_opened` from `escalated` + `plan_blocked` for a `design` item → `awaiting_human_review`.
3. `pr_opened` from `merged` (or `completed`) → still raises. Regression guard against over-permissiveness.
3a. `pr_opened` from `escalated` + `dispatch_label_removed` → **still raises** (T-S6 human stop signal preserved).
3b. `pr_opened` from `escalated` + `retry_count_exhausted` → **still raises**.
3c. `pr_opened` from `escalated` + `escalation_reason=None` → **still raises** (default-deny; this is the existing `test_pr_opened_rejected_after_item_escalated` case, which must keep passing **unmodified**).
4. Retry with `pr_number` set → 409, item unchanged (`pr_number` still set, still `escalated`).
5. Retry with `pr_number is None` → still works exactly as before.
6. Escalating a `dispatched` item with an owner → broadcast payload carries `owner_may_be_active: True`; escalating a `pending` item → `False`.

Baseline to preserve: **274 passing** (`pytest tests/agent_teams tests/agent_mail -q`).
