# Status Line

Customize the bottom status bar in Claude Code with presets, powerline themes, or custom scripts.

## Overview

The Status Line page lets you configure what Claude Code shows at the bottom of the terminal. Choose from built-in presets, powerline themes, or write a custom bash script.

## How to Use

### Enable/Disable

Toggle the status line on or off with the switch at the top of the page.

### Presets

Four built-in presets are available:

| Preset | Shows |
|--------|-------|
| **Simple** | Model name and directory |
| **Git-Aware** | Model, directory, git branch |
| **Minimal** | Model name only |
| **Full Context** | Model, directory, git branch, context usage |

Click **Preview** to see rendered output with mock data before applying. Click **Apply** to activate.

### Powerline Themes

Six powerline themes with styled separators and colors:

- **Dark** / **Light** / **Nord** / **Tokyo Night** / **Rose Pine** / **Gruvbox**

::: info
Powerline themes require Node.js 18+ (uses `npx @owloops/claude-powerline`).
:::

### Custom Script

Expand the "Custom Script" section to write a bash script that receives JSON context via stdin:

```bash
#!/usr/bin/env bash
read -r context
model=$(echo "$context" | jq -r '.model // "unknown"')
dir=$(echo "$context" | jq -r '.cwd // "~"' | sed "s|$HOME|~|")
echo "$model | $dir"
```

The JSON context includes fields like `model`, `cwd`, `gitBranch`, `contextPercent`, and more.

### Padding

Set the padding value (0 = flush to edge, empty = default spacing) in the Configuration section.

## Configuration

Status line settings are stored in `~/.claude/settings.json` under the `statusLine` key:

```json
{
  "statusLine": {
    "enabled": true,
    "type": "command",
    "command": "~/.claude/statusline.sh",
    "padding": 0
  }
}
```

The status line script is saved to `~/.claude/statusline.sh` and made executable automatically.

## Tips

- **Preview before applying** — presets render with mock data so you can see the output.
- Custom scripts receive JSON on stdin — use `jq` to parse fields.
- Powerline themes look best in terminals that support Unicode box-drawing characters.
