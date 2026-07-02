# Autonomous GitHub Dispatch — Design

**Status:** Design spec (no implementation committed)
**Date:** 2026-07-02
**Scope:** Give Claude Deck an optional "brain" that watches labeled GitHub issues on one or more repos per Agent Team, routes each issue to the team's subject-matter-expert slot (mimicking how a real team triages — the specialist looks at it first, not the lead), has that slot check in with the team leader before starting work, and closes the loop through one of **two distinct pipelines depending on issue type**: a code pipeline (local checks → CI-gated PR → merge per policy) for defects/features, and a design pipeline (PR opens directly for human review, never CI-gated, never auto-merged) for brainstorming/spec issues whose output is documentation. Zero human interaction beyond labeling issues and (for code issues, optionally) merging.

---

## 1. Problem & Motivation

Claude Deck today is a **human-driven** control surface: a person decides what a team should work on and calls Agent Teams launch APIs (via UI, curl, or an external tool like OpenClaw) to make it happen. The goal of this spec is to let a human instead manage a **GitHub issue backlog** — labeling issues that are ready for a Claude Deck team to pick up — and have Claude Deck run the rest of the loop unattended: detect the label, route the issue to the team's subject-matter-expert slot (mimicking a real team, where the specialist triages before the lead), have that owner check in with the leader before starting, verify the resulting work, and apply a per-repo merge policy.

This is explicitly framed as "an actor using existing rails," not a new orchestration engine:

- **Agent Teams** (`agent_team_service.py`, `POST /presets/{id}/plan-launch` → `/launch`) already does provider-aware dispatch with a plan-hash confirmation safety gate.
- **Agent Mail** (`agent_mail_service.py`) already lets a dispatched slot message and route to other slots without any code changes — the SME-to-leader ack exchange (§5c) is just another use of tools that already exist.
- **External Agent Mail** (`external_agent_mail.py`, bearer-token actors) already lets an outside process drive both of the above — this is the precedent for "the brain is just another actor," established by OpenClaw's own `docs/plans/2026-03-06-agent-orchestration-design.md` proposal.

What's missing, and what this spec adds: something that polls labeled GitHub issues, turns them into `launch` calls scoped to the *right* repo (a team can span multiple repos), and closes the loop with verification + merge — while staying inside the existing actor/permission model rather than inventing a new one.

**Revision note (this version).** An earlier draft of this spec treated "verify then merge" as one uniform pipeline regardless of what an issue actually produces. Pressure-testing against real backlog composition — a mix of defects/features (output: code, merged via a CI-gated PR) and design/brainstorming issues (output: a spec doc, merged via PR but with no meaningful CI signal to gate on) surfaced that a uniform pipeline is wrong on two counts: (1) CI-green is not evidence a design doc is *correct* — it only proves nothing broke, which for a docs-only change is nearly always true regardless of quality; (2) every dispatched session inherits this project's own global instructions, which include a **hard gate** (`superpowers:brainstorming`) requiring human approval before any creative/design work proceeds — a gate an unattended session has no human to satisfy. §5, §7, and §8 below now branch on issue type specifically to resolve both.

**Out of scope for this spec** (deliberately deferred, not forgotten):
- GitHub webhooks (polling only for v1 — lower operational surface, no inbound exposure required).
- CI failures / stale PRs as *dispatch* triggers (see §9 — kept as future scope-entry toggles, not required for v1's labeled-issue flow).
- A brain-side *relevance* judgment — the human's `dispatch_label` is still the entire filter for "should Claude Deck act on this at all." The one semantic step this revision *does* add is narrower: a cheap fallback classification for *which slot* should own an issue when no area label is present (§5) — routing, not relevance.
- Fine-tuned models, a dedicated "developer brain" product surface, or anything beyond an actor using the APIs that already exist.

**Findings addressed in this revision** (from a pressure-test against real backlog composition — defects, features, and design/brainstorming issues):

| Finding | Fix location |
|---|---|
| B1 — ownership doesn't travel with an internal handoff | §5c/§5d (new `deck_report_dispatch_status` tool with `reassign_to_slot_id`) |
| B2 — no per-slot dispatch concurrency, only per-repo | §5b (per-slot busy check), §8 (new guardrail) |
| C1 — leader-ack doesn't satisfy the brainstorming skill's human-approval gate; design issues can wedge the queue forever | §5a (issue-type detection), §5c (leader as delegated approver for design issues), §7b |
| C2 — CI-green is a meaningless signal for docs-only PRs | §7b (design pipeline skips CI-gating entirely) |
| C3 — `area_labels`/`expertise` conflate code-area ownership with issue-type; design issues don't route cleanly | §5a (issue-type detected independently of SME routing, via a separate label) |
| D — `merge_policy` can't distinguish "always human for design" from "configurable for code" | §7b (design pipeline is unconditionally human-gated, independent of the scope's `merge_policy`) |

