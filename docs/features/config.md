# Config

The Config page lets you view, edit, and understand provider configuration. Claude Code uses JSON settings across multiple scopes; Codex CLI uses TOML files under `$CODEX_HOME`.

## Overview

Claude Code stores settings in multiple files at different scopes. The Claude Code config page provides three views:

- **Settings Editor** — form-based editor for common settings
- **Scope Resolver** — shows how settings merge from different scopes
- **Raw Viewer** — displays actual configuration files

## How to Use

### Settings Editor

The Settings Editor tab provides form controls for common Claude Code settings:

| Setting | Type | Description |
|---------|------|-------------|
| Model | Dropdown | Claude model selection, including current Opus, Sonnet, Haiku, and Fable aliases |
| Advisor Model | Text input | Optional model alias or full model ID for Claude Code's advisor tool |
| Fallback Models | List | Ordered model chain to try when the primary model is overloaded or unavailable |
| Permission Mode | Dropdown | default, acceptEdits, dontAsk, plan, bypassPermissions, delegate |
| Update Channel | Dropdown | stable or latest |
| Teammate Mode | Dropdown | auto, in-process, or tmux |
| Remote Control & Notifications | Toggles/dropdowns | Remote Control startup, mobile push notifications, and terminal notification channel |
| Safety & Privacy | Toggles | Artifact publishing, Claude.ai connectors, bundled skills, WebFetch preflight, hooks, and workflow behavior |
| Plugins | Map/JSON editors | Plugin enablement and marketplace settings using Claude Code's documented JSON shapes |
| Worktrees & Sandbox | Lists/toggles | Worktree base refs, symlink directories, sparse paths, sandbox filesystem/network controls, and macOS service allowlists |
| Timeouts & Limits | Number inputs | Cleanup, feedback survey, file suggestion, and sandbox proxy settings |

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

## Codex CLI

When the selected provider is Codex CLI, the Config page switches to Codex-specific cards:

- General settings such as model, reasoning effort, and profile
- Runtime settings such as sandbox, approval policy, search, strict config, and alternate screen behavior
- Feature flags reported by `codex features list`
- Project trust entries
- Profile v2 files
- Rules files
- MCP and plugin inventory
- Diagnostics from `codex doctor`

Codex config writes are intentionally narrower than Claude Code settings. Claude Deck only updates whitelisted TOML keys, creates a backup before saving, and refuses unsafe paths. Auth, history, model cache, and log files are not shown in the raw viewer.

### Codex Settings Editor

The Codex editor keeps open-ended fields editable and uses dropdowns where Codex has known values:

| Setting | Control | Notes |
|---------|---------|-------|
| Model | Dropdown with custom fallback | Shows model ids already found in the loaded config/profile data, while still allowing any Codex-supported model id. |
| Reasoning Effort | Dropdown | Default, low, medium, high, or extra high. Existing custom values remain selectable. |
| Profile | Dropdown with custom fallback | Shows profile names found in config/profile diagnostics, while still allowing any Codex profile name. |
| Sandbox Mode | Dropdown | Default, read-only, workspace-write, or danger-full-access. |
| Approval Policy | Dropdown | Default, untrusted, on-request, never, or deprecated on-failure. |
| Search | Toggle | Enables live web search for Codex. |
| Strict Config | Toggle | Makes Codex reject unrecognized config fields. |
| No Alt Screen | Toggle | Runs the Codex TUI inline so terminal scrollback is preserved. |

Settings and feature labels include help icons. When an official description is known, the tooltip explains the setting. When a Codex feature flag has no public description, Claude Deck says so and still shows the stage and current effective state reported by the installed CLI.

### Codex Feature Flags

The Features card lists active, non-deprecated flags from `codex features list`. The value shown is the effective value from Codex unless you explicitly override it in `config.toml`.

Common documented flags include:

- `goals`
- `memories`
- `hooks`
- `multi_agent`
- `network_proxy`
- `shell_tool`
- `shell_snapshot`
- `unified_exec`
- `prevent_idle_sleep`

Use the reset button next to a configured flag to remove the explicit override and return to the Codex default.

Profile diagnostics resolve default and active profiles, profile files, inherited and overridden settings, and missing or malformed profile files. Summaries redact secret-like values and avoid exposing auth, history, or cache data.

History and model-cache diagnostics are privacy-bounded. They may report file existence, size, parse state, root keys, row counts, and metric-like key names, but they do not return prompt text, session ids, raw history rows, model ids, raw model cache payloads, or SQLite contents.

Usage and context parity are not supported for Codex. Claude Code usage and context pages remain Claude-specific until Codex exposes a stable metric source that can be read without sensitive prompt or cache data.

Codex backups are export-only in this version. They include redacted config, profile files, rules, and provider inventory metadata, but automatic restore is disabled.

## Tips

- Use the **Scope Resolver** to understand why a setting has a particular value — it shows the source scope.
- **Local overrides** (`settings.local.json`) take highest priority and are not committed to version control.
- Permission patterns support glob syntax. The editor validates patterns and suggests fixes for deprecated syntax.
