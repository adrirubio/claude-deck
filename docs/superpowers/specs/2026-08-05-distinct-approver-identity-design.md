# Distinct Approver Identity — Design (Findings #1 and #6)

**Date:** 2026-08-05
**Status:** Design, revision 2 — revised after implementer review of `8e0bdb8` found six blockers, all confirmed against source
**Closes:** Finding #1 (Leader self-ack), Finding #6 (agent commit identity collides with human reviewer identity)
**Both are Window 2 gates** — `merge_policy=auto` must not be enabled until PR0 and PR1 land.

**Relation to #280:** #280 is the *when do we stop waiting* theme (ack/idle timeout governance). This spec is the *who is a distinct party* theme. They share the ack as a data structure and nothing else. Deliberately kept apart: #280 warns that a uniform softening of the ack gate would reopen the C1 no-unreviewed-design invariant, and this spec does not touch timeout behavior at all.

**What revision 2 changed, and why.** Revision 1 rested on a premise that measurement destroyed: that `mail_messages.sender_member_id` is unforgeable. It is not (§1.5). Everything downstream of that premise had to be rebuilt. The changes:

| # | Revision 1 said | Measured reality | Now |
|---|---|---|---|
| 1 | mail sender identity is unforgeable | `POST /agent-mail/messages` has no auth and takes `sender_member_id` from the caller | **New PR0** — capability tokens, identity derived server-side (§3) |
| 2 | `request_status == 'acknowledged'` is approver evidence | it is set by the request **author** — the owner (`agent_mail_service.py:1306-1313`) | evidence is the leader-authored `answer` row only (§4.3) |
| 3 | "any member that is not the owner" is a distinct approver | 19 members exist, 12 with `team_slot_id = NULL` | approver must be the preset's **designated leader member** (§4.3) |
| 4 | no replay concern | `reset_for_retry` cannot delete mail rows; `accept_handoff:705` never clears approval | per-dispatch **nonce** + clear-on-owner-change (§4.2, §4.4) |
| 5 | "the backend mints and refreshes tokens" | one sentence standing in for a subsystem; no settings, no JWT, no cache | full lifecycle, and a **credential-helper callback** so no token is ever handed to a pane (§5.3) |
| 6 | `extra_env` at spawn carries identity | the **reuse** path returns at `:575`, before `spawn_session` at `:616` | per-worktree git config, not env (§5.4); `report_pr_opened` verifies the PR (§5.5) |

---

## 1. What the problem actually is

Findings #1 and #6 are one question asked at two layers — *who is a distinct party?* — and at both layers the current answer is "nobody, and nothing checks."

### 1.1 Finding #1 is worse than the run log records

The soak run log says a leader-owned code item under `merge_policy=auto` would have "leader-ack + CI as its ONLY gates." Measured, that overstates the ack's role.

`_ack_satisfied` (`backend/app/services/github_dispatch_service.py:902`) has exactly **one** caller: the monitor loop at `:778`, where it decides whether to nudge or escalate `leader_ack_timeout`. The auto-merge path (`github_verification_service.py:227-266`) gates on `merge_policy`, auto-merge budget, `mergeable_state`, head-freshness vs `last_verified_sha`, and CI-green. It never reads the ack.

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
| `mail_team_members` rows | 19 total; **12 have `team_slot_id = NULL`** |
| members bound to a slot | 6 — slots 1-6, exactly one member each |

The self-ack thread, verbatim:

```
id  kind             sender  recipient  thread_root  request_status
114 context_request  16      16         NULL         answered
115 answer           16      NULL       114          NULL
```

The healthy shape also exists, which is what the fix preserves — e.g. id 348: `context_request` sender 17 (Specialist) → recipient 16 (Leader).

Three conclusions: the defect is real and total on the path it affects; enforcing a distinct approver would reject a **rare** case (3/81 requests), not break normal operation; and "not the owner" is far too weak a test, because 12 of 19 members are not team slots at all (`juan`, `claude-deck`, `snazzyemail`, per-repo members). An answer from any of those would pass a not-the-owner check.

### 1.4 Finding #6 is absent plumbing

Nothing in the backend sets `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, or a per-agent token — verified by search across `backend/app/`. Agents inherit the ambient identity of the host shell:

```
git config user.name   -> Juan A. Rubio
gh auth active account -> juanrubio        <- also the human reviewer
```

Agents open PRs themselves via `gh pr create` in their panes; the backend never creates a PR (`github_client.py` has `get_pull`, `mark_pull_ready_for_review`, `merge_pull` and no create). GitHub forbids approving your own PR, so with `required_approving_review_count=1` the human-merge gate deadlocks — observed in the soak, where all 3 PRs stuck `REVIEW_REQUIRED`/BLOCKED and branch protection had to be relaxed as a temporary accommodation.

### 1.5 The asymmetry revision 1 relied on does not exist

Revision 1 claimed this table:

| Signal | Set by | Owner can forge? |
|---|---|---|
| `mail_messages.sender_member_id` on an `answer` row | MCP shim, from its own registration | ~~No~~ |

That is **wrong**, and it was the foundation of the whole design. Measured:

```python
# app/api/v1/agent_mail.py:65-70 — no auth dependency of any kind
@router.post("/messages", response_model=MailMessageResponse)
async def send_message(request: MailMessageCreate, db: AsyncSession = Depends(get_db)):

