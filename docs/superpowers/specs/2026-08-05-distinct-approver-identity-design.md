# Distinct Approver Identity — Design (Findings #1 and #6)

**Date:** 2026-08-05
**Status:** Design, approved for planning
**Closes:** Finding #1 (Leader self-ack), Finding #6 (agent commit identity collides with human reviewer identity)
**Both are Window 2 gates** — `merge_policy=auto` must not be enabled until PR1 lands.

**Relation to #280:** #280 is the *when do we stop waiting* theme (ack/idle timeout governance). This spec is the *who is a distinct party* theme. They share the ack as a data structure and nothing else. Deliberately kept apart: #280 warns that a uniform softening of the ack gate would reopen the C1 no-unreviewed-design invariant, and this spec does not touch timeout behavior at all.

---

## 1. What the problem actually is

Findings #1 and #6 are one question asked at two layers — *who is a distinct party?* — and at both layers the current answer is "nobody, and nothing checks."

### 1.1 Finding #1 is worse than the run log records

The soak run log says a leader-owned code item under `merge_policy=auto` would have "leader-ack + CI as its ONLY gates." Measured, that overstates the ack's role.

`_ack_satisfied` (`backend/app/services/github_dispatch_service.py:902`) has exactly **one** caller: the monitor loop at `:778`, where it decides whether to nudge or escalate `leader_ack_timeout`. The auto-merge path (`github_verification_service.py:233-266`) gates on `merge_policy`, auto-merge budget, `mergeable_state`, head-freshness vs `last_verified_sha`, and CI-green. It never reads the ack.

So the ack is a **liveness probe, not an approval gate**, and under `merge_policy=auto` today **CI is the only gate**. The self-ack is therefore a symptom of a *missing* approval concept, not a weakened one. Recording who acked is necessary but not sufficient: the gate has to be created.

### 1.2 The collision is structural, not accidental

```python
# github_dispatch_service.py:534
def _leader_slot(self, preset_slots):
    enabled = sorted([s for s in preset_slots if s.enabled], key=lambda s: s.position)
    return enabled[0] if enabled else None

# github_dispatch_service.py:128 — end of route_item()
return enabled[0].id, "leader_fallback"
```

The approver and the fallback owner are *the same expression*. When no `area_labels` match and classification does not fire, the item is routed to the very slot that must approve it.

`record_ack_received` (`:681`) then stores only a timestamp:

```python
async def record_ack_received(self, db, item):
    item.ack_received_at = datetime.utcnow()
    item.last_nudge_at = None
    item.updated_at = datetime.utcnow()
    await db.commit()
```

No approver identity is captured, so a self-ack is indistinguishable from a genuine one after the fact.

### 1.3 Measurements (live DB, read-only, 2026-08-05)

| Measurement | Value |
|---|---|
| Work items total | 28 |
| Owned by leader slot 4 | 2, both `routing_method='leader_fallback'` |
| …of those, acked | **2 (100%)** — every leader-owned item self-acked |
| `routing_method='label'` → slot 5 | 15 items, 3 acked |
| `routing_method='label'` → slot 6 | 11 items, 10 acked |
| `mail_messages` self-addressed `context_request` | **3 of 81** (`sender_member_id == recipient_member_id`) |

The self-ack thread, verbatim:

```
id  kind             sender  recipient  thread_root  request_status
114 context_request  16      16         NULL         answered
115 answer           16      NULL       114          NULL
```

The healthy shape also exists, which is what the fix preserves — e.g. id 348: `context_request` sender 17 (Specialist) → recipient 16 (Leader).

Two conclusions: the defect is real and total on the path it affects, and enforcing a distinct approver would reject a **rare** case (3/81 requests), not break normal operation.

### 1.4 Finding #6 is absent plumbing

