# Tizonia Attempt-Recovery Soak: Final Replay and Cleanup

Status: **evidence draft; not master-merge clearance**. Times below are UTC. This
records the final revision and terminal cleanup from live Deck DB/API, Agent Mail,
GitHub, and the leased checkout. Earlier checkpoints are summarized from durable
authority rows and private operator artifacts where possible. The private
`attempt-recovery-deploy-20260829T205204Z.log` and
`attempt-recovery-soak-20260829T205204Z.md` record the pre-deployment backup
reference/digest and early checkpoint evidence; do not copy the database or its
private backup details into the repository.

## Identity and safety boundary

| Field | Observed |
|---|---|
| Deck deployment | `d4d7f5dcc08031f4404c071273a04b4ace3cc71c`, integration branch `feature/autonomous-github-dispatch`, not `master` |
| Deck preset / scope | `tizonia-v1` id 2 / `tizonia/tizonia-openmax-il` id 1 |
| Work item / public issue / PR | 23 / #821 / #875 |
| Owner / distinct approver | Specialist member 17, slot 6 / Leader member 16, slot 4 |
| Scope merge policy | `human`; `auto_merged_at` remained NULL |
| Leased workspace | id 2; released during cleanup |
| Final PR head / merge commit | `b6880f541a0b3f0d3e651e2a9592391b5dc4af58` / `d509ad8ea043c787c890dd54626d9c65b955e82c` |

No lease token, capability token, credential, or token hash is recorded here.
Issue #329 remains open. The private early-soak log records a dedicated
`deck-soak` tmux socket isolated from the unrelated default-socket session.
Independent review must verify that isolation covered the later replay too.

## Checkpoint evidence

| Gate | Durable outcome | Evidence / qualification |
|---|---|---|
| 0 — deployment | Backend healthy at integration tip, no integration-to-`master` merge | Current `/health` healthy. Private deploy/soak artifacts record the pre-deployment backup and original preflight; independent reviewer must verify them. |
| 1 — team and scope | Distinct owner and Leader slots/members; one observed pane and one fresh authenticated MCP session for each at final proposal | Private log records Checkpoint 1 PASS on 2026-08-30 with isolated panes. Live DB and tmux checks repeated on 2026-09-28. |
| 2 — continuation policy | Finite policy, autonomy off at proposal | Private log records initial 6/8/2 cap and Checkpoint 2 PASS on 2026-08-30. Final proposal used 15/11/2 after separately authorized increases; intermediate decisions require reconciliation. |
| 3 — owner proposal | Revision 15 proposed by member 17 at `decision_hold` | Created 2026-09-28 22:48:23; approval request 15, request mail 1118. Scope: implementation, one allowed path `player/src/decoders/tizflacgraph.cpp`, hosted CI, two failed heads. No coordinator proposal. |
| 4 — decision and ack | Distinct Leader approved; owner acknowledged | Decision mail 1121 at 22:57:53; server delivery mail 1122 at 22:57:53; member 17 acknowledged at 22:58:55. Decision and ack holds were separately released by the operator. |
| 5 — diagnostics and restoration | Earlier diagnostic revisions 3, 6, 8, 9, 12, 13 completed; all diagnostic revisions now terminal | Durable revision rows show no active diagnostic. Known hosted runs include 33221787425, 35969694440, 36041701517, 36049559994. Full per-run restoration evidence for earlier rounds still needs review. |
| 6 — implementation and product CI | Revision 15 completed; item became `ready_for_review` | One-file commit `b6880f54` on preserved PR branch; submitted at 23:39:58, completed at 23:41:49. Hosted run 36498366182: Core Meson build and full Playback smoke both SUCCESS on that head. Revision failed-head count 0; product and diagnostic retry counts remained 6 each. |
| 7 — human merge and cleanup | PR and item merged; autonomy, continuation and gate disabled; lease cleared | Human squash merge at 2026-09-29 08:46:06; Deck item `merged` at 08:46:47. Cleanup details below. Independent evidence review remains pending. |

Revisions 1–15 are all terminal. The private early-soak log records Checkpoint 3
and 4 blockers/retries and the first diagnostic-restoration PASS; it does not
cover every later revision. Its deployment log also records an **unsanctioned
local Tizonia build attempt during initial rollout**, with all build processes
stopped and no source edits. Do not describe the entire soak as having had no
local build. The final implementation path was reviewed
before push: Leader's corrected actual-diff PASS followed the coordinator's
`nSampleRate` → `nSamplingRate` compile-blocker correction. Leader's full PR
net-diff review reported no blocker across 16 files. The public PR contains
historical diagnostic/revert pairs, but no diagnostic instrumentation survives
in its net diff.

## Merge and terminal cleanup

1. GitHub records PR #875 `MERGED` into `master` at 08:46:06 and issue #821
   `CLOSED` at 08:46:07. Deck's work item reached `merged` at 08:46:47;
   `auto_merged_at` is NULL. The user reported temporarily disabling repository
   rules to perform the human merge. A post-merge GitHub read confirmed master
   protection again requires one approving review and enforces administrators.
   The bypass window and `reviewDecision=REVIEW_REQUIRED` must be visible to the
   independent reviewer; do not describe the merge as a protected approval.
2. Preset 2 autonomy was disabled. The exact-attempt scheduler job became
   unscheduled. No broad Tizonia dispatch was enabled during cleanup.
3. The owner's normal `workspace_released` report returned HTTP 409 because
   `release_blocker` counted 23 branch commits not ancestral to `origin/master`
   after the squash merge. The checkout was clean and the branch head remained
   pushed remotely. All 16 PR file blob SHAs match the merged master tree; two
   files were already identical on master before the squash commit. The operator
   then used the acquisition-bound force-release route with a recorded reason.
   Workspace 2 released at 08:59:47; the lease token and item pointer are NULL.
   Follow-up: [Deck issue #359](https://github.com/adrirubio/claude-deck/issues/359).
4. The recovery-only selector was removed from the ignored, mode-0600
   `backend/.env`; Deck restarted and `/health` passed. The operator-only
   recovery-gate endpoint now returns `active=false`.
5. Scope 1 continuation was disabled with numerical limits preserved for audit
   (15 revisions, 11 total failed heads, 2 per revision). Preset autonomy is
   false. No scope-1 lease, pending approval, nonterminal revision, open
   approval request root, or missing approved-request/delivery linkage remains.

The branch's local checkout was not reset, rebased, built, or deleted. Its clean
head is still `b6880f54`, matching the remote PR branch. No local Tizonia build
was run during the final revision or cleanup, and no auto-merge was attempted.

## Review gates before integration-to-master

- Independently inspect the private 2026-08-29 deploy/soak artifacts for the
  original Checkpoints 0–2 evidence, backup digest, the contained local-build
  deviation, and issue #329 runtime isolation through the later replay. These
  are not proven by the terminal-state audit alone.
- Reconcile the earlier diagnostic runs and exact tree-restoration evidence
  with the durable revision records. No diagnostic authority remains active.
- Independently review the human branch-protection bypass, restored rules,
  squash-merge lease exception, and Deck issue #359.
- Approve this evidence log independently. Keep the integration branch out of
  `master` until those checks are complete; do not equate green product CI with
  soak clearance.
