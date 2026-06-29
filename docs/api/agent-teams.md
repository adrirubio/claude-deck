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

Multiple enabled slots can point at the same repository. Use this for same-repo roles such as planner/reviewer or implementer/reviewer. Each launched slot gets a distinct Agent Mail identity, so external tools should route follow-up Agent Mail requests to the slot member returned by Agent Mail discovery.

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
