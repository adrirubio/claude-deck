# Memory API

Manage memory hierarchy, rules, auto-memory, and imports.

## Memory Files

### Get Hierarchy

```http
GET /api/v1/memory/hierarchy?project_path={path}
```

Returns all memory files organized by scope.

### Get File

```http
GET /api/v1/memory/file?file_path={path}&include_imports={bool}
```

**Response:**

```json
{
  "path": "/home/user/.claude/CLAUDE.md",
  "exists": true,
  "content": "# My Instructions\n...",
  "imports": ["./coding-standards.md"],
  "frontmatter": null
}
```

### Save File

```http
PUT /api/v1/memory/file?file_path={path}
```

```json
{ "content": "# Updated instructions\n..." }
```

### Delete File

```http
DELETE /api/v1/memory/file?file_path={path}
```

## Rules

### List Rules

```http
GET /api/v1/memory/rules?project_path={path}
```

### Create Rule

```http
POST /api/v1/memory/rules?project_path={path}
```

```json
{
  "name": "typescript-rules",
  "content": "Use strict TypeScript.",
  "paths": ["src/**/*.ts"],
  "description": "TypeScript formatting rules"
}
```

## Auto-Memory

### List Auto-Memory Files

```http
GET /api/v1/memory/auto-memory?project_path={path}
```

## Imports

### Resolve Import Tree

```http
GET /api/v1/memory/imports?file_path={path}
```

Returns the full import dependency tree with cycle detection.
