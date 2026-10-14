# Agent Teams API

Saved rosters for launching or reusing local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions.

Response timestamps identify UTC with `Z` or `+00:00`. The JSON serializer leaves stored datetimes unchanged.
Send the returned timestamp unchanged in `expected_updated_at` or `expected_leased_at`.
Those two confirmation fields preserve the instant when they decode a UTC or non-UTC offset.
Naive confirmation values keep their existing UTC meaning. Stale instants still fail the existing comparison with 409.

## Authorization

"Operator token" means the `X-Deck-Operator-Token` header. "Mail session" means an authenticated `X-Deck-Session-Token`.

- A route marked **Operator token** accepts only the operator token. A session token never opens it. Without a configured backend operator token the route returns 503 `operator_token_unconfigured`; a missing or wrong header returns 401 `operator_token_required` or `operator_token_invalid`.
- A route that accepts both principals authenticates a non-empty session header first, also when both headers are sent. With no session header, or an empty one, it requires the operator token.
- A Mail session qualifies only when the backend enforces Agent Mail capability tokens (`mail_capability_tokens_required=true`), the session comes from MCP, and its mailbox is connected.

| Route | Access |
| --- | --- |
| GET `/api/v1/agent-teams/presets/{preset_id}/summary` | None |
| GET `/api/v1/agent-teams/presets`, GET `/api/v1/agent-teams/presets/{preset_id}`, GET `/api/v1/agent-teams/presets/{preset_id}/activity`, GET `/api/v1/agent-teams/presets/{preset_id}/github-scopes` | None |
| POST `/api/v1/agent-teams/presets`, `/api/v1/agent-teams/presets/from-agent-mail`, `/api/v1/agent-teams/presets/from-agent-bridge`, `/api/v1/agent-teams/presets/{preset_id}/duplicate` | Operator token |
| PATCH and DELETE `/api/v1/agent-teams/presets/{preset_id}` | Operator token |
| PUT `/api/v1/agent-teams/presets/{preset_id}/leader` | Operator token |
| POST `/api/v1/agent-teams/presets/{preset_id}/slots`, PATCH and DELETE `/api/v1/agent-teams/slots/{slot_id}`, POST `/api/v1/agent-teams/presets/{preset_id}/slots/reorder` | Operator token |
| POST `/api/v1/agent-teams/presets/{preset_id}/github-scopes` | Operator token |
| POST `/api/v1/agent-teams/presets/{preset_id}/plan-launch`, POST `/api/v1/agent-teams/presets/{preset_id}/launch` | Operator token, or a qualifying Mail session |
| POST `/api/v1/agent-teams/github-work-items/{work_item_id}/retry` | Operator token, or the qualifying Mail session of the team's current enabled Leader slot |

A Mail session that plans or launches cannot use prompt or path overrides, include disabled slots, force a respawn, adopt unbound sessions or skip plan confirmation. Those requests return 403 `operator_launch_override_required`. For plan and launch, a session that does not qualify returns 403 `authenticated_mcp_session_required`. For retry, a session that does not qualify or is not the current Leader returns 403 `current_leader_required`.

## Presets

### Shared agent status

The activity route returns `agent_status` for each slot.
Agent Mail members, Live sessions, and factory session associations use the same status service.

| Field | Values or meaning |
| --- | --- |
| `session_state` | `online`, `offline`, or `unknown` |
| `activity_state` | `working`, `idle`, `stopped`, or `unknown` from native evidence |
| `activity_reason` | Native observation reason |
| `wake_state` | `can_wake`, `cannot_wake`, or `unknown` |
| `wake_reason` | Existing delivery refusal code, or null when delivery has a wake target |
| `idle_since` | Native idle event time, or null when that time is unknown |
| `checked_at`, `valid_until` | UTC observation time and expiry; the validity interval is 15 seconds |

Online status and wake status are separate facts.
An old pane observation does not hide a live MCP session.
It can still prevent delivery under the existing wake rules.
For example, an agent can be online and idle, with `cannot_wake` and `wake_target_unbound`.

Calculate idle duration only from `idle_since`.
Do not use mailbox age as idle duration.
Show unknown after `valid_until` expires.
Unknown activity does not prove that work stopped.

