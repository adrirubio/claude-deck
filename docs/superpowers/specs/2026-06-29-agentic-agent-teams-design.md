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

There are **three distinct silent-drop paths**, all toxic for agentic generation where the caller can't see the resulting tmux command: (1) unknown `launch_options` keys filtered out by `_clean_launch_options()` before launch (a typoed agent-generated key vanishes); (2) recognized keys a provider's `build_spawn_command` ignores (codex + `reasoning_effort`); (3) wrong env injected for a provider (OpenCode + Bedrock, see §3). The design treats all three as first-class.

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

**The shim is single-purpose.** `_request()` is hardwired to `API = f"{DECK_URL}/api/v1/agent-mail"` (`agent_mail_server.py:13,48`) and every existing tool posts relative to that prefix. Adding team tools is therefore **not** a simple path addition — it requires a prefix-aware request helper (see §6d). This is a real architectural constraint, not a detail.

---

## 3. Capability Matrix — declared vs. honored

For each provider, what `build_spawn_command` (argv) and `build_platform_env` (env) actually do with the relevant `SpawnCommandOptions` fields.

| Field | claude-code | codex-cli | copilot-cli | opencode-cli |
|---|---|---|---|---|
| `model` | (worktree/resume focus) | `--model` ✓ | `--model` ✓ | `--model` ✓ |
| `profile` | — | `--profile` ✓ | — | — |
| `platform=bedrock` (argv) | env-only | `--config model_provider="amazon-bedrock"` ✓ | — | ❌ none |
| `bedrock_model` | via env `ANTHROPIC_MODEL` | used as effective `--model` ✓ | — | ❌ |
| `aws_profile` / `aws_region` (env) | ✓ via `build_platform_env` | ✓ via `build_platform_env` | — | ⚠️ **falls through to Claude-Code branch** |
| `reasoning_effort` | — | ❌ **silently ignored** | `--effort` ✓ | ❌ **raises** |
| `context_tier` | — | — | `--context` ✓ | — |
| `agent` | — | — | `--agent` ✓ | `--agent` ✓ |

References: `providers/codex_cli.py:80-121`, `providers/copilot_cli.py` (`build_spawn_command`), `providers/opencode_cli.py:62-91`, `providers/platform_env.py:27-58`.

**Reading of the matrix:**
- **Copilot CLI is the reference implementation** — it already consumes `reasoning_effort` (`--effort`) and `context_tier` (`--context`). The pattern to copy exists in-repo.
- **Codex silently ignores `reasoning_effort`** — `build_spawn_command` never reads it. No error, no flag. Most dangerous failure mode for agentic generation: the agent believes it set xhigh; the session runs at default.
- **OpenCode hard-rejects `reasoning_effort`** — `opencode_cli.py:66` raises `"OpenCode TUI launch does not support model variants"`. Lines 76-77 then try to emit `--variant <reasoning_effort>`, but that branch is **unreachable dead code** behind the earlier raise.
- **OpenCode gets the *wrong* Bedrock env, not none** — this is the most important correction in this spec. Tracing `build_platform_env` (`platform_env.py:38-57`) for `opencode-cli` + `platform=bedrock`: it sets `AWS_REGION`/`AWS_PROFILE`, then the early `if provider_id == PROVIDER_CODEX_CLI: return env` does **not** fire (opencode ≠ codex), so execution falls through to the Claude-Code branch and injects `CLAUDE_CODE_USE_BEDROCK=1` plus (if a model is given) `ANTHROPIC_MODEL`. So an OpenCode session receives **Claude-Code-specific env vars it should never see**, while OpenCode's own `build_spawn_command` emits no Bedrock routing. G3 is therefore *"wrong provider-specific Bedrock env for non-Codex/non-Claude providers,"* not *"missing env wiring."* The fix shape and the mandatory regression test (§6c) differ accordingly: this is a correctness bug, and the same fallthrough affects **any** future non-Claude/non-Codex provider (copilot included) the moment it is given `platform=bedrock`.

---

## 4. The Target Roster, Mapped

