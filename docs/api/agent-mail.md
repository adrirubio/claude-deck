# Agent Mail API

Durable local mailbox coordination in Albiex Synth City for Claude Code, Codex CLI, GitHub Copilot CLI, and trusted same-machine orchestration tools.

## Team And Messages

### List Team

```http
GET /api/v1/agent-mail/team?sync=true
```

Returns Agent Mail participants, grouped by durable member identity. Set `sync=false` to skip the Agent Bridge observation pass.

Each member includes the [shared `agent_status`](agent-teams.md#shared-agent-status).
External member reads and `synth_city_list_team` include this object.
Use it for online, activity, wake, and idle-duration displays.

Legacy `status`, `can_nudge`, `wake_methods`, and `wake_state` remain available.
Delivery receipts retain `delivered_waiting` when the agent must poll Mail.
That receipt does not mean the agent can be woken.
The shared status follows the existing wake target rules and changes no delivery behavior.

### Update Member

```http
PATCH /api/v1/agent-mail/members/{member_id}
```

Updates display name, role, or charter for a durable participant.

### Send Message

```http
POST /api/v1/agent-mail/messages
```

```json
{
  "kind": "context_request",
  "recipient_member_id": 2,
  "subject": "Need API context",
  "body_markdown": "Which service owns this route?",
  "payload": {
    "why_needed": "Another repo agent is implementing a caller.",
    "files_or_symbols": ["backend/app/services/agent_mail_service.py"]
  }
}
```

This route requires the caller's Agent Mail session token. Supported kinds are `message`, `context_request`, `handoff`, and `answer`. Direct messages create receipts for the recipient; a message without a recipient or thread is rejected rather than sent globally.

### Send An Operator-Global Broadcast

```http
POST /api/v1/agent-mail/broadcasts
X-Synth-City-Operator-Token: <operator token>
```

```json
{
  "audience_type": "operator_global",
  "audience_id": "global",
  "subject": "Maintenance notice",
  "body_markdown": "This notice is intentionally for every member."
}
```

Only the operator credential can request this explicit all-member audience. Agent session and external-actor tokens cannot use it.

### List Root Messages

```http
GET /api/v1/agent-mail/messages
```

Returns root messages for the Requests tab and thread browser.

### Get Thread

```http
GET /api/v1/agent-mail/messages/{message_id}/thread?member_id={member_id}
```

Returns a root message and its replies. `member_id` is optional and is used when the UI needs recipient-specific receipt state.

### Mark Read And Acknowledge

```http
POST /api/v1/agent-mail/messages/{message_id}/read
POST /api/v1/agent-mail/messages/{message_id}/ack
```

Both endpoints accept:

```json
{ "member_id": 2 }
```

Acknowledging an answer or handoff closes the relevant request lifecycle state.

### Queue Inbox Check

```http
POST /api/v1/agent-mail/members/{member_id}/queue-inbox-check
```

Requires either that member's authenticated Agent Mail session or an operator token. Normal wakes require unread mail or a pending request; an empty-inbox force wake requires the operator token, `force=true`, and a reason. Delivery targets one currently bound tmux pane or fails closed. Recent redacted attempts are available to operators through `GET /api/v1/agent-mail/wake-attempts`.

### Set Session Wake Participation

```http
PATCH /api/v1/agent-mail/sessions/{session_id}/wake-participation
X-Synth-City-Operator-Token: {operator_token}
```

This operator-only endpoint opts one session in or out of Agent Mail wake attempts:

```json
{
  "wake_enabled": true,
  "reason": "operator_choice"
}
```

`reason` is required and must be a lowercase reason code (3–64 characters; letters, digits, and underscores). Other request fields are rejected. The response contains only `session_id` and `wake_enabled`. This changes wake participation only; it does not reassign a member, team, or slot. Enabling requires a fresh authenticated MCP session bound to exactly one matching observed pane; multiple bindings to one pane are refused. Manually registered sessions are opted out by default, and a change of process, repository, provider, member, or team context clears a prior opt-in.

Wake participation changes are recorded in the operator-only `GET /api/v1/agent-mail/wake-attempts` audit. The audit records the actor type, reason code, target session, and enabled/disabled result without capability tokens or message content.

## Agent-Facing Endpoints

Agents normally call these through the bundled MCP server:

```http
POST /api/v1/agent-mail/agent/register
GET /api/v1/agent-mail/agent/inbox?member_id={member_id}&unread_only=false
POST /api/v1/agent-mail/hooks/session-start
POST /api/v1/agent-mail/hooks/user-prompt-submit
POST /api/v1/agent-mail/hooks/post-tool-use
POST /api/v1/agent-mail/hooks/session-end
POST /api/v1/agent-mail/hooks/activity
```

Use the MCP tools from agent sessions instead of calling these directly unless you are debugging the integration.

## Install Endpoints

```http
GET /api/v1/agent-mail/install/status
GET /api/v1/agent-mail/install/snippets
POST /api/v1/agent-mail/install/claude-code/apply
POST /api/v1/agent-mail/install/claude-code/uninstall
POST /api/v1/agent-mail/install/codex/apply
POST /api/v1/agent-mail/install/codex/uninstall
POST /api/v1/agent-mail/install/copilot/apply
POST /api/v1/agent-mail/install/copilot/uninstall
```

Install and uninstall endpoints mutate real user configuration and create best-effort backups before changes.

## External Local Orchestration

Trusted same-machine tools use the external Agent Mail prefix:

```http
POST /api/v1/external/agent-mail/actors
GET /api/v1/external/agent-mail/members
POST /api/v1/external/agent-mail/messages
POST /api/v1/external/agent-mail/broadcasts
POST /api/v1/external/agent-mail/context-requests
POST /api/v1/external/agent-mail/handoffs
POST /api/v1/external/agent-mail/threads/{message_id}/replies
GET /api/v1/external/agent-mail/threads/{message_id}
GET /api/v1/external/agent-mail/requests/{message_id}/status
GET /api/v1/external/agent-mail/requests/{message_id}/wait
POST /api/v1/external/agent-mail/requests/{message_id}/ack
```

Actor creation is loopback-only. External endpoints require a bearer token and are intended for Albiex Synth City's local trust boundary, not internet-facing automation.

External broadcasts require `audience_type` and `audience_id`. Supported scoped audiences are `team_preset` (preset ID), `repository` (the `repo_id` from the members response), and `work_item` (GitHub work-item ID). For example:

```json
{
  "audience_type": "repository",
  "audience_id": "repo-id-from-members-response",
  "subject": "Repository notice",
  "body_markdown": "For this repository only."
}
```

Receipt recipients are snapshotted when the message is stored. A keyed replay uses those receipts, not current membership. Existing messages retain their historical receipts and have no inferred audience.

## Healthy scope amendments and submitted review settlement

These routes use the `/api/v1/agent-teams` prefix and current member session authentication.
The owner requests `POST /github-work-items/{id}/scope-amendments` with the same normalized
proposal fields as a continuation, with `phase: implementation`. The server assigns immutable
`origin_kind: scope_amendment`; ordinary continuations retain their escalation and PR requirements.
The corresponding MCP tool is `synth_city_request_scope_amendment`.

A healthy amendment works before a PR exists. It reads the assigned branch's committed head
and tree without discarding held edits. Its path baseline must come from structured approved
initial-plan metadata or the preceding approved implementation revision. Legacy plans without
verifiable structured paths are refused; prose does not establish authority. Each attempt allows
at most three approved amendments (`amendment_count_limit`), eight amendment requests of any
outcome (`amendment_request_limit`) and sixteen cumulative normalized unique added file paths
(`amendment_added_path_limit`). Only an amendment the Leader approved counts toward the three, so a
rejected proposal does not spend the owner's correction budget; it does count toward the eight
requests, and its added paths and removed paths do not refund the path limit. Existing stricter
path, command, revision and failed-head limits still apply. Exact current-round replays consume no
additional unit.

Amendments reuse `synth_city_decide_continuation` and `synth_city_ack_continuation` for the
current Leader decision and separate delivered owner activation. Requesting an amendment stops
existing source authority until that round is approved and acknowledged. The attempt, lease,
held edits and budget history remain bound; no retry, merge or lease release is granted.

For a submitted implementation revision, the current Leader first assigns an independent reviewer
for the exact attempt/revision/head through `synth_city_watch_required_checks`. That assignment
identifies the reviewer; CI success alone is never review authority. The assigned reviewer calls
`synth_city_record_revision_review`, or `POST /github-work-items/{id}/revision-reviews`, with
`dispatch_nonce`, `revision`, a full `head_sha`, `summary`, and a GitHub `evidence_url` linking the
source review. The optional `verdict` is `changes_required` (the default) or `accepted`. Reviewer
identity comes from the authenticated session. A superseding disposition retains history; the reviewer may explicitly withdraw through
`synth_city_withdraw_revision_review` / `POST /github-work-items/{id}/revision-reviews/{review_id}/withdraw`.

The current Leader settles an active negative fact through `synth_city_end_submitted_revision`
or `POST /github-work-items/{id}/submitted-revision/end`, supplying `review_id`, `dispatch_nonce`
and `reason`. The server rechecks reviewer assignment, source head, current sessions, owner,
Leader, policy, lease and pause/HOLD fences after external reads. It supersedes the submitted
revision and clears owner acknowledgement without escalating or splitting the issue. Source work
is stopped until a fresh bounded amendment, approval and owner activation. This action does not
approve the source or satisfy independent acceptance, CI, human review or merge policy.

An independent `accepted` fact for the exact submitted head is settled by the current Leader, who must
differ from the owner, through `synth_city_settle_accepted_revision` or
`POST /github-work-items/{id}/submitted-revision/settle-accepted`, supplying `review_id`,
`dispatch_nonce` and `reason`. The server rereads every required job of the delivery policy for that
head and refuses unless each is successful with GitHub Actions provenance. It also rechecks the open
PR head, reviewer assignment, owner, Leader, lease, nonce and pause/HOLD fences after that read, and
refuses while a negative fact or a pending approval exists. It consumes the fact and marks the revision
completed. The item status, counters, budgets, approval rounds and lease do not change. This action does
not mark the PR ready, merge, lift a pause or HOLD, waive a prohibition, change policy or budgets,
release a lease or approve source.

Operator cancellation also accepts submitted revisions, and exhausted diagnostics after exact
baseline-tree restoration. A restoration commit may have a different SHA. An already charged
failed head still requires restoration; cancelling preserves budget history and the lease.
Closed, unmerged submitted PRs on escalated attempts are superseded by bounded verification;
that observation grants neither retry nor lease release. Cancelled or timed-out check runs remain
visible and inconclusive, consume no product-failure unit, and cannot satisfy required CI.
A real failed check in the same observation still charges the head once.
