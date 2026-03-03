# Config

The Config page lets you view, edit, and understand Claude Code settings across all configuration scopes.

## Overview

Claude Code stores settings in multiple files at different scopes. The Config page provides three views:

- **Settings Editor** — form-based editor for common settings
- **Scope Resolver** — shows how settings merge from different scopes
- **Raw Viewer** — displays actual configuration files

## How to Use

### Settings Editor

The Settings Editor tab provides form controls for common Claude Code settings:

| Setting | Type | Description |
|---------|------|-------------|
| Model | Dropdown | Claude model selection (Opus 4.6, Sonnet 4.6, Haiku 4.5, etc.) |
| Permission Mode | Dropdown | default, acceptEdits, dontAsk, plan, bypassPermissions, delegate |
| Update Channel | Dropdown | stable or latest |
| Teammate Mode | Dropdown | auto, in-process, or tmux |
| Read-only Files | Toggle | Always allow reading files without permission prompts |
| Timeouts & Limits | Number inputs | Various timeout and limit settings |

The editor also includes a **Permission Rules** section where you can add allow/ask/deny patterns using glob syntax.

### Scope Resolver

The Scope Resolver tab shows how Claude Code merges settings from four sources (highest to lowest priority):

1. **Local** — `~/.claude/settings.local.json` (not committed)
2. **Project** — `.claude/settings.json` (project-specific)
3. **User** — `~/.claude/settings.json` (user-wide)
4. **Managed** — Enterprise-enforced settings (read-only)

For each setting, you can see which scope provides the active value and use the "Override in local" button to copy a value to your local scope.

### Raw Viewer

The Raw Viewer tab shows a file list on the left and file content on the right:

- `~/.claude.json` — OAuth tokens, caches, MCP servers
- `~/.claude/settings.json` — User settings and permissions
- `.claude/settings.json` — Project settings
- `.mcp.json` — Project MCP servers
- `CLAUDE.md` — Project instructions
- Command files from `~/.claude/commands/` and `.claude/commands/`

::: tip
Sensitive values (tokens, secrets, passwords, API keys) are automatically masked in the merged settings view.
:::

## Configuration

The Config page reads and writes to the standard Claude Code configuration files. No additional Claude Deck configuration is needed.

## Tips

- Use the **Scope Resolver** to understand why a setting has a particular value — it shows the source scope.
- **Local overrides** (`settings.local.json`) take highest priority and are not committed to version control.
- Permission patterns support glob syntax. The editor validates patterns and suggests fixes for deprecated syntax.
