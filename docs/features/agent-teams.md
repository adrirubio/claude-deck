# Agent Teams

Agent Teams are saved rosters of local Claude Code, Codex, and Copilot sessions. Use them when the same group of repositories should be launched or reused together, such as a project team, DevOps team, or release validation team.

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

Launch accepts a reviewed `confirm_plan_hash`, or `skip_plan_confirmation: true` for explicit single-step local automation. If a plan hash is stale, the API returns `409` with the updated plan.

After a launch, use the [External Agent Orchestration](./external-agent-orchestration.md) Agent Mail API to discover registered participants, send context requests, create handoffs, and poll for answers.
