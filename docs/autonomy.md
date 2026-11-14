# Autonomous GitHub dispatch

This guide is for the operator of a Albiex Synth City team. Autonomy is off until you enable it for the team, and a watched repo can also be paused separately.

## Before enabling

1. Give the watcher GitHub access and configure the operator token described below before editing the roster. The code defaults that start the dashboard do not supply these factory settings. Add `github_token=<token>` to `backend/.env` and restart the backend. The watcher uses this host token to poll GitHub; private repos cannot be polled through GitHub App settings alone. If you use App-backed dispatch, also configure `github_app_id`, `github_app_private_key_path`, and `github_app_bot_login`. The repo card distinguishes a missing polling token from a dispatch mode not yet selected. Synth City selects the dispatch mode when eligible work is dispatched, not on the first poll. A selected mode is not proof of successful access; check the last poll and Activity.
2. Assign the Leader explicitly and launch it. Guided repository setup names the Leader slot for a new team. For an existing team, use **Set Leader** on an enabled slot in Roster while team automation is off; the server also requires a quiescent team. The team's `leader_slot_id` supplies Leader authority. Slot order and the Role field do not select it. The Leader approves plans and takes issues that no other slot matches.
3. Add a watched repo. Give its GitHub owner/name and an existing primary clone under your home directory. Synth City creates a separate issue worktree beside that clone; ordinary slot sessions keep using their own repo path.
4. Create the dispatch and optional design/area labels on GitHub. Adding the dispatch label queues an issue; an area label routes it to a matching owner. Without one, Synth City uses slot expertise and finally the Leader. A design label on the same issue uses the human-review design pipeline. Removing the dispatch label during an attempt escalates it.
5. Choose merge policy and finite budgets. Human policy leaves PRs for review. Auto policy merges eligible code PRs after checks pass, subject to the daily cap; design PRs always need human review. Enable autonomy when the roster and watched repos are ready.

Synth City polls GitHub every 60 seconds by default. The Activity table refreshes every five seconds while open; it does not trigger another GitHub poll. Issues move through queued, dispatched, verifying, and ready for human review or merged. An escalated issue has stopped and needs attention.

### Dispatch priority and queue order

The Director can order ready issues with GitHub labels `priority:1` through
`priority:9999`. Lower numbers run first. The syntax is exact: lowercase,
positive decimal, no leading zero. If an issue has several valid priority
labels, the lowest number wins. Invalid labels are ignored. Explicit priorities
come before issues without a valid priority; ties and unprioritized work use
ascending issue number (oldest first), then work-item ID. GitHub poll order and
work-item creation time do not decide priority.

Each poll observes priority labels and clears removed values. Pending issues
are refreshed again before the dispatch batch is ranked. Existing databases
start with no explicit priority until labels are observed. Priority only orders
attempts within one watched repository scope. It does not admit dependencies,
preempt active work or order different repository scopes. The Leader still
handles dependencies written in prose. Keep dependent issues unready until
their prerequisites are satisfied.

All label, autonomy, pause/HOLD, routing/area, Leader, memory, reservation,
workspace and concurrency gates still apply. A high-priority item waiting for
its owner does not block eligible work for another free owner. Priority grants
no approval, retry, lease, release or merge authority.

The team summary's `campaign.dispatch_order` and the Progress card show the
complete observed pending attempt order, with repository, issue, effective
priority and position within that scope. This includes ready work outside a
selected campaign milestone; existing campaign counts remain milestone-scoped.
The list works when milestone backlog data is unavailable. It reflects the last
observed labels, not a guaranteed next launch: routing and capacity gates may
skip queued entries. Label changes appear after the next successful poll.

### CI polling permissions

The polling credential needs Checks:read and Actions:read for private repositories.
Synth City uses the configured host `github_token` for these reads. App dispatch credentials
do not replace the polling credential. Do not grant Actions write permission for polling.

Synth City reads current workflow runs and jobs before it classifies CI results. It ignores
an older execution only when the workflow and execution context prove replacement.
An incomplete or unavailable observation keeps the item unverified. It does not
consume a verification retry or a diagnostic failure budget. The status note gives
a short reason. Check credential access if this note persists.

CI observation is bounded to five pages per list, 64 requests and 45 seconds per
item. More than 16 current execution contexts is unavailable. These limits do not
establish that an incomplete history is green. Cancellation retains its existing
conservative accounting for unclassified pushed heads.

## Build hints

Synth City does not run the build command. The optional build settings are instructions in the owner's brief. An out-of-tree build directory may include `{issue_number}`. The command hint may include `{build_dir}` and `{parallelism}`. The parallelism value also tells the agent to cap build jobs.

## Leader plan-approval wait

The initial plan clock starts when the bound approval request is created.
`github_leader_ack_timeout_seconds` defaults to 300 seconds. At that boundary,
Synth City sends one Leader reminder and a system notice to the team's currently
bound Supervisor. The pending request, builder lease and workspace stay intact.
The reminder cannot interrupt a running provider turn.

