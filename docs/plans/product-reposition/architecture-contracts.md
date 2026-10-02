# Claude Deck delivery architecture and contracts

**Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / `ac9252242fcf436c3ea9997add5d32416cad2cd1`. Product work starts first in the fork `juanrubio/claude-deck`, from and targeting `feature/software-delivery-product-reposition`. Follow the agent deployment plan and startup gates. Earlier release snapshots and M0 readiness tables are historical evidence; this decision supersedes their pending-G00 or master-target instructions.

The repositioning introduces a delivery read model and a new interface over the existing dispatch system. It preserves the current team, work-item, approval, attempt, Mail, and workspace authorities.

All new endpoints and fields below are proposed implementation contracts. Existing behavior is anchored to the reference commit in the [packet index](README.md).

Implement these contracts only after the autonomy feature has been merged into `master`. Use the updated `master` as the implementation base and reconcile the proposed contracts with the merged autonomy code before editing.

## Data ownership

| Record | Authority |
| --- | --- |
| `AgentTeamPreset` | Saved team and team automation policy |
| `AgentTeamSlot` | Worker identity, configured harness, routing, and launch options |
| `TeamGithubScope` | One team's watched repository and finite policy |
| `GithubWorkItem` | One issue tracked inside a scope |
| `GithubApprovalRequest` | Normalized request and designated decision authority |
| `GithubAttemptScopeRevision` | Preserved attempt revision and bounded implementation or diagnostic authority |
| `GithubWorkspace` | Lease, checkout, and acquisition identity |
| Mail and pane records | Authenticated session identity, delivery, and wake evidence |
| GitHub | Issue, PR, head, check, review, and merge facts |

The same GitHub issue can have separate work-item IDs in different scopes. Aggregate reads retain those identities. They do not merge independent attempts by repository name or issue number.

M1a adds no second job engine or task database. Extract shared projection helpers when needed so existing team endpoints and new factory endpoints use the same interpretation of approvals, revisions, and eligibility.

## Planned delivery read API

Add an API router under `/api/v1/factory`.

| Endpoint | Purpose |
| --- | --- |
| `GET /overview` | Counts and automation freshness across the selected scope |
| `GET /work-items` | Paginated work with team, owner, waiting, and action projections |
| `GET /work-items/{item_id}` | Safe details for one work item |
| `GET /repositories` | Paginated watched-scope summaries grouped by repository in the client |
| `GET /repositories/{scope_id}` | Safe details for one watched scope |

These endpoints read persisted local state and a sanitized, read-only snapshot of the local scheduler and recovery gate. They do not poll GitHub, synchronize scheduler jobs, launch providers, write active-project selection, send Mail, change read receipts, acquire workspaces, or perform continuation claims.

Safe factory reads have the same access class as existing general local team/work-item reads. Protected revision commands, detailed recovery evidence, and operator audit history retain their protected endpoints. This packet does not introduce a new account or tenancy model.

### Filters and pagination

Overview and list endpoints accept optional `team_id`, `scope_id`, and `provider`. Work also accepts `category` with `all`, `queued`, `active`, `review`, `attention`, `finished`, or `unknown`.

`provider` matches the owner slot's current configured harness. Missing owners only match an omitted provider filter. Return configured and observed runtime harness values as different fields.

Validate positive IDs, provider IDs, category values, and compatible team/scope combinations. A well-formed but absent selected resource returns `404`; invalid combinations or query values return `422`. A provider known to the registry can be selected even when its binary is missing.

List pagination uses `limit` from 1 to 100, default 50, and an opaque validated cursor. Sort by `updated_at DESC, id DESC`, using both values in the cursor. Tie cursors to their filters and reject a cursor reused with different filters. Encode versioned cursor data; do not include credentials.

Pagination is eventually consistent while records change. Return `generated_at`, `total`, `has_more`, and `next_cursor`. Deduplicate accumulated rows by ID. Do not promise an immutable historical snapshot.

Counts are calculated over the complete matching set before pagination. A single response obtains its counts and records from a consistent database read transaction.

