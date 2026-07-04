# Conversational Team + Autonomy Setup — Design

**Status:** Design spec (no implementation committed)
**Date:** 2026-07-04
**Companion mockups:** `2026-07-04-autonomous-github-dispatch-conversational-setup-mockups.html`
**Depends on:** `2026-07-02-autonomous-github-dispatch-design.md` (the autonomy/dispatch spec — this document adds a second way to configure the schema that spec introduces; it does not change dispatch behavior)

**Scope:** Give Claude Deck a conversational entry point that lets a human describe a project and have the brain propose *both* an `AgentTeamPreset` roster (if none exists yet for the named repo) *and* the `TeamGithubScope`/per-slot autonomy configuration from the dispatch spec — in one guided, five-stage conversation, ending in a single review/confirm checkpoint before anything is written. The existing form screens (Agent Teams page, slot editor, Autonomy tab) remain the source of truth and the fallback path; this is an additional way to arrive at the same data, not a replacement for it.

---

## 1. Problem & Motivation

The autonomy-configuration spec (`2026-07-02-...-design.md`) and its UI mockups (`2026-07-03-...-ui-mockups.html`) both assumed an `AgentTeamPreset` already existed — the human's job was tuning autonomy settings on top of a team someone had already built by hand, field by field, across the existing Slots tab, Add-scope dialog, and slot editor.

Pressure-testing that assumption surfaced the real gap: **most humans setting up autonomy for a new project don't have a team yet either.** The cognitive load isn't just "too many autonomy fields" — it's the combination of (a) not knowing what fields mean, (b) not knowing what values to put in them, and (c) too much cross-screen navigation, and all three apply just as much to *building the roster* as to configuring dispatch on top of it. A conversational flow that only solves the second half misses the harder, earlier half of the problem.

This spec extends the conversational flow (still guided, still widget-driven, still one brain — the same one that later runs autonomous dispatch, in an interview mode) to cover team composition first, then flow into autonomy configuration, with one review/confirm checkpoint for the whole thing.

**Explicitly not a new capability, in one sentence:** every field this conversation sets is a column on `AgentTeamPreset`, `AgentTeamSlot`, or `TeamGithubScope` that the existing REST API already accepts — this spec adds a new *client* of those APIs (a chat-driven one, backed by the brain) and, for the composition stage specifically, one new *inference* capability (proposing a roster from repo inspection). It does not add new schema beyond what the autonomy spec already defined, except where called out in §3.

