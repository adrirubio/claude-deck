# Providers API

Provider endpoints expose installed agent CLI metadata, capabilities, diagnostics, and safe provider-specific command surfaces.

## Endpoints

### List Providers

```http
GET /api/v1/providers
```

Returns registered providers such as `claude-code`, `codex-cli`, and `copilot-cli`, including install status, version, capabilities, and config paths.

Capability flags are stable booleans. Unsupported provider surfaces are returned as `false`; detailed provider-specific state belongs in metadata fields such as backup policy, diagnostics, inventory, or command status.

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
GET /api/v1/providers/codex-cli/mcp
GET /api/v1/providers/codex-cli/plugins
GET /api/v1/providers/codex-cli/features
```

Returns Codex MCP, plugin, and feature inventory. Secret-like values are redacted. MCP JSON output is parsed and redacted before any raw output is returned. Plugin text output is treated as read-only text with best-effort row parsing.

Feature inventory is parsed from `codex features list` and returns the feature name, stage, and effective enabled state. Removed and deprecated flags may still be present in raw CLI output; the frontend hides those from the main toggle list unless they already exist as explicit config overrides.

### Codex MCP Mutation

```http
POST /api/v1/providers/codex-cli/mcp
DELETE /api/v1/providers/codex-cli/mcp/{name}
```

Adds or removes Codex MCP servers through the Codex CLI with strict validation.

### Codex Plugin Mutation

```http
POST /api/v1/providers/codex-cli/plugins
DELETE /api/v1/providers/codex-cli/plugins/{name}
```

Installs or removes Codex plugins through the Codex CLI when the installed CLI exposes safe commands. Codex plugin enable/disable remains unsupported until Codex exposes a stable safe contract.

### Codex Config/Profile Diagnostics

```http
GET /api/v1/codex-config
GET /api/v1/codex-config/profile-diagnostics
```

Returns redacted Codex config summaries, profile-file diagnostics, and active/default profile resolution. Auth, history, cache, and raw secret values are omitted or redacted.

### Codex Usage/Context Diagnostics

```http
GET /api/v1/providers/codex-cli/usage-context-diagnostics
```

Returns diagnostics-only metadata for Codex history and model cache shape. This endpoint does not return prompt text, session ids, raw history rows, model ids, raw model cache payloads, auth data, or SQLite contents. Usage and context parity are explicitly unsupported for Codex.

## Normalized Provider Errors

Provider endpoints should surface user-actionable error states:

| Error code/state | Meaning |
|------------------|---------|
| `unknown_provider` | The requested provider id is not registered. |
| `unsupported_operation` | The provider does not support the requested capability. |
| `unsupported_provider_operation` | The endpoint exists, but only for another provider. |
| `command_not_allowed` | The requested CLI command is outside the provider whitelist. |
| `provider_binary_missing` | The provider CLI is not installed or not on `PATH`. |
| CLI failure | The CLI returned a non-zero exit code; stdout/stderr are redacted. |
| Parse failure | CLI output could not be parsed; raw sensitive payloads are omitted or redacted. |
| Validation failure | User input failed strict validation before any CLI command ran. |

The frontend should use provider status and these error states to disable unsupported controls instead of routing Codex users to Claude-only pages.
