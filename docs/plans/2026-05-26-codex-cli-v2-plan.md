# Codex CLI and Multi-Provider v2 Plan

**Date:** 2026-05-26  
**Status:** Follow-up plan  
**Related work:** PR #139, issues #140 and #142, `docs/plans/2026-05-25-codex-cli-support.md`  
**Scope:** Deferred v1 bullets, multi-provider hardening, Codex parity investigation, E2E coverage

## Goal

Turn the v1 Codex CLI support into a durable multi-provider foundation.

v1 proved the architecture: Claude Deck can detect, configure, launch, diagnose, and back up Codex CLI alongside Claude Code. v2 should close the deliberately deferred gaps, deepen the shared provider model, and make the mixed-provider experience feel native rather than newly grafted on.

This plan is not a continuation of the v1 implementation checklist. It is the next planning layer for the items v1 intentionally narrowed plus the extra work exposed by the first implementation.

## V1 Baseline

Already shipped:

- Provider registry for Claude Code and Codex CLI.
- Provider status, diagnostics, and CLI execution safeguards.
- Agent Bridge backend with Codex discovery and spawn/resume/fork support.
- Provider context and provider-aware UI routing.
- Codex TOML config loading and whitelisted structured edits.
- Backup-before-write for Codex config changes.
- Codex MCP inventory plus MCP add/remove controls.
- Codex plugin inventory in read-only mode.
- Export-only Codex backups.
- Provider-aware dashboard, header, sidebar, and docs.
- Backend tests and build verification.

## Deferred From V1

These came directly from the original v1 plan but were intentionally reduced:

- Full frontend `cc-bridge` to `agent-bridge` feature/module rename.
- Richer mixed-provider Agent Bridge UX with an explicit All / Claude Code / Codex filter model.
- Codex history and model cache read-only surfaces.
- Full Codex profile resolver.
- Dedicated Codex cards for profiles, rules, features, and plugin workflows.
- Codex plugin mutation.
- Codex backup restore policy.
- Broader browser-level E2E smoke coverage.
- Deeper usage/context parity investigation for Codex.

## Non-Goals

- Do not expose Codex auth secrets in raw viewers or backups by default.
- Do not add broad arbitrary Codex CLI execution.
- Do not treat Claude-only metrics as provider-neutral until Codex has reliable local data.
- Do not add a third provider until the two-provider contract is tighter.
- Do not support automatic Codex restore until the restore safety model is explicitly designed and tested.

## Workstream 1: Agent Bridge v2

### Objective

Make the mixed Claude Code + Codex session experience first-class.

### Scope

- Rename frontend feature code from `cc-bridge` toward `agent-bridge` where practical.
- Keep route compatibility for existing `/cc-bridge` links if needed.
- Add explicit provider filters:
  - All agents
  - Claude Code
  - Codex CLI
- Make provider badges, empty states, and unsupported actions consistent.
- Improve new-session dialog structure:
  - provider choice first
  - then provider-specific fields
  - clearer dangerous-option warnings
- Ensure mixed sessions can be viewed and attached side by side without hidden provider assumptions.

### Acceptance Criteria

- A mixed tmux fleet shows Claude Code and Codex sessions together by default.
- Provider filtering works without losing selected terminal state unexpectedly.
- Codex and Claude Code session cards use shared layout with provider-specific actions.
- Frontend naming no longer leaks `cc-bridge` into newly touched public UI strings.
- Existing deep links continue working or redirect cleanly.

## Workstream 2: Codex Session and History Surfaces

### Objective

Investigate and expose reliable Codex history/session metadata without inventing unsupported semantics.

### Scope

- Inspect `$CODEX_HOME/history.jsonl`.
- Inspect `$CODEX_HOME/models_cache.json`.
- Identify whether Codex has stable session IDs, timestamps, project paths, model choices, and message summaries.
- Add read-only backend services if the files are stable enough.
- Add a Codex history/session page only if the data quality is good.
- Otherwise, document what is missing and keep this out of product UI.

