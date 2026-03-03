# Commands API

Manage slash commands across user and project scopes.

## Endpoints

### List Commands

```http
GET /api/v1/commands?project_path={path}
```

**Response:**

```json
{
  "commands": [
    {
      "name": "review",
      "path": "review.md",
      "scope": "user",
      "description": "Code review",
      "allowed_tools": ["Read", "Grep"],
      "content": "Review the current changes..."
    }
  ]
}
```

### Get Command

```http
GET /api/v1/commands/{scope}/{path}?project_path={path}
```

### Create Command

```http
POST /api/v1/commands?project_path={path}
```

**Request Body:**

```json
{
  "name": "review",
  "scope": "user",
  "description": "Code review",
  "allowed_tools": ["Read", "Grep", "Glob"],
  "content": "Review the current changes for bugs and issues."
}
```

### Update Command

```http
PUT /api/v1/commands/{scope}/{path}?project_path={path}
```

**Request Body:**

```json
{
  "description": "Updated description",
  "allowed_tools": ["Read"],
  "content": "Updated content"
}
```

### Delete Command

```http
DELETE /api/v1/commands/{scope}/{path}?project_path={path}
```
