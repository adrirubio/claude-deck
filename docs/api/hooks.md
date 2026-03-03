# Hooks API

Manage event-triggered hooks.

## Endpoints

### List Hooks

```http
GET /api/v1/hooks?project_path={path}
```

**Response:**

```json
{
  "hooks": [
    {
      "id": "abc123",
      "event": "PreToolUse",
      "matcher": "Bash",
      "type": "command",
      "command": "npm run lint",
      "scope": "user"
    }
  ]
}
```

### Get Hooks by Event

```http
GET /api/v1/hooks/{event}?project_path={path}
```

Valid events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `Stop`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PermissionRequest`, `Notification`, `SubagentStart`, `SubagentStop`, `PreCompact`

### Create Hook

```http
POST /api/v1/hooks?project_path={path}
```

**Request Body:**

```json
{
  "event": "PreToolUse",
  "matcher": "Bash",
  "type": "command",
  "command": "npm run lint",
  "scope": "user"
}
```

Hook types: `command`, `prompt`, `agent`

### Update Hook

```http
PUT /api/v1/hooks/{hook_id}?scope={scope}&project_path={path}
```

### Delete Hook

```http
DELETE /api/v1/hooks/{hook_id}?scope={scope}&project_path={path}
```