Positive activity from the current authenticated, bound Leader can preserve the
request until `github_leader_ack_max_wait_seconds` (default 1800 seconds) from its
creation. This is a fixed maximum, not a sliding renewal. Native working evidence
is read with bounded effort and checked against the current process/session
identity. Recent authenticated Mail/MCP contact within the initial window can
also qualify. Display status, stale or future contact, retired panes, unknown or
ambiguous identity, and native requests waiting for human input do not qualify.
An inactive request can expire after the one reminder's existing
`github_nudge_grace_seconds` (default 180 seconds). The hard maximum always ends
an unanswered request with `leader_ack_timeout`. Durable reminder and extension
records survive service restarts and prevent repeated notices.

An operator can set nullable `leader_ack_timeout_seconds` and
`leader_ack_max_wait_seconds` on the team preset through the existing protected
`POST /api/v1/agent-teams/presets` and `PATCH .../presets/{preset_id}` routes.
Both fields accept integer seconds from 30 through 86400. The effective maximum
must be at least the effective initial window. Omission on PATCH preserves the
value; explicit `null` restores the global default. Preset responses expose the
overrides, and duplication and creation from Mail/Agent Bridge preserve them.
For example, `{ "leader_ack_timeout_seconds": 600,
"leader_ack_max_wait_seconds": 2400 }` gives a team a ten-minute initial window
and a forty-minute maximum. Design items multiply both windows by
`github_design_ack_multiplier` (default 3).

Leader guidance: finish a running turn normally, then read the pending request
and record an explicit approval or rejection. Activity and a soft notice grant
no approval. The owner still needs the current normalized plan decision and
acknowledgement before implementation. Pause, HOLD, offline, binding, dispatch,
lease and review gates retain their existing force.

## Ordinary review corrections

An initial implementation plan remains the basis for work while its normalized
approval and owner acknowledgement remain valid. Opening a PR or reaching
`ready_for_review` does not end that plan. The Leader sends review findings back
to the current owner. The owner can correct findings within that same plan on
the existing branch and PR after reconciling owner identity, dispatch nonce,
workspace lease and approval evidence. Operator pauses and safety holds stop
work. Missing or stale authority must be resolved before edits.

`continuation_disabled` describes recovery of an escalated attempt. It does not
by itself prohibit ordinary corrections under an existing initial approval.
Do not escalate, retry, release the workspace, change recovery policy or request
a continuation just to make in-scope review corrections. Do not send a second
`pr_opened` report for an already tracked PR.

Every pushed head needs independent review and hosted CI for its full SHA.
Previous review acceptance and CI readiness apply to the previous head. Preserve
the configured merge policy; human policy still requires human merge. The owner
context returned by `synth_city_get_work_item_context` includes `review_rework_guidance`;
that text explains the workflow and does not grant approval.

This rule applies to nonterminal, non-escalated initial implementation attempts
with `active_scope_revision=0`. Scoped and diagnostic continuations retain their
approved paths, commands and finite budgets. Completing one does not grant
authority for another head. Work outside the approved plan requires a supported
new approval.

## Recovery and operator token

An escalated issue with an open PR may be continued within a bounded scope revision. The owner proposes a plan, allowed files, and allowed commands; the Leader approves; the owner continues in the same workspace. A failed head is a pushed PR commit whose GitHub checks fail. The policy caps revisions and failed heads so recovery cannot loop indefinitely. A checkpoint hold pauses the Leader's decision or owner's acknowledgement until an operator releases it.

To create an operator token on the Synth City host, run `openssl rand -hex 32`, put the result in `backend/.env` as `operator_token=<value>`, run `chmod 600 backend/.env`, and restart the backend. Do not export this token into the agent environment. The UI stores it only in the current browser tab and asks for it when you edit the roster, watched repos, autonomy settings, recovery policy, or use operator remedies. The current authenticated Leader can request an eligible retry through Agent Mail without the operator token. Ordinary issue dispatch does not need the token. This token does not isolate agents running under the backend's OS user: such processes can read `backend/.env` despite its `0600` permissions.

Planning or launching a team requires an authenticated agent session or the operator token. Agent sessions can use the configured roster but cannot override launch prompts or paths, include disabled slots, force a respawn, or bypass plan confirmation. Terminating a session through Agent Bridge requires the operator token.

Plan launch reuses only a live pane already bound to its slot. A discovered pane with no verified slot binding blocks the default plan; it is **not** silently promoted to Leader. An operator can request a new plan that explicitly marks such a pane for adoption and names its tmux target and PID. Review the pane and its startup instructions before selecting **Adopt and launch**, or choose a forced fresh spawn instead. Agent sessions cannot request adoption. Agent Bridge's raw spawn route accepts a minimal same-repository plain spawn from an authenticated agent session, but requires the operator token for prompts and other overrides; the legacy CC Bridge spawn and kill routes are operator-only. This does not isolate same-UID agent panes from the backend's operator token or direct tmux access.

