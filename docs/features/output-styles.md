# Output Styles

Configure custom output formatting to shape how Claude responds.

## Overview

Output styles are markdown files with formatting instructions that control Claude's response style — conciseness, verbosity, markdown flavor, code block preferences, etc.

## How to Use

### Browsing Styles

The Output Styles page lists all configured styles with name, description, and scope badge. A stat card shows the total count and how many have the "keep coding instructions" flag enabled.

### Creating a Style

Click **"New Style"** to open the wizard:

1. Enter a name and description
2. Choose the scope (user or project)
3. Toggle "Keep coding instructions" if desired
4. Write formatting instructions in markdown

### Style Format

Styles use YAML frontmatter in markdown files:

```yaml
---
description: Concise technical responses
keep-coding-instructions: true
---
- Be concise and direct
- Use bullet points over paragraphs
- Include code examples when helpful
- Skip pleasantries and filler
```

| Property | Description |
|----------|-------------|
| `description` | Short description of the style |
| `keep-coding-instructions` | Preserve coding-related instructions when this style is active |

## Configuration

| Location | Scope |
|----------|-------|
| `~/.claude/output-styles/` | User styles |
| `.claude/output-styles/` | Project styles |

## Tips

- Enable **keep-coding-instructions** to preserve code formatting rules while changing the response tone.
- Use project-scoped styles to enforce consistent output within a team.
