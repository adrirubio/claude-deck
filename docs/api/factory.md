# Factory API

These five observational routes return versioned factory work and repository observations. Availability depends on the installed version.

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
