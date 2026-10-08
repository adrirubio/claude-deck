# Agent Teams

Agent Teams are saved rosters of local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions. Use them when the same group of repositories should be launched or reused together, such as a project team, DevOps team, or release validation team.

## Teams inside the work flow

Teams retains saved rosters and manual launch planning alongside factory work. Overview/Work span teams; here configure a roster and its repositories. The preset's `leader_slot_id` supplies Leader authority. Slot order and descriptive Role text do not select the Leader.

## Current autonomy and repository setup

Autonomy configures watched repositories, existing primary checkout, labels, merge policy and finite dispatch/recovery limits. GitHub polling uses host access separately from operator authorization; GitHub App dispatch settings alone do not authenticate polling. Repository setup checks access and labels without creating records or labels. New teams start with automation off; new repository scopes start disabled. Explicit Leader changes require operator authority, a disabled team, and a quiescent team.

Team/scope enablement controls intake. Pausing retains configuration; inspect current attempts/processes separately. Code follows configured merge policy with the rolling automatic-merge cap; design-labelled work always requires human PR review. Leader plan approval, operator intervention and human PR review are separate.

Build directory, command and parallelism fields are hints in the owner's brief; Deck does not run those build commands. Editable numeric drafts validate on save; clearing a field does not silently increase a budget or authorize recovery.

### Continuation path scope

A continuation request must list its allowed paths explicitly. `README.md` permits changes to that exact file. `docs/` permits changes below that directory, including nested files. It does not permit changes below `docs-old/`. It does not permit replacement of the directory itself with a file.

Directory permission requires the trailing slash in the approved request. Existing entries such as `docs` keep their exact-file meaning. Use a new approved revision to change the scope. Globs, absolute paths, parent paths and the repository root are not valid scopes.

The path limit counts entries in the approved request. Each directory entry grants the stated subtree. Tree observations, commands, actions, ownership, workspace leases and failed-head budgets retain their own limits. Completion checks each changed file against the approved scope. An accepted-source import records only exact accepted files outside that scope. It does not grant edit permission.

## Authorization, reuse and deletion

Roster, watched-repository, autonomy and recovery settings/remedies require the configured operator token. Browser launch planning uses the existing per-tab flow. Protected reads and constrained agent launch APIs have separate authenticated Mail-session principal rules; credentials are separate from GitHub polling and are not a role/bootstrap prompt.

Normal reuse requires a live pane already bound to its intended slot. Unbound panes block the default plan; an operator must review target/PID and explicitly adopt or choose fresh spawn. An offline actor's link only selects launch context. Agent sessions cannot adopt, include disabled slots, override paths/prompts, force respawn or bypass plan confirmation.

Retry is confirmed and can discard attempt markers; a leased workspace can defer re-dispatch until normal owner release. A response is not proof of a new dispatch. Remedies depend on current state/principal and finite policy. Enabling recovery while autonomy is live requires explicit live-effect confirmation.