# app/models/schemas.py:1867-1874 — the sender is a caller-supplied field
class MailMessageCreate(BaseModel):
    kind: str = "message"
    sender_member_id: Optional[int] = None

# app/services/agent_mail_service.py:859 — checks the CLAIM, not the CALLER
if root.recipient_member_id != request.sender_member_id:
    raise ValueError("only the context request recipient can answer it")
```

The shim fills `sender_member_id` honestly, but the shim is not the only writer. Every agent pane has Bash and the backend listens on localhost, so an owner blocked on "you need leader approval" can post an `answer` as the leader with one `curl`. `:859` compares two caller-supplied values and proves nothing about who is calling.

This is not a malice argument. An agent taking a shortcut past a blocking gate is ordinary agentic behavior, and it is exactly the behavior a gate exists to constrain. A gate a blocked agent can step around is decoration.

**Consequence:** trustworthy attribution has to be *created* before it can be *read*. That is PR0.

The one signal that behaves as revision 1 hoped, and still does: `_brief_delivered` (`:806-824`) verifies an owner-side claim against `MailReceipt.read_at`, and `brief_message_id` (`database.py:439-440`) is precedent for storing a mail message id on a work item. The shape of the fix survives; only its trust basis had to be built.

---

## 2. Architecture

Three PRs. Each is independently reviewable and leaves the system in a coherent state.

```
PR0  Agent Mail capability tokens               (auth; no dispatch logic)
     registration returns a token; identity-bearing writes require it
     and derive the sender server-side

PR1  Approval attribution + a real gate         (pure code, testable offline)
     1. link ack requests to work items with a per-dispatch nonce
     2. record who approved; require the designated leader; reject replay
     3. make auto-merge require a valid distinct approval
     4. surface the new fields in the work-item response

PR2  Distinct commit/PR identity                (needs a GitHub App)
     one bot as PR author, per-slot commit identity via per-worktree
     git config, tokens via a credential-helper callback, and
     verification that the reported PR is what it claims to be
```

**Why PR0 is separate and first.** PR1's entire value is that its evidence cannot be fabricated. Shipping PR1 without PR0 produces a gate that logs an approver id an agent chose for itself — worse than no gate, because it reads as enforcement. PR0 is also a strictly larger blast radius (every mail write path, the shim, the UI, ~13 test call sites), and a reviewer must be able to reject the auth change without rejecting the dispatch change. PR0 additionally closes the separately-tracked `/dispatch-status` auth gap, which is the same defect one router over.

**Why PR2 is last.** Its failure mode is a *deadlocked* merge, not a *bad* merge. If PR2 slips, autonomy is strictly safer than today rather than blocked on provisioning.

---

## 3. PR0 — Agent Mail capability tokens

### 3.1 The precedent to follow

`mail_external_actors` already solves this problem for external orchestrators: a bearer token, sha256-hashed at rest, compared with `hmac.compare_digest`, resolved into an identity by a FastAPI dependency (`external_agent_mail.py:45-55`, `external_agent_mail_service.py:57-121`). PR0 applies the same pattern to *sessions* instead of *actors*. No new concepts, no new libraries.

### 3.2 Schema

`mail_agent_sessions` gains one nullable column via the migration ladder. The `session_columns` set already exists for this table at `app/database.py:353`, so the new rung goes directly after the existing `team_slot_id` rung at `:358`:

```python
if session_columns and "capability_token_hash" not in session_columns:
    await conn.execute(text("ALTER TABLE mail_agent_sessions ADD COLUMN capability_token_hash TEXT"))
