# Agent Teams

Agent Teams are saved rosters of local Claude Code, Codex, and Copilot sessions. Use them when the same group of repositories should be launched or reused together, such as a project team, DevOps team, or release validation team.

## Teams inside the work flow

Teams retains saved rosters and manual launch planning alongside factory work. Overview/Work span teams; here configure a roster and its repositories. The first enabled slot supplies Leader authority; Role text is descriptive.

## Current autonomy and repository setup

Autonomy configures watched repositories, existing primary checkout, labels, merge policy and finite dispatch/recovery limits. GitHub polling uses host access separately from operator authorization; GitHub App dispatch settings alone do not authenticate polling. Existing host/label setup remains necessary; no guided wizard or explicit-role authority redesign is included.

Team/scope enablement controls intake. Pausing retains configuration; inspect current attempts/processes separately. Code follows configured merge policy with the rolling automatic-merge cap; design-labelled work always requires human PR review. Leader plan approval, operator intervention and human PR review are separate.

Build directory, command and parallelism fields are hints in the owner's brief; Deck does not run those build commands. Editable numeric drafts validate on save; clearing a field does not silently increase a budget or authorize recovery.

## Authorization, reuse and deletion

Roster, watched-repository, autonomy and recovery settings/remedies require the configured operator token. Browser launch planning uses the existing per-tab flow. Protected reads and constrained agent launch APIs have separate authenticated Mail-session principal rules; credentials are separate from GitHub polling and are not a role/bootstrap prompt.

Normal reuse requires a live pane already bound to its intended slot. Unbound panes block the default plan; an operator must review target/PID and explicitly adopt or choose fresh spawn. An offline actor's link only selects launch context. Agent sessions cannot adopt, include disabled slots, override paths/prompts, force respawn or bypass plan confirmation.

Retry is confirmed and can discard attempt markers; a leased workspace can defer re-dispatch until normal owner release. A response is not proof of a new dispatch. Remedies depend on current state/principal and finite policy. Enabling recovery while autonomy is live requires explicit live-effect confirmation.

Deletion refuses enabled autonomy, nonterminal/unknown work, residual workspace authority, nonterminal approvals/revisions and affected or unavailable recovery protection. Inspect bounded safe blockers and resolve through normal controls; pausing, a stopped process or an empty-looking table does not establish safe deletion. Quiescent deletion is not a promise of retained delivery audit history.

See [Work](/features/work), [Repositories](/features/repositories), [Live sessions](/features/agent-bridge) and [Agent Mail](/features/agent-mail).

## What A Team Contains

Each team has slots. A slot stores:

- provider
- repository path
- display name
- role and charter
- optional UI color for Agent Bridge cards and terminals
- optional bootstrap prompt
- launch mode and provider options
- enabled or disabled state

Agent Teams do not create a second messaging system. Once agents are launched or reused, use Agent Mail for messages, context requests, and handoffs.

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
