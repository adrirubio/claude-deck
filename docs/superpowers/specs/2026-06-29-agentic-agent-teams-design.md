# Agentic Agent Teams — Capability Gap Analysis & Design

**Status:** Investigation / design spec (no implementation committed)
**Date:** 2026-06-29
**Target version:** post-2.0.0
**Scope:** Can the Claude Deck Agent Teams API faithfully express, and can an external agent generate, a roster where each slot pins a specific CLI tool × provider/platform × model × thinking (reasoning) mode? What backend, MCP, and frontend changes would close the gaps?

---

## 1. Problem & Motivation

We want to create Agent Teams **agentically** — tell an agent (Claude Code, Codex CLI, OpenCode, etc.) to call the Claude Deck API and generate a team configuration from a prompt. A representative target roster:

> Generate a SnazzyEmail team:
> - **Architect** — OpenCode instance, Amazon Bedrock (jrubio AWS profile), Opus 4.8, xhigh thinking.
> - **Lead developer** — Codex CLI instance, OpenAI Pro GPT-5.5, xhigh reasoning.
> - **Reviewer / QA** — Codex CLI instance (jrubio AWS profile), GPT-5.5, xhigh reasoning.

The open question this spec answers: **does the API actually support all of these knobs per slot**, and if not, what would it take? The conclusion is that the *schema* is a superset of what is actually honored downstream — several fields are silently dropped or hard-rejected at spawn time — and there is no agentic write surface for teams at all. Both backend and frontend need work.

---

## 2. Current Architecture (as-is)

### 2.1 Backend launch path

A saved team is an `AgentTeamPreset` containing ordered `AgentTeamSlot` rows. Each slot carries a freeform `launch_options` JSON blob. The launch pipeline:

```
AgentTeamSlot.launch_options (Dict[str, Any], DB JSON column)
  └─ _clean_launch_options()         # filter to SpawnCommandOptions field names
       └─ _spawn_options_for_slot()  # build SpawnCommandOptions dataclass
            └─ spawn_session()        # agent_bridge/spawn.py
                 ├─ provider.build_spawn_command(options)   # per-provider argv
                 └─ build_platform_env(...)                 # Bedrock/AWS env vars
                      └─ tmux new-session -e KEY=VAL ... <command>
```

Key references:
- `backend/app/models/database.py:155` — `launch_options` is a nullable JSON column.
- `backend/app/services/agent_team_service.py:1211` — `_clean_launch_options()` keeps only keys that match `SpawnCommandOptions` field names (`_OPTION_FIELDS`).
- `backend/app/services/agent_team_service.py:1002` — `_spawn_options_for_slot()` maps the cleaned dict onto `SpawnCommandOptions`.
- `backend/app/services/agent_team_service.py:553-564` — team launch calls `spawn_session()` with team env vars.
- `backend/app/services/agent_bridge/spawn.py:64-74` — builds argv via the provider, then computes `build_platform_env()` from `options.platform/aws_region/aws_profile/bedrock_model`.
- `backend/app/services/providers/base.py:18-49` — `SpawnCommandOptions` dataclass (the field whitelist).

### 2.2 `SpawnCommandOptions` — the declared field surface

`providers/base.py:18` declares (abridged): `directory`, `mode`, `model`, `profile`, `profile_v2`, `sandbox`, `approval_policy`, `platform` (default `"anthropic"`), `aws_region`, `aws_profile`, `bedrock_model`, `agent`, `context_tier`, `reasoning_effort`, `plan`, `remote`, plus permission flags.

**This is the trap:** a field existing here does **not** mean a given provider's `build_spawn_command` emits it, nor that `build_platform_env` acts on it. The dataclass is the union of all providers' needs; each provider honors a subset.

### 2.3 Two frontend surfaces — inconsistent