`updated_at` is a persisted record-update observation, not an execution heartbeat or lifecycle event time. The audited code assigns it explicitly at mutation sites; the review established no missing update. P01 verifies representative dispatch, review, escalation, and retry transitions before freezing cursor fixtures. Preserve existing timestamp semantics unless a failing case justifies a focused fix; an ORM listener is not a prerequisite.

### Refresh while browsing

Use cursor-based **Load more** for Work and other paginated delivery lists. Automatic polling may replace the first page only while the user has not requested an additional page.

Starting Load more pauses automatic refresh of that list and invalidates any earlier first-page request still in flight. Retain accumulated rows, the continuation cursor, scroll position, and keyboard focus. Show the last observation time and **Live updates paused while browsing older results**, with a **Refresh from start** action. Reaching the last page or returning from a hidden tab does not resume list polling.

An explicit Refresh from start or a filter change clears accumulated rows and the cursor, starts a new request generation, and resumes first-page polling. Overview counts and work details may continue refreshing independently; label their observation times instead of implying that they share the paused list's snapshot. After a mutation or conflict, refresh the affected detail and mark the paused list as needing refresh without discarding its browsing position.

### Status mapping

| Raw `dispatch_status` | Display category |
| --- | --- |
| `pending` | `queued` |
| `dispatched`, `verifying` | `active` |
| `awaiting_human_review`, `ready_for_review` | `review` |
| `escalated`, `failed` | `attention` |
| `merged`, `completed` | `finished` |
| Any other value | `unknown` |

Always return the raw status, issue type, attempt phase, and relevant authority status alongside the category. An active revision attached to an escalated item does not by itself mean execution is currently running. `finished` means tracking reached a terminal state; it is not a delivery-success measure. The watcher can assign `completed` after an issue closes without a merged PR. Keep that distinction visible until the outcome evidence defined below is available.

**Abandon decision:** preserve the existing state machine. The protected abandon route calls `escalate` with `abandoned_by_operator`; that item remains in `attention`. In the new interface, call this action **Escalate attempt**, and display **Operator requested stop** as its reason. Explain that this does not prove the agent process stopped or permanently close the issue. Manual retry can remain eligible, and a later GitHub issue update can requeue work when the existing auto-retry predicate permits it. Do not relabel this state Finished or infer `closed_without_delivery`. A permanently terminal abandon workflow would require a separate backend contract covering retry, watcher, monitoring, and leases; it is deferred.

The count invariant is:

```text
total = queued + active + review + attention + finished + unknown
```

### Overview response

