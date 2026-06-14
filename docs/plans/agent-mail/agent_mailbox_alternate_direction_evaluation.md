# Agent Mailbox Alternate Direction Evaluation

**Companion document to:** `claude_deck_agent_mailbox_implementation_plan.md`
**Purpose:** Evaluate the original Agent Mailbox plan against the intended product goal: enabling multiple local agent instances, usually working in separate repositories, to coordinate as a useful team under the Claude Deck user's direction.

This document does not replace the original plan. Treat it as a product and architecture critique that can guide a revised implementation plan or future evaluations.

---

## 1. Executive position

The original plan is a good technical foundation. Its central choice is correct: Claude Deck should own shared coordination state, while agents interact through local MCP tools and lifecycle hooks.

However, the current plan is too repo-local and inbox-oriented for the broader feature goal. It mostly builds "local agent mail" inside a project path. The higher-value product is closer to a **local team coordination layer**:

- Agents know who else is active.
- Agents know which repo and domain each peer owns.
- Agents can ask another repo expert for context.
- Agents can hand off work with enough structure to be useful.
- The human can inspect the communication without managing a complex message system.
- Setup remains low-effort: install mailbox capability once per agent provider, then assign scopes/roles lightly.

The original plan should be kept as the base implementation reference, but its MVP should be adjusted before coding.

---

## 2. Product goal restatement

The feature should let the Claude Deck user run multiple Claude Code and Codex CLI sessions as a coordinated local team.

Common target scenarios:

1. **Multi-repo product work**
   - One agent works in frontend.
   - One agent works in backend.
   - One agent works in docs or infra.
   - All repos contribute to the same product or release.

2. **Expertise transfer**
   - An agent in repo A needs context from repo B.
   - Repo B's agent has local knowledge from reading or editing that repository.
   - Repo A can ask a structured question without the user manually copying context.

3. **Loose knowledge sharing**
   - Repos are related but not part of one strict workspace.
   - Agents should still leave searchable coordination notes, handoffs, and decisions.

4. **Human-directed coordination**
   - The user can see who is working on what.
   - The user can send or route requests.
   - Claude Deck does not become an autonomous task scheduler unless explicitly expanded later.

The product should avoid feeling like a chat app bolted onto Claude Deck. It should feel like an operational coordination surface for local coding agents.

---

## 3. What to keep from the original plan

Keep these original-plan decisions:

- **Claude Deck backend as source of truth.** Shared state belongs in Claude Deck and SQLite.
- **MCP as the agent-facing interface.** MCP is the right way for agents to list peers, read messages, send handoffs, and reserve paths.
- **Agent Bridge for passive discovery.** Observed sessions should appear before they have mailbox tooling installed.
- **Observed / connected / offline states.** This is a useful mental model.
- **No direct agent-to-agent transport.** Avoid peer networking and ad hoc daemon complexity.
- **No raw transcript sharing to agents.** Messages and handoffs should be explicit.
- **Safe config mutation.** Installation must preview, confirm, and avoid writing raw secrets to project files.
- **Advisory leases first.** File coordination should warn before it blocks.

These decisions are practical and aligned with Claude Deck's existing shape.

---

## 4. Main gaps in the original plan

### 4.1 No first-class team or workspace concept

The original plan groups agents, messages, and leases by `project_path`. That works for a single repo, but it misses the intended multi-repo workflow.

The MVP should add a lightweight coordination scope:

```text
CoordinationScope
  id
  name
  description
  created_at
  updated_at
```

Agents can belong to one or more scopes:

```text
AgentScopeMembership
  agent_id
  scope_id
  repo_path
  role
  expertise_label
```

Default behavior can stay simple:

- If no custom scope exists, use the current repo path as an implicit scope.
- The user can create a named scope such as "Billing Launch" and attach multiple repos.
- Agents can still filter by repo.

This gives Claude Deck the vocabulary needed for "agents in different repos are on the same team."

### 4.2 Messages are too passive

The original plan relies heavily on inbox polling through `deck_read_inbox`. That is technically simple but behaviorally weak. Agents may never notice messages unless prompted.

The revised plan should define attention mechanics:

- `deck_whoami` returns unread and urgent counts.
- `deck_list_agents` includes whether each connected agent has unread messages.
- Claude Code `SessionStart` hook nudges the model to call `deck_read_inbox`.
- Optional `Stop` or `Notification` hook can include a short "you have unread mailbox items" reminder.
- UI distinguishes `sent`, `delivered`, `read`, `acked`, and `stale`.

The feature should not pretend messages are real-time if agents only receive them when they call tools.

### 4.3 Missing structured knowledge request

The plan includes generic messages and handoffs. It should also include a first-class **context request** or **knowledge request**.

This is the main value path for cross-repo collaboration.

Suggested MCP tool:

```text
deck_request_context
```

Input:

```json
{
  "to_agent_id": "agent_...",
  "to_role": "backend",
  "scope_id": "scope_...",
  "topic": "How does auth session refresh work?",
  "why_needed": "Frontend agent is wiring retry behavior.",
  "files_or_symbols": ["backend/app/auth/session.py", "refresh_token"],
  "urgency": "normal"
}
```

The receiving agent can answer with:

```text
deck_reply_context
```

or use normal `deck_reply` with metadata.

This is more useful than generic chat because it gives the model a task shape and gives the human a cleaner audit trail.

### 4.4 Roles are underpowered

The original plan has an optional `role` string. That should be more central.

Roles should answer:

- What repo/domain does this agent know?
- What kind of requests should be routed to it?
- What should the human call this agent?

Keep configuration minimal:

- Default role is derived from repo name or selected manually in UI.
- Agent can set or update its role with `deck_whoami` or `deck_set_status`.
- The UI lets the user override display name, role, and expertise label.

Avoid complex team templates in MVP, but make roles visible everywhere.

### 4.5 Installation model needs provider-aware clarity

The original plan treats Codex support as conditional. In the current repo, Codex MCP is already classified as write-capable, while Codex hooks are unsupported.

The revised install model should be explicit:

```text
Claude Code:
  - MCP mailbox install: yes
  - lifecycle hooks: yes
  - lease guard hooks: optional

Codex CLI:
  - MCP mailbox install: yes, through Codex CLI MCP mutation
  - lifecycle hooks: no, unless Codex later exposes compatible hooks
  - status freshness: heartbeat/tool-call based
```

The Install/Coverage UI should show capability by provider instead of presenting one generic install path.

### 4.6 Presence should be reused more directly

The current Claude Deck repo already has Presence event ingestion, session aggregation, and WebSocket broadcast. The original plan mentions Presence but does not make reuse strong enough.

Recommended boundary:

```text
Presence:
  Raw lifecycle and activity facts about sessions.

Agent Mailbox:
  Coordination objects: agents, scopes, messages, context requests, handoffs, leases, receipts.
```

Agent Mailbox should either subscribe to or call Presence processing for hook events. Avoid duplicate hook pipelines where possible.

### 4.7 UI risks becoming a chat product

The UI should stay operational and compact. The original tabs are mostly fine, but the center of gravity should change:

Recommended top-level views:

1. **Team**
   - Agents grouped by coordination scope and repo.
   - Status, role, current activity, unread/ack state.

2. **Requests**
   - Context requests, handoffs, urgent messages.
   - Read/ack status.
   - Human can create and route requests.

3. **Leases**
   - Active path claims and conflicts.

4. **Activity**
   - Small audit timeline of coordination events.
   - Not raw transcript viewing.

5. **Install**
   - Provider-aware mailbox coverage.

Generic threaded chat should be secondary to structured requests and handoffs.

---

## 5. Recommended revised MVP

### Backend

Keep the original models, but adjust them:

- Add `AgentMailboxScope`.
- Add `AgentMailboxAgentScopeMembership`.
- Add `message_kind`: `message | handoff | context_request | context_response | system`.
- Add `scope_id` to threads, messages, leases, and events.
- Keep `project_path` for repo-local filtering.
- Add receipt states that support UI truthfulness: delivered/read/acked/stale.

### Agent-facing MCP tools

Core MVP tools:

```text
deck_whoami
deck_list_agents
deck_set_status
deck_read_inbox
deck_send_message
deck_reply
deck_ack_message
deck_create_handoff
deck_request_context
deck_reserve_paths
deck_release_paths
deck_list_path_leases
deck_check_path_conflicts
```

Optional later:

```text
deck_list_scopes
deck_join_scope
deck_update_expertise
```

For MVP, scope assignment can happen from UI and be returned by `deck_whoami`.

### Hooks

Claude Code hooks:

- `SessionStart`: register/update agent and inject a short mailbox reminder.
- `SessionEnd`: mark offline.
- `Notification`: mark waiting.
- `PostToolUse`: update activity and modified file summaries.
- `PreToolUse`: optional lease warning/block.
- Consider `Stop`: if unread urgent items exist, emit a short reminder.

Codex:

- No hook assumptions.
- Heartbeat on MCP tool calls.
- Optional background heartbeat only if robust.

### UI

MVP UI should answer:

- Who is currently active?
- Which repo and role does each agent cover?
- Which agents are mailbox-capable versus merely observed?
- What requests are pending?
- What messages require acknowledgement?
- What paths are reserved?
- What install steps are missing?

Do not optimize for high-volume chat. Optimize for coordination clarity.

### Install

Must include:

- Provider-aware install status.
- Preview before mutation.
- Confirmation before mutation.
- Backup before mutation.
- No raw token in project config.
- Warning for machine-specific absolute paths.
- Clear restart/reload messaging for existing sessions.

---

## 6. Alternative product directions

### Direction A: Mailbox-first

This is closest to the original plan.

Strengths:

- Simple mental model.
- Easy MVP.
- Good audit trail.

Weaknesses:

- Agents may ignore messages.
- Cross-repo team identity is weak unless scopes are added.
- Can feel like generic chat.

Best if the goal is a quick incremental feature.

### Direction B: Team workspace-first

Claude Deck introduces scopes/workspaces as the core unit, then messages and requests live inside them.

Strengths:

- Matches multi-repo collaboration.
- Better UI story.
- More useful for human-directed orchestration.

Weaknesses:

- Slightly more data model and UI work.
- Needs careful defaults to avoid setup burden.

Best if the goal is durable product value.

### Direction C: Request broker-first

Instead of emphasizing chat, the feature centers on structured requests:

- Ask for context.
- Hand off task.
- Request review.
- Reserve paths.
- Acknowledge completion.

Strengths:

- Strongest "real value" framing.
- Avoids gimmicky chat.
- Easy for human to inspect.

Weaknesses:

- Less flexible than generic messages.
- Requires thoughtful tool descriptions and schemas.

Best direction for an MVP that feels purposeful.

### Recommended blend

Use **Direction B + Direction C**:

- Team scopes establish who belongs together.
- Structured requests drive collaboration.
- Generic messages remain available but are not the hero feature.

---

## 7. Risks and mitigations

### Risk: Agents do not check messages

Mitigation:

- Make unread counts visible in every relevant tool response.
- Use SessionStart and Stop reminders for Claude Code.
- Track stale/unread state honestly in UI.

### Risk: Setup feels complex

Mitigation:

- Default to implicit repo scopes.
- One-click user-scope install per provider.
- Let the user optionally group repos later.

### Risk: Project-scope config leaks local details

Mitigation:

- Prefer user-scope install.
- Never write raw token to project config.
- Warn on absolute script/token paths in project config.

### Risk: UI becomes noisy

Mitigation:

- Default to active scope.
- Prioritize pending requests and connected agents.
- Hide raw event logs behind compact activity views.

### Risk: Hooks duplicate Presence logic

Mitigation:

- Reuse Presence event processing where possible.
- Keep mailbox events focused on coordination state.

### Risk: Path leases create false confidence

Mitigation:

- Label leases as advisory by default.
- Do not block edits unless explicit strict mode is enabled.
- Keep conflict messages actionable.

---

## 8. Evaluation checklist for future reviews

Use these questions to evaluate any revised implementation plan:

1. Can two agents in different repos intentionally join the same coordination scope?
2. Can an agent ask another repo's expert a structured context question?
3. Can the human see whether that request was noticed and answered?
4. Can observed-but-not-connected sessions be distinguished from addressable agents?
5. Can Claude Code and Codex both install the mailbox MCP path with minimal effort?
6. Does Codex avoid unsupported hook assumptions?
7. Does installation preview every config mutation?
8. Does the system avoid raw transcript sharing by default?
9. Does the UI make pending requests obvious without becoming a chat dashboard?
10. Does the feature still provide value if only one or two agents are connected?
11. Does it fail softly when Claude Deck is stopped?
12. Are path leases clearly advisory unless strict mode is enabled?

---

## 9. Suggested changes to the original plan before implementation

Before coding, update the original plan or create a v2 plan with these changes:

1. Add coordination scopes/workspaces to the MVP.
2. Add `context_request` and `context_response` as first-class message kinds.
3. Reframe UI from "Threads" toward "Requests" and "Team".
4. Make provider-aware install behavior explicit.
5. Make Presence reuse a required implementation constraint.
6. Add honest delivery/read/ack/stale semantics.
7. Add tests for cross-repo scope membership and context request flow.
8. Add acceptance criteria for multi-repo collaboration, not only same-project messaging.

---

## 10. Revised acceptance criteria

An improved MVP should be considered successful when:

1. Claude Deck can show observed and connected Claude Code/Codex sessions.
2. The user can create or use a coordination scope spanning multiple repo paths.
3. Agents can identify themselves, including provider, repo path, role, and scope.
4. An agent in repo A can send a context request to an agent or role in repo B.
5. The receiving agent can read, answer, and acknowledge the request.
6. The UI shows pending, read, answered, acked, and stale requests clearly.
7. Agents can create and check advisory path leases.
8. Claude Code hooks update presence/status without breaking when Claude Deck is unavailable.
9. Codex agents can participate through MCP without unsupported hook assumptions.
10. Installation is previewed, confirmed, backed up, and avoids raw token leakage.
11. Existing Claude Deck MCP, Hooks, Presence, Agent Bridge, Config, and Sessions pages still work.

---

## 11. Bottom line

The original plan should not be thrown away. It has the right technical primitives.

The change I would make is product framing:

```text
Not: agent mail inside a repo.
Instead: local agent team coordination across repos, using structured requests and handoffs.
```

That shift keeps the implementation grounded while making the feature more valuable and less gimmicky.