Nothing in the backend sets `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, or a per-agent token — verified by search across `backend/app/`. Agents inherit the ambient identity of the host shell:

```
git config user.name   -> Juan A. Rubio
git config user.email  -> jarubio2001@gmail.com
gh auth active account -> juanrubio        <- also the human reviewer
```

Agents open PRs themselves via `gh pr create` in their panes; the backend never creates a PR (`github_client.py` has `get_pull`, `mark_pull_ready_for_review`, `merge_pull` and no create). GitHub forbids approving your own PR, so with `required_approving_review_count=1` the human-merge gate deadlocks — observed in the soak, where all 3 PRs stuck `REVIEW_REQUIRED`/BLOCKED and branch protection had to be relaxed as a temporary accommodation.

### 1.5 The asymmetry that makes a real fix possible

| Signal | Set by | Owner can forge? | Is it the approver? |
|---|---|---|---|
| `reporting_slot_id` on `POST /dispatch-status` | MCP shim, from the caller's own registration (`mcp_shim/agent_mail_server.py:618-627`) | No | **No** — it is the owner |
| `mail_messages.sender_member_id` on an `answer` row | MCP shim, from its own registration (`mcp_shim/agent_mail_server.py:296-327`) | **No** | **Yes** |

Approval evidence already exists in the mail tables; the dispatch service simply never consults it. That is the entire design: stop taking the owner's word for the approval, and read the approver's own message instead.

This mirrors an established pattern in this codebase. G2's `_brief_delivered` (`:806-824`) verifies an owner-side claim against independent mail evidence (`MailReceipt.read_at`), and `brief_message_id` (`:439-440` in the migration ladder) is precedent for storing a mail message id on a work item. PR1 is the same shape, one table over.

---

## 2. Architecture

Two independent changes, shipped as two PRs. They fail differently, and only one needs infrastructure that does not exist yet.

```
PR1  Approval attribution + a real gate          (pure code, testable offline)
     1. link ack requests to work items (the anchor does not exist today, §3.2.1)
     2. record who approved; reject self-acks and unattributable acks
     3. make auto-merge require a distinct approver

PR2  Distinct commit/PR identity                 (needs a GitHub App)
     one bot as PR author + per-slot commit identity
```

Sequencing rationale: PR1 needs no external setup and closes the safety gate. PR2's failure mode is a *deadlocked* merge, not a *bad* merge. Landing PR1 first means that if PR2 slips, autonomy is strictly safer than it is today rather than blocked on provisioning.

---

## 3. PR1 — approval attribution and the distinct-approver gate

### 3.1 Schema (via the existing migration ladder)

No change to `mail_messages` — it already carries everything needed. `github_work_items` gains two nullable columns, following `app/database.py:421-440` exactly:

```python
if work_item_columns and "ack_approver_member_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approver_member_id INTEGER"))
if work_item_columns and "ack_evidence_message_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_evidence_message_id INTEGER"))
```

Both nullable, so existing rows migrate silently. `reset_for_retry` (which already clears `ack_received_at` at `:70`) must clear both new columns too — otherwise a retried item inherits a stale approval, which is the same class of defect as Finding 20.

### 3.2 Verified ack

`record_ack_received` gains an evidence lookup and stops trusting the reporter:

```python
async def _ack_evidence(self, db, item) -> MailMessage | None:
    """Return the approver's own message approving this item, or None.

    Evidence must be a message SENT BY a member other than the owner. The
    owner reports the ack, but the owner cannot author the evidence for it.
    """