- **`frontend/src/features/cc-bridge/NewSessionDialog.tsx`** (single-session bridge spawn) — fully structured, provider-aware controls: Platform select (`anthropic`/`bedrock`), AWS region/profile inputs, Bedrock model field, codex model dropdown, copilot effort/context-tier selects. This is the **reference UI**. Notably its codex Bedrock model placeholder is `openai.gpt-5.5` (line 184) and the default-platform label for codex is `OpenAI` (line 179).
- **`frontend/src/features/agent-teams/AgentTeamsPage.tsx`** (team slot editor) — `launch_options` is edited as a **raw JSON textarea** (`launchOptionsText` / `parseLaunchOptions`, lines 339/352). No structured controls, no validation, no provider-conditional fields.

### 2.4 No agentic write surface for teams

The MCP shim `backend/mcp_shim/agent_mail_server.py` exposes only Agent **Mail** coordination tools: `deck_whoami`, `deck_list_team`, `deck_check_inbox`, `deck_send_message`, `deck_reply`, `deck_ack_message`, `deck_request_context`, `deck_create_handoff`. There is **no** `deck_create_team` / `deck_launch_team`. Creating or launching a team is **REST-only** (`backend/app/api/v1/agent_teams.py`: `POST /presets`, `POST /presets/{id}/slots`, `POST /presets/{id}/launch`). So "tell an agent to use the Claude Deck API" today means the agent shells out to `curl` — it cannot do this through a tool call.

---

## 3. Capability Matrix — declared vs. honored

For each provider, what `build_spawn_command` (argv) and `build_platform_env` (env) actually do with the relevant `SpawnCommandOptions` fields.

| Field | claude-code | codex-cli | copilot-cli | opencode-cli |
|---|---|---|---|---|
| `model` | (worktree/resume focus) | `--model` ✓ | `--model` ✓ | `--model` ✓ |
| `profile` | — | `--profile` ✓ | — | — |
| `platform=bedrock` (argv) | env-only | `--config model_provider="amazon-bedrock"` ✓ | — | ❌ none |
| `bedrock_model` | via env `ANTHROPIC_MODEL` | used as effective `--model` ✓ | — | ❌ |
| `aws_profile` / `aws_region` (env) | ✓ via `build_platform_env` | ✓ via `build_platform_env` | — | ❌ **returns `{}`** |
| `reasoning_effort` | — | ❌ **silently ignored** | `--effort` ✓ | ❌ **raises** |
| `context_tier` | — | — | `--context` ✓ | — |
| `agent` | — | — | `--agent` ✓ | `--agent` ✓ |

References: `providers/codex_cli.py:80-121`, `providers/copilot_cli.py` (`build_spawn_command`), `providers/opencode_cli.py:62-91`, `providers/platform_env.py:27-58`.

**Reading of the matrix:**
- **Copilot CLI is the reference implementation** — it already consumes `reasoning_effort` (`--effort`) and `context_tier` (`--context`). The pattern to copy exists in-repo.
- **Codex silently ignores `reasoning_effort`** — `build_spawn_command` never reads it. No error, no flag. Most dangerous failure mode for agentic generation: the agent believes it set xhigh; the session runs at default.
- **OpenCode hard-rejects `reasoning_effort`** — `opencode_cli.py:66` raises `"OpenCode TUI launch does not support model variants"`. Lines 76-77 then try to emit `--variant <reasoning_effort>`, but that branch is **unreachable dead code** behind the earlier raise.
- **OpenCode has no Bedrock support** — `build_platform_env` returns `{}` unless `platform == bedrock`, and even then only emits env for `claude-code` and `codex-cli` (`platform_env.py:50-57`). For `opencode-cli` it returns the bare region/profile dict with no provider-routing var, and `opencode build_spawn_command` emits no Bedrock routing flag.

---

## 4. The Target Roster, Mapped

| Slot | Provider | Model | Platform / creds | Thinking | Works today? |
|---|---|---|---|---|---|
| **Architect** | `opencode-cli` | Opus 4.8 | Bedrock + jrubio AWS profile | xhigh | ❌ **No** — opencode has no Bedrock env (G3) **and** raises on `reasoning_effort` (G2). |
| **Lead dev** | `codex-cli` | GPT-5.5 (OpenAI Pro) | OpenAI (default platform) | xhigh | ⚠️ **Partial** — model + OpenAI auth fine; xhigh **silently dropped** (G1). |
| **Reviewer** | `codex-cli` | `openai.gpt-5.5` | Bedrock + jrubio AWS profile | xhigh | ⚠️ **Partial** — Bedrock routing + AWS profile + model work; xhigh **silently dropped** (G1). |

