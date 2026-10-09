# Supervised factory playbook

Use this playbook when an operator delegates a GitHub backlog to a supervising agent and a Deck team. It covers preparation, autonomous delivery, independent review, maintenance, recovery and completion.

This process comes from the product reposition work and the Deck v3 release. It describes the operating practice for Deck 3.0.0. Check the installed version before using a command. Team names, issue numbers, model choices and machine paths are campaign settings.

Reading this playbook or loading its companion skill grants no execution authority. The operator's instructions and the campaign's recorded permissions govern the work.

## Quick sequence

1. Agree on the outcome, backlog, limits and delegated actions.
2. Prepare a team, repository scopes, isolated workspaces and an installation record.
3. Create the supervisor's goal when requested. Complete startup checks before enabling autonomy.
4. Let the Leader coordinate delivery. The supervisor checks execution and resolves authorized factory defects.
5. Use independent review on the source that will merge. Use process reviews at useful decision points.
6. For maintenance, obtain a safe handoff, deploy the accepted fix, check the retained state, then resume.
7. Complete the publication or acceptance gates. Record the result and disable completed dispatch.

## Roles and authority

| Role | Responsibility | Authority |
|---|---|---|
| Operator | Select the outcome, budget, roster constraints and publication gates | Grant or change delegation; make retained human decisions |
| Supervisor | Prepare the factory, own the outer goal, monitor execution and handle maintenance | Use operator powers only within recorded delegation |
| Team Leader | Assess the backlog, approve eligible plans, coordinate owners and publish current summaries | Use the team's authenticated Leader authority |
| Implementer | Complete one assigned attempt in its leased workspace; push checkpoints and request review | Use the current approved plan, paths, commands and budgets |
| Independent verifier | Review the implementation and check its contracts | Report acceptance or findings for an exact source; no operator powers |
| External reviewer | Review a difficult fix or the delivery process from outside the implementing team | Advise or supply review evidence; no implicit plan, merge or recovery authority |

The supervisor and Leader are separate roles. The supervisor can manage several campaigns. Each team has its own Leader, selected through `leader_slot_id`. A role name or pane title does not establish that authority.

The supervisor records when it acts under delegation. It must not describe an agent check as a human trial. Independent review, hosted CI, integration merge and human acceptance are separate facts.

### What supplies each part

| Part | Supplied by |
|---|---|
| Saved roster, authenticated Mail, dispatch, workspace leases and bounded recovery | Deck |
| Repository labels, issues, PRs, checks and branch protection | GitHub and the project |
| Outer goal and continued supervisor turns | The supervising harness, when it supports a goal tool |
| Checks while the operator is absent | A running supervisor harness and a configured durable watcher or timer |
| Model access and native CLI execution | The installed harness and saved private configuration |
| Machine paths, service units, backups and maintenance evidence | The installation record and operator tooling |

A goal tool records the objective and status. It does not, by itself, schedule a wake-up or keep a process alive. Confirm the actual continuation mechanism before promising unattended checks.

## 1. Record the campaign

Keep a short campaign record. Use the parent GitHub issue for public scope and current status. Keep the machine record and sensitive runtime details in protected local storage.

Agree on these fields before dispatch:

- Outcome and concrete completion conditions.
- Parent issue, repository backlogs, dependencies and excluded work.
- Integration branch, dispatch labels and ownership routing for each repository.
- Roster roles, chosen harnesses and models, concurrency and resource limits.
- Startup authorization, review policy, merge policy and maintenance delegation.
- Human decisions, publication gates and stop conditions.
- Check plan, active effort limit, monitoring interval and restart procedure.

Use explicit delegation. This example is a starting point, not a default permission grant:

| Action | Example agreement |
|---|---|
| Prepare workspaces, roster and startup evidence | Supervisor may proceed |
| Enable autonomy after successful preflight | Already authorized by the campaign brief |
| Approve implementation plans | Team Leader, through Deck |
| Merge accepted implementation PRs into integration | Supervisor or configured automatic policy |
| Repair a factory bug and deploy a reviewed fix | Supervisor, with recorded maintenance evidence |
| Change models, credentials, authority or budgets | Operator decision unless specifically delegated |
| Accept a pilot or milestone | Named human decision; keep its evidence gate |
| Promote to master, publish a release or deploy production | Explicit publication decision, if retained by the operator |