```

Nullable, so existing rows migrate silently and pre-upgrade sessions simply have no token until they next register (the shim heartbeats every `HEARTBEAT_INTERVAL_SECONDS`, so this self-heals without operator action).

`session_key` is **not** usable as the token: it is returned in `MailSessionResponse.session_key` (`schemas.py:1817`) from the unauthenticated `GET /agent-mail/team`, so every agent can already read every other agent's session key. The token must be a separate secret that is never echoed in any response body except the one that mints it.

### 3.3 Minting

`POST /agent-mail/agent/register` mints `secrets.token_urlsafe(32)` on every registration, stores only `sha256(token)`, and returns the plaintext once in `MailAgentRegisterResponse`. Re-registration rotates it — which is correct: the shim re-registers on heartbeat, so a token's useful life is one heartbeat interval, and a stolen token expires on its own.

`register_session` already resolves and *validates* team context (`agent_mail_service.py:276-305` checks provider and repo identity against the slot before accepting a claimed `team_slot_id`), so the member the token is bound to is not simply whatever the caller asked for.

### 3.4 Enforcement

A dependency mirroring `external_actor`:

```python
async def mail_session(
    x_deck_session_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> MailAgentSession:
    """Resolve the calling session from its capability token, or 401."""
```

Applied to the endpoints whose semantics depend on *who is calling* — and only those:

| Endpoint | Enforcement |
|---|---|
| `POST /agent-mail/messages` | sender derived from the token's session member |
| `POST /agent-mail/messages/{id}/ack` | acking member derived from the token |
| `POST /agent-mail/messages/{id}/read` | reading member derived from the token |
| `POST /agent-teams/dispatch-status` | `reporting_slot_id` derived from the token |

Read endpoints (`GET /team`, `GET /messages`, `GET /agent/inbox`) are untouched. This is an attribution fix, not a confidentiality fix — and confining it keeps PR0 reviewable.

**Derive, do not compare.** The server sets `sender_member_id` from the token's session. A caller-supplied `sender_member_id` that disagrees is a `403`, not a silent overwrite: silent overwriting would mask a misconfigured shim as success. A caller-supplied value that *agrees* is accepted, which keeps the shim's current payload shape valid.

### 3.5 The operator path stays open

The Agent Mail UI writes as an operator-chosen member (`ThreadDialog.tsx:159` sends `sender_member_id: senderId`) and holds no session token. Two write paths therefore need a non-session identity: the UI's reply/compose, and its ack.

Rather than invent a third auth scheme, the UI authenticates as an **external actor** — the mechanism that already exists for exactly this, is loopback-gated at creation (`external_agent_mail.py:76-78`), and lands in `sender_actor_id` rather than `sender_member_id`, so operator-authored messages are *distinguishable from* agent-authored ones in the data.

This has a consequence PR1 depends on and §4.3 states explicitly: an operator-authored message has `sender_member_id = NULL`, so it can never be mistaken for the leader's approval. A human who wants to approve does it by merging, not by typing into the mail UI.

### 3.6 Tests

1. Registration returns a token; the hash is stored and the plaintext is not.
2. `POST /messages` without a token ⇒ `401`.
3. With a valid token ⇒ `sender_member_id` equals the token's session member, even when the body omits it.
4. With a valid token and a *conflicting* `sender_member_id` ⇒ `403`.
5. The forgery from §1.5 — posting an `answer` claiming to be another member — ⇒ `403`. Written directly from the live self-ack shape.
6. Re-registration rotates the token; the old token ⇒ `401`.
7. An external actor's token can still send, and lands in `sender_actor_id` with `sender_member_id = NULL`.
8. `POST /dispatch-status` derives `reporting_slot_id` from the token; a body claiming a different slot ⇒ `403`.

**Mutation requirement.**

| Mutant | Test that must fail |
|---|---|
| dependency present but return value unused (body value still trusted) | 3, 5 |
| conflicting sender silently overwritten instead of rejected | 4 |
| token compared with `==` instead of `hmac.compare_digest` | — (not observable by test; enforce in review) |
| rotation leaves the old hash valid | 6 |

The third row is deliberate. A timing-safe comparison is not test-observable, so listing it as a review item is honest; claiming a test covers it would not be.

### 3.7 Blast radius, stated plainly

- `backend/mcp_shim/agent_mail_server.py` — store the token in `_state` at registration, send it as a header in `_request`/`_dispatch_request`. The shim already does exactly this for the Agent Bridge terminal token (`_bridge_request_with_token`, `:117-132`), so the pattern is in-file.
- `frontend/src/features/agent-mail/api.ts` — three write calls gain actor auth.
- ~13 test call sites hitting `agent-mail/messages` across 5 test files.

If PR0's cost proves larger than this in practice, the fallback is to weaken the threat model explicitly in §1.5 and file the auth work separately — **not** to ship PR1 with unverifiable evidence and call it a gate.

---

## 4. PR1 — approval attribution and the distinct-approver gate

### 4.1 Schema

`github_work_items` gains three nullable columns, following `app/database.py:421-440` exactly:

```python
if work_item_columns and "ack_approver_member_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approver_member_id INTEGER"))
if work_item_columns and "ack_evidence_message_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_evidence_message_id INTEGER"))
if work_item_columns and "dispatch_nonce" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_nonce TEXT"))
```

All nullable, so existing rows migrate silently — and a pre-upgrade row with `dispatch_nonce = NULL` cannot be acked until re-dispatched, which §4.3 rule 5 makes explicit and correct.

### 4.2 The dispatch nonce

`secrets.token_hex(8)`, minted at dispatch, following `workspace.lease_token` (`github_workspace_service.py:130`) — same generator, same lifecycle shape, same purpose: bind a claim to one attempt.

Minted where `dispatched_at` is set (`github_dispatch_service.py:344`), so one nonce per dispatch attempt. Cleared or replaced at every point where the attempt's identity changes:

| Event | Site | Action |
|---|---|---|
| dispatch | `:344` | mint a fresh nonce |
| retry | `reset_for_retry:64-71` | clear nonce + both ack columns alongside the existing `ack_received_at = None` |
| handoff accepted | `accept_handoff:705` | clear **both ack columns**; **keep the nonce** — see below |

The nonce is a *correlation* value, not a secret — PR0 provides the authentication. It exists so that evidence from attempt N cannot satisfy attempt N+1, which no amount of authentication would prevent on its own.

**Why handoff keeps the nonce.** Clearing it there would deadlock the item. `accept_handoff` (`:697-710`) changes `owner_slot_id` and commits — it sends **no new brief**, so the new owner never learns a replacement nonce, and every subsequent ack attempt would refuse with `no_linkage` forever. Clearing the *ack columns* is what matters: the new owner must obtain their own approval, and §4.3 rule 3 requires the `context_request` to have been sent **by the current owner member**, so the previous owner's request cannot satisfy the new one even though the nonce is unchanged. Retry is different — it re-dispatches through `:344`, which mints a fresh nonce, so clearing is both safe and necessary there.

**The deferred-retry path is already covered.** `reset_for_retry` returns early at `:56-63` when the item still holds a lease, setting only `retry_requested_at`. The monitor at `:84-98` later re-selects those items and calls `reset_for_retry` **again** once the lease is gone, and that second call reaches the clearing block. So the deferred path clears the columns too, with no extra work — but a test must prove it, because "the early return skips the clear" is exactly the kind of thing that looks broken and is not (test 10b).

### 4.3 Structured evidence

```python
@dataclass(frozen=True)
class AckEvidence:
    """Why an ack was accepted or refused. `reason` is operator-facing."""
    ok: bool
    reason: str                       # one of: "ok", "self_ack", "not_designated_approver",
                                      #         "no_linkage", "stale_nonce", "no_leader", "no_owner"
    approver_member_id: int | None = None
    evidence_message_id: int | None = None
