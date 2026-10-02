# Fork product bootstrap reconciliation ledger

Recorded 2026-10-02 for fork #3/#4 and bootstrap PR #15. This is coordination evidence and a contract proposal for independent review; it is not self-acceptance or an intake instruction.

## Source and release record

| Evidence | Exact identity / disposition |
| --- | --- |
| Preserved source packet | Commit `86a0f4702ef40f3f88bc5e1f53b26803ee7a0881`; all twelve imported packet files remain recoverable there. Do not rewrite that commit or access the original source workspace. |
| Initial reviewed bootstrap candidate | `3df0cfd69826d1e003ad0683e49e0890e294c678`, PR #15, branch `product/bootstrap-packet`; B4 identified stale routing and pilot-authority prose. Revised acceptance must name the new exact head. |
| G00 / completed M0 | Upstream PR #399 merged 2026-10-01T19:20:30Z, resulting SHA `ac9252242fcf436c3ea9997add5d32416cad2cd1`, recorded by fork #4. No upstream operation is authorized. |
| Product integration / controller pin | `ac9252242fcf436c3ea9997add5d32416cad2cd1`; product PRs target `feature/software-delivery-product-reposition` on `juanrubio/claude-deck`. |
| Approved product PRs / migrations | None recorded. Packet review pending; no product migration or runtime deployment performed. |
| Other runtime / hotfixes | Not inspected; no access or changes authorized. No approved cherry-picks recorded by this assignment. |
| Heavy operations this assignment | None. `product-heavy` is mandatory for full suites, browser fixtures and production builds; exit 75 waits. Record holder/category/UTC start/end when acquired. |

## Binding and authority

Authenticated Mail on the product controller verifies preset 1: B1 member 2 / slot 1 Leader; B2 member 3 / slot 2 Implementer; B3 member 4 / slot 3 Implementer; B4 member 5 / slot 4 Reviewer. B2/B3 sent readiness reports (Mail 8/9); B4 acknowledged exact reviewer binding (Mail 5) and standing workspace status (Mail 11). These messages prove receipt/preparation, not completion of implementation or review.

Leader `deck_list_work_items(status="")` and `status="escalated"` both returned no items at startup. No cold-start retry applies. No dispatch workspace supersedes B1's standing bootstrap branch in that evidence. Supplied owner-bound workspaces take precedence on later dispatch; never infer a release from terminal output or force-release a lease.

User authorized prerequisite work, but root operator arming is still required before scope activation or dispatch labels. Human merge remains initial policy. B4 reviews each exact PR head independently; changed heads invalidate acceptance. Operator alone decides pilot proceed/narrow/defer and promotion/deployment. B1 records those decisions and cannot approve its own bootstrap changes.

## Dependency map and exclusive file schedule

Roadmap issue bodies #3–#11 were read at startup. All are open; no explicit `Blocked by #N` list was present. The graph below resolves their prose using packet milestones and the existing queue. Parent issue #3 is tracking, not a closure prerequisite. Issues #12–#14 are open reconciliation follow-ups with ambiguous remaining gates; do not invent dependencies or dispatch them.

| Issue | Owner | Required evidence before admission |
| --- | --- | --- |
| #4 packet | B1 | Standing prerequisite assignment; B4 acceptance of revised PR #15 exact head before downstream implementation |
| #11 P06 | B4 | Standing baseline/review assignment at controller pin; no permanent implementation lease |
| #5 deletion | B2 | Accepted #4 packet, root arming, supported dispatch and distinct Leader plan approval |
| #6 P01 | B2 | Accepted packet and integrated/reviewed #5, root arming, dispatch/approval; freeze fixtures with B3 |
| #7 P02 | B3 | Accepted packet and independently reviewed P06 baseline; accepted versioned P01 fixture handoff before consuming fixtures; integrated P01 reads before M1a acceptance |
| #8 P03 | Assigned later | Accepted combined M1a SHA including P01/P02/V33/P06, and explicit operator pilot disposition permitting the named scope |
| #9 P04 | Assigned later | Accepted M1b, mutation/deletion prerequisites; explicit-authority migration and guards integrated together |
| #10 P05 | Assigned later | Accepted M2 and integrated P04 authority/guards |

Serialize B2's #5 edits to `agent_teams.py` / `agent_team_service.py` and guard tests before #6 projection/router/schema work. B3 owns frontend views and routes after baseline acceptance; B2 does not edit those files. Backend router registration is scheduled with B1 before writing. B4 owns separate validation artifacts/review checkouts. P03 receives Harnesses ownership only through an explicit P02 handoff. Start with one active dispatch; no budget or concurrency increase follows this ledger.