Honor authorization already given. Do the authorized preparation before asking for a retained decision. A publication request must refer to a concrete reviewed result.

An abbreviated campaign record can use this shape:

```yaml
campaign: example-delivery
parent_issue: OWNER/REPO#NUMBER
completion: "Accepted outcome, required publication and final records"
team_preset: RECORD_AFTER_CREATION
leader_slot: RECORD_AFTER_CREATION
repositories:
  - repository: OWNER/REPO
    integration_branch: feature/example-delivery
    dispatch_label: campaign-example-ready
    design_label: campaign-example-design
    backlog: [ISSUE_NUMBERS]
permissions:
  startup_after_preflight: authorized
  integration_merge: delegated_after_review_and_checks
  maintenance: delegated_reviewed_bug_fixes
  roster_changes: operator_decision
  publication: explicit_operator_approval
monitoring_minutes: 10
effort_stop_rule: AGREED_LIMIT_AND_REQUIRED_DECISION
private_installation_record: LOCAL_REFERENCE_ONLY
```

This is a planning record. It is not a Deck API payload. Record each additional repository separately.

## 2. Prepare the backlog and branches

Review existing issues before creating new ones. Give each implementation issue a bounded outcome, acceptance conditions, dependencies and an owner route. Put unresolved product decisions in separate decision records.

Create an integration branch for a large campaign. Implementation PRs target that branch. A later promotion PR targets the project's main branch. Record both names; projects need not call the main branch `master`.

Begin with human or delegated supervisor merges. Enable automatic integration only after the current-head checks and independent review have an enforceable gate. A review comment or label alone does not establish enforcement. Design-labelled work retains Deck's human-review pipeline.

For several repositories, configure one watched scope per repository in the same team. Each scope has its own checkout, base branch, labels, checks and delivery policy. The team shares slot capacity. Cross-repository dependencies still need explicit evidence and Leader assessment.

The Leader keeps the eligible queue current. A PR awaiting human merge does not automatically block unrelated work. Continue another item only when its dependencies, gates, owner capacity and workspace are ready. Do not route a dependent item around an unmet milestone.

Separate campaigns use separate presets, Leaders, queues and task directories. They can share a controller. A shared controller upgrade requires coordination with all its active owners.

## 3. Choose and provision the roster

A useful starting roster has one Leader, two implementers and one independent verifier. That is four native team sessions, plus the supervisor's separate harness session. Use fewer implementers when the backlog has little independent work. Open temporary external review sessions when their work is needed.

Choose models for the task's reasoning demands. Check access with the installed harness. Use a small representative task to establish whether an implementer can follow the contracts. If repeated integration mistakes consume more review effort than implementation effort, reconsider the assignment with the operator.

The product work used several harness and model combinations. The v3 team used Claude Code Sonnet implementers and a Leader, with an Opus verifier. Earlier maintenance reviews used GPT-6 Astra. Claude Opus 5.5 supplied process retrospectives. These are examples of role assignments, not availability or performance guarantees.

For every slot, record its role, charter, harness, model, repository context and writing style. Keep controlled language enabled unless the operator selects another style. Deck supplies ASD-STE100 guidance; it does not certify compliance. Preserve code, identifiers, commands and evidence limits.

### Workspace layout

Use one writable checkout and task branch per active writer. A worktree or a separate clone is suitable. Use separate review checkouts for exact PR heads. Keep the controller source outside implementation workspaces.

```text
controller/                 Pinned running Deck source
campaign/
  leader/                   Coordination context
  repo-one-primary/         Watched repository context
  repo-one-dispatch-1/      Leased implementation workspace
  repo-two-primary/         Second repository context
  repo-two-dispatch-1/      Second leased workspace
  review-PR-SHA/            Independent source review
  maintenance-candidate/    Isolated factory fix
private-state/              Installation record, receipts and backups
```

These names are examples. Save the real paths. Check read and write access under the actual native session OS user. Separate directories alone do not isolate credentials or the operator token from same-user processes.

Schedule shared-file edits. Set host limits for heavy suites, builds and browser workloads. Agent count is not build concurrency. Use an enforceable shared lock where required; lightweight checks can remain parallel.

## 4. Complete machine and startup checks