**Correction to an earlier assumption:** the reviewer slot ("codex + AWS profile + GPT-5.5") is **valid**, not contradictory. Codex's Bedrock path fronts OpenAI models — `NewSessionDialog.tsx:184` literally placeholders the codex Bedrock model id as `openai.gpt-5.5`, and `codex_cli.py:86` injects `model_provider="amazon-bedrock"`. So GPT-5.5 served through a Bedrock-compatible gateway under the jrubio profile is a supported shape, **provided** the AWS account/gateway actually exposes that model. This depends on account configuration (see §8), so the validation layer (G5) should warn, not hard-block, on `provider=codex + platform=bedrock + non-anthropic model`.

**Net:** the only slot that fully works today is none of them — every slot needs at least the reasoning-effort fix; the architect needs three fixes.

---

## 5. Gaps (severity-tagged)

| ID | Gap | Severity | Evidence |
|---|---|---|---|
| **G1** | Codex `build_spawn_command` silently ignores `reasoning_effort` | **High** (silent wrong-config) | `providers/codex_cli.py:80-121` |
| **G2** | OpenCode raises on `reasoning_effort`; `--variant` branch is dead code | **High** (blocks architect slot) | `providers/opencode_cli.py:66,76-77` |
| **G3** | OpenCode has no Bedrock/AWS env wiring | **High** (blocks architect slot) | `providers/platform_env.py:50-57`; no routing flag in `opencode_cli.py` |
| **G4** | No agentic (MCP) write surface to create/launch teams | **High** (defeats the "agentic" goal) | `mcp_shim/agent_mail_server.py` exposes mail tools only |
| **G5** | No validation rejecting/ warning on incoherent slots | **Medium** (agent gets silent-wrong session) | `_clean_launch_options` only filters keys; no semantic checks |
| **G6** | Team slot editor is a raw JSON textarea — no structured/validated UI for model/platform/effort | **Medium** (no parity with bridge UI) | `AgentTeamsPage.tsx:339,352` |

---

## 6. Full Design — Backend

### 6a. Codex reasoning effort (G1)

Codex already accepts repeated `--config key=value` (that is exactly how Bedrock routing is injected). `model_reasoning_effort` is a known Codex config key (`backend/app/services/codex_config_service.py:23`). So:

- **File:** `backend/app/services/providers/codex_cli.py`, in `build_spawn_command`.
- **Change:** after the existing `--config model_provider=...` block, add:
  ```python
  if options.reasoning_effort:
      command += ["--config", f'model_reasoning_effort="{options.reasoning_effort}"']
  ```
- **Validation:** restrict to Codex's accepted set (`minimal`/`low`/`medium`/`high`/`xhigh` — confirm against installed Codex, see §8). Reject unknown values with a clear `ValueError`.
- **Tests:** extend `backend/tests/.../providers` codex spawn tests to assert the `--config model_reasoning_effort="xhigh"` token appears; add a rejection test for an invalid value.

### 6b. OpenCode reasoning effort (G2)

- **File:** `backend/app/services/providers/opencode_cli.py:62-91`.
- **Change:** resolve the raise-vs-`--variant` contradiction. Two options:
  - **(b1, preferred if `opencode --variant` is real)** Remove the early `raise` at line 66; keep the `--variant` emission at lines 76-77; map the effort vocabulary to OpenCode's variant names if they differ (e.g. `xhigh` → opencode's highest variant).
  - **(b2, if `--variant` is NOT a real flag)** Keep rejecting, but make the error explicit and machine-readable so G5 validation and the MCP tool surface it cleanly (e.g. `block_code = "reasoning_effort_unsupported"`), and document that opencode slots cannot pin thinking mode.
