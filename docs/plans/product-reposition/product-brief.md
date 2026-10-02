# Claude Deck software delivery product brief

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Claude Deck will make delivery work the primary product experience. An operator should be able to connect a GitHub backlog, run a team of coding agents, see progress and review requests, and recover bounded attempts. Harness configuration remains accessible as the infrastructure that enables this work.

The initial promise is observation and intervention around bounded agent attempts on an existing GitHub backlog. Delivery is the objective; reliability and independent human review require evidence from actual outcomes. The first implementation reuses the autonomous dispatch system already present on the audited integration snapshot.

## Timing and implementation base

The repositioning is follow-on work after the autonomy feature has been merged into `master`. Start implementation packages P01–P06 only after that merge, including fixture-based UI development and implementation validation.

Use the updated `master` as the implementation base and PR target. The autonomy feature branch remains the analysis reference. The coordinator records the actual merge evidence and reconciles this packet with the merged code before assigning implementation work.

## Product direction

The direction established in the user discussion is:

- Promote factory workflows in the product story, navigation, and homepage.
- Make native harness configuration secondary in the daily operating experience.
- Support mixed harnesses through a common operating contract.
- Preserve useful manual session and team workflows.

Keep the product name **Claude Deck** during this implementation. A shorter name such as Deck is an option to evaluate after the workflow change; no rename, domain change, package rename, or repository rename is part of this packet.

Proposed descriptive copy:

> A self-hosted workspace to observe and intervene in bounded coding-agent attempts on GitHub issues, with visible policies and recovery controls.

Keep public copy at this scope until observed outcomes support stronger delivery and review claims.

## Initial audience assumption

The working audience is a technical operator running a local factory with multiple coding harnesses, existing repositories, native toolchains, tmux sessions, and existing model credentials. This assumption follows the discussion but was not separately confirmed by the user.

The first release should work for this audience without adding hosted infrastructure, organization accounts, billing, fleet management, or a new model subscription. Broader engineering-team requirements can inform a later product decision.

Treat M1a as a pilot for existing factory operators. It improves daily observation while repository configuration still uses the existing flow. Hold the pilot checkpoint before M1b's full harness catalog. M2 introduces guided configuration, with explicit host prerequisites that remain outside the wizard.

Record pilot participants and their relationship to implementation. Maintainer or implementer runs establish internal usability observations, not independent audience validation. Seek at least two operators who did not implement the system before making broader usability claims, and record recruitment or availability gaps. This small formative cohort cannot establish market demand by itself; repeat use, concrete workflow needs, and observed adoption are separate evidence. Repository stars, forks, and contributor counts establish neither demand nor its absence.

The checkpoint may justify continued investment for the user's own factory and its accountability needs. Absence of external participants does not automatically block useful configuration or audit work. It limits claims and requires an explicit scope decision, instead of silently treating an internal pilot as external validation.

## Jobs the product should support

| Situation | Desired outcome |
| --- | --- |
| Returning after agents have been running | Understand what progressed, what finished, and what needs intervention |
| Starting work in a repository | Establish access, a runnable team, routing, and explicit policies |
| Following an issue | See the owner, approver, stage, PR, checks, waiting reason, and workspace together |
| Resolving a stopped attempt | Understand the stop reason and use the valid existing remedy |
| Choosing a harness | Understand operational readiness and the native features Deck actually supports |
| Running one agent manually | Launch or inspect a session without first configuring automatic dispatch |

GitHub remains the source of issues and PRs. Deck presents execution and intervention around that backlog. It does not introduce a second editable issue tracker in the first release.

## Evidence behind the direction

At the reference commit, the backend already stores teams, slots, watched repository scopes, work items, approvals, attempt revisions, and leased workspaces. The scheduler polls, routes, monitors, verifies, and reconciles work. The operator guide documents code and design pipelines, human and automatic merge policies, and finite recovery budgets.

The current presentation emphasizes configuration inventory and requires an operator to open a selected team's Autonomy tab to see delivery activity. The global provider selector also gives a single-harness context to a product whose teams can contain several harnesses. These observations come from the source register in the [packet index](README.md).

The existing Codex integration includes real configuration, profile, diagnostic, inventory, and launch support. Other harnesses have narrower surfaces. The problem combines uneven native settings coverage with a product shell that still reflects Claude-specific assumptions.

## Product requirements

| Requirement | Required behavior | Owning package |
| --- | --- | --- |
| R01 | The default homepage explains delivery progress, intervention, and effective automation mode across the current Deck instance | P01, P02 |
| R02 | Factory views include all harnesses by default and use explicit local filters | P01, P02 |
| R03 | Native configuration remains accessible under Harnesses through explicit provider/page/API adapters and read/write guards; integration capability flags alone do not grant page access | P02, P03 |
| R04 | Operational support is described separately from configuration coverage and runtime readiness | P03 |
| R05 | New UI entry points preserve server authority, actor separation, finite budgets, and operator authentication | All |
| R06 | Work views retain source identities, raw statuses, accurate eligibility, and explicit unknown states; automatic refresh preserves browsing beyond the first page | P01, P02 |
| R07 | Leader assignment becomes explicit through a migration that preserves existing authority | P04 |
| R08 | Guided repository configuration checks access and labels, explains remaining host steps and overlapping scopes, and preserves existing teams while saving new scopes disabled | P04 |
| R09 | Audit history survives operational-record deletion; delivery metrics retain historical attribution and distinguish evidenced delivery, non-delivery, and unknown outcomes | P05 |
| R10 | Existing routes, API clients, native settings, and saved teams remain usable | P01, P02, P03, P04 |
| R11 | A single manually operated agent remains a supported starting workflow | P02, P03 |
| R12 | Each milestone has isolated functional, cross-harness, accessibility, and documentation validation; M1a and M2 also have recorded operator-task comparisons with participant provenance | P06 |
| R13 | Team deletion cannot remove in-use work, approvals, revisions, or leases; authentication and state safety are separate requirements | Release/coordinator prerequisite, P06 |