The shared status does not grant approval, execution, recovery, lease renewal, or delivery authority.
Delivery checks its current target again.
Legacy native observation fields and wake fields keep their existing meanings.
Shared status reads send no input and change no heartbeat.
They do not save native session identity.
The existing Teams activity route retains its separate first-launch identity capture.

### List Presets

```http
GET /api/v1/agent-teams/presets
```

Returns saved team presets and their slots.

### Get Preset

```http
GET /api/v1/agent-teams/presets/{preset_id}
```

Returns one saved team preset with its slots.

### Create Preset

```http
POST /api/v1/agent-teams/presets
```

```json
{
  "name": "Release validation",
  "description": "Agents used to validate a release branch",
  "slots": [
    {
      "provider": "codex-cli",
      "repo_path": "/home/user/repo",
      "display_name": "Reviewer",
      "role": "planner-reviewer",
      "charter": "Review the plan and implementation against release goals.",
      "ui_color": "purple",
      "controlled_language_enabled": true,
      "enabled": true
    }
  ]
}
```

Slots also accept `"provider": "copilot-cli"` for GitHub Copilot CLI launch/reuse workflows. `ui_color` is optional and must be one of `blue`, `purple`, `green`, `amber`, `red`, `cyan`, or `slate`; send `null` on slot update to clear it.

### Create From Current State

```http
POST /api/v1/agent-teams/presets/from-agent-mail
POST /api/v1/agent-teams/presets/from-agent-bridge
```

`from-agent-mail` snapshots selected durable Agent Mail members. `from-agent-bridge` snapshots currently visible Agent Bridge tmux sessions and can keep multiple same-repo sessions as separate slots.

### Update, Duplicate, And Delete

```http
PATCH /api/v1/agent-teams/presets/{preset_id}
POST /api/v1/agent-teams/presets/{preset_id}/duplicate
DELETE /api/v1/agent-teams/presets/{preset_id}
```

### Set Leader

```http
PUT /api/v1/agent-teams/presets/{preset_id}/leader
```

```json
{
  "leader_slot_id": 2,
  "expected_leader_slot_id": 1,
  "expected_updated_at": "2026-10-01T12:00:00Z",
  "reason": "Assign the reviewed Leader slot."
}
```

Sets the team's explicit `leader_slot_id`. It needs the operator token. `expected_leader_slot_id` (nullable) and `expected_updated_at` must match the current team; `reason` has 1–500 characters. An absent team returns 404 `{"code": "team_not_found"}`. A stale expectation or a guard refusal returns 409 with its `code` and records a rejected audit event; the Leader stays unchanged. Slot order and Role text never select the Leader.

## Slots

```http
POST /api/v1/agent-teams/presets/{preset_id}/slots
PATCH /api/v1/agent-teams/slots/{slot_id}
DELETE /api/v1/agent-teams/slots/{slot_id}
POST /api/v1/agent-teams/presets/{preset_id}/slots/reorder
```

Slots store provider, repository path, display name, role, charter, UI color, bootstrap prompt, launch mode, provider options, and enabled state.

Slots also store `controlled_language_enabled`. The default is `true` for new and existing slots.
Send `false` on creation or slot update to disable ASD-STE100 guidance for that member. Omit the field on update to keep its value.
A copied roster preserves explicit `false` values. This option does not disable the requirement for human review summaries.

The member form exposes the same option. Launch prompts, Agent Mail identity and session-start context, and dispatch instructions use the saved value.
Agent Mail member responses expose `controlled_language_enabled` and `communication_instructions` for team slots. Other participants receive `null`.
The instructions guide agent output. They do not certify ASD-STE100 compliance or change approval and merge authority.

Multiple enabled slots can point at the same repository. Use this for same-repo roles such as planner/reviewer or implementer/reviewer. Each launched slot gets a distinct Agent Mail identity, so external tools should route follow-up Agent Mail requests to the slot member returned by Agent Mail discovery.

## Human Decisions in Backlog Assessments

The current authenticated Leader publishes assessments through `deck_report_backlog_assessment`.
For a human decision, use `required_actor: "operator"`.
This rule also applies to incomplete entries with `m1a_acceptance`, `m1b_acceptance`, or `pilot_decision` as the reason.
It also applies to an incomplete entry with an explicit `milestone_acceptance` or `pilot_decision` action.
The assessment route rejects a conflicting actor with HTTP 422 and `operator_gate_actor_required`.
It retains the previous assessment. The rejected report does not advance its revision or notification counters.