- **Decision gate:** §8 open question — verify against the installed `opencode` CLI before choosing b1 vs b2. **Do not ship b1 on assumption.**
- **Tests:** assert chosen behavior; remove the now-unreachable-code smell.

### 6c. OpenCode Bedrock env (G3)

OpenCode resolves providers/models through its own config + standard AWS SDK credential chain, so the lever is environment variables, not a CLI flag.

- **File:** `backend/app/services/providers/platform_env.py:27-58`.
- **Change:** add an `opencode-cli` branch. At minimum export `AWS_REGION` / `AWS_PROFILE` (already partially done by the shared region/profile block). Determine whether OpenCode needs an explicit "use bedrock" signal analogous to `CLAUDE_CODE_USE_BEDROCK=1`; if OpenCode selects Bedrock purely via its config file + model id prefix, then env-only region/profile is sufficient and the model is pinned via the existing `--model` arg.
- **Constraint:** keep the module's invariant — **never** handle secrets here; only non-secret region/profile/model id. Creds resolve from the host AWS chain.
- **Decision gate:** §8 — confirm how OpenCode selects a Bedrock model (config key vs env vs model-id prefix). 
- **Tests:** extend `platform_env` tests with an `opencode-cli` + bedrock case.

### 6d. Agentic MCP write surface (G4)

Add team create/launch tools to the shim, thin wrappers over existing REST endpoints (the shim already calls the backend via `_request`).

- **File:** `backend/mcp_shim/agent_mail_server.py`.
- **New tools:**
  - `deck_create_team(name, description, slots)` → `POST /api/v1/agent-teams/presets`. `slots` is a list of `{display_name, provider, repo_path, role?, charter?, launch_mode?, launch_options?}`. Returns the created preset (ids + per-slot echo).
  - `deck_launch_team(preset_id, reuse_existing=True, confirm_plan_hash?)` → `POST /presets/{id}/launch` (optionally `plan-launch` first to return the plan for confirmation).
  - (optional) `deck_list_teams()` → `GET /presets`, and `deck_plan_team_launch(preset_id)` → `POST /presets/{id}/plan-launch`.
- **Validation:** the tool docstrings must enumerate valid `provider` ids and which `launch_options` keys each provider honors (derived from §3), so the calling agent fills them correctly. Surface backend 400s (from G5) back to the agent verbatim.
- **Tests:** extend `backend/tests/agent_mail/test_mcp_shim.py` with create/launch happy-path and a validation-error passthrough.

### 6e. Slot validation layer (G5)

Give the agent (and UI) fast, clear feedback instead of a silently-wrong session.

- **File:** `backend/app/services/agent_team_service.py` (add a `_validate_slot_options(provider, launch_options)` called from `add_slot` / `update_slot` / preset create). Reuse the existing `_validate_spawn_options` which already round-trips `build_spawn_command` (`agent_team_service.py:995`) — extend it to run semantic checks, not just argv construction.
- **Rules (initial):**
  - Unknown `provider` → reject (already done by `_validate_provider`).
  - `reasoning_effort` set on a provider that cannot honor it (opencode if b2 chosen) → reject with `reasoning_effort_unsupported`.
  - `reasoning_effort` value outside the per-provider accepted set → reject.
  - `platform=bedrock` without `aws_region`/`aws_profile` and no ambient default → **warn** (not block), since creds may resolve from the host chain.
  - `provider=codex + platform=bedrock + model not starting anthropic.*` → **warn** ("requires a Bedrock account/gateway that exposes this model"), not block (see §4 correction).
- **Surface:** validation failures already become `HTTP 400` via `_bad_request`. Warnings need a channel — return them in the create/launch response (e.g. a `warnings: []` field on `AgentTeamSlotResponse` or the launch plan items) so the MCP tool and UI can show them.
- **Tests:** unit tests per rule.

---

## 7. Full Design — Frontend

Goal: the team slot editor reaches parity with `NewSessionDialog`, so everything the post-change API accepts is reachable in the UI (not only via curl/MCP).

### 7a. Extract a shared launch-options component