**Out of scope for this spec** (deliberately deferred, mirroring the autonomy spec's own scoping discipline):
- Anything about how the brain later behaves once dispatch is running — that's entirely `2026-07-02-...-design.md`'s territory, unchanged by this spec.
- A freeform chat mode (§6's design-approach discussion settled on guided-multi-stage-with-widgets, not open-ended text parsing) — revisit only if the guided flow proves too rigid in practice.
- Live-updating side-panel form view (discussed as a stronger v2, not attempted here) — the review stage's summary card is the v1 answer to "let the human see the real state before committing."
- Editing an *existing* team's non-autonomy fields (renaming slots, changing charters post-creation) conversationally — this flow's team-composition stage only fires when no team exists yet for the named repo; changing an established team's slots stays a forms-only action.
- Multi-repo team composition in one sitting — Stage 2 proposes a roster for the one repo named in Stage 1. A team that should span multiple repos (per the autonomy spec's `TeamGithubScope` list) still adds subsequent repos through the existing "+ Add repo" form action after this conversation ends, not through a second composition pass.

---

## 2. Current Architecture (as-is, relevant slice)

```
AgentTeamPreset (name, description)
  └─ AgentTeamSlot[] (repo_path, provider, role, charter, launch_mode, launch_options,
                       area_labels, expertise)          ← area_labels/expertise from the autonomy spec
       └─ launch() → spawn_session() → tmux session
            └─ registers as MailTeamMember

TeamGithubScope (repo_owner, repo_name, repo_path, dispatch_label, design_label,
                 merge_policy, max_approval_rounds)      ← all from the autonomy spec, §3.1
  belongs to one AgentTeamPreset, many rows per preset (multi-repo)
```

Key facts this design must respect:

- **Preset creation is already a single atomic operation.** `AgentTeamService.create_preset()` (`backend/app/services/agent_team_service.py:83`) takes an `AgentTeamPresetCreate` with a `slots: List[AgentTeamSlotCreate]` and creates the preset plus all its slots in one DB transaction. This conversation's team-composition stage produces exactly this payload shape — no new creation primitive needed.
- **`TeamGithubScope` rows attach to a preset that must already exist** (autonomy spec §3.1 — `preset_id` is a required FK). This is *why* team composition must run before the autonomy stages in this flow, not a design choice made independently here — it's a direct consequence of a schema decision the prior spec already made.
- **No chat/interview request-response mode exists for "the brain" yet.** The autonomy spec's brain (§9, deployment modes) is described purely as a background scheduler loop (APScheduler job in hosted mode, or an external process polling REST). Nothing in that spec, or anywhere else in the backend (confirmed by search — no `anthropic_agent_sdk`/`ClaudeSDKClient` usage exists anywhere in `backend/app`), gives the brain a synchronous, turn-by-turn conversational interface. **This is new infrastructure this spec must define**, not something to wire up to an existing component.
- **The autonomy conversation's stages already exist as a design** — the four stages from `2026-07-03-...-conversational-setup-mockups.html`'s original version (Repo, Labels & policy, Slot routing, Review) are preserved here as the back half of a five-stage flow, renumbered as Stages 1, 3, 4, 5. This spec's job is defining Stage 2 and the orchestration that makes the fast-path/full-path branch work — not redesigning the parts that were already validated.

---

## 3. Data Model Changes

### 3.1 No new tables

Team composition writes to `AgentTeamPreset`/`AgentTeamSlot` (existing tables, unchanged shape). Autonomy configuration writes to `TeamGithubScope`/the `area_labels`/`expertise` columns on `AgentTeamSlot` (all defined in the autonomy spec, §3.1/§3.1a — this spec adds no columns there). The only new persistent state this spec introduces is the conversation session itself:

```python
class SetupConversationSession(Base):
    """In-progress or completed conversational setup session (team + autonomy)."""

    __tablename__ = "setup_conversation_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    # active | confirmed | abandoned
    current_stage: Mapped[str] = mapped_column(String, default="repo", nullable=False)
    # repo | team_composition | labels_policy | slot_routing | review
    fast_path: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # true once Stage 1 detects an existing TeamGithubScope for the named repo — skips team_composition
    repo_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_name: Mapped[str | None] = mapped_column(String, nullable=True)
    repo_path: Mapped[str | None] = mapped_column(String, nullable=True)
    existing_preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="SET NULL"), nullable=True
    )  # set on the fast path; null while building a brand-new team
    draft_state: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # accumulated, not-yet-committed answers across all stages -- see §5
    transcript: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # ordered list of {role: "brain"|"human", content, stage, created_at} -- for the UI to render and for resuming a session
    created_preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_presets.id", ondelete="SET NULL"), nullable=True
    )  # set on confirm, whether newly created (full path) or the pre-existing one (fast path)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
```

`draft_state` and `transcript` are both JSON blobs rather than normalized columns — deliberately. The shape of what's being drafted (slot proposals, label choices, routing suggestions) is exactly the shape of the eventual `AgentTeamPresetCreate`/`TeamGithubScope`/slot-update payloads, which already have their own typed schemas elsewhere (autonomy spec §3, Agent Teams API). Normalizing a second, parallel typed representation for the *in-progress, not-yet-valid* draft would be duplicated modeling effort for data that's discarded (on confirm, it's transformed into real typed payloads and the session's job is done) or abandoned (on cancel, the whole blob is irrelevant). This mirrors the autonomy spec's own reasoning for why `GithubWorkItem` doesn't normalize into a fully separate parallel model of Agent Teams state (§3.2 there) — draft/in-flight state gets a loose shape, committed state gets the real one.

### 3.2 Nothing added to `AgentTeamPreset`/`AgentTeamSlot`/`TeamGithubScope`

Confirmed no new columns needed on any of the three existing tables — the review/confirm step (§5e) writes through the **existing** `create_preset`, `add_slot`, and (autonomy-spec-defined) `TeamGithubScope`-create endpoints. This conversation is a client of those APIs, not a modifier of their schema.

---

## 4. New Backend Component: the Brain's Interview Mode

### 4.1 Why this needs to be a real architectural piece, not "just prompt the LLM"

The autonomy spec's brain is a scheduler-driven background loop — it wakes up, polls GitHub, makes dispatch decisions, goes back to sleep. This conversation needs the *same* brain (per the earlier design-conversation decision: "same brain, different mode," not a separate assistant) to instead hold a synchronous, multi-turn, stateful conversation with a human, capable of:

- Reading existing Deck state (a preset's slots, a repo's config) before speaking.
- Making tool calls mid-conversation (GitHub API reads) and incorporating results into its next message.
- Proposing structured data (slot definitions, label choices) that the frontend renders as widgets, not raw prose the frontend has to parse.
- Resuming a session across page loads (the human closes the tab mid-conversation and comes back).

This is a genuinely new mode for the brain, layered on top of whatever the autonomy spec's dispatch loop already needs (an Agent-SDK-backed reasoning component, per the earlier brainstorming's "same brain, different mode" decision) — not a reuse of dispatch-loop code paths, since dispatch is fire-and-forget background work and this is turn-by-turn interactive work. They share the *identity* of "the brain" (one conceptual component, one Deck-facing name) but not a code path — this is worth being explicit about so implementation doesn't force an awkward shared abstraction between "poll GitHub every 5 minutes" and "hold a chat turn" just because both are called "the brain."

### 4.2 New service: `SetupConversationService`

**New file:** `backend/app/services/setup_conversation_service.py`

Responsibilities:
- Own the `SetupConversationSession` lifecycle (create, advance stage, record transcript turns, confirm, abandon).
- On each human turn, assemble the context the brain's interview mode needs (current stage, draft state so far, relevant read-only tool results) and get back either: a brain message + next widget to render, or a structured "stage complete, advancing to X" signal.
- Own the **inference calls** that back each stage's "checked the repo" moments — these are read-only GitHub API calls (reusing the autonomy spec's `GITHUB_TOKEN`, §4 there — never a new credential) plus, for Stage 2 specifically, a repo-structure inspection (see §5b) that has no autonomy-spec precedent and is new to this spec.
- On confirm, translate `draft_state` into the real typed payloads and call the **existing** `AgentTeamService`/scope-creation methods — this service is an orchestrator over existing write paths, it does not duplicate their validation or persistence logic.

### 4.3 New API surface

```
POST   /api/v1/setup-conversations                    → create a session, returns session_id + first brain message
POST   /api/v1/setup-conversations/{id}/messages       → post a human turn (a widget answer or free text), returns next brain message
GET    /api/v1/setup-conversations/{id}                → fetch session state (for resuming after a page reload)
POST   /api/v1/setup-conversations/{id}/confirm         → commit draft_state via existing create/update APIs, returns created/updated preset
POST   /api/v1/setup-conversations/{id}/abandon         → mark abandoned, no writes
```

`POST .../messages` is intentionally one endpoint for every stage rather than one per stage — the frontend doesn't need to know which stage-specific shape to send; it posts whatever the currently-rendered widget produced (a repo string, a chip-list update, a button-choice value) and the backend's stage machine interprets it against `current_stage`. This keeps the frontend generic (render whatever widget the response says to render, post back whatever it collects) rather than needing per-stage request schemas the frontend has to special-case.

### 4.4 Read-only tool access during the conversation

Every "checked the repo" moment in the mockups is a real, auditable action, not conversational flavor text:

| Mockup moment | Backend action |
|---|---|
| "checked the repo" (Stage 1) | `GET /repos/{owner}/{repo}` + branch protection + Actions workflow config, via `GITHUB_TOKEN` |
| "checked the repo's structure & issue history" (Stage 2, full path) | Repo tree listing (top-level dirs, manifest files like `package.json`/`pyproject.toml`) + `GET /repos/{owner}/{repo}/issues?state=all&per_page=100` label frequency count |
| "checked the repo's structure & issue history" (Stage 2, thin-repo fallback) | Same call; fallback triggers when commit count and issue count both fall under a small fixed threshold (exact numbers are an implementation-time tuning decision, not fixed here — the principle, not the threshold, is what this spec commits to) |
| "checked the repo's labels" (Stage 4) | `GET /repos/{owner}/{repo}/labels` + per-label usage frequency on past issues — same call whether or not Stage 2 ran, since Stage 4's routing inference is independent of how the roster came to exist |
| "matches your other teams" (Stage 2, provider default) | Local query: `SELECT DISTINCT provider FROM agent_team_slots ORDER BY ...` — most-used provider across the human's existing presets, no external call |

All of these are read-only and idempotent — none of them write to GitHub or to Deck's own tables until the confirm step. This matters for a reason the autonomy spec already established for its own watcher: an inspection pass that only reads is safe to retry, re-run, or abandon mid-conversation without any cleanup concern.

---

## 5. The Five-Stage Flow

### 5a. Stage 1 — Repo

Unchanged in mechanics from the original conversational-setup mockup's Stage 1, with one addition: after the repo/local-path exchange, the backend checks for an existing `TeamGithubScope` row matching the named repo. If found, `SetupConversationSession.fast_path = true` and `current_stage` jumps straight to `labels_policy` — the original four-stage flow's exact starting point, now reached as a detected branch of this one rather than a separate flow a human has to know to pick.

If no match is found, `existing_preset_id` stays null and the session proceeds to Stage 2.

### 5b. Stage 2 — Team Composition (new)

Only reached when `fast_path = false`. Two sub-branches, both producing the same output shape (a list of proposed `AgentTeamSlotCreate`-shaped drafts):

- **Full inference** (repo has enough structure/history): inspect top-level directories and manifest files to guess service boundaries (e.g. `backend/` + `frontend/` directories, or a `pyproject.toml` at root with no subdivision → one slot), cross-reference with label-usage frequency from issue history to confirm those boundaries reflect real divided ownership (not just folder structure that happens to exist). Propose one slot per confirmed boundary, plus one `Architect`/coordinator slot when more than one SME slot is proposed (mirrors the mockup's SnazzyEmail Core example — a single-slot proposal has no separate architect, since there's nothing to coordinate between).
- **Thin-repo fallback** (commit/issue counts below the fallback threshold): ask directly ("describe what this project does and who's working on it") and let the brain's judgment, not repo inspection, propose a roster from the human's plain-language answer — explicitly sized to what the human described (the mockup's one-slot "Maintainer" example for a solo side project), not padded to match the full-inference path's typical output shape.

Each proposed slot carries: `display_name`, `role`, `charter` (this is the text that Stage 4 later reuses as an `expertise` fallback — see §5d), and `provider` (defaulted from the human's most-used provider across existing presets, per §4.4's local query). The human can rename, remove, or add slots via widget actions before confirming the roster shape; nothing is written yet.

**Note on charter quality**: the charters proposed here become durable data if confirmed — they're not placeholder text overwritten later. This is a deliberate reuse of writing effort (the autonomy spec's slot-editor mockup already treats `charter` as meaningful, human-facing text), but it does mean Stage 2's inference quality directly determines how good a starting charter a human gets, not just how good a routing label suggestion they get three stages later. Worth flagging as a place where inference quality genuinely matters, echoing the autonomy spec's own §11.8 concern about classification-fallback quality being unverified until tried against real repos.

### 5c. Stage 3 — Labels & Merge Policy

Unchanged from the original mockup's Stage 2 (repo's branch-protection/Actions findings inform a `merge_policy` recommendation; `dispatch_label`/`design_label` default to the standard names). No behavioral change — included here only for stage-numbering continuity.