```

A `MailMessage | None` return cannot carry the distinct refusal reasons the tests below require — revision 1 asked for reasons it had no way to express. This type is the fix.

`record_ack_received` gains a `scope` parameter (the `/dispatch-status` route at `agent_teams.py:294` already loads it) and resolves slots itself via the existing `agent_team_service._slots_for_preset(db, scope.preset_id)` — do not write a new query. It then calls `_ack_evidence(db, item, preset_slots)` and stops trusting the reporter. Rules, in order:

1. Resolve the **designated leader member**: `_leader_slot(preset_slots)` → `_slot_member(db, leader.id)`. This is the *only* acceptable approver. Not "any member," not "any slot member" — the specific member bound to the leader slot. Live data justifies the strictness: 12 of 19 members have no slot at all. If either the leader slot or its member cannot be resolved, refuse `no_leader` — fail closed, never treat an unresolvable approver as satisfied.
2. Resolve the owner member via the existing `_owner_member(db, item)`. If the owner **is** the designated leader, refuse with `self_ack` immediately — this is Finding #1's exact shape and needs no evidence lookup to reject. If the owner member cannot be resolved, refuse `no_owner`.
3. Find `context_request` rows whose payload `work_item_id` equals `item.id`, sent by the owner member and addressed to the leader member. If **no** row matches the work item at all ⇒ refuse `no_linkage`. If a row matches the work item but **none** matches `item.dispatch_nonce` ⇒ refuse `stale_nonce`. Evaluate in that order, so the two reasons stay distinguishable: `no_linkage` means "they never asked," `stale_nonce` means "they are replaying an older attempt's approval." A NULL `item.dispatch_nonce` (a pre-upgrade row) can never match, so it refuses `stale_nonce` — correct, and §4.1 already states such items must be re-dispatched.
4. Among the matching threads, require an `answer` row whose `thread_root_id` is that `context_request` and whose `sender_member_id == leader_member.id`. Found ⇒ accept, recording `approver_member_id` and `evidence_message_id` (the **answer** row's id, not the request's — the answer is the approval). If more than one qualifies, take the earliest by `created_at`, so the recorded evidence is the approval that actually unblocked the owner. Not found ⇒ refuse `not_designated_approver`.
5. Accepted ⇒ set `ack_received_at`, `ack_approver_member_id`, `ack_evidence_message_id`. Refused ⇒ **do not** set `ack_received_at`; return `409` from `/dispatch-status` with `reason` in the detail.

Rule 1's `no_leader` matters more than it looks: `_leader_slot` returns `None` when no slot is enabled, and `_slot_member` returns `None` when a slot has no registered member. Both are reachable — a preset can be edited while an item is in flight. Treating either as "no approver required" would turn a misconfiguration into an open gate.

**Do not use `request_status`.** Revision 1's predicate accepted `request_status == 'acknowledged'` as approver evidence. Measured, that value is set by the request **author**:

```python
# agent_mail_service.py:1306-1313
if message is not None and message.kind == "answer" and message.thread_root_id:
    root = await db.get(MailMessage, message.thread_root_id)
    if (root is not None
            and root.sender_member_id == member_id      # <-- the OWNER
            and root.request_status == "answered"):
        root.request_status = "acknowledged"
