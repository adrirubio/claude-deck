# Sessions

Browse Claude Code conversation transcripts with full message details and tool use.

## Overview

The Sessions page displays conversation history from Claude Code sessions stored as JSONL files. You can filter by project and browse through conversations with paginated message views.

## How to Use

### Browsing Sessions

The session list shows all recorded conversations with:

- Session date and time
- Message count
- Project name

Use the **project filter** dropdown to show sessions from a specific project or all projects.

### Viewing a Session

Click a session to open the conversation viewer. Messages are displayed in order with:

- **User messages** — your prompts
- **Assistant messages** — Claude's responses with full text
- **Tool calls** — tool name, arguments, and results
- **Content blocks** — code, text, and structured output

Conversations are paginated (5 prompts per page) for performance.

## Configuration

Sessions are read-only. Claude Code stores transcripts as JSONL files in:

```
~/.claude/projects/{project-folder}/*.jsonl
```

Claude Deck caches parsed sessions in its database with a 5-minute TTL and file hash validation for fast page loads.

## Tips

- Sessions are **read-only** — you can browse but not modify transcripts.
- The cache refreshes automatically when session files change on disk.
- Filter by project to quickly find conversations for a specific codebase.