---

## 2. Current Architecture (as-is, relevant slice)

```
AgentTeamPreset (name, description)
  └─ AgentTeamSlot[] (repo_path, provider, role, charter, launch_mode, launch_options)
       └─ launch() → spawn_session() → tmux session
            └─ registers as MailTeamMember (Agent Mail identity)
                 └─ triages/routes via deck_send_message / deck_check_inbox (existing, unchanged)
```

Key facts this design must respect:

- `AgentTeamSlot.repo_path` is fixed **per slot** at creation time (`backend/app/models/database.py:149`). There is currently no way to launch a slot against a different repo without editing the slot.
- Launch already has a two-step safety gate: `plan-launch` returns a `plan_hash`; `launch` requires `confirm_plan_hash` (or an explicit `skip_plan_confirmation=true`) (`AgentTeamLaunchRequest`, `schemas.py:2174`). This spec's brain **always** uses the plan/confirm flow, never the skip flag — see §7.
- External actors (`MailExternalActor`, `external_agent_mail_service.py`) already authenticate via bearer token and are loopback-only to create (`external_agent_mail.py:75`). The brain reuses this actor model rather than inventing a new credential type for Deck-internal callers.
- No GitHub integration, scheduler, or background job exists anywhere in the backend today (confirmed by repo-wide search — no `octokit`/`webhook`/`APScheduler`/`asyncio.create_task` polling loop). This is genuinely new infrastructure, not a gap in something partially built.

---

## 3. Data Model Changes

### 3.1 `TeamGithubScope` (new table)

A team preset can watch **multiple repos**, each with its own label and merge policy — a team is not 1:1 with a repo.

```python
class TeamGithubScope(Base):
    __tablename__ = "team_github_scopes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)  # local checkout used for dispatch override
    dispatch_label: Mapped[str] = mapped_column(String, default="claude-deck-ready", nullable=False)
    design_label: Mapped[str] = mapped_column(String, default="claude-deck-design", nullable=False)
    merge_policy: Mapped[str] = mapped_column(String, default="human", nullable=False)  # "human" | "auto"; code-pipeline only, see §7b
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("preset_id", "repo_owner", "repo_name", name="uix_preset_repo"),
    )
```

- `dispatch_label` is per **scope entry**, not global — two teams (or two scope entries within one team) can watch the same repo with different labels if needed. Default `"claude-deck-ready"` covers the common single-team-per-repo case with zero configuration.
- `design_label` (**new**, fixes C1/C3) is a second, independent label that marks an issue as design/brainstorming rather than code — e.g. a human applies both `claude-deck-ready` *and* `claude-deck-design` to a spec-writing issue. This is a distinct signal from `area_labels` (§3.1a): `area_labels` answers "which SME owns this," `design_label` answers "which pipeline does this go through" (§5a, §7b). An issue can carry `design_label` regardless of which area it's routed to — a design issue about the billing module still routes to the billing SME, it just goes through the design pipeline once dispatched. Default `"claude-deck-design"`, same zero-config-by-default philosophy as `dispatch_label`.
- `repo_path` here is the **default working directory override** used at dispatch time (§5), decoupled from any single slot's saved `repo_path`.
- `merge_policy` is per scope entry (per repo), not per team — a team spanning a low-stakes repo and a critical one can auto-merge on one and require a human on the other. **Applies only to the code pipeline** — the design pipeline (§7b) is always human-gated regardless of this setting, since "nothing failed" is not evidence a design decision is sound (fixes D).

### 3.1a `AgentTeamSlot` gains an expertise declaration

Two new nullable columns on the **existing** `AgentTeamSlot` table (`backend/app/models/database.py:136`), additive and optional — existing teams/slots are unaffected until a human fills them in:

```python
area_labels: Mapped[list | None] = mapped_column(JSON, nullable=True)   # e.g. ["area:backend", "area:billing"]
expertise: Mapped[str | None] = mapped_column(String, nullable=True)     # freeform, used only as classifier fallback input
```

- `area_labels` is the **mechanical** match target (§5 step 1) — a slot claims one or more GitHub area labels it owns.
- `expertise` is a short freeform blurb ("owns the billing/Stripe integration and the subscription state machine") consumed **only** by the fallback classifier (§5 step 2) when no `area_labels` match. It is not surfaced to GitHub and does not affect mechanical routing.
- Both are edited alongside the existing `role`/`charter` fields in the slot editor (§10) — same form, two more optional inputs, no new page.

### 3.2 `GithubWorkItem` (new table)

Dedup ledger so the watcher doesn't re-dispatch the same issue every poll cycle.

