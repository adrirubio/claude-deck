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
GET /api/v1/cc-bridge/token?target={target}&purpose=readonly
```

Returns a 30-second, single-use token for one exact tmux target and purpose. `purpose=interactive` requires `X-Deck-Operator-Token`; agent session tokens do not grant interactive access. Read-only tokens cannot be upgraded by a WebSocket query or mode frame. The modern Agent Bridge uses the same policy.

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

The legacy Claude Code endpoint uses the same spawn and kill service as Agent
Bridge. Resume with an empty `directory` requires a matching Claude transcript;
otherwise, provide the directory explicitly. Spawning and killing require the
operator token.

### Kill Session

```http
DELETE /api/v1/cc-bridge/sessions/{target}?cleanup_worktree={bool}
```

## WebSocket

### Attach to Terminal

```
WS /api/v1/cc-bridge/sessions/{target}/terminal?mode={mode}
```

Send the token as the single WebSocket subprotocol `deck-terminal.{token}`, not in the URL. Modes: `readonly` or `interactive`, matching the token's purpose and target exactly. Do not log WebSocket subprotocol headers.

Provides full PTY relay — terminal output streams to the client, and in interactive mode, keystrokes are sent to the session.