```

Rules, in order:

1. Resolve the owner's member via the existing `_owner_member(db, item)`.
2. Look for a mail row in the item's ack thread with `kind in ('answer',)` **or** a `context_request` whose `request_status == 'acknowledged'`, whose `sender_member_id` is not the owner's member id and is not NULL.
3. Found ⇒ set `ack_received_at`, `ack_approver_member_id = sender_member_id`, `ack_evidence_message_id = <row id>`.
4. Not found ⇒ **do not** set `ack_received_at`. Return a `409` from `/dispatch-status` with a message naming the reason.

A rejected ack leaves the item un-acked, so the **existing** monitor path at `:778-791` takes over: nudge, then `leader_ack_timeout`. No new `dispatch_status` value, no new escalation reason, no new machinery — which also keeps the standing "NO new `dispatch_status` values" constraint intact.

#### 3.2.1 The anchor does not exist yet — PR1 must create it

This was the one open question in the design, and it is now settled by measurement: **there is no way to link an ack request to a work item today.**

- `mail_messages` columns are `id, thread_root_id, kind, sender_member_id, sender_actor_id, recipient_member_id, subject, body_markdown, payload, request_status, created_at` — no work-item column.
- `deck_request_context` (`mcp_shim/agent_mail_server.py:349-374`) accepts `to_member_id, topic, why_needed, files_or_symbols` and sends a payload of `{why_needed, files_or_symbols}`. No `work_item_id`, not even optionally.
- The work item appears in the ack request only as **prose** inside `why_needed`, e.g. message 80: *"Issue #852 requires Leader acknowledgment before implementation starts."* Five such rows exist. Parsing that text would be guessing.

So a lookup phrased as "find the answer in the item's ack thread" has nothing to key on. PR1 must therefore add the linkage as its **first** task, and the rest of §3.2 depends on it:

1. `deck_request_context` gains an optional `work_item_id: Optional[int] = None`, forwarded into the message payload as `{"work_item_id": N, ...}`. Optional keeps every existing caller and test working — this tool is used for ordinary questions too, not only acks.
2. The brief's ack instruction (`_leader_ack_instruction`, `:541-573`) is updated to pass `work_item_id={item.id}`, so dispatched owners always produce a linkable request. The brief already interpolates `item.id` elsewhere, so this is a wording change, not new plumbing.
3. `_ack_evidence` resolves the thread by finding `context_request` rows whose payload `work_item_id` equals the item id, then examines that thread's `answer` rows and `request_status`.

   Use SQLAlchemy's JSON accessor (`MailMessage.payload["work_item_id"].as_integer()`), not raw `->>`. Both work on the SQLite in this venv — verified on 3.45.1, `json_extract` and `->>` each return `41` for `{"work_item_id": 41}` — but `->>` requires SQLite ≥ 3.38, and the ORM form keeps the query portable and consistent with the rest of the codebase. Because `payload` is nullable and free-form, the filter must tolerate rows whose payload is NULL or lacks the key without raising.
4. **Fallback when the payload linkage is absent** (an agent that ignores the instruction, or an in-flight item briefed before the upgrade): no linkage ⇒ **no evidence** ⇒ the ack is rejected. This fails closed, consistent with the G2/G3 rule that inability to observe is not permission to proceed. It does mean an item briefed before this ships cannot be acked until re-dispatched, which is correct: its ack genuinely cannot be attributed.

The plan must include a test for step 4 specifically, because it is the difference between "we cannot attribute this ack" and "there was no ack" — the two must behave identically, and only the note should differ.

### 3.3 The gate

`github_verification_service`'s auto-merge path gains one condition, placed with the other pre-merge checks around `:233-264`:

```
auto-merge requires:
    merge_policy == "auto"          (existing)
    issue_type != "design"          (existing — C1 invariant)
    budget not exhausted            (existing)
    mergeable_state not transient   (existing)
    head == last_verified_sha       (existing)
    head is green                   (existing)
    ack satisfied by a DISTINCT member   <-- NEW
