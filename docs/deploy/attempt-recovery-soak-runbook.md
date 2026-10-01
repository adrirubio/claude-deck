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

## Checkpoint 0 — Deployment Healthy, Autonomy Off

1. Deploy the independently reviewed checkpoint barrier to the integration
   backend with autonomy off. Record the PR4 integration merge SHA, the barrier
   merge SHA, and the deployed backend commit. Do not deploy to `master`.
2. Confirm Deck health and migration completion.
   Confirm the `mail_wake_attempts` table exists after deploying the reviewed
   Agent Mail wake-safety change and the revision checkpoint-stage column exists.
3. Confirm autonomy is off. Continuation must be off for a fresh rollout; on
   re-entry after revision 5 cancellation, it may remain on. Do not toggle it
   merely to satisfy the fresh-rollout preflight.
4. Confirm human merge policy.
5. Confirm issue #821 and draft PR #875 remain open.
6. Confirm no integration-to-`master` merge occurred.
7. For a fresh rollout with continuation off, run:

   ```bash
   scripts/attempt-recovery-preflight.sh http://127.0.0.1:8000 2 1 23
   ```

   On re-entry with continuation already on, this script intentionally refuses
   the policy state. Repeat its identity, session, scope, item, and Bridge reads
   without writes and record that substitution in the soak log.
8. Confirm issue #329 is resolved or replay sessions are isolated from unrelated projects.

Stop and report the preflight output with secrets excluded.

## Checkpoint 1 — Exact Team, Scope, and Sessions

With autonomy still off (and continuation off only for a fresh rollout):

1. Verify preset, scope, issue, work item, PR, owner slot, Leader slot, nonce, branch, and
   workspace acquisition from fresh API/DB reads.
2. Verify exactly one observed tmux pane and at least one fresh authenticated MCP registration
   for the Specialist owner slot.
3. Verify exactly one observed tmux pane and at least one fresh authenticated MCP registration
   for the distinct Leader slot. Ignore the auxiliary hook row when counting physical agents.
4. Confirm the preflight's sixth GET, `/api/v1/agent-bridge/sessions`, maps each exact observed
   owner and Leader pane to one Bridge session with the expected preset and slot,
   `mail_wake_state = wakeable`, `mail_wake_enabled = true`, and an exact
   `mail_wake_target` match to that pane's tmux target. The owner and Leader targets must be
   distinct; duplicate Bridge rows or any stale, ambiguous, unbound, or opted-out state blocks
   the soak.
5. Verify no duplicate Tizonia sessions are registered to either slot.
   Confirm each observed pane PID matches its slot's fresh authenticated MCP
   session binding and process start time. An observed-only pane is not a wake
   target. Inspect redacted wake attempts through the operator-only
   `GET /api/v1/agent-mail/wake-attempts` endpoint; do not force a test wake
   of an empty inbox merely to prove the route works.
6. Verify finite continuation caps are the reviewed values. Five revisions already
   exist for this attempt, including cancelled revision 5, and the live cap is 6.
   The diagnostic-then-implementation path below requires at least two further
   revisions. Before Checkpoint 3, set `max_continuation_revisions=7` only after
   the reviewed barrier is deployed and the user-approved finite cap increase
   is recorded. Leave `max_continuation_failed_heads=8` unchanged. If another
   revision becomes necessary, stop for a separate budget decision rather than
   increasing the cap automatically. An implementation-only path requires a
   separately approved runbook change because it skips the hosted diagnostic
   checkpoint.
7. Verify no pending legacy continuation request for the selected attempt has
   `recovery_checkpoint_stage=NULL`. Legacy requests retain their old decision
   behavior; cancel or resolve any such request under an explicit operator
   decision before using these checkpoint steps. The current attempt has none.
8. Verify PR #875's current head and baseline restoration target are recorded.

The preflight is read-only: its Bridge-session verification does not enable participation,
send a wake, or assign a team role or slot. Preserve the reported exact targets in the
checkpoint evidence.

Stop and report the complete identity matrix before changing policy.

## Checkpoint 2 — Continuation On, Autonomy Off

1. Use Agent Bridge's dedicated recovery-policy editor with the per-tab operator token.
2. For a fresh rollout, enable continuation with reviewed finite caps. On
   re-entry after revision 5, leave continuation enabled and set only
   `max_continuation_revisions=7` after the reviewed barrier is deployed;
   preserve the failed-head cap and all other policy fields.
3. Do not enable autonomy.
4. Re-read the scope through the API and confirm all six policy values. Only
   the intended fields may change atomically.
5. Confirm no proposal, mail, revision, nudge, or work-item transition occurred while
   autonomy remained off.

Stop and report before enabling autonomy.

## Checkpoint 3 — Autonomous Owner Proposal

1. Before enabling autonomy, confirm the reviewed recovery-only scheduler gate
   and checkpoint barrier are deployed, with
   `GITHUB_RECOVERY_ONLY_ATTEMPT=1:23:875:4173e3b8851fccc8:deck/slot-6/issue-821-4173e3b8851fccc8`
   in the backend-only `.env`. Verify this exact selector is active,
   `identity_matches=true` through the operator-only
   `GET /api/v1/agent-teams/github-recovery-gate`, the scope still uses human
   merge, the lease and PR are unchanged, and both exact team panes are wakeable.
   A missing or mismatched selector blocks this checkpoint. After enabling autonomy,
   the same read must show `scheduler_running=true` and `job_scheduled=true`.
   This gate runs only continuation monitoring, verification, and recovery for the
   selected attempt. It skips the broad watcher, new dispatch, PR-less monitoring,
   release reminders, and dependency-unblock broadcasts; item 26 and unrelated
   `agent-ready` issues stay untouched.
   The gate does not restrict agent-initiated MCP writes; do not manually wake
   unrelated panes or direct agents to act on other work items during the soak.
