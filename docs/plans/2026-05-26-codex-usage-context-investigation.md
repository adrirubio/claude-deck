# Codex Usage/Context Parity Investigation

Date: 2026-05-26
Issue: #142

## Decision

Codex usage and context parity should stay diagnostics-only for now. The local
Codex files observed on this machine do not expose a stable token usage or
context-window metric surface that is safe to treat like Claude Code usage and
context data.

The backend now exposes a read-only Codex diagnostics endpoint:

- `GET /api/v1/providers/codex-cli/usage-context-diagnostics`

This endpoint returns file-shape metadata and an explicit unsupported decision.
It does not return prompt text, raw history rows, raw model cache payloads,
session ids, model ids, auth data, or cache contents.

## Safe Observations

Observed local Codex files:

- `history.jsonl`: JSONL rows include keys such as `session_id`, `ts`, and
  `text`. The `text` field is prompt content and must be treated as sensitive.
- `models_cache.json`: root keys include metadata such as `fetched_at`, `etag`,
  `client_version`, and `models`. The model list is cache data rather than a
  usage ledger.

The diagnostics endpoint reports counts, root keys, file sizes, parse status,
and whether metric-like key names are present. It intentionally omits values for
sensitive or opaque fields.

## Product Implication

Claude Code usage and context pages remain Claude-specific. Codex should not be
shown as having usage or context parity until a stable local or CLI-backed Codex
metric source exists that can be read without exposing prompt text or raw cache
payloads.
