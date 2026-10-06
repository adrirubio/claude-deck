# Audit ledger and delivery metrics contract (P05)

Scope: issue 10 implementation record. This document states the durable
observation-ledger contract, the delivery and review evidence rules, the
metric definitions and the recorded limits.

## Event kinds

The ledger records these explicit kinds: `policy_change`,
`leader_assignment`, `recovery_cancellation`, `prepared_attempt_resume`,
`operator_escalation`, `workspace_release`, `work_lifecycle` and
`observed_snapshot` imports. Each event records occurrence and recording
times, source, record kind with distinct fact source and fact time, actor
kind and reference, deletion-safe live references, immutable context keys
and snapshot labels, non-secret correlation and optional operation identity,
sanitized reason, allowlisted before and after values, action outcome,
delivery outcome, completion kind and human-review evidence.

## Actor derivation rules

Actors come from actual authentication or scheduler context. The shared
operator credential is recorded as an operator role with no invented
personal identity. Members record their authenticated member reference. The
scheduler records its scheduler identity. No credential, credential hash or
agent token is ever stored.

## Safe-field allowlist

Before and after values pass a strict allowlist of state and identity labels.
Credential-shaped keys and values are dropped. Sanitized reasons remove
credential-shaped keywords together with the value token that follows them.

## Rollback and failure injection evidence

Policy and Leader changes persist their event in the same transaction as the
change. An audit-write failure rolls back the change; no partial event state
can exist without its audited change. The applied workspace release and the
applied prepared-attempt resume commit their events in the same transaction.
Refused actions record `rejected` in a fresh observation transaction after
the rollback; observation failure never masks the refusal.

## Replay behavior

A non-secret operation identity tied to the action and resource deduplicates
replays: duplicate delivery cannot duplicate an accepted action or terminal
event. The optional operation identity preserves legacy callers and all
authorization, nonce, lease and revision guards.

## Delivery and review evidence rules

`delivery_outcome` stays null while work continues without delivery or
terminal disposition evidence. `delivered` requires a sourced merged PR tied
to the attempt or a recorded independent human acceptance of the exact
design artifact or version. `closed_without_delivery` requires terminal
tracking plus sourced proof the attempt ended without delivery. Terminal
tracking without sufficient evidence is `unknown`. An issue closure or
completed status alone yields unknown. A merge, Leader approval, human merge
policy, an issue state or a write through a human-owned credential never
establishes independent human review. `abandoned_by_operator` is an
escalation reason: it keeps its action outcome and leaves delivery outcome
null. Later retries never inflate non-delivery counts and never convert the
escalation into a past non-delivery. Later sourced evidence appends an event
and reconciles the classification without double-counting delivery. Routine
closure after proven delivery does not downgrade the result.

## Metric definitions

Metrics report requested window, filter scope, counting unit, sample count,
sources, available interval, missing intervals and coverage. Terminal,
delivered, non-delivery, unknown, review, recovery, intervention, harness
and cost counts stay distinct. Unknown and excluded counts appear with their
reasons. Elapsed attempt duration uses recorded start and stop or terminal
events for the same attempt and is named by those boundaries; it is never
presented as execution time or operator hands-on minutes. Diagnostic and
implementation retries stay separate; authoritative budget counters retain
their semantics and event totals never replace them. Cost is null or
unknown without measured attribution; partial provider or time coverage is
displayed as coverage and never presented as a total. Tracked attempts in
separate scopes remain distinct and are never advertised as a unique-PR
total.

## Sample calculation

One attempt with a merged PR and no independent human review yields:
delivered_in_window 1 with unit tracked_attempts; independently
human-reviewed design 0 with unknown 1 and the reason that no attributable
independent human acceptance exists; unknown outcomes 0; closed without
delivery 0. One attempt closed without result evidence yields unknown 1.

## Historical attribution and retention

Imported current state records `observed_snapshot` at import observation
time. Reliable external facts keep their source and fact time distinct from
import time. Unknown historical times remain unavailable. Generic row
timestamps never supply merge, execution or human-review times. Ledger rows
survive legitimate deletion of teams, scopes, items, revisions and requests;
live references use deletion-safe nulling and never cascade events away or
add deletion blocks after completed guards. Immutable context keys defeat
numeric ID reuse. Renames, provider changes and slot reconfiguration never
rewrite past facts. Configured-at-event and observed-runtime providers stay
distinct; absent runtime evidence stays unknown. Aggregations never depend
on inner joins to live operational rows. The ledger is retained for the life
of the database; no automatic purge exists.

## Protected reads and safe metrics

`GET /api/v1/factory/audit-events` is operator protected through the
existing operator workflow (503 unconfigured, 401 missing or invalid; no
blanket 403). Agent tokens do not authorize audit reads. Filters accept
historical `team_context_key` and `scope_context_key`; current-id filters
resolve the current resource context key. Deleted live links render
unavailable while snapshot labels remain readable. Ordinary factory detail
routes still return 404 for deleted resources. `GET /api/v1/factory/metrics`
is a safe aggregate read: no protected details, no fresh external fetches
and no writes.

## Coverage limits and unavailable measurements

Instrumentation start is the earliest recorded ledger time; events before it
do not exist and missing intervals stay unavailable. The ledger observes
actual results and never approves plans, raises limits, retries work,
releases a workspace or replays a mutation because an event is present or
absent. V14 measurements remain NOT_PERFORMED. Operator hands-on minutes
remain a pilot or manual measurement until activity instrumentation exists.
Unattributed native usage cannot become a factory-wide cost total.