Follow [Installation](./installation.md), [Autonomous dispatch](../autonomy.md) and [Agent Teams](../features/agent-teams.md). On a new machine, establish a new installation record. Do not copy old pane IDs, process identities or session bindings.

Before enabling intake:

- Confirm the controller version, API health, UI and actual database path. Back up existing state.
- Record the API address, runtime environment, controller checkout, service units, state directory and supervisor identity.
- Confirm GitHub polling access, dispatch authentication, configured labels and CI read permissions.
- Prepare watched scopes and dispatch workspaces. Keep them disabled during setup.
- Save the intended Leader and roster. Confirm the selected native CLI and model access.
- Launch or reuse sessions through Deck. Reuse only sessions with valid intended slot bindings.
- Check each member's authenticated Mail identity and one successful tool call. Complete first-use workspace confirmation.
- Check the conversation, native process lifetime, tmux pane, working directory and workspace ownership.
- Configure supervision for the actual preset, slots and supported native event formats. Confirm that it survives the supervisor's interactive turn.
- Record activation readiness for every scope. Keep other campaigns in their intended state.

Do not treat a configured model card, live pane or HTTP 200 response as proof of the complete startup path. A simple authenticated Mail canary helps establish that the native member can use the controller.

The checked-in `scripts/product-factory/` supervisor is a historical campaign example. It contains fixed team identities and installation assumptions. It is not a generic team installer. Prepare and review the watcher for the new installation; copying its timer unchanged is insufficient.

Where a native observer is unavailable, select and document a compatible progress-report policy. Do not claim all harnesses provide the same observation coverage.

After the checks pass, activate only the authorized team and scopes. Start at a bounded concurrency. Confirm the first dispatch, plan approval, owner acknowledgement, review, merge and normal workspace release before increasing it.

## 5. Use the supervisor's goal

Create a goal only when the operator requests one. Use the goal tool provided by the outer harness. Store the complete prompt in a file that the operator can read and reuse.

If the chosen harness has no goal tool, say so. Use a durable campaign record and the configured continuation mechanism. Record objective, status, budget, blockers and completion there. Do not report that a tool-managed goal exists. The operator's delegation still governs execution.

The goal must name the outcome, backlog, saved team, permissions, monitoring, publication gates and completion conditions. Include paths by reference to the installation record. Keep private configuration out of public goal records.

Keep the goal active while implementation, verified runtime waits or authorized maintenance can progress. A factory pause does not itself pause the goal: the supervisor can continue the repair. Use the harness's `paused` status only for an explicit operator request to pause the goal.

Use `blocked` when required input or an external change prevents meaningful progress and the tool's blocking threshold is met. Follow the installed tool's rules. For the Codex goal tool used in this campaign, the same blocker must persist for three consecutive goal turns. A resumed blocked goal starts a fresh audit.

A tool budget limit is a stopping limit. It is not evidence that the objective is complete. Do not create replacement goals or reset budgets to evade it.

The periodic supervisor loop should:

1. Read the goal and campaign record.
2. Check controller and watcher health, team enablement and the actual database identity.
3. Check issue, PR, CI, owner, Mail, lease and current assessment state.
4. Check holds, native session evidence and the last meaningful published progress.
5. Resolve an authorized routine blocker, or record the required actor and decision.
6. Publish a short checkpoint when the state changes. Schedule the next real check.

About ten minutes is a useful ordinary interval. Check more often during startup, cutover and recovery. A local watcher can inspect holds and session failures more often. Record its last successful tick. If the monitoring process ends, state that supervision stopped.

The goal is complete only when its stated outcome and records are complete. A ready PR or preview is an intermediate state.

## 6. Deliver with visible checkpoints and bounded review

The Leader uses authenticated Agent Mail for plans, approvals, handoffs, blocked work and decisions. GitHub holds durable work and review evidence. Do not require routine heartbeat messages when current supported native evidence supplies owner contact.

Push a useful checkpoint after a coherent substep and before a handoff or long wait. Open draft PRs early. Mark an incomplete checkpoint as work in progress; it is not a request for final acceptance. Avoid empty commits or placeholder reviews to satisfy a timer.

Keep one current summary near the start of the main issue and PR. Use one responsible publisher. Refresh the marked summary sections and preserve requirements, other scopes' records and historical evidence. Do not append competing current-status paragraphs.

