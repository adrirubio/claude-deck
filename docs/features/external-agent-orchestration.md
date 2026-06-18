# External Agent Orchestration

Claude Deck exposes a local Agent Mail API for tools such as OpenClaw to coordinate installed agents without pretending to be a repo agent or a UI user.

This API is for same-machine automation. It does not replace Agent Teams preset launch APIs, and it does not add a new wake path for non-tmux agent sessions.

## Setup

Create or rotate a local external actor token:

```bash
curl -s http://127.0.0.1:8000/api/v1/external/agent-mail/actors \
  -H 'Content-Type: application/json' \
  -d '{
    "actor_key": "openclaw",
    "display_name": "OpenClaw",
    "kind": "external_tool",
    "description": "Local validation and orchestration agent"
  }'
```

Store the returned `token` locally and send it as a bearer token:

```bash
export DECK_EXTERNAL_AGENT_TOKEN='returned-token'
export DECK_API='http://127.0.0.1:8000/api/v1'
```

Actor registration is loopback-only. External Agent Mail endpoints require `Authorization: Bearer ...`.

## Discover Participants

```bash
curl -s "$DECK_API/external/agent-mail/members" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN"
```

The response includes each Agent Mail participant's repo, role, charter, connection status, inbox load, `wake_state`, `wake_methods`, and current Agent Team preset/slot context when present. A repository can have multiple participants when Agent Team slots represent distinct same-repo roles.

Wake states mean:

- `wakeable`: Claude Deck has a visible wake path, currently tmux-observed Claude Code or Codex through Agent Bridge.
- `delivered_waiting`: the message can be stored and read through Agent Mail, but Claude Deck cannot wake the visible session.
- `offline`: no live session is available.

## Send A Direct Message

```bash
curl -s "$DECK_API/external/agent-mail/messages" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "recipient_member_id": 2,
    "subject": "Validation note",
    "body_markdown": "Please check your local test result when you are next active."
  }'
```

The response includes the stored message, receipt recipients, aggregate `delivery_state`, and per-recipient wake results.

## Request Context And Poll

```bash
curl -s "$DECK_API/external/agent-mail/context-requests" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "recipient_member_id": 2,
    "subject": "Need API ownership context",
    "body_markdown": "Which module owns the Agent Mail delivery path?",
    "why_needed": "OpenClaw is validating a cross-repo change.",
    "files_or_symbols": ["backend/app/services/agent_mail_service.py"]
  }'
```

Poll the request:

```bash
curl -s "$DECK_API/external/agent-mail/requests/17/status" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN"
```

Or wait briefly with bounded local long-polling:

```bash
curl -s "$DECK_API/external/agent-mail/requests/17/wait?timeout_seconds=20" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN"
```

After consuming an answer, an external actor can acknowledge its own request:

```bash
curl -s -X POST "$DECK_API/external/agent-mail/requests/17/ack" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN"
```

## Handoffs And Broadcasts

Create a handoff:

```bash
curl -s "$DECK_API/external/agent-mail/handoffs" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "recipient_member_id": 2,
    "subject": "Take over deploy check",
    "body_markdown": "Please continue from the failed deploy step.",
    "files": ["infra/deploy.yaml"],
    "next_steps": ["Inspect the failing job", "Reply with the owner and likely fix"]
  }'
```

Broadcast to all Agent Mail members:

```bash
curl -s "$DECK_API/external/agent-mail/broadcasts" \
  -H "Authorization: Bearer $DECK_EXTERNAL_AGENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "subject": "Validation run started",
    "body_markdown": "OpenClaw has started a local validation pass."
  }'
```

## Agent Teams Integration

External tools should use the existing Agent Teams API to launch or reuse a saved roster:

```bash
curl -s "$DECK_API/agent-teams/presets"
curl -s -X POST "$DECK_API/agent-teams/presets/3/plan-launch" \
  -H 'Content-Type: application/json' \
  -d '{"requested_by": "OpenClaw"}'
```

After reviewing the plan, launch with the returned plan hash:

```bash
curl -s -X POST "$DECK_API/agent-teams/presets/3/launch" \
  -H 'Content-Type: application/json' \
  -d '{
    "requested_by": "OpenClaw",
    "confirm_plan_hash": "returned-plan-hash"
  }'
```

Once agents register through Agent Mail, use `/external/agent-mail/members` to discover their participant/member ids, then send context requests or handoffs through the external Agent Mail endpoints.

## Safeguards

- External actor tokens are distinct from Agent Mail members and are shown by name in the Agent Mail UI.
- Non-tmux Claude Code and Codex sessions return `delivered_waiting`; they are not falsely reported as woken.
- Per-actor message rate limits return `429` with a `Retry-After` header.
- This is a local trust boundary, not a general network authentication system.
