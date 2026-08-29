# Attempt Recovery Tizonia Soak Runbook

## Scope

Replay the preserved Tizonia attempt through normalized proposal, Leader decision,
delivery, acknowledgement, diagnostic isolation, exact restoration, implementation
continuation, product verification, and human merge.

Expected identities, subject to fresh verification:

- preset: `tizonia-v1`, expected id 2;
- GitHub scope: `tizonia/tizonia-openmax-il`, expected id 1;
- work item: 23;
- issue: #821;
- PR: #875;
- owner: Specialist slot;
- approver: distinct Leader slot;
- merge policy: `human`.

These identifiers are hints, not authority. Stop if live API and database state do not agree.

## Hard Rules

- Stop at every checkpoint and obtain explicit user confirmation.
- Do not combine checkpoints.
- Do not retry or release work item 23.
- Do not touch historical item 26 or issue #818.
- Do not reset, clean, replace, or relay the preserved workspace lease.
- Do not run a Tizonia build locally.
- Do not install diagnostic tools on the Deck host.
- Do not commit, push, report status, propose, approve, acknowledge, or cancel on behalf of
  a live owner or Leader.
- Do not write outside PR #875's branch and its approved scope revisions.
- Do not auto-merge. A human merges PR #875.
- Stop on any unsanctioned GitHub, database, workspace, mail, or session write.
- Treat unresolved issue #329 as a replay blocker unless unrelated sessions are shut down or
  prompt routing isolation is independently verified.

Use `docs/deploy/attempt-recovery-soak-log-template.md` throughout. Record public identifiers
and hashes only; never record credentials or lease material.

## Checkpoint 0 — Deployment Healthy, Recovery Off

1. Record the reviewed PR4 integration merge SHA and deployed backend commit.
2. Confirm Deck health and migration completion.
3. Confirm autonomy is off and continuation is off.
4. Confirm human merge policy.
5. Confirm issue #821 and draft PR #875 remain open.
6. Confirm no integration-to-`master` merge occurred.
7. Run:

   ```bash
   scripts/attempt-recovery-preflight.sh http://127.0.0.1:8000 2 1 23
   ```

8. Confirm issue #329 is resolved or replay sessions are isolated from unrelated projects.

Stop and report the preflight output with secrets excluded.

## Checkpoint 1 — Exact Team, Scope, and Sessions

With autonomy and continuation still off:

1. Verify preset, scope, issue, work item, PR, owner slot, Leader slot, nonce, branch, and
   workspace acquisition from fresh API/DB reads.
2. Verify exactly one observed tmux pane and at least one fresh authenticated MCP registration
   for the Specialist owner slot.
3. Verify exactly one observed tmux pane and at least one fresh authenticated MCP registration
   for the distinct Leader slot. Ignore the auxiliary hook row when counting physical agents.
4. Verify no duplicate Tizonia sessions are registered to either slot.
5. Verify finite continuation caps are the reviewed values.
6. Verify PR #875's current head and baseline restoration target are recorded.

Stop and report the complete identity matrix before changing policy.

## Checkpoint 2 — Continuation On, Autonomy Off

1. Use Agent Bridge's dedicated recovery-policy editor with the per-tab operator token.
2. Enable continuation with reviewed finite caps.
3. Do not enable autonomy.
4. Re-read the scope through the API and confirm all six values changed atomically.
5. Confirm no proposal, mail, revision, nudge, or work-item transition occurred while
   autonomy remained off.

Stop and report before enabling autonomy.

## Checkpoint 3 — Autonomous Owner Proposal

1. Enable autonomy for `tizonia-v1`.
2. Observe the recovery monitor nudge only the current Specialist owner.
3. Confirm the owner performs read-only diagnosis and submits one explicit bounded
   continuation proposal.
4. Confirm normalized approval and revision rows commit before request mail.
5. Confirm the proposal preserves PR #875, owner, workspace, nonce, branch, and retry history.
6. Confirm Deck/coordinator did not fabricate the proposal.

Stop with revision id, request id, mail id, phase, scope summary, and counters.

## Checkpoint 4 — Leader Decision, Delivery, and Ack

1. Observe the designated distinct Leader receive the normalized request.
2. The Leader approves or rejects using its authenticated session; an operator must not
   approve.
3. For approval, verify decision authority commits before decision mail, and decision mail
   before owner delivery.
4. Verify stable delivery keys produce exactly one request, decision, and delivery message
   across repeated scheduler polls.
5. Observe the current owner acknowledge the exact revision with its own session and lease.
6. Confirm activation preserves the original attempt identity and refreshes only the
   continuation liveness anchors.

Stop with the authority/mail linkage and actor identities.

## Checkpoint 5 — Hosted Diagnostic and Exact Restoration

This checkpoint applies when the approved revision is diagnostic.

1. Confirm all diagnostic actions, commands, paths, evidence objectives, failed-head budget,
   hosted target, tool fallback, and mandatory revert match the approved revision.
2. Observe hosted CI install a named diagnostic tool only through the approved temporary
   fallback when required.
3. Confirm diagnostic red/green results update diagnostic counters only and never promote,
   merge, or consume product retry history.
4. Observe the owner revert all diagnostic changes and report `diagnostic_completed`.
5. Confirm Deck re-fetches the current PR head and proves its Git tree equals the persisted
   baseline tree.
6. Confirm a mismatched or moved head is refused and no product verification starts.
7. Confirm successful restoration returns the attempt to the originating escalation and
   requests a new bounded implementation proposal.

Stop with hosted CI run ids, head/tree SHAs, diagnostic counters, and restoration result.

## Checkpoint 6 — Implementation Continuation and Product CI

1. Observe the owner submit the smallest implementation proposal informed by diagnosis.
2. Repeat the distinct Leader decision, delivery, and owner acknowledgement checks.
3. Confirm edits stay inside exact allowed paths/actions/commands.
4. Observe `continuation_completed` validate the Git diff and current PR head.
5. Confirm product verification starts only after submission.
6. Confirm distinct failed heads use the revision budget while preserving historical product
   retry facts.
7. Require all product checks green.

Stop with revision ids, PR head, changed paths, check runs, and counters.

## Checkpoint 7 — Human Review, Merge, and Cleanup

1. Confirm Deck marks item 23 ready for review under human merge policy.
2. Confirm no auto-merge attempt occurred.
3. A human reviews and merges PR #875.
4. Observe the watcher mark item 23 merged.
5. Disable autonomy.
6. Decide explicitly whether continuation remains enabled or is disabled.
7. Confirm the workspace lease is released only through the normal terminal owner flow.
8. Confirm no pending approval/revision/mail repair remains.
9. Commit the completed soak log to the integration branch.

Stop. An independent reviewer must approve the evidence log before the integration branch is
proposed for merge to `master`.
