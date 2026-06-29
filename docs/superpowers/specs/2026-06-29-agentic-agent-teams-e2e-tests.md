# E2E Test Scenarios — Agentic Agent Teams

**Companion to:** `2026-06-29-agentic-agent-teams-design.md`
**Date:** 2026-06-29
**Audience:** the implementing agent, executing these end-to-end.
**Purpose:** verify that an agent can set up, validate, and launch Agent Teams through the Claude Deck agentic surface (MCP tools, with REST equivalents), exercising the happy paths, the validation guards, the non-blocking warnings, and the launch-safety contract delivered for G1–G7.

These are **black-box, agent-driven** scenarios — they drive the running system the way a real coordinating agent would, not unit tests. Unit/integration coverage lives in `backend/tests/`.

---

## How to run

**Primary interface — MCP tools** (the agentic surface, G4). Each scenario gives the exact tool calls. If you are an agent with the `deck_*` tools loaded, call them directly.

**Fallback interface — REST** (equivalent `curl`), for when MCP is unavailable or for cross-checking. Base URL defaults to `http://127.0.0.1:8000` (override via the `CLAUDE_DECK_URL` env var — the MCP shim reads the same variable). API prefix: `/api/v1/agent-teams`.

### Prerequisites

| Requirement | Needed by | Notes |
|---|---|---|
| Claude Deck backend running | all | `deck_whoami` must return `ok:true`, not `deck_unreachable` |
| `tmux` installed | launch scenarios (L*) | sessions spawn into tmux |
| `codex` CLI installed | scenarios using `codex-cli` | `codex --version` |
| `opencode` CLI installed (≥1.17) | scenarios using `opencode-cli` | `opencode --version` |
| AWS profile `jrubio` configured in `~/.aws` | Bedrock scenarios | non-secret region/profile only; creds resolve from host chain |
| Repos exist on disk | launch scenarios | `/home/juan/work/repos/juanrubio/snazzyemail`, `/home/juan/work/repos/juanrubio/claude-deck` |

> **Create/validation-only scenarios (D*, V*, W*) do NOT require the CLIs or AWS to be live** — they exercise validation and persistence, which run server-side before any spawn. Only the launch scenarios (L*) actually spawn tmux sessions and need the toolchain.

### Conventions

- `⇒` marks the expected result / pass criterion.
- `{preset_id}`, `{plan_hash}` are captured from a prior step's response.
- Record results in the table at the end.
- **Cleanup:** delete presets created during testing via `DELETE /api/v1/agent-teams/presets/{id}` (no MCP delete tool exists yet) and `tmux kill-session` any spawned sessions.

### Provider capability cheat-sheet (authoritative source: `launch_contract.py`)

| Provider | Launch modes | Reasoning effort | Bedrock | Notable honored `launch_options` keys |
|---|---|---|---|---|
| `claude-code` | plain, worktree, resume | — (none) | yes | platform, aws_region, aws_profile, bedrock_model |
| `codex-cli` | plain, resume, fork | low/medium/high/xhigh | yes | model, profile, reasoning_effort, platform, aws_*, bedrock_model |
| `copilot-cli` | plain, resume | none/low/medium/high/xhigh/max | **no** | model, agent, context_tier, reasoning_effort |
| `opencode-cli` | plain, resume | **unsupported (rejects)** | yes | model, agent, platform, aws_region, aws_profile |

---

## Scenario group A — Discovery & happy path

### E2E-A1 — Capability discovery before building

**Goal:** an agent inspects what each provider accepts before composing slots (the §6f contract that prevents blind silent-drops).

**Steps**
1. `GET /api/v1/providers/codex-cli/launch-options`
2. `GET /api/v1/providers/opencode-cli/launch-options`
3. `GET /api/v1/providers/copilot-cli/launch-options`
4. `GET /api/v1/providers/claude-code/launch-options`

**⇒ Pass criteria**
- All four return `200` with a descriptor containing: `supported_launch_modes`, `supported_launch_options`, `bedrock_supported`, `reasoning_effort_supported`, `reasoning_effort_options`, `model_options`/`model_examples`.
- `codex-cli`: `reasoning_effort_supported: true`, options end with `xhigh`; `bedrock_supported: true`; `model_options` includes both the live Codex catalog **and** the examples `openai.gpt-5.5` / `gpt-5.5`.
- `opencode-cli`: `reasoning_effort_supported: false`; `bedrock_supported: true`; `supported_launch_modes` = `["plain","resume"]` (no worktree/fork).
- `copilot-cli`: `bedrock_supported: false`; `reasoning_effort_options` include `none`…`max`; `context_tier_options` present.
- `claude-code`: `reasoning_effort_supported: false`; `bedrock_supported: true`.

