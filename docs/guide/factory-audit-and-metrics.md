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

Each outcome metric counts **one current result per tracked attempt**. A delivered result outranks sourced non-delivery, which outranks unknown, so later evidence can resolve an unknown result but never lowers a delivered one. Repeated evidence counts once. A known fact time places the result in a window; otherwise the record time does.

| Metric | Meaning |
| --- | --- |
| `terminal_tracking_in_window` | Tracked attempts with a terminal fact. Terminal tracking is not delivery. Deleting the live item does not change the count. |
| `delivered_in_window` | Attempts whose current result is delivered. A merged pull request, observed by the verification merge paths, records this result with the PR merge time and the verified head version. A trusted acceptance declaration of an exact design version also records it (see below). |
| `closed_without_delivery` | Attempts with sourced proof that they ended without delivery. GitHub closed the issue as not planned or duplicate, with no pull request. Or a fresh read showed that every pull request of the attempt is closed without merge, the issue is closed, and no approval, revision or retry continues the attempt. |
| `unknown_outcomes` | Terminal tracking without result evidence, for example an ordinary issue closure with no merge evidence. |
| `independently_human_reviewed_design` | Delivered design attempts with a validated independent human review of the exact delivered version, counted once per attempt. The evidence must name a human reviewer and attest independence; an agent member or the operator credential never qualifies. A merge, Leader approval or a review of another version is not human review. |
| `elapsed_attempt_duration` | The median seconds from dispatch to terminal tracking of the same launched attempt. It is not execution time or operator hands-on time. Unpaired facts are unknown. |
| `implementation_retries`, `diagnostic_retries` | Recorded retry charges by class. |
| `implementation_retry_counters`, `diagnostic_retry_counters` | The authoritative budget counters now. An authorized retry can reset them, so they are not charge counts. |
| `recovery_success` | Preserved revision results that completed. A cancellation or resume request is not a recovery success. |
| `operator_interventions` | Distinct applied operator actions. Notification facts are not actions; rejected and uncertain actions are excluded and reported. |
| `harness_failures` | Failed launch transitions only. |
| `current_queue`, `total_tracked_attempts`, `pending_reviews`, `active_revisions` | Present state from live records, labelled with their population. |
| `cost` | Unknown. There is no measured usage attribution. |

Tracked attempts in separate scopes stay distinct. A count is never a unique-PR total.

## Result times and later results

A closed-without-merge result is a combination of current conditions. It has no reliable result time, so its fact time stays unknown and the record time places it. The pull request closure time and the issue closure time are kept as separate source times.

The watcher reads later results. Each poll reads at most 20 attempts that are unknown or closed without delivery, in turn, with no age limit. When a pull request of such an attempt merged later, the watcher records the delivery on the original attempt. It never changes a work item. The metrics read itself never fetches GitHub.

## Review acceptance declarations

An operator can record a review acceptance from a trusted source with `POST /api/v1/factory/review-acceptances`. The declaration names:

- the work item, its attempt, the pull request and the exact commit version
- the reviewer, the reviewer kind (`human`), independence and the decision
- the review time and the source type and reference

The declaration must match an attempt of the item, the pull request of that attempt, and a version that the factory recorded for it. A changed or unrelated version is refused with 409 and a rejected record. The operator credential proves only who recorded the declaration. The factory never derives a human reviewer or independence from a credential or account type.

An accepted, independent declaration for a design item also records delivery of that exact version, before or after a merge. A declaration never changes work state, approvals or merges.

## Filters

Both reads use the same applied team and scope context keys. A context key belongs to one resource lifetime. When a team, scope or item is deleted, its key is retired; a later resource with the same numeric ID receives a new key, so old history never attaches to it. A retired key still addresses the retained history, but it has no current population. A key of the wrong kind, an unknown key, or a scope of another team also has no current population: present-state values are then unknown, never global. Reading the audit events never creates a key.

Each section names the filters, page and observation time of the data it shows. When a newer read is pending, fails or is cancelled, the section labels its data as retained. Paging waits while the rows on screen belong to another selection.

## Operator token

The event list uses the operator token for this browser tab. If no token is stored, the page asks for one once. A 401 response removes the refused token, and the next read asks for a replacement. A 503 response means the backend has no configured operator token. In both cases the safe metrics stay available.

## Limits

- Facts before the coverage marker are not available and are not reconstructed.
- Independent human review is recorded only through operator declarations from a trusted source. Without a declaration, reviewed-design counts stay at zero with explicit unknowns. Test declarations are synthetic and prove no live human review.
- The observed runtime provider comes only from the native process of the slot's current authenticated Mail session. Agents started through a `node` or `bun` wrapper, and absent, ambiguous or changed sessions, stay unknown.
- Human benefit measurements and operator hands-on minutes are not measured (V14 NOT_PERFORMED).
- Cost stays unknown without measured usage attribution.
- Events are retained for the life of the database. No automatic purge exists.

See the [Factory API](/api/factory) for the route contracts.
