# Agent deployment and autonomous coordination plan

**Date:** 2026-10-02.

**Status:** Product lane started first and is now paused for the review workflow repairs recorded below. This document does not launch sessions, deploy a backend, enable autonomy or authorize automatic merges.

Deploy four product harness sessions first, coordinated through a dedicated Claude Deck instance, authenticated Agent Mail and GitHub. Preserve the Tizonia runtime and roster. Add two soak preparation sessions when the user chooses to start that lane. Both lanes are designed to operate independently and eventually concurrently, with their own coordinators and one shared host resource limit.

## Decisions and scope

| Decision | Required behavior |
| --- | --- |
| Start order | Product lane first. Soak preparation and live intake wait for a separate start decision. Product work does not require soak completion. |
| Product tracking | [#3](https://github.com/juanrubio/claude-deck/issues/3), label `lane:product-reposition`. |
| Soak tracking | [#403](https://github.com/adrirubio/claude-deck/issues/403), label `lane:tizonia-v1-soak`. |
| Product integration | All product implementation and packet reconciliation PRs target `feature/software-delivery-product-reposition` on `juanrubio/claude-deck`. Task branches start from its current tip. |
| Integration baseline | The fork product integration branch was created from `ac9252242fcf436c3ea9997add5d32416cad2cd1`, the master merge of [PR #399](https://github.com/adrirubio/claude-deck/pull/399), merged 2026-10-01T19:20:30Z. This satisfies G00. |
| Product promotion | A separately reviewed promotion PR to `master` follows accepted milestone evidence and an explicit promotion decision. Integration merges do not deploy either runtime. |
| Deferred hardening | #356, #389 and #390 remain outside both active queues under `autonomy-hardening`; #356 is also `deferred`. |

This plan supersedes older packet instructions that target individual product PRs at `master` or say G00 is still open. [#4](https://github.com/juanrubio/claude-deck/issues/4) owns reconciliation of the remaining packet, source assumptions and contracts. The milestone and acceptance requirements in the packet continue to apply.

The Tizonia source plan is `docs/deploy/tizonia-v1-post-merge-soak-plan.md` in the `claude-deck-master-promotion` worktree. Its deployment, arming, human merge, checkpoint and exit gates govern Lane A when that lane starts.

## Sessions and models

The assignments below are recommendations, subject to model availability in the installed harness and account. GPT-6.1 Sol is the default implementer and coordination model; GPT-6 Astra is reserved for independent validation and demanding operational review. These choices follow [OpenAI model selection guidance](https://developers.openai.com/api/docs/guides/model-selection), checked 2026-10-02.

| Session | Start | Harness and model | Reasoning | Responsibility |
| --- | --- | --- | --- | --- |
| B1 Product Leader | First | Codex, GPT-6.1 Sol | Medium; high for authority or integration decisions | Own #3 and #4, ready queue, plan approvals, shared-file schedule, integration decisions and release ledger. |
| B2 Product backend | First | Codex, GPT-6.1 Sol | High | Own #5 deletion guard, then #6 P01 and later assigned backend work. |
| B3 Product frontend | First | Codex, GPT-6.1 Sol | High | Own #7 P02, contracts consumed by the UI, fixtures, adapters and delivery views. |
| B4 Product validation | First | Codex, GPT-6 Astra | High | Own #11 P06, pre-change baseline, independent PR review and combined milestone evidence. |
| A1 Soak coordinator and reviewer | When Lane A starts | Codex, GPT-6 Astra | High | Own #403, read-only reconciliation, operational evidence review and checkpoints. |
| A2 Soak engineer | When Lane A starts | Codex, GPT-6.1 Sol | High | Own #405 migration/rollback preparation and #406 backlog preflight implementation. |

Start with four product sessions. The later preparation layout has six working sessions across both lanes. The existing three Tizonia Leader/Generalist/Specialist sessions are separate from this count and must not be repurposed for product work. When live Tizonia intake is authorized, A2 can be parked after preparation acceptance, giving up to eight active sessions if the three Tizonia sessions participate alongside A1 and B1–B4.

The soak plan records Pi/Kimi K3 for the Tizonia Leader and Pi/MiMo-V2.6-Pro for the owners. Revalidate their actual configuration before live intake. A roster/model change requires a separate operational decision. Preserve one active Tizonia dispatch, even when several roster panes are available.

Reuse the product roles for later packages instead of opening six package sessions at once. Start a fresh task conversation for substantial role changes, carrying the accepted contract, issue, base SHA and outstanding evidence forward.

## Directory and runtime layout

Each writing session uses its own task branch and directory. Product worktrees may share a Git repository, but never the same writable checkout. Reviewers inspect an exact PR head in a separate review worktree; they do not switch the implementer's directory.

The following names are proposed destinations, not claims that these directories exist:

```text
claude-deck-product-controller/    Pinned control-plane release
claude-deck-product-coordination/  B1 packet and coordination task branch
claude-deck-product-backend/       B2 current backend task branch
claude-deck-product-frontend/      B3 current frontend task branch
claude-deck-product-validation/    B4 validation branch
claude-deck-product-review-<pr>/   Exact PR SHA for independent review

claude-deck-soak-coordination/     A1 evidence branch, created later
claude-deck-soak-preflight/        A2 branch from approved release pin, created later
<existing-live-checkout>/         Dedicated pinned Tizonia backend
```

Preserve uncommitted edits in the existing `claude-deck-product-reposition` documentation worktree. Do not reset or rebase it, and do not use its older code as the implementation base. Reconcile its documentation through #4 and make the accepted packet available to the new task worktrees.

Use a dedicated product Deck instance on a recorded reviewed release SHA, initially the PR #399 release candidate subject to setup review. Do not run the coordinator from an implementation branch, hot reload it as agents edit code, or replace its code when a product PR merges. Restarting or upgrading this controller is a separate recorded operation.

The product controller needs its own absolute database path, listening ports, GitHub credentials, operator credential and session bindings. Implementation tests use additional disposable databases, synthetic credentials, mocked GitHub/provider calls, dedicated tmux sockets and separate app ports. Restrict any shared GitHub credential's intended use to the product repository/integration workflow.

Product agents must not use the Tizonia DB, `.env`, operator token, preset, workspaces or wake targets. Git worktrees separate files; they do not prevent same-UID processes from reading credentials. Use OS-user or container isolation with restricted mounts, or record explicit gate-owner acceptance of the remaining threat boundary and compensating controls. Do not provide operator credentials to agent panes.

## Durable coordination

GitHub is the durable work and review record. The product controller stores dispatch, approval, workspace and session state. Agent Mail carries authenticated notifications and handoffs. Terminal wakes notify only an exact bound recipient session; a guessed, ambiguous or cross-project wake target fails closed.

B1 is the designated Leader, using the merged release's actual authority selection rather than a descriptive role field. At that release, the first enabled roster slot is the Leader. Verify its authenticated member, slot and live pane binding, and keep it distinct from the implementation owner whose plan it approves.

Each handoff identifies:

- Issue, work package and intended recipient.
- Branch and exact commit or PR head SHA.
- Accepted contract/fixture version and delivered artifact.
- Checks completed, findings and known limitations.
- Requested next action and relevant dependency or resource gate.

For example, B2 sends B3 the accepted API fixture path and commit SHA. B3 acknowledges that version before integration. A contract change updates the canonical contract and consumers through an explicit handoff. B4 reviews an exact head; a changed head invalidates review acceptance until rechecked.

Keep credentials, capability tokens, lease tokens/hashes, private commands and message bodies out of public issue comments and evidence logs. Publish safe issue/PR IDs, SHAs, status summaries and UTC times.

## Ready queue and autonomous work cycle

Use one watched product repository scope. Ownership labels remain `lane:product-reposition`; a separate proposed `product-dispatch-ready` label marks eligible implementation issues. Proposed routing labels `product:backend` and `product:frontend` select the relevant owner. Configure and verify these labels against Deck's actual routing before using them.

Do not give the tracker or every package the dispatch label. Adding the configured dispatch label queues work, and removing it during an attempt escalates that attempt. B1 changes readiness only when no active attempt will be disrupted.

Deck does not infer the packet's dependency graph from issue labels. B1 must maintain a persistent dependency ledger and reconcile it before marking work ready. If reliable unattended dependency scheduling is required, implement and review a small scheduling controller; it must enforce the same graph, authority and finite retry policy. Do not assume that four open harness windows provide durable unattended orchestration.

The coordination cycle is:

1. B1 verifies dependency evidence, available owner, exclusive shared-file assignment and resource availability, then marks an eligible implementation issue ready.
2. Deck dispatches to an owner-bound task workspace. The implementer proposes a bounded plan and the distinct Leader approves through the supported authority flow.
3. The implementer opens a PR targeting the product integration branch and sends B4 the exact head, results and limitations.
4. B4 independently reviews the diff and reproduces the relevant checks in isolated fixtures. Findings return to the implementer; every changed head is reviewed again.
5. The merge controller checks required hosted checks and independent review for that same head before integrating it. B1 records the merged SHA and updates dependencies.
6. B4 validates the combined integration SHA against the milestone cases. B1 records acceptance or a concrete blocker before advancing the queue.

### Ordinary PR review corrections

B1 routes B4's findings to the current implementation owner and checks that the
corrections fit the approved plan. For a nonterminal, non-escalated initial
implementation attempt with `active_scope_revision=0`, opening a PR or reaching
`ready_for_review` does not end the initial plan. The owner continues on the same
issue branch and PR after reconciling owner binding, dispatch nonce, workspace
lease, normalized approval and owner acknowledgement. Missing, revoked or stale
authority, an operator pause or a safety hold stops work.

`continuation_disabled` concerns escalated recovery. It does not by itself revoke
an initial plan. Do not manufacture an escalation, request recovery, retry,
release the workspace or change policy solely to make in-scope review corrections.
Do not submit a second `pr_opened` report for an already tracked PR. Work outside
the approved plan needs supported new approval. Scoped or diagnostic continuations
retain their approved paths, commands, completion rules and finite budgets.

After each push, the owner sends B4 the new full head SHA. B4 reviews that head;
B1 reconciles the review disposition and actual hosted checks for the same SHA.
Old review acceptance and CI readiness do not accept a changed head. The current
human merge policy remains in force. Owner-context `review_rework_guidance`
explains this workflow and does not grant approval.

### Factory repair gate, 2026-10-02

Lane B is paused while upstream [#425](https://github.com/adrirubio/claude-deck/issues/425)
and [#426](https://github.com/adrirubio/claude-deck/issues/426) repair changed-head
verification under human merge policy and the ordinary review instructions.
Fork [#26](https://github.com/juanrubio/claude-deck/issues/26) owns their integration
backport and controller deployment. These issues carry `factory-maintenance` and
must not receive the product dispatch-ready label.

Preserve the current PR, partial edits, initial approval and owner lease during
this pause. Resume requires accepted fixes, checks for their exact heads and a
recorded, reviewed controller deployment that preserves the verification-clock
fix and accepted P01 fixtures. An integration merge alone does not deploy the
controller. The root operator reconciles authority and live bindings, clears the
repair pause and explicitly resumes; B1 then routes the outstanding P02 findings
through the ordinary review loop. Milestone, pilot and promotion gates remain in
force.

B4's continuing P06 assignment must not hold a dispatched implementation lease indefinitely. Run validation/review as a standing coordination role, with bounded review tasks and separately recorded acceptance results. Documentation/design work follows its own reviewed disposition; do not create dummy code PRs to satisfy dispatch bookkeeping.

Start with one active product dispatch to prove session binding, wake isolation, routing and normal release. Permit two simultaneous implementation assignments only after review of those results and a recorded concurrency decision. Use one product scope; do not enable multiple scopes sharing slots while #389 remains unresolved. Two eligible workers may edit concurrently, but shared-file and host build limits still apply.

## Product sequence

| Stage | Assignments | Completion or start gate |
| --- | --- | --- |
| Bootstrap | B1 reconciles #4; B4 captures P06 baseline; B2/B3 inspect contracts | Accepted packet and recorded baseline before P02 UI changes. No product setup touches the Tizonia runtime. |
| M1a implementation | B2 sequences #5 deletion guard and #6 P01; B3 builds #7 P02 against agreed fixtures; B4 validates | P01/P02 integration, V33 deletion evidence and required P06 cases. Assign shared backend files sequentially. |
| Pilot checkpoint | B4 reports baseline/after task measurements; B1 assembles decision packet | Operator records proceed, named reductions or defer. No agent invents human observations or accepts the decision on the operator's behalf. |
| M1b | Assign #8 P03 after the recorded pilot decision | Operations/readiness and accepted M1b evidence. Transfer Harnesses file ownership from P02 explicitly. |
| M2 | Assign #9 P04 | Accepted M1b, mutation/deletion prerequisites, explicit authority migration and setup evidence. |
| M3 | Assign #10 P05 | Integrated P04 authority/guards and accepted audit/outcome evidence. |
| Promotion | B1 prepares a reviewed integration-to-master promotion | Explicit promotion decision and accepted release evidence. No automatic deployment. |

P06 continues throughout. Existing UI issues #364–#366 belong to Lane B for reconciliation of already-landed fixes and remaining criteria. Avoid duplicate implementation. The functional packet and handoffs own detailed acceptance cases; this document owns agent deployment and coordination.

## Merge and intervention policy

Bounded automatic merging of eligible code PRs into `feature/software-delivery-product-reposition` is the proposed steady-state policy. Initial operation uses human merge until setup and review enforcement are demonstrated and the operator explicitly selects the automatic policy and finite daily cap.

Deck supports automatic merging after eligible hosted checks, but this plan does not establish that it enforces B4's independent review. Before enabling automatic merge, prove an enforceable exact-head review gate through the controller and repository protection configuration. A comment or label is insufficient unless the controller validates its authorized origin and SHA. Check the behavior when a head changes, checks are missing, or credentials could bypass protections. Fail closed when review state is uncertain. Design PRs retain human review under the existing pipeline.

Ordinary implementation, approved handoffs, bounded revisions, eligible retries and integration may proceed autonomously after setup. The operator retains decisions for credentials and initial enablement, pilot disposition, changes exceeding scope/budgets, unresolved authority or isolation exceptions, promotion to master and deployment.

When an issue needs intervention, leave a specific blocker with the required decision and evidence. Let unrelated eligible work continue. Exhausted budgets, uncertain authority, repeated failures or missing human prerequisites do not justify silent retries, budget increases or policy changes. Resume only through the supported actor and reviewed gate.

## Resource scheduling and recovery

Permit only one memory-heavy local operation across both lanes: full backend suites, frontend production builds, browser fixtures, Tizonia compilation or packaging. Use `product-heavy` for each full suite, browser fixture or production build; exit 75 means wait for the shared lock. The coordinator records the holder, command category and UTC start/end times in the resource ledger. When Lane A starts, its coordinator and B1 share this ledger. Make acquisition exclusive; if no enforceable shared lock/controller exists, serialize heavy operations through the coordinator rather than relying on advisory messages alone.

Hosted CI is preferred for Tizonia builds. Local Tizonia compilation requires an enforceable memory limit and initially `-j1`, as specified by the soak plan. Agent count does not imply build concurrency.

After a harness or controller restart, reconcile issue/PR state, exact owner/Leader session bindings, pending approvals and workspace leases before resuming. Retain normal owner-bound workspace release and do not reset an occupied checkout. If B1 is unavailable, hold new dispatch/approvals until an authenticated coordinator resumes; do not promote another discovered pane automatically.

## Product startup checklist

- [ ] Operator records the product-only start scope; Lane A remains scheduled for later.
- [ ] Preserve the dirty packet and reconcile #4 against PR #399 and the product integration tip.
- [ ] Prepare the pinned product controller, dedicated state/ports/credentials, isolation boundary and rollback procedure.
- [ ] Create B1–B4 task/review worktrees and record each issue, base SHA, model and owner.
- [ ] Configure one product scope, integration base ref, finite budgets, initial human merge and verified routing.
- [ ] Verify distinct Leader/owner identity, authenticated Mail and exact session wakes using disposable fixtures.
- [ ] Capture B4's existing UI baseline and freeze initial P01/P02 fixture contracts.
- [ ] Prove one complete bounded dispatch/review/integration/normal-release cycle before increasing concurrency.
- [ ] Record the shared-file schedule, resource lock, dependency ledger and restart procedure.
- [ ] Obtain explicit operator enablement; enable automatic integration only after exact-head review enforcement is accepted.

Writing this document does not complete these checks. Current bindings and prerequisite evidence are recorded in the reconciliation ledger. Unverified checklist items remain open; intake needs the root operator arming instruction.

## Execution supervision and cybersecurity blocks

The user requested supervision of Lane B once autonomy is enabled, with reference to [Codex issue #43203](https://github.com/openai/codex/issues/43203). That issue reports a suspected false positive; it does not establish the cause or a general diagnosis.

A dedicated supervisor must watch Lane B controller state, exact bound panes and structured Codex error/assistant events. A suspected cybersecurity safety block pauses product autonomy immediately and writes a redacted incident with UTC time, slot/session, work item, PR/head SHA when known, notice classification and execution state. Preserve approvals, workspaces, leases and prior evidence. A stopped dispatcher does not necessarily stop an already executing owner; the roster instructions also require a hold before subsequent work.

After a hold, wait for the user's instructions. Do not automatically retry, rephrase the blocked task, switch models, replace the roster, cancel authority or force-release a workspace. The user may direct a reviewed change from Codex/GPT to Pi/OpenRouter; preserve the same authorized scope, isolation, dependency and review gates, and verify new session bindings before any resume. Resume requires a new explicit user instruction.

The supervisor uses recognisable notices and structured events; it cannot prove that every silent interruption was a cybersecurity block or that every reported block was a false positive. Controller health failures and unresolvable supervision evidence also hold new intake for review. Private logs stay local; public evidence excludes prompts, message bodies and credentials.
