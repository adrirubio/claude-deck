# Permissions API

Manage allow/ask/deny permission rules.

## Endpoints

### List Rules

```http
GET /api/v1/permissions?project_path={path}
```

**Response:**

```json
{
  "rules": [
    { "id": "abc123", "type": "allow", "pattern": "Bash(npm run *)", "scope": "user" }
  ],
  "settings": {
    "defaultMode": "default",
    "additionalDirectories": [],
    "disableBypassPermissionsMode": false
  }
}
```

### Get Rules by Scope

```http
GET /api/v1/permissions/scope/{scope}?project_path={path}
```

### Add Rule

```http
POST /api/v1/permissions?project_path={path}
```

```json
{ "type": "allow", "pattern": "Bash(npm run *)", "scope": "user" }
```

### Update Rule

```http
PUT /api/v1/permissions/{rule_id}?scope={scope}&project_path={path}
```

```json
{ "type": "deny", "pattern": "Write(*.env)" }
```

### Delete Rule

```http
DELETE /api/v1/permissions/{rule_id}?scope={scope}&project_path={path}
```

### Update Settings

```http
PUT /api/v1/permissions/settings?scope={scope}&project_path={path}
```

```json
{
  "defaultMode": "conservative",
  "additionalDirectories": ["/tmp/workspace"],
  "disableBypassPermissionsMode": true
}
```
