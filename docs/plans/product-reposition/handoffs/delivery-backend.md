# Delivery backend implementation handoff

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Implement **P01 in M1a**: observational delivery endpoints over the existing factory records. The operator must be able to see complete filtered counts, a paginated queue, safe details, and repository state across teams.

Read the [product brief](../product-brief.md), [experience specification](../experience-spec.md), and [architecture contracts](../architecture-contracts.md). The response contracts in the architecture document are the shared interface with P02.

## Start conditions

G00 is complete. Start only after accepted packet reconciliation and this package's milestone/assignment gates. Branch from updated `feature/software-delivery-product-reposition` and record the autonomy merge evidence and base SHA. Reconcile against the audited integration snapshot `301e37c1e53e822a47a9572dc592e866df77f763`; the documentation worktree's older source is not the implementation baseline.

After G00, this package can start before any further mutation hardening. Its endpoints perform observations only. It does not change dispatch, budgets, approval decisions, leases, or scheduler behavior.

The coordinator separately owns the team-deletion prerequisite and shared-file schedule. Its completion gates M1a acceptance, not the start of these observational reads. P03's full provider catalog is not a dependency.

## Source files

- `backend/app/api/v1/agent_teams.py`: `_work_item_response`, `_load_work_item_authority`, `_reload_work_item_response`, safe scope projections, and current per-team list.
- `backend/app/models/database.py`: team, slot, scope, work-item, workspace, approval, and revision records.
- `backend/app/models/schemas.py`: existing work-item and scope response fields.
- `backend/app/services/github_dispatch_service.py`: shared retry predicate and current authority interpretation.
- `backend/app/services/github_dispatch_scheduler.py` and `github_recovery_gate.py`: runtime mode, recovery-only gating, and repository job observations.
- `backend/app/services/agent_mail_service.py`: authenticated member/session associations.
- `backend/app/services/agent_bridge/discovery.py`: verified Bridge metadata.
- `backend/tests/agent_teams/test_github_workspace_api.py`: projection and recovery regression behavior.
- `backend/tests/agent_teams/test_agent_bridge_session_metadata.py`: association evidence.

## Write scope

Own new `factory.py`, `factory_schemas.py`, `factory_projection_service.py`, shared `github_work_item_projection.py`, and `backend/tests/factory/` files. The first projection extraction also owns the required edits to `agent_teams.py`.

Coordinate router registration with the integration coordinator. Do not modify provider launch contracts or team authority selection in this package.

## Implementation steps

1. Extract the existing authority loading and safe projection into a shared module. Preserve existing response fields, retry predicates, access checks, and normalized authority reads.
2. Add typed planned factory schemas using the architecture's explicit safe-field decisions. Omit dispatch nonce/head identity, absolute workspace paths, raw active-scope summaries, and private/freeform command diagnostics; preserve the legacy API contract separately.
3. Implement database filters and complete-set category counts. Retain work-item IDs and separate scope identities; terminal tracking counts make no delivery-success claim.
4. Implement cursor pagination with deterministic timestamp/ID ordering, validation, and filter binding. Check representative mutation paths update the existing timestamp correctly; do not add a global listener without a demonstrated defect.
5. Implement safe single-item details and watched-scope reads. Derive approver and waiting actor from actual authority records. Add the separate configuration/intake projections, bounded scheduler/gate observations, and same-repository/dispatch-label overlap warnings without synchronizing jobs or arbitrating dispatch.
6. Bulk-load owner and session evidence. Return `ambiguous` or `unknown` when no unique verified binding exists.
7. Add checked-in response fixtures for P02. Cover all categories, missing owners, preserved PRs, operator escalation with retry/auto-retry still possible, offline actors, overlapping scopes, failed refresh responses, and normal/recovery-only/stopped/unknown runtime observations.
8. Register the new router and validate legacy endpoints alongside the new reads.

Full revision commands and private diagnostic evidence continue through existing protected reads. Do not make the basic detail endpoint a shortcut around their authorization.

## Acceptance criteria

The relevant P06 cases are V01, V02, V03, V04, V07, V08, V09, V10, V12, V13, V16, V26, V34, and the M1a projection of V36. Supply pagination fixtures for P02's V27.

In particular:

- Counts agree with the full filtered dataset containing more than 100 rows.
- Two teams watching the same repository retain separate issue/attempt rows.
- Unknown raw states remain visible and contribute to the unknown count.
- `completed` remains a terminal-tracking observation and is not projected as proven delivery or human review.
- `escalated` with `abandoned_by_operator` stays in attention; neither a Finished category nor terminal non-delivery is inferred.
- Deleted/missing owners remain unassigned; no default provider fills them.
- An escalated item with a revision is described as stopped unless actual execution evidence establishes otherwise.
- Factory and legacy responses use the same retry eligibility.
- Factory GETs produce no work, Mail, lease, GitHub, provider-launch, or active-project mutation.
- Runtime observations do not start or synchronize scheduler jobs, and their own timestamps remain distinct from the database snapshot.
- Two configured-enabled scopes under a recovery-only gate both show normal intake blocked. Stopped/unknown scheduler and missing-job cases have distinct reasons; suspended polling is not classified as an unexplained stale poll.
- Safe runtime fields reveal no protected recovery target, nonce, head, or private evidence.
- Response serialization follows the explicit safe-field table, including sentinel checks for omitted dispatch identity, workspace paths, and raw active-scope summaries.
- Same-label enabled scopes produce a warning identifying both teams without merging their work or claiming dispatch exclusivity.
- Query count remains bounded between one and 100 results.

## Validation

Create isolated fixtures under `backend/tests/factory/` using an in-memory or temporary database and dependency overrides. Mock Bridge/GitHub/provider observations where required.

Run the new focused tests and the affected existing regressions:

```bash
cd backend
python -m pytest tests/factory -q
python -m pytest tests/agent_teams/test_github_workspace_api.py tests/agent_teams/test_agent_bridge_session_metadata.py -q
```

Add a query-count check and a side-effect spy test. Validate pagination under tied timestamps, representative persisted state transitions, malformed cursors, and filter changes. Stub scheduler/gate observations for V26, including unavailable runtime data; verify the count partitions and safe-field boundary without contacting the running scheduler. V34 must retain authoritative manual and issue-update retry semantics after operator escalation. V36 compares active collisions, paused scopes, and different labels.

## Delivery evidence

Provide the response fixtures, exported contract names, endpoint examples using fixture data, focused test results, measured query count, runtime-state truth table, and compatibility evidence. Identify any eligibility, runtime observation, or association that remains `unknown`.

P02 should receive the fixtures as soon as the schemas settle. Complete the package through the review sequence in the [implementation plan](../implementation-plan.md).

## Agent start instruction

> Start P01 for M1a after accepted packet reconciliation, integrated #5 and owner-bound dispatch with distinct Leader approval. Branch from updated `feature/software-delivery-product-reposition` and reconcile the audited source. Build allowlisted aggregate reads with truthful escalation, intake, and overlap projections. Keep dispatch and mutation behavior intact, with no P03 dependency. Deliver fixtures, focused tests, and the acceptance evidence listed here.
