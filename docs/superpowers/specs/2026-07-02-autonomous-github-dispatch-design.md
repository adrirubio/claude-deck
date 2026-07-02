# Autonomous GitHub Dispatch — Design

**Status:** Design spec (no implementation committed)
**Date:** 2026-07-02
**Scope:** Give Claude Deck an optional "brain" that watches labeled GitHub issues on one or more repos per Agent Team, dispatches them to the team's leader slot, waits for local + CI verification, and applies a merge policy — with zero human interaction beyond labeling issues and (optionally) merging.

---

## 1. Problem & Motivation

Claude Deck today is a **human-driven** control surface: a person decides what a team should work on and calls Agent Teams launch APIs (via UI, curl, or an external tool like OpenClaw) to make it happen. The goal of this spec is to let a human instead manage a **GitHub issue backlog** — labeling issues that are ready for a Claude Deck team to pick up — and have Claude Deck run the rest of the loop unattended: detect the label, dispatch the team's leader, let the team triage/route internally (as it already does via Agent Mail), verify the resulting work, and apply a per-repo merge policy.

This is explicitly framed as "an actor using existing rails," not a new orchestration engine:

- **Agent Teams** (`agent_team_service.py`, `POST /presets/{id}/plan-launch` → `/launch`) already does provider-aware dispatch with a plan-hash confirmation safety gate.
- **Agent Mail** (`agent_mail_service.py`) already lets a dispatched leader triage and route to other slots without any code changes.
- **External Agent Mail** (`external_agent_mail.py`, bearer-token actors) already lets an outside process drive both of the above — this is the precedent for "the brain is just another actor," established by OpenClaw's own `docs/plans/2026-03-06-agent-orchestration-design.md` proposal.

What's missing, and what this spec adds: something that polls labeled GitHub issues, turns them into `launch` calls scoped to the *right* repo (a team can span multiple repos), and closes the loop with verification + merge — while staying inside the existing actor/permission model rather than inventing a new one.

**Out of scope for this spec** (deliberately deferred, not forgotten):
- GitHub webhooks (polling only for v1 — lower operational surface, no inbound exposure required).
- CI failures / stale PRs as *dispatch* triggers (see §9 — kept as future scope-entry toggles, not required for v1's labeled-issue flow).
- A brain-side relevance/triage LLM pass — the human's label *is* the relevance decision; the brain does no semantic judgment before dispatch.
- Fine-tuned models, a dedicated "developer brain" product surface, or anything beyond an actor using the APIs that already exist.

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
    merge_policy: Mapped[str] = mapped_column(String, default="human", nullable=False)  # "human" | "auto"
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("preset_id", "repo_owner", "repo_name", name="uix_preset_repo"),
    )
```

- `dispatch_label` is per **scope entry**, not global — two teams (or two scope entries within one team) can watch the same repo with different labels if needed. Default `"claude-deck-ready"` covers the common single-team-per-repo case with zero configuration.
- `repo_path` here is the **default working directory override** used at dispatch time (§5), decoupled from any single slot's saved `repo_path`.
- `merge_policy` is per scope entry (per repo), not per team — a team spanning a low-stakes repo and a critical one can auto-merge on one and require a human on the other.

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
    dispatch_status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    # pending | dispatched | verifying | ready_for_review | merged | failed | escalated
    launch_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agent_team_launches.id", ondelete="SET NULL"), nullable=True
    )
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("scope_id", "issue_number", name="uix_scope_issue"),
    )
```

`dispatch_status` is the state machine driving everything downstream (§6-§7). `github_updated_at` lets the watcher detect "still open, label re-applied after removal" as a fresh dispatch candidate without re-processing untouched issues.

### 3.3 Dispatch-time repo override (backend change to Agent Teams)

**This is the one change to existing Agent Teams code**, flagged explicitly because it's shared infrastructure, not new-only code:

- `AgentTeamLaunchRequest` (`schemas.py:2174`) gains an optional field:
  ```python
  repo_path_override: Optional[str] = None
  ```
- `agent_team_service.py`'s launch path: when `repo_path_override` is set, the slot(s) being launched use the override for `SpawnCommandOptions.directory` (and for the resulting `AgentTeamLaunchResultItem.repo_path` / Agent Mail member registration) **instead of** the slot's saved `repo_path`, for that launch only. The slot's own saved `repo_path` is never mutated.
- Scope: applies to the **leader slot only** for v1 (the slot the brain dispatches to — see §5). Non-leader slots continue to use their saved `repo_path` when they join via internal team routing, since only the leader's working directory needs to match the triggering issue's repo at dispatch time.
- Backward compatibility: field is optional and defaults to `None` — every existing single-repo team, and every human/OpenClaw-driven launch that doesn't pass it, is unaffected.

---

## 4. GitHub Watcher (polling service)

