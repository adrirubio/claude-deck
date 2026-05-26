# Codex History and Model Cache Investigation

**Date:** 2026-05-26  
**Status:** Decision recorded  
**Scope:** Codex CLI generated `history.jsonl` and `models_cache.json`

## Decision

Use a diagnostics-only backend surface for now. Do not add a product Codex Sessions page yet.

Local inspection shows `history.jsonl` rows with `session_id`, `ts`, and `text`. The session id and timestamp are useful, but `text` is prompt content and must be treated as sensitive. There is not enough non-sensitive metadata yet to provide a useful history UI comparable to Claude Code transcripts without exposing prompt bodies or inventing unsupported semantics.

Local inspection shows `models_cache.json` root keys including `fetched_at`, `etag`, `client_version`, and `models`. This is useful for diagnostics, but the raw model cache is generated data and should not be exposed wholesale.

## Implemented Surface

Add a read-only Codex diagnostics endpoint that summarizes:

- History file existence, size, row counts, observed keys, timestamp range, session counts, and hashed session identifiers.
- Model cache existence, size, root keys, fetch/client metadata, cache validator presence, model container shape, and model count.

The endpoint intentionally omits:

- Raw history rows.
- Prompt text.
- Raw session ids.
- Raw model cache JSON.
- Cache validator values.

## Follow-Up Criteria

A product Codex Sessions page should wait until Codex exposes stable, non-sensitive local metadata for project paths, message roles, model choices per session, and safe summaries. Until then, Claude-only transcript pages should remain Claude-only and Codex should use diagnostics-only history/cache reporting.
