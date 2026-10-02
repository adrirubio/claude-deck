# Audit and delivery metrics implementation handoff

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

Implement **P05** after the explicit authority model: record policy and recovery decisions durably, and measure delivery from observed lifecycle evidence.

Read the audit contract in [architecture and contracts](../architecture-contracts.md), the [product brief](../product-brief.md), and the [soak evidence record](../../../deploy/attempt-recovery-soak-log-2026-09-29.md).

The soak record establishes why policy changes and outcome claims need durable evidence. It does not supply a complete event stream to backfill.

## Start conditions

G00 is complete. Start only after accepted packet reconciliation and this package's milestone/assignment gates. Branch from updated `feature/software-delivery-product-reposition` and record the autonomy merge evidence and base SHA.

P04 authority and mutation authorization coverage must be integrated. Rebase after its model/migration changes. Preserve the current cancellation accounting, diagnostic restoration, and workspace release behavior.

The checkpoint must record the internal accountability need and any narrowed optional metrics scope. Missing external pilot participants is not a blanket gate on necessary audit work. Verify the team-deletion prerequisite before relying on legitimate deletion fixtures.

## Source files

- `backend/app/models/database.py` and `database.py`.
- `backend/app/api/v1/agent_teams.py`: policy, protected remedy, and workspace routes.
- `backend/app/services/github_approval_service.py`.
- `backend/app/services/github_dispatch_service.py`.
- `backend/app/services/github_verification_service.py` and `github_watcher_service.py`.
- `backend/app/services/github_workspace_service.py`.
- Existing structured Mail delivery and wake records.
- M1a factory schemas, API, and interface, plus any accepted M1b additions.
- Existing cancellation, force-release concurrency, diagnostic recovery, and operator-auth tests.

## Write scope

Own the new event model/schema/migration, `factory_audit_service.py`, `factory_metrics_service.py`, audit/metric API extensions and tests, and the related factory UI.

Coordinate modifications to existing mutation services after P04. Do not create an alternative recovery state machine.

## Ledger implementation

1. Add the event fields defined in the architecture contract, immutable context snapshots/keys, nullable deletion-safe live references, and a stable instrumentation start/coverage marker.
2. Use explicit event kinds for policy changes, Leader assignment, recovery holds/cancellation, prepared-attempt resume, operator escalation through the abandon route, workspace release, and forward work lifecycle changes.
3. Store allowlisted before/after values and sanitized reasons. Snapshot original identities/creation times, repository and team labels, issue type, non-secret attempt identity, and known harness attribution without credentials, token hashes, raw command bodies, or private diagnostics.
4. Derive actors from actual authentication or scheduler context. The shared operator credential establishes an operator role, not a named person.
5. Persist required policy/Leader events in the same transaction as those changes. An audit-write failure rolls back the change.
6. Instrument recovery outcomes through their existing services. Preserve an explicit uncertain outcome when committed state, Mail transport, or external effects require reconciliation.
7. Deduplicate replays using a non-secret operation/correlation identity tied to the action and resource. Legacy callers remain supported; introducing an optional operation ID cannot weaken their guards.
8. Record new lifecycle transitions once, with the work item and preserved attempt/revision identity needed for measurement. Keep `action_outcome` separate from evidenced `delivery_outcome`, completion kind, and independent human-review evidence.
9. Add operator-protected paginated audit reads with historical context-key filters and snapshot labels. Keep ordinary factory work readable without access to private audit details.

The ledger observes actual results. It does not approve plans, raise limits, retry work, release a workspace, or replay a mutation because an event is absent.

## Historical data

Use `observed_snapshot` for imported current state and give it the import observation time. Do not infer merge, execution, or human-review times from generic `updated_at` values.

If reliable GitHub or existing normalized records provide a historical fact, keep its source and event time distinct from the import time. Unproven history stays unavailable.

Expose the instrumentation start, available interval, event source, and any missing interval. Reconstructed conversations do not become contemporaneous policy-approval records.

### Retention and mutable records

Keep ledger events when teams, scopes, items, or other referenced operational records are legitimately deleted. The audited source lacks the required team-deletion state guard; it must be supplied before M1a acceptance and verified here. Live foreign keys use `ON DELETE SET NULL`; events cannot cascade away or add a deletion block once the completed authority/state guards pass.

Use immutable snapshots and context keys for historical display, attribution, grouping, and filtering. Current-ID filters resolve the current resource's context key; `team_context_key` and `scope_context_key` address retained history after deletion. Numeric ID reuse must not attach old events to a new record. Render deleted-resource links as unavailable while retaining their snapshot labels.

Team/repository renames and slot-provider changes do not rewrite past facts. Keep configured-at-event and observed-runtime providers distinct. Aggregations cannot depend on inner joins to live records. Retain events for the life of the Deck database; no automatic purge is part of this package.

## Metrics

Implement safe aggregates with a requested window, filter scope, sample count, source, and coverage.