---

### E2E-A2 — Build the SnazzyEmail roster from the original prompt (and adapt to a real limit)

**Goal:** reproduce the founding use case — *"Generate a SnazzyEmail team: architect (opencode + Bedrock + Opus 4.8 + xhigh), lead dev (codex + OpenAI GPT-5.5 + xhigh), reviewer (codex + jrubio Bedrock + GPT-5.5 + xhigh)"* — and demonstrate that the agent discovers and works around the OpenCode-cannot-pin-effort limit.

**Step 1 — naive attempt (expected to be REJECTED on the architect slot):**

```
deck_create_team(
  name="SnazzyEmail (naive)",
  description="First attempt, architect with xhigh on opencode",
  slots=[
    { "display_name": "Architect",
      "provider": "opencode-cli",
      "repo_path": "/home/juan/work/repos/juanrubio/snazzyemail",
      "role": "team-leader",
      "launch_options": { "platform": "bedrock", "aws_profile": "jrubio",
                          "aws_region": "us-east-1", "model": "anthropic/claude-opus-4-8",
                          "reasoning_effort": "xhigh" } },
    ...
  ]
)
```

**⇒** Rejected with `block_code: "reasoning_effort_unsupported"` (HTTP 400 via REST), message naming OpenCode. **No partial preset is created.** This is the spec's predicted limit (§6b/b2), surfaced loudly rather than silently dropped.

**Step 2 — adapted roster (the agent removes effort from the opencode slot):**

```
deck_create_team(
  name="SnazzyEmail",
  description="Architect/lead/reviewer for SnazzyEmail",
  slots=[
    { "display_name": "Architect",
      "provider": "opencode-cli",
      "repo_path": "/home/juan/work/repos/juanrubio/snazzyemail",
      "role": "team-leader / architect",
      "charter": "Own architecture and task breakdown; coordinate the team via Agent Mail.",
      "launch_mode": "plain",
      "launch_options": { "platform": "bedrock", "aws_profile": "jrubio",
                          "aws_region": "us-east-1",
                          "model": "anthropic/claude-opus-4-8" } },

    { "display_name": "Lead Developer",
      "provider": "codex-cli",
      "repo_path": "/home/juan/work/repos/juanrubio/snazzyemail",
      "role": "lead developer",
      "charter": "Primary implementer.",
      "launch_mode": "plain",
      "launch_options": { "model": "gpt-5.5", "reasoning_effort": "xhigh" } },

    { "display_name": "Reviewer / QA",
      "provider": "codex-cli",
      "repo_path": "/home/juan/work/repos/juanrubio/snazzyemail",
      "role": "reviewer / QA",
      "charter": "Review changes; run tests; adversarial verification.",
      "launch_mode": "plain",
      "launch_options": { "platform": "bedrock", "aws_profile": "jrubio",
                          "aws_region": "us-east-1", "bedrock_model": "openai.gpt-5.5",
                          "reasoning_effort": "xhigh" } }
  ]
)
```

**⇒ Pass criteria**
- `200`, preset created with 3 slots.
- Lead Developer slot: no warnings.
- Reviewer slot: **non-blocking warning** present (codex + bedrock + non-`anthropic.` model → "requires an AWS account/gateway that exposes this model"). Slot is still saved.
- Architect slot: saved; a missing-creds warning only if neither explicit nor ambient AWS creds are detected.
- Capture `{preset_id}`.

> Substitute the concrete account-specific model IDs you actually use; the example IDs come from `GET /providers/{id}/launch-options` → `model_examples`. Deck does **not** resolve "Opus 4.8" → an ID for you (G7).

---

### E2E-A3 — Plan → confirm → launch (the safe path)

**Goal:** the canonical launch flow with plan confirmation. Requires the toolchain (see prerequisites).

**Steps**
1. `deck_plan_team_launch(preset_id={preset_id})` ⇒ returns a plan with per-slot `action` (spawn/reuse/skip/blocked), `warnings`, and a `plan_hash`. Capture `{plan_hash}`.
2. Review the plan; confirm slots are `spawn` and `can_launch:true`.
3. `deck_launch_team(preset_id={preset_id}, confirm_plan_hash="{plan_hash}")`