```

So `acknowledged` means *the owner has read the reply* — the opposite of approval. Using it would have let an owner mark its own item approved through the ordinary, un-hacked mail flow. Only the leader-authored `answer` row counts.

A refused ack leaves the item un-acked, so the **existing** monitor path at `:778-791` takes over: nudge, then `leader_ack_timeout`. No new `dispatch_status` value, no new escalation reason.

### 4.4 The anchor does not exist yet — PR1 must create it

There is no way to link an ack request to a work item today:

- `mail_messages` columns are `id, thread_root_id, kind, sender_member_id, sender_actor_id, recipient_member_id, subject, body_markdown, payload, request_status, created_at` — no work-item column.
- `deck_request_context` (`mcp_shim/agent_mail_server.py:349-374`) accepts `to_member_id, topic, why_needed, files_or_symbols`. No `work_item_id`.
- The work item appears in ack requests only as **prose** in `why_needed`, e.g. message 80: *"Issue #852 requires Leader acknowledgment before implementation starts."* Five such rows exist. Parsing that would be guessing.

PR1's **first** task is therefore the linkage:

1. `deck_request_context` gains optional `work_item_id: Optional[int] = None` and `dispatch_nonce: Optional[str] = None`, forwarded into the message payload. Optional keeps every existing caller working — the tool serves ordinary questions too.
2. `_leader_ack_instruction` (`:541-573`) passes both, taking the nonce from the brief. The brief already interpolates `item.id`, so this is a wording change plus one new interpolation.
3. `_ack_evidence` matches on the payload pair via the SQLAlchemy JSON accessor (`MailMessage.payload["work_item_id"].as_integer()`), **not** raw `->>`. Both work on this venv's SQLite (verified on 3.45.1: `json_extract` and `->>` each return `41` for `{"work_item_id": 41}`), but `->>` needs SQLite ≥ 3.38 and the ORM form stays portable. `payload` is nullable and free-form, so the filter must tolerate NULL and missing keys without raising.
4. **No linkage ⇒ no evidence ⇒ refuse.** Fails closed, per the standing G2/G3 rule that inability to observe is not permission to proceed. An item briefed before this ships cannot be acked until re-dispatched — correct, because its ack genuinely cannot be attributed.

### 4.5 The gate

`github_verification_service`'s auto-merge path gains one condition among the existing pre-merge checks (`:227-266`):

```
auto-merge requires:
    merge_policy == "auto"                    (existing)
    issue_type != "design"                    (existing — C1 invariant)
    not already human-merge-noted             (existing)
    budget not exhausted                      (existing)
    mergeable_state not transient             (existing)
    head == last_verified_sha                 (existing)
    head is green                             (existing)
    ack_approver_member_id is the leader      <-- NEW
    and differs from the owner's member