| Metric | Evidence required |
| --- | --- |
| Current queue/progress/review/attention | M1a persisted state projections |
| Delivered code or design in a window | Sourced merged PRs, or independent human acceptance of an exact design artifact/version, with event time and attempt identity |
| Independently human-reviewed design | Attributable human review/acceptance evidence for that artifact/version; a merge alone is insufficient |
| Closed without delivery and unknown outcomes | Explicit non-delivery evidence or terminal tracking without enough result evidence, counted separately |
| Elapsed attempt duration | Recorded start and stop/terminal events for the same attempt |
| Recovery success | Recorded preserved-attempt revisions and their actual outcomes |
| Operator intervention count | Recorded authenticated operator actions classified by kind |
| Harness failures | Recorded launch, binding, delivery, or execution outcome with known harness context |
| Cost | Stable measured usage attribution to the relevant work; otherwise unknown |

Separate agent approval from human review. A GitHub write attributed to a human-owned credential is not automatically an independent human review.

Apply the architecture's `delivered`, `closed_without_delivery`, and `unknown` outcome rules without changing the dispatch state machine. An issue closed as `completed` without a result fact stays unknown, including a failed design issue with no PR. A merged design PR can count as delivered while its human-review status remains unknown. Confirmed termination of the tracked attempt without delivery belongs to non-delivery; cancelling a continuation request/revision, releasing a workspace, or escalating work alone does not terminate the attempt.

In particular, `abandoned_by_operator` is an escalation reason and can remain eligible for manual or issue-update retry. Record the operator action as applied/rejected/uncertain, but do not infer a terminal delivery outcome. A later retry is not evidence of a previously closed attempt, and a UI label cannot supply terminal evidence. Extend V29 with the V34 escalation/retry fixture.

Expose unknown/excluded counts and reasons alongside the sample size and coverage. State whether a metric counts tracked attempts or unique artifacts; separate scopes cannot silently become a unique-PR total. Append later evidence and reconcile the classification without duplicating a delivered result or treating routine closure after delivery as a failure.

Name duration according to its boundaries. Do not present elapsed time, model execution time, and operator hands-on minutes as interchangeable. Operator minutes remain a pilot/manual measurement until actual activity instrumentation exists.

Keep diagnostic and implementation retries separate. Existing authoritative budget counters retain their semantics; event totals do not replace them.

Provider or time ranges with partial usage coverage must display that coverage. Unattributed native usage cannot become a factory-wide cost total.

## Acceptance criteria

The relevant P06 cases are V13, V22–V25, V29, and V30.

- A policy/Leader mutation and its event either commit together or both roll back.
- Applied, rejected, and uncertain recovery outcomes are distinguishable.
- Duplicate delivery does not duplicate an accepted action or terminal event.
- Actors and reason fields contain no credential or fabricated identity.
- Current-state snapshots do not manufacture historical throughput.
- Terminal status alone cannot establish delivery or human review; unknown and explicit non-delivery results stay separate from successes.
- An applied abandon-route escalation leaves delivery outcome unset unless separate outcome evidence exists; subsequent retries do not inflate non-delivery counts.
- Legitimate deletion retains events and historical filtering; renames, provider changes, and numeric ID reuse do not alter past attribution or counts.
- Metrics state their time boundaries, sample count, sources, and missing coverage.
- Unsupported/unattributed cost is null or unknown.
- Existing cancellation, lease, revision, and failed-head accounting regressions remain green.

## Validation

Add transaction-failure injection, replay/deduplication, actor derivation, redaction, interrupted transport, snapshot-import, and metric coverage tests. V29 must exercise unproven issue closure, proven terminal non-delivery, operator escalation followed by retry, merged code/design, independent human acceptance, and later evidence. V30 must exercise rename, provider reassignment, guard-permitted scope/team deletion, historical filtering, and numeric ID reuse without losing or relabelling events.

Use an isolated database and mocked external effects. Relevant existing regressions include:

```bash
cd backend
python -m pytest tests/agent_teams/test_active_continuation_cancellation.py tests/agent_teams/test_force_release_concurrency.py tests/agent_teams/test_operator_auth.py tests/test_sqlite_compat_migrations.py -q
```

Run the new factory audit/metric tests and the affected approval/verification/workspace tests. Frontend audit/coverage components require the standard test, lint, and build checks.

## Delivery evidence

Provide event kinds, actor derivation rules, the safe-field allowlist, retention/snapshot schema, rollback/failure-injection evidence, replay behavior, delivery/review evidence rules, metric definitions, sample fixture calculations, historical filters, coverage UI, and remaining unavailable measurements.

## Agent start instruction

> Start P05 only after accepted M2, integrated explicit roles, and complete operator guards. Branch from updated `feature/software-delivery-product-reposition` and target the PR at `feature/software-delivery-product-reposition`. Add a transactional observation ledger with retained historical context and evidence-based delivery metrics through existing mutation services. Preserve recovery semantics, distinguish terminal status from proven delivery or human review, and validate deletion, attribution, uncertain outcomes, and missing coverage.
