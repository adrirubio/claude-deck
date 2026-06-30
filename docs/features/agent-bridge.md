# Agent Bridge

Agent Bridge discovers and manages local agent CLIs running inside tmux. It supports mixed Claude Code, Codex CLI, GitHub Copilot CLI, and OpenCode CLI sessions in the same view.

## Overview

The bridge performs a provider-aware tmux discovery pass and classifies each matching pane as `claude-code`, `codex-cli`, `copilot-cli`, or `opencode-cli`. The UI can show all sessions together or filter to one provider.

Session cards include:

- Provider badge
- tmux target
- Current working directory
- Live preview
- Attach, fullscreen, and kill controls

The terminal grid is shared across providers. Read-only and interactive modes work the same way whether the pane is Claude Code, Codex, or Copilot.

Provider filters are explicit:

- **All** — mixed Claude Code, Codex, Copilot, and OpenCode sessions
- **Claude Code** — Claude Code panes only
- **Codex** — Codex panes only
- **Copilot** — GitHub Copilot CLI panes only
- **OpenCode** — OpenCode CLI panes only

When Agent Team sessions are running, Agent Bridge also shows a team filter row. Team filters compose with provider filters, so selecting a team and a provider shows only matching session cards. Selecting a specific team also detaches any open terminal panes that do not belong to that team; it does not auto-attach that team's sessions or kill any tmux sessions. New sessions launched from Agent Bridge remain standalone and are not attached while a specific team filter is active.

With a specific team selected, the **Team lanes** action opens a fullscreen vertical-lane layout for that team. Lane mode shows up to four live team sessions side by side, ordered by configured team slot position, without changing the normal grid attachments. Press `Esc` or the exit button to return to the previous grid; if more than four members are live, Agent Bridge shows how many are not displayed.

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

GitHub Copilot CLI supports:

- New sessions with `copilot -C <directory>`
- Resume by session id or `--continue`
- Optional model, custom agent, context tier, reasoning effort, plan mode, remote control, prompt seed, and explicit permissive launch flags

Claude Code and Codex support a launch-time platform choice:

- Claude Code: Anthropic or Amazon Bedrock
- Codex CLI: OpenAI or Amazon Bedrock

For Codex Bedrock sessions, Deck passes a per-session Codex config override for `model_provider = "amazon-bedrock"`. Optional AWS region and profile values are passed as process environment variables. Deck does not collect AWS secret keys or Bedrock bearer tokens; Codex resolves credentials from the existing shell environment or AWS SDK credential chain.

## Compatibility

The frontend route `/agent-bridge` is the primary route. `/cc-bridge` remains as a compatibility alias.

The backend keeps `/api/v1/cc-bridge/*` for existing callers and adds `/api/v1/agent-bridge/*` for provider-aware clients.

## Smoke Coverage

Multi-provider smoke checks should cover mixed discovery, provider filters, attach/read-only/interactive terminal behavior, Codex spawn/resume/fork options, and the legacy `/cc-bridge` compatibility route. Claude-only transcript, usage, context, plugin, permission, hook, agent, skill, and memory pages should stay hidden or disabled when Codex is the selected provider until provider-aware equivalents exist.
