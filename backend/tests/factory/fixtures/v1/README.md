# Factory read contract v1

These JSON responses are generated from disposable SQLite fixtures through the
five ASGI factory routes, without application lifespan, live GitHub, provider
processes, browser sessions, dispatch or Mail writes. They are proposed contract
evidence until B4 independently reviews the exact head and B3 acknowledges it.
Final P01 implementation acceptance and human merge remain separate.

Each scenario records endpoint, query, method, HTTP status and response. `schema.json`
contains six typed response models, including read errors. `mapping.json` freezes
category, bounded reason and action source mappings. `manifest.json` identifies
the full earlier source commit containing these artifacts, avoiding a commit
hash that refers to itself. Consumers record both the accepted review head and
that source SHA. IDs and timestamps are synthetic; no real credentials or paths
are present. Protected error examples use disposable synthetic authority and
fail before mutation.

Work provider filtering means the assigned owner's configured harness; missing
or cross-team owners have no inferred provider and do not match that filter.
Repository provider filtering means a configured slot in that team's
roster, because a scope has no assigned owner. Provider labels describe the
configured registry; verified session provider is observed separately. Duplicate
GitHub names remain separate scopes, including overlap warnings computed against
all enabled local teams/scopes before filters, with normalized repository and
dispatch label identity.

All timestamps are UTC. Category counts cover the complete selected filters and
category before pagination. Cursors are versioned, opaque to clients, bound to
filters and list type, and ordered by updated timestamp then ID descending.
Database count/list/authority reads share a real SQLite read snapshot. Separate
requests remain eventually consistent; refresh from the start after updates.
Runtime observations have their own timestamp and never establish scheduler
readiness from database configuration alone. Only eligible intake contributes
stale/never-polled counters; paused or blocked intake suspends poll freshness.

Optional IDs, item PR/approval/review fields, owner, approver, waiting, workspace,
association providers/targets, link hints, runtime observation/reason, last poll
and next cursor are explicit null. Nested item/policy fields follow the packet's
allowlists; private legacy fields never enter the new models. `schema.json`
is the complete nullable-field inventory. Unknown raw dispatch states retain
their text and category unknown. Unrecognized private reasons become a bounded
generic summary. Operator stop is attention; tracking finished states do not
prove historical delivery outcomes. Verified SHA is omitted without a displayed
PR or during diagnostic execution.

Retry eligibility comes from the existing shared legacy projection and
`GithubDispatchService.retry_eligibility`. Its read eligibility does not authorize
the viewer: the existing protected mutation requires current Leader or operator
authority and checks state again. Retry behavior and issue-update auto-retry are
unchanged. Resume, escalate, cancel continuation request, cancel active revision
and release recovery checkpoint always return unknown in this read contract;
their protected route predicates are not evaluated here. Continuation proposal
policy is not prepared-attempt resume eligibility. A configured continuation
flag, leased workspace or action label must never enable those remedies in P02.

Fresh authenticated MCP association plus exact nonretired pane identity supplies
typed session targets. Offline, unknown and ambiguous states do not guess a
terminal. Launch hints only identify a verified offline owner or Leader slot;
opening any link grants no authority and performs no mutation.

Reproduce from a non-project working directory, with the backend import root and
an in-memory application database URL, to avoid reading a task `.env`:

```sh
PYTHONPATH=/path/to/checkout/backend DATABASE_URL=sqlite+aiosqlite:///:memory: \
  python -m pytest /path/to/checkout/backend/tests/factory -q
```

`--freeze-factory-fixtures` intentionally regenerates the responses for a reviewed
contract change. Normal runs compare exact response/schema/mapping values against
the frozen files. Full suites still require the product-heavy shared lock.