2. Enable autonomy for `tizonia-v1`.
3. Observe the recovery monitor nudge only the current Specialist owner.
4. Confirm the owner performs read-only diagnosis and submits one explicit bounded
   continuation proposal. The selected attempt's new revision must be held at
   `recovery_checkpoint_stage=decision_hold` before the request mail is sent.
   A diagnostic proposal must use `execution_target=hosted_ci`; Deck refuses a
   workspace diagnostic while this recovery-only selector is active.
5. Confirm normalized approval and revision rows commit before request mail.
6. Confirm the proposal preserves PR #875, owner, workspace, nonce, branch, and retry history.
7. Confirm Deck/coordinator did not fabricate the proposal.
8. Disable autonomy as soon as the held proposal is observed. Do not release
   the decision hold or ask the Leader to decide yet. The hold is durable and
   remains effective even if the Leader calls its MCP decision tool. The
   recovery monitor does not issue a decision nudge while held; other Agent Mail
   traffic can still wake the Leader, so a premature tool call must return 409.

Stop with revision id, request id, mail id, phase, scope summary, hold stage,
and counters. Revision 5 was cancelled after an out-of-runbook local-build
proposal. It still counts toward the cap. Never consume the last configured
revision slot speculatively.

## Checkpoint 4 — Leader Decision, Delivery, and Ack

1. After explicit clearance of Checkpoint 3, use the operator-only
   `POST /api/v1/agent-teams/github-work-items/23/scope-revisions/{revision}/checkpoint-release`
   with `release=true`, the exact nonce and approval-request id, and
   `stage=decision`. This opens only the Leader decision, not owner acknowledgement.
   The proposal expiry clock starts at release (default 3600 seconds; verify
   the deployed setting). If the Leader cannot act within that bound, leave
   the hold in place rather than releasing it early.
2. Observe the designated distinct Leader decide using its authenticated session;
   the operator must not approve. A successful approval moves the revision to
   `recovery_checkpoint_stage=ack_hold` in the same authority transaction.
   With autonomy off, explicitly ask the Leader to check its inbox after the
   decision hold is released; do not decide on its behalf.
3. Verify decision authority commits before decision mail, and decision mail
   before owner delivery. The owner's early MCP acknowledgement must be refused
   with `recovery_checkpoint_paused` and must leave the item escalated.
4. Verify stable delivery keys produce exactly one request, decision, and delivery
   message across repeated scheduler polls. Keep autonomy off while inspecting.

Stop with the authority/mail linkage, actor identities, and `ack_hold` evidence.
Do not release owner acknowledgement until this checkpoint is confirmed.

## Checkpoint 5 — Hosted Diagnostic and Exact Restoration

This checkpoint applies when the approved revision is diagnostic.

1. After explicit clearance of Checkpoint 4, use the same operator-only release
   route with `stage=ack`. Confirm it moves exactly the approved revision to
   `ack_open`, then observe the current owner acknowledge it with its own
   authenticated session and lease. Confirm activation preserves the original
   attempt identity and refreshes only continuation liveness anchors. With
   autonomy off, explicitly ask the owner to check its inbox after the hold is
   released; do not acknowledge on its behalf. The acknowledgement expiry clock
   starts at this release; do not release before the owner can act.
2. Confirm all diagnostic actions, commands, paths, evidence objectives, failed-head budget,
   hosted target, tool fallback, and mandatory revert match the approved revision.
3. Observe hosted CI install a named diagnostic tool only through the approved temporary
   fallback when required.
4. Confirm diagnostic red/green results update diagnostic counters only and never promote,
   merge, or consume product retry history.
5. Observe the owner revert all diagnostic changes and report `diagnostic_completed`.
6. Confirm Deck re-fetches the current PR head and proves its Git tree equals the persisted
   baseline tree.
7. Confirm a mismatched or moved head is refused and no product verification starts.
8. Confirm successful restoration returns the attempt to the originating escalation and
   requests a new bounded implementation proposal.

Stop with hosted CI run ids, head/tree SHAs, diagnostic counters, and restoration result.

## Checkpoint 6 — Implementation Continuation and Product CI

1. Observe the owner submit the smallest implementation proposal informed by diagnosis.
2. Repeat the decision-hold and acknowledgement-hold releases and distinct
   Leader/owner identity checks. Do not treat the diagnostic revision's earlier
   releases as authority for a later revision.
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
4. Observe the recovery-only verification stage mark item 23 merged.
5. Disable autonomy.
6. With autonomy still off, remove `GITHUB_RECOVERY_ONLY_ATTEMPT` from the
   backend-only `.env`, restart Deck, and verify the operator recovery-gate
   endpoint reports `active=false`. Do not re-enable broad dispatch as part of
   this cleanup.
7. Decide explicitly whether continuation remains enabled or is disabled.
8. Confirm the workspace lease is released only through the normal terminal owner flow.
9. Confirm no pending approval/revision/mail repair remains.
10. Commit the completed soak log to the integration branch.

Stop. An independent reviewer must approve the evidence log before the integration branch is
proposed for merge to `master`.
