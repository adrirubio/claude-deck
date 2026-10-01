# Autonomous Attempt Recovery — Staged Implementation Index

**Status:** Ready for implementation after plan review
**Spec:** `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md`
(Revision 7)
**Issue:** `https://github.com/adrirubio/claude-deck/issues/325`
**Integration branch:** `feature/autonomous-github-dispatch`

## Objective

Deliver autonomous, Leader-authorized recovery for a preserved escalated attempt without
resetting its PR, branch, workspace, owner, nonce, or history. Keep diagnostic CI separate
from product verification, expose the state through REST/MCP/Agent Bridge, and replay
Tizonia work item 23 / PR #875 before any merge to `master`.

## Plan Sequence

1. `docs/superpowers/plans/2026-08-29-pr1-approval-request-authority.md`
   - normalized approval authority;
   - inert revision persistence;
   - idempotent Agent Mail transport;
   - explicit initial approval requests.
2. `docs/superpowers/plans/2026-08-29-pr2-non-destructive-attempt-continuation.md`
   - finite scope policy;
   - implementation continuation request/decision/delivery/ack;
   - watcher preservation;
   - tree/path-gated product verification;
   - active-continuation monitor.
3. `docs/superpowers/plans/2026-08-29-pr3-diagnostic-recovery-orchestration.md`
   - diagnostic proposal policy;
   - isolated CI accounting;
   - tree restoration;
   - automatic recovery and crash repair;
   - final scheduler orchestration.
4. `docs/superpowers/plans/2026-08-29-pr4-agent-bridge-visibility-and-soak-replay.md`
   - Agent Bridge policy/recovery UI;
   - shared Retry eligibility;
   - MCP conflict details;
   - read-only preflight;
   - rollout and checkpointed Tizonia replay.

## Dependency Gates

| Gate | Requirement |
|---|---|
| Start PR1 | Branch from latest integration tip; autonomy off |
| Start PR2 | PR1 reviewed and merged to integration |
| Start PR3 | PR2 reviewed and merged to integration |
| Start PR4 | PR3 reviewed and merged to integration |
| Enable continuation | PR4 merged to integration; migration/config checkpoint approved |
| Enable autonomy | Continuation config and exact live sessions independently verified |
| Merge to `master` | Tizonia replay log independently clears all gates |

Every implementation PR targets the integration branch and stops for review. No phase PR
targets `master`.

## Cross-PR Invariants

- Continuation defaults off for every migrated and newly created scope until explicitly
  enabled.
- Approval prose and generic context requests never authorize work.
- One pending normalized request is database-enforced.
- Approval does not resume work; authenticated current-owner acknowledgement does.
- Continuation never calls `reset_for_retry`.
- PR, refs, workspace acquisition, owner, nonce, counters, and evidence survive activation.
- Product verification does not poll an unsubmitted implementation revision.
- Diagnostic checks never promote, merge, or consume product retries.
- Diagnostic completion requires exact baseline/restored Git tree identity.
- Scope and attempt caps prevent unbounded recovery.
- Human stop reasons and human merge remain stronger than autonomy.
- REST, MCP, and UI use the same server-derived state and Retry predicate.
- Server logs and responses omit all token/credential material.

## Planning Corrections Captured During Decomposition

1. PR1 creates both normalized tables so SQLite never needs a later FK table rebuild; the
   revision table remains inert until PR2.
2. Initial approval uses an explicit route/tool. Generic work-item context requests stay
   non-authoritative.
3. Scope revisions persist `execution_target`; diagnostic policy cannot be reconstructed
   from command prose.
4. Backend responses project Retry eligibility from the same predicate used by the retry
   route; Agent Bridge does not duplicate safety logic.
5. Continuation policy changes use a dedicated operator-only route; generic scope mutation
   remains unable to enable recovery.
6. Retry eligibility preserves the existing safe deferred-retry behavior for PR-less items
   with a held workspace; only preserved continuation authority adds new blocks.
7. Agent Bridge creates its per-tab operator credential helper before protected clients and
   uses it for policy, exact revision detail, and operator cancellation.

These corrections are incorporated into spec Revision 7.

## Shared Execution Rules

- Use a fresh isolated worktree per PR.
- Use the existing Python environment but run tests with the isolated worktree's `backend`
  as CWD so its temporary/default DB cannot resolve to the live checkout.
- Record baseline and final test collection counts in each PR; measured counts win over
  estimates.
- Test every named mutation against the exact test that claims to catch it.
- Do not fix unrelated baseline failures.
- Do not manipulate another worktree's branch, stash, refs, or uncommitted files.
- After a phase PR is merged and its isolated worktree is confirmed clean and fully pushed,
  remove that worktree with `git worktree remove`; never force-remove a dirty or unmerged
  worktree.
- Keep `/home/juan/work/repos/juanrubio/claude-deck` and
  `/home/juan/work/repos/tizonia/` untouched during implementation.
- No local Tizonia builds.
- No live DB edits.
- No Deck/tmux restarts until the deployment runbook explicitly authorizes them.

## Review Expectations

Review each PR independently for:

- schema/migration idempotency;
- transaction and crash boundaries;
- owner/Leader/operator/session/lease authorization;
- stale state and concurrent scheduler interleavings;
- hand-written response/MCP/frontend projections;
- mutation-discriminating tests;
- absence of live-state changes;
- strict PR boundary adherence.

The implementation agent must resolve review findings on the PR branch, re-run scoped and
full validation, and stop before merge unless explicitly instructed.

## Program Completion

The feature is complete only when all four PRs are merged to the integration branch and the
post-merge Tizonia replay proves:

1. Deck autonomously asks the owner for a bounded proposal.
2. The designated Leader decides it through normalized authority.
3. Deck delivers and the owner acknowledges the exact revision.
4. Hosted diagnostic/tool fallback executes and is reverted.
5. Deck proves diagnostic tree restoration.
6. Product correction proceeds under a separate bounded revision.
7. CI becomes green without coordinator impersonation.
8. Deck marks PR #875 ready under human merge policy.
9. A human merges; work item 23 reaches merged.
10. The independent reviewer approves the soak log before any master merge.