### 5d. Stage 4 — Slot Routing

Unchanged in mechanics from the original mockup's Stage 3, with one behavioral addition when arriving via the full path (not the fast path): a slot whose `area_labels` don't cleanly match any repo label falls back to using the **charter text written in Stage 2** as its `expertise` classifier input, rather than asking the human to describe the slot's ownership a second time in different words. On the fast path (Stage 2 never ran), this fallback doesn't apply — the question is asked directly, exactly as in the original mockup, since there's no Stage-2-authored charter to reuse.

### 5e. Stage 5 — Review & Confirm

Unchanged in principle (nothing committed until this step; "Edit in forms instead" remains a real escape hatch, not a dead end) — grown in scope to include a "New team" summary card alongside the existing "scope" and "slot routing" cards, only rendered on the full path (fast path has no new team to show, since `existing_preset_id` is already set).

On confirm, the backend performs, in order, inside one logical operation from the frontend's point of view (see §5f for what "one operation" means at the transaction level):

1. **Full path only:** `AgentTeamService.create_preset()` with the confirmed slot list → yields a new `preset_id`.
2. `TeamGithubScope` creation for the named repo, against whichever `preset_id` is now in scope (newly created, or `existing_preset_id` on the fast path).
3. Per-slot `area_labels`/`expertise` updates via the existing slot-update path.
4. `SetupConversationSession.status = "confirmed"`, `created_preset_id` set.

