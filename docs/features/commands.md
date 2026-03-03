# Commands

Create, manage, and organize custom slash commands for Claude Code.

## Overview

Slash commands are markdown files that Claude Code executes when you type `/command-name`. Claude Deck lets you browse all available commands across user, project, and plugin scopes, create new ones with a guided wizard, and edit existing ones.

## How to Use

### Browsing Commands

The Commands page shows all available commands grouped by scope:

- **User** — global commands in `~/.claude/commands/`
- **Project** — project-specific commands in `.claude/commands/`
- **Plugin** — commands provided by installed plugins (read-only)

Use the search bar to filter by name, description, or content. Stats at the top show counts per scope.

### Creating a Command

Click **"Add Command"** to open the wizard:

1. **Name** — enter the command name and optional namespace (e.g., `tools:analyze` becomes `/tools:analyze`)
2. **Scope** — choose user (global) or project (version-controlled)
3. **Frontmatter** — add description and allowed tools
4. **Content** — select a template or write custom markdown

### Editing Commands

Click a command card to view its details, then click **Edit** to modify the description, allowed tools, or markdown content.

### Allowed Tools

Commands can restrict which tools they use via the `allowed-tools` frontmatter:

```yaml
---
description: Run the test suite
allowed-tools: Bash, Read
---
Run all tests and report results.
```

Available tools: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebFetch`, `Task`

## Configuration

| Location | Scope | Description |
|----------|-------|-------------|
| `~/.claude/commands/` | User | Global commands |
| `.claude/commands/` | Project | Project-specific commands |

Commands are stored as `.md` files. Namespaces map to subdirectories: `tools:analyze` → `commands/tools/analyze.md`.

## Tips

- **Plugin commands** are read-only — you can view them but not edit or delete.
- **Namespaces** help organize large command libraries (e.g., `git:hooks`, `tools:lint`).
- Use **allowed-tools** to restrict what a command can do for security.