**⇒ Pass criteria**
- Launch returns per-slot results with `status` in {`spawned`/`pending_registration`, `reused`}.
- New tmux sessions exist (`tmux ls`) — one per spawned slot.
- The codex Bedrock (reviewer) session has `AWS_PROFILE=jrubio` / `AWS_REGION=us-east-1` in its environment and **no** `CLAUDE_CODE_USE_BEDROCK`/`ANTHROPIC_MODEL` (G3). The opencode (architect) session likewise has AWS env only.
- The codex lead-dev session's command includes `--config model_reasoning_effort="xhigh"` (G1).

---

## Scenario group V — Validation guards (negative; no toolchain needed)

### E2E-V1 — Unknown launch_options key is rejected (G5a)

```
deck_create_team(name="V1", description="typo key", slots=[
  { "display_name":"Dev","provider":"codex-cli",
    "repo_path":"/home/juan/work/repos/juanrubio/claude-deck",
    "launch_options": { "model":"gpt-5.5", "reasoning_efort":"xhigh" } }   // typo
])
```
**⇒** `400`, message names the unsupported key (`reasoning_efort`) for `codex-cli`. **No preset created.** (Proves the typo does not silently vanish.)

### E2E-V2 — launch_mode not supported by provider is rejected (G5b)

```
deck_create_team(name="V2", description="bad mode", slots=[
  { "display_name":"Dev","provider":"opencode-cli",
    "repo_path":"/home/juan/work/repos/juanrubio/claude-deck",
    "launch_mode":"fork" }    // opencode supports only plain/resume
])
```
**⇒** `400`, message indicates `fork` is unsupported for `opencode-cli`. No preset created.
*(Variant: `worktree` on `codex-cli` → also rejected.)*

### E2E-V3 — reasoning_effort on a provider that can't honor it (G5c)

```
slots=[{ "display_name":"Arch","provider":"opencode-cli",
         "repo_path":"/home/juan/work/repos/juanrubio/claude-deck",
         "launch_options": { "reasoning_effort":"high" } }]
```
**⇒** `400` with `block_code: "reasoning_effort_unsupported"`.

### E2E-V4 — invalid reasoning_effort value (G5c)

```
slots=[{ "display_name":"Dev","provider":"codex-cli",
         "repo_path":"/home/juan/work/repos/juanrubio/claude-deck",
         "launch_options": { "reasoning_effort":"ultra" } }]   // not in low/medium/high/xhigh
```
**⇒** `400` with `block_code: "invalid_reasoning_effort"`, message listing the accepted set.

### E2E-V5 — copilot + Bedrock is rejected (capability says copilot has no Bedrock path)

```
slots=[{ "display_name":"Dev","provider":"copilot-cli",
         "repo_path":"/home/juan/work/repos/juanrubio/claude-deck",
         "launch_options": { "platform":"bedrock", "aws_profile":"jrubio" } }]
```
**⇒** `400` — copilot does not support Bedrock (`PROVIDER_BEDROCK_SUPPORT[copilot]=false`). No preset created.

---

## Scenario group W — Non-blocking warnings (slots still save)

### E2E-W1 — Bedrock without discoverable creds → warn, not block

Precondition: ensure no ambient `AWS_PROFILE`/`AWS_REGION` for this check, and omit them from options.
```
slots=[{ "display_name":"Arch","provider":"opencode-cli",
         "repo_path":"/home/juan/work/repos/juanrubio/snazzyemail",
         "launch_options": { "platform":"bedrock", "model":"anthropic/claude-opus-4-8" } }]
```
**⇒** `200`, preset **created**; the slot carries a non-blocking `warnings[]` entry about missing region/profile. (Creds may still resolve from the host chain — hence warn, not block.)

### E2E-W2 — codex + Bedrock + non-Anthropic model → warn

```
slots=[{ "display_name":"Reviewer","provider":"codex-cli",
         "repo_path":"/home/juan/work/repos/juanrubio/snazzyemail",
         "launch_options": { "platform":"bedrock","aws_profile":"jrubio",
                             "aws_region":"us-east-1","bedrock_model":"openai.gpt-5.5",
                             "reasoning_effort":"xhigh" } }]
```
**⇒** `200`, created; slot has a warning that the model requires an account/gateway exposing it. Capture `{preset_id}` for W3.

### E2E-W3 — Warning is reflected in the plan_hash (confirmation integrity)

