# Factory audit and delivery metrics

The audit ledger records what the factory actually did. The metrics page counts those records in a time window. Both are observations. They never approve a plan, raise a limit, retry work, release a workspace or replay an action.

Open **Audit** in the main navigation (`/audit`). The safe metrics load without an operator token. The event list needs the operator token for this browser tab.

## What the ledger records

Each event records:

- the event kind, its source and its occurrence and recording times
- the actor: the shared operator role, an authenticated member and session, or a code-owned scheduler reference
- the action outcome: `applied`, `rejected` or `uncertain`
- deletion-safe links to the team, scope, item, revision and request, and immutable context keys
- a typed snapshot of safe labels from the time of the event
- allowlisted before and after values, and a sanitized reason

The ledger stores no credential, credential hash, token, nonce or private command. Free text is sanitized before it is stored. Assignment, header, URL and known token forms are replaced with `[redacted]`. Nested objects and unknown fields are dropped.

A refused action records `rejected`. When an external effect cannot be proved, the event records `uncertain`, for example a notice whose send failed after the action committed. The committed action is never repeated because its notice failed. A notice has its own fact, separate from the action fact.

## Coverage starts at the installation marker

The first start after an upgrade installs one coverage marker. Coverage starts at that marker and does not move. At installation the factory also imports the current state of each existing work item once, as an `observed_snapshot` at the marker time. The import has no fact time. It does not reconstruct history.

For each window, the metrics read reports:

- the requested window
- the available interval, from the later of the window start and the marker to the window end
- each missing interval before the marker
- `full`, `partial` or `unavailable` coverage on each ledger metric

A window wholly before the marker has no ledger values: they are unknown, not zero. An event inside a missing interval does not remove the gap.

## How to read the metrics

| Metric | Meaning |
| --- | --- |
| `terminal_tracking_in_window` | Work items with a terminal tracking fact. Terminal tracking is not delivery. |
| `delivered_in_window` | Tracked attempts with sourced delivery evidence. |
| `closed_without_delivery` | Attempts with sourced proof that they ended without delivery. |
| `unknown_outcomes` | Terminal tracking without result evidence, for example a closed issue with no merge evidence. |
| `independently_human_reviewed_design` | Only validated independent human review of the exact artifact and version. A merge or Leader approval is not human review. |
| `elapsed_attempt_duration` | The median seconds from dispatch to terminal tracking of the same launched attempt. It is not execution time or operator hands-on time. Unpaired facts are unknown. |
| `implementation_retries`, `diagnostic_retries` | Recorded retry charges by class. |
| `implementation_retry_counters`, `diagnostic_retry_counters` | The authoritative budget counters now. An authorized retry can reset them, so they are not charge counts. |
| `recovery_success`, `operator_interventions`, `harness_failures` | Ledger facts with their own units and coverage. |
| `current_queue`, `total_tracked_attempts`, `pending_reviews`, `active_revisions` | Present state from live records, labelled with their population. |
| `cost` | Unknown. There is no measured usage attribution. |

Tracked attempts in separate scopes stay distinct. A count is never a unique-PR total.

## Filters

Both reads use the same applied team and scope context keys. Context keys address retained history after a team, scope or item is deleted. A key of the wrong kind, an unknown key, or a scope of another team has no current population: present-state values are then unknown, never global.

Each section names the filters, page and observation time of the data it shows. When a newer read is pending, fails or is cancelled, the section labels its data as retained. Paging waits while the rows on screen belong to another selection.

## Operator token

The event list uses the operator token for this browser tab. If no token is stored, the page asks for one once. A 401 response removes the refused token, and the next read asks for a replacement. A 503 response means the backend has no configured operator token. In both cases the safe metrics stay available.

## Limits

- Facts before the coverage marker are not available and are not reconstructed.
- Human benefit measurements and operator hands-on minutes are not measured (V14 NOT_PERFORMED).
- Cost stays unknown without measured usage attribution.
- Events are retained for the life of the database. No automatic purge exists.

See the [Factory API](/api/factory) for the route contracts.
