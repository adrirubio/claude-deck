# MCP Servers API

Manage MCP server connections, test connectivity, and browse the registry.

## Server Management

### List Servers

```http
GET /api/v1/mcp/servers?project_path={path}
```

Returns all configured MCP servers across user and project scopes.

**Response:**

```json
{
  "servers": [
    {
      "name": "postgres",
      "type": "stdio",
      "scope": "user",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "disabled": false,
      "tools": [...],
      "resources": [...],
      "prompts": [...]
    }
  ]
}
```

### Get Server

```http
GET /api/v1/mcp/servers/{name}?scope={scope}&project_path={path}
```

### Add Server

```http
POST /api/v1/mcp/servers?project_path={path}
```

**Request Body:**

```json
{
  "name": "my-server",
  "type": "stdio",
  "scope": "user",
  "command": "node",
  "args": ["server.js"],
  "env": { "API_KEY": "..." }
}
```

Types: `stdio`, `http`, `sse`

### Update Server

```http
PUT /api/v1/mcp/servers/{name}?scope={scope}&project_path={path}
```

### Delete Server

```http
DELETE /api/v1/mcp/servers/{name}?scope={scope}&project_path={path}
```

### Toggle Server

```http
POST /api/v1/mcp/servers/{name}/toggle
```

```json
{ "disabled": true }
```

## Testing

### Test Server

```http
POST /api/v1/mcp/servers/{name}/test?scope={scope}&project_path={path}
```

Tests connectivity and discovers tools, resources, and prompts. 30-second timeout.

### Test All Servers

```http
POST /api/v1/mcp/servers/test-all?project_path={path}
```

Tests all servers sequentially, returns results for each.

## OAuth

### Check Auth Status

```http
GET /api/v1/mcp/servers/{name}/auth-status?scope={scope}
```

### Start OAuth Flow

```http
POST /api/v1/mcp/servers/{name}/auth/start?scope={scope}
```

Returns `{ "auth_url": "...", "state": "..." }`

### OAuth Callback

```http
GET /api/v1/mcp/auth/callback?code={code}&state={state}
```

## Approval Settings

### Get Settings

```http
GET /api/v1/mcp/approval-settings
```

### Update Settings

```http
PUT /api/v1/mcp/approval-settings
```

```json
{
  "default_mode": "ask-every-time",
  "server_overrides": { "postgres": "always-allow" }
}
```

## Registry

### Search

```http
GET /api/v1/mcp/registry/search?q={query}&limit={limit}
```

### Get Server Details

```http
GET /api/v1/mcp/registry/servers/{name}/versions/{version}
```

### Install from Registry

```http
POST /api/v1/mcp/registry/install?project_path={path}
```

```json
{
  "server_name": "postgres",
  "scope": "user",
  "package_registry_type": "npm",
  "package_identifier": "@modelcontextprotocol/server-postgres"
}
```