| Slot | Provider | Model | Platform / creds | Thinking | Works today? |
|---|---|---|---|---|---|
| **Architect** | `opencode-cli` | Opus 4.8 | Bedrock + jrubio AWS profile | xhigh | ❌ **No** — opencode gets *wrong* Bedrock env (G3) **and** raises on `reasoning_effort` (G2). |
| **Lead dev** | `codex-cli` | GPT-5.5 (OpenAI Pro) | OpenAI (default platform) | xhigh | ⚠️ **Partial** — model + OpenAI auth fine; xhigh **silently dropped** (G1). |
| **Reviewer** | `codex-cli` | `openai.gpt-5.5` | Bedrock + jrubio AWS profile | xhigh | ⚠️ **Partial** — Bedrock routing + AWS profile + model work; xhigh **silently dropped** (G1). |

**Correction to an earlier assumption:** the reviewer slot ("codex + AWS profile + GPT-5.5") is **valid**, not contradictory. Codex's Bedrock path fronts OpenAI models — `NewSessionDialog.tsx:184` literally placeholders the codex Bedrock model id as `openai.gpt-5.5`, and `codex_cli.py:86` injects `model_provider="amazon-bedrock"`. So GPT-5.5 served through a Bedrock-compatible gateway under the jrubio profile is a supported shape, **provided** the AWS account/gateway actually exposes that model. This depends on account configuration (see §8), so the validation layer (G5) should warn, not hard-block, on `provider=codex + platform=bedrock + non-anthropic model`.

**The model-identity problem (G7).** The target prompt names models by product label — "Opus 4.8", "OpenAI Pro GPT-5.5" — but every spawn path needs a concrete, provider-specific **model ID** (`openai.gpt-5.5`, an Anthropic Bedrock ARN/alias, etc.). There is no name→ID resolution anywhere, and the only catalog endpoint that exists is **Codex-only** (`GET /providers/{id}/launch-options` → `CodexConfigService().get_launch_options()`, `backend/app/api/v1/providers.py:157`). For agentic creation to be reliable, an agent needs one of: (a) documented exact model IDs per provider/platform to send, (b) a provider-aware model catalog endpoint it can query, or (c) validation/warnings that distinguish a *malformed/unknown* model ID from an *account-specifically-unavailable* one. This is tracked as a new gap **G7** (§5) with design in §6f.

**Net:** the only slot that fully works today is none of them — every slot needs at least the reasoning-effort fix; the architect needs three fixes; and all three require knowing the concrete model ID to send (G7).

---

## 5. Gaps (severity-tagged)