Use three simple lines for remaining work:

```text
Remaining: Connect the final caller and check the completed change.
Estimate: 1–2 active hours, medium confidence. CI waiting is separate.
Next: Implementer pushes the complete candidate; verifier reviews it.
```

Use `Unknown` when there is no credible estimate. Do not infer completion from commit counts or elapsed time. The Leader can use `deck_prepare_work_remaining_summary` after a safe published checkpoint.

### Check plan

Agree on the checks in the issue plan. Use focused checks during implementation and one combined broad check after integration. Prefer required hosted CI for the final broad suite when the repository has the configured exact-head gate.

For shared services or behavior involving several callers, map the real entry points before implementation. Include actors, transaction boundaries, result producers and public consumers. Check at least one complete path through the real caller. A direct database insert does not prove that the producer works.

For a regression, demonstrate a relevant assertion failure on the affected source and a pass on the candidate. An import error or missing fixture is not proof of the defect. Record justified inspection evidence when a before/after test is unsuitable.

Bind receipts to the commit, tree, command, dependencies and environment. Store raw receipts outside the worktree. Publish only safe summaries. Reuse evidence for unchanged source and dependencies; assess changed contracts independently.

Final hosted gates must still cover the actual PR head and current workflow execution. Old successful runs do not override a new pending or failed required run. Do not rerun the same broad suite at every handoff solely to manufacture another receipt.

Complete one bounded correction batch before final review. Keep one finding register with stable IDs, requirements, locations, decisive checks and state. Repair in-scope findings under valid existing authority. Use a new approved scope when the existing continuation no longer authorizes the change.

