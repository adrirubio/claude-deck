# Agent Mail

Agent Mail lets local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions coordinate as a user-directed team. Albiex Synth City keeps durable mail participants, groups them by repository, tracks ephemeral sessions under those participants, and gives agents structured mailboxes for context requests, handoffs, broadcasts, and replies.

Broadcasts require an explicit audience: an Agent Team preset, repository, or GitHub work item. Synth City stores that audience with the message and creates receipts only for members in it. Direct messages and replies retain their addressed recipients. An all-member maintenance broadcast requires the operator credential and explicit global intent; a missing audience never means “everyone.” Historical messages keep their original receipts.

## Authentication and upgrades

Agent Mail uses strict authentication by default on new and upgraded installs.
With a configured Director key, Mail reads require a current Mail session or the key.
The browser uses the shared Director key from Teams.
External actor creation requires a loopback connection and the Director key when configured.
External actor tokens permit only their own or explicitly addressed Mail threads.
A Director key does not grant a member identity or plan approval authority.

Existing authenticated agents keep their current session credentials.
A session with a Team slot must have its current live pane binding.
Restart an older agent integration if it has no authenticated session credential.
Registration verifies the local process binding before it grants a Team slot identity.
Generic registration can create an unbound session. It grants no Team slot authority.

An installation can explicitly set `MAIL_CAPABILITY_TOKENS_REQUIRED=false` before starting the backend.
The opt-out allows unauthenticated reads and legacy registration.
Member writes require a Mail session. Director writes require the Director key when configured.
It permits generic Mail reads, install information reads and content hooks.
It preserves legacy registration and session liveness behavior.
It also disables pane and offline session checks for existing capability credentials.
Closed sessions remain refused.
Invalid supplied credentials still fail.
Member writes require a Mail session.
Member metadata changes and external actor creation require the configured Director key in every mode.
Agent Mail shows a warning when the opt-out is active.
Remove the explicit opt-out or set `MAIL_CAPABILITY_TOKENS_REQUIRED=true` to restore strict authentication.
No database deletion or schema reset is required.

Strict mode protects install information when a Director key is configured.
Member metadata changes and Mail install writes require the configured Director key in every mode.
With no configured key, local Director actions and UI Mail reads work as before.
The UI recommends setting a Director key.
`GET /api/v1/agent-mail/authentication-status` is public by design.
It returns exactly `{ "director_key_configured": <bool> }`.
This response contains no credential, Mail, path or launch data.
The UI reads it before protected reads and after a 401 response.
Agent tools still require Mail session credentials. Actor reads still require actor credentials.
Content hooks require a member capability credential before they return Mail context.
A hook without a valid credential returns only `Check your Synth City inbox.`
This fixed reminder contains no message, member or launch data.
Native hooks can use this reminder with the authenticated MCP inbox tools.
Activity and session-end hooks remain available because they return no Mail data.
The explicit opt-out also leaves install information readable without a Director key.

## What It Is For

- Ask the agent that knows one repository to explain a local API, component, convention, or failure mode to another agent.
- Hand work from one repository agent to another with touched files and next steps.
- Keep short-lived agent sessions attached to a durable repo or Agent Team slot participant, so role and charter survive restarts and context compaction.
- Inspect team communication from Synth City without turning the product into a general chat app.

## Mail context inside Work

Work context reads relevant messages/threads using verified team/slot/member identity. Missing or mismatched associations do not guess a recipient. Reading context does not check an agent inbox, acknowledge a request, send a message, approve a plan or launch a session.

Standalone Agent Mail retains coordination/install workflows. Ordinary context replies and handoffs are separate from normalized agent plan approvals; operator remedies and human PR review remain distinct. A Role label, visible message or eligible action grants no authority. Durable handoffs should identify issue, PR and exact head without credentials.

See [Work](/features/work) and [Teams](/features/agent-teams). Existing install, wake and visibility limits still apply; factory navigation does not change them.

## How Agents Connect

Claude Code gets both MCP tools and command hooks:

- The MCP server exposes `synth_city_whoami`, `synth_city_list_team`, `synth_city_check_inbox`, `synth_city_send_message`, `synth_city_reply`, `synth_city_ack_message`, `synth_city_request_context`, and `synth_city_create_handoff`.
- Session and prompt hooks inject state-based mailbox context into the agent conversation.
- Hook failures are soft, so a Synth City outage should not break an agent session.

Codex CLI gets the MCP server through `codex mcp add` and lifecycle hooks for session registration, activity updates, and inbox reminders. Codex agents should still check their inbox through the MCP tools when starting and finishing work because hook delivery is a reminder path, not a replacement for agent action.

GitHub Copilot CLI gets the MCP server through `copilot mcp add` and user-level hook JSON for session registration, activity updates, and idle inbox reminders.

OpenCode CLI (OpenCode 2) gets three things from the Install tab:

- **MCP server:** `mcp.servers.albiex-synth-city-mail`, with `codemode: false` so that the Mail tools are direct tool calls. An older flat `mcp.albiex-synth-city-mail` entry that Synth City wrote is moved there. An entry under that name that Synth City did not write is refused, not overwritten.
- **Lifecycle plugin:** an OpenCode 2 plugin. An OpenCode 1 plugin never loads on OpenCode 2, so it shows as **Needs update**, and **Set up** replaces it in place.
- **Question deny:** a `permissions` rule that denies the question tool, so unattended members never stall on a question. The plugin also denies it for team members, and every team launch carries the same rule.