### Acceptance Criteria

- Decision recorded: supported surface, partial diagnostics-only surface, or no UI.
- No raw secrets or sensitive prompt bodies are exposed without deliberate UI framing.
- Tests cover malformed, missing, and large history/cache files.

## Workstream 3: Codex Plugin Management

### Objective

Move from read-only plugin inventory to safe mutation workflows if Codex CLI behavior is stable enough.

### Scope

- Validate local `codex plugin` command behavior for:
  - install
  - remove/uninstall
  - enable/disable, if supported
  - update, if supported
  - marketplace/list metadata
- Model plugin operations as provider-owned commands, not raw shell strings.
- Add strict allowlists and argument validation.
- Add confirmation UX for destructive actions.
- Preserve read-only mode when mutation support is unavailable or ambiguous.

### Acceptance Criteria

- Plugin mutation commands use fixed binary resolution and `shell=False`.
- All plugin identifiers are validated.
- Destructive operations require explicit confirmation.
- Failed CLI operations return actionable errors.
- Tests cover supported operations and refusal paths.

## Workstream 4: Codex Configuration Depth

### Objective

Fill the remaining Codex config UI gaps without overfitting to unstable TOML details.

### Scope

- Add a Codex profile resolver:
  - active profile
  - `profile-v2` reference
  - profile TOML files
  - overridden keys
- Add dedicated cards where useful:
  - profiles
  - rules
  - features
  - project trust
- Improve raw TOML editing only if validation and recovery are robust enough.
- Keep structured edits whitelisted.

### Acceptance Criteria

- Users can see where effective Codex values come from.
- Profile v2 files are visible and safely editable only for approved keys.
- Rules files can be viewed without exposing auth/cache/history files.
- Parse errors are clear and do not block unrelated read-only views.

## Workstream 5: Backup, Export, and Restore Policy

### Objective

Design a serious Codex backup policy instead of casually adding restore.

### Scope

- Keep export-only behavior as the default.
- Define restore categories:
  - safe restore: non-secret config/rules/profile files
  - unsafe restore: auth, tokens, cache, history
  - unsupported restore: generated or version-sensitive files
- Add restore preview for safe files only if path checks and parse validation are strong.
- Consider an explicit advanced export mode for history/cache, but keep auth excluded unless there is a compelling reason.

### Acceptance Criteria

- Restore never writes outside `$CODEX_HOME`.
- Restore validates TOML before replacing active config.
- Restore creates a pre-restore backup.
- Auth files remain excluded by default.
- UI clearly distinguishes export, restore preview, and actual restore.

## Workstream 6: Provider Capability Matrix

### Objective

Make provider support explicit in the UI and API.

### Scope

- Expand provider capability metadata beyond booleans where useful:
  - supported
  - read-only
  - write-capable
  - unsupported
  - unknown
- Use capability metadata to drive:
  - sidebar visibility
  - diagnostics
  - empty states
  - disabled actions
  - docs/API output
- Make Claude-only surfaces explicit rather than implied.

### Acceptance Criteria

- The UI can explain why an action is hidden or disabled.
- Capability metadata is tested for both Claude Code and Codex.
- Adding a future provider does not require hardcoding every nav decision in React.

## Workstream 7: Usage and Context Parity Investigation

### Objective

Decide whether Codex can support meaningful usage/context views.

### Scope

- Investigate local Codex data sources for:
  - model usage
  - token usage
  - session duration
  - project activity
  - context/tool usage
- Compare against existing Claude Code usage/context surfaces.
- Add diagnostics-only summaries if data is partial.
- Avoid fake precision.

### Acceptance Criteria

- A short decision doc states what Codex can and cannot support.
- Any UI added labels Codex metrics accurately.
- Claude-only usage/context pages remain clearly labeled until parity is real.