Before requesting human input, include the action and its current readiness:

```json
{
  "issue_number": 9,
  "disposition": "human_decision_blocked",
  "reason": "m1b_acceptance",
  "required_actor": "operator",
  "evidence_issue_numbers": [8, 9],
  "human_actions": [
    {
      "kind": "milestone_acceptance",
      "readiness": "requested",
      "prerequisite_issue_numbers": []
    }
  ]
}
```

Use `requested` when the human can act now. Use `waiting_for_prerequisites` when required evidence is absent.
The complete report must still cover every assigned issue. Use the fresh private token only in the authenticated tool exchange.

```http
GET /api/v1/agent-teams/presets/{preset_id}/human-actions
```

This observation also shows human gates from older assessments with a conflicting actor.
It marks their readiness as waiting and sets `coverage_complete` to `false`.
The Leader must correct the report. The observation does not approve work or satisfy a milestone.

## Current Operator Action Records

A current action needs instructions in the main issue body. A comment or Mail message alone is insufficient.
Each record states its status, responsible person, reason, exact action, evidence, completion condition, and UTC update time.
A PR record also states the actual target branch and full reviewed head.
The responsible role must be `operator`. Name any delegated maintainer after the role, such as `operator — Root`.

The Leader can prepare records before a first assessment:

```http
POST /api/v1/agent-teams/github-scopes/{scope_id}/operator-action-contexts/prepare
```

The body is `{ "entries": [...] }`. Use the assessment entry schema for the intended assigned issues.
The current authenticated Leader can prepare one to sixteen unique actions and at most eight PRs.
This route checks scope, role, current inspection state, and PR identity. It returns text templates and section markers.
It does not publish to GitHub or grant workflow authority. OFF and HOLD prevent this preparation.

Use `deck_prepare_operator_action_contexts(scope_id, entries)` for intended Leader requests.
Use `deck_get_operator_action_contexts(preset_id)` for automatic dispatch review and recovery requests.
The latter reads `human-actions?include_templates=true`. Ordinary UI reads omit templates to keep responses small.

### Parent issue and team summary

`parent_issue_url` is nullable. Create and update requests accept an HTTPS GitHub issue URL.
Omit the field to keep its value. Send `null` in a PATCH request to clear it.
The additive startup migration preserves existing teams and links.
The existing `description` supplies the outcome. Completion conditions stay in the parent issue.

`GET /api/v1/agent-teams/presets/{preset_id}/summary` returns one observation for the team card.
It returns the outcome, parent link, existing attention signals, human actions, remaining effort, and next actors.
The `description` field supplies the outcome text. No `outcome` or `done_when` field is added.
`supervisor` stays `none` until #549 supplies the supervisor contract.
`hold_code` uses the existing HOLD and recovery-only check.
Attention uses existing recovery actions, recorded owner escalations, and recorded observation pauses.
This read creates no monitor, dispatch action, approval, resume authority, or owner contact.
The existing progress service can refresh its derived observation cache.

The summary limits observations to eight seconds and 64 unfinished tracked items.
The existing human-actions read also limits coverage to 32 repository scopes.
It excludes `merged` and `completed` items from effort totals.
The total is known only when every included report is current and has validated numeric bounds.
Incomplete, stale, unknown, expired, or changed-context observations keep the whole estimate Unknown.
The total excludes waiting time. Its confidence is the lowest reported confidence.
An empty complete observation has zero remaining effort.
`next_actors` preserves all observed actors. `next_actor_coverage_complete` states whether coverage is complete.
Consumers must check `valid_until` and coverage. These observations grant no execution authority.

MCP tools: `deck_get_team_summary` reads the summary.
`deck_update_team_parent_issue` changes only the link. Its required nullable argument clears the link with `null`.
`deck_create_team` accepts `parent_issue_url`. Existing preset reads return the link.

### Work remaining reports

`GET /api/v1/agent-teams/github-work-items/{item_id}/progress` includes `remaining_work`.
Current validated reports expose `effort_low_minutes`, `effort_high_minutes`, and `confidence`.
Historical reports do not expose current numeric bounds.
The view contains three short fields: `remaining`, `estimate`, and `next_action`.
It includes report state, author, time, source SHA, and optional completed work and assumptions.
The ordinary progress read makes no GitHub writes and changes no dispatch authority.