### 5f. Confirm is not one database transaction, and that's an accepted tradeoff

Steps 1–3 above are, mechanically, three separate calls into existing services (`create_preset`, then two rounds of scope/slot updates), each of which commits independently per the autonomy spec's and Agent Teams' existing patterns — this spec does not introduce a new cross-service transaction wrapping all three, because doing so would mean either (a) teaching `AgentTeamService` and the autonomy spec's scope-creation logic to participate in an externally-managed transaction they weren't designed for, or (b) duplicating their validation inside a new combined write path. Neither is worth the complexity for what is, in practice, a low-risk multi-step commit: if step 2 or 3 fails after step 1 succeeded, the human is left with a **team that was created but isn't yet autonomy-configured** — which is a perfectly valid, recognizable state (it's exactly what "+ New team" followed by never touching the Autonomy tab produces today), not a corrupted one. The failure is visible (the confirm action would surface an error) and recoverable (retry, or finish configuring autonomy through the existing forms) rather than silent or destructive.

This is called out explicitly, not glossed over, because it's a real, deliberate scope boundary: **this spec does not attempt distributed-transaction semantics across the create-team and configure-autonomy write paths.** If that failure mode proves painful in practice, a follow-up could add a compensating rollback (delete the just-created preset if scope creation fails) — not attempted here because it's speculative hardening for a failure mode with a benign fallback, which the project's own conventions (per the autonomy spec's repeated "don't build for a need that hasn't materialized" framing) argue against doing preemptively.

