# Hooks

Configure event-triggered actions that run during the Claude Code lifecycle.

## Overview

Hooks execute commands, inject prompts, or spawn subagents in response to Claude Code events. They're stored in `settings.json` and organized by event type.

## How to Use

### Browsing Hooks

The Hooks page shows hooks organized in tabs by event type. Stats cards at the top show total, user, and project hook counts.

### Creating a Hook

Click **"Add Hook"** to open the wizard:

1. **Event** — select when the hook triggers (see events table below)
2. **Matcher** — optional pattern to filter which tools trigger the hook
3. **Type & Content** — choose the hook type and configure it:
   - **Command** — shell command to execute
   - **Prompt** — text to inject into the conversation
   - **Agent** — spawn a subagent with a prompt and model selection
4. **Scope & Options** — set user/project scope and advanced options

### Hook Events

| Event | When It Fires |
|-------|--------------|
| `PreToolUse` | Before a tool is called |
| `PostToolUse` | After a tool completes |
| `BeforeCompletion` | Before Claude sends a response |
| `Notification` | When a notification is displayed |
| `Stop` | When Claude stops generating |
| `SubagentStop` | When a subagent stops |
| `PreCompact` | Before context compaction |
| `PostCompact` | After context compaction |
| `UserPromptSubmit` | When the user submits a prompt |

### Hook Types

| Type | Description | Example |
|------|-------------|---------|
| **Command** | Execute a shell command | `npm run lint` |
| **Prompt** | Inject text into the conversation | "Remember to follow the style guide" |
| **Agent** | Spawn a Claude subagent | Custom review agent with Haiku model |

### Advanced Options

- **Matcher** — regex/glob pattern to match specific tools (e.g., `Bash` to only trigger on Bash tool use)
- **Async** — run in the background without blocking Claude
- **Once** — run only once per session
- **Status Message** — custom spinner text while the hook executes
- **Timeout** — maximum execution time in seconds

### Environment Variables

Command hooks have access to context variables:

- `$CLAUDE_TOOL_NAME` — name of the tool being used
- `$CLAUDE_TOOL_ARGS` — tool arguments as JSON
- `$CLAUDE_PROJECT_DIR` — current project directory

## Configuration

Hooks are stored in `settings.json` under the `hooks` key, organized by event:

| File | Scope |
|------|-------|
| `~/.claude/settings.json` | User hooks |
| `.claude/settings.json` | Project hooks |

## Tips

- Use **PreToolUse** hooks for validation (e.g., lint before committing).
- Use **PostToolUse** hooks for logging or notifications.
- **Prompt hooks** on `BeforeCompletion` can enforce coding standards.
- The **async** flag is useful for long-running operations that shouldn't block Claude.
- **Templates** in the wizard provide quick starts for common hook patterns.
