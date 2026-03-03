# Config API

Manage Claude Code configuration across all scopes.

## Endpoints

### List Config Files

```http
GET /api/v1/config/files?project_path={path}
```

Returns all configuration file paths with their existence status.

### Get Merged Config

```http
GET /api/v1/config?project_path={path}
```

Returns the merged configuration from all scopes. This is the effective configuration that Claude Code uses.

**Response:**

```json
{
  "settings": { ... },
  "mcp_servers": { ... },
  "hooks": { ... },
  "permissions": { ... },
  "commands": [ ... ],
  "agents": [ ... ]
}
```

### Get Raw File Content

```http
GET /api/v1/config/raw?path={file_path}&project_path={path}
```

Returns the raw content of a specific configuration file.

### Get Settings by Scope

```http
GET /api/v1/config/settings/{scope}?project_path={path}
```

`scope`: `user` or `project`

### Get Resolved Config

```http
GET /api/v1/config/resolved?project_path={path}
```

Returns resolved settings with the effective value and source scope for each key.

### Get All Scopes

```http
GET /api/v1/config/scopes?project_path={path}
```

Returns settings from all scopes (managed, user, project, local) without merging.

### Update Settings

```http
PUT /api/v1/config/settings
```

**Request Body:**

```json
{
  "scope": "user",
  "settings": { "model": "claude-sonnet-4-6" },
  "project_path": "/path/to/project"
}
```

### Validate Settings

```http
POST /api/v1/config/validate-settings
```

Validates permission patterns without saving.

**Request Body:**

```json
{
  "settings": { "permissions": { "allow": ["Bash(npm run *)"] } }
}
```