```

The check reads the **persisted** columns, not a fresh mail lookup: PR0 plus §4.3 mean the columns can only have been written by a verified approval, and re-deriving at merge time would read a mail table that may have changed for unrelated reasons.

**Do not route this through `_ack_satisfied`.** That function short-circuits on `if item.pr_number is not None: return True` (`:903-904`), which is correct for its actual job — once a PR exists, nudging the leader for an ack is pointless. But auto-merge only ever runs on items that **have** a `pr_number` (`github_verification_service.py:99` filters on `pr_number.is_not(None)`), so reusing `_ack_satisfied` as the merge gate would return `True` unconditionally, every time. The gate would be a no-op that reads like enforcement — the same failure mode as a silent test.

So the new condition is a **separate** predicate reading `ack_approver_member_id` directly, and `_ack_satisfied` keeps its one existing caller and its current behavior. Test 12 is the one that catches this: an item with a PR, CI-green, fresh head, and no approval must **not** merge. Written against `_ack_satisfied` it would pass while proving nothing.

Failing it routes to the existing `_fallback_to_human_merge` (`:421-432`), which sets `ready_for_review` and a note — and because that note is matched by `_HUMAN_MERGE_NOTE_PREFIXES` (`:20-25`), the new note **must** start with `"Auto-merge blocked"` so the fallback is sticky and does not re-run every poll. Revision 1 missed this; a note with any other prefix would loop.

A leader-owned code item therefore cannot auto-merge; it waits for a human. Finding #1 is closed by construction rather than by prompt discipline.

### 4.6 Operator and agent visibility

`GithubWorkItemResponse` (`schemas.py:2272-2299`) and `_work_item_response` (`agent_teams.py:196-229`) both enumerate every field by hand, so a new column is invisible until added in **both** places. All three new columns are added to both, which is what makes the gate auditable by an operator in the UI *and* by the leader through `deck_list_work_items`.

An unaudited safety gate is a claim, not a control — and this codebase's serializer style means "add the column" and "expose the column" are genuinely separate steps that a plan must both name.

### 4.7 Brief wording

The owner's brief already names the leader as "Team leader / approver" (`:428-432`). It gains one line: the ack must come from the leader's own Agent Mail answer in the thread the owner opened with `work_item_id` and `dispatch_nonce`, and self-approval is rejected. Wording carries no enforcement weight — §4.3 does.

### 4.8 Tests (all offline, no GitHub needed)

1. `deck_request_context(work_item_id=N, dispatch_nonce=X)` puts both in the payload; omitting them still works.
2. Leader-authored answer on a correctly-linked thread ⇒ ack recorded, `ack_approver_member_id` == leader member.
3. Owner **is** the leader (`leader_fallback` shape) ⇒ `409` `self_ack`, `ack_received_at` stays NULL.
4. Answer authored by a **non-leader** slot member ⇒ `409` `not_designated_approver`. This is blocker 3: a Specialist answering does not approve.
5. Answer authored by a member with `team_slot_id = NULL` (e.g. `juan`, member 19) ⇒ `409` `not_designated_approver`.
6. No evidence at all ⇒ `409` `no_linkage`.
7. Linkage present but `dispatch_nonce` is from a previous attempt ⇒ `409` `stale_nonce`.
8. Payload NULL or missing the key ⇒ no raise, treated as `no_linkage`.
    8b. No enabled leader slot, or a leader slot with no registered member ⇒ `409` `no_leader`, not an accepted ack.
9. A refused ack still lets the monitor nudge, then escalate `leader_ack_timeout`.
10. `reset_for_retry` clears all three columns; an ack valid before the retry is refused after it.
    10b. **Deferred retry** — `reset_for_retry` on an item that still holds a lease returns early without clearing; the monitor's second call, after release, does clear. Both halves asserted.
11. `accept_handoff` clears both ack columns and **keeps** the nonce; the previous owner's approval does not carry to the new owner, *and* the new owner can still be acked (proving the §4.2 deadlock is avoided).
12. Auto-merge with CI-green + fresh head but no distinct approval ⇒ falls back to human merge, `auto_merged_at` stays NULL.
13. Auto-merge with CI-green + fresh head + valid distinct approval ⇒ merges.
14. The fallback note starts with `"Auto-merge blocked"`, so a second poll does not re-run the fallback.
15. Replay of the live self-ack shape (`context_request` 16→16, `answer` from 16) ⇒ refused. Regression test written directly from production data.
16. All three columns appear in `GithubWorkItemResponse` for a real item.

**Mutation requirement.** Each guard must be shown to bite:

| Mutant | Test that must fail |
|---|---|
| drop the owner-is-leader early refusal | 3 |
| accept any non-owner sender instead of the designated leader | 4, 5 |
| accept `request_status == 'acknowledged'` as evidence (revision 1's bug) | 3 |
| ignore `dispatch_nonce` in the payload match | 7 |
| treat missing linkage as satisfied | 6 |
| treat an unresolvable leader as satisfied | 8b |
| drop the new auto-merge condition | 12 |
| implement the gate as `_ack_satisfied(item)` (always `True` once a PR exists) | 12 |
| forget to clear columns in `reset_for_retry` | 10 |
| clear only on the immediate path, not the deferred one | 10b |
| forget to clear columns in `accept_handoff` | 11 |
| also clear the nonce in `accept_handoff` (deadlocks the new owner) | 11 |
| change the fallback note prefix | 14 |

A guard whose test passes with the guard removed is decoration, and this has bitten this project once: the G3 plan shipped two retention tests that were **silent** against the exact mutant they existed to catch (`if session.pid is not None:` for `if self._pid_is_running(session.pid):`) — 2 passed with the mutant in place. Write the mutant list before the tests.

---

## 5. PR2 — distinct commit and PR identity

### 5.1 What GitHub does and does not let us choose

| Identity | Determined by | Can vary per agent? |
|---|---|---|
| PR author | the credential that calls `gh pr create` | **No** — one App ⇒ one author |
| Commit author / committer | git config or `GIT_*` env, per invocation | **Yes** |
| PR presentation (title, body, branch) | fully ours | **Yes** |

Decision: **one bot as author, per-slot identity everywhere else.** Per-slot bot accounts were rejected — they multiply App registrations, secrets, and refresh by the slot count, and a new slot could not dispatch until provisioned by hand.

Result for a Specialist-owned item:

```
PR author:      claude-deck-bot[bot]        <- distinct from juanrubio; you can approve
PR title:       [Specialist] fix: harden packaging retry path
Branch:         deck/specialist/issue-827
Commit author:  Specialist (Deck agent) <specialist+slot6@claude-deck.local>
Trailers:       Deck-Agent-Slot: 6 (Specialist)
                Deck-Work-Item: 41