## Workstream 8: Provider Contract Hardening

### Objective

Make the provider layer boring enough that a third provider can be added later without another architectural retrofit.

### Scope

- Review `AgentProvider` boundaries after v1 usage.
- Separate provider metadata, CLI commands, config files, session discovery, and backup behaviors cleanly.
- Reduce provider-specific conditionals in route handlers and frontend components.
- Add contract tests for shared provider behavior.
- Document provider implementation requirements.

### Acceptance Criteria

- Provider-specific logic lives primarily in provider modules.
- Shared routes use provider interfaces rather than provider id conditionals where practical.
- Tests catch missing capabilities, unsafe command exposure, and malformed provider responses.

## Workstream 9: E2E and Smoke Coverage

### Objective

Add browser-level confidence for the multi-provider flows.

### Scope

- Use temp config homes for Codex and Claude where possible.
- Add E2E coverage for:
  - provider switching
  - dashboard provider status
  - Agent Bridge provider filters
  - Codex settings edit in a temp `$CODEX_HOME`
  - Codex MCP add/remove against a controlled fixture or mocked CLI
  - Codex backup export
  - unsupported/disabled provider actions
- Keep manual smoke checklist for local tmux attachment because terminal interaction is environment-sensitive.

### Acceptance Criteria

- E2E tests run in CI or are clearly marked as local-only with documented prerequisites.
- Tests do not mutate real `~/.codex` or `~/.claude`.
- Manual smoke checklist is updated and repeatable.

## Workstream 10: Documentation and Product Framing

### Objective

Make the product story match the multi-provider reality.

### Scope

- Update docs once v2 features land:
  - Agent Bridge mixed-provider workflows
  - Codex config/profile/rules handling
  - Codex plugin management safety model
  - backup/export/restore policy
  - provider capability matrix
- Decide whether public copy still leans on "Claude Deck" or starts introducing a broader "local agent console" framing more strongly.
- Add examples for mixed tmux fleets.

### Acceptance Criteria

- Docs distinguish Claude Code, Codex CLI, and provider-neutral features.
- Safety limitations are documented without burying them.
- README feature list does not overpromise Codex parity.

## Suggested Milestones

### Milestone 1: Mixed Provider UX Hardening

- Agent Bridge v2
- Capability matrix
- Header/dashboard/sidebar refinements
- E2E smoke for provider switching and mixed sessions

### Milestone 2: Codex Config and History Depth

- Profile resolver
- Rules/features/profile cards
- History/model cache investigation
- Usage/context decision doc

### Milestone 3: Safe Mutation and Recovery

- Plugin mutation, if CLI behavior is stable
- Backup restore preview and safe restore policy
- Additional command/path validation tests

### Milestone 4: Provider Platform Hardening

- Provider contract cleanup
- Third-provider readiness audit
- Docs refresh

## Issue Breakdown

Create one umbrella GitHub issue for this plan, then track implementation with child issues:

- Agent Bridge v2 mixed-provider UX
- Codex history and model cache investigation
- Codex plugin mutation workflows
- Codex config depth and profile resolver
- Codex backup restore policy
- Provider capability matrix
- Codex usage/context parity investigation
- Provider contract hardening
- Multi-provider E2E smoke coverage
- Multi-provider docs refresh

## Open Questions

- Does Codex expose stable enough history/session metadata to deserve a real Sessions page?
- Should Codex plugin mutation be supported immediately, or kept behind an experimental flag?
- Should Codex backup restore support profile/rules files before main `config.toml`?
- Should the app publicly stay "Claude Deck" while internally becoming a provider-neutral agent console?
- Is there a third provider we expect soon enough to shape the provider contract now?

## Recommended Next Step

Start with Milestone 1. Mixed-provider UX and capability metadata are the right next investment because they reduce confusion across every later Codex feature. Plugin mutation and restore are more dangerous; they should wait until the provider model and test coverage are stronger.