The current Leader uses `deck_prepare_work_remaining_summary` to prepare a report.
The tool reads `/github-work-items/{item_id}/remaining-work-context` with its Agent Mail capability.
That route requires the current Leader for this item's scope. It checks the Leader again after asynchronous observations.
An unavailable published source returns `progress_context_unavailable`. It does not create a report for an unconfirmed checkpoint.

Tool inputs are `work_item_id`, `remaining`, and `next_action`.
For a time estimate, supply ordered `effort_low_minutes` and `effort_high_minutes`, `confidence`, and `effort_scope`.
Use `low`, `medium`, or `high` confidence. Omit both bounds for **Unknown**.
Optional `completed` and `assumptions` fields belong in report details.
Text fields are bounded plain text. Private values, markup, raw logs, and completion percentages are invalid.

Publish the exact returned block in the main issue through existing authorized GitHub access.
Copy it to the PR when requesting review. Replace only that block and keep other facts.
The read path accepts one marked, validated block from the exact expected GitHub issue endpoint.
It caches only the sanitized report, not the issue body.

The report must match item, dispatch, owner, scope revision, source SHA, and phase.
It becomes historical after a mismatch or two hours. A missing, invalid, or unavailable report has no current estimate.
The UI shows an explicit **Unknown** and retains the authoritative next action.
Reports remain advisory. They do not grant execution, recovery, approval, review, merge, or milestone authority.

### Publication sequence

1. Prepare the intended records. Keep the generated metadata, headings, and labels.
2. Fill every `WRITE_` placeholder. State the exact operator steps and the condition that clears each request.
3. Put one marked section within the first 4096 characters of the main issue body. Use the exact heading `Current operator actions`.
4. Use existing authorized GitHub access. Preserve other issue facts, human edits, and records that belong to other scopes.
5. Read the current issue again before updating it. Reconcile concurrent edits. Confirm the published section after the update.
6. Read fresh backlog coordination after publication. Pass its private token to the complete assessment.
7. Update the section when the actor, evidence, PR head, checkpoint, or requested action changes.
8. Set old records to `Cleared` or `Superseded`, or remove them, before reporting that their requests ended.

The returned markers enclose this shape. Fill the generated records; do not publish the example placeholders:

```markdown
<!-- deck:operator-actions:start -->
## Current operator actions

<!-- deck:operator-action:GENERATED_PUBLIC_ID:start -->
<!-- deck:operator-record scope=1 source=leader -->
### Record milestone acceptance

**Status:** Requested
**Responsible:** operator — Juan
**Reason:** The candidate has a recorded evidence packet. Its limits remain explicit.
**Action:** Review the linked packet. Record acceptance or the changes that you require on this issue.
**Done when:** The operator decision is recorded and the Leader updates the gate.
**Updated:** CURRENT_UTC_TIMESTAMP
**Evidence:** https://github.com/OWNER/REPO/issues/NUMBER

<!-- deck:operator-action:end -->
<!-- deck:operator-actions:end -->
```

Use `Waiting for prerequisites` for a future decision gate. Its record must describe the remaining evidence.
Records must remain visible Markdown prose. Do not put them in a code fence, HTML comment, or raw HTML container.
Deck rejects raw HTML tags before or inside the section. Put the section before existing HTML content.
Keep at most sixteen records in the section. Do not alter a generated public ID or use a private nonce as an ID.

### Validation and incomplete records

All declared human actions need a current matching record before the new assessment is accepted.
HTTP 422 `human_action_context_required` retains the previous assessment when instructions are absent, stale, or mismatched.
`human_action_context_not_cleared` means that the issue still requests a superseded action from this scope.
`human_action_actor_required` rejects a declared human action assigned to an agent.
`human_action_completed` rejects an action on a completed disposition.
`human_action_attempt_changed` means an inspection no longer matches the current stopped attempt or checkpoint.

Older assessments and automatic dispatch requests remain visible. Missing or stale instructions produce `state: "context_pending"`.
The UI shows **Action details pending** and names the Leader as the person who must prepare the details.
It keeps Autonomy inspection available. It does not label an unexplained request ready for the human.
This state makes `coverage_complete` false. It never clears a real gate or approves a recovery action.

