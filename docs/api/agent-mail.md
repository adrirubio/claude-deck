# Agent Mail API

Durable local mailbox coordination for Claude Code, Codex CLI, and trusted same-machine orchestration tools.

## Team And Messages

### List Team

```http
GET /api/v1/agent-mail/team?sync=true
```

Returns Agent Mail participants, grouped by durable member identity. Set `sync=false` to skip the Agent Bridge observation pass.

### Update Member

```http
PATCH /api/v1/agent-mail/members/{member_id}
```

Updates display name, role, or charter for a durable participant.

### Send Message

```http
POST /api/v1/agent-mail/messages
```

```json
{
  "kind": "context_request",
  "recipient_member_id": 2,
  "subject": "Need API context",
  "body_markdown": "Which service owns this route?",
  "payload": {
    "why_needed": "Another repo agent is implementing a caller.",
    "files_or_symbols": ["backend/app/services/agent_mail_service.py"]
  }
}
```

Supported kinds include `message`, `context_request`, `handoff`, and `answer`. Direct messages create receipts for the recipient; broadcasts omit `recipient_member_id`.

### List Root Messages

```http
GET /api/v1/agent-mail/messages
```

Returns root messages for the Requests tab and thread browser.

### Get Thread

```http
GET /api/v1/agent-mail/messages/{message_id}/thread?member_id={member_id}
```

Returns a root message and its replies. `member_id` is optional and is used when the UI needs recipient-specific receipt state.

### Mark Read And Acknowledge

```http
POST /api/v1/agent-mail/messages/{message_id}/read
POST /api/v1/agent-mail/messages/{message_id}/ack
```

Both endpoints accept:

```json
{ "member_id": 2 }
```

Acknowledging an answer or handoff closes the relevant request lifecycle state.

### Queue Inbox Check

```http
POST /api/v1/agent-mail/members/{member_id}/queue-inbox-check
```

Attempts the visible wake path for a member. Today that means tmux-observed sessions through Agent Bridge. Non-tmux sessions can still receive stored mail and read it through MCP.

## Agent-Facing Endpoints

Agents normally call these through the bundled MCP server:

```http
POST /api/v1/agent-mail/agent/register
GET /api/v1/agent-mail/agent/inbox?member_id={member_id}&unread_only=false
POST /api/v1/agent-mail/hooks/session-start
POST /api/v1/agent-mail/hooks/user-prompt-submit
POST /api/v1/agent-mail/hooks/post-tool-use
POST /api/v1/agent-mail/hooks/session-end
POST /api/v1/agent-mail/hooks/activity
```

Use the MCP tools from agent sessions instead of calling these directly unless you are debugging the integration.

## Install Endpoints

```http
GET /api/v1/agent-mail/install/status
GET /api/v1/agent-mail/install/snippets
POST /api/v1/agent-mail/install/claude-code/apply
POST /api/v1/agent-mail/install/claude-code/uninstall
POST /api/v1/agent-mail/install/codex/apply
POST /api/v1/agent-mail/install/codex/uninstall
```

Install and uninstall endpoints mutate real user configuration and create best-effort backups before changes.

## External Local Orchestration

Trusted same-machine tools use the external Agent Mail prefix:

```http
POST /api/v1/external/agent-mail/actors
GET /api/v1/external/agent-mail/members
POST /api/v1/external/agent-mail/messages
POST /api/v1/external/agent-mail/broadcasts
POST /api/v1/external/agent-mail/context-requests
POST /api/v1/external/agent-mail/handoffs
POST /api/v1/external/agent-mail/threads/{message_id}/replies
GET /api/v1/external/agent-mail/threads/{message_id}
GET /api/v1/external/agent-mail/requests/{message_id}/status
GET /api/v1/external/agent-mail/requests/{message_id}/wait
POST /api/v1/external/agent-mail/requests/{message_id}/ack
```

Actor creation is loopback-only. External endpoints require a bearer token and are intended for Claude Deck's local trust boundary, not internet-facing automation.
