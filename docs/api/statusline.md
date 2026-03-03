# Status Line API

Configure the terminal status bar.

## Endpoints

### Get Config

```http
GET /api/v1/statusline
```

**Response:**

```json
{
  "type": "command",
  "command": "~/.claude/statusline.sh",
  "padding": 0,
  "enabled": true,
  "script_content": "#!/usr/bin/env bash\n..."
}
```

### Update Config

```http
PUT /api/v1/statusline
```

```json
{ "enabled": true, "padding": 0 }
```

### Get Presets

```http
GET /api/v1/statusline/presets
```

### Apply Preset

```http
POST /api/v1/statusline/apply-preset/{preset_id}
```

### Save Custom Script

```http
POST /api/v1/statusline/script
```

Body: raw script content as string.

### Preview Script

```http
POST /api/v1/statusline/preview
```

```json
{ "script": "#!/usr/bin/env bash\necho 'test'" }
```

### Check Node.js

```http
GET /api/v1/statusline/check-nodejs
```

Returns `{ "available": true, "version": "v20.10.0" }`

### Get Powerline Presets

```http
GET /api/v1/statusline/powerline-presets
```

### Apply Powerline Preset

```http
POST /api/v1/statusline/apply-powerline/{preset_id}
```
