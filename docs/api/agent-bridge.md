# Agent Bridge API

Provider-aware live terminal monitoring for Claude Code and Codex CLI tmux sessions.

## Endpoints

### List Sessions

```http
GET /api/v1/agent-bridge/sessions?provider={provider_id}
```

`provider` is optional. Supported values are `claude-code` and `codex-cli`.

```json
{
  "sessions": [
    {
      "provider": "codex-cli",
      "provider_display_name": "Codex",
      "tmux_target": "repo-1234:0.0",
      "session_name": "repo-1234",
      "window_name": "main",
      "pane_id": "%1",
      "cwd": "/home/user/repo",
      "pid": "12345",
      "status": "active"
    }
  ],
  "count": 1
}
```

### Get Preview

```http
GET /api/v1/agent-bridge/sessions/{target}/preview
```

Returns a captured pane preview.

### Get Terminal Token

```http
GET /api/v1/agent-bridge/token
```

Returns a short-lived one-time token for WebSocket terminal access.

### Attach Terminal

```http
WS /api/v1/agent-bridge/sessions/{target}/terminal?token={token}&mode={mode}
```

`mode` can be `readonly` or `interactive`.

### Spawn Session

```http
POST /api/v1/agent-bridge/sessions
```

Claude Code example:

```json
{
  "provider": "claude-code",
  "directory": "/home/user/repo",
  "mode": "plain",
  "prompt": "Review the current branch"
}
```

Codex example:

```json
{
  "provider": "codex-cli",
  "directory": "/home/user/repo",
  "mode": "resume",
  "use_last": true,
  "model": "gpt-5.5",
  "approval_policy": "on-request"
}
```

Codex on Amazon Bedrock:

```json
{
  "provider": "codex-cli",
  "directory": "/home/user/repo",
  "mode": "plain",
  "platform": "bedrock",
  "aws_region": "us-east-2",
  "aws_profile": "bedrock-prod",
  "bedrock_model": "openai.gpt-5.5"
}
```

When `platform` is `bedrock` for Codex, Agent Bridge launches Codex with `model_provider = "amazon-bedrock"` as a per-session config override. `aws_region` and `aws_profile` are optional non-secret environment hints; AWS credentials must already be available to the spawned process through the environment or AWS SDK credential chain.

### Delete Session

```http
DELETE /api/v1/agent-bridge/sessions/{target}
```

Kills the tmux session or pane target.

## Legacy Route

`/api/v1/cc-bridge/*` remains for compatibility. New clients should use `/api/v1/agent-bridge/*`.
