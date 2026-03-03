# Plans API

Browse and search implementation plans.

## Endpoints

### List Plans

```http
GET /api/v1/plans?project_path={path}
```

**Response:**

```json
{
  "plans": [
    {
      "filename": "2026-03-03-feature-plan.md",
      "title": "Feature Plan",
      "created_at": "2026-03-03",
      "size_bytes": 12345
    }
  ],
  "total": 10
}
```

### Get Plan Stats

```http
GET /api/v1/plans/stats?project_path={path}
```

Returns statistics about plans (total count, etc.).

### Search Plans

```http
GET /api/v1/plans/search?q={query}&project_path={path}
```

Search plans by title or content.

### Get Plan Detail

```http
GET /api/v1/plans/{filename}?project_path={path}
```

Returns full plan content with linked sessions.
