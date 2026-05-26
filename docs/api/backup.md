# Backup API

Create, restore, and manage configuration backups.

## Endpoints

### List Backups

```http
GET /api/v1/backup/list
```

### Create Backup

```http
POST /api/v1/backup/create
```

```json
{
  "name": "pre-migration",
  "scope": "full",
  "description": "Backup before major config change",
  "project_path": "/path/to/project"
}
```

Use `"scope": "codex"` for a Codex export. Codex exports are redacted and export-only.

### Get Backup

```http
GET /api/v1/backup/{backup_id}
```

### Get Contents

```http
GET /api/v1/backup/{backup_id}/contents
```

Returns list of files in the backup archive.

### Get Manifest

```http
GET /api/v1/backup/{backup_id}/manifest
```

Returns full metadata including dependencies and component lists.

### Get Restore Plan

```http
GET /api/v1/backup/{backup_id}/plan?project_path={path}
```

Analyzes what will be restored and identifies missing dependencies.

### Validate Backup

```http
POST /api/v1/backup/{backup_id}/validate
```

### Download

```http
GET /api/v1/backup/{backup_id}/download
```

Returns the ZIP archive file.

### Restore

```http
POST /api/v1/backup/{backup_id}/restore?project_path={path}
```

Claude Code backups can be restored according to the restore plan. Codex backups refuse automatic restore and return an explicit failure because the archive excludes auth, history, cache, SQLite state, raw prompt text, and raw cache payloads.

### Install Dependencies

```http
POST /api/v1/backup/{backup_id}/install-dependencies
```

```json
{ "npm": true, "pip": true, "plugins": true }
```

### Delete

```http
DELETE /api/v1/backup/{backup_id}
```

### Export Config

```http
POST /api/v1/backup/export
```

```json
{
  "paths": ["~/.claude/settings.json", "~/.claude/agents/"],
  "name": "settings-export"
}
```
