# Memory

View and edit Claude Code's memory hierarchy — CLAUDE.md files, rules, auto-memory, and imports.

## Overview

Claude Code uses a layered memory system where instructions are loaded from multiple files at different scopes. The Memory page provides four tabs:

- **Hierarchy** — CLAUDE.md files across all scopes
- **Rules** — path-scoped rule files
- **Auto-Memory** — session-generated memory files
- **Imports** — dependency tree of @path references

## How to Use

### Memory Hierarchy

The Hierarchy tab shows CLAUDE.md files organized by scope (highest to lowest priority):

| Scope | File | Description |
|-------|------|-------------|
| **Managed** | Enterprise CLAUDE.md | Organization-wide policy (read-only) |
| **User** | `~/.claude/CLAUDE.md` | User preferences and global instructions |
| **Project** | `.claude/CLAUDE.md` or `CLAUDE.md` | Team project instructions |
| **Local** | `.claude/CLAUDE.local.md` | Personal project overrides (not committed) |

Click any memory file card to open the editor with markdown preview. Quick create buttons let you create missing files at any scope.

### Rules

Rules are markdown files in `.claude/rules/` with optional path-scoped frontmatter:

```yaml
---
description: TypeScript formatting rules
paths:
  - "src/**/*.ts"
  - "src/**/*.tsx"
---
Use strict TypeScript. No `any` types.
```

Rules only apply when working on files matching the specified paths.

### Auto-Memory

Session-based memory files that Claude Code auto-generates, stored in `~/.claude/projects/{project}/memory/`. These persist learnings and preferences across sessions for each project.

### Imports

The Imports tab shows the dependency tree of `@path` references across memory files:

```markdown
<!-- In CLAUDE.md -->
@./docs/coding-standards.md
@~/global-rules.md
```

Import syntax:
- `@./relative/path` — relative to current file
- `@~/user/path` — relative to home directory
- `@/absolute/path` — absolute path

The import viewer detects circular references and shows them as warnings.

## Configuration

Memory files are standard markdown. No special Claude Deck configuration needed — the Memory page reads and writes directly to the filesystem.

## Tips

- **Local files** (`.claude/CLAUDE.local.md`) are for personal overrides — they're not committed to version control.
- **Managed files** are read-only (enterprise-enforced).
- Use **rules** with path patterns to apply instructions only to specific file types.
- **Auto-memory** files are auto-generated — edit them to correct or refine Claude's learned preferences.