- **New file:** `frontend/src/features/providers/ProviderLaunchOptionsFields.tsx` (or `cc-bridge/` shared subfolder).
- **Source:** lift the structured controls from `NewSessionDialog.tsx` — Platform select, AWS region/profile inputs, Bedrock model field, model dropdown/custom, copilot effort + context-tier, opencode model/agent.
- **Props:** `provider`, `value` (a typed launch-options object), `onChange`, and capability/model option data (the dialog already fetches codex launch options). Keep it controlled and provider-agnostic; conditional rendering keyed off `provider`.
- **Refactor:** `NewSessionDialog` then consumes this same component, eliminating divergence (single source of truth for "which fields for which provider").

### 7b. Replace the raw-JSON textarea in the slot editor

- **File:** `frontend/src/features/agent-teams/AgentTeamsPage.tsx` (slot form around lines 339-352, 371-417).
- **Change:** render `<ProviderLaunchOptionsFields>` bound to the slot's `launch_options`. Keep the existing raw-JSON textarea as a collapsible **"Advanced (raw JSON)"** escape hatch, two-way synced with the structured fields, for power users / forward-compat with options the UI doesn't model yet.

### 7c. Provider-conditional rendering

- Effort/thinking control: shown for codex, copilot, and (pending §8/b1) opencode; hidden for claude-code.
- Bedrock block: shown per provider that supports it (claude-code, codex, and — after G3 — opencode). For codex, model placeholder `openai.gpt-5.5` and platform label `OpenAI`, mirroring `NewSessionDialog.tsx:179,184`.
- Effort vocabulary per provider comes from a single shared map so backend (G1/G5) and frontend agree on the accepted set.

### 7d. Surface validation errors/warnings (pairs with G5)

- Show backend `400` detail inline on the offending field.
- Render slot-level `warnings[]` (e.g. GPT-5.5-via-Bedrock account caveat) as non-blocking inline notices.

### 7e. Types

- **File:** `frontend/src/types/agentTeams.ts`.
- **Change:** replace `launch_options: Record<string, unknown>` usage in the editor with a typed `SlotLaunchOptions` interface (`model?`, `platform?`, `aws_region?`, `aws_profile?`, `bedrock_model?`, `reasoning_effort?`, `context_tier?`, `agent?`, `profile?`, …) shared with the new component. Add `warnings?: string[]` to the slot/launch response types if G5 adds them.

---

## 8. Open Questions / Risks

1. **Does `opencode --variant <effort>` actually exist?** Decides G2 b1 vs b2. Verify against the installed `opencode` CLI (`opencode --help`) before implementing. The current code both rejects and (unreachably) emits it — someone was unsure too.
2. **How does OpenCode select a Bedrock model?** Config key, env var, or model-id prefix? Decides the exact G3 change. Verify against OpenCode docs/`opencode models`/`opencode providers`.
3. **Codex reasoning-effort vocabulary.** Confirm the accepted set for `model_reasoning_effort` on the installed Codex (`minimal`/`low`/`medium`/`high`/`xhigh`?) so G1/G5 validate against reality.
4. **GPT-5.5 via Bedrock availability.** The codex+Bedrock+`openai.gpt-5.5` shape is only usable if the jrubio AWS account/gateway exposes that model. This is account config, outside Claude Deck — hence G5 warns rather than blocks.
5. **Codex auth coexistence.** Lead dev (OpenAI Pro) and reviewer (Bedrock) are both codex but different auth/platform per slot. Confirm per-session env (`AWS_PROFILE` injected via tmux `-e`) cleanly overrides without polluting the OpenAI-Pro slot. The spawn path sets env per session (`spawn.py:74-80`), so this should hold — worth an integration check.

---

## 9. Out of Scope

- Implementing any of §6/§7 (this is a design spec only).
- Net-new pages or navigation. The frontend work reuses the existing Agent Teams page and bridge dialog.
- Secret/credential handling — unchanged; creds always resolve from the host AWS chain.
- A natural-language "team designer" prompt template. Once G4 exists, the calling agent composes slots directly; a canned prompt is a separate, optional follow-up.