The observation reports `context_request_id`, `instructions_url`, `instructions_state`, and instruction timestamps.
Records expire after 24 hours. Issue observations expire within 60 seconds. Failed reads retry after a short cache interval.
The observer bounds concurrent issue reads to 32 and PR reads to eight. It stores structural checks, not issue prose or private diagnostics.
Publication failures, read-only credentials, or rate limits leave details pending. No HTTP GET writes to GitHub or sends publication Mail.
Escalation broadcasts and team communication guidance give the Leader the explicit publication task.

The public ID uses only public request identity. Issue prose remains advisory and cannot grant API authority.
No token, lease, private nonce, prompt, raw private log, or private host path belongs in a record.
The parser checks structure and request identity. It does not certify the quality of an agent's explanation.

Existing MCP server processes must reload to expose the new preparation tools. This does not require changing the roster or model.

## Launch Planning

### Plan Launch

```http
POST /api/v1/agent-teams/presets/{preset_id}/plan-launch
```

```json
{
  "requested_by": "OpenClaw"
}
```

The plan checks provider availability, Agent Mail MCP/hooks readiness, reusable Agent Bridge sessions, disabled slots, launch-option validity, and unsafe launch combinations.

For Codex CLI slots, `resume` with `use_last: true` is blocked when multiple enabled slots target the same repository and would need to spawn. Use `plain` for fresh agents, or provide a distinct `session_id` per slot.

### Launch

```http
POST /api/v1/agent-teams/presets/{preset_id}/launch
```

```json
{
  "requested_by": "OpenClaw",
  "confirm_plan_hash": "returned-plan-hash"
}
```

Use `confirm_plan_hash` after reviewing a plan. Only the operator token can pass `skip_plan_confirmation: true` for an intentional one-step launch; a Mail session receives 403 `operator_launch_override_required`. Stale plans return `409` `plan_conflict` with the updated plan.

After launch, agents register through Agent Mail and receive team-slot role and charter context.

## Operator delivery policy and maintenance routes

These routes need the operator token. They are generic references; IDs in paths are placeholders. They grant no authority beyond each route's own checks and do not restart work, acknowledge Mail, reset budgets, merge or accept a milestone.

### Delivery policy

| Route | Behavior |
| --- | --- |
| PATCH `/api/v1/agent-teams/github-scopes/{scope_id}/delivery-policy` | Changes the scope's default delivery policy. The body has `expected_revision`, `policy` and `reason`. A changed revision returns 409 `delivery_policy_revision_changed`. New dispatch attempts record the new defaults. |
| PATCH `/api/v1/agent-teams/github-work-items/{item_id}/delivery-policy` | Applies the current scope policy to one existing attempt. The body has `expected_dispatch_nonce`, `expected_scope_revision`, `expected_policy_revision`, `target_policy_revision` and `reason`. A changed context returns 409 `attempt_delivery_policy_context_changed`. |
| GET `/api/v1/agent-teams/github-scopes/{scope_id}/delivery-policy/history` | Lists the latest 100 policy change events for the scope. The history is append-only. |

### Maintenance

| Route | Behavior |
| --- | --- |
| POST `/api/v1/agent-teams/presets/{preset_id}/work-items/{item_id}/accepted-source-imports` | Records one accepted-source import for the item. Inconclusive evidence returns 409 `source_import_evidence_inconclusive`; a changed context returns 409 `source_import_context_changed`; another refusal returns 409 with its reason. The original owner scope, baseline and budgets remain. |
| GET `/api/v1/agent-teams/presets/{preset_id}/work-items/{item_id}/accepted-source-imports` | Lists at most 64 recorded imports, with `truncated` when more exist. |
| GET `/api/v1/agent-teams/presets/{preset_id}/work-items/{item_id}/observation-pauses` | Lists the latest 20 recorded owner observation pauses. |
| POST `/api/v1/agent-teams/presets/{preset_id}/work-items/{item_id}/resume-observation` | Resumes one unchanged recorded pause. The body has `pause_id` and `reason`. It does not restart work, acknowledge Mail, retry or reset a budget. |
| POST `/api/v1/agent-teams/presets/{preset_id}/work-items/{item_id}/integration-outcome` | Records one idempotent integration outcome (`completed` or `needs_coordination`) for the expected dispatch nonce, scope revision and owner slot. `needs_coordination` escalates the item. A replay with different content returns 409 `maintenance_replay_conflict`; a changed context returns 409 `maintenance_context_changed`. |

Responses from the maintenance routes use `Cache-Control: no-store`. An item outside the named team returns 404.
