# Agent Bridge

Agent Bridge discovers and manages local agent CLIs running inside tmux. It supports mixed Claude Code and Codex CLI sessions in the same view.

## Overview

The bridge performs a provider-aware tmux discovery pass and classifies each matching pane as `claude-code` or `codex-cli`. The UI can show all sessions together or filter to one provider.

Session cards include:

- Provider badge
- tmux target
- Current working directory
- Live preview
- Attach, fullscreen, and kill controls

The terminal grid is shared across providers. Read-only and interactive modes work the same way whether the pane is Claude Code or Codex.

Provider filters are explicit:

- **All** — mixed Claude Code and Codex sessions
- **Claude Code** — Claude Code panes only
- **Codex** — Codex panes only

## New Sessions

The new session dialog starts with a provider choice.

Claude Code keeps the existing session modes:

- Plain session
- Worktree session
- Resume session

Codex CLI supports:

- New session with `codex --cd <directory>`
- Resume by session id or `--last`
- Fork by session id or `--last`
- Model and profile selectors with custom-value fallback
- Optional sandbox, approval policy, web search, and prompt seed

Dangerous Codex bypass mode is exposed as an explicit advanced option because it disables approval and sandbox protections.

Both providers support a launch-time platform choice:

- Claude Code: Anthropic or Amazon Bedrock
- Codex CLI: OpenAI or Amazon Bedrock

For Codex Bedrock sessions, Deck passes a per-session Codex config override for `model_provider = "amazon-bedrock"`. Optional AWS region and profile values are passed as process environment variables. Deck does not collect AWS secret keys or Bedrock bearer tokens; Codex resolves credentials from the existing shell environment or AWS SDK credential chain.

## Compatibility

The frontend route `/agent-bridge` is the primary route. `/cc-bridge` remains as a compatibility alias.

The backend keeps `/api/v1/cc-bridge/*` for existing callers and adds `/api/v1/agent-bridge/*` for provider-aware clients.

## Smoke Coverage

Multi-provider smoke checks should cover mixed discovery, provider filters, attach/read-only/interactive terminal behavior, Codex spawn/resume/fork options, and the legacy `/cc-bridge` compatibility route. Claude-only transcript, usage, context, plugin, permission, hook, agent, skill, and memory pages should stay hidden or disabled when Codex is the selected provider until provider-aware equivalents exist.