Using the W2 preset:
1. `deck_plan_team_launch(preset_id={preset_id})` ⇒ note `plan_hash` (call it `H1`) and that the slot's plan item carries the warning.
2. Edit the slot (`PATCH /api/v1/agent-teams/slots/{slot_id}`) to add `aws_region` such that a *different* warning set results (or change the model to `anthropic.*` to clear the model warning).
3. `deck_plan_team_launch` again ⇒ new `plan_hash` `H2`.

**⇒** `H1 ≠ H2`. The hash incorporates warnings, so a stale confirmation cannot silently launch a roster whose advisory state changed (§6e warning-channel decision).

---

## Scenario group L — Launch safety & lifecycle

### E2E-L1 — Launch without a plan hash is refused by default

```
deck_launch_team(preset_id={preset_id})        // no confirm_plan_hash, no force
```
**⇒** `ok:false`, `error.code: "plan_hash_required"`; **the backend launch endpoint is never called** (client-side guard). This is the core safety contract — the default cannot launch blind.

### E2E-L2 — Stale plan hash is refused

1. `deck_plan_team_launch` ⇒ `{plan_hash}`.
2. Mutate the preset (add/remove a slot, or `PATCH` a slot).
3. `deck_launch_team(preset_id={preset_id}, confirm_plan_hash="{plan_hash}")` with the now-stale hash.

**⇒** Rejected with a plan-conflict (`409` at REST, surfaced as an error result via MCP) returning the fresh plan. The agent must re-plan and re-confirm.

### E2E-L3 — Explicit, conspicuous bypass works (and only the explicit arg does)

```
deck_launch_team(preset_id={preset_id}, force_without_plan=true)
```
**⇒** Launches (maps to REST `skip_plan_confirmation=true`). Confirms the bypass exists but is opt-in and conspicuously named — never the default.

### E2E-L4 — Reuse vs. re-spawn (idempotency)

1. Launch the SnazzyEmail preset (A3).
2. Without killing sessions, `deck_plan_team_launch` again ⇒ slots should plan as `reuse` (matching wakeable sessions), not `spawn`.
3. `deck_launch_team(..., confirm_plan_hash=...)` with `reuse_existing=true` (default).

**⇒** Slots report `reused`; no duplicate tmux sessions are created.

---

## Scenario group M — Multi-team setup

### E2E-M1 — Stand up several teams and enumerate them

**Goal:** the realistic "agent provisions a workspace" flow.