**New file:** `backend/app/services/github_watcher_service.py`
**New scheduler:** APScheduler `AsyncIOScheduler`, one interval job per distinct `(repo_owner, repo_name)` across **all** enabled scope entries — not one job per team, and not one job per scope entry. Two teams watching the same repo share one poll (respects GitHub rate limits; avoids duplicate API calls for the same data).

Per poll cycle, for a given repo:
1. `GET /repos/{owner}/{repo}/issues?labels={label}&state=open` for each **distinct label** configured across scope entries pointing at this repo.
2. For each returned issue: upsert a `GithubWorkItem` keyed on `(scope_id, issue_number)`. New row → `dispatch_status="pending"`. Existing row where `github_updated_at` advanced *and* status is `failed` → reset to `pending` (lets a human fix something and re-trigger by touching the issue; does **not** reset `merged`/`ready_for_review` rows — no re-dispatch of already-handled issues just because someone commented).
3. Does **not** decide anything about the *content* of the issue — no relevance/priority judgment happens here or anywhere else in the brain. The label is the entire filter, matching the explicit design decision that the human's backlog grooming *is* the triage step.

**Credentials:** a single GitHub token (PAT or GitHub App installation token), configured once in `backend/app/config.py` as `GITHUB_TOKEN` (new `Settings` field, following the existing pattern of code-level defaults / env override, no `.env` required per project convention). This token is used **only** by the watcher and the merge step (§7) — never distributed to spawned team sessions. Rationale: one auditable credential holder, smaller secret surface, no need to inject GitHub write access into every tmux session's environment.

---

## 5. Dispatch

**New file:** `backend/app/services/github_dispatch_service.py`, invoked by the same scheduler tick right after a watcher poll (or on its own shorter interval — implementation detail, not a design decision).

