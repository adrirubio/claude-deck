# Agent Bridge — Platform selection (Anthropic / Bedrock)

**Date:** 2026-05-29
**Status:** Design — pending implementation
**Scope:** Add a per-session platform picker (Anthropic default / Amazon Bedrock) to the Agent Bridge "New Session" dialog for the Claude Code provider, injecting the appropriate Bedrock environment variables into the spawned `claude` process.

## Problem

The Agent Bridge spawns `claude` inside a tmux session (`backend/app/services/agent_bridge/spawn.py`). Today it calls `tmux new-session` **without passing any environment**, so the session simply inherits the backend server's environment. There is no way, from the UI, to start a session against Amazon Bedrock rather than the default Anthropic API. Running Claude Code against Bedrock requires setting `CLAUDE_CODE_USE_BEDROCK=1` plus AWS configuration (region, optionally profile and model) in the process environment.

The user wants to select **Bedrock vs. Anthropic** when starting an Agent Bridge session.

## Decisions (locked)

- **Credential source: inherit from the server.** Claude Deck never collects or stores AWS secrets. Selecting Bedrock sets non-secret env vars (`CLAUDE_CODE_USE_BEDROCK`, region, profile name, model ID) and lets the AWS SDK credential chain on the backend host resolve actual credentials (env vars, `~/.aws/credentials` profile, or instance role).
- **Bedrock fields exposed:** AWS Region, AWS Profile name, Model ARN/ID. All optional.
- **Vertex:** out of scope for now. The design leaves the door open via a single env-builder map so Vertex can be added later without reworking the plumbing.
- **Remember last selection:** yes — persist the last-used platform and its (non-secret) field values in browser `localStorage` so the dialog pre-fills next time. No backend persistence change.

## Approach

A `platform` enum plus a provider-side env builder.

1. The dialog gains a **Platform** selector for the Claude Code provider: `Anthropic` (default) or `Amazon Bedrock`.
2. Selecting Bedrock reveals three optional inputs: **AWS Region**, **AWS Profile**, **Model ARN/ID**.
3. On spawn, the backend translates the platform choice into a `dict[str, str]` of environment variables and injects them into the tmux session via `tmux new-session -e KEY=VALUE` (one `-e` per variable).
4. `Anthropic` produces an **empty** env map → the tmux command is byte-for-byte identical to today (full backward compatibility).

### Env mapping (Bedrock)

| Setting | Env var | Condition |
|---|---|---|
| (platform = bedrock) | `CLAUDE_CODE_USE_BEDROCK=1` | always when Bedrock |
| AWS Region | `AWS_REGION=<value>` | if provided |
| AWS Profile | `AWS_PROFILE=<value>` | if provided |
| Model ARN/ID | `ANTHROPIC_MODEL=<value>` | if provided |

### Alternatives considered (rejected)

- **settings.json `env` only** — Claude Code already reads `env` from settings.json, so Bedrock vars could be set globally there with zero code. Rejected: it is global, not the per-session picker requested, and the spawn path never sets a custom env anyway.
- **Store AWS keys in Claude Deck** (typed per session, or saved profiles) — rejected in favor of inherit-from-server, which is safer (no secret storage) and simpler.

## Components & data flow

### Backend

- **`backend/app/services/providers/platform_env.py` (new)**
  - Constants: `PLATFORM_ANTHROPIC = "anthropic"`, `PLATFORM_BEDROCK = "bedrock"`.
  - `build_platform_env(platform, region, aws_profile, model) -> dict[str, str]`:
    - Anthropic → `{}`.
    - Bedrock → `{"CLAUDE_CODE_USE_BEDROCK": "1", ...}` adding region/profile/model only when set.
    - Defensive validation: reject values containing `\n` or `\0`; skip empty/whitespace-only values.
  - Single extension point for a future Vertex platform.

- **`backend/app/services/providers/base.py`** — add four frozen-dataclass fields to `SpawnCommandOptions`:
  `platform: str = "anthropic"`, `aws_region: str | None = None`, `aws_profile: str | None = None`, `bedrock_model: str | None = None`.
  A distinct `bedrock_model` (not the existing Codex-only `model`) avoids overloading semantics and keeps the Anthropic Claude Code spawn untouched.

