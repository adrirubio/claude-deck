# Harness operations implementation handoff

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Implement **P03 in M1b**: extend the accepted thin Harnesses index with a common operating contract and readiness for Claude Code, Codex CLI, Copilot CLI, OpenCode, and Pi.

Read the [product brief](../product-brief.md), [experience specification](../experience-spec.md), and provider contract in the [architecture document](../architecture-contracts.md).

## Start conditions

G00 is complete. Start only after accepted packet reconciliation and this package's milestone/assignment gates. Branch from updated `feature/software-delivery-product-reposition` and record the autonomy merge evidence and base SHA.

Start only after M1a is accepted and the pilot checkpoint records a disposition to proceed with this scope. Use the merged provider adapters and preserve their launch contracts. This package does not run alongside initial P01/P02 development or delay the delivery pilot.

Native capability coverage differs today. Operational metadata should explain participation in delivery while keeping those differences accurate.

## Source files

- `backend/app/services/providers/`: registry, base class, capability matrix, launch contract/options, and the five adapters.
- `backend/app/api/v1/providers.py`.
- `backend/app/services/agent_team_service.py`: `_agent_mail_ready_reason` and launch planning.
- `backend/app/services/agent_mail_install_service.py`.
- `backend/app/services/pi_mail_readiness.py`.
- `backend/app/services/agent_bridge/discovery.py`.
- `frontend/src/types/providers.ts`, `hooks/useProviders.ts`, and provider launch fields.
- `docs/guide/multi-provider-codex-v2.md` and `docs/deploy/pi-provider-rollout.md`.
- Existing provider, multi-provider smoke, Pi, and team-launch tests.

## Write scope

Own new `backend/app/services/provider_operations_service.py`, the provider-operations endpoint and schemas including `native_surfaces`, provider types/API clients, extensions to P02's `frontend/src/features/harnesses/`, and focused tests.

Coordinate the shared readiness extraction from `agent_team_service.py`. Reuse P02's completed native page/API adapter registry and fixtures. Add catalog agreement/mismatch fixtures before M1b integration; the coordinator assigns any shared registry or route edits sequentially.

This package adds metadata and consistent readiness. It does not add universal configuration editors, change native permission defaults, or rewrite the Pi extension.

## Implementation steps

1. Inventory the ten operational keys in the architecture contract for all five adapters.
2. For each classification, record its conditions and source/fixture evidence. Use `unknown` where verified behavior is absent.
3. Extract shared bounded configuration-readiness checks so launch planning and the new screen use the same prerequisites.
4. Implement `GET /providers/{provider_id}/operations` with separate operation, native-capability, native-surface, and readiness objects. Classify page availability only where an implemented provider-specific adapter exists.
5. Keep credential readiness separate. Use a safe existing local check when available and leave it unknown otherwise.
6. Scope session readiness to verified slot/member/pane evidence. A generic provider card must not imply that every team using it has a bound worker.
7. Extend the thin index with all-provider cards and details. Intersect catalog availability/access with the implemented adapter registry before mounting or fetching. A failed or missing required catalog read cannot fall back to wider static permissions. Describe CLI/integration support separately when no page exists.
8. Replace inconsistent “ready” labels in affected entry points with precise configured, credential, and session states.
9. Test missing binaries, incomplete Mail integration, stale/ambiguous bindings, provider-specific conditions, and positive native capability flags paired with unavailable native pages.

A configuration `ready` result is displayed as **Configured for launch**. It is not proof of model access. Checks do not make paid model calls, refresh credentials through a new workflow, modify files, or launch disposable production sessions.

## Provider constraints

| Harness | Constraint to preserve |
| --- | --- |
| Claude Code | Rich native configuration does not establish live slot binding or approval authority |
| Codex CLI | Preserve safe TOML/profile editing, supported CLI mutations, redacted exports, and current metric/restore limits |
| Copilot CLI | Describe launch and integration behavior separately from narrower native configuration pages |
| OpenCode | Distinguish integration-specific config/plugin installation from a broad configuration editor |
| Pi | Preserve explicit extension opt-in, runtime requirements, exact project-local resume, authenticated lifecycle handling, and the absence of a Deck-provided sandbox |

An operational capability may be conditional even when the underlying CLI has a corresponding flag. Exact resume, permission enforcement, and safe recovery require their documented identity and workspace conditions.

The existing native capability matrix remains backward compatible. OpenCode config/plugins/usage and Copilot integration-only capabilities do not grant access to legacy pages. `native_surfaces` supplies explicit availability, adapter ID, and read/write access; unsupported or unknown pages have no adapter or access. Adding metadata is not authorization to implement new universal editors.

## Acceptance criteria

The relevant P06 cases are V05, V06, V11, V13, V14, V15, and V16. V11 repeats M1a's adapter checks with the added M1b catalog; it does not retroactively make P03 a dependency of the earlier pilot.

- All five registry entries have complete operational-key classifications.
- Native configuration count does not determine operational support.
- Native page availability is independent of CLI/integration capability flags and agrees with P02's explicit adapter registry.
- A read-only surface exposes no writes; an unavailable or mismatched adapter exposes no provider API calls.
- Screen readiness agrees with launch-plan readiness for the same fixture.
- Missing binaries and incomplete integrations produce useful block reasons.
- Unknown credential, execution-control, or recovery support remains unknown.
- A generic card does not impersonate a slot-specific session check.
- No status or metadata probe exposes credentials or contacts a model.
- Existing provider registry consumers remain backward compatible.
- Existing M1a delivery views and manual/configuration-only entry points remain usable.

## Validation

Use fixture provider processes and temporary configuration homes. Run focused tests and affected regressions:

```bash
cd backend
python -m pytest tests/test_provider_contract_api.py tests/test_providers.py tests/test_multi_provider_smoke.py tests/agent_teams/test_agent_team_service.py tests/agent_teams/test_pi_team.py -q
```

Add provider-operation and readiness tests. Frontend checks are:

```bash
cd frontend
npm run test
npm run lint
npm run build
```

If extension code is genuinely required, also run the existing Pi typecheck/tests and `scripts/generate-pi-mail-manifest.py --check` with the project's backend interpreter. A live paid probe requires its own task authorization and is not part of this package.

## Delivery evidence

Provide the five-provider matrix, classification evidence, API and native-surface fixtures, agreement tests with launch planning and P02 adapters, native-route coverage, and the remaining unknowns.

## Agent start instruction

> Start P03 in M1b only after G00, M1a acceptance, and the pilot checkpoint's disposition to proceed. Branch from updated `feature/software-delivery-product-reposition`. Extend the existing Harnesses index with sourced operations/readiness and a native catalog that restricts the completed adapter registry. Use bounded local probes, test catalog failures and launch agreement, and coordinate shared route edits.
