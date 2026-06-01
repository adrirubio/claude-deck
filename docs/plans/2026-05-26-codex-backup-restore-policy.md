# Codex Backup/Export/Restore Policy

Date: 2026-05-26
Issue: #142

## Decision

Codex backups are export-only. Claude Deck may create and download a redacted
Codex export, but it must not automatically restore Codex files until there is a
stable provider-owned restore path.

## Export Scope

Codex exports include:

- `config.toml` with secret-like assignments redacted
- `*.config.toml` profile files with secret-like assignments redacted
- `rules/*.rules` files with secret-like assignments redacted
- redacted provider inventory metadata

Codex exports exclude:

- `auth.json`
- `history.jsonl`
- `models_cache.json`
- `*.sqlite` files and related SQLite sidecars
- raw cache payloads and prompt text

## Restore Policy

Automatic Codex restore is refused with an explicit error. The restore plan
lists the archive contents for review, but the restore action returns a refusal
instead of extracting files.

Refusal reasons:

- Codex auth, history, cache, and local state are intentionally excluded from
  exports.
- Automatic restore could overwrite active Codex state without a stable
  provider-owned restore API.

Manual restore remains possible outside Claude Deck after downloading and
reviewing the redacted archive.