If the card says the polling token is not set, check `github_token` in `backend/.env` and restart the backend. A card that says the dispatch mode is not selected can remain that way after successful polls if no issue is eligible for dispatch. If Activity reports an auth error, verify the host token's repository access or the GitHub App installation and settings before retrying.

### Required-check completion and stopped teams

The Leader registers the assigned independent reviewer with
`synth_city_watch_required_checks(work_item_id, dispatch_nonce, scope_revision,
head_sha, reviewer_member_id)`. Use the full current PR SHA and repeat registration
for every new head. Pass `null` to clear the reviewer. The current designated Leader
and a current enabled reviewer from the same team are required; the owner cannot
be their own reviewer. A watch does not approve a plan, accept a review, change a
retry budget, or authorize a merge.

The existing verification monitor records each configured required check by exact
name, app slug and head. Missing or ambiguous evidence stays unknown. A legacy
policy without named required checks does not produce a required-check completion
notice. On the first completion for an attempt revision/head, success notifies the
Leader and registered reviewer; any required failure notifies the owner and Leader
with the failed check named. Repeated polls and backend restarts reuse durable
recipient records. A reviewer registered after completion can receive that same
completion once. Same-head reruns update the visible results without creating a
second completion event; a changed head needs its own watch and fresh evidence.

Mail and wake claims are durable before external delivery. Each recipient gets at
most one wake attempt per completion. A crash during a wake cannot prove delivery;
that claim remains unconfirmed, and the view says **checks finished, no next actor**.
The Leader reconciles the current owner/reviewer instead of relying on a manual CI
watch. No automatic check reruns occur. Independent acceptance, required hosted
checks and the configured merge policy remain separate gates.

The progress panel shows required-check counts and wake confirmation. The team
summary and Supervisor check-in expose advisory `team_idle` items after no semantic
mail/check/item-state progress for `GITHUB_TEAM_IDLE_TIMEOUT_SECONDS` (default 1800,
valid 30–86400). Polling, summary reads, heartbeats, system notices and Supervisor
check-ins do not renew this clock. Its first trusted observation starts a baseline;
no pre-upgrade idle duration is guessed. Human, native-input and external-check
waits, OFF/HOLD and incomplete bounded observations suppress this signal. Actual
progress clears it. Last actor names come from authenticated recorded evidence;
otherwise the view says Unknown. Idle attention grants no execution authority.

### Unanswered explicit requests

The team summary and the Supervisor check-in also show **unanswered requests**: a pending
Agent Mail `context_request` or `handoff` that is addressed to an idle member of the team and
is older than `MAIL_REQUEST_UNANSWERED_SECONDS` (default 1200 seconds, valid 60–86400; an age
equal to the threshold counts). The team card shows "C1 has not answered L1's request for 25
min" and the Supervisor line shows a second sentence with the count and the age of the oldest.
The names are display names only. A subject, a body or a payload is never shown.

- Only an **explicit** request counts. A plain message that asks for something carries no
  request marker, and Albiex Synth City does not guess from prose. Send a request that needs an
  answer as a context request addressed to the member directly.
- A request leaves the view when it is answered, superseded or acknowledged, or when the
  addressed member sends a plain reply in the request's own thread. A message from any other
  member, including the requester, never clears it. Approval requests have their own timeout
  flow and are not listed. A working member is active, so its requests are not listed.
- The view says when it is **incomplete**, with a fixed reason: `candidate_limit` (more than 64
  unresolved requests, or older history than the budget below was not examined), `native_unknown` (a member's activity is unknown, stopped or could not be
  read in time), `ambiguous_legacy_request` (an older request nested inside a thread cannot be
  matched to a reply), `reply_scan_limit` (the reply check reached its bound) or `entry_limit`
  (more than 16 unanswered requests; the count of those not listed is shown). A truncated or
  unproven view is never shown as complete.
- Requests are examined oldest first, page after page, and a request that is provably answered,
  including one answered only through an older nested reply in its own thread, is skipped without
  counting. The first 64 requests that are not provably answered are evaluated, and a 65th means
  `candidate_limit`. All of the reading shares one budget: 256 reply rows, 512 reads (each examined
  request is one read) and five seconds. History beyond that budget is reported as incomplete,
  never as complete, and it is not claimed to have been examined.
- The signal grants no authority and does not change `team_idle` or the next actor.

### Thread view limits

A thread read returns at most 500 replies. It reads the thread breadth first, by depth and then by
id, with indexed page reads, so the work depends on the replies kept and not on how many
descendants exist. The depth bound is 33. A thread with at most 500 replies and a depth below 33
is returned whole, in the usual order (creation time, then id).

When a thread is **truncated**, the reply list says so with `replies_complete: false` and the
reason `reply_limit` (more than 500 replies) or `depth_limit` (a reply at depth 33). A truncated
view holds the 500 replies with the smallest ids by depth and then id. It does **not** hold the
500 earliest replies by time, and it must not be read that way. The kept replies are still shown
ordered by creation time and id.
