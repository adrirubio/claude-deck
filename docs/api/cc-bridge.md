# CC Bridge API

::: warning Legacy route
Use `/api/v1/agent-bridge/*` for new provider-aware clients. `/api/v1/cc-bridge/*` remains for compatibility with Claude Code-only integrations.
:::

Monitor and manage live Claude Code terminal sessions.

## REST Endpoints

### List Sessions

```http
GET /api/v1/cc-bridge/sessions
```

Returns discovered Claude Code tmux sessions.

### Get Preview

```http
GET /api/v1/cc-bridge/sessions/{target}/preview
```

Returns a text snapshot of the terminal pane.

### Generate WebSocket Token

```http
GET /api/v1/cc-bridge/token
```

Returns a one-time token for WebSocket authentication.

### Spawn Session

```http
POST /api/v1/cc-bridge/sessions
```

```json
{
  "directory": "/path/to/project",
  "mode": "plain",
  "worktree_name": "feature-x",
  "skip_permissions": false
}
```

Modes: `plain`, `worktree`, `resume`

### Kill Session

```http
DELETE /api/v1/cc-bridge/sessions/{target}?cleanup_worktree={bool}
```

## WebSocket

### Attach to Terminal

```
WS /api/v1/cc-bridge/sessions/{target}/terminal?token={token}&mode={mode}
```

Modes: `readonly` or `interactive`

Provides full PTY relay — terminal output streams to the client, and in interactive mode, keystrokes are sent to the session.