- **`backend/app/services/agent_bridge/spawn.py`** — in `spawn_session`:
  - Call `build_platform_env(...)` from the options.
  - Insert `-e KEY=VALUE` argv elements into the `tmux new-session` call (after `-c <dir>`, before the shell command, so the fixed `-d -s <name> -c <dir>` prefix is unchanged). Empty env → unchanged command.
  - Store `platform` in `_spawned_sessions[name]` metadata for visibility. Never log AWS values.

- **`backend/app/api/v1/agent_bridge/router.py`** — add the four fields to `SpawnRequest` and pass them through when constructing `SpawnCommandOptions`.

### Frontend

- **`frontend/src/features/cc-bridge/types.ts`** — add `platform?`, `aws_region?`, `aws_profile?`, `bedrock_model?` to `SpawnSessionRequest`.
- **`frontend/src/features/cc-bridge/NewSessionDialog.tsx`** — for the Claude Code provider:
  - A **Platform** `<Select>` (Anthropic / Amazon Bedrock), defaulting to Anthropic.
  - When Bedrock is selected, conditionally render Region / Profile / Model inputs (mirroring the existing Codex-only conditional fields), with a hint that region is usually required.
  - **Remember last selection:** read/write `localStorage` (e.g. key `cc-bridge.platform`) holding `{platform, aws_region, aws_profile, bedrock_model}` — **non-secret values only** — to pre-fill on open.

### Flow

Dialog → `SpawnSessionRequest` (with platform fields) → `POST` spawn → `SpawnRequest` → `SpawnCommandOptions` → `spawn_session` → `build_platform_env` → `tmux new-session -e ...` → `claude` runs in a tmux session whose environment carries the Bedrock vars; the AWS SDK resolves credentials from the inherited chain.

## Error handling & validation

- **Injection safety:** values are passed as separate argv elements to `tmux -e KEY=VALUE`, never shell-interpolated, so there is no quoting/injection risk. `build_platform_env` additionally rejects values with `\n`/`\0`.
- **Optional fields:** Region/profile/model are optional even for Bedrock. Bedrock with no region sets only `CLAUDE_CODE_USE_BEDROCK=1`; Claude Code / the AWS SDK surface their own "no region" error inside the tmux session. We do not duplicate AWS-side validation client-side.
- **No credential handling** in the path — nothing to leak, log, or persist. Logs record `platform=bedrock` but no AWS values.
- **Backward compatibility:** omitting `platform` defaults to `"anthropic"`; Anthropic yields an empty env map and the current tmux command.

## Testing

- **Backend (pytest):**
  - `build_platform_env`: Anthropic → `{}`; Bedrock with all fields; Bedrock with only region; defensive rejection of `\n`/`\0` and empty values.
  - `spawn_session`: mock `subprocess.run`; assert `-e` flags appear in the tmux argv for Bedrock, and that Anthropic produces no `-e` flags.
- **Frontend:** no test harness exists yet (per CLAUDE.md); rely on `tsc` + ESLint and manual verification.
- **Manual:** Anthropic session unchanged; Bedrock session on an AWS-credentialed host starts on Bedrock; dialog pre-fills the last selection.

## Out of scope (YAGNI)

- Google Vertex AI (door left open via the env-builder map).
- Storing AWS secrets or named credential profiles in Claude Deck.
- Database persistence of bridge sessions (they remain in-memory).
- Editing settings.json from this feature.

## Files to change

| File | Change |
|---|---|
| `backend/app/services/providers/platform_env.py` | **New** — platform constants + `build_platform_env()` |
| `backend/app/services/providers/base.py` | +4 fields on `SpawnCommandOptions` |
| `backend/app/services/agent_bridge/spawn.py` | Build env, inject `-e` flags, store `platform` metadata |
| `backend/app/api/v1/agent_bridge/router.py` | +4 fields on `SpawnRequest`, pass through |
| `backend/tests/` | New tests for env builder + spawn argv |
| `frontend/src/features/cc-bridge/types.ts` | +4 fields on `SpawnSessionRequest` |
| `frontend/src/features/cc-bridge/NewSessionDialog.tsx` | Platform select + conditional Bedrock fields + localStorage remember |

## Workflow

Feature → GitHub issue + `feat/agent-bridge-bedrock-platform` branch + PR against `master`.