For each `GithubWorkItem` with `dispatch_status="pending"`:
1. Resolve its `TeamGithubScope` → `preset_id`, `repo_path` override, and identify the **leader slot** — the first `enabled` slot by `position` in the preset (matches existing Agent Teams convention where slot order encodes seniority; no new field needed).
2. Build a bootstrap prompt: issue number, title, body, URL, and a fixed preamble identifying this as a Claude-Deck-dispatched task (so the leader's own system/role framing, not a novel prompt template, drives what happens next).
3. Call `plan-launch` for the preset scoped to just the leader slot (`slot_ids=[leader_slot_id]`), with `repo_path_override` set to the scope's `repo_path`.
4. Call `launch` with the returned `plan_hash` as `confirm_plan_hash` — **the brain never sets `skip_plan_confirmation=true`**, matching the plan-review precedent already established for external actors (§2). If the plan is blocked (`can_launch=false`), mark the work item `dispatch_status="escalated"` and emit an Agent Mail broadcast / Deck notification rather than retrying blindly.
5. On successful launch: `dispatch_status="dispatched"`, store `launch_id`.

From here, **the team's own internal Agent Mail routing takes over** — the leader triages and routes to other slots exactly as it would for a human-dispatched task. Claude Deck's brain does not participate in or observe that internal routing; it only re-enters the loop at verification (§6).

---

## 6. Monitoring

The brain does not need a bespoke monitoring protocol — it reuses the same visibility any Agent Mail actor already has:

- Periodically (same scheduler cadence), for each `dispatch_status="dispatched"` item, check the leader's Agent Mail member state (idle time, last activity) via the existing `agent_mail_service` queries.
- If idle beyond a threshold with no PR opened yet, send one re-steer Agent Mail message ("status check" nudge) — not a retry of the whole dispatch. If still idle after a second check, escalate (§8) rather than nudge indefinitely.

This section is intentionally thin: monitoring is "watch for stuck," not "supervise correctness" — correctness is verification's job (§7).

---

## 7. Verification → Merge

The team's bootstrap prompt (§5) instructs the leader to, as part of its normal workflow:
1. Run the project's existing local test/build/lint commands before pushing anything.
2. Push a branch and open a **draft PR** once local checks pass.
3. Report the PR number back via Agent Mail (a `handoff`-kind message addressed to... itself is awkward; concretely: the leader calls the existing `deck_create_handoff` or a plain status message that the brain's monitoring pass (§6) reads back off the Agent Mail thread to capture `pr_number` onto the `GithubWorkItem`).

Once a `pr_number` is captured, `dispatch_status="verifying"`:
- The brain polls `GET /repos/{owner}/{repo}/commits/{sha}/check-runs` (or `GET /pulls/{pr_number}` merge-ability + `GET /pulls/{pr_number}/checks`) on the same polling cadence as the watcher.
- **All checks green** → `dispatch_status="ready_for_review"`; brain calls `PATCH /pulls/{pr_number}` to flip draft → ready for review.
  - `merge_policy="human"` → stop here. Emit an Agent Mail broadcast + Deck UI notification ("PR #N ready for review"). A human merges via GitHub as normal — Claude Deck does not touch the merge button.
  - `merge_policy="auto"` → the **brain itself** (using its own `GITHUB_TOKEN`, not any team session's credentials) calls `PUT /pulls/{pr_number}/merge`. On success, `dispatch_status="merged"`.
- **Any check failed** → send the failure detail back to the leader via Agent Mail (which check, which log line if available) and increment `retry_count`. If `retry_count` is within budget (§8), stay in `verifying`/return to `dispatched` for another pass; if the budget is exhausted, `dispatch_status="escalated"`.

This is the "PR open = the checkpoint" model: everything up to and including opening the PR happens with zero human interaction; the only two human touchpoints are (a) applying the dispatch label originally, and (b) clicking merge, and (b) is itself optional per repo.

---

## 8. Guardrails

Per `TeamGithubScope` (i.e., per repo, not per team globally — a team spanning a well-trodden repo and a risky one shouldn't share one budget):

| Guardrail | Default | Behavior on breach |
|---|---|---|
| Max concurrent dispatched items | 3 | New `pending` items wait; not silently dropped, just queued |
| Max verification retries per item | 2 | Escalate (`dispatch_status="escalated"`) instead of retrying forever |
| Max auto-merges per day | 5 | Further green PRs stay `ready_for_review` and wait for a human even under `merge_policy="auto"` — the cap does not block dispatch or verification, only the merge action |

"Escalate" always means: Agent Mail broadcast to the team + a row surfaced in the Deck UI (§10) with a clear reason (`block_code`-style string, matching the existing `AgentTeamLaunchPlanItem.block_code` convention) — never a silent stall, never an automatic unbounded retry.

These are configurable per scope entry (columns on `TeamGithubScope`, defaults as above) — not global settings — since risk tolerance is a per-repo decision.

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
- List of `TeamGithubScope` entries (add/edit/remove): repo owner/name, local `repo_path`, `dispatch_label`, `merge_policy`, `enabled`.
- Activity feed: recent `GithubWorkItem` rows for this preset's scopes — issue title/link, `dispatch_status`, PR link once available, retry count, escalation reason if any. Read-only in v1 — no manual retry/dismiss actions from the UI (use GitHub directly: remove/reapply the label, or close the issue).

This reuses the existing Agent Teams page and the visual pattern already established by the (unbuilt but designed) Activity Dashboard in `docs/plans/2026-03-05-http-hooks-integration-design.md` — same shape (stats + timeline + filters), new data source.

---

## 11. Open Questions / Risks

1. **GitHub token scope.** A single `GITHUB_TOKEN` covers all watched repos across all teams. If different repos need different GitHub identities (e.g. separate orgs), this needs to become per-scope-entry credentials — deferred until a real multi-org need arises (YAGNI for v1; the field can be added to `TeamGithubScope` later without breaking anything).
2. **Leader-slot ambiguity.** "First enabled slot by position" is a convention, not an explicit field. If a team wants a non-first slot to be the GitHub-dispatch target, this needs an explicit `is_dispatch_leader` flag on `AgentTeamSlot`. Not added in v1 because every team observed so far orders architect/lead first; revisit if that assumption breaks.
3. **PR-number capture mechanism (§7).** Reading `pr_number` back from an Agent Mail message is a bit indirect — a cleaner path might be a dedicated small MCP tool (`deck_report_pr`) the leader calls explicitly. Left as an implementation-time decision; both fit the existing MCP shim pattern without new architecture.
4. **CI-check API shape.** GitHub's check-runs vs. combined-status APIs have overlapping but not identical semantics depending on how the repo's Actions are configured. Implementation should probe both and document which one this repo's / a given watched repo's Actions setup actually needs — not assumed here.
5. **External-mode parity for the watcher (§9).** Deferred; noted as a explicit gap, not silently dropped.
6. **CI-failure / stale-PR triggers (§1 out-of-scope).** The original brainstorm considered these as dispatch triggers alongside labeled issues. This spec's `TeamGithubScope` schema leaves room for `watch_failed_ci` / `watch_stale_prs` boolean columns to be added later, but v1 implements only the labeled-issue path — CI-failure-as-trigger conflates with CI-as-verification-gate (§7) in ways that need their own design pass to avoid the brain fixing its own verification loop's failures as if they were new work items.

---

## 12. Out of Scope

- Implementing any of §3–§10 (this is a design spec only).
- GitHub webhooks (§1).
- Any semantic/LLM-driven relevance triage before dispatch (§1) — the label is the entire filter.
- External-mode watcher parity (§9, §11.5).
- Multi-org / per-scope GitHub credentials (§11.1).
- A configurable dispatch-leader flag (§11.2) — first-enabled-slot convention only.
