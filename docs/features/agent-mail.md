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

Codex CLI gets the MCP server through `codex mcp add`. Lifecycle hooks are not supported for Codex in this MVP.

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
- Agent Mail is coordination state, not source control. Handoffs should still reference files, branches, issues, or commits when durable provenance matters.

## Install Details

Open **Agent Mail** in Claude Deck and use the **Install** tab.

- Claude Code install adds user-scope command hooks and a user-scope MCP server.
- Codex install runs the Codex CLI MCP installer.
- Install and uninstall actions require confirmation and attempt a backup before mutating config.

The Install tab also shows manual Codex snippets for config and `AGENTS.md`.