```python
class GithubWorkItem(Base):
    __tablename__ = "github_work_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("team_github_scopes.id", ondelete="CASCADE"), index=True, nullable=False
    )
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_title: Mapped[str] = mapped_column(String, nullable=False)
    issue_url: Mapped[str] = mapped_column(String, nullable=False)
    github_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issue_type: Mapped[str] = mapped_column(String, default="code", nullable=False)  # "code" | "design" — set once at intake (§5a), fixes C1/C2/C3
    dispatch_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    # pending | dispatched | verifying | awaiting_human_review | ready_for_review | merged | failed | escalated
    # "verifying" and its CI-polling substeps apply to issue_type="code" only (§7a).
    # "awaiting_human_review" applies to issue_type="design" only (§7b) — reached directly from "dispatched", no CI step.
    launch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_launches.id", ondelete="SET NULL"), nullable=True
    )
    owner_slot_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_slots.id", ondelete="SET NULL"), nullable=True
    )
    routing_method: Mapped[str | None] = mapped_column(String, nullable=True)  # "label" | "classified" | "leader_fallback" | "reassigned" (§5c)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_id", "issue_number", name="uix_scope_issue"),
    )
```

`dispatch_status` is the state machine driving everything downstream (§6-§7), now branching into two distinct sub-paths keyed by `issue_type` (§7a code, §7b design). `github_updated_at` lets the watcher detect "still open, label re-applied after removal" as a fresh dispatch candidate without re-processing untouched issues.

### 3.3 Dispatch-time repo override (backend change to Agent Teams)

**This is the one change to existing Agent Teams code**, flagged explicitly because it's shared infrastructure, not new-only code:

- `AgentTeamLaunchRequest` (`schemas.py:2174`) gains an optional field:
  ```python
  repo_path_override: Optional[str] = None
  ```
- `agent_team_service.py`'s launch path: when `repo_path_override` is set, the slot(s) being launched use the override for `SpawnCommandOptions.directory` (and for the resulting `AgentTeamLaunchResultItem.repo_path` / Agent Mail member registration) **instead of** the slot's saved `repo_path`, for that launch only. The slot's own saved `repo_path` is never mutated.
- Scope: applies to the **slot the brain dispatches to** — the routed SME slot, not necessarily the leader (see §5, revised for SME-first routing). Any other slot that joins later via internal Agent Mail routing (including the leader, when it gets looped in for the ack step) continues to use its own saved `repo_path` unless it too needs a same-repo override, which is out of scope for v1 (a leader ack is a message exchange, not a second `launch` call — see §5).
- Backward compatibility: field is optional and defaults to `None` — every existing single-repo team, and every human/OpenClaw-driven launch that doesn't pass it, is unaffected.

---

## 4. GitHub Watcher (polling service)

**New file:** `backend/app/services/github_watcher_service.py`
**New scheduler:** APScheduler `AsyncIOScheduler`, one interval job per distinct `(repo_owner, repo_name)` across **all** enabled scope entries — not one job per team, and not one job per scope entry. Two teams watching the same repo share one poll (respects GitHub rate limits; avoids duplicate API calls for the same data).

Per poll cycle, for a given repo:
1. `GET /repos/{owner}/{repo}/issues?labels={label}&state=open` for each **distinct `dispatch_label`** configured across scope entries pointing at this repo.
2. For each returned issue: read its full label set (already returned by the issues endpoint — no extra call) and set `issue_type = "design"` if the issue also carries the scope's `design_label`, else `"code"`. This is a second mechanical label check, not a judgment call — consistent with the "label is the entire filter" rule; it just answers a second yes/no question (pipeline) instead of the first one (should we act at all).
3. Upsert a `GithubWorkItem` keyed on `(scope_id, issue_number)`, including `issue_type` from step 2. New row → `dispatch_status="pending"`. Existing row where `github_updated_at` advanced *and* status is `failed` → reset to `pending` (lets a human fix something and re-trigger by touching the issue; does **not** reset `merged`/`ready_for_review`/`awaiting_human_review` rows — no re-dispatch of already-handled issues just because someone commented). If `issue_type` changes on an existing `pending` row (human added/removed `design_label` before dispatch happened), update it in place — no dispatch has occurred yet, so there's nothing to reconcile.
4. Does **not** decide anything about the *relevance* of the issue — no priority/should-we-act judgment happens here or anywhere else in the brain. `dispatch_label` is the entire relevance filter, matching the explicit design decision that the human's backlog grooming *is* the triage step. `design_label` is a routing/pipeline signal, not a relevance signal — it never causes an issue to be skipped, only to take a different path once dispatched.

**Credentials:** a single GitHub token (PAT or GitHub App installation token), configured once in `backend/app/config.py` as `GITHUB_TOKEN` (new `Settings` field, following the existing pattern of code-level defaults / env override, no `.env` required per project convention). This token is used **only** by the watcher and the merge step (§7) — never distributed to spawned team sessions. Rationale: one auditable credential holder, smaller secret surface, no need to inject GitHub write access into every tmux session's environment.

---

## 5. Dispatch