```

Failing the new condition is **not** an escalation — it routes to the existing `_fallback_to_human_merge` with a note naming the reason. A leader-owned code item therefore cannot auto-merge; it waits for you. Finding #1 is closed by construction rather than by prompt discipline.

### 3.4 Brief wording

The owner's brief already names the leader as "Team leader / approver" (`:428-432`). It gains one line stating that the ack must come from the leader's own Agent Mail reply, and that self-approval will be rejected. Wording is prompt-only and carries no enforcement weight — the enforcement is §3.2.

### 3.5 Tests (all offline, no GitHub needed)

Behavioral, one assertion each, following the repo's existing dispatch-test fixtures:

1. `deck_request_context(work_item_id=N)` puts `work_item_id` in the message payload; omitting it still works (existing callers unaffected).
2. A distinct-member answer on a linked thread ⇒ ack recorded, `ack_approver_member_id` set to that member.
3. An owner-authored answer (self-ack) ⇒ `409`, `ack_received_at` stays NULL.
4. No evidence at all ⇒ `409`, `ack_received_at` stays NULL.
5. **Unlinkable ack** — a distinct-member answer exists but no payload carries `work_item_id` ⇒ `409`, identical outcome to test 4, differing only in the note (§3.2.1 step 4).
6. A payload that is NULL or lacks the key does not raise — the query skips it.
7. A rejected ack still lets the monitor nudge, then escalate `leader_ack_timeout` — proving §3.2 reuses the existing path.
8. Auto-merge with CI-green + fresh head but **no** distinct ack ⇒ falls back to human merge, `auto_merged_at` stays NULL.
9. Auto-merge with CI-green + fresh head + distinct ack ⇒ merges.
10. `reset_for_retry` clears both new columns.
11. Replay of the live self-ack shape (`context_request` 16→16, `answer` from 16) ⇒ rejected. This is a regression test written directly from observed production data.

**Mutation requirement.** Each guard must be shown to bite:

| Mutant | Test that must fail |
|---|---|
| drop the `sender_member_id != owner` condition | 3 (self-ack) |
| accept an ack with no evidence row | 4 |
| treat missing linkage as satisfied | 5 |
| drop the new auto-merge condition | 8 |
| forget to clear the columns in `reset_for_retry` | 10 |

A guard whose test passes with the guard removed is decoration, and this has already bitten this project once: the G3 plan shipped two retention tests that were **silent** against the exact mutant they existed to catch (`if session.pid is not None:` for `if self._pid_is_running(session.pid):`) — 2 passed with the mutant in place. Only a third test, added because the implementer pushed back, caught it. Write the mutant list before the tests, not after.

---

## 4. PR2 — distinct commit and PR identity

### 4.1 What GitHub does and does not let us choose

Three identities are conflated in "PR author," with different mechanics:

| Identity | Determined by | Can vary per agent? |
|---|---|---|
| PR author | the credential that calls `gh pr create` | **No** — one App ⇒ one author |
| Commit author / committer | `GIT_AUTHOR_*` / `GIT_COMMITTER_*` per command | **Yes** |
| PR presentation (title, body, branch) | fully ours | **Yes** |

Decision: **one bot as author, per-slot identity everywhere else.** Per-slot bot accounts were considered and rejected — they multiply App registrations, secrets, and token refresh by the slot count, and a new slot could not dispatch until its identity was provisioned by hand.

Result for a Specialist-owned item:

```
PR author:      claude-deck-bot[bot]        <- distinct from juanrubio; you can approve
PR title:       [Specialist] fix: harden packaging retry path
Branch:         deck/specialist/issue-827
Commit author:  Specialist (Deck agent) <specialist+slot6@claude-deck.local>
Trailers:       Deck-Agent-Slot: 6 (Specialist)
                Deck-Work-Item: 41
