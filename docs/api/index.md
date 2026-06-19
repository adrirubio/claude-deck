# API Overview

Claude Deck exposes a RESTful API under `/api/v1/`. The frontend communicates with the backend entirely through this API.

## Base URL

```
http://localhost:8000/api/v1
```

In development, the Vite dev server proxies `/api` requests from port 5173 to the backend at port 8000.

## Authentication

None. Claude Deck is a local-only application — no authentication is required.

## Request/Response Format

All request and response bodies use JSON. Set `Content-Type: application/json` for requests with bodies.

## Common Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `project_path` | string | Optional. Project directory path for project-scoped resources. |
| `scope` | string | `user`, `project`, `plugin`, or `managed` — depends on the endpoint. |

## Error Handling

| Status | Meaning |
|--------|---------|
| `200` | Success |
| `201` | Resource created |
| `204` | Deleted (no content) |
| `400` | Validation error |
| `404` | Resource not found |
| `500` | Server error |

Error responses return JSON with a `detail` field:

```json
{
  "detail": "Resource not found"
}
```

Provider-aware endpoints may also map failures into normalized states such as unsupported capability, missing binary, unavailable CLI command, CLI failure, parse failure, or validation failure. Sensitive CLI stdout/stderr and raw provider payloads should be redacted or omitted before they are returned.

## API Documentation

FastAPI generates interactive API docs at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

## Route Modules

| Module | Prefix | Description |
|--------|--------|-------------|
| [Config](/api/config) | `/config` and `/codex-config` | Configuration management |
| [Providers](/api/providers) | `/providers` | Provider metadata, status, diagnostics, and inventory |
| [MCP Servers](/api/mcp) | `/mcp` | MCP server management |
| [Commands](/api/commands) | `/commands` | Slash commands |
| [Plugins](/api/plugins) | `/plugins` | Plugin management |
| [Hooks](/api/hooks) | `/hooks` | Event hooks |
| [Permissions](/api/permissions) | `/permissions` | Access control rules |
| [Agents](/api/agents) | `/agents` | Agents and skills |
| [Sessions](/api/sessions) | `/sessions` | Session transcripts |
| [Context](/api/context) | `/context` | Context window analysis |
| [Plans](/api/plans) | `/plans` | Implementation plans |
| [Output Styles](/api/output-styles) | `/output-styles` | Response formatting |
| [Status Line](/api/statusline) | `/statusline` | Terminal status bar |
| [Agent Bridge](/api/agent-bridge) | `/agent-bridge` | Provider-aware live terminal monitoring |
| [Agent Mail](/api/agent-mail) | `/agent-mail` and `/external/agent-mail` | Local agent mailbox coordination and external same-machine orchestration |
| [Agent Teams](/api/agent-teams) | `/agent-teams` | Saved agent rosters, launch planning, and team slot context |
| [CC Bridge](/api/cc-bridge) | `/cc-bridge` | Legacy Claude Code terminal monitoring route |
| [Usage](/api/usage) | `/usage` | Token usage tracking |
| [Memory](/api/memory) | `/memory` | Memory hierarchy |
| [Backup](/api/backup) | `/backup` | Configuration backups |