| ID | Gap | Severity | Evidence |
|---|---|---|---|
| **G1** | Codex `build_spawn_command` silently ignores `reasoning_effort` | **High** (silent wrong-config) | `providers/codex_cli.py:80-121` |
| **G2** | OpenCode raises on `reasoning_effort`; `--variant` branch is dead code | **High** (blocks architect slot) | `providers/opencode_cli.py:66,76-77` |
| **G3** | OpenCode (and any non-Claude/non-Codex provider) gets **wrong** Bedrock env (`CLAUDE_CODE_USE_BEDROCK`/`ANTHROPIC_MODEL`) via Claude-Code fallthrough | **High** (blocks architect slot; correctness bug) | `providers/platform_env.py:46-57` |
| **G4** | No agentic (MCP) write surface to create/launch teams; shim `_request` is Agent-Mail-only | **High** (defeats the "agentic" goal) | `mcp_shim/agent_mail_server.py:13,48` |
| **G5a** | Unknown `launch_options` keys silently dropped before launch | **Medium** (typoed agent options vanish) | `agent_team_service.py:1211` |
| **G5b** | No provider-specific `launch_mode` validation; UI/API accept modes a provider rejects | **Medium** (error pushed to launch planning) | `codex_cli.py:81`, `opencode_cli.py:63`, `copilot_cli.py:59` |
| **G5c** | No semantic validation of incoherent slots (effort on unsupporting provider, bedrock w/o creds, etc.) | **Medium** (agent gets silent-wrong session) | `_clean_launch_options` filters keys only |
| **G6** | Team slot editor is a raw JSON textarea — no structured/validated UI for model/platform/effort/mode | **Medium** (no parity with bridge UI) | `AgentTeamsPage.tsx:339,352` |
| **G7** | No model name→ID resolution; only catalog endpoint is Codex-only | **High** (agentic creation can't turn "Opus 4.8" into a spawnable ID) | `backend/app/api/v1/providers.py:157` |

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
- **Validation:** restrict to the **already-established** Codex effort set used by the settings UI — `low`/`medium`/`high`/`xhigh`. Do **not** introduce `minimal` or any other value unless the installed Codex or its official config contract confirms it (the earlier draft of this spec speculated `minimal`; that was unverified — dropped). Reject unknown values with a clear `ValueError`.
- **Shared vocabulary:** this effort set is currently duplicated risk across three places — the spawn provider (G1), the Codex settings editor, and the new team editor (G6). Define it **once** (a backend constant exposed via the capability/options contract of G7/§6f) and have all consumers read from it, rather than re-typing the literals.
- **Tests:** extend `backend/tests/.../providers` codex spawn tests to assert the `--config model_reasoning_effort="xhigh"` token appears; add a rejection test for an invalid value.

### 6b. OpenCode reasoning effort (G2)

- **File:** `backend/app/services/providers/opencode_cli.py:62-91`.
- **Evidence:** the installed `opencode 1.17.11 --help` lists `--model`, `--agent`, `--prompt`, `--continue`, `--session` and **no `--variant`**. So the dead `--variant` branch (lines 76-77) targets a flag that does not exist in this environment. **b2 is the expected path.**
- **Change (b2, preferred):** keep rejecting `reasoning_effort` for OpenCode, but (1) delete the unreachable `--variant` dead code, and (2) make the rejection explicit and machine-readable so G5c validation and the MCP tool surface it cleanly — e.g. raise with a stable `block_code = "reasoning_effort_unsupported"`. Document that OpenCode TUI-launched slots cannot pin a thinking mode in this environment.
- **Change (b1, only if proven):** *if* a newer OpenCode is confirmed to support a variant/effort flag (verify with `opencode --help` on the actual target box, not docs alone), remove the early raise and emit the real flag, mapping the shared effort vocabulary to OpenCode's variant names. **Do not ship b1 on assumption** — the current evidence says b1 is wrong here.
- **Consequence for the roster:** under b2, the architect slot **cannot** honor "xhigh thinking" on OpenCode. Flag this to the user as a capability limit, not a bug to fix — the alternative is switching the architect slot to a provider that supports effort (codex/copilot) or accepting default reasoning.
- **Tests:** assert the explicit rejection + `block_code`; assert the `--variant` token is no longer emitted.

### 6c. OpenCode Bedrock env — fix the Claude-Code fallthrough (G3)

This is a **correctness fix**, not an additive one. Today the function leaks `CLAUDE_CODE_USE_BEDROCK=1`/`ANTHROPIC_MODEL` into any non-codex provider via fallthrough (see §3). OpenCode resolves providers/models through its own config + the standard AWS SDK credential chain, so the lever is environment variables, not a CLI flag.

- **File:** `backend/app/services/providers/platform_env.py:27-58`.
- **Change:** restructure the provider dispatch so the Claude-Code-specific block (`CLAUDE_CODE_USE_BEDROCK`, `ANTHROPIC_MODEL`) is reached **only for `claude-code`**, not by fallthrough. Make provider handling explicit/whitelisted rather than "codex returns early, everyone else gets Claude env." Add an `opencode-cli` branch that exports only `AWS_REGION` / `AWS_PROFILE` (non-secret) and whatever explicit Bedrock signal OpenCode actually needs — to be confirmed (§8): if OpenCode selects Bedrock purely via its config file + model-id prefix, env-only region/profile suffices and the model is pinned via the existing `--model` arg.
- **Constraint:** keep the module's invariant — **never** handle secrets here; only non-secret region/profile/model id. Creds resolve from the host AWS chain.
- **Decision gate:** §8 — confirm how OpenCode selects a Bedrock model (config key vs env vs model-id prefix).
- **Tests:**
  - extend `platform_env` tests with an `opencode-cli` + bedrock case asserting the *expected* env;
  - **regression test (mandatory):** assert `opencode-cli` + bedrock does **NOT** receive `CLAUDE_CODE_USE_BEDROCK` or `ANTHROPIC_MODEL`. Add the equivalent assertion for `copilot-cli` so the fallthrough cannot silently re-appear for any future provider.

### 6d. Agentic MCP write surface (G4)

**Prerequisite — generalize the shim's request helper.** `_request()` is hardwired to the Agent-Mail prefix (`API = .../api/v1/agent-mail`, `agent_mail_server.py:13,48`), so team tools cannot reuse it as-is. First refactor to a prefix-aware helper, e.g. `_deck_request(method, api_prefix, path, **kwargs)`, and express the existing mail tools as `_deck_request("…", "agent-mail", …)` (or keep a thin `_mail_request` wrapper for them). Team tools then call `_deck_request(..., "agent-teams", ...)`. Without this, the first implementation will post team payloads to `/agent-mail/...` and 404.

- **File:** `backend/mcp_shim/agent_mail_server.py`.
- **New tools:**
  - `deck_create_team(name, description, slots)` → `POST /api/v1/agent-teams/presets`. `slots` is a list of `{display_name, provider, repo_path, role?, charter?, launch_mode?, launch_options?}`. Returns the created preset (ids + per-slot echo, including any validation `warnings`).
  - `deck_plan_team_launch(preset_id)` → `POST /presets/{id}/plan-launch`. Returns the plan **and** its `plan_hash` so the agent/user can review before committing.
  - `deck_launch_team(preset_id, confirm_plan_hash, reuse_existing=True)` → `POST /presets/{id}/launch`. **Plan confirmation is required by default:** the tool takes `confirm_plan_hash` and forwards it; it must **not** default to `skip_plan_confirmation=true`. A caller wanting to bypass confirmation must pass an explicit, conspicuously-named argument (e.g. `force_without_plan=True`) that maps to the REST `skip_plan_confirmation`. This mirrors the REST safety contract (`AgentTeamLaunchRequest.confirm_plan_hash` / `skip_plan_confirmation`) rather than quietly relaxing it.
  - (optional) `deck_list_teams()` → `GET /presets`.
- **Validation:** the tool docstrings must enumerate valid `provider` ids and which `launch_options` keys each provider honors (derived from §3 and the capability contract of §6f), so the calling agent fills them correctly. Surface backend 400s (from G5) and slot `warnings` back to the agent verbatim.
- **Tests:** extend `backend/tests/agent_mail/test_mcp_shim.py` with: prefix-helper routing (team tool hits `/agent-teams`, mail tool still hits `/agent-mail`), create/plan/launch happy-path, launch-without-confirm-hash rejection, and a validation-error passthrough.

### 6e. Slot validation layer (G5a / G5b / G5c)

Give the agent (and UI) fast, clear feedback instead of a silently-wrong session. The three sub-gaps are distinct contract checks; implement them together but keep them individually testable.

- **File:** `backend/app/services/agent_team_service.py` (add `_validate_slot_options(provider, launch_mode, launch_options)` called from `add_slot` / `update_slot` / preset create). Reuse the existing `_validate_spawn_options` which already round-trips `build_spawn_command` (`agent_team_service.py:995`) — extend it to run semantic checks, not just argv construction.
- **G5a — unknown option keys:** validate keys **before** `_clean_launch_options()` drops them (`agent_team_service.py:1211`). Unknown keys are a **hard error** for agentic/MCP and structured-UI writes (so a typoed `reasoning_efort` fails loudly), unless the caller is in the explicit raw-JSON advanced mode (§7b).
- **G5b — provider/launch_mode:** reject a `launch_mode` the selected provider's `build_spawn_command` rejects. Concretely: opencode/copilot support `{plain, resume}`; codex supports `{plain, resume, fork}`; claude-code additionally supports `worktree`. Source these from a single per-provider mode map shared with the frontend (§7c), not hardcoded twice.
- **G5c — semantic coherence:**
  - `reasoning_effort` on a provider that cannot honor it (opencode under b2) → reject with `reasoning_effort_unsupported`.
  - `reasoning_effort` value outside the per-provider accepted set (codex `low/medium/high/xhigh`) → reject.
  - `platform=bedrock` without `aws_region`/`aws_profile` and no ambient default → **warn** (creds may resolve from host chain).
  - `provider=codex + platform=bedrock + model not `anthropic.*`` → **warn** ("requires a Bedrock account/gateway that exposes this model"; see §4).
- **Warning channel — explicit schema decision (do not add ad hoc):**
  - Warnings are **non-persisted and recomputed**, never stored on the slot row. The DB stays the source of *intent*; warnings are *derived* from current intent + provider capabilities, so they can't go stale against code changes.
  - On **create/update** responses: compute and attach a transient `warnings: string[]` per slot in the response model (not a DB column).
  - On **launch plan items** (`AgentTeamLaunchPlanItem`): warnings **are included in `plan_hash`** so that `confirm_plan_hash` proves the agent/user reviewed exactly the warnings shown. Hard-blocking validation errors prevent plan generation entirely (the slot can't be saved), so they never reach the hash.
- **Surface:** hard failures → `HTTP 400` via `_bad_request` (already wired). Warnings → the `warnings` fields above.
- **Tests:** one unit test per rule (G5a/b/c), plus a test asserting a warning changes `plan_hash`.

### 6f. Model identity & provider capability contract (G7)

Agentic creation starts from product names ("Opus 4.8", "GPT-5.5") but spawn needs concrete IDs, and the only catalog today is Codex-only (`providers.py:157`). Rather than scatter model knowledge, give the backend one authoritative contract that both the MCP tools and the frontend consume.

- **Backend — generalize the launch-options/capability endpoint.** Extend `GET /providers/{provider_id}/launch-options` beyond Codex so each provider returns its own capability descriptor: supported `launch_mode`s, whether it honors `reasoning_effort` and the accepted effort set, whether it supports Bedrock, and a **model catalog** (known model IDs + optional default) where the provider can supply one. For providers without a queryable catalog, return documented example IDs (e.g. codex Bedrock → `openai.gpt-5.5`; Anthropic Bedrock → the ARN/alias form) rather than nothing.
- **Single source of truth.** The effort vocabulary (§6a), per-provider mode map (§6b/§6e-G5b), and Bedrock-support flags all live here and are read by: the spawn providers, the validation layer (G5), the MCP tool docstrings (§6d), and the frontend (§7). No re-typing literals in three files.
- **Name→ID resolution is explicitly out of scope as auto-magic.** Claude Deck will **not** guess that "Opus 4.8" means a specific ARN. Instead it (a) documents/serves the concrete IDs to send, and (b) at validation time distinguishes a *malformed/unknown* model ID (reject) from a *well-formed but account-unavailable* one (warn — Claude Deck can't verify account entitlements). This keeps the agent honest: it must supply a real ID, and it gets a clear signal which kind of wrong it is.
- **Tests:** per-provider launch-options shape; codex catalog still returns its existing content (no regression); validation distinguishes malformed vs. unavailable model IDs.

---

## 7. Full Design — Frontend

Goal: the team slot editor reaches parity with `NewSessionDialog`, so everything the post-change API accepts is reachable in the UI (not only via curl/MCP).

### 7a. Extract a shared launch-options component

- **New file:** `frontend/src/features/providers/ProviderLaunchOptionsFields.tsx` (or `cc-bridge/` shared subfolder).
- **Source + gaps:** lift the structured controls from `NewSessionDialog.tsx` (Platform select, AWS region/profile, Bedrock model, model dropdown/custom, copilot effort + context-tier, opencode model/agent) — **but note the dialog is not a complete reference.** It only sends `reasoning_effort` for Copilot (not Codex), and exposes no OpenCode Bedrock controls. So this is **extract + extend**: the shared component must *add* (a) a codex reasoning-effort control (pairs with §6a) and (b) OpenCode Bedrock controls (pairs with §6c), neither of which exists today.
- **Props:** `provider`, `value` (a typed launch-options object), `onChange`, and the provider capability descriptor from §6f (supported modes, effort set, bedrock support, model catalog). Keep it controlled and provider-agnostic; conditional rendering keyed off the descriptor, not hardcoded per-provider branches.
- **Refactor:** `NewSessionDialog` then consumes this same component, eliminating divergence (single source of truth for "which fields for which provider"), and gains codex-effort/opencode-bedrock for free.

### 7b. Replace the raw-JSON textarea in the slot editor

- **File:** `frontend/src/features/agent-teams/AgentTeamsPage.tsx` (slot form around lines 339-352, 371-417).
- **Change:** render `<ProviderLaunchOptionsFields>` bound to the slot's `launch_options`. Keep the existing raw-JSON textarea as a collapsible **"Advanced (raw JSON)"** escape hatch, two-way synced with the structured fields, for power users / forward-compat with options the UI doesn't model yet.

### 7c. Provider-conditional rendering

- **Effort/thinking control:** shown for codex and copilot; hidden for claude-code; hidden for opencode under b2 (with a short "OpenCode can't pin thinking mode" hint rather than a dead control).
- **Bedrock block:** shown per provider that supports it (claude-code, codex, and — after G3 — opencode). For codex, model placeholder `openai.gpt-5.5` and platform label `OpenAI`, mirroring `NewSessionDialog.tsx:179,184`.
- **Launch mode (new):** the mode dropdown (`AgentTeamsPage.tsx:409-418` currently offers `plain/worktree/resume/fork` to *all* providers) must be filtered to the selected provider's supported set (§6f map). This stops the editor from offering `worktree`/`fork` to opencode/copilot (which reject them at `build_spawn_command`), moving the error from launch-planning back to edit time.
- **Shared vocabularies:** effort set, mode map, and bedrock-support all come from the §6f backend descriptor — frontend never re-declares the literals.

### 7d. Surface validation errors/warnings (pairs with G5)

- Show backend `400` detail inline on the offending field.
- Render slot-level `warnings[]` (e.g. GPT-5.5-via-Bedrock account caveat) as non-blocking inline notices.

### 7e. Types

- **File:** `frontend/src/types/agentTeams.ts`.
- **Change:** replace `launch_options: Record<string, unknown>` usage in the editor with a typed `SlotLaunchOptions` interface (`model?`, `platform?`, `aws_region?`, `aws_profile?`, `bedrock_model?`, `reasoning_effort?`, `context_tier?`, `agent?`, `profile?`, …) shared with the new component. Add `warnings?: string[]` to the slot/launch response types (matching §6e).
- **Contract ownership (important):** TypeScript types help only the frontend — they do nothing for MCP/curl callers. The **authoritative** provider capability/options contract lives in the backend (§6f) and is served at runtime. The frontend *consumes* that descriptor (or shares generated/static constants derived from the same source). Do not let the TS interface become a second, drifting source of truth for what providers accept.

---

## 8. Open Questions / Risks

1. **~~Does `opencode --variant` exist?~~ Resolved (mostly).** `opencode 1.17.11 --help` does **not** list `--variant` (only `--model`, `--agent`, `--prompt`, `--continue`, `--session`). So G2 takes path **b2** (reject + delete dead code). Re-open only if a newer OpenCode on the actual target box proves an effort/variant flag — verify with `--help`, not docs.
2. **How does OpenCode select a Bedrock model?** Config key, env var, or model-id prefix? Decides the exact G3 change (the env-only branch vs. an explicit signal). Verify against OpenCode docs / `opencode models` / `opencode providers`.
3. **Codex reasoning-effort vocabulary.** Use the **established** set `low`/`medium`/`high`/`xhigh` (matches the Codex settings UI). Confirm against the installed Codex before adding any other value — the earlier `minimal` guess was unverified and has been dropped.
4. **GPT-5.5 via Bedrock availability.** The codex+Bedrock+`openai.gpt-5.5` shape is only usable if the jrubio AWS account/gateway exposes that model. This is account config, outside Claude Deck — hence G5/G7 *warn* (well-formed but maybe-unavailable) rather than block.
5. **Codex auth coexistence.** Lead dev (OpenAI Pro) and reviewer (Bedrock) are both codex but different auth/platform per slot. Confirm per-session env (`AWS_PROFILE` injected via tmux `-e`) cleanly overrides without polluting the OpenAI-Pro slot. The spawn path sets env per session (`spawn.py:74-80`), so this should hold — worth an integration check.
6. **Per-provider model catalogs (G7).** Which providers can actually serve a queryable catalog vs. only documented examples? Determines how much of §6f is live data vs. static documentation.

---

## 9. Out of Scope

- Implementing any of §6/§7 (this is a design spec only).
- Net-new pages or navigation. The frontend work reuses the existing Agent Teams page and bridge dialog.
- Secret/credential handling — unchanged; creds always resolve from the host AWS chain.
- A natural-language "team designer" prompt template. Once G4 exists, the calling agent composes slots directly; a canned prompt is a separate, optional follow-up.