```

The `.local` domain is deliberately non-routable and unverifiable, so these commits can never be mistaken for a verified human identity.

### 5.2 Provisioning (manual, yours to run)

1. Create a GitHub App with minimum permissions: `contents:write`, `pull_requests:write`, `issues:write`, `checks:read`.
2. Install it on the target repos (`adrirubio/claude-deck`, the tizonia sandbox). Record the **installation id** — App credentials alone cannot mint a usable token.
3. Store the App id and private key in `backend/.env`, which stays **0600 and gitignored**. The key is never logged, never echoed, never committed, never sent to a pane.

### 5.3 Token lifecycle

Revision 1 covered this in one sentence. It is a subsystem, and it needs to be specified.

**Settings** (`config.py`, alongside the existing `github_token: str = ""` at `:39`):

```python
github_app_id: str = ""
github_app_private_key_path: str = ""     # a path, not the key — keeps the key out of process env
github_app_installation_id: int = 0
github_app_token_refresh_margin_seconds: int = 300
```

Empty values mean "App auth not configured," and the system falls back to today's `github_token` behavior. No configuration change is forced on anyone by this PR landing.

**Dependencies.** App auth needs a JWT signed with RS256, which needs `pyjwt` and `cryptography`. Both are importable in the current venv (2.13.0 / 49.0.0) but **neither is in `requirements.txt`** — PyJWT is a transitive dependency of `mcp`. Relying on that is a latent break: a legitimate `mcp` release could drop it. Both must be added as explicit direct dependencies, with the extra spelled `pyjwt[crypto]`.

**Minting.** Standard two-step: sign a short-lived JWT with the App private key, exchange it at `POST /app/installations/{id}/access_tokens` for an installation token (~1h TTL). GitHub returns `expires_at`; store it.

**Caching.** One in-process cached token guarded by an `asyncio.Lock`, refreshed when `expires_at - now < refresh_margin`. The lock prevents a thundering herd of concurrent dispatches each minting a separate token. Not persisted — a backend restart mints a fresh one, which is cheap and avoids storing a live credential at rest.

**Scoping.** Installation tokens are already scoped to the installation's repositories. The optional `repositories` parameter narrows further; use it, keyed on the scope's repo, so a token minted for one scope cannot write to another.

**Never log it.** The token, the JWT, and the private key are excluded from every log line and every brief. A test asserts this.

### 5.4 Delivery: a credential helper, not an environment variable

Revision 1 put the token in `extra_env` at spawn. Three measured problems:

1. The **reuse** path returns at `agent_team_service.py:575`, before `spawn_session(extra_env=...)` at `:616`. A reused session receives no `extra_env` at all — so the identity silently does not apply on exactly the path that G2's Finding 13 already showed is the common one.
2. A pane's env is fixed at spawn, but an installation token lives ~1h and a dispatch can run longer. There is no channel to replace it.
3. A token in a pane's environment is readable by anything in that pane and outlives its usefulness.

All three dissolve if the pane never holds a token. Instead, configure the **workspace worktree**, which is per-dispatch state Deck already provisions and controls:

```
git -C <workspace> config extensions.worktreeConfig true
git -C <workspace> config --worktree user.name  "Specialist (Deck agent)"
git -C <workspace> config --worktree user.email "specialist+slot6@claude-deck.local"
git -C <workspace> config --worktree credential.https://github.com.helper ""
git -C <workspace> config --worktree --add credential.https://github.com.helper "<deck helper>"
```

Measured on git 2.43.0 in a throwaway repo:

- Per-worktree config is isolated: the helper set in the worktree did not appear in the main checkout (`git config --get` exited 1 there).
- Per-worktree identity is isolated: a commit in the worktree was authored by `Specialist (Deck agent) <specialist+slot6@claude-deck.local>` while a commit in the main checkout was authored by the human.
- The **URL-scoped** form is required. Setting plain `credential.helper` did **not** win — git still used the human's `credential.https://github.com.helper` from `~/.gitconfig`, and the real `gh` OAuth token came back. Only `credential.https://github.com.helper`, emptied first then re-added, overrode it. The empty-then-add pattern is the same one `~/.gitconfig` itself uses, and it matters: without it the human's helper stays in the list and may answer first.
- The helper is invoked **per git command**, and returned a distinct value on each of two consecutive `git credential fill` calls (different sha256 prefixes one second apart). So freshness is automatic — the token is minted at use time, never stored, and the ~1h TTL stops being a problem to manage.
- `config.worktree` lives in `.git/worktrees/<name>/`, outside the working tree, so it is not committable and cannot leak into a PR (`git status --porcelain` stayed clean).

The helper is a small executable that asks Deck for a token on `get` and prints `username=x-access-token` plus `password=<token>`. Measured: with `credential.https://github.com.helper` pointing at it, `git credential fill` returned exactly those values.

**One env var still covers `gh`.** Measured: `GH_TOKEN=<value> gh auth git-credential get` echoes `username=x-access-token / password=<value>`, so `gh` and git can share one credential. But that only works *because* of a user-level `~/.gitconfig` line (`credential.https://github.com.helper=!/usr/bin/gh auth git-credential`) — host configuration this repo does not control and must not depend on. The worktree helper makes the git side explicit and self-contained; `GH_TOKEN` remains for `gh pr create` in the pane, where a short-lived token in the environment is the price of `gh` working at all.

**Bounding that residual.** `GH_TOKEN` in the pane is the one place a live credential is exposed, and it applies to spawn and reuse alike. The reuse path therefore needs the same treatment as spawn — either a fresh session per dispatch, or a documented mechanism for setting it in an existing pane. The plan must pick one and test it; "spawn sets it" is not sufficient given `:575`.

### 5.5 Verify the PR, do not trust the report

`report_pr_opened` (`github_verification_service.py:44-86`) makes **no** GitHub call. It accepts `pr_number` and records it. So an agent can report any number — including a PR in another repo, or someone else's — and Deck will thereafter verify CI and potentially auto-merge *that* PR.

With auto-merge enabled, this is the shortest path from a wrong report to a merged stranger's code. It gains a verification step via the existing `client.get_pull`:

