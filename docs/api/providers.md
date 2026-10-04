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

### Operating Catalog and Readiness

```http
GET /api/v1/providers/{provider_id}/operations
GET /api/v1/providers/{provider_id}/operations?team_id=1&slot_id=2
```

Schema version `1` keeps `operations`, `native_capabilities`, `native_surfaces` and `readiness` separate. The existing registry/status/capability responses remain unchanged. Every provider has these exact operation keys:

| Operation | Claude / Codex | Copilot / OpenCode | Pi |
| --- | --- | --- | --- |
| `launch` | conditional | conditional | conditional |
| `observe_session` | conditional | conditional | conditional |
| `mail_identity` | conditional | conditional | conditional |
| `receive_work` | conditional | conditional | conditional |
| `report_work_status` | conditional | conditional | conditional |
| `approval_participation` | conditional | conditional | conditional |
| `workspace_association` | conditional | conditional | conditional |
| `resume_exact` | conditional | conditional | conditional |
| `interactive_terminal` | conditional | conditional | conditional |
| `execution_controls` | conditional | unknown | unsupported |

Each classification includes `reason`, `conditions` and checked-in `evidence` references. Conditions retain current authenticated identity, dispatch/lease/approval, exact resume/project and native execution-control limits. Classifications describe support rather than grant authority or certify isolation.

Each `native_surfaces` entry supplies `state` (`available`, `unavailable`, `unknown`), `adapter_id`, `access` (`none`, `read_only`, `read_write`), reason and conditions. Unavailable/unknown surfaces have no adapter and no access. Available IDs must match the implemented provider/page/component registry; capability flags alone cannot create a page. Browser guards intersect this catalog with the static adapter and native capabilities before mounting, fetching or writing. Required catalog failure cannot fall back to static permissions. The exact known-provider operations GET is the read-only bootstrap exception; it does not allow mutations or arbitrary catalog-provided API paths.

Readiness separates configuration checks from credentials and session identity. Configuration uses the binary/Mail prerequisites shared with launch planning; `ready` means **Configured for launch**, not verified model access. Negative legacy Mail observations can represent failed probes; the check remains unknown even when missing positive evidence blocks launch. Credentials are not checked and remain unknown. The generic request never establishes a team-slot worker binding.

Optional `team_id` and `slot_id` must be paired positive integers. A scoped read validates the configured provider, exactly one authenticated member matching both team and slot, all conflicting live MCP candidates before provider selection, observed provider, heartbeat and exact non-retired pane PID/process-start evidence. Unpaired/invalid input returns 422; missing/mismatched slot context or unknown provider returns 404. Ambiguous, stale, offline or unavailable evidence cannot become a bound session. Reads use team-scoped SQL evidence and do not discover processes, claim work, launch sessions or mutate lifecycle state.

`observed_at`, `observation_started_at`, `probe_state`, cache TTL, request wait and aggregate deadline expose observation limits. One singleflight snapshot worker per API process shares safe allowlisted flags across cards for 60 seconds; each request waits at most two seconds. At the 90-second observation deadline a private Linux supervisor terminates only the trusted observer-owned process group and reaps its children before snapshot completion or refresh. Cleanup time is awaited, not guaranteed to finish at exactly 90 seconds. Unsupported cleanup support, malformed observations and failures project to unknown. Local version/runtime/MCP-inventory checks perform no model calls, credential checks/refreshes or production-session launches; public responses contain no raw install status, private errors, host paths or output. The cleanup is not containment of hostile/self-detaching processes.

Reviewed schema fixtures are in `backend/tests/fixtures/provider-operations/v1` and their byte-identical frontend copy; they are separate from frozen P01 and P02 fixtures. New full-head review, hosted CI and human merge remain distinct from source/fixture acceptance.

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