**New file:** `backend/app/services/github_dispatch_service.py`, invoked by the same scheduler tick right after a watcher poll (or on its own shorter interval — implementation detail, not a design decision).

This is the section most changed from the original "always hit the leader" model. The goal is to mimic how a real team triages: the specialist looks at it first, and loops the lead in before starting — not the other way around.

### 5a. Routing: pick the owning slot

For each `GithubWorkItem` with `dispatch_status="pending"`:
1. **Mechanical match**: fetch the issue's GitHub labels. If any label matches a slot's `area_labels` (§3.1a) within the preset, that slot is the **owner**. If more than one slot matches, pick the first by `position` (same seniority-by-order convention used elsewhere) — do not silently multi-dispatch; log which one was picked so the choice is inspectable (§10 activity feed).
2. **Classification fallback**: if no label match, run one cheap classification call — issue title + body against each enabled slot's `expertise` blurb (§3.1a) — to pick the best-matching owner. If the team has no `expertise` set on any slot (nothing to classify against), fall back to the leader slot (first enabled by `position`) rather than blocking. This is the one semantic judgment call in the whole pipeline, scoped narrowly to "who owns this," never to "should we act on this."
3. Store the resolved owner as `GithubWorkItem.owner_slot_id` (new nullable FK column, `agent_team_slots.id`, `ondelete="SET NULL"`) so routing is recorded, not just acted on transiently.

### 5b. Per-slot concurrency check (fixes B2)

Before dispatching, check whether `owner_slot_id` already has another `GithubWorkItem` where an agent is actively working — `dispatch_status` in (`dispatched`, `verifying`) — for **this same slot**, regardless of which repo or which scope entry that other item belongs to, since a slot maps to one running session. **Deliberately excludes** `awaiting_human_review` and `ready_for_review`: once a PR is open and only a human action remains, the owner slot is free for its next dispatch (see §8's guardrail table for why this also means such items don't count against the per-repo concurrency cap). If a same-slot active item is found, this item stays `pending` and is retried on the next scheduler tick rather than dispatched now. This is a **per-slot** queue, layered underneath the existing **per-repo** concurrency guardrail (§8) — the two are independent limits, not a replacement for each other: per-repo caps overall throughput per scope entry; per-slot prevents two work items from being launched into (or, via session reuse, injected into) the same already-busy tmux session.

Only once the owner slot is confirmed free does dispatch proceed.

### 5c. Dispatch to the owner, then leader ack/approval before work starts

4. Build a bootstrap prompt for the **owner slot**, branching on `issue_type`:
   - **`issue_type="code"`**: issue number, title, body, URL, a fixed preamble identifying this as a Claude-Deck-dispatched task, and an explicit instruction — *triage this issue, then send the team leader a short plan (what you understand the issue to need, your intended approach) via Agent Mail and wait for an acknowledgment before starting implementation.*
   - **`issue_type="design"`** (fixes C1): the same triage-then-message-the-leader instruction, but framed explicitly as a **design/brainstorming task**, with one addition: *this session's own project instructions may require presenting a design and waiting for human approval before proceeding (a "brainstorming" gate) — there is no human available to give that approval directly. Treat the team leader's acknowledgment, given after reviewing your triage message, as the approval that gate requires. Do not proceed to writing the design document until the leader has explicitly approved.* This reframes the leader-ack step from "FYI, I'm starting" (code path) into "this IS the approval gate" (design path) — it doesn't bypass the project's brainstorming skill, it satisfies it by substituting the team leader as the accountable human-equivalent reviewer, which is a defensible reading of the gate's intent (a considered second party reviews the design before implementation) even though the gate's literal text says "user."
5. Call `plan-launch` for the preset scoped to just the owner slot (`slot_ids=[owner_slot_id]`), with `repo_path_override` set to the scope's `repo_path`.
6. Call `launch` with the returned `plan_hash` as `confirm_plan_hash` — **the brain never sets `skip_plan_confirmation=true`**, matching the plan-review precedent already established for external actors (§2). If the plan is blocked (`can_launch=false`), mark the work item `dispatch_status="escalated"` and emit an Agent Mail broadcast / Deck notification rather than retrying blindly.
7. On successful launch: `dispatch_status="dispatched"`, store `launch_id`.

**Note on the leader:** the leader slot is *not* separately launched by the brain here — if the leader isn't already running (e.g. reused from a prior dispatch, or launched once and kept alive), the owner's ack/approval message will sit undelivered/unread until the leader is active. This is the same `wake_state` semantics (`wakeable` / `delivered_waiting` / `offline`) that Agent Mail already models for any recipient (§2) — no new delivery mechanism is introduced. If the team's leader is never running, ack will never arrive; this is covered by the idle-timeout escalation in §6, not a new guardrail. **For `issue_type="design"` this matters more**, since the leader is now a hard approval gate rather than a courtesy notice — an offline leader means the design pipeline cannot proceed at all, by design (no fallback auto-approval exists or should exist).