On blocker-merged notifications, update all prerequisite evidence and retry only an escalated dependent whose entire blocker set is satisfied, once per event, using its API work-item ID. Ambiguous graphs stay escalated. Do not retry before arming or override leases/approval/budgets.

## Authority and browser contracts

Source inspection at `ac9252242fcf436c3ea9997add5d32416cad2cd1` confirms the architecture matrix in `backend/app/api/v1/agent_teams.py`; current client is `frontend/src/features/agent-teams/api.ts`, using per-tab operator headers. This is source reconciliation, not executed authorization evidence.

| Contract | Current server / browser signature and preserved rule |
| --- | --- |
| Retry | Session-or-operator; agent must be connected MCP bound to current Leader with capability enforcement. `retryGithubWorkItem(workItemId, operatorToken)`; server rechecks canonical retry eligibility. |
| Plan / launch | Session-or-operator with `_require_safe_agent_launch`; browser plan/launch helpers take operator token. Preserve plan confirmation and constrained agent requests. |
| Continuation request cancellation | Session-or-operator plus requester checks; `cancelGithubContinuationRequest(workItemId, requestId, operatorToken)`. Not active-revision cancellation. |
| Active revision cancellation | Operator; `cancelGithubActiveRevision(workItemId, revision, reason, operatorToken)` supplies expected revision/nonce. Preserve service state/authority checks. |
| Recovery checkpoint release | Operator; `releaseGithubRecoveryCheckpoint(workItemId, revision, stage, operatorToken)` supplies revision, nonce, approval ID and stage. Not workspace release. |
| Resume / escalation | Operator; `resumeGithubWorkItem(presetId, workItemId, operatorToken, reassignToSlotId?)` and `abandonGithubWorkItem(workItemId, reason, operatorToken)`. Abandon remains nonterminal escalation. |
| Owner workspace release | Authenticated work report, owner slot and lease required; releasable status and `release_blocker` checks, conditional lease identity, credential revocation. Preserve normal owner release; browser operator force-release is a separate expected-lease remedy. |
| Creation/import/duplication | Four route families still have no route-level operator dependency; browser `createAgentTeamPreset(input)`, `createAgentTeamFromMail(input)`, `createAgentTeamFromBridge(input)`, `duplicateAgentTeamPreset(presetId, input)` have no token parameter. P04 changes server and callers together. |
| Team deletion | Operator route exists, but service reassigns sessions/deletes records without the required active-state guard. B2 #5 supplies transaction/race/rollback evidence; V33 required. |

First-enabled slot order `(position, id)` remains current Leader authority. Explicit assignment is P04 planned work; do not treat charter text as its implementation. Initial/continuation approval identities and owner/Leader separation, cancellation and lease release remain canonical service authority.

## Contract freeze and remaining acceptance evidence

The [architecture wire contract](architecture-contracts.md#wire-contract-and-fixture-freeze) resolves the missing list/detail envelopes and link/error semantics raised by B3 in Mail 13. It is a proposed schema-v1 contract until B4 independently accepts this exact packet head.

B2 owns `backend/tests/factory/fixtures/v1/` after #6 dispatch/approval; B3 owns `frontend/tests/fixtures/factory/v1/` copies. Each copy manifest records `schema_version`, endpoint, query, expected HTTP status, scenario, source repository/path and full source commit. B3 acknowledges exact fixture SHA before consumption; changes update canonical contracts/fixtures and consumers together. No fixtures exist yet and no response tests have passed. P02 can use reviewed fixtures while P01 endpoints proceed; real read integration remains an M1a gate.

Outstanding: B4 packet exact-head review; independently reviewed #11 baseline artifact/SHA; versioned P01 fixtures and acknowledgement; deletion guard; first complete dispatch/review/human integration/normal-release evidence; milestone combined-SHA checks. Human task timings, independent participant observations and benefit measures are unavailable. Missing observations are not a pass. Queue gate booleans stay false until corresponding evidence is accepted; eligible label queue stays empty until root arming and admission gates.

B4 preliminary baseline report (Mail 17) identifies source pin `ac9252242fcf436c3ea9997add5d32416cad2cd1` and 20/20 isolated jsdom checks in three files under `product-heavy`. Artifact commit and independent baseline review remain pending. Environment caveat: copied controller dependencies, actual Vitest 3.2.7 versus lock declaration 3.2.4; existing dialog-description warnings. No browser screenshots or human timings observed. This is a reported result, not B1 independent reproduction or V31 acceptance.
