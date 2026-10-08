# Claude Deck product repositioning implementation packet

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Claude Deck will lead with operating a software delivery factory. Harness configuration will support that workflow through native settings and explicit operational readiness. This packet gives implementation agents the product direction, target experience, proposed contracts, work boundaries, and acceptance criteria.

**Execution decision, 2026-10-02:** Start product repositioning first on `juanrubio/claude-deck`. Follow the [agent deployment and autonomous coordination plan](agent-deployment-plan.md) for session ownership, isolated worktrees, dependency scheduling and operational gates. Product PRs target `feature/software-delivery-product-reposition`; the plan supersedes older master-target and pending-G00 wording below. Tizonia soak work starts later through its own decision and retains an independent pinned runtime.

- **Date:** 2026-09-30
- **Last revised:** 2026-10-01, following the independent whole-approach review and source reconciliation
- **Status:** Implementation preparation. G00 is satisfied by PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`; implementation follows the product factory startup gates. The new routes, schemas and migrations remain planned work.
- **Reference branch:** `origin/feature/autonomous-github-dispatch`
- **Audited integration snapshot:** `301e37c1e53e822a47a9572dc592e866df77f763`
- **Observed master snapshot:** `96954a6a07d3b376ea9cd32341ce18dd6f6f9328`; the autonomy merge gate was still open at this check.
- **Implementation target:** `feature/software-delivery-product-reposition` on `juanrubio/claude-deck`.

These internal planning documents live under `docs/plans/` and are excluded from the public documentation build by the top-level VitePress `srcExclude` rules.

## Implementation start gate

G00 is complete: upstream PR #399 merged 2026-10-01T19:20:30Z as `ac9252242fcf436c3ea9997add5d32416cad2cd1`. The fork integration branch starts at that release. M0's prior pending disposition is historical evidence, not a new product gate.

Before assigning implementation, B1 reconciles this packet with that baseline and obtains B4 independent acceptance of the exact bootstrap PR head. Branch from the current fork `feature/software-delivery-product-reposition` tip and target PRs there. Record the product integration base SHA. P06 baseline acceptance precedes P02 UI edits. Scope/dispatch arming requires the root operator's separate instruction; packet acceptance alone does not arm intake.

See the [reconciliation ledger](reconciliation-ledger.md) for source preservation, current authority/client signatures, dependencies, contract freeze requirements and evidence still missing.

## Reading order

| Document | Purpose |
| --- | --- |
| [Product brief](product-brief.md) | Positioning, audience assumption, scope, requirements, and success measures |
| [Experience specification](experience-spec.md) | Navigation, work views, configuration access, operator actions, and compatibility |
| [Architecture and contracts](architecture-contracts.md) | Data ownership, planned API contracts, readiness, authority, and audit boundaries |
| [Implementation plan](implementation-plan.md) | Milestones, dependencies, file ownership, PR sequence, and integration procedure |
| [Agent deployment plan](agent-deployment-plan.md) | Product-first rollout, sessions/models, autonomous coordination, isolation, review and resource gates |

The product brief owns the product requirements. The experience specification owns visible behavior. The architecture document owns the proposed contracts. If an implementation needs to change a contract, update that document and its consumers together.

## Implementation handoffs

| Handoff | Work package | First deliverable |
| --- | --- | --- |
| [Delivery backend](handoffs/delivery-backend.md) | P01 | Aggregate delivery reads and shared projections |
| [Delivery interface](handoffs/delivery-interface.md) | P02, M1a | Overview, Work, repository views, navigation, and a thin Harnesses index |
| [Harness operations](handoffs/harness-operations.md) | P03, M1b | Operational capabilities, readiness, and the full Harnesses catalog |
| [Repository onboarding and roles](handoffs/onboarding-and-roles.md) | P04, M2 | Guided configuration, access/label checks, and explicit Leader assignment |
| [Audit and metrics](handoffs/audit-and-metrics.md) | P05 | Durable policy history and measured delivery outcomes |
| [Validation and release documentation](handoffs/validation-and-release.md) | P06 | Cross-package acceptance evidence and accurate user documentation |

Each handoff includes its prerequisites, source files, proposed files, implementation steps, required checks, and completion evidence. These are handoff documents; this documentation change does not launch implementation agents or alter running teams.

## Start here

Follow **M0 → M1a → pilot checkpoint → M1b → M2 → M3**. After G00, assign P01, P02, and P06 for M1a. P06 records the existing-interface task baseline before the interface change. P02 can build against the documented fixtures while P01 implements the reads. Its thin Harnesses index and checked-in native adapters do not depend on P03's new operations API.

Review the delivery pilot before starting P03 in M1b. Record whether to continue, narrow, or defer the remaining scope. P04 follows accepted M1b; P05 follows the authority changes. Internal operator benefit can justify this work, including audit needs, without claiming external demand. Broader usability and adoption claims need independent evidence.

Before creating an implementation branch, inspect the current fork product integration tip and compare it with the reference commit. Reconcile changes to operator guards, approval attribution, cancellation, and workspace release. The merged autonomy implementation takes precedence over assumptions in this snapshot.

After G00, delivery reads can proceed independently of remaining mutation prerequisites. Use the [audited authorization matrix](architecture-contracts.md#operator-authorization-prerequisite): most policy mutations are already operator protected, retry and launch retain constrained agent access, and team creation/import/duplication still need an explicit M2 authorization change. A team-deletion state guard is required before M1a acceptance.

## Review follow-up

The requirements below are carried into contracts, handoffs, and [acceptance evidence](handoffs/validation-and-release.md). M1a is an existing-operator pilot; P06 owns the before/after task measurements and distinguishes implementer observations from independent operator evidence.

| Review gap | Contract or procedure | Owner and acceptance |
| --- | --- | --- |
| Capability flags do not establish native page support | [Native page availability](architecture-contracts.md#native-page-availability) | P02/P03, V11 |
| Enabled toggles do not establish normal intake | [Effective automation state](architecture-contracts.md#effective-automation-state) | P01/P02, V26 |
| Polling can reset older-page browsing | [Refresh while browsing](architecture-contracts.md#refresh-while-browsing) | P01/P02, V27 |
| Reusing an active team can affect other repositories | [Saving new and reused configuration](architecture-contracts.md#saving-new-and-reused-configuration) | P04, V28 |
| Terminal status does not prove delivery or human review | [Delivery outcomes and evidence](architecture-contracts.md#delivery-outcomes-and-evidence) | P05, V29 |
| Deletion or renaming can erase or relabel history | [Historical retention and attribution](architecture-contracts.md#historical-retention-and-attribution) | P05, V30 |
| Functional checks do not measure operator benefit | [Operator pilot measurements](handoffs/validation-and-release.md#operator-pilot-measurements) | P06, V31/V32 |
| The autonomy release needs accountable coordination | [M0 autonomy release](implementation-plan.md#m0-autonomy-release) | Proposed release owner and coordinator; actual merge evidence |
| Full harness metadata delays the delivery pilot | [M1a delivery workspace](implementation-plan.md#m1a-delivery-workspace) and [M1b harness operations](implementation-plan.md#m1b-harness-operations) | P02 before checkpoint; P03 after checkpoint |
| Operator authentication does not make active-team deletion safe | [Team deletion prerequisite](architecture-contracts.md#team-deletion-prerequisite) | Release/coordinator prerequisite, V33 |
| The existing abandon action is an escalation, not terminal disposal | [Status mapping](architecture-contracts.md#status-mapping) | P01/P02, V34; P05, V29 |
| Setup leaves access, labels, and host prerequisites unclear | [Setup preflight](architecture-contracts.md#setup-preflight) | P04, V35 |
| Overlapping scopes can independently dispatch one issue | [Overlapping repository scopes](architecture-contracts.md#overlapping-repository-scopes) | P01/P02/P04, V36 |
| Authority migration needs tied-position and rollback evidence | [Explicit Leader assignment](architecture-contracts.md#explicit-leader-assignment) | P04, V17/V37 |

The revision does not add an ORM timestamp listener, a slot-position uniqueness constraint, cookie login, cross-scope dispatch arbitration, or a new terminal abandon state. No current timestamp defect or production Leader mismatch was established. The relevant contracts now require regression evidence; larger changes need a demonstrated problem and a separate decision.

## Source register

The original packet used `07df206905e0b86e06d5fe9bcda8d93e409d1055`; that statement described the original documentation worktree, not this fork checkout. Current bootstrap code is pinned to `ac9252242fcf436c3ea9997add5d32416cad2cd1`. The independent review used integration `a9b563a`. This revision checks the fixed integration snapshot `301e37c1e53e822a47a9572dc592e866df77f763`, including later authorization/client fixes. None of those snapshots substitutes for the recorded merged autonomy baseline and current fork integration tip.

Source links below locate files in the checkout. To inspect the audited version, use `git show 301e37c1e53e822a47a9572dc592e866df77f763:<path>` with the repository-relative path. Planned behavior is identified explicitly in the other documents.

| Source | What it establishes |
| --- | --- |
| [Autonomy operator guide](../../autonomy.md) | Issue intake, worktrees, merge policy, recovery, polling, and build hints |
| [Current navigation](../../../frontend/src/components/layout/Sidebar.tsx) | Global provider selection and provider-specific navigation |
| [Current dashboard](../../../frontend/src/features/dashboard/DashboardPage.tsx) | Configuration-oriented homepage and Claude-specific rendering |
| [Team interface](../../../frontend/src/features/agent-teams/AgentTeamsPage.tsx) | Roster, team selection, launch planning, and nested Autonomy |
| [Autonomy interface](../../../frontend/src/features/agent-teams/AutonomyPanel.tsx) | Activity, explanations, recovery history, and operator remedies |
| [Factory records](../../../backend/app/models/database.py) | Team, slot, repository scope, work-item, approval, revision, and workspace identities |
| [Team API](../../../backend/app/api/v1/agent_teams.py) | Current projections, policy routes, recovery reads, and mutations |
| [Provider capability matrix](../../../backend/app/services/providers/capabilities.py) | Existing native configuration and launch capability classifications |
| [Native configuration page](../../../frontend/src/features/config/ConfigViewerPage.tsx) | Existing Claude/Codex API branching; positive capability metadata does not supply other native editors |
| [Dispatch scheduler](../../../backend/app/services/github_dispatch_scheduler.py) | Recovery-only mode, scheduled repository jobs, and normal-intake gating |
| [Issue watcher](../../../backend/app/services/github_watcher_service.py) | Issue closure can terminate tracking as `completed` without delivery evidence |
| [Launch readiness](../../../backend/app/services/agent_team_service.py) | Provider-specific Agent Mail readiness and team launch planning |
| [Operator credential helper](../../../frontend/src/features/agent-teams/operatorAuth.ts) | Existing per-tab browser credential handling |
| [Codex support guide](../../guide/multi-provider-codex-v2.md) | Existing Codex functionality and explicit coverage limits |
| [Conversational setup proposal](../../superpowers/specs/2026-07-04-conversational-team-and-autonomy-setup-design.md) | Earlier setup design, explicitly unimplemented at its publication |
| [Soak evidence record](../../deploy/attempt-recovery-soak-log-2026-09-29.md) | Observed recovery outcomes, interventions, exceptions, and remaining release gates |

## Completion evidence

An implementation handoff is complete when its acceptance criteria pass, its changes are reviewable against the product integration base, and the agent reports the autonomy merge evidence, base SHA, changed paths, checks, limitations, and next dependency. Report fixture validation and live observations separately. A documentation packet, green fixture tests, or the recorded soak-evidence pass does not establish that a future live replay has passed.