---

## 6. Frontend

### 6.1 New entry point

**File:** `frontend/src/features/agent-teams/AgentTeamsPage.tsx` — a new "Build a team with the brain" button alongside the existing "+ New team" action on the list page (not nested inside a preset, since no preset may exist yet — the entry point moving up a level from the autonomy spec's original placement is the one navigation change this spec makes to an existing screen).

### 6.2 New component: the conversation panel

**New directory:** `frontend/src/features/setup-conversation/`

- `SetupConversationPanel.tsx` — the chat surface itself: renders `transcript` turns, the progress rail (5 steps, with a "skipped" visual state for `team_composition` on the fast path — per the mockup's dashed-rail-dot treatment), and whatever widget the current brain turn specifies.
- `widgets/` — one component per widget type used across the mockups: choice buttons, chip-input (labels/area_labels), text-field, and the slot-proposal card (with Rename/Remove/Add actions) — this last one is new; nothing in the existing Agent Teams UI has an inline-editable slot summary card outside a full dialog, so it's a genuinely new shared component, not a reskin of an existing one.
- `ReviewSummary.tsx` — Stage 5's card stack (new-team/scope/routing cards) — structurally similar to existing summary patterns elsewhere in Deck (e.g. the Agent Teams launch-plan summary) but not a direct reuse, since the data shape (draft, not-yet-real IDs) differs from a launch plan's shape (real IDs, real slots).

### 6.3 "Skip to forms" and "Edit in forms instead"

Both exit points route to the **existing** screens, pre-filled from `draft_state`:
- "Skip to forms" (available at every stage) → abandons the conversation session, opens the relevant existing form (Add-scope dialog, slot editor, or — new, for team composition — the existing preset-creation form) pre-filled with whatever was captured so far.
- "Edit in forms instead" (Stage 5 only) → same mechanism, but with a complete draft rather than a partial one, and does **not** mark the session abandoned until the human actually leaves without confirming (so returning to the conversation after glancing at the forms is still possible) — mirrors the "the conversation is a third path into the same schema, not a fourth kind of state" principle established in the autonomy-spec mockups.

Pre-filling an existing form from a partial or complete draft is new plumbing this spec introduces (the autonomy-spec UI mockups gestured at this seam but didn't need to build it, since their conversation only ever produced complete, in-scope drafts for an already-existing preset) — concretely, this means the preset-creation form and slot editor both need an optional "initial values" prop they don't currently accept.

---

## 7. Guardrails Carried Over From the Autonomy Spec, Applied Here

- **Read-only credential reuse.** Every GitHub inspection call in this conversation uses the same `GITHUB_TOKEN` the autonomy spec's watcher/merge step use (§4 there) — no new credential type, no elevated scope. The conversation only ever *reads* GitHub; it never writes to GitHub (labels, issues, PRs) — all GitHub writes remain the dispatched team's job once autonomy is actually running, per the autonomy spec's existing division of responsibility.
- **Never bypass the plan-hash-style confirmation.** Stage 5's confirm step is this flow's equivalent of the autonomy spec's `confirm_plan_hash` requirement (§2/§5c there, itself modeled on the pre-existing Agent Teams launch safety gate) — nothing commits without an explicit human confirm action, and this spec does not introduce a "skip confirmation" flag analogous to the autonomy spec's explicitly-avoided `skip_plan_confirmation=true` default.
- **`autonomy_enabled` still defaults to false.** This conversation can walk a human all the way through configuring autonomy, but per the autonomy spec's §9, the resulting `AgentTeamPreset.autonomy_enabled` still needs its own explicit toggle — this flow does not implicitly turn autonomy on as a side effect of completing Stage 5; Stage 5's confirm creates the scope/routing configuration, and a human still flips the toggle (in the conversation's final message, or on the Autonomy tab afterward — an implementation-time UX choice, not fixed here, since both are equally consistent with "explicit, not implicit").

---

## 8. Open Questions / Risks

1. **Fallback-threshold tuning (§4.4, §5b).** "Commit count and issue count both under a small fixed threshold" needs real numbers, chosen against actual repos, not guessed here. Too high a threshold means real, structured repos get pushed into the thin-repo fallback unnecessarily (annoying — the human answers a question the brain could have inferred); too low means a genuinely sparse repo gets a padded-out roster it doesn't need (worse — per §5b's explicit design goal, inference should scale down as readily as up).
2. **Composition-inference quality is unverified.** Same category of risk the autonomy spec flagged for its own classification fallback (§11.8 there) — proposing service boundaries from directory structure and label history is a real inference, not a mechanical lookup, and its quality is unknown until tried against a range of real repos (monorepos with non-obvious boundaries, repos where directory structure and actual ownership have drifted apart, etc.).
3. **§5f's non-atomic confirm.** Flagged and reasoned through above as an accepted tradeoff, not silently ignored — but it's worth restating as an open risk rather than a closed decision: if partial-failure-after-preset-creation turns out to be common in practice (not just theoretically possible), the "benign fallback" argument weakens and a compensating-rollback follow-up becomes worth its complexity.
4. **Session resumption after a long gap.** `SetupConversationSession` supports resuming (§4.3's `GET` endpoint), but this spec doesn't define a staleness policy — if a human abandons a session mid-Stage-2 and returns a week later, should the repo-inspection results (branch protection, label list) be re-fetched rather than trusted from the stored `draft_state`? Repos change. Left as an implementation-time decision; the safe default is probably "re-run Stage 1's and Stage 2's inspection calls on resume if more than some threshold of time has passed," but no threshold is fixed here.
5. **Interview-mode brain infrastructure is the biggest unknown in this spec.** §4.1 names the requirement (a synchronous, stateful, tool-calling conversational mode for the same brain that also runs a background dispatch loop) but does not design the Agent-SDK-level plumbing that makes both modes coexist cleanly — that's appropriately a separate, lower-level design pass once this spec's shape is approved, not something to improvise inline here.
6. **Provider-default inference (§4.4) has a cold-start problem.** "Most-used provider across the human's existing presets" has no signal for the very first team a human ever creates conversationally — this needs a hardcoded fallback default (presumably matching whatever the Agent Teams form's own default is today) for that specific case, not left to return null/error.

---

## 9. Out of Scope

- Implementing any of §3–§6 (this is a design spec only).
- A freeform (non-widget-driven) conversational mode (§1).
- Live-updating side-panel form view alongside the chat (§1) — noted as a stronger v2 candidate, not attempted here.
- Conversationally editing an already-existing team's non-autonomy fields (§1) — this flow's composition stage only fires for a repo with no existing team.
- Composing a team across multiple repos in one conversation (§1) — additional repos still go through the existing "+ Add repo" form action after this conversation ends.
- Compensating-transaction rollback for the non-atomic confirm step (§5f, §8.3) — deferred pending evidence it's actually needed.
- Fixing exact fallback thresholds, staleness windows, or the Agent-SDK-level interview-mode plumbing (§8.1, §8.4, §8.5) — named as required decisions, not resolved here.