Use this shape as the P01 and P02 contract:

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-30T12:00:00Z",
  "filters": {
    "team_id": null,
    "scope_id": null,
    "provider": null
  },
  "counts": {
    "total": 0,
    "queued": 0,
    "active": 0,
    "review": 0,
    "attention": 0,
    "finished": 0,
    "unknown": 0
  },
  "automation": {
    "configured_scopes": 0,
    "enabled_scopes": 0,
    "paused_scopes": 0,
    "never_polled_scopes": 0,
    "stale_scopes": 0,
    "intake_eligible_scopes": 0,
    "intake_blocked_scopes": 0,
    "intake_unknown_scopes": 0,
    "runtime": {
      "mode": "unknown",
      "scheduler_state": "unknown",
      "observed_at": null,
      "reason_code": "runtime_not_observed"
    }
  }
}
```

The values above are an empty fixture, not an observation of the user's factory.

`enabled_scopes` requires both team automation and scope activation and describes configuration only. `paused_scopes` counts the remainder of configured scopes. The additional intake counts partition configured-enabled scopes:

```text
configured_scopes = enabled_scopes + paused_scopes
enabled_scopes = intake_eligible_scopes + intake_blocked_scopes + intake_unknown_scopes
```

### Effective automation state

`runtime.mode` is `normal`, `recovery_only`, or `unknown`. `scheduler_state` is `running`, `stopped`, or `unknown`. Observe these once per response without starting or resynchronizing the scheduler. The runtime observation has its own timestamp; the database transaction does not make in-memory scheduler state part of an atomic snapshot.

Repository summaries/details include the team and scope activation flags, `configured_enabled`, and an `intake` projection with `state` (`eligible`, `blocked`, or `unknown`), `reason_code`, and readable summary. Derive it in this order:

| Condition | Intake state and explanation |
| --- | --- |
| Team or scope disabled | `blocked`, `team_paused` or `scope_paused`; counted in `paused_scopes` only |
| Recovery-only gate active | `blocked`, `recovery_only_gate`; normal intake is blocked for every configured-enabled scope |
| Scheduler known to be stopped | `blocked`, `scheduler_stopped` |
| Runtime mode, scheduler state, or repository-job observation unavailable | `unknown`, `runtime_not_observed` |
| Normal mode and running scheduler, but the repository job is absent | `blocked`, `job_not_scheduled` |
| Normal mode, running scheduler, and repository job present | `eligible`; existing access, readiness, capacity, and item rules still apply |

Recovery-only mode permits bounded recovery processing for its designated attempt; it never establishes normal intake eligibility. Reuse the safe active-gate predicate behind `/agent-teams/github-recovery-gate/active`. Ordinary factory responses expose the mode and its effect on intake, without revealing the protected target attempt, nonce, head, or recovery evidence. Detailed recovery-gate inspection remains operator protected.

Only scopes eligible for normal intake contribute to never-polled and stale poll counts. A non-null last poll is stale after twice the configured GitHub polling interval. Repository details return that interval and last poll timestamp even when polling is suspended. Label poll freshness `suspended` for known paused/blocked intake and `unknown` for unavailable runtime evidence, so the recovery gate does not appear as an unexplained polling failure. These are observations of existing scheduler behavior, not new scheduler policy or a guarantee that an agent is executing.

### Work-item projection

Return a separately allowlisted safe `item` projection from the existing work-item response, plus:

- `team`: ID and display name.
- `repository`: scope ID, validated GitHub owner/name, and display name.
- `category`: the mapping above.
- `owner`: nullable slot ID, name, configured provider ID, and provider label.
- `approver`: designated slot/member references and a clear source for the assignment.
- `waiting`: actor kind (`owner`, `leader`, `operator`, `human`, or `unknown`), reason code, and readable summary, or null.
- `session`: association state (`bound`, `offline`, `ambiguous`, or `unknown`), nullable observed runtime provider, and a nullable verified Bridge target.
- `policy`: the relevant safe policy values already exposed by team/scope reads.
- `actions`: named eligibility records with state, block code, readable reason, and required actor.

P01 must enumerate and review the safe fields rather than blindly serializing ORM rows. Keep lease and capability tokens, token hashes, credentials, full revision commands, raw launch commands, and private diagnostic payloads out of these responses.

Apply these explicit decisions to list and ordinary detail responses; the richer legacy schema is not itself an allowlist:

| Source field or content | Factory projection |
| --- | --- |
| `dispatch_nonce`, acknowledgement enforcement identity, `dispatch_head_ref` | Omit; retain internal/protected protocol use |
| `workspace_path` | Omit the absolute host path; project workspace ID and safe association/lease state. Existing authorized workspace inspection supplies any further detail |
| `active_scope_summary`, freeform `status_note`, private diagnostic text | Omit raw text; derive a bounded explanation from allowlisted status/reason codes. Unknown codes have a generic explanation |
| `last_verified_sha` | Include only as verification evidence tied to the displayed PR; do not expose the protected recovery-gate head or diagnostic command payload |
| Stable item/scope/slot IDs, validated issue/PR identity, raw state, phase, finite counters, known timestamps | Include with the documented meanings; build external links from validated identities |

Do not alter legacy API responses as a side effect of this new projection. Redaction tests seed forbidden fields with sentinel values and check both serialized data and rendered summaries.

Keep the existing retry predicate authoritative. Extract other shared predicates only where needed for the existing operator actions. If reliable eligibility is unavailable, use `unknown` and link to the existing remedy surface instead of manufacturing an allowed action.

Eligibility describes work-item state. It does not grant caller authorization. Every mutation rechecks current identity, state, and credentials server-side.

Derive session links through verified team-slot/member/pane associations. Do not identify an owner by current working directory, display name, or a “most recent” unrelated session. Ambiguous sessions produce a team/slot-filtered Bridge link without automatically selecting a terminal.

For a verified offline owner or Leader, expose a link to that team's launch planner with the exact slot selected. Opening the link does not launch anything. The planner rechecks current state, requests operator authentication for the browser action, and requires review of the current plan before launching selected slots. Unknown actor identity leads to team inspection, not a guessed launch target.

Build external issue and PR links from validated GitHub identities and numeric IDs. The client builds internal routes from stable IDs. Loading a Mail link only reveals context through the existing read contract; it does not send a message or check an agent's inbox.

### Errors and performance

Preserve existing actionable error detail codes. New read errors use a structured detail containing `code` and `message`. A database or projection failure produces an error state, not zero counts.

Bulk-load work-item authority and associations. Query counts must remain bounded as the page grows from one to 100 records. No per-row CLI call, GitHub request, or filesystem discovery belongs in a work list. Add indexes only after measuring query plans.

## Operator authorization prerequisite

This matrix was checked against `301e37c1e53e822a47a9572dc592e866df77f763`, including route dependencies and internal actor checks. Paths are under `/api/v1/agent-teams`. Reconcile it with the eventual merged `master` and record the resulting matrix and browser client signatures before implementation.

| Route family | Audited authorization | Reposition requirement |
| --- | --- | --- |
| PATCH/DELETE `/presets/{id}` | Operator | Preserve; deletion also needs the state guard below |
| POST `/presets/{id}/github-scopes`; PATCH/DELETE `/github-scopes/{id}`; continuation policy | Operator | Preserve for activation, merge, and finite-budget policy |
| Add/edit/delete/reorder slots; create/reprobe/force-release workspaces | Operator | Preserve state checks as well as authentication |
| POST `/github-work-items/{id}/retry` | Session-or-operator, with an authenticated connected MCP session bound to the current Leader for the agent path | Browser uses operator credentials; retain the legitimate Leader path and retry state predicate |
| POST plan-launch/launch and the launch-plan alias | Session-or-operator; `_require_safe_agent_launch` constrains agent requests | Browser uses operator credentials; preserve the existing safe agent path and plan confirmation |
| Resume attempt, abandon, active-revision cancellation, checkpoint release | Operator | Preserve remedy-specific state and authority checks |
| Continuation-request cancellation | Session-or-operator with internal actor checks | Preserve request cancellation separately from operator-only active-revision cancellation |
| POST `/presets`, `/presets/from-agent-mail`, `/presets/from-agent-bridge`, `/presets/{id}/duplicate` | No route-level authentication at this snapshot | P04 prerequisite: require operator authority for these browser/API creation paths and update their clients together |
| New explicit Leader assignment | Planned in P04 | Operator plus expected-state and quiescence checks |

The safe agent launch path requires an authenticated connected MCP session with capability tokens enabled. It rejects prompt/repository overrides, inclusion of disabled slots, forced respawn, adoption of unbound sessions, and bypassing plan confirmation. Do not replace this contract with blanket rejection of all agent sessions. The same distinction applies to legitimate current-Leader retry.

Agent work-report, acknowledgement, continuation-claim, and dispatch-credential routes can enforce authority inside their handlers. Absence of a `require_operator` dependency does not establish that they are unprotected. Preserve their owner/Leader/lease contracts; an operator credential cannot impersonate those roles.

P04 hardens the four creation/import/duplication route families before the wizard uses them. Inventory existing browser and API callers, update credential handling and compatibility documentation in the same change, and keep authenticated agent tool behavior separate. A discovered caller needing creation authority requires an explicit reviewed contract, not a broadly accepted Mail token.

Reuse the existing per-tab operator credential helper throughout the shell. Measure prompt frequency, task interruption, and multi-tab friction in the pilot. A cookie/session login would change authentication and CSRF handling; evaluate it separately if the measurements justify it. No new login model is assumed by M2.

After G00, observational delivery work can proceed while remaining guards are completed. Do not expose a new mutation path until its server and client contracts agree. Tests must accept each intended principal and reject credentials outside that route's authority.

### Team deletion prerequisite

At the audited snapshot, `delete_preset` is operator protected but lacks an in-use-state check before reassigning Mail sessions and cascading team records. Scope deletion already rejects leases and work in pending, dispatched, verifying, review, escalated, or failed states. Do not describe team deletion as guarded merely because it requires an operator.

The release owner/coordinator must land a focused guard in M0 or as a post-G00 prerequisite before M1a acceptance. Require team automation disabled and check every scope using at least the existing scope-deletion predicate, plus pending approvals and nonterminal revisions. A leased workspace or in-use record returns a structured `409` before any session reassignment or delete. Check and delete in one transaction with concurrency protection so dispatch, approval, or lease acquisition cannot slip between them. Test all API/service entry points, rollback, and races. No force-delete bypass or silent stopping/releasing of work is introduced.

This is stricter than the Leader-edit quiescence rule: a queued or escalated item still blocks deletion under the existing scope rule. A safe error identifies the blocking records and existing inspection/remedy links. Only genuinely deletable teams exercise P05's retained-history path.

## Harness operating contract

In M1b, after the M1a pilot checkpoint, P03 adds `GET /api/v1/providers/{provider_id}/operations`. Existing provider registry and native capability responses remain backward compatible. M1a's thin Harnesses index uses the existing registry/status reads and does not call this planned endpoint or promise its richer readiness classifications.

The response separates `operations`, `native_capabilities`, `native_surfaces`, and `readiness`. Operational keys are:

| Key | Meaning |
| --- | --- |
| `launch` | Launch a provider through Deck's validated launch contract |
| `observe_session` | Discover and associate running sessions |
| `mail_identity` | Establish authenticated team-slot identity |
| `receive_work` | Receive briefs and valid wake delivery |
| `report_work_status` | Use structured status reporting |
| `approval_participation` | Participate as the designated actor under server authority |
| `workspace_association` | Work in the assigned leased checkout |
| `resume_exact` | Resume an identified session with the documented project/identity conditions |
| `interactive_terminal` | Use the existing Bridge terminal mode |
| `execution_controls` | Expose supported native permission or sandbox controls honestly |

Each entry has `state` (`supported`, `conditional`, `unsupported`, or `unknown`), `reason`, and explicit `conditions`. Initial classification requires source and fixture evidence; support for a CLI flag alone does not establish complete recovery support.

Readiness fields are:

- `configuration`: `ready`, `blocked`, or `unknown`, with installation, compatibility, and Mail integration checks.
- `credentials`: `ready`, `blocked`, or `unknown`, with the source and time of a safe check when one exists.
- `session`: `bound`, `offline`, `ambiguous`, or `unknown`, scoped to a team slot when requested.
- `observed_at`: the observation timestamp.

Use the UI phrase **Configured for launch** for configuration readiness. Unknown credentials remain **Credentials not checked**. A generic provider response does not claim a particular repository's worker is bound.

Readiness checks must be local, bounded, read-only, and non-billable. Do not contact a model to turn an unknown credential state into a green badge. Reuse existing installation and launch checks so the screen and launch planner agree.

For Pi, preserve the extension opt-in, supported runtime conditions, exact project-local resume, and current execution-policy limits. Capability metadata cannot imply that Deck adds a sandbox to Pi.

### Native page availability

Existing capability flags describe provider or integration functionality. They do not establish that Deck has a page or editor for that function. At the reference commit, OpenCode configuration, plugins, and usage have positive capability classifications despite lacking corresponding native pages; Copilot also has integration or inventory capabilities without matching editors.

In **M1a**, P02 owns a checked-in registry mapping each `(provider_id, surface, adapter_id)` to its component, provider-specific read API adapter, explicit supported write actions, and access level. The registry enables only implementations verified on the merged base. This static guard is sufficient for M1a native links and pages; it has no dependency on P03 or a new catalog endpoint.

In **M1b**, P03 adds a `native_surfaces` catalog keyed by surface name. Each entry has `state` (`available`, `unavailable`, or `unknown`), a nullable stable `adapter_id`, `access` (`none`, `read_only`, or `read_write`), a reason, and any conditions. Unavailable or unknown entries have no adapter and `access: none`. Keep the existing capability matrix backward compatible.

When M1b integrates the catalog, require both an available catalog entry and a matching checked-in adapter before mounting a native page or fetching its data. Intersect the catalog and adapter access levels; read-only entries cannot expose writes. Missing, mismatched, or unknown entries render an explanation and supported alternatives without mounting a legacy editor. Do not silently fall back to M1a permissions if a required M1b catalog read fails. API paths come from reviewed adapters, never arbitrary response-provided URLs.

Initial entries enable only surfaces with verified implementations on the merged base. OpenCode configuration/plugins/usage and Copilot integration-only surfaces remain unavailable as native pages unless a dedicated adapter is implemented and tested. Links to existing Agent Mail installation or launch configuration remain separate operations. Apply the same registry to Harnesses links, canonical routes, legacy aliases, and native dashboard cards; checking `!isCodex` or a positive capability flag is insufficient.

These page permissions restrict client behavior. Existing backend authorization and provider-specific mutation checks remain authoritative. P02 freezes M1a adapter fixtures first, including positive capability flags without pages. P03 reuses those fixtures and adds catalog agreement/mismatch cases before M1b integration. This later fixture review cannot delay the M1a pilot.

## Explicit Leader assignment

P04 adds nullable `leader_slot_id` to team presets and exposes the resolved assignment in team reads.

Migrate existing presets once by selecting the same enabled slot that the current backend designates: order by `position`, then `id`. Preserve preset, slot, member, approval, work-item, attempt, and lease identities. Presets with no enabled slot remain unassigned.

Inventory caller ordering as well as the resolver: `_leader_slot` sorts by position, while audited production callers load slots by `(position, id)`. No current production authority disagreement was established. Prove migration equality for tied positions, disabled slots, no enabled slot, and pending authority using each real consumer. Replace both Python and SQL inference with the explicit assignment. A position uniqueness constraint or reorder normalization is not required for this migration.

After migration, resolve authority through the explicit field. Roster order and descriptive role text no longer choose the Leader. An absent or invalid assignment blocks automatic dispatch instead of silently selecting another worker.

Add a dedicated operator-protected Leader update route. Its request carries the new slot ID, expected previous assignment, expected preset update timestamp, and a reason. A mismatch returns `409`.

Changes require team automation disabled and a quiescent team: no dispatched/verifying attempt, pending approval, nonterminal revision, or leased workspace within its scopes. Validate same-team membership and enabled state. Reject disabling or deleting the designated Leader until a valid replacement is selected through this procedure.

Apply the resolver to routing fallback, initial and continuation approvals, participant lookup, prompts, monitoring, and the frontend. SQL approval guards must agree with the explicit assignment; a Python helper alone cannot replace those checks.

Copying teams maps the assignment to the new slot IDs. Import and creation flows surface an explicit selection before activation. Single-agent manual teams remain valid; autonomous work still requires an owner and a distinct eligible approver.

Rollback cannot silently reinterpret assignments through roster order. Before downgrade, pause automation, quiesce attempts/approvals/revisions/leases, stop relevant writers, and back up the database. Record each explicit assignment against the legacy `(position, id)` resolver. If any differs or is unrepresentable, refuse an ordinary downgrade and keep the explicit-authority version until a reviewed authority-preserving repair is available. For a representable assignment, validate the downgrade against a restored backup and compare every authority reference before production use. Restoring a pre-upgrade database also loses later work and requires separate release approval; it is never an automatic rollback step.

## Guided repository setup

P04 composes existing team, scope, installation, and launch APIs, plus the bounded preflight below. The flow is Repository, Team and roles, Routing, Policies, and Review. Describe it as guided configuration: host credentials, native installation, and any required restart remain operator procedures.

Maintain a local draft until the operator confirms writes. Existing APIs may commit each step independently; track created IDs, show partial completion, and resume only the remaining steps. Do not present several REST commits as an atomic transaction.

### Saving new and reused configuration

| Record selected by setup | Save behavior |
| --- | --- |
| New team | Create with `autonomy_enabled: false` |
| Existing team | Preserve its automation flag, existing roster/Leader, and other scopes unless a separate reviewed change is requested |
| New repository scope under either team type | Send `enabled: false` in the creation request; the existing API defaults to true, so omission is unsafe |
| Existing scope found during selection or interrupted setup | Reconcile its ID and current state; show existing configuration and review any requested edits without resetting activation or applying new-scope defaults |

Writes to reused teams must omit activation fields rather than replaying a stale saved value. Human merge and existing finite defaults apply to new scopes. Saving an additional repository never pauses another repository or starts intake for the new one.

Reusing an active team initially keeps its current roster and Leader. A requested Leader change uses the dedicated protected route and its paused/quiescent preconditions. Show the block and allow the operator to retain the assignment or choose another team. The wizard must not pause an active team to make a role edit possible; any such pause and authority change is a separate reviewed operation.

Launch remains a separately reviewed current launch plan with explicit slot selection. Automation activation is another explicit action after readiness. For an already active team, activating the new scope affects that scope. If activation also requires enabling a team, preview every already-enabled scope that would resume and obtain confirmation for that concrete team-wide effect. Partial-save or lost-response reconciliation preserves these boundaries.

### Setup preflight

Add an explicit operator-protected `POST /api/v1/factory/setup-preflight` that performs observations only. Accept validated GitHub owner/name, the selected local checkout reference, dispatch/design label names, and selected dispatch-auth mode. It is an explicit **Check access and labels** action; ordinary factory GETs still never contact GitHub. Use bounded timeouts and the existing GitHub integration, without creating labels, changing credentials, polling issues into work items, or requesting model execution.

Return `observed_at` and separate checks for local checkout identity, polling credential presence, repository readability, each selected label's existence, selected dispatch-auth configuration, and operator credential configuration. Each check reports `ready`, `blocked`, or `unknown`, a safe reason code, and a remedy. A rate limit, timeout, or unavailable probe remains unknown. Repository readability proves read access at the observation time, not future push/merge authority. Declared auth mode or configured credentials alone never becomes successful access.

If operator authentication is unavailable, show the existing credential prompt and host setup instructions before preflight. Do not bypass the protected endpoint to inspect configuration; an authentication failure is not a successful host-status check.

Use an allowlist of effective configuration key names and boolean presence only, sourced from parsed server settings. Never return environment values, key-file contents/paths, credential hashes, or a raw `.env` inventory. The Review screen explains the applicable host procedure: configure `github_token` and `operator_token` in `backend/.env`; configure the existing GitHub App settings only when that mode is selected; install required harness/Mail integration; apply the documented backend restart when settings change; create missing labels on GitHub; then repeat the check. Do not collect host secrets in the wizard. Show runtime recovery-only restrictions separately from credential readiness.

Saving disabled configuration is allowed with gaps. The activation review lists blocked/unknown checks, their observation time, remaining host steps, and overlap warnings. It cannot label the repository ready until required checks pass, and cannot offer guided activation while a required check is blocked or unknown. Recheck after relevant draft changes and immediately before activation; report any race or server conflict without claiming a preflight guarantees dispatch. Existing API activation semantics remain authoritative.

### Overlapping repository scopes

Existing dispatch tracks issues independently per scope; a shared repository scheduler job does not arbitrate ownership across teams. P01's repository reads report a potential collision when scopes with both team and scope enabled watch the same normalized GitHub repository identity with the same dispatch label. Check all relevant scopes for that repository, including teams outside the view's filters, using bounded bulk reads. Include the conflicting scope/team IDs and labels without merging their work rows. Disabled scopes may be shown as prospective overlaps, distinct from an active collision.

P02 shows the warning on repository summaries/details in M1a. P04 checks the proposed activation against current enabled scopes and any sibling scopes a team-enable action would resume. The review must show **This can dispatch the same issue more than once** and require explicit acknowledgement of the displayed overlap before that activation action. Reconcile changed conflicts before proceeding. This is an advisory configuration decision, not an atomic cross-scope ownership guarantee; do not claim detection of all possible overlapping label combinations.

Deliberate overlapping scopes remain supported. This packet adds no dispatch lock, arbitration engine, issue deduplication, or automatic policy rewrite. A future exclusivity rule requires a separate product and scheduler contract.

## Audit and outcome measurement

P05 introduces a durable event ledger using the existing database migration mechanism. Planned fields are event ID, occurrence and recording times, event kind, source, actor kind, nullable authenticated actor reference, nullable live team/scope/item and revision/request references, immutable context snapshots, a correlation ID, sanitized reason, allowlisted before/after values, and action outcome. `action_outcome` (`applied`, `rejected`, or `uncertain`) is separate from the delivery outcome below.

An operator using the current shared credential is recorded as an operator with no invented personal identity. Never store the credential, a credential hash, or a copied agent token.

Record policy and Leader changes in the same transaction as their database mutations. Roll back the policy change if the audit insert fails. Recovery actions must record the outcome they actually establish; transport or external-write uncertainty remains explicit.

Use new forward lifecycle events to calculate terminal times and attempt durations. Existing row timestamps support current-state observations, not a reconstructed complete history. Imported snapshots are labelled `observed_snapshot` at import time.

### Delivery outcomes and evidence

Preserve raw dispatch statuses and record a separate `delivery_outcome` for each tracked attempt. It remains null while work is ongoing and no delivery or terminal disposition is established:

| Outcome | Required evidence |
| --- | --- |
| `delivered` | A sourced merged PR associated with the attempt, or a recorded independent human acceptance of the exact design artifact/version |
| `closed_without_delivery` | Terminal tracking plus sourced evidence that this attempt ended without delivery, such as a confirmed duplicate/not-planned disposition or its PR closed unmerged with no continuing attempt |
| `unknown` | Terminal tracking state without evidence sufficient to establish either outcome |

An issue's closure or `completed` status alone yields `unknown`. A failed design issue closed without a PR must not increase delivered or human-reviewed design counts. A design PR merge can establish delivered design work, but does not by itself establish independent human review. Record the completion kind and review evidence separately.

Cancelling a continuation request/revision, releasing a workspace, or escalating an item does not alone prove that the tracked attempt ended. The existing abandon route records an operator escalation, not terminal abandonment: retain its action outcome while `delivery_outcome` remains null unless other evidence establishes an outcome. A later retry or issue update cannot turn that escalation into a past non-delivery count. Use the same terminal-state/evidence rules in reads and metrics.

Evidence records identify their source, fact kind, repository/artifact identity, PR and head/version where applicable, occurrence time when known, and observation time. Human-reviewed design counts require attributable independent human acceptance/review evidence for that artifact/version. Leader approval, `merge_policy: human`, an issue state, or a write through a human-owned credential does not supply that evidence. If existing integrations cannot establish it, report human review as unknown; factory GETs do not fetch new GitHub evidence.

Keep terminal-tracking counts, delivery outcomes, and human-review counts distinct. Report sample counts and unknown/excluded outcomes with their reasons. Name the counting unit; tracked attempts across different scopes remain distinct and cannot be advertised as a unique-PR total. Later evidence appends a sourced event and reconciles the attempt's classification without double-counting delivery. Routine issue closure after a proven delivery does not downgrade that result.

### Historical retention and attribution

Deleting a team or scope can currently cascade to its work items. The team-deletion guard above is a required prerequisite; it is absent at the audited snapshot. Ledger rows must survive deletion permitted by the completed guards. Any foreign keys to operational records use `ON DELETE SET NULL`; they must neither cascade-delete the event nor add a new deletion block after those guards pass.

Snapshot the original team/scope/item/slot identities and creation timestamps, team display name, GitHub owner/name and issue/PR identity, issue type, non-secret attempt/revision identity, and known harness attribution when recording the event. Allocate immutable context keys so reused numeric database IDs cannot attach old events to new records. Keep configured-at-event and observed-runtime harness values distinct; absent evidence stays unknown.

Event facts and context snapshots remain immutable when live references are nulled or teams, repositories, or slots are renamed or reconfigured. Metrics use these snapshots and event evidence instead of inner joins to current operational rows or the slot's current provider. Keep the ledger for the life of the Deck database; no automatic purge is part of P05.

Audit/metric responses expose historical context keys and snapshot labels. Accept `team_context_key` and `scope_context_key` filters for retained history; current-ID filters resolve the current resource's context key. Deleted records remain inspectable through historical keys, with unavailable live links labelled. Ordinary factory detail routes still return `404` for deleted resources.

Planned endpoints:

- `GET /api/v1/factory/audit-events`: operator protected, filtered and paginated.
- `GET /api/v1/factory/metrics`: safe aggregates with window, sample count, source, and coverage.

Separate merged code, delivered design, independently human-reviewed design, explicit non-delivery, unknown outcomes, recovery, and intervention metrics. Cost is null/unknown when measured attribution is unavailable; partial harness coverage cannot be presented as total factory cost.
