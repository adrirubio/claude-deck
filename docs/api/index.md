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

## API Documentation

FastAPI generates interactive API docs at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

## Route Modules

| Module | Prefix | Description |
|--------|--------|-------------|
| [Config](/api/config) | `/config` | Configuration management |
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
| [CC Bridge](/api/cc-bridge) | `/cc-bridge` | Live terminal monitoring |
| [Usage](/api/usage) | `/usage` | Token usage tracking |
| [Memory](/api/memory) | `/memory` | Memory hierarchy |
| [Backup](/api/backup) | `/backup` | Configuration backups |