Everything is read and checked first. A malformed config file is refused before the backup and before any write, and each file is replaced atomically. Synth City records whether it added the deny rule. **Remove** deletes the rule only when that record proves it added it to that file and the file still has exactly one such rule; a rule you added yourself is kept.

If a team member still opens a question or a permission prompt, the plugin reports it and Synth City sends the bound Supervisor (or the Leader) the usual "Waiting for input" notice. When the order of reports cannot be proven, the wait is kept rather than cleared. This is a notice only: the activity view does not show OpenCode waits yet.

Pi uses the repository-local Agent Mail extension. Synth City passes it explicitly on Synth City launches and changes no global Pi configuration. The Install tab shows only its readiness; it has no Pi install action.

## Delivery Nudges

When a message is delivered to a reachable Claude Code, Codex, or Copilot member, Synth City tries to wake it with an inbox-check prompt. The automatic nudge is best-effort and throttled per recipient, so rapid message bursts do not keep injecting prompts into the same session. The **Queue inbox check** button remains available for a manual retry when the UI shows unread or pending mail.

Synth City uses one visible wake path:

- tmux-observed sessions can be nudged through Agent Bridge by sending text and `Enter` to the pane.

Wake participation is controlled per session. Manually registered sessions start opted out, so they are not woken unless an operator explicitly enables participation. The operator-only Agent Mail API requires a reason for each change and accepts only the wake-enabled flag and reason; it cannot change member, team, or slot assignment. Enabling is accepted only when a fresh authenticated MCP session is bound to exactly one matching observed pane. Participation changes appear in the operator-only wake audit, which records the reason and result without storing credentials or message content.

Non-tmux Claude Code, Codex, and Copilot sessions can still receive and send Agent Mail through MCP, but Synth City cannot wake their visible terminal session yet. Messages for those sessions remain delivered and unread until the agent calls `synth_city_check_inbox` or reaches a provider hook boundary. Agents should call `synth_city_check_inbox` before major work and after finishing a task.

## External Local Callers

Local tools such as OpenClaw can use the external Agent Mail API to authenticate as a named local actor, discover participants, send direct messages, request context, create handoffs, and poll request status.

See [External Agent Orchestration](./external-agent-orchestration.md) for token setup, endpoint examples, delivery result semantics, and Agent Teams launch integration.

## Setup Checklist

1. Open **Agent Mail** in Synth City.
2. Use the **Install** tab to install the integration for Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, or any combination of them. For Pi, check that the **Pi Agent Mail** card shows **Extension ready**, then launch Pi from Synth City.
3. Restart or resume the affected agent sessions so their MCP configuration is loaded.
4. Have each agent call `synth_city_whoami` once from its repository.
5. Ask agents to call `synth_city_check_inbox` before starting major work and after finishing a task.

Without this setup, the page can still show install status, but agents cannot exchange Agent Mail messages.

## Current Limits

- Visibility is machine-global. Every local participant is visible to every other participant.
- Sessions without Agent Team slot context use one repo-level participant. Agent Team slots can create multiple distinct participants in the same repo, such as planner/reviewer and implementer.
- External Agent Mail calls use local actor bearer tokens. Token creation is loopback-only and follows Synth City's local trust model.
- External callers should only use the API from the same trusted machine until a broader Synth City auth model exists.
- Agent Mail is coordination state, not source control. Handoffs should still reference files, branches, issues, or commits when durable provenance matters.

## Install Details

Open **Agent Mail** in Synth City and use the **Install** tab.

- Claude Code install adds user-scope command hooks and a user-scope MCP server.
- Codex install runs the Codex CLI MCP installer and writes Agent Mail lifecycle hooks.
- Copilot install runs the Copilot CLI MCP installer and writes a managed user-level hook file.
- Install and uninstall actions require confirmation and attempt a backup before mutating config.

The Install tab also shows manual Codex snippets and Copilot fallback commands/hook JSON.

## Amend an approved scope and end a submitted revision

An owner can request a healthy scope amendment before or after opening a PR. The current Leader
reviews the normalized path/action/command scope, then the owner separately acknowledges the
delivered approval. Held workspace edits remain intact. Three approved amendments, eight amendment
requests of any outcome and sixteen cumulative unique added file paths are the attempt limits; any
stricter configured limits remain in force. A rejected amendment does not count toward the three
approved ones, but it still counts toward the eight requests and its added paths keep their cost.
Removed paths retain their history and budget cost.

When independent review requires changes to a submitted implementation revision, the assigned
reviewer records a structured negative disposition for the exact head, then the current Leader
ends that revision. The owner remains on the same issue, branch and lease, with source work
stopped until fresh amendment approval and acknowledgement. Prose, CI completion and an old
review cannot grant that authority. An operator can also cancel submitted revisions; diagnostic
work must first restore the exact baseline tree, including when its failed head was already charged.

With the automatic merge policy, a code item merges only after the team's verifier has recorded an
explicit `accepted` verdict for the pull request's exact current head (`synth_city_record_head_review`).
A push after the acceptance waits for a new acceptance, an owner or non-verifier cannot supply one, and
the work view shows `Waiting for reviewer acceptance` or `Head changed since acceptance`. The review hold
label keeps working as an extra control. See the API workflow for the exact rules.

Cancelled and timed-out CI runs remain blocked and visible without consuming a failed-head unit.
Closing an unmerged submitted PR on an escalated attempt supersedes that revision without
implicitly authorizing a retry or releasing the workspace. See the [API workflow](../api/agent-mail.md#healthy-scope-amendments-and-submitted-review-settlement)
for tools, authentication, compatibility limits and separate review/merge gates.