1. Create **Team 1 — SnazzyEmail** (reuse A2's adapted roster).
2. Create **Team 2 — Claude Deck maintenance**:
   - Lead: `codex-cli`, `/home/juan/work/repos/juanrubio/claude-deck`, `{ "model":"gpt-5.5","reasoning_effort":"high" }`
   - Reviewer: `claude-code`, same repo, `launch_mode:"worktree"`, `{ "platform":"bedrock","aws_profile":"jrubio","aws_region":"us-east-1","bedrock_model":"<anthropic bedrock id>" }`
3. Create **Team 3 — Docs**: single `copilot-cli` slot, `{ "model":"claude-sonnet-4.6","reasoning_effort":"medium","context_tier":"long_context" }`.
4. `deck_list_teams()` (or `GET /api/v1/agent-teams/presets`).

**⇒ Pass criteria**
- Three presets exist with the right slot counts (3, 2, 1).
- Team 2's claude-code reviewer accepts `worktree` (allowed for claude-code) — contrast with V2 where opencode rejected `fork`.
- Team 3's copilot slot accepts `context_tier` and a copilot-range effort.
- Listing returns all three with slots and per-slot warnings recomputed live.

---

## Cross-cutting assertions (verify across whichever scenarios you run)

1. **No silent drops.** Every option an agent sends is either honored, warned about, or rejected with a clear message — never accepted-and-ignored. (Spot-check: the V-series typo/effort cases all 400 rather than 200-with-missing-behavior.)
2. **Machine-readable errors.** Rejections carry a stable `block_code` (`reasoning_effort_unsupported`, `invalid_reasoning_effort`, unknown-key, mode-mismatch) so an agent can branch on them programmatically.
3. **Warnings are advisory and live.** They never block a save, are not persisted as state, and recompute on read/plan.
4. **Bedrock env hygiene (G3).** Non-Claude providers under Bedrock get only `AWS_REGION`/`AWS_PROFILE`; they must never receive `CLAUDE_CODE_USE_BEDROCK` or `ANTHROPIC_MODEL`.
5. **Launch is gated.** Default `deck_launch_team` cannot launch without a current `confirm_plan_hash`.

---

## Results log

| Scenario | Interface used | Result (PASS/FAIL/BLOCKED) | Notes / observed `block_code` / warnings |
|---|---|---|---|
| E2E-A1 capability discovery | REST fallback | PASS | All four provider descriptors returned `200`; codex advertised `xhigh` and examples `openai.gpt-5.5`/`gpt-5.5`; opencode modes were `plain,resume`; copilot had no Bedrock and included context tiers. |
| E2E-A2 naive roster rejected | REST fallback | PASS | HTTP `400`, `block_code=reasoning_effort_unsupported`, message `opencode-cli does not support reasoning_effort`; no partial preset was created. |
| E2E-A2 adapted roster created | REST fallback | PASS | Created preset `1` with 3 slots; lead warnings `[]`; reviewer warning `Codex Bedrock model requires an AWS account or gateway that exposes this model.`; architect warnings `[]`. |
| E2E-A3 plan→confirm→launch | REST fallback | PASS | Plan hash `8f1d841e46c25b06f324cda67f1653cf14a95c3771291623388f06197e32d7c2`; launch statuses `pending_registration,pending_registration,pending_registration`; tmux env for opencode/reviewer had `AWS_PROFILE=jrubio`/`AWS_REGION=us-east-1` and no `CLAUDE_CODE_USE_BEDROCK`/`ANTHROPIC_MODEL`; codex command contained `--config 'model_reasoning_effort="xhigh"'`. |
| E2E-V1 unknown key | REST fallback | PASS | HTTP `400`, message `Unsupported launch_options for codex-cli: reasoning_efort`. |
| E2E-V2 bad launch_mode | REST fallback | PASS | HTTP `400`, message `Unsupported launch_mode for opencode-cli: fork. Expected one of: plain, resume`. |
| E2E-V3 effort unsupported | REST fallback | PASS | HTTP `400`, `block_code=reasoning_effort_unsupported`, message `opencode-cli does not support reasoning_effort`. |
| E2E-V4 invalid effort value | REST fallback | PASS | HTTP `400`, `block_code=invalid_reasoning_effort`, message listed `low, medium, high, xhigh`. |
| E2E-V5 copilot+bedrock | REST fallback | PASS | HTTP `400`, message `copilot-cli does not support Bedrock launch options: aws_profile, platform`. |
| E2E-W1 bedrock-no-creds warn | REST fallback | PASS | HTTP `200`; warning `Bedrock launch relies on ambient AWS configuration; set aws_region/aws_profile if the host environment does not provide them.` |
| E2E-W2 codex+bedrock model warn | REST fallback | PASS | Created preset `3`, slot `5`; warning `Codex Bedrock model requires an AWS account or gateway that exposes this model.` |
| E2E-W3 warning in plan_hash | REST fallback | PASS | `H1=a8dbdeb9249acb024b5f0eea8aa9fff8b01e1069a74d4dac15232871e70329f8`; after patching model to `anthropic.claude-sonnet-4-6`, `H2=f31066129168d5131a24c964f541d0be83dd0827e914e87192d654ae38db855c`; hashes differed. |
| E2E-L1 launch w/o hash refused | REST fallback | PASS | REST launch without hash returned HTTP `409`, message `confirm_plan_hash is required unless skip_plan_confirmation is true`; MCP team-tool client guard was unavailable in this session. |
| E2E-L2 stale hash refused | REST fallback | PASS | Old hash `f31066129168d5131a24c964f541d0be83dd0827e914e87192d654ae38db855c`; after mutation, launch returned HTTP `409`, message `Launch plan changed; review the latest plan before launching`. |
| E2E-L3 explicit force bypass | REST fallback | PASS | REST `skip_plan_confirmation=true` returned HTTP `200`; statuses `reused,reused,reused`, equivalent to MCP `force_without_plan=true`. |
| E2E-L4 reuse vs respawn | REST fallback | PASS | Re-plan actions `reuse,reuse,reuse`; launch statuses `reused,reused,reused`; `tmux ls` output unchanged, so no duplicate sessions were created. |
| E2E-M1 multi-team + list | REST fallback | PASS | Created/listed three expected teams with slot counts `3,2,1`; Team 2 accepted `claude-code` `worktree`; Team 3 accepted copilot `context_tier=long_context` and `reasoning_effort=medium`. |

**Environment recorded:** Deck version 2.0.1 · codex codex-cli 0.142.3 · opencode 1.17.11 · AWS profile `jrubio` present? yes · date 2026-06-29
