# Providers API

Provider endpoints expose installed agent CLI metadata, capabilities, diagnostics, and safe provider-specific command surfaces.

## Endpoints

### List Providers

```http
GET /api/v1/providers
```

Returns registered providers such as `claude-code` and `codex-cli`, including install status, version, capabilities, and config paths.

### Provider Status

```http
GET /api/v1/providers/{provider_id}/status
```

Returns status for one provider.

### Codex Doctor

```http
GET /api/v1/providers/codex-cli/doctor
```

Runs Codex diagnostics and returns redacted output.

### Codex Inventory

```http
GET /api/v1/providers/codex-cli/inventory
```

Returns read-only Codex MCP and plugin inventory. Secret-like values are redacted.

### Codex MCP Mutation

```http
POST /api/v1/providers/codex-cli/mcp
DELETE /api/v1/providers/codex-cli/mcp/{name}
```

Adds or removes Codex MCP servers through the Codex CLI with strict validation. Plugin mutation remains read-only in this version.