| Check | Refuse if |
|---|---|
| repository | `head.repo.full_name` != the scope's `owner/repo` |
| author | `user.login` != the configured bot login (when App auth is configured) |
| head branch | `head.ref` does not match the expected `deck/<slot>/issue-<n>` pattern for this item |

A refusal is a `409` and leaves `pr_number` unset, so the item stays dispatched and the existing monitor handles it. When App auth is not configured, the author check is skipped rather than failing every report — otherwise this PR would break the current working flow for anyone who has not provisioned an App.

`report_pr_opened` currently takes no `client` parameter and never touches the network; adding one changes its signature and every existing test that calls it. The plan must name that.

### 5.6 Tests

1. Workspace provisioning sets all four per-worktree config values; a second worktree in the same repo is unaffected.
2. The URL-scoped helper wins over an ambient `credential.https://github.com.helper` — the exact case that failed when measured with the unscoped key.
3. A slot whose display name contains spaces and punctuation is slugified into a valid email local-part (lowercase, `[a-z0-9.-]`, collapsed runs). This is a **correctness** requirement, not a security one: `_env_flags` (`spawn.py:38-44`) validates variable *names* against `[A-Z_][A-Z0-9_]*` and raises on a bad one, but does not validate values — and `subprocess.run` is called with an argv list and no `shell=True` (`:79-84`), so no shell ever interprets a value. Measured: `{'GIT_AUTHOR_NAME': 'Bad; rm -rf / $(whoami)'}` passes through untouched and harmlessly. The plan must not add shell-escaping theater; a malformed email pollutes `git log` and `Co-authored-by` trailers, and that is the real defect.
4. The token cache refreshes inside the margin and reuses outside it; concurrent callers mint once (lock held).
5. The private key, the JWT, and the token appear in no log record and no brief.
6. `pyjwt[crypto]` and `cryptography` are declared in `requirements.txt`.
7. With App auth unconfigured, dispatch still works on the existing `github_token` path.
8. `report_pr_opened` refuses a PR in a different repo (`409`, `pr_number` unset).
9. `report_pr_opened` refuses a PR whose author is not the bot, when App auth is configured.
10. `report_pr_opened` refuses a PR whose head branch does not match the item's expected branch.
11. `report_pr_opened` skips the author check when App auth is unconfigured.
12. Brief contains the `[Slot]` prefix, the `deck/<slot>/issue-<n>` branch instruction, and both trailers.

### 5.7 Deployment (gated, manual, not part of the PR)

Restoring tizonia branch protection is the hard gate the soak log records. The backup exists at `/tmp/tizonia-master-protection-backup.json` (`required_approving_review_count: 1`, `enforce_admins: true`). **Copy it somewhere durable first** — `/tmp` is not a safe home for the only copy of a gate. Restore only after PR2 is deployed and a bot-authored PR has been observed to be approvable by `juanrubio`.

---

## 6. Explicitly out of scope

- **`route_item`'s fallback is unchanged.** Refusing to route to the leader strands work when no specialist matches; the enforced gate makes leader ownership *safe* rather than forbidden.
- **No ack timeout changes.** No softening, no tiering, no idle monitor — that is #280, and mixing it in risks the C1 invariant.
- **No new `dispatch_status` values.**
- **Autonomy stays off** (`autonomy_enabled = 0`, both presets). No PR here enables it, and none restores branch protection.
- **Confidentiality of mail reads.** PR0 authenticates identity-bearing *writes*. `GET /team` and `GET /messages` stay open; any agent can still read the roster and message list. That is a real gap and a separate decision.
- **Per-slot bot accounts** — considered, rejected in §5.1.

## 7. Deferred

- **Approval expiry.** An ack survives an arbitrary number of pushes after it was given; only auto-merge's head-freshness check bounds it. The nonce bounds it per *dispatch*, not per *push*. Re-approval after a force-push belongs with #280's head re-confirm item.
- **External human approvers.** Attribution assumes the approver is an Agent Mail member. A GitHub PR review by a human is stronger evidence and is not read at all.
- **Timing-safe token comparison as a tested property.** Enforced by review in PR0 (§3.6), not by a test.

## 8. Success criteria

1. An agent cannot post a message as another member: the §1.5 forgery returns `403`.
2. A self-ack cannot set `ack_received_at`, and the live shape (`context_request` 16→16 answered by 16) is refused by a regression test.
3. Only the designated leader member's own answer can approve — not any non-owner, and not a member with no slot.
4. Evidence from a previous dispatch attempt cannot approve the current one, across both retry and handoff.
5. Every recorded ack names its approver and the message that proves it, and all three columns are visible to operators and to `deck_list_work_items`.
6. Auto-merge cannot happen without a valid distinct approval, and failing that check falls back to human merge stickily, without escalating.
7. A bot-authored PR is approvable by `juanrubio`, so branch protection can be restored to `required_reviews=1, enforce_admins=true`.
8. Commits, PR titles, and branch names identify which agent produced them, on the reuse path as well as the spawn path.
9. A reported PR that is in the wrong repo, from the wrong author, or on an unexpected branch is refused.
10. No agent pane ever holds a long-lived GitHub credential, and no log or brief contains the App private key.
11. Every new guard is shown to bite by mutation.
