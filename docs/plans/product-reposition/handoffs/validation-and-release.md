# Product repositioning validation and release handoff

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Implement **P06** alongside each milestone: validate the integrated behavior, own the operator pilot measurements, and update user documentation to describe what has actually shipped.

Use the [product requirements](../product-brief.md), [experience specification](../experience-spec.md), [architecture contracts](../architecture-contracts.md), and [integration plan](../implementation-plan.md).

## Start conditions

Start P06 implementation validation and fixture preparation only after the autonomy feature has been merged into `master` ([G00](../implementation-plan.md#autonomy-merge-gate)). Branch from updated `feature/software-delivery-product-reposition` and record the autonomy merge evidence and base SHA. P06 then runs alongside each milestone.

M0's existing release owner supplies its combined-candidate review/test/UI evidence and actual merge record. P06 verifies that record after G00; it does not begin early to perform the autonomy release. Reconcile the pinned integration snapshot and route matrix with merged master, including any carried team-deletion prerequisite.

## Test environment

Use a disposable Deck database, temporary repository/config directories, mocked GitHub and provider operations, and isolated tmux processes where a real binding check is necessary. The backend API fixture must override its database and avoid scheduling the running factory.

Tests do not read, modify, restart, or replay the user's live factory. A live replay follows its own existing runbook and authorization.

Record the code SHA, fixture, test commands, and observation time with each acceptance result. Keep screenshots and runtime observations linked to the environment they depict.

## Shared fixture set

Prepare:

- At least two teams and several watched scopes, including the same GitHub repository watched by both teams with matching and differing dispatch labels, plus paused/prospective overlaps.
- All five harness IDs across configured slots, plus missing and unassigned owners.
- More than 100 work items to exercise pagination.
- Every documented raw status/category, an unknown future status, code/design work, and implementation/diagnostic phases.
- A preserved PR, pending Leader approval, pending owner acknowledgement, an escalated revision, and stale/ambiguous session bindings.
- Missing binaries, incomplete integrations, unknown credentials, and unsupported native surfaces.
- Operator-denial, delayed-response, refresh-failure, partial-setup, and mutation-conflict scenarios.
- Positive native capability flags without a page adapter, mismatched adapters, and read-only surfaces.
- Two enabled scopes under a recovery-only gate, a stopped/unknown scheduler, and a missing repository job.
- An active team with two configured scopes receiving a disabled third scope, plus a paused-team activation preview.
- Failed design work closed without a PR, proven terminal non-delivery, nonterminal operator escalation followed by manual/issue-update retry, sourced PR merges, and design acceptance with and without independent human evidence.
- Retained event history after team/repository rename, slot-provider changes, scope/team deletion, and numeric ID reuse.
- Team deletion blocked by queued/active/review/escalated work, approvals, revisions, leases, and concurrent acquisition; a separate genuinely deletable team.
- Tied slot positions, disabled/all-disabled rosters, pending authority, and explicit assignments that differ from legacy order for rollback checks.
- Configuration-only use with no scopes, an offline owner/Leader, missing access/labels/host settings, and a timed-out preflight.

Fixtures contain synthetic credentials and identifiers only. They do not copy real attempt IDs, tokens, private payloads, or production screenshots.

## Operator pilot measurements

P06 owns the measurement record; the coordinator names the actual measurement owner and participants after G00. Capture the baseline on the existing interface before M1a changes. Repeat tasks after M1a, hold the checkpoint before P03/M1b starts, then repeat applicable configuration tasks after M2.

Identify each participant's operator experience and implementation involvement. Maintainer/implementer runs are internal usability observations. Seek at least two operators who did not implement the system for broader usability claims, record recruitment gaps, and report such a small cohort as formative evidence. It does not establish market demand. Unavailable external participation can narrow claims without automatically blocking internal configuration or audit needs.

| Task | Measurement and expected result |
| --- | --- |
| Return to a mixed-team workload | Identify progress, a blocked issue, the next valid actor/action, and the difference between enabled configuration and effective intake |
| Inspect older work and recover context | Find an item beyond the first page, retain position through refresh intervals, and inspect the correct work/PR/team context without unintended actions |
| Recover an offline actor | Identify the correct owner/Leader, open its slot-specific launch plan, and understand authentication/review without launching by navigation |
| Continue configuration-only work | From an empty factory, find Harnesses and the guarded native summary/editor for the chosen provider |
| Establish a repository using an existing team | Reach saved configuration and a reviewed launch plan while preserving other repositories; M2 checks access, labels, host prerequisites, and overlaps |
| Reach a first reviewable PR | Measure only an actually observed pilot from setup start to a PR satisfying the recorded reviewable criteria |

Record task scripts, fixture/repository state, code SHA, provider mix, participant experience/involvement, observation time, task correctness/completion, elapsed time, navigation steps, errors, credential prompts, and interventions by reason. Include host configuration and required restarts in actual first-PR timing instead of starting the clock after the hard steps. Retain per-run results and sample sizes. Record comparison criteria after the baseline and before after-results; this packet does not invent numerical targets.

Fixture tasks measure navigation, interpretation, and setup behavior. They cannot establish live delivery time, autonomous reliability, or a first reviewable PR. Any actual pilot requiring live or paid execution follows its existing separate authorization and runbook; until observed, those measurements are `unavailable` with a reason. The ordinary fixture suite remains isolated from the running factory.

V31 owns the baseline/M1a comparison and checkpoint. The coordinator records proceed, proceed with named reductions, or defer, with needs justifying M1b/M2/M3, defects, participant limits, and allowed claims. Missing comparisons remain unavailable; any continuation for known internal needs must state that basis. No silent external-demand pass is permitted.

V32 repeats applicable tasks after M2 and records first-PR evidence or its absence. Broader onboarding or first-PR claims wait for corresponding observations even when functional acceptance is green. Cookie/session login is a separate evaluation if measured token friction warrants it.

## M1a acceptance matrix

| Case | Required observation | Owners |
| --- | --- | --- |
| V01 | Counts cover the complete filtered set, category sums equal total, and count links preserve filters | P01, P02 |
| V02 | Duplicate GitHub issues in different scopes remain separate; missing owners remain unassigned | P01, P02 |
| V03 | Pagination handles tied timestamps, representative persisted mutation updates, malformed/filter-mismatched cursors, and explicit refresh/filter reset; update time is not presented as an execution heartbeat | P01, P02 |
| V04 | Raw status, display category, code/design type, phase, and stopped revision state remain distinct | P01, P02 |
| V07 | Factory page/GET loading performs no dispatch, lease claim, Mail acknowledgement, launch, or active-project write | P01, P02 |
| V08 | Basic details work without an operator token; private recovery history preserves its authorization | P01, P02 |
| V09 | Agent decisions, operator remedies, and human PR review have different actors; an offline known actor opens the correct reviewed launch plan without automatic launch or browser approval | P01, P02 |
| V10 | Retry and remedy eligibility match server checks; preserved PR and stale-attempt conflicts remain actionable | P01, P02 |
| V11 | M1a native routes require checked-in provider/page/API adapters and permitted access; positive integration flags cannot grant pages/writes. Repeat in M1b with catalog agreement, unknown/mismatch/failure, and access intersection | P02; P03 repeats in M1b |
| V12 | Verified bindings link to read-only terminals; ambiguous or unrelated sessions never become the selected owner | P01, P02 |
| V13 | New factory projections enforce the explicit field allowlist, including omitted nonce/head identity, workspace paths, and raw summaries. New responses, exports, and ordinary logs expose no credential/hash/private command payload | All, at each affected milestone |
| V14 | A single manual agent can launch/use Bridge without automatic dispatch; an empty factory prominently exposes guarded Harnesses/configuration access. M1a must work without the planned P03 API; M1b retains access through its catalog guards | P02; P03 repeats in M1b |
| V15 | Filters, aliases, browser history, dialogs, focus, and tables work with keyboard input and narrow layouts | P02; P03 repeats in M1b |
| V16 | Failed/stale refreshes retain labelled data; obsolete responses cannot overwrite current filters; reads remain bounded | P01, P02; P03 repeats in M1b |
| V26 | Configured enablement and effective intake differ correctly for recovery-only, stopped, missing-job, and unknown-runtime cases; suspended polls and protected gate details remain correctly handled | P01, P02 |
| V27 | With more than 100 rows, Load more pauses list polling and preserves rows/cursor/scroll/focus through multiple intervals, tab visibility changes, and an older first-page response; only explicit refresh/filter reset restarts the list | P01, P02 |
| V33 | Team deletion rejects enabled automation and in-use work/approval/revision/lease states before writes, including acquisition races; valid deletion and rollback preserve correct session/record state | Release/coordinator prerequisite; P06 verifies after G00 |
| V34 | Existing abandon-route escalation stays in attention, does not assert process stop or terminal outcome, and retains the authoritative manual/issue-update retry rules and preserved-PR blocks | P01, P02 |
| V36 | M1a warns about same-label enabled scopes on one repository while preserving identities; M2 checks prospective activation/team resume and requires acknowledgement of current overlaps without claiming arbitration | P01, P02; P04 extends in M2 |

For V10 and policy controls, test the audited authorization matrix directly on the server. Operator-only routes deny missing/wrong/operator-inappropriate credentials. Retry must also accept a valid authenticated connected current-Leader MCP session and reject stale/wrong-Leader or unrelated sessions. Launch retains its constrained authenticated agent path while denying operator-only overrides. Verify browser operator headers and actionable `401`/`403`/`409` results. A disabled button alone is insufficient evidence.

Check native routes with Claude, Codex, Copilot, OpenCode, and Pi selected and with a remembered legacy provider preference. Factory views must still default to all matching work.

V11 must include OpenCode config/plugins/usage and Copilot integration-only capabilities that currently have positive flags but no corresponding native page. Check navigation, direct URLs, aliases, and native dashboard cards before any child fetch or mutation.

For V26, both enabled scopes must show new intake blocked under the recovery-only gate, regardless of which attempt can receive recovery processing. Verify the safe response omits the protected target, nonce, and head. For V27, include an action/detail refresh while browsing older rows; it must not reset the paused list.

V33 is a required server guard, not a deletion dialog. Its in-use cases include pending, review, escalated, and failed work as well as executing work. Inject a race before commit and verify no orphaned live attempt, lease, or reassigned Mail session. V34 exercises both retry-eligible and preserved-PR/active-authority-blocked items; issue-update retry uses the real predicate under mocked watcher input.

V36 distinguishes active collisions from disabled prospective overlaps and differing dispatch labels. A team-filtered view must still warn about a conflicting scope outside that filter. It adds no dispatcher behavior. Repeat its activation portion in M2.

## Pilot checkpoint acceptance

| Case | Required observation | Owner |
| --- | --- | --- |
| V31 | Baseline and M1a task comparison records correctness, time/navigation, credential prompts, interventions, participant provenance, sample size, missing observations, justified next scope, and coordinator disposition before P03 starts | P06 |

Functional M1a acceptance is separate from V31's evidence and claim limits. No live or paid run is implied by this checkpoint.

## M1b acceptance matrix

| Case | Required observation | Owner |
| --- | --- | --- |
| V05 | All five harnesses have coherent full cards and sourced operational classifications independent of native feature count | P03 |
| V06 | Missing CLI/integration and unknown credentials agree with the launch planner and produce useful explanations | P03 |

Repeat V11, V13, V14, V15, and V16 for the new catalog and components. Include catalog failures, access downgrades, adapter mismatch, keyboard/navigation behavior, and retained manual/configuration-only access. A required M1b catalog failure must not silently restore broader static permissions. M1a delivery reads remain independent of that catalog.

## M2 acceptance matrix

| Case | Required observation | Owner |
| --- | --- | --- |
| V17 | Legacy migration preserves effective Leader and authority identities across real Python/SQL consumers, tied positions, disabled/all-disabled rosters, and pending requests/revisions; repeated startup does not reset assignment | P04 |
| V18 | Cross-team, disabled, missing, stale, active, concurrent, and unauthorized Leader changes fail correctly | P04 |
| V19 | Reordering preserves authority; Leader deletion/disable is guarded; copy/import maps new IDs correctly | P04 |
| V20 | Setup remains a draft until confirmed; protected creation/import/duplication and their browser clients enforce intended authority; new teams/scopes separate save, reviewed launch, and activation with finite defaults | P04 |
| V21 | Partial or unknown setup/launch outcomes are visible and resumable without blind duplicate creation or respawn | P04 |
| V28 | Adding a scope to an active team preserves its other scopes, policies, activation, Leader, and sessions; the new scope stays disabled through interrupted saves, blocked role edits never pause the team, and later activation previews its actual scope/team effect | P04 |
| V32 | M2 repeats applicable tasks with participant provenance, configuration correctness, host-step and credential friction, actual first-PR evidence or its absence, and bounded onboarding claims | P06 |
| V35 | Explicit preflight checks checkout, polling/repository access, labels, and selected host-auth prerequisites independently; missing/timeout/unknown results are actionable, prevent false readiness/guided activation, and expose no secret values | P04 |
| V37 | Paused rollback preserves representable legacy authority on an isolated backup, refuses divergent/unrepresentable assignments, and never silently restores a stale production database | P04 |

Migration evidence must include tied positions and outstanding approval/revision records, with the caller-order inventory attached. A fresh empty database alone does not exercise authority compatibility. Do not assume that tied positions prove an existing production bug or require a uniqueness constraint.

Repeat V13 for configuration presence/redaction and V36 for a collision appearing after the activation review, including a team-enable action resuming sibling scopes. V35 includes absent token configuration, operator-auth failure before preflight, denied repository access, missing labels, rate limits/timeouts, changed inputs, and host restart instructions. Preflight performs no GitHub writes or implicit issue intake.

## M3 acceptance matrix

| Case | Required observation | Owner |
| --- | --- | --- |
| V22 | Required policy/Leader audit insert and mutation commit atomically, with authentic actors and sanitized before/after values | P05 |
| V23 | Replay, duplicate delivery, interrupted transport, and rejected/uncertain recovery outcomes do not invent success or repeat mutations | P05 |
| V24 | Metrics use sourced lifecycle boundaries and coverage; imported snapshots cannot create historical delivery times | P05 |
| V25 | Missing or partial usage attribution stays unknown or explicitly partial, with no misleading total cost | P05 |
| V29 | `completed` without delivery evidence stays unknown; operator escalation/abandon and retry create no terminal non-delivery; proven terminal disposition, sourced merges, and independent human design review remain distinct without double-counting | P05 |
| V30 | Renames, provider reassignment, valid scope/team deletion, and numeric ID reuse preserve ledger facts, historical attribution/filtering, and aggregate counts; deleted live links become unavailable | P05 |

Inject an audit-write failure and verify unchanged policy values. Validate metric calculations against a small fixture ledger whose expected results can be checked manually.

For V29, a failed design issue closed without a PR contributes no delivered or human-reviewed result. A merged design PR can count as delivered while human review remains unknown. Request/revision cancellation or operator abandonment/escalation must not alone produce terminal non-delivery. Reuse V34's retry scenarios. For V30, first satisfy the V33 deletion guard, then query retained context keys after deletion and verify that a reused numeric ID does not inherit old history. Repeat V13 for event and export redaction.

## Regression and browser checks

Run focused tests at package completion, then affected combined suites at milestone integration. The frontend scripts are:

```bash
cd frontend
npm run test
npm run lint
npm run build
```

Backend coverage follows changed behavior: factory reads, existing team/work projections, provider contracts, operator authentication, approval concurrency, recovery/cancellation, workspace release, and SQLite compatibility migrations.

P02a establishes reusable fetch/router/fake-timer/visibility fixtures from the existing frontend test pattern. Use them to test request generations and polling deterministically; browser viewport checks complement those tests. P03 reuses them after the checkpoint.

Perform browser acceptance at 360px, 768px, and 1280px with light/dark themes. Verify visible status text, keyboard focus, dialog dismissal/restoration, long issue/repository names, and empty/error states. Start with fixture services and identify fixture images as such.

If a check fails because of an existing integration defect, record the failure and its source separately. Do not mark the relevant acceptance case passed.

## User documentation

Update documentation only for implemented milestone behavior:

| File or area | Required change |
| --- | --- |
| `README.md` | Lead with bounded observation/intervention, describe mixed harnesses and the M1a pilot, retain installation and trust facts |
| GitHub repository description | Prepare milestone-accurate copy for the release owner; remove the configuration-only positioning without implying unproven delivery reliability |
| Public website landing copy | Identify its source and publishing owner, reconcile it with shipped README/docs claims, and record published or pending status |
| `docs/index.md` and `docs/guide/index.md` | Product story, daily operating flow, and supported scope |
| `docs/guide/quick-start.md` | Observe work or launch manually, then connect repositories and teams |
| `docs/features/dashboard.md` | Describe the new Overview and relocate native configuration summaries |
| `docs/features/agent-teams.md`, `agent-bridge.md`, and `agent-mail.md` | Explain their role inside delivery and their standalone use |
| New Work, Repositories, and Harnesses feature guides | Explain effective automation, nonterminal escalation, paused list refresh, safe reuse/deletion, overlaps, offline-actor launch review, and the M1a/M1b availability distinction |
| New factory API documentation | Distinguish safe reads, protected reads, and existing mutations |
| `docs/.vitepress/config.ts` | Add shipped guide/API navigation and update relevant descriptions |
| Existing Codex/native support guides | Keep real capability and restore/usage limits accurate |

Retain the Claude Deck name. Do not announce a rename or universal configuration parity.

Explain that agent plan approval, operator intervention, and human PR review are separate. Explain automation pause behavior, code/design review differences, build hints, and unknown readiness/cost where applicable.

At M2, call the flow guided configuration, document remaining host/label procedures and creation-route authorization, and keep the existing per-tab token workflow explicit. Cookie login is not shipped by this plan.

At M3, explain terminal tracking versus evidenced delivery, unknown/non-delivery counts, historical labels, and retained audit data after operational-record deletion. Broader onboarding and first-PR claims must reference actual pilot evidence and its coverage.

Future audit charts, explicit-role fields, and guided setup should not appear as shipped features before their milestone is integrated. Keep the implementation packet excluded from the public documentation build through the top-level VitePress `srcExclude` rule for `plans/**`.

P06 prepares release text; external repository metadata and website publishing follow the release owner's existing publishing authority. This planning update does not publish those surfaces. Missing access or an unknown website source is recorded as a concrete pending release item.

## Acceptance evidence

Produce a milestone evidence record with:

- Integrated SHA and fixture/environment.
- Acceptance cases with passed, failed, or unavailable results.
- Commands and test results.
- Browser screenshots and keyboard/layout observations.
- Compatibility and migration evidence.
- Reconciled route/principal matrix, team-deletion prerequisite, and safe-field decisions.
- Operator baseline and M1a/M2 comparisons, with participant implementation involvement, per-run measurements, unavailable observations, and pre-M1b checkpoint disposition.
- Documentation links and build results.
- GitHub description/public website copy and published or pending status for each release surface.
- Unresolved defects and limits on the product claims.

Documentation verification includes local links, rendered guide navigation, and the normal app/documentation build where those surfaces changed.

The existing soak-evidence pass remains distinct from UI acceptance, the combined integration test result, live replay, and integration-to-master clearance. G00 requires evidence of the actual autonomy merge into `master`.

## Agent start instruction

> Start P06 only after G00, including fixture preparation. Branch from updated `feature/software-delivery-product-reposition` and verify the M0 evidence and reconciled contracts. Capture the existing-interface baseline, validate M1a, and record the pilot checkpoint before P03 starts; then validate M1b, M2, and M3. Separate internal usability, independent operator evidence, live outcomes, and release gates. Record missing evidence and publish only milestone-accurate documentation through the existing release process.