**Ownership reassignment (fixes B1).** If the owner or the leader decides the work belongs elsewhere mid-triage (e.g. backend SME discovers a feature needs frontend work too, and hands the frontend half to the frontend SME), the owner calls the new `deck_report_dispatch_status` MCP tool (§5d) with `reassign_to_slot_id` set. This updates `GithubWorkItem.owner_slot_id` in place, so monitoring (§6) and the per-slot concurrency check (§5b) both track the *current* owner, not the original dispatch target. `routing_method` for a reassigned item is recorded as `"reassigned"` (extending the enum from §3.2) so the activity feed (§10) shows the handoff instead of silently attributing the eventual PR to the wrong slot.

### 5d. New MCP tool: `deck_report_dispatch_status` (fixes B1, and the "awkward" PR-reporting question from the prior revision)

**File:** `backend/mcp_shim/agent_mail_server.py` (same shim that already hosts `deck_create_team`/`deck_launch_team`; per `docs/superpowers/specs/2026-06-29-agentic-agent-teams-design.md` §6d, the shim's `_request` helper is already being generalized to a prefix-aware form for team tools — this new tool follows that same pattern rather than introducing another one-off request path).

```
deck_report_dispatch_status(
    work_item_id: int,
    status: Literal["triaging", "in_progress", "pr_opened", "blocked"],
    pr_number: Optional[int] = None,
    reassign_to_slot_id: Optional[int] = None,
    note: Optional[str] = None,
)
```

The owner slot calls this explicitly instead of the brain inferring status by reading Agent Mail message contents (the prior revision's "a bit indirect" open question, §11.3 — now resolved, not just flagged). `work_item_id` is included in the bootstrap prompt (§5c step 4) so the owner always has it on hand. This is a small, purpose-built tool rather than overloading `deck_send_message`/`deck_create_handoff`, because those are for *inter-agent* communication and this is *agent-to-brain* status reporting — different audiences, different schema, no reason to force one shape onto both.

- `status="pr_opened"` with `pr_number` set is what advances `dispatch_status` from `dispatched` into `verifying` (code) or `awaiting_human_review` (design) — see §7.
- `reassign_to_slot_id` triggers the ownership update described above.
- `status="blocked"` with a `note` moves the item straight to `escalated` — an explicit "I can't do this" signal, distinct from a silent idle timeout (§6).

From here, **the team's own internal Agent Mail routing takes over**: owner triages, messages the leader, waits for ack/approval, then proceeds (or reassigns, per above) — exactly as a human-driven team would, using tools the owner and leader already have plus the one new reporting tool. Claude Deck's brain does not participate in or observe the ack/approval exchange's content; it only re-enters the loop when `deck_report_dispatch_status` is called or via idle-timeout monitoring (§6).

---

## 6. Monitoring

The brain does not need a bespoke monitoring protocol — it reuses the same visibility any Agent Mail actor already has, plus the explicit signal from `deck_report_dispatch_status` (§5d) when the owner sends one:

- Periodically (same scheduler cadence), for each `dispatch_status="dispatched"` item, check the **current `owner_slot_id`'s** Agent Mail member state (idle time, last activity) via the existing `agent_mail_service` queries — "current" matters because a reassignment (§5c) may have moved this off the original dispatch target.
- If idle beyond a threshold with no `pr_opened` status report yet, send one re-steer Agent Mail message to the current owner ("status check" nudge) — not a retry of the whole dispatch. If still idle after a second check, escalate (§8) rather than nudge indefinitely.
- **Leader-ack/approval stall is a distinct, common case** the threshold must cover explicitly: the owner may be sitting fully idle *waiting on the leader* (§5c), which looks identical to "stuck" from the outside — both are "owner idle, no PR yet." The brain does not need to distinguish the two causes; the same idle-timeout-then-nudge-then-escalate handling applies either way, and the nudge message itself (sent to the owner, who can re-ping the leader) is sufficient without the brain reasoning about *why* the owner stalled. **This threshold needs to be generous enough for `issue_type="design"`** specifically — a design-approval exchange with the leader plausibly takes longer than a code-plan ack, since the leader is now doing real review, not rubber-stamping. A single global idle threshold risks nudging (or, worse, escalating) a design issue that's in a perfectly healthy, if slower, leader-review conversation. Use a longer default threshold for `issue_type="design"` items — a concrete multiplier (e.g. 2-3x the code threshold) is an implementation-time tuning decision, not fixed here.

This section is intentionally thin: monitoring is "watch for stuck," not "supervise correctness" — correctness is verification's job (§7).

---

## 7. Verification → Merge

The pipeline forks here on `issue_type`, set once at intake (§4) and immutable after dispatch. §7a is the original code pipeline (unchanged in substance from the prior revision, restated for clarity). §7b is new — the design pipeline that resolves C1/C2/D.

### 7a. Code pipeline (`issue_type="code"`)

The bootstrap prompt (§5c) instructs the **owner** to, as part of its normal workflow (after the leader ack, or after a reassignment is resolved):
1. Run the project's existing local test/build/lint commands before pushing anything.
2. Push a branch and open a **draft PR** once local checks pass.
3. Call `deck_report_dispatch_status(work_item_id, status="pr_opened", pr_number=...)` (§5d).

Once `pr_number` is captured, `dispatch_status="verifying"`:
- The brain polls `GET /repos/{owner}/{repo}/commits/{sha}/check-runs` (or `GET /pulls/{pr_number}` merge-ability + `GET /pulls/{pr_number}/checks`) on the same polling cadence as the watcher.
- **All checks green** → `dispatch_status="ready_for_review"`; brain calls `PATCH /pulls/{pr_number}` to flip draft → ready for review.
  - `merge_policy="human"` → stop here. Emit an Agent Mail broadcast + Deck UI notification ("PR #N ready for review"). A human merges via GitHub as normal — Claude Deck does not touch the merge button.
  - `merge_policy="auto"` → the **brain itself** (using its own `GITHUB_TOKEN`, not any team session's credentials) calls `PUT /pulls/{pr_number}/merge`. On success, `dispatch_status="merged"`.
- **Any check failed** → send the failure detail back to the owner via Agent Mail (which check, which log line if available) and increment `retry_count`. If `retry_count` is within budget (§8), stay in `verifying`/return to `dispatched` for another pass; if the budget is exhausted, `dispatch_status="escalated"`.
- **No check-runs exist at all** (e.g. the repo's Actions are path-filtered and this PR touched only paths outside any filter) → treat as `escalated`, not as "vacuously green." A code PR with zero check-runs is a repo-configuration mismatch worth a human looking at, not a silent auto-promote — this is the code-pipeline-specific version of the "CI-green is meaningless without real checks" problem that motivates the design pipeline skipping CI entirely (§7b) rather than trying to fake a signal that isn't there.

This is the "PR open = the checkpoint" model: everything up to and including opening the PR happens with zero human interaction; the only two human touchpoints are (a) applying the dispatch label originally, and (b) clicking merge, and (b) is itself optional per repo via `merge_policy`.

### 7b. Design pipeline (`issue_type="design"`) — fixes C1, C2, D

Design/brainstorming issues produce a document, not application code, and — per §5c's reframing — the leader's approval during triage already stood in for the human-approval gate the brainstorming skill would otherwise require. That means by the time the owner starts writing, the design has already been reviewed once. The design pipeline's job is to get it in front of the *actual* human (not just the leader) before it merges, and to never pretend CI status is a proxy for design quality.

The bootstrap prompt (§5c) instructs the owner to, after leader approval:
1. Write the design document (per whatever the project's own doc-writing conventions are — this spec does not add new conventions, it reuses the existing `writing-plans`/spec-doc pattern this project already follows for design work, evidenced by the very document you're reading).
2. Push a branch and open a PR — **not a draft PR**, and with no expectation of CI gating it (see below).
3. Call `deck_report_dispatch_status(work_item_id, status="pr_opened", pr_number=...)` (§5d) — same tool as the code path, so monitoring (§6) doesn't need separate logic to detect "a PR exists."

Once `pr_number` is captured, `dispatch_status="awaiting_human_review"` — **not** `"verifying"`. The brain does **not** poll check-runs for this item at all, regardless of whether the repo's CI happens to run on the PR's branch. This is a deliberate, explicit skip (fixes C2): CI passing on a docs-only PR proves nothing about whether the design is sound, and treating it as a gate would let a bad design auto-promote to "ready for review" purely because nothing broke.

- The brain's only remaining action is notification: Agent Mail broadcast + Deck UI activity-feed entry ("Design PR #N ready for human review — no CI gating applies to design issues"), immediately upon capturing `pr_number`.
- **`merge_policy` is not consulted for design issues, at all** (fixes D) — there is no `merge_policy="auto"` path for `issue_type="design"`, full stop. This is a hard rule, not a default that a scope entry could override, because the entire premise of the design pipeline is that a human must read and judge a design before it lands, and `merge_policy` was never meant to answer "should a human read this," only "should a human click merge on already-verified code."
- A human reviews the PR via GitHub as normal (possibly requesting changes, which the owner or leader would handle exactly like any human-requested revision — no new mechanism needed) and merges it themselves. `dispatch_status="merged"` is set the same way as the code path — the watcher (§4) detects the PR's merge state on its next poll and updates the row; no separate merge-detection logic is needed since both pipelines converge on "watcher notices the PR is merged."
- **Retry budget does not apply** to the design pipeline in the same shape as §7a's CI-failure retries, since there's no CI failure to retry against. If a human requests changes on GitHub, that's normal review, not an escalation — the item can sit in `awaiting_human_review` indefinitely without breaching any guardrail (see §8's revised concurrency handling for why this is now safe rather than a resource leak).

---

## 8. Guardrails

Per `TeamGithubScope` (i.e., per repo, not per team globally — a team spanning a well-trodden repo and a risky one shouldn't share one budget), plus one new **per-slot** guardrail that isn't scope-scoped at all:

| Guardrail | Scope | Default | Behavior on breach |
|---|---|---|---|
| Max concurrent dispatched items | per `TeamGithubScope` (repo) | 3 | New `pending` items wait; not silently dropped, just queued |
| Max concurrent items per owner slot (**new**, fixes B2) | per `AgentTeamSlot`, across all scopes/repos it's ever dispatched for | 1 | Item stays `pending` — see §5b. This is a hard 1, not configurable: a slot maps to one tmux session, so "concurrent items for one slot" is a correctness constraint, not a risk-tolerance dial. |
| Max verification retries per item | per `TeamGithubScope` | 2 | Escalate (`dispatch_status="escalated"`) instead of retrying forever. **Applies to §7a (code) only** — §7b (design) has no CI-failure-retry concept; a human requesting changes on GitHub is normal review, not a retry-budget event. |
| Max auto-merges per day | per `TeamGithubScope` | 5 | Further green PRs stay `ready_for_review` and wait for a human even under `merge_policy="auto"` — the cap does not block dispatch or verification, only the merge action. **Applies to §7a (code) only** — §7b (design) never auto-merges regardless of this cap (§7b, fixes D). |

**Does `awaiting_human_review` count against "max concurrent dispatched items"? No** (resolves the forward-reference in §7b and §11.9's tuning question) — the moment a `GithubWorkItem` reaches `awaiting_human_review` or `ready_for_review`, the *agent* work is done and the owner slot is free for its next dispatch (§5b's per-slot check looks at `dispatched`/`verifying` only, not the post-PR states). So a slow-moving design review does not hold its owner slot hostage, and does not count against the repo's concurrency cap either — both caps track "items where an agent is actively working," not "items awaiting anything, including a human." This is a deliberate, explicit answer, not left open: it falls directly out of restricting §5b's non-terminal-state check to `dispatched`/`verifying` rather than including every non-`merged` status.

"Escalate" always means: Agent Mail broadcast to the team + a row surfaced in the Deck UI (§10) with a clear reason (`block_code`-style string, matching the existing `AgentTeamLaunchPlanItem.block_code` convention) — never a silent stall, never an automatic unbounded retry.

The per-scope guardrails are configurable per scope entry (columns on `TeamGithubScope`, defaults as above) — not global settings — since risk tolerance is a per-repo decision. The per-slot guardrail is a fixed correctness constraint, not configurable anywhere.

---

## 9. Deployment Modes (brain placement)

Unchanged from the earlier discussion in this design conversation, restated for the spec record:

- **Hosted mode**: the watcher/dispatch scheduler described above runs *inside* the Deck backend process as an APScheduler job, using a loopback `MailExternalActor` token Deck creates for itself on first enable.
- **External mode**: an outside process (OpenClaw or similar) implements the same watcher/dispatch/verify loop against Deck's **existing** External Agent Mail + Agent Teams REST APIs — no Deck backend change is required to support this mode; it already works today per `docs/features/external-agent-orchestration.md`. This spec's new pieces (§3 data model, §7 GitHub polling/merge) would need to be replicated in that external process if it wants the same GitHub-native loop; alternatively, a future iteration could expose §3/§4/§7 as external-actor-callable endpoints so an external brain can drive Deck's watcher instead of rolling its own. **Decision for this spec: v1 ships hosted-mode only.** External-mode parity for the GitHub-watcher specifically (as opposed to Agent Teams/Agent Mail generally, which already has parity) is deferred — see §11.
- A per-preset toggle (`AgentTeamPreset.autonomy_enabled: bool`, new column, default `False`) gates whether the hosted scheduler acts on a given preset's scope entries at all. Off by default: existing teams keep working exactly as today until a human opts in.

---

## 10. Frontend

**New section on `AgentTeamsPage.tsx`** (or a new sub-route if the preset detail view is already dense) per preset: "Autonomy."

- Toggle: `autonomy_enabled` on/off.
- List of `TeamGithubScope` entries (add/edit/remove): repo owner/name, local `repo_path`, `dispatch_label`, `design_label`, `merge_policy` (labeled as "code-pipeline only" in the UI, per §7b), `enabled`.
- Slot editor gains two optional fields alongside the existing `role`/`charter` inputs (§3.1a): `area_labels` (tag input) and `expertise` (short freeform text) — so setting up SME routing is part of the normal slot-editing flow, not a separate surface.
- Activity feed: recent `GithubWorkItem` rows for this preset's scopes — issue title/link, `issue_type` badge (code/design), `dispatch_status`, **routed owner slot + `routing_method`** (label / classified / leader_fallback / reassigned, §5a/§5c) so a human can sanity-check routing decisions, PR link once available, retry count, escalation reason if any. Read-only in v1 — no manual retry/dismiss/reroute actions from the UI (use GitHub directly: remove/reapply the label, or close the issue).

This reuses the existing Agent Teams page and the visual pattern already established by the (unbuilt but designed) Activity Dashboard in `docs/plans/2026-03-05-http-hooks-integration-design.md` — same shape (stats + timeline + filters), new data source.

---

## 11. Open Questions / Risks

1. **GitHub token scope.** A single `GITHUB_TOKEN` covers all watched repos across all teams. If different repos need different GitHub identities (e.g. separate orgs), this needs to become per-scope-entry credentials — deferred until a real multi-org need arises (YAGNI for v1; the field can be added to `TeamGithubScope` later without breaking anything).
2. **Leader identification is still a convention.** "First enabled slot by position" identifies the leader for the ack/approval step (§5c) and the classification-fallback owner (§5a step 2). If a team wants a non-first slot to be the leader, this needs an explicit `is_team_leader` flag on `AgentTeamSlot`. Not added in v1 because every team observed so far orders architect/lead first; revisit if that assumption breaks.
3. **Resolved (was open in the prior revision): PR-number capture mechanism.** The prior revision left this as "reading `pr_number` back from an Agent Mail message is a bit indirect." §5d now resolves it with a dedicated `deck_report_dispatch_status` MCP tool the owner calls explicitly — no more inferring status from message contents. Noted here so the reasoning trail from finding to fix stays visible.
4. **CI-check API shape.** GitHub's check-runs vs. combined-status APIs have overlapping but not identical semantics depending on how the repo's Actions are configured. Implementation should probe both and document which one this repo's / a given watched repo's Actions setup actually needs — not assumed here.
5. **External-mode parity for the watcher (§9).** Deferred; noted as a explicit gap, not silently dropped.
6. **CI-failure / stale-PR triggers (§1 out-of-scope).** The original brainstorm considered these as dispatch triggers alongside labeled issues. This spec's `TeamGithubScope` schema leaves room for `watch_failed_ci` / `watch_stale_prs` boolean columns to be added later, but v1 implements only the labeled-issue path — CI-failure-as-trigger conflates with CI-as-verification-gate (§7) in ways that need their own design pass to avoid the brain fixing its own verification loop's failures as if they were new work items.
7. **Leader-ack/approval failure mode.** §5c's ack/approval step relies entirely on prompt-level instruction (the owner is *told* to wait) rather than a backend-enforced gate — nothing stops a misbehaving or under-instructed owner session from starting work before the leader replies. For `issue_type="code"` this is a minor risk (worst case: a plan the leader would have redirected proceeds unredirected). For `issue_type="design"`, this is a materially bigger risk, since the leader-approval step is now standing in for the project's brainstorming-skill human-approval gate (§5c) — an owner session that skips the wait defeats that gate entirely, silently. This is an accepted v1 limitation (no new enforcement plumbing), consistent with the design's "prompt instruction, not new backend plumbing" choice, but it is the single weakest link in how this spec resolves C1, and is flagged as such rather than presented as fully solved.
8. **Classification-fallback cost and quality.** §5a step 2's cheap classification call needs a real model choice and a fallback-of-the-fallback (leader) when `expertise` blurbs are absent — both are implementation-time decisions, but the *quality* of routing when relying on freeform `expertise` text (vs. mechanical label match) is unverified until tried against real slot descriptions. This is now also the mechanism that could misroute a design issue to the wrong SME (C3) if `expertise` blurbs don't clearly describe non-code judgment areas — worth revisiting once real slot descriptions exist.
9. **Resolved (was open in an earlier pass of this revision): does design-pipeline review latency starve the concurrency cap?** §8 now states explicitly that `awaiting_human_review`/`ready_for_review` items count against neither the per-slot nor the per-repo concurrency cap — only `dispatched`/`verifying` (active-agent-work states) do. So a slow-moving design review can't starve new dispatches on the same repo or hold its owner slot hostage. Noted here as a resolved risk, not a remaining open question, so the reasoning trail from finding to fix is visible.

---

## 12. Out of Scope

- Implementing any of §3–§10 (this is a design spec only).
- GitHub webhooks (§1).
- Any semantic/LLM-driven judgment of *whether* to act on an issue (§1) — the `dispatch_label` is the entire relevance filter. The classification pass in §5a is scoped strictly to *routing* (which slot owns it), never relevance.
- A backend-enforced leader-ack gate (§11.7) — v1 relies on prompt-level instruction only; no new API/state machine enforces that the owner actually waited.
- External-mode watcher parity (§9, §11.5).
- Multi-org / per-scope GitHub credentials (§11.1).
- A configurable dispatch-leader flag (§11.2) — first-enabled-slot convention only.
