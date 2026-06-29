# Agent Bridge API

Provider-aware live terminal monitoring for Claude Code, Codex CLI, and GitHub Copilot CLI tmux sessions.

## Endpoints

### List Sessions

```http
GET /api/v1/agent-bridge/sessions?provider={provider_id}
```

`provider` is optional. Supported values are `claude-code`, `codex-cli`, and `copilot-cli`.

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
      "status": "active",
      "team_preset_id": 10,
      "team_preset_name": "Release validation",
      "team_slot_id": 20,
      "team_slot_name": "Reviewer",
      "team_slot_role": "planner-reviewer",
      "team_slot_charter": "Review the plan and implementation against release goals.",
      "team_slot_color": "purple"
    }
  ],
  "count": 1
}
```

Team fields are present only for sessions launched from Agent Teams. Manual tmux sessions fall back to provider, repo, and tmux metadata with no team slot color.

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

### Image Attachments

Use image attachments to upload a screenshot or mockup to the Claude Deck host, then paste a file-path prompt into a live tmux session.

All attachment endpoints require a fresh token from `GET /api/v1/agent-bridge/token` in the `X-Claude-Deck-Terminal-Token` header.

```http
POST /api/v1/agent-bridge/sessions/{target}/attachments
Content-Type: multipart/form-data
X-Claude-Deck-Terminal-Token: {token}
```

Multipart fields:

- `file`: PNG, JPEG, WebP, or GIF image
- `prompt`: optional prompt template containing `{path}`
- `created_by`: optional source label

```json
{
  "id": 123,
  "target": "repo-1234:0.0",
  "provider": "codex-cli",
  "mime_type": "image/png",
  "size_bytes": 482103,
  "agent_path": "/home/user/.claude-registry/bridge-attachments/repo-1234/2026-06-29/185422-a1b2c3d4.png",
  "prompt_text": "Please inspect this image: /home/user/.claude-registry/bridge-attachments/repo-1234/2026-06-29/185422-a1b2c3d4.png"
}
```

```http
POST /api/v1/agent-bridge/sessions/{target}/attachments/{attachment_id}/paste
X-Claude-Deck-Terminal-Token: {token}
```

```json
{
  "submit": false
}
```

`submit: true` sends Enter after a short delay. Generated prompt text strips newlines so `submit: false` cannot submit accidentally.

```http
GET /api/v1/agent-bridge/sessions/{target}/attachments
DELETE /api/v1/agent-bridge/sessions/{target}/attachments/{attachment_id}
```

Attachments are stored by default under `~/.claude-registry/bridge-attachments`. In remote deployments, this path is on the Claude Deck host and must be readable by the tmux agent process.

Configuration:

- `BRIDGE_ATTACHMENT_DIR`: host storage directory
- `BRIDGE_ATTACHMENT_AGENT_ROOT`: optional agent-visible root to use in pasted paths
- `BRIDGE_ATTACHMENT_MAX_BYTES`: maximum accepted upload size
- `BRIDGE_ATTACHMENT_RETENTION_DAYS`: retention window for startup cleanup
- `BRIDGE_ATTACHMENT_MAX_PER_SESSION_PER_DAY`: per-session daily upload limit

Agentic interfaces can use the MCP shim tools:

- `deck_attach_image_to_bridge_session(target, file_path, submit, prompt)`
- `deck_list_bridge_attachments(target)`
- `deck_paste_bridge_attachment(target, attachment_id, submit)`

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

Copilot example:

```json
{
  "provider": "copilot-cli",
  "directory": "/home/user/repo",
  "mode": "resume",
  "use_last": true,
  "model": "claude-sonnet-4.6",
  "agent": "planner",
  "context_tier": "long_context",
  "reasoning_effort": "high",
  "plan": true,
  "remote": true
}
```

### Delete Session

```http
DELETE /api/v1/agent-bridge/sessions/{target}
```

Kills the tmux session or pane target.

## Legacy Route

`/api/v1/cc-bridge/*` remains for compatibility. New clients should use `/api/v1/agent-bridge/*`.