The effective delivery policy belongs to each repository and attempt. New scope defaults do not silently update an active attempt. See the [Factory API](../api/factory.md) and the [delivery practices source](https://github.com/adrirubio/claude-deck/blob/master/docs/deploy/factory-delivery-practices.md).

## 7. Use external reviewers where they add evidence

Use the team's independent verifier for ordinary completed candidates. Add external source review for a material cross-cutting or operational change, such as lease authority, recovery, CI selection, controller cutover or rollback. Do not add a second full review to every ordinary PR.

An Astra reviewer or a Claude Opus 5.5 reviewer can perform either source review or process analysis. Name the assigned role and scope. The prior campaigns used Astra for demanding maintenance reviews and Opus for delivery retrospectives. The process depends on independent evidence, not a particular model name.

### Source review handoff

Supply the reviewer with:

- Issue, acceptance conditions, base and full candidate SHA.
- Changed contracts, relevant callers and the bounded review question.
- Focused results, hosted checks, receipt links and known limits.
- For maintenance, the runtime file map, target commit, cutover and rollback procedure.

The reviewer returns `ACCEPT` or `CHANGES_REQUIRED`, the reviewed SHA and concrete findings. The supervisor or Leader reconciles findings into one register. A changed head requires review of the changed source and its effects. Carry forward unaffected evidence with its original source binding.

For a backport, compare the patch, target context and resulting file contents. Record the distinct target SHA. An identical patch can reuse reasoning; target differences still need review and required CI.

Fix blocking correctness findings before acceptance. Record minor follow-ups separately when they do not invalidate the agreed outcome. Do not expand the acceptance conditions at every review handoff.

### Process retrospective

Use a retrospective after a milestone, a difficult issue, an effort limit or repeated stalls. Give the reviewer pushed source, the finding register, check receipts and an event timeline. Include active work, external waiting and factory downtime separately. Exclude private credentials and raw sensitive transcripts.

Useful measures include time to a complete published candidate, review rounds, blocking findings, repeated broad runs and factory pauses. State their scope and evidence coverage. The audit ledger does not supply missing historical events, human benefit measurements or known total cost.

Ask for the largest causes of lost time, evidence for each cause, and a few prioritized changes. Distinguish model limitations, factory defects and process costs. When several factors changed together, do not attribute all improvement to one model.

The supervisor converts accepted recommendations into generic fixes or configurable team policy. Implement the highest-impact corrections at a safe handoff. Track deferred work explicitly. Send a short actions-taken record back to the reviewer, including what changed, what did not, source/PR links and remaining limits.

A review does not grant retry, budget, roster, merge or deployment authority. The supervisor applies recommendations within the operator's delegation.

## 8. Detect and classify stalls

Read evidence before taking a remedy. Native liveness, activity, progress and authorization are different facts.

| Observation | Response |
|---|---|
| Required CI is pending or cannot be read | Check the actual execution and credential read access; keep the item unverified |
| Current bound native work is active | Let the supported observer supply contact; avoid interrupting reasoning with routine Mail |
| Native observation is unknown, but the exact bound owner is live | Inspect the recorded observation pause and recovery window; use the supported remedy if eligible |
| Owner, approval, ACK or workspace identity is stale | Hold the affected action; reconcile through the authorized workflow |
| Integration PR awaits a human | Publish exact instructions; let independent eligible work continue |
| A factory bug prevents progress | Record a maintenance issue; preserve the attempt and use the repair procedure below |
| Credits or access are exhausted | Hold affected work; after the operator resolves access, check actual readiness and notify the existing roster |
| A real provider safety block or security HOLD exists | Stop affected autonomy and safely hold active execution; wait for operator instructions |
| A CLI warning appears | Check its structured result and effect; do not classify the display text alone as a security block |

A suspected false positive is still an incident until classified. Preserve the notice and exact session context in protected evidence. Do not automatically retry, rephrase the task, clear a genuine HOLD or switch models to bypass it.

State the cause, affected item, source head, required actor and action that removes the block. Keep those instructions in the main issue body and the current Deck operator-action record. Put delegated maintenance under `operator — supervisor` when appropriate. The operator must be able to tell whether their input is actually needed.

Use `deck_prepare_operator_action_contexts` and the Leader's current assessment for requested actions. When the request is completed, clear or supersede it and refresh the assessment. A comment alone is insufficient. See [Current operator action records](../api/agent-teams.md#current-operator-action-records).

## 9. Stop safely for factory maintenance

### Prepare the repair and handoff

1. Create or reconcile the defect issue. Separate the factory defect from the delivery issue it blocked.
2. Preserve pushed work. Record dirty or unpushed work and ask the owner to publish a safe checkpoint where possible.
3. Prepare the fix in an isolated checkout. For Deck maintenance, target upstream `master`; backport accepted fixes to affected integration branches and an operator fork when used.
4. Obtain independent source and runtime review. Check the exact target and backport heads. Reuse valid check evidence.
5. Prepare a machine-specific maintenance profile and request. Bind the old and target versions, accepted PRs, reviewed files and proof receipts.
6. Obtain a current maintenance checkpoint from each affected active owner. The owner confirms that no source operation is in flight and holds work until the outcome.

Turning off team autonomy or a watched scope stops intake. It does not stop an already executing owner. Prove the safe handoff before changing the controller or an owner's source.

A shared controller upgrade can affect all teams on its database. Coordinate every active owner. Wait for in-progress verification to finish, or resolve it through a supported handoff. Preserve unrelated teams' original enablement settings.

### Use the reusable operation

The maintenance CLI uses explicit installation and request files. Run it with the installation's Python environment and authorized OS identity:

```sh
python scripts/factory-maintenance.py upgrade \
  --profile /private/installation.json \
  --request /private/upgrade.json

python scripts/factory-maintenance.py upgrade \
  --profile /private/installation.json \
  --request /private/upgrade.json --checkpoint-template

python scripts/factory-maintenance.py upgrade \
  --profile /private/installation.json \
  --request /private/upgrade.json --execute
```

The first command validates only the data shape. It is not an operational dry run. The second reads current checkpoint fields; it does not send the owner's checkpoint. Put actual authenticated Mail message IDs in the final execution request.

The profile records controller and database paths, the operator environment file, loopback API, service, active supervisor, state directory, HOLD paths, arming marker, OS users, protected files and declared version records. Files must be regular, protected files owned by the executing operator or root, with mode `0600`.

Use the exact schemas from [maintenance operations](https://github.com/adrirubio/claude-deck/blob/master/backend/app/services/maintenance_operations.py) and the [maintenance runbook](https://github.com/adrirubio/claude-deck/blob/master/docs/deploy/factory-maintenance-operations.md). The current helper uses Unix user/process checks and systemd service control. A profile does not add support for a different service manager.

The operation checks accepted source, review, CI, owner checkpoints and retained authority. It pauses autonomy, removes the arming marker, obtains a consistent database backup, proves controller termination, changes the reviewed source, starts the controller and checks retained state.

Successful source deployment returns `deployed_paused`. It does not resume the factory. The helper does not install dependencies or publish a frontend bundle. Handle those changes as explicit accepted artifacts, with their own backup and source checks, while execution remains held.

Do not replace the reusable operation with a new unreviewed deployment script for each fix. Do not edit live SQL, reset counters, forge owner ACKs, force-release leases or change session metadata to make a refused handoff pass. Inspect the exact refusal and use the supported remedy.

If deployment fails, read the operation record and cleanup results. Do not assume a timeout means termination. Keep the factory paused or stopped until the deployed version and process state are known. A controller rollback restores the matching code, UI and consistent database backup. Remove stale WAL/SHM files before starting the restored database; later records are absent from an older backup.

### Import accepted integration changes without a global pause

An accepted base update is different from a controller upgrade. When the attempt policy permits `accepted_base_update: fast_forward` or `merge`, use the scoped integration operation:

```sh
python scripts/factory-maintenance.py integration-update \
  --profile /private/installation.json \
  --request /private/integration-update.json --execute
```

This operation needs the accepted integration PR, exact tip, required checks and owner checkpoint. It retains supervision and does not disarm team autonomy. It preserves original approval, ACK, lease and counters. Accepted files outside a continuation scope are recorded as imports; they do not become editable paths.

On conflict, preserve commits and conflict files. Coordinate the outcome instead of resetting or force-pushing. A continuation directory permission needs a trailing slash, such as `docs/`; `docs` permits only that exact path.

### Check and resume

Before releasing maintenance holds:

- Confirm the deployed commit and UI/artifact source. Check API and actual UI operation.
- Confirm the same database, configuration, roster, policies, attempts, owner sources and workspace leases.
- Confirm native session generation, process lifetime and authenticated Mail after the restart.
- Confirm that the active supervisor watches the correct preset and installation. Keep genuine HOLD files intact.
- Reconcile GitHub, required CI, approvals, imports and paused attempts. Read each operation's recorded result.
- Confirm activation readiness for the intended scopes. Release only the holds belonging to this completed operation.

Restore only the previously authorized team and scope enablement. Do not activate another campaign. Notify the Leader and owners of the installed fix and their next supported action. Observe the first resumed dispatch or continuation before returning to the ordinary monitoring interval.

Agree on a bounded observation period for the fix. Watch the behavior that failed, native contact, dispatch transitions, CI and normal workspace release. Record the installed version and incidents. A healthy API alone does not prove the defect is fixed. State when the relevant behavior did not occur during observation. Give the external reviewer that evidence if the fix's acceptance requires runtime follow-up.

## 10. Publish and finish

When a retained human decision is ready, present the actual reviewed UI or artifact. For a factory release, show the controller and UI on the intended existing database. Name a test database clearly when one is used.

Put a brief human summary at the top of the main issue and promotion PR. State the outcome, changes, checks, limits, rollback and exact requested action. Separate approval of an integration merge from approval of production publication.

If the campaign retains publication approval, wait for it. Automatic goal continuation is not that approval. Once approved, pin the exact reviewed heads and complete the authorized publication sequence.

For Deck releases, follow [Documentation publishing](https://github.com/adrirubio/claude-deck/blob/master/DOCUMENTATION_PUBLISHING.md). Record the tag/commit, artifact checksums, documentation source, website commit, workflow run and live result. A website master merge can deploy production; check that trigger before merging.

After the outcome is verified:

1. Record final sources, checks, evidence limits and rollback in the parent issue.
2. Close completed issues and reconcile the Leader's assessments and operator actions.
3. Confirm no active implementations, pending authority or leased work remains.
4. Disable completed team dispatch and repository intake. Disarm its dedicated watcher as appropriate. Leave unrelated teams unchanged.
5. State which services, previews and native sessions remain running. Stop sessions through supported controls when requested or planned.
6. Mark the goal complete. Report the goal tool's final usage when its rules require it.

The Deck v3 publication record is an example: [release issue #490](https://github.com/adrirubio/claude-deck/issues/490). The records establish that campaign's result. They do not establish performance or cost gains for other teams.

## Templates

### Goal prompt

Replace all bracketed fields. Keep the complete prompt in a readable file. Supply actual permissions; do not treat this example as approval.

```text
Create and start a goal to deliver [outcome].
Read the supervised factory playbook in [Deck checkout].
Read campaign [parent issue or record] and private installation record [local reference].

Complete only when [acceptance, publication and required records] are done.
Repositories and backlogs: [repositories, issues, integration branches, dependencies].
Excluded work: [exclusions].
Team: [prepare a new preset, or use the saved preset and explicit Leader].
Roster constraints: [roles, permitted harnesses/models, concurrency, resource limits].
Preserve saved private configuration. Keep it out of team messages and GitHub artifacts.

Prepare and check services, database, dispatch workspaces, native sessions and Mail.
Configure durable supervision for this team and installation.
[I authorize startup after these checks pass / retain a stated startup decision].
Keep other campaigns in their recorded state.

Delegation: [issue/PR creation, integration merges, reviewed maintenance and deployment].
Retained decisions: [roster changes, budget changes, milestones, production publication].
Check about every [interval] minutes; check more often during startup and recovery.
Use published checkpoints, short remaining-work estimates and current human instructions.
Use [check plan], the independent verifier and focused external reviews when needed.
Effort stop rule: [limit, evidence and decision required].

For maintenance, preserve owner work and authority. Use the reviewed operations.
After cutover, check retained state and readiness before releasing holds or resuming.
For a genuine security HOLD, stop affected autonomy and wait for my instructions.
Do not change models or clear that HOLD unilaterally.

Before [retained publication actions], show [live factory, previews and evidence].
Wait for my explicit approval. Then complete publication and live checks.
At completion, reconcile records, disable completed dispatch, report running services
and mark the goal complete. Do not mark it complete at the preview stage.
```

### External review request

```text
Review [issue/PR] at full SHA [candidate]. Base: [SHA].
Role: [source verifier / runtime reviewer / process reviewer].
Question and scope: [bounded question].
Requirements: [links]. Evidence: [checks, receipts, finding register, timeline].
Limits: [unperformed checks and uncertain observations].
Return [ACCEPT or CHANGES_REQUIRED with source-bound findings / prioritized process advice].
Keep private configuration out of the report. This request grants no execution authority.
```

### Human action summary

```text
Goal: [user outcome in one or two sentences].
Changes: [short list].
Checks and limits: [completed evidence and material gaps].
Action: [exact decision or merge, link, target and reviewed SHA].
Reason: [why this person must act].
Done when: [observable condition that clears the request].
```

### Supervisor handoff

```text
Outcome and goal status: [current objective and tool status].
Authority: [delegated actions, retained decisions and any HOLD].
Runtime: [installation record, controller/UI source, actual database, supervisor tick].
Team: [preset, Leader, slots, session evidence and enabled scopes].
Work: [issues, PR heads, pushed checkpoints, approvals, leases and findings].
Next: [actor, action, blocker and next scheduled check].
Private evidence references: [protected paths; no secret values].
```

## Use the companion skill

The repository contains `skills/deck-factory-supervisor/SKILL.md`. Give that directory to the supervising harness through its supported skill loader. Keep the Deck source checkout available: the skill reads this playbook from that checkout rather than keeping another copy.

For Claude Code, the current Deck skill documentation lists `.claude/skills/` and `~/.claude/skills/`. For Codex, the skill authoring convention uses `~/.codex/skills/`. Other harnesses can use their own loader or an explicit instruction to read the skill file. Installation and invocation differ; confirm the installed harness's behavior. Deck's native Skills page is not a universal installer for every harness.

An explicit request can use this form:

```text
Use the deck-factory-supervisor skill at [path]/SKILL.md.
The Deck source checkout is [path]. The campaign brief is [reference].
Prepare or resume the team within the permissions in that brief.
```

The skill belongs to the supervisor. The team's members continue to use their own role prompts, authenticated Mail and approved task context. Loading the skill does not start a goal, enable a team or grant maintenance or publication permission.

Keep machine records outside the skill. If the same skill is used on another computer, repeat discovery and startup checks. Update this playbook for demonstrated process changes. Keep the skill as a short entry point.