Deletion refuses enabled autonomy, nonterminal/unknown work, residual workspace authority, nonterminal approvals/revisions and affected or unavailable recovery protection. Inspect bounded safe blockers and resolve through normal controls; pausing, a stopped process or an empty-looking table does not establish safe deletion. After a valid deletion, the [audit ledger](/guide/factory-audit-and-metrics#filters) keeps its recorded facts under their context keys, with their historical attribution; live links to the deleted records become unavailable.

See [Work](/features/work), [Repositories](/features/repositories), [Live sessions](/features/agent-bridge) and [Agent Mail](/features/agent-mail).

## What A Team Contains

Each team has slots. A slot stores:

- provider
- repository path
- display name
- role and charter
- optional UI color for Agent Bridge cards and terminals
- optional bootstrap prompt
- controlled language, enabled by default for each member
- launch mode and provider options
- enabled or disabled state

Agent Teams do not create a second messaging system. Once agents are launched or reused, use Agent Mail for messages, context requests, and handoffs.

## Controlled Language

Each member uses ASD-STE100 guidance by default. Clear **Controlled language (ASD-STE100)** in the member form to select another writing style.
The option applies to one member. A copied roster keeps each member's choice. Existing slots use the enabled default after migration.

Deck includes the guidance in launch prompts, Agent Mail identity and session-start context, and new work instructions.
Custom bootstrap prompts and launch prompt overrides retain this guidance. A saved change does not rewrite an active conversation.
An active member receives the new choice with its next identity or session-start context, or its next work instructions.

The guidance applies to team messages, GitHub issue and PR text, comments, reports, and documentation.
It asks agents to use short sentences, active voice, simple verb forms, and consistent terms.
Agents must preserve code, commands, identifiers, quotations, safety conditions, decision gates, and evidence limits.

The [official ASD-STE100 standard](https://www.asd-ste100.org/about_STE.html) contains writing rules and a controlled dictionary.
Deck supplies agent instructions. It does not check the full dictionary or certify output compliance.

## Summary for Human Review

Before agents request human review or merge, they must add a brief **Human review summary**.
The section belongs near the start of both the PR body and its main issue body.
This rule also applies when a member selects another writing style.

The summary must state:

- **Goal:** The user outcome, in one or two sentences.
- **Changes:** The main changes, in a short list.
- **Checks:** The completed checks and material limits. Distinguish source review, automatic checks, and human trials.
- **Action:** The requested human action, PR link, target branch, and any separate decision gate.

Agents must preserve the original issue facts and PR metadata. They must update the summary when the head, results, or requested action changes.
They must link detailed evidence below the summary. A comment alone does not meet this instruction.
Deck supplies this rule in launch and Agent Mail context, work instructions, and review notifications.
These instructions do not prove summary quality or replace independent review and the configured merge policy.

## Work Remaining

The progress view shows three short lines:

- **Remaining:** The tasks and decisions that still need work.
- **Estimate:** A range of active effort, with confidence and scope, or **Unknown**.
- **Next:** The next actor and action.

The owner supplies the estimate. The Leader calls `deck_prepare_work_remaining_summary` after a safe published checkpoint or review handoff.
The Leader places the returned block near the start of the main issue and PR. Keep the other issue facts and action records.
The tool formats the block. It does not write to GitHub. Use existing authorized GitHub access.

An estimate excludes waiting for another actor. It is not a promised finish time.
Do not infer completion from commits, elapsed time, or passing tests. State the unit and scope of any count.
Put completed work and estimate assumptions in the optional detail fields. The UI keeps them in a closed disclosure.

The report names its author, update time, and source checkpoint. It expires after two hours.
A changed item, dispatch, owner, scope revision, published source, or phase makes it historical.
When Deck cannot confirm the source or find a current report, it shows **Unknown** and the current next action.
Refresh the block after changes or review corrections. A team report does not clear approval, review, CI, merge, or milestone gates.

## Reported Human Decisions

The **Human actions and decision gates** section appears above the Roster and Autonomy tabs.
It shows the human requests from the Leader's current assessment and dispatch state.

The Leader must assign human decisions to the operator. This includes milestone acceptance and pilot decisions.
Deck rejects a new assessment that assigns an incomplete human decision to the Leader or another actor.
The check covers the stated reason and explicit milestone or pilot actions.
The Leader must include the action and its readiness before requesting human input.
Use **requested** when the human can act now. Use **waiting for prerequisites** when required evidence is absent.

Deck also shows a human gate from an older report with a conflicting actor.
It marks that gate as waiting and warns that the assessment needs confirmation.
It does not present the gate as ready or treat its evidence as accepted.

These reports describe the requested action. They do not approve work or satisfy a milestone.

## Clear Instructions for Human Actions

Deck keeps the detailed instructions in the main GitHub issue. A comment history or team Mail exchange is insufficient.
The **Current operator actions** section belongs near the start of the issue body.
It states why the request exists, who must act, the exact steps, the evidence, and the condition that clears it.
It names delegated maintenance explicitly. A delegated repair must not look like an unexplained new decision for the operator.

The team Leader prepares and publishes these instructions through the team's existing authorized GitHub access.
This task covers automatic dispatch escalations and review requests as well as milestone and pilot decisions.
The Leader updates the record when the request changes and clears or supersedes it when the request ends.
Other issue facts and records from other scopes remain intact.

Deck checks the current record before showing an action as ready. A PR record identifies its target and reviewed head.
A new assessment with missing or stale instructions is refused. Older or automatic requests remain visible as **Action details pending**.
The Leader must prepare those details. Autonomy inspection remains available for urgent recovery.
Missing instructions do not clear a gate, hide the stopped attempt, or authorize a retry.

The panel shows a short action label, its readiness, and a **Read action instructions** link.
The link opens the current section in GitHub. Detailed steps stay in the issue.
Instruction records expire after 24 hours and need an update if the request remains current.
A failed GitHub read or publication cannot make an unexplained action ready.

These records do not approve work, release a workspace, change merge policy, or satisfy a milestone.
Deck checks the record's structure and identity. The Leader remains responsible for clear and accurate explanations.
See the [API publication contract](../api/agent-teams.md#current-operator-action-records) for the preparation tools and record format.

## Same-Repo Role Workflows

Use Agent Teams when multiple agents need distinct roles inside the same repository. A common setup is:

1. create one slot named `Planner` for the repository
2. create a second slot named `Reviewer` for the same repository
3. give each slot a role, charter, and optional bootstrap prompt
4. plan and launch the team from Agent Teams
5. use Agent Mail for context requests, replies, and handoffs between the slots

Launching through Agent Teams is important because each slot receives its own Agent Mail identity. Two manually started sessions in the same repository may be represented as one repo-level participant, which is not reliable for planner/reviewer routing.

Use `reuse existing` only when the existing sessions already belong to the intended team slots. For a clean planner/reviewer workflow, spawn fresh slots from the team.

## Creating Teams

You can create a team manually, import selected Agent Mail members, or snapshot currently visible Agent Bridge sessions.

`From Mail` uses Agent Mail participants and copies their current role and charter into slot-specific values. This is a snapshot; editing a team slot does not update existing mail history.

`From Bridge` uses live Agent Bridge tmux sessions. If multiple sessions are visible for the same repo, Claude Deck keeps each session as a separate slot so the resulting team can have distinct same-repo roles.

## Launch Planning

Before launch, Claude Deck computes a plan. The plan checks:

- provider availability
- Agent Mail MCP/hooks readiness
- live Agent Bridge tmux sessions that can be reused
- disabled slots
- provider launch option validity
- unsafe launch combinations, such as multiple same-repo Codex slots using `resume --last` or Copilot slots using `--continue`

By default, launch only includes enabled slots and only reuses wakeable sessions observed through Agent Bridge. Connected non-tmux Agent Mail sessions can still communicate, but they are not reliable team launch/reuse targets.

For same-repo Codex or Copilot teams, prefer fresh sessions (`plain`) or explicit `resume` session ids per slot. Do not use Codex `resume --last` or Copilot `--continue` for more than one slot in the same repo: each slot can resume the same conversation and lose the role-specific team boundary.

## Agent Activity and Your Actions

The roster and work-item owner show activity for the owner's current harness.
This is separate from the issue's delivery status:

| Label | Meaning | Appearance |
| --- | --- | --- |
| Working | A native turn started and has recent native progress. | Gentle halo pulse; text stays readable. |
| Idle | The native turn finished or was interrupted. The harness can still be running. | Steady. |
| Stopped | The bound process ended or was suspended. | Steady. |
| Activity unknown | The binding, provider, log access or fresh observation cannot confirm activity. | Steady. |

The pulse respects the system's reduced-motion preference. Activity is shared
across an owner's issues; it does not prove which specific issue is being worked
on. A dispatched issue, an enabled autonomy switch and a running harness do not
start the pulse.

Human review and merge gates show **Your review or merge is needed**, explain why
the team is waiting and link to the PR. The activity summary counts items needing
your action and can filter them. Leader approvals are labeled separately. For
operator recovery checkpoints or stranded initial approvals, the action remains
visible for the operator instead of being labeled as a Leader decision. Under
automatic merge policy, a review-ready item needs your action only when Deck has
explicitly fallen back to human merge. Passing checks do not prove independent
review acceptance. Check the current PR head and review evidence before merging.

### Observation limits

The initial adapter supports Codex CLI sessions with an explicit resume UUID and
an authenticated current process binding. Other providers and fresh sessions
without a pinned native identity show Activity unknown. The controller must be
able to read the process's open file descriptors and the corresponding native
rollout log. An exact-ID lookup in the Codex state database is used as a fallback
when the process has no open rollout descriptor and the database is readable.
Each Codex slot must have a distinct UUID across Deck presets. Reused UUIDs show
Activity unknown, including reuse in disabled slots, because the shared log cannot
distinguish which harness supplied an event.

The read-only `GET /api/v1/agent-teams/presets/{preset_id}/activity` endpoint
returns only slot, state, reason and timestamps. It does not expose transcript
content, credentials, native IDs or filesystem paths. It checks process start
identity, current process lifetime, session metadata and repository path, and reads a bounded log tail
outside the event loop. No activity is inferred from terminal text or Mail prose.

The UI polls the selected team every five seconds while the page is visible.
Responses expire after fifteen seconds; request failure, hidden pages and team
switches clear the pulse. A working native event older than three minutes becomes
unknown, including long work that produces no native progress events. A completed
turn can remain Idle while the same process and identity are still current.

### Deployment with separate controller and agent users

If the controller cannot read the runtime user's Codex history, labels remain
steady at Activity unknown. Before enabling observations, arrange read access to
the dedicated runtime's process descriptors and rollout logs, with directory
traversal access. The indexed fallback also needs access to the native state
database and SQLite WAL/SHM files. SQLite can require writable scratch files for
that fallback even with a read-only connection; the process descriptor lookup
avoids that requirement. New rollout files must inherit the same read access.
Grant read access only for that dedicated runtime; do not make home directories
or histories world-readable. This PR does not change live filesystem permissions.

For custom `CODEX_HOME` or `HOME`, the process environment must be readable by the
controller. When it is not readable, the adapter uses the process owner's default
Codex home and returns unknown if it cannot find and validate the exact session.

## External Local Agents

Local external agents can use the JSON API:

1. `GET /api/v1/agent-teams/presets`
2. `POST /api/v1/agent-teams/presets/{preset_id}/plan-launch`
3. inspect `items` and `plan_hash`
4. `POST /api/v1/agent-teams/presets/{preset_id}/launch`

Launch requires an operator credential or eligible authenticated Mail-session principal and a reviewed current `confirm_plan_hash`. A stale plan returns `409` with the updated plan. Explicit skip-plan-confirmation, adoption and launch overrides are operator-only; authenticated agent sessions cannot bypass confirmation.

After a launch, use the [External Agent Orchestration](./external-agent-orchestration.md) Agent Mail API to discover registered participants, send context requests, create handoffs, and poll for answers.
