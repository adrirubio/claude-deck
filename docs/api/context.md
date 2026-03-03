# Context API

Monitor context window usage across active sessions.

## Endpoints

### Get Active Sessions

```http
GET /api/v1/context/active
```

Returns recently active sessions with context window usage percentages.

**Response:**

```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "project_name": "my-project",
      "context_percentage": 72.5,
      "is_active": true
    }
  ]
}
```

### Analyze Session Context

```http
GET /api/v1/context/{project_folder}/{session_id}
```

Returns detailed context analysis for a specific session.
