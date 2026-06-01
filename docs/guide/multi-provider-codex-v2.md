# Multi-Provider and Codex v2

Claude Deck is moving from a Claude Code-only control surface to a provider-aware local agent dashboard. Claude Code remains the most complete provider. Codex CLI support is explicit about what is supported, what is diagnostics-only, and what is intentionally unavailable.

## Provider Model

Provider status comes from `/api/v1/providers` and `/api/v1/providers/{provider_id}/status`.

Each provider reports:

- install state, binary path, and version when available
- config paths used by the provider
- capability flags used by the API and UI
- provider-specific policy metadata, such as backup and restore behavior

Boolean capability flags stay backward-compatible: unsupported or unavailable surfaces are `false`, not omitted. Newer provider-specific details live in metadata objects so older clients can continue using the boolean flags.

## Capability Summary

| Surface | Claude Code | Codex CLI |
|---------|-------------|-----------|
| Agent Bridge tmux discovery | Supported | Supported |
| Spawn/resume/fork | Spawn and resume; no fork | Spawn, resume, and fork |
| Config editing | JSON settings, scopes, permissions | Safe TOML scalar and feature edits |
| Config/profile diagnostics | Scope resolver | Profile and profile-file diagnostics |
| MCP inventory | Claude settings/API | `codex mcp list --json` |
| MCP mutation | Claude MCP pages | CLI-backed add/remove only |
| Plugin inventory | Supported | `codex plugin list` inventory |
| Plugin install/remove | Supported | CLI-backed install/remove when supported by Codex CLI |
| Plugin enable/disable | Supported | Unsupported until Codex exposes a safe contract |
| History/session transcripts | Supported | Diagnostics-only investigation |
| Usage/context metrics | Supported | Unsupported |
| Backup/export | Backup and automatic restore | Redacted export only |
| Automatic restore | Supported | Refused |

## Codex Supported Surfaces

Codex CLI support is productized for:

- mixed-provider Agent Bridge sessions with provider filters
- provider status, version, config paths, and capability metadata
- safe TOML settings edits for whitelisted scalar and feature fields
- config/profile diagnostics, including active/default profile resolution and malformed profile reporting
- MCP inventory and CLI-backed MCP add/remove
- plugin inventory and CLI-backed plugin install/remove where the local Codex CLI supports those commands
- `codex doctor` diagnostics with secret-like values redacted
- redacted export-only backups

## Diagnostics-Only Surfaces

Some local Codex files are useful for support diagnostics but are not stable product data sources.

History and model cache diagnostics may report file existence, size, parse status, root keys, row counts, and whether metric-like key names appear. They must not return prompt text, session ids, raw history rows, model ids, raw model cache payloads, auth data, or SQLite contents.

Usage and context parity are not supported for Codex. Claude Deck should not present Codex token usage, cost, billing block, or context-window metrics until Codex exposes a stable source that can be read without sensitive prompt or cache data.

## Backup and Restore Policy

Codex backups are redacted exports, not automatic restore points.

Codex exports may include:

- `config.toml` with secret-like assignments redacted
- `*.config.toml` profile files with secret-like assignments redacted
- `rules/*.rules` files with secret-like assignments redacted
- redacted provider inventory metadata

Codex exports must exclude:

- `auth.json`
- `history.jsonl`
- `models_cache.json`
- SQLite state and SQLite sidecar files
- raw prompt text and raw cache payloads

Automatic Codex restore is refused. The restore plan can show archive contents and refusal reasons, but the restore action must not extract files into `CODEX_HOME`.

## Provider Errors

Provider-specific operations should return normalized, user-actionable errors:

- unsupported capability
- provider binary missing
- command unavailable in the installed CLI
- CLI execution failure with redacted stdout/stderr
- parse failure with raw sensitive payloads omitted or redacted
- validation failure for unsafe input

The UI should use these states to disable unsupported controls rather than routing users to Claude-only pages while Codex is selected.

## Smoke Coverage

Multi-provider smoke coverage should exercise both providers in one run:

- provider registry returns Claude Code and Codex status without requiring both binaries to be installed
- Agent Bridge can show mixed Claude Code and Codex tmux sessions together and can filter All, Claude Code, and Codex
- Codex config, doctor, MCP, plugin, history/model-cache diagnostics, and backup export paths redact sensitive values
- unsupported Codex usage/context and automatic restore states are visible and non-mutating
- Claude-only pages remain hidden or disabled when Codex is selected
