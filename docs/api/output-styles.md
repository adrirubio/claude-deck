# Output Styles API

Manage custom output formatting styles.

## Endpoints

### List Styles

```http
GET /api/v1/output-styles?project_path={path}
```

**Response:**

```json
{
  "output_styles": [
    {
      "name": "concise",
      "scope": "user",
      "description": "Short, direct responses",
      "keep_coding_instructions": true,
      "content": "Be concise and direct..."
    }
  ]
}
```

### Get Style

```http
GET /api/v1/output-styles/{scope}/{name}?project_path={path}
```

### Create Style

```http
POST /api/v1/output-styles?project_path={path}
```

```json
{
  "name": "concise",
  "scope": "user",
  "description": "Short responses",
  "keep_coding_instructions": true,
  "content": "Be concise and direct."
}
```

### Update Style

```http
PUT /api/v1/output-styles/{scope}/{name}?project_path={path}
```

### Delete Style

```http
DELETE /api/v1/output-styles/{scope}/{name}?project_path={path}
```
