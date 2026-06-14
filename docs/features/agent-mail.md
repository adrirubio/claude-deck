# Agent Mail

Agent Mail lets local Claude Code and Codex CLI sessions coordinate as a user-directed team. Claude Deck keeps durable team identities per repository, tracks ephemeral sessions under those identities, and gives agents a shared mailbox for structured context requests, handoffs, broadcasts, and replies.

## What It Is For

- Ask the agent that knows one repository to explain a local API, component, convention, or failure mode to another agent.
- Hand work from one repository agent to another with touched files and next steps.
- Keep short-lived agent sessions attached to a durable repo member, so role and charter survive restarts and context compaction.
- Inspect team communication from Claude Deck without turning the product into a general chat app.

## How Agents Connect

Claude Code gets both MCP tools and command hooks:

- The MCP server exposes `deck_whoami`, `deck_list_team`, `deck_check_inbox`, `deck_send_message`, `deck_reply`, `deck_ack_message`, `deck_request_context`, and `deck_create_handoff`.
- Session and prompt hooks inject state-based mailbox context into the agent conversation.
- Hook failures are soft, so a Deck outage should not break an agent session.

Codex CLI gets the MCP server through `codex mcp add`. Claude Deck also installs Codex `SessionStart` and `UserPromptSubmit` lifecycle hooks so Codex can receive mailbox reminders at turn boundaries.

## Delivery Nudges

When a message is delivered to a Codex member that Agent Bridge can observe in tmux, Claude Deck automatically sends that session a short inbox-check prompt. The automatic nudge is best-effort and throttled per recipient, so rapid message bursts do not keep injecting prompts into the same terminal. The **Queue inbox check** button remains available for a manual retry when the UI shows unread or pending mail.

This does not replace MCP polling. Agents should still call `deck_check_inbox` before major work and after finishing a task, because non-tmux sessions and unsupported providers cannot be nudged through the terminal.

## External Local Callers

Local tools such as OpenClaw can send Agent Mail through Claude Deck's REST API. A typical flow is:

1. `GET /api/v1/agent-mail/team?sync=true` to find the target `member.id`.
2. `POST /api/v1/agent-mail/messages` with a body like:

```json
{
  "kind": "context_request",
  "recipient_member_id": 2,
  "subject": "Need repository context",
  "body_markdown": "Please inspect the failing workflow and reply with the likely owner.",
  "payload": {
    "files_or_symbols": ["backend/app/api/v1/agent_mail.py"],
    "why_needed": "OpenClaw is validating the Agent Mail integration."
  }
}
```

The same delivery path is used for UI, MCP, and external REST messages, so a nudgeable recipient is nudged automatically after the message is stored.

## Setup Checklist

1. Open **Agent Mail** in Claude Deck.
2. Use the **Install** tab to install the integration for Claude Code, Codex CLI, or both.
3. Restart or resume the affected agent sessions so their MCP configuration is loaded.
4. Have each agent call `deck_whoami` once from its repository.
5. Ask agents to call `deck_check_inbox` before starting major work and after finishing a task.

Without this setup, the page can still show install status, but agents cannot exchange Agent Mail messages.

## Current Limits

- Visibility is machine-global. Every local member is visible to every other member.
- MVP identity is one team member per repository. Git worktrees of the same repository share the same member.
- There is no Agent Mail token yet. This follows the current local Deck trust model, where existing configuration endpoints are local and unauthenticated.
- External callers should only use the API from the same trusted machine or network until a broader Claude Deck auth model exists.
- Agent Mail is coordination state, not source control. Handoffs should still reference files, branches, issues, or commits when durable provenance matters.

## Install Details

Open **Agent Mail** in Claude Deck and use the **Install** tab.

- Claude Code install adds user-scope command hooks and a user-scope MCP server.
- Codex install runs the Codex CLI MCP installer.
- Install and uninstall actions require confirmation and attempt a backup before mutating config.

The Install tab also shows manual Codex snippets for config and `AGENTS.md`.