## Meaning of complete harness support

The operating contract covers launch, distinct team identity, work delivery, communication, approval participation, progress reporting, workspace association, and supported continuation or resume behavior. Each capability has a stated support level and conditions.

Native settings remain provider specific. A harness can participate effectively in delivery without having every Claude Code configuration surface. Equally, installing a CLI or editing its settings does not prove that its running session can receive work or act with the intended authority.

The UI must distinguish a configured launch environment, checked credentials, and a connected session. Unsupported or unobserved capabilities must remain visible as such.

## Delivery milestones

| Milestone | Product result | Included work |
| --- | --- | --- |
| M0 | Autonomy completes its existing release process and merges into `master` | Accountable release coordination, combined-tip review/tests, UI acceptance, recorded merge evidence |
| M1a | Existing factory operators can observe delivery across teams and retain access to native configuration | Delivery reads, Overview, Work, repositories, details, navigation, a thin Harnesses index, native adapter guards |
| Pilot checkpoint | Evidence determines whether and why to continue the remaining programme | Baseline comparison, participant provenance, observed needs, defects, and claim limits |
| M1b | Operators can inspect each harness's operational support and readiness coherently | P03 operations contract, bounded readiness, full Harnesses cards and native surface catalog |
| M2 | An operator can configure a repository team with understandable authority, prerequisites, and policies | Guided configuration, access/label checks, explicit Leader assignment, migration and compatibility |
| M3 | An operator can inspect durable policy changes and measured delivery outcomes | Audit records, forward lifecycle events, metrics with coverage |

M1a must be useful before the full harness catalog exists. M1b adds provider detail; M2 changes configuration and authority; M3 expands accountability. The pilot checkpoint can narrow or defer later scope, while preserving authority safeguards and necessary audit work.

## Scope boundaries

The first programme preserves the existing GitHub issue dispatch engine, local execution model, Agent Mail identities, approval state machines, and workspace leases.

Deferred product options include freeform goal decomposition, new backlog providers, autonomous prioritization, cross-machine fleets, automatic provider replacement, universal configuration editors, a new terminal-abandon workflow, dispatch arbitration across scopes, and a brand rename. A conversational setup assistant can follow the deterministic setup flow if observed usage justifies it. Measure operator-token friction in the pilot; a cookie/session login needs a separate authentication design and is not a default M2 dependency.

Build hints remain instructions for the owner agent. Deck does not become a build runner through this UI work. Usage and cost visibility continue to depend on the stable data exposed for each harness.

## Success measures

P06 owns the baseline and pilot evidence. After G00 and before the interface change, record representative operator tasks against the existing experience. The coordinator names the measurement owner and participating operators, identifies implementers versus independent operators, and records the task scripts, environments, and comparison criteria before collecting the after-results. Re-run the same tasks after M1a and M2:

- Time and navigation needed to identify why an issue is waiting and the next valid action.
- Time to configure a new repository and obtain a first reviewable PR.
- Operator interventions per delivered issue, separated by reason.
- Completion and recovery outcomes, separated by code and design work.
- Harness-specific launch, binding, and work-delivery failures.
- Credential prompts, blocked actions, and navigation needed to launch an offline owner or Leader.

Use these measures as pilot evidence. This packet sets no numerical performance target without a baseline.

Record task completion and correctness as well as time, navigation, interventions, errors, and limitations. Report per-run evidence and sample size; missing observations do not count as a pass. P06 cases V31 and V32 own these comparisons and the coordinator records their release disposition. A first-reviewable-PR time requires an actual observed pilot; fixture setup completion measures navigation and configuration only. Live or paid runs retain their existing separate authorization and runbook requirements.

For M1a, current status counts are valid metrics. `Finished` means terminal tracking, and a closed issue marked `completed` does not prove successful delivery or human review. The existing abandon endpoint escalates work and can leave it eligible for manual or issue-update retry; it does not establish a terminal disposition. Daily throughput and duration claims require reliable lifecycle evidence and outcome classification. Historic `updated_at` values alone cannot establish delivery or merge times. M3 defines measured event coverage, unknown outcomes, and retained historical attribution.

## Product claims and release limits

The recorded soak-evidence gate passed with documented exceptions and operator interventions. The record explicitly reserves integration-to-master clearance. Autonomy must complete its release requirements and merge into `master` before reposition implementation starts. Position the product around bounded autonomy, visible review, and recoverable execution.

The repositioning should make the operator's responsibility easier to understand: agent plan approval, operator remedies, and human PR review are distinct acts. Display them with the actor that actually performed them.
