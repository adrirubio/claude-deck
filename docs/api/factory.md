# Factory API

These five observational routes return versioned factory work and repository observations. Availability depends on the installed version. Two more routes read the audit ledger and the delivery metrics, and one protected route records review acceptance declarations; see [Audit events and delivery metrics](#audit-events-and-delivery-metrics).

All paths below begin with `/api/v1/factory`. These GET routes read local factory records and a bounded scheduler observation. They do not dispatch, claim a lease, send or acknowledge Mail, launch a provider, change the active project, or fetch GitHub issues. They have no operator/session authentication dependency in this source. Protected recovery reads and mutations have their own authentication and state checks.

| Method and path | Response |
| --- | --- |
| GET `/overview` | Selected work counts, configured automation and observed intake |
| GET `/work-items` | Paginated safe work projections and complete filtered counts |
| GET `/work-items/{item_id}` | One safe work projection |
| GET `/repositories` | Paginated watched scopes with intake, poll and overlap observations |
| GET `/repositories/{scope_id}` | One watched scope observation |

## Filters and pagination

Overview and both lists accept optional `team_id`, `scope_id` and `provider`. IDs must be positive integers no larger than 2^63−1. A scope selected with a team must belong to that team. `provider` must be a registered harness ID: `claude-code`, `codex-cli`, `copilot-cli`, `opencode-cli` or `pi-cli`.

For work counts/lists, provider matches the assigned owner's currently configured harness. An unassigned or invalid owner is not replaced with a default provider and does not match a provider filter. For repository selection, provider matches a configured slot in that scope's team roster; scopes have no assigned owner. These filters therefore describe different sets. Configured harness and observed session provider are separate fields.

The work list also accepts `category`: `all` (default), `queued`, `active`, `review`, `attention`, `finished` or `unknown`. Both lists accept `limit` from 1 to 100 (default 50) and optional `cursor`. Details accept their path ID, without list filters or pagination.

List records sort by updated timestamp descending, then ID descending. Treat the cursor as opaque; pass `next_cursor` back with the same filters and list type. A changed filter, malformed cursor or incompatible cursor requires a fresh request from the start. A response's count/list/authority reads share a database snapshot; subsequent pages can observe later changes. `updated_at` describes a persisted record update, not an execution heartbeat.

```text
GET /api/v1/factory/work-items?team_id=1&category=attention&limit=50
GET /api/v1/factory/repositories?provider=codex-cli&limit=50
```

The IDs in examples are synthetic. Repeated GitHub names and issues in different scopes remain independent records.

## Response envelopes

Successful responses include `schema_version: 1` and UTC ISO-8601 `generated_at`. Optional values are explicit null; arrays are empty arrays when no records match.

| Route | Additional top-level fields |
| --- | --- |
| Overview | `filters`, `counts`, `automation` |
| Work list | `filters`, `total`, `has_more`, `next_cursor`, `counts`, `items` |
| Work detail | `work_item` |
| Repository list | `filters`, `total`, `has_more`, `next_cursor`, `repositories` |
| Repository detail | `repository` |

`total` and category counts describe the full selected dataset before pagination, including the selected category. Repository total counts scopes, not distinct GitHub names. `next_cursor` is null exactly when `has_more` is false.

Work projections contain an allowlisted `item`, team/repository context, category, nullable owner/approver/waiting/workspace, separate owner and approver session associations, policy, action observations and typed link hints. Basic details do not expand the private legacy payload. Dispatch nonces/head identity, host workspace paths, credentials/hashes, private commands and freeform recovery summaries are omitted. Last verified SHA is nullable and belongs only to the displayed PR; it is null for diagnostic execution. Treat titles and raw statuses as display text.

## Status and action meaning

| Raw tracking status | Category |
| --- | --- |
| `pending` | queued |
| `dispatched`, `verifying` | active |
| `awaiting_human_review`, `ready_for_review` | review |
| `escalated`, `failed` | attention |
| `merged`, `completed` | finished |
| Any unrecognized state | unknown, with the raw state retained |

Finished counts describe tracking state, not measured delivery success or human acceptance. Operator-requested escalation remains attention and does not prove that the operating-system process stopped or that a terminal delivery outcome occurred. Authoritative manual and issue-update retry rules remain intact.

An action has `name`, `state`, `block_code`, `reason` and `required_actor`. Retry uses the existing retry predicate; it can be blocked by active continuation authority, pending approval or a preserved PR. The other five remedies report unknown eligibility in this API. A configured continuation flag is not permission to resume a prepared attempt. No action observation authorizes its viewer: protected mutations check the current principal and state again. Retry accepts the configured operator or an eligible authenticated current-Leader MCP session. Protected revision history also checks its caller and limits private commands by principal. Agent decisions and human PR review remain separate.

Session state can be bound, offline, ambiguous or unknown. Only a verified association provides a concrete team/slot/member/MCP-session target. Nullable Mail or offline launch hints identify context, not an instruction to send, claim or launch.

## Repository intake and overlap

Each repository projection is one scope. Team automation and scope enablement determine configured enablement. Effective intake is eligible, blocked or unknown based on that configuration plus normal/recovery-only/unknown runtime mode, running/stopped/unknown scheduler state and whether its job is scheduled. Runtime has its own observation timestamp, distinct from response generation. Configuration alone does not prove intake is running.

Polling freshness is fresh, stale, never_polled, suspended or unknown. Stale means an eligible scope's last poll is older than twice the configured interval. Blocked or paused intake suspends freshness; unknown runtime remains unknown. Overview stale/never-polled counts include eligible intake only.

Overlap warns when enabled teams/scopes share a normalized GitHub repository and dispatch label. It checks local scopes outside the selected filters and returns safe other scope IDs. A warning neither merges work records nor arbitrates dispatch ownership.

## Errors

New read errors use `detail: {code, message}`.

| HTTP status | Code | Meaning |
| --- | --- | --- |
| 422 | `invalid_filter` | Invalid IDs, category, provider, limit or incompatible filters |
| 422 | `invalid_cursor` | Malformed, wrong-version, wrong-list or filter-mismatched cursor |
| 404 | `resource_not_found` | Selected team, scope or work item is absent |
| 500 | `projection_failed` | Database/projection observations could not be loaded |

```json
{"detail":{"code":"invalid_cursor","message":"Refresh from start with the selected filters."}}
```

Preserve both code and message. A read failure is an error, not a zero count. Existing protected routes retain their own string or structured error details and their 401/403/409 semantics; this contract does not rewrite them.

## Synthetic response and source

The following overview comes from checked-in disposable fixtures, not a live factory capture:

```json
{
  "automation": {
    "configured_scopes": 3,
    "enabled_scopes": 2,
    "intake_blocked_scopes": 0,
    "intake_eligible_scopes": 2,
    "intake_unknown_scopes": 0,
    "never_polled_scopes": 1,
    "paused_scopes": 1,
    "runtime": {
      "mode": "normal",
      "observed_at": "2026-09-30T11:59:00Z",
      "reason_code": null,
      "scheduler_state": "running"
    },
    "stale_scopes": 0
  },
  "counts": {
    "active": 27,
    "attention": 26,
    "finished": 26,
    "queued": 14,
    "review": 26,
    "total": 132,
    "unknown": 13
  },
  "filters": {
    "provider": null,
    "scope_id": null,
    "team_id": null
  },
  "generated_at": "2026-09-30T12:00:00Z",
  "schema_version": 1
}
```

Complete nested schemas, nullable fields and bounded reason mappings are in `backend/app/models/factory_schemas.py` and `backend/tests/factory/fixtures/v1/`. The checked-in fixtures are synthetic examples of this versioned contract.

## Audit events and delivery metrics

These two GET routes read the observation ledger. They never fetch GitHub facts and never change a record. The [audit and metrics guide](/guide/factory-audit-and-metrics) explains the numbers.

| Method and path | Authentication | Parameters |
| --- | --- | --- |
| GET `/audit-events` | Operator token header `X-Deck-Operator-Token` | `page` (default 1), `page_size` (1–100, default 25), `event_kind`, `team_context_key`, `scope_context_key`, `item_context_key`, `team_id`, `scope_id`, `item_id` |
| GET `/metrics` | None | `window_start`, `window_end` (required), `filter_scope` (`all` or `scoped`), `team_context_key`, `scope_context_key` |

Audit events accept pagination and context filters, without a time window. Metrics accept a time window and context filters, without pagination. Agent session tokens do not authorize audit reads. A missing backend operator token returns 503; a missing or invalid header returns 401.

An audit page has `items`, `total`, `page`, `page_size`, the applied keys and `snapshot_labels` (the observed snapshot keys in the page). Each item has its kind, source, record kind, fact source and fact time, actor kind and reference, live links and context keys, a typed safe `context_snapshot`, a sanitized reason, allowlisted before and after values, and the action, delivery and completion outcomes. Member and session IDs, operation identities and replay keys are not returned. `live_links_available` is false when every live link was removed by deletion.

A current-ID filter (`team_id`, `scope_id`, `item_id`) resolves the active context key of the current resource lifetime, without writing. An ID with no recorded lifetime returns no events. A context key also addresses its own history after deletion; a reused numeric ID has a new key.

A metrics window has `window_start`, `window_end`, `filter_scope`, `counting_unit_note`, `instrumentation_start`, `available_interval_start`, `available_interval_end`, `missing_intervals` and `metrics`. `instrumentation_start` is the installed coverage marker, not the first event. A `scoped` request without a key returns no metrics. Each sample has `name`, `counting_unit`, `value` (null when unknown), `sample_count`, `unknown_count`, `excluded_count`, `unknown_reasons`, `source` and `coverage`. Ledger samples say `full`, `partial` or `unavailable` coverage. Outcome samples count one current result per tracked attempt. Present-state samples name their population. A key without a current resource gives unknown present-state values.

### Review acceptance declarations

POST `/review-acceptances` records one review acceptance from a trusted source. It needs the operator token header `X-Deck-Operator-Token`. It is observational: it never changes work state, approvals, merges, retries, leases or counters.

| Field | Rule |
| --- | --- |
| `declaration_id` | 8–64 characters (`A-Z a-z 0-9 . _ : -`). The idempotency key. |
| `work_item_id` | An existing work item. |
| `attempt` | The attempt key `item:{id}:launch:{launch}:revision:{revision}` of that item. |
| `artifact` | `owner/repo/pull/N` in the item's repository. |
| `version` | The 40-character lowercase commit SHA that was reviewed. |
| `reviewer` | The attributed reviewer. `operator`, `shared-operator-credential` and `member:` references are refused. |
| `reviewer_kind` | `human`, as declared by the source. |
| `independent` | As declared by the source. |
| `decision` | `accepted` or `rejected`. |
| `occurred_at` | The review time, with a timezone, not in the future. |
| `source_kind`, `source_ref` | `github_review`, `signed_record` or `operator_attested`, and a safe source reference. |

Responses:

- 201 with `event_id`, `operation_id`, `counted` and `delivery_established` when the declaration is recorded.
- 200 with the stored result for an exact replay.
- 409 with `refusal` when the declaration does not bind: `attempt_unrelated`, `artifact_unrelated`, `version_changed`, `version_unrelated`, `work_item_not_found` or `replay_conflict`. The refusal is recorded as a rejected event.
- 422 for a field that breaks the contract, and 401 or 503 for the operator token, with no write.

An accepted, independent, human declaration for a design item also records delivery of that exact version. The recording credential is stored as the recording actor, separate from the reviewer.
