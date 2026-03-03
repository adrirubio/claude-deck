# Sessions API

Query session transcripts and statistics.

## Endpoints

### List Projects

```http
GET /api/v1/sessions/projects
```

Returns all projects with session counts.

### List Sessions

```http
GET /api/v1/sessions?project_folder={folder}&limit={n}&sort_by={field}&sort_order={asc|desc}
```

**Response:**

```json
{
  "sessions": [
    {
      "id": "abc123",
      "project_folder": "my-project",
      "project_name": "My Project",
      "summary": "Implemented feature X",
      "modified_at": "2026-03-03T10:00:00Z",
      "size_bytes": 45678,
      "total_messages": 24,
      "total_tool_calls": 12
    }
  ],
  "total": 150
}
```

### Get Dashboard Stats

```http
GET /api/v1/sessions/dashboard/stats
```

Returns aggregate session statistics (total sessions, messages, tool calls, average size).

### Get Session Detail

```http
GET /api/v1/sessions/{project_folder}/{session_id}?page={n}
```

Returns full session with paginated conversations (5 prompts per page).
