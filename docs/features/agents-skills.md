# Agents & Skills

Create custom agents and discover reusable skills for Claude Code.

## Agents

Agents are autonomous configurations with specialized system prompts, tool permissions, and memory scopes.

### Browsing Agents

The Agents page shows all agents grouped by scope (user, project, plugin) with stat cards. Each agent card displays the name, description, scope badge, and configured tools.

### Creating an Agent

Click **"New Agent"** to open the wizard:

1. **Name & Description** — agent identity
2. **Scope** — user (global) or project (version-controlled)
3. **Tools** — list of allowed tools and disallowed tools
4. **Model** — Claude model to use
5. **Content** — system prompt (markdown)

### Agent Configuration

Agents support YAML frontmatter in markdown files:

```yaml
---
description: Code review specialist
tools: Read, Grep, Glob
disallowed-tools: Write, Bash
permission-mode: default
model: claude-sonnet-5
skills: code-review, testing
memory: user
---
Review code for quality, security, and maintainability.
```

| Property | Description |
|----------|-------------|
| `tools` | Allowed tools list |
| `disallowed-tools` | Blocked tools list |
| `permission-mode` | Permission level for the agent |
| `model` | Claude model |
| `skills` | Skills the agent can use |
| `hooks` | Before/after hooks (command or prompt type) |
| `memory` | Memory scope (none, user, session) |

### Storage

| Location | Scope |
|----------|-------|
| `~/.claude/agents/` | User agents |
| `.claude/agents/` | Project agents |

---

## Skills

Skills are reusable knowledge and workflow modules — markdown files with metadata that extend Claude's capabilities.

### Browsing Skills

The Skills page has two tabs:

- **Installed** — skills on your system with dependency status badges
- **Discover** — browse and install from the [skills.sh](https://skills.sh) registry

Each skill card shows the name, description, scope badge, and tags (context, tools, fork, hidden, user-invocable).

### Skill Metadata

Skills use YAML frontmatter:

```yaml
---
name: code-review
description: Review code for quality issues
version: 1.0.0
allowed-tools: Read, Grep, Glob
user-invocable: true
argument-hint: "path to review"
---
```

| Property | Description |
|----------|-------------|
| `allowed-tools` | Tools the skill can access |
| `user-invocable` | Whether users can call it directly as `/skill-name` |
| `argument-hint` | Hint text for skill arguments |
| `context` | Fork context for the skill |
| `disable-model-invocation` | Prevent Claude from auto-invoking |

### Storage

| Location | Scope |
|----------|-------|
| `~/.claude/skills/` | User skills |
| `.claude/skills/` | Project skills |

## Tips

- **Plugin agents and skills** are read-only — view but not edit.
- Skills show dependency status (green = satisfied, amber = missing) to help troubleshoot.
- Agents can reference skills in their frontmatter to compose capabilities.
