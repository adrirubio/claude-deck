# Plugins API

Manage plugin installation, marketplace browsing, and updates.

## Installed Plugins

### List Plugins

```http
GET /api/v1/plugins?project_path={path}
```

### Get Plugin

```http
GET /api/v1/plugins/{name}?project_path={path}
```

### Install Plugin

```http
POST /api/v1/plugins/install
```

```json
{
  "name": "my-plugin",
  "marketplace_name": "official",
  "scope": "user"
}
```

### Toggle Plugin

```http
POST /api/v1/plugins/{name}/toggle
```

```json
{ "enabled": true, "source": "local" }
```

### Uninstall Plugin

```http
DELETE /api/v1/plugins/{name}?project_path={path}
```

### Check Updates

```http
GET /api/v1/plugins/updates
```

### Update Plugin

```http
POST /api/v1/plugins/{name}/update
```

### Update All

```http
POST /api/v1/plugins/update-all
```

### Validate Plugin

```http
POST /api/v1/plugins/validate
```

```json
{ "path": "/path/to/plugin" }
```

## Marketplaces

### List Marketplaces

```http
GET /api/v1/plugins/marketplaces
```

### Add Marketplace

```http
POST /api/v1/plugins/marketplaces
```

```json
{ "input": "owner/repo" }
```

### Remove Marketplace

```http
DELETE /api/v1/plugins/marketplaces/{name}
```

### Browse Marketplace

```http
GET /api/v1/plugins/marketplace/{name}/browse
```

### Get Marketplace Plugin

```http
GET /api/v1/plugins/marketplace/{marketplace_name}/plugin/{plugin_name}
```

### Get All Available

```http
GET /api/v1/plugins/available
```