```

Every commit, the title, and the branch name identify the agent. The author stays a single bot so branch protection is satisfiable.

### 4.2 Provisioning the bot identity (manual, yours to run)

Not automated, and deliberately outside the code:

1. Create a GitHub App with the minimum permissions: `contents:write`, `pull_requests:write`, `issues:write`, `checks:read`.
2. Install it on the target repos (`adrirubio/claude-deck`, the tizonia sandbox).
3. Store the App id and private key in `backend/.env` — which must stay **0600 and gitignored**, per the standing constraint. The key is never logged, never echoed, never committed.
4. The backend mints installation tokens (~1h TTL) and refreshes them; agents receive a short-lived token, never the private key.

### 4.3 Per-slot commit identity

Injected through the **existing** `extra_env` at `agent_team_service.py:619`, which already renders into `tmux new-session -e` flags via `_env_flags` (`spawn.py:38-76`) and is the same mechanism G3's slot rebinding reads:

```python
extra_env={
    ...existing CLAUDE_DECK_TEAM_* vars...,
    "GIT_AUTHOR_NAME": f"{slot.display_name} (Deck agent)",
    "GIT_AUTHOR_EMAIL": f"{slug}+slot{slot.id}@claude-deck.local",
    "GIT_COMMITTER_NAME": f"{slot.display_name} (Deck agent)",
    "GIT_COMMITTER_EMAIL": f"{slug}+slot{slot.id}@claude-deck.local",
}
```

`_env_flags` (`spawn.py:38-44`) validates the variable **name** against `[A-Z_][A-Z0-9_]*` and raises on a bad one; it does **not** validate the value. The four names above are constants, so they always pass.

**Value safety, measured rather than assumed.** A hostile `display_name` does pass through `_env_flags` untouched — verified: `{'GIT_AUTHOR_NAME': 'Bad; rm -rf /  $(whoami)'}` yields `['-e', 'GIT_AUTHOR_NAME=Bad; rm -rf /  $(whoami)']`. That is **not** a shell-injection risk, because `spawn_session` calls `subprocess.run` with an argv **list** and no `shell=True` (`spawn.py:79-84`), so no shell ever interprets the value. The plan should not add shell-escaping theater here.

What the value *does* need is to be a well-formed email local-part, since a display name with spaces or `@` produces a nonsense commit author that `git` will accept and that pollutes `git log` and `Co-authored-by` trailers. So slugification is a **correctness** requirement, not a security one: lowercase, strip to `[a-z0-9.-]`, collapse runs, and include a test with a display name containing spaces and punctuation.

The email domain is `.local` — deliberately non-routable and non-verifiable, so these commits can never be mistaken for a verified human identity.

The brief gains the title-prefix, branch-naming, and trailer conventions, plus an instruction to use the provided token for `gh pr create`.

### 4.4 Tests

1. Spawn env for a slot contains all four `GIT_*` vars with the slot's name and id.
2. A slot whose display name would produce an invalid env value is slugified safely (no `_env_flags` raise).
3. Brief contains the `[Slot]` prefix, `deck/<slot>/issue-<n>` branch instruction, and both trailers.
4. Token minting refreshes before expiry, and the private key never appears in any log record or brief.

### 4.5 Deployment (gated, manual, not part of the PR)

Restoring tizonia branch protection is the hard gate the soak log records, and the backup still exists — verified present at `/tmp/tizonia-master-protection-backup.json`, containing `required_approving_review_count: 1` and `enforce_admins: true`. **Copy it somewhere durable before relying on it; `/tmp` is not a safe home for the only copy of a gate.** Restore it only after PR2 is deployed and a bot-authored PR has been observed to be approvable.

---

## 5. Explicitly out of scope

- **`route_item`'s fallback is unchanged.** Refusing to route to the leader strands work when no specialist matches; the enforced gate makes leader ownership *safe* rather than *forbidden*.
- **No ack timeout changes.** No softening, no tiering, no idle monitor — that is #280, and mixing it in risks the C1 invariant.
- **No new `dispatch_status` values.**
- **Autonomy stays off** (`autonomy_enabled = 0`, both presets). Neither PR enables it, and neither restores branch protection.
- **Per-slot bot accounts** — considered, rejected in §4.1.

## 6. Deferred

- **Approval expiry.** An ack survives an arbitrary number of pushes after it was given; only auto-merge's head-freshness check bounds it. Re-approval after a force-push is a real question, and it belongs with #280's head re-confirm item rather than here.
- **External human approvers.** Attribution assumes the approver is an Agent Mail member. A GitHub PR review by a human is stronger evidence and is not currently read at all.

## 7. Success criteria

1. A self-ack cannot set `ack_received_at`, and the observed live shape (`context_request` 16→16 answered by 16) is rejected by a regression test.
2. Every recorded ack names its approver and the message that proves it, and an ack that cannot be attributed is rejected rather than assumed good.
3. An auto-merge cannot happen without a distinct approver, and failing that check falls back to human merge rather than escalating.
4. A bot-authored PR is approvable by `juanrubio`, so branch protection can be restored to `required_reviews=1, enforce_admins=true`.
5. Commits, PR titles, and branch names identify which agent produced them.
6. Every new guard is shown to bite by mutation.
