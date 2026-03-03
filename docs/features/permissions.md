# Permissions

Visual rule builder for controlling which operations Claude Code can perform.

## Overview

The Permissions page lets you define allow, ask, and deny rules using pattern matching. Rules control tool access at both user and project levels.

## How to Use

### Viewing Rules

Rules are organized in three tabs:

- **Allow** — operations Claude can perform automatically
- **Ask** — operations that require user confirmation
- **Deny** — operations that are blocked entirely

Each rule shows its pattern (e.g., `Bash(npm run *)`), scope badge, and type hints.

### Creating Rules

Click **"Add Rule"** on any tab to open the rule builder:

1. **Type** — select Allow, Ask, or Deny
2. **Tool** — choose the tool (Bash, Read, Write, WebFetch, MCP, Task, Skill, etc.)
3. **Pattern** — enter an argument pattern with wildcards
4. **Scope** — set user (global) or project (per-project)

Quick pattern buttons provide common presets for each tool.

### Pattern Syntax

Rules use `Tool(pattern)` format with glob wildcards:

| Pattern | Matches |
|---------|---------|
| `Bash` | All Bash commands |
| `Bash(npm run *)` | Any npm run command |
| `Read(*.env)` | Reading .env files |
| `Write(/tmp/*)` | Writing to /tmp/ |
| `WebFetch(domain:*.anthropic.com)` | Fetching from Anthropic domains |
| `MCP(server:postgres:*)` | All tools from postgres MCP server |
| `Task(explore)` | Explore subagent only |
| `Skill(skill-name)` | Specific skill |

### Evaluation Order

Rules are evaluated with deny taking highest priority:

1. **Deny** rules checked first — if matched, operation is blocked
2. **Ask** rules checked next — if matched, user is prompted
3. **Allow** rules checked last — if matched, operation proceeds
4. If no rules match, the **default mode** applies

### Permission Settings

The settings card provides:

- **Default Permission Mode** — `default` (ask by default), `dontAsk` (allow by default), or `conservative` (deny by default)
- **Disable Bypass Mode** — prevents using `--dangerously-skip-permissions`
- **Additional Allowed Directories** — paths outside the project that Claude can access

## Configuration

| File | Scope |
|------|-------|
| `~/.claude/settings.json` → `permissions` | User rules |
| `.claude/settings.json` → `permissions` | Project rules |

Rules are stored as arrays under `allow`, `ask`, and `deny` keys.

## Tips

- Start with **deny rules** for sensitive operations, then add specific allow rules.
- Use **domain filtering** on WebFetch to restrict which sites Claude can access.
- **Project-level rules** extend (don't replace) user-level rules.
- The **conservative** default mode blocks everything not explicitly allowed — good for sensitive projects.
