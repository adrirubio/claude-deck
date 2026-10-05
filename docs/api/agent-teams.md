# Agent Teams API

Saved rosters for launching or reusing local Claude Code, Codex CLI, and GitHub Copilot CLI sessions.

## Presets

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

Use `confirm_plan_hash` after reviewing a plan. Local automation can pass `skip_plan_confirmation: true` when it intentionally wants a one-step launch; stale plans return `409` with the updated plan.

After launch, agents register through Agent Mail and receive team-slot role and charter context.
