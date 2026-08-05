# Distinct Approver Identity — Design (Findings #1 and #6)

**Date:** 2026-08-05
**Status:** Design, revision 3 — revised after a second implementer review of `d3d35b6` found six further blockers, all confirmed against source
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
| 6 | `extra_env` at spawn carries identity | the **reuse** path returns at `:575`, before `spawn_session` at `:616` | per-worktree git config, not env (§5.4); `report_pr_opened` verifies the PR (§5.6) |

**What revision 3 changed.** The second review found six blockers in revision 2. All six confirmed; two were worse than reported.

| # | Revision 2 said | Measured reality | Now |
|---|---|---|---|
| 1 | registration "validates" the claimed slot, so the token is bound honestly | `_slot_matches_registration` (`:294-305`) checks **only** provider + `repo_id`, and all three Tizonia slots share the identical pair — the check cannot separate Leader from Specialist even in principle | token bound to the **tmux pane**, derived from the kernel, never from the request body (§3.3) |
| 2 | rotate the token on every registration; a stolen token dies in one heartbeat | `_ensure_registered` has **5** call sites including a 60s heartbeat thread; rotating the only valid hash invalidates a header a concurrent call already built | token is **stable for the session**; rotation only on explicit re-bind (§3.4) |
| 3 | read endpoints are untouched, so `GET /agent/inbox` needs no auth | that GET hardcodes `refresh_mcp_session=True` (`agent_mail.py:147`) and writes `last_seen_at`, `mailbox_status`, `receipt.read_at`, `last_inbox_checked_at` — all inputs to liveness and to `brief_unread` | it is a **write** endpoint; `member_id` derived from the token (§3.5) |
| 4 | handoff clears "both ack columns", keeps the nonce | `ack_received_at` is a **third** column and `_ack_satisfied` reads it against `dispatched_at`, which handoff does not change — a stale ack stays valid | clear **all three** ack fields plus `last_nudge_at` (§4.2) |
| 5 | one `github_app_installation_id`, one cached token | `TeamGithubScope.repo_owner` is per-scope; `tizonia` and `adrirubio` are different accounts → different installations. No setting defined the bot login | installation resolved **per repository**, cache keyed by installation (§5.3) |
| 6 | "the plan must pick one" for `GH_TOKEN` delivery | that is an unresolved design decision wearing a plan's clothes | decided here: **askpass + helper, no token in any pane env** (§5.4) |

Revision 3 also answers a question no review raised: applying §5.4's recipe to a `kind="primary"` workspace silently overwrites the human's git identity. Measured, and now refused (§5.7).

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

### 1.6 The same defect, one layer down (revision 3)

Revision 2 proposed capability tokens and then bound them to whatever `team_slot_id` the caller sent, on the grounds that registration validates it. Measured, that validation has no discriminating power for this question:

```python
# agent_mail_service.py:294-305 — the whole check
def _slot_matches_registration(self, slot, request) -> bool:
    if request.provider != slot.provider:
        return False
    return derive_repo_identity(request.cwd)["repo_id"] == slot.repo_id
```

Live DB, all six slots:

| preset | slots | provider | repo_id | separable? |
|---|---|---|---|---|
| 2 (Tizonia) | Leader (4), Generalist (5), Specialist (6) | all `codex-cli` | all `4532704bf856d362` | **no** |
| 1 | Architect (1), Lead Dev (2), Reviewer (3) | 3 different | all `6aab3a28565c31b2` | only by provider |

A team is *by construction* a set of slots on one repo. So `provider + repo_id` can never distinguish the leader from the owner in the case that matters. An owner could register with `team_slot_id: 4` and be handed a leader-bound token.

The lesson is the one this project keeps relearning: **a check's name tells you it validates; only the data tells you whether it separates the cases you care about.** Revision 2 read the function, saw validation, and did not ask what it validated *against*.

The one signal that behaves as revision 1 hoped, and still does: `_brief_delivered` (`:806-824`) verifies an owner-side claim against `MailReceipt.read_at`, and `brief_message_id` (`app/database.py:439-440`) is precedent for storing a mail message id on a work item. The shape of the fix survives; only its trust basis had to be built.

---

## 2. Architecture

Three PRs. Each is independently reviewable and leaves the system in a coherent state.

```
PR0  Agent Mail capability tokens               (auth; no dispatch logic)
     registration returns a token bound to the caller's tmux pane;
     identity-bearing writes require it and derive the actor
     server-side. Ships disabled; the operator enables it.

PR1  Approval attribution + a real gate         (pure code, testable offline)
     1. link ack requests to work items with a per-dispatch nonce
     2. record who approved; require the designated leader; reject replay
     3. make auto-merge require a valid distinct approval
     4. surface the new fields in the work-item response

PR2  Distinct commit/PR identity                (needs a GitHub App)
     one bot as PR author, per-slot commit identity via per-worktree
     git config, tokens via a credential-helper callback that no pane
     ever holds, and verification that the reported PR is what it claims
```

**Why PR0 is separate and first.** PR1's entire value is that its evidence cannot be fabricated. Shipping PR1 without PR0 produces a gate that logs an approver id an agent chose for itself — worse than no gate, because it reads as enforcement. PR0 is also a strictly larger blast radius (every mail write path, the shim, the UI, ~13 test call sites), and a reviewer must be able to reject the auth change without rejecting the dispatch change. PR0 additionally closes the separately-tracked `/dispatch-status` auth gap, which is the same defect one router over.

**PR0 ships inert and is switched on by hand.** A pre-upgrade shim cannot learn to send a header it has never heard of, so enforcement is behind `mail_capability_tokens_required`, default `False` (§3.4). Deploying PR0 changes no behavior. The operator restarts the agent panes, confirms every live session has a token, then flips the flag. PR1's gate refuses to merge anything while the flag is `False` (§4.5), so the inert state is safe rather than silently degraded.

**Why PR2 is last.** Its failure mode is a *deadlocked* merge, not a *bad* merge. If PR2 slips, autonomy is strictly safer than today rather than blocked on provisioning.

---

## 3. PR0 — Agent Mail capability tokens

### 3.1 The precedent to follow

`mail_external_actors` already solves this problem for external orchestrators: a bearer token, sha256-hashed at rest, compared with `hmac.compare_digest`, resolved into an identity by a FastAPI dependency (`external_agent_mail.py:45-55`, `external_agent_mail_service.py:57-121`). PR0 applies the same pattern to *sessions* instead of *actors*. No new concepts, no new libraries.

### 3.2 Schema

`mail_agent_sessions` gains three nullable columns via the migration ladder. The `session_columns` set already exists for this table at `app/database.py:353`, so the new rungs go directly after the existing `team_slot_id` rung at `:358`:

```python
if session_columns and "capability_token_hash" not in session_columns:
    await conn.execute(text("ALTER TABLE mail_agent_sessions ADD COLUMN capability_token_hash TEXT"))
if session_columns and "bound_pane_pid" not in session_columns:
    await conn.execute(text("ALTER TABLE mail_agent_sessions ADD COLUMN bound_pane_pid INTEGER"))
if session_columns and "bound_pane_proc_start" not in session_columns:
    await conn.execute(text("ALTER TABLE mail_agent_sessions ADD COLUMN bound_pane_proc_start TEXT"))
```

All nullable, so existing rows migrate silently. `bound_pane_proc_start` pairs with the pid for the same reason `github_workspaces.leased_owner_proc_start` does (`app/models/database.py:309`, read by `_owner_process_is_alive` at `github_workspace_service.py:83`): a pid alone is reused by the kernel, a pid plus its start time is not.

`session_key` is **not** usable as the token: it is returned in `MailSessionResponse.session_key` (`schemas.py:1817`) from the unauthenticated `GET /agent-mail/team`, so every agent can already read every other agent's session key. The token must be a separate secret that is never echoed in any response body except the one that mints it.

### 3.3 Binding: derived from the kernel, never from the body

Revision 2 bound the token to the claimed `team_slot_id`. §1.6 shows why that fails. The binding must come from something the caller does not author.

**What Deck can establish without trusting the caller.** Measured on this host:

```
$ python3 peercred_test.py
client real pid   : 4086564
claimed in body   : 99999          <- the client lied
server derived    : 4086564 (ok)   <- from /proc/net/tcp inode -> /proc/*/fd
MATCH real pid?   : True
```

The server resolves the peer's pid from the loopback connection itself: the client's source port gives an inode in `/proc/net/tcp`, and that inode is owned by exactly one process's fd. The body's `pid` field becomes irrelevant.

**From the peer pid to a slot.** Measured on the three live Codex shims:

```
149263 (codex) -> ppid 149190 (MainThread) -> ppid 149167 (tmux: server)
159024 (codex) -> ppid 159009 (MainThread) -> ppid 149167 (tmux: server)
379563 (codex) -> ppid 379552 (MainThread) -> ppid 149167 (tmux: server)

$ tmux list-panes -a -F "#{pane_id} #{pane_pid}"
%2 149190   %3 159009   %4 379552
```

Every shim's parent **is** a tmux pane pid. So the chain is: peer pid → walk `ppid` until it hits a pid in tmux's pane list → that pane. `_resolve_pane_pid` (`github_dispatch_service.py:181-200`) already does the tmux half of this, and `_pid_is_descendant` (`agent_mail_service.py:477`) already walks ppids with a depth cap of 8.

**From the pane to a slot — the gap PR0 must fill.** `AgentTeamLaunchItem` (`database.py`) persists `tmux_target` but **no pane pid**, so today there is no durable record of which pane Deck spawned for which slot. PR0 adds one column:

```python
if launch_item_columns and "pane_pid" not in launch_item_columns:
    await conn.execute(text("ALTER TABLE agent_team_launch_items ADD COLUMN pane_pid INTEGER"))
```

`_execute_plan_item` already computes it on both paths — `spawned.get("pid")` at `agent_team_service.py:637` and `plan_item.matching_session.get("pid")` at `:569` — and puts it in the response object. It just is not stored. Persisting it makes spawn and reuse identical for binding purposes, which is exactly why this option was chosen over a spawn-time secret: **there is no `:575` problem here**, because the reuse path records a pane pid too.

**Registration then binds:**

1. Derive the peer pid from the connection. If it cannot be derived, refuse — `bind_unverifiable`.
2. Walk to the owning tmux pane pid. If no ancestor is a pane, this is not a tmux-hosted agent: mint a token with **no slot binding** (`team_slot_id` stays `NULL`). Such a session can send mail as a repo member; it can never be an approver.
3. Look up the launch item whose `pane_pid` matches. That launch item's `slot_id` is the slot. A `team_slot_id` in the body that disagrees is a `403` — derive, do not compare (§3.6).
4. Record `bound_pane_pid` and `bound_pane_proc_start`.

**Residual risk, stated plainly.** All panes run as one user with no `hidepid`, so any pane can read `/proc/<other>/environ` and `/proc/<other>/stat` — measured: 123 environment entries readable from another pane, including `CLAUDE_DECK_TEAM_SLOT_ID`. A pane that wanted to impersonate another slot could therefore *read* the target's secrets. It still cannot **use** them for registration, because binding is derived from its own connection, not from anything it can present. What it cannot do is make the kernel say its socket belongs to a different process.

This is the honest limit: pane binding defeats *claiming* another slot, not *co-resident compromise*. Defeating co-residency needs OS isolation (separate users, `hidepid=2`) and is out of scope. §8 records it as accepted.

### 3.4 Minting: stable for the session

Revision 2 rotated the token on every registration. That is a race. `_ensure_registered` (`agent_mail_server.py:139`) is called from **five** places — `_guard` before every tool call (`:202`), `deck_report_dispatch_status` (`:618`), `deck_list_work_items` (`:640`), `deck_retry_work_item` (`:686`), and the 60-second heartbeat thread (`:165`). Its `threading.Lock` serializes the shim's own calls but not the round trip: the heartbeat can rotate the stored hash after a concurrent tool call has already built its header, and that call then fails `401` for no reason the agent can act on.

So: **mint once per session row, on first registration.** Re-registration for an already-bound session returns the *same* token if the pane binding still matches, and rotates **only** when the binding changes (`bound_pane_pid` or `bound_pane_proc_start` differs) — which means a genuinely new process, where the old token should die.

This also removes the need for a grace window or current-plus-previous hashes. There is no rotation to be caught mid-flight.

**Deployment.** A pre-upgrade shim cannot self-heal: its loaded code has no idea the header exists, so it will never send one, no matter how many times it heartbeats. Revision 2's claim that this "self-heals without operator action" was wrong. PR0 therefore requires a **grace mode**:

- `mail_capability_tokens_required: bool = False` in `config.py`.
- With it `False` (the default PR0 ships), a request with no token falls back to today's caller-supplied behavior and the response logs `capability_token_missing` once per session. Nothing breaks on deploy.
- The operator restarts the agent panes at their convenience, confirms every live MCP session has a `capability_token_hash`, then flips it `True`.
- PR1's merge gate requires `True`. §4.5 states this as a precondition, and the gate refuses (`tokens_not_enforced`) when it is `False` — a gate whose evidence is optional is not a gate.

Live blast radius: 150 `source='mcp'` session rows, of which 7 are `connected` with a recent `last_seen_at`. Restarting agent panes is a normal operation here, but it is the operator's to schedule — and it is one more reason autonomy stays off until this lands.

### 3.5 Enforcement

A dependency mirroring `external_actor`:

```python
async def mail_session(
    request: Request,
    x_deck_session_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> MailAgentSession:
    """Resolve the calling session from its capability token, or 401."""
```

Applied to the endpoints whose semantics depend on *who is calling*:

| Endpoint | Enforcement |
|---|---|
| `POST /agent-mail/messages` | sender derived from the token's session member |
| `POST /agent-mail/messages/{id}/ack` | acking member derived from the token |
| `POST /agent-mail/messages/{id}/read` | reading member derived from the token |
| `POST /agent-teams/dispatch-status` | `reporting_slot_id` derived from the token |
| `GET /agent-mail/agent/inbox` | `member_id` derived from the token — see below |

**`GET /agent/inbox` is a write endpoint.** Revision 2 listed it as untouched. It is not read-only:

```python
# agent_mail.py:133-149 — member_id is a QUERY PARAM, refresh is hardcoded
async def agent_inbox(member_id: int, unread_only: bool = False, mark_read: bool = False, ...):
    return await agent_mail_service.get_inbox(..., refresh_mcp_session=True)
```

`refresh_mcp_session=True` is not optional at the route. It calls `heartbeat_member_mcp_session` (`:332-348`), which writes `last_seen_at` and forces `mailbox_status = "connected"`. With `mark_read=true` it also writes `receipt.read_at` and `member.last_inbox_checked_at`.

Those are not bookkeeping fields. They are the inputs to two safety decisions:

| Field written | Read by | Consequence of forging it |
|---|---|---|
| `last_seen_at`, `mailbox_status` | `_effective_status` (`:648-663`) | a dead agent reads as `connected`; the G2 ambiguity gate sees a live owner |
| `receipt.read_at` | `_brief_delivered` (`:806-824`) | the `brief_unread` escalation (`github_dispatch_service.py:776`) never fires |

So `curl "/agent/inbox?member_id=16&mark_read=true"` forges the leader's liveness *and* silences a dispatch escalation, with no token and no authentication. This is the failure mode my own [[invariant-evidence-freshness]] rule names: a safety rule is only as good as the freshness of what it reads, and here an unauthenticated caller controls the freshness.

`member_id` therefore comes from the token. The parameter is removed from the agent route, not merely validated — an unused query parameter is a trap for the next reader.

**The operator UI keeps a read path.** The Deck frontend also needs inbox contents for members it is not. That is the *existing* `GET /agent-mail/members/{id}/...` surface used by the UI, which stays as it is; only the `/agent/` route (the shim's route) gets the token. Confidentiality of reads across members remains out of scope (§6).

**Derive, do not compare.** The server sets `sender_member_id` from the token's session. A caller-supplied `sender_member_id` that disagrees is a `403`, not a silent overwrite: silent overwriting would mask a misconfigured shim as success. A caller-supplied value that *agrees* is accepted, which keeps the shim's current payload shape valid.

### 3.6 The operator path stays open

The Agent Mail UI writes as an operator-chosen member (`ThreadDialog.tsx:159` sends `sender_member_id: senderId`) and holds no session token. Two write paths therefore need a non-session identity: the UI's reply/compose, and its ack.

Rather than invent a third auth scheme, the UI authenticates as an **external actor** — the mechanism that already exists for exactly this, is loopback-gated at creation (`external_agent_mail.py:76-78`), and lands in `sender_actor_id` rather than `sender_member_id`, so operator-authored messages are *distinguishable from* agent-authored ones in the data.

This has a consequence PR1 depends on and §4.3 states explicitly: an operator-authored message has `sender_member_id = NULL`, so it can never be mistaken for the leader's approval. A human who wants to approve does it by merging, not by typing into the mail UI.

**Provisioning, which revision 2 left undefined.** No new mechanism is needed. `create_actor` (`external_agent_mail_service.py`) **upserts by `actor_key`** and rotates the token on repeat calls, and the route is loopback-gated (`external_agent_mail.py:78`). So:

- On first use of a mail write, the frontend `POST`s `/external-agent-mail/actors` with a fixed `actor_key: "deck-ui"` and stores the returned token in `sessionStorage`.
- `sessionStorage`, not `localStorage`: the token dies with the tab. A rotation on the next page load is free, because the upsert is idempotent by key.
- On `401` the frontend re-provisions once and retries. No operator step, no settings page, no token to copy.
- The ack path uses the actor ack endpoint that already exists (`external_agent_mail.py:218`), so no new route is needed for §3.6's second write path.

**Remotely hosted Deck.** The loopback gate means this self-provisioning only works when the browser and the backend share a host — the normal case, and the only case Deck currently supports (CORS is pinned to `localhost:5173`). If Deck is ever served remotely, the frontend cannot mint its own actor and an operator must provision one out of band. That is a real limitation and it is recorded in §8 rather than solved here: solving it means real user authentication for Deck, which is a project, not a section of this spec.

### 3.7 Tests

With `mail_capability_tokens_required = True` unless a test says otherwise.

1. Registration returns a token; the hash is stored and the plaintext is not.
2. `POST /messages` without a token ⇒ `401`.
3. With a valid token ⇒ `sender_member_id` equals the token's session member, even when the body omits it.
4. With a valid token and a *conflicting* `sender_member_id` ⇒ `403`.
5. The forgery from §1.5 — posting an `answer` claiming to be another member — ⇒ `403`. Written directly from the live self-ack shape.
6. An external actor's token can still send, and lands in `sender_actor_id` with `sender_member_id = NULL`.
7. `POST /dispatch-status` derives `reporting_slot_id` from the token; a body claiming a different slot ⇒ `403`.

Binding (§3.3), with the peer-pid resolver injected so tests do not need real sockets:

8. **The §1.6 forgery.** Registration from a pane bound to slot 6 (Specialist) that claims `team_slot_id: 4` (Leader) ⇒ `403`, and no token is minted. This is the blocker-1 test; it must fail if binding falls back to the body.
9. A peer pid that resolves to no tmux pane ⇒ token minted with `team_slot_id = NULL`, and that session's `answer` is rejected as approval evidence by PR1 (`not_leader`).
10. A peer pid that cannot be derived at all ⇒ `bind_unverifiable`, refuse. Fail closed on inability to observe.
11. A pane pid matching a launch item for slot 6 ⇒ session bound to slot 6 even when the body sends no `team_slot_id`.
12. Pane pid reuse: same `bound_pane_pid`, different `bound_pane_proc_start` ⇒ treated as a new process, token rotated, old token `401`.

Stability (§3.4):

13. Two consecutive registrations from the same live pane return the **same** token, and the first token still authenticates after the second call. This is the blocker-2 test.
14. Interleaved order — build a header, re-register, then use the header — succeeds. Written to fail against revision 2's rotate-always design.

Grace mode (§3.4):

15. With `mail_capability_tokens_required = False`, a tokenless `POST /messages` succeeds with the body's `sender_member_id` (today's behavior), and logs `capability_token_missing`.
16. With it `False`, PR1's merge gate still refuses with `tokens_not_enforced`. A gate whose evidence is optional is not a gate.

Inbox (§3.5):

17. `GET /agent/inbox` without a token ⇒ `401`.
18. The forged-liveness attack: a tokenless `GET /agent/inbox?member_id=<leader>&mark_read=true` ⇒ `401`, and the leader's `last_seen_at`, `mailbox_status`, and the brief's `receipt.read_at` are all **unchanged**. Asserting the refusal alone would pass even if the route wrote first and refused after.
19. With a valid token, the inbox returned is the token's member's, and a `member_id` query parameter is either absent from the signature or ignored — assert on the returned member, not on the status code.

**Mutation requirement.**

| Mutant | Test that must fail |
|---|---|
| dependency present but return value unused (body value still trusted) | 3, 5 |
| conflicting sender silently overwritten instead of rejected | 4 |
| binding falls back to `request.team_slot_id` when pane lookup misses | **8** |
| `bind_unverifiable` treated as "no binding" instead of a refusal | 10 |
| token rotated on every registration (revision 2's design) | **13, 14** |
| `proc_start` ignored, pid compared alone | 12 |
| inbox route authenticates but still honours the query `member_id` | 19 |
| inbox mutations applied before the auth check | **18** |
| token compared with `==` instead of `hmac.compare_digest` | — (not observable by test; enforce in review) |
| rotation leaves the old hash valid | 6 |

The third row is deliberate. A timing-safe comparison is not test-observable, so listing it as a review item is honest; claiming a test covers it would not be.

### 3.8 Blast radius, stated plainly

- `backend/mcp_shim/agent_mail_server.py` — store the token in `_state` at registration, send it as a header in `_request`/`_dispatch_request`. The shim already does exactly this for the Agent Bridge terminal token (`_bridge_request_with_token`, `:117-132`), so the pattern is in-file. Note the token is stored **once** and not replaced on later registrations (§3.4).
- `backend/app/services/agent_team_service.py` — persist `pane_pid` on launch items, both paths (`:569`, `:637`).
- `frontend/src/features/agent-mail/api.ts` — three write calls gain actor auth, plus the `sessionStorage` provisioning helper (§3.6).
- ~13 test call sites hitting `agent-mail/messages` across 5 test files.
- **Operator action required at deploy:** restart agent panes, then flip `mail_capability_tokens_required` to `True` (§3.4). Live: 150 `mcp` session rows, 7 currently connected.

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
| retry | `reset_for_retry:64-71` | clear nonce + the two new ack columns alongside the existing `ack_received_at = None` |
| handoff accepted | `accept_handoff:705` | clear **all three** ack fields + `last_nudge_at`; **keep the nonce** — see below |

The nonce is a *correlation* value, not a secret — PR0 provides the authentication. It exists so that evidence from attempt N cannot satisfy attempt N+1, which no amount of authentication would prevent on its own.

**Handoff clears three fields, not two.** Revision 2 said "both ack columns," meaning the two new ones. That was an off-by-one with a consequence. `ack_received_at` already exists and `_ack_satisfied` reads it (`:905-911`):

```python
if item.ack_received_at is None:
    return False
if item.dispatched_at is not None and item.ack_received_at < item.dispatched_at:
    return False
return True
```

`accept_handoff` (`:697-710`) sets `owner_slot_id`, `handoff_state`, `handoff_target_slot_id`, `routing_method`, `updated_at` — and crucially **not** `dispatched_at`. So the staleness comparison still passes, `_ack_satisfied` returns `True` for the *new* owner on the *previous* owner's ack, and the monitor's ack branch (`:778-791`) is skipped: no nudge, no `leader_ack_timeout`, ever. The new owner is treated as pre-approved and the leader is never asked.

So `accept_handoff` clears:

| Field | Why |
|---|---|
| `ack_received_at` | otherwise `_ack_satisfied` is `True` on inherited evidence |
| `ack_approver_member_id` | the previous owner's approver did not approve this owner |
| `ack_evidence_message_id` | ditto — and PR1's gate reads it |
| `last_nudge_at` | `record_ack_received:685` nulls it on ack; leaving a stale value shifts the new owner's first nudge by up to one full grace period, or skips it (`:785` tests `is None`) |

`dispatched_at` is deliberately **not** reset: it anchors the ack deadline, and re-anchoring it on handoff would silently extend the timeout every time an item changes hands. The new owner inherits the original deadline, which is the existing behavior for every other field and is #280's territory, not this spec's.

**Why handoff keeps the nonce.** Clearing it would deadlock the item. `accept_handoff` sends **no new brief**, so the new owner never learns a replacement nonce, and every subsequent ack attempt would refuse with `no_linkage` forever. Clearing the *ack* fields is what matters: the new owner must obtain their own approval, and §4.3 rule 3 requires the `context_request` to have been sent **by the current owner member**, so the previous owner's request cannot satisfy the new one even though the nonce is unchanged. Retry is different — it re-dispatches through `:344`, which mints a fresh nonce, so clearing is both safe and necessary there.

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
    mail_capability_tokens_required is True   <-- NEW (§3.4)
    ack_approver_member_id is the leader      <-- NEW
    and differs from the owner's member
```

The check reads the **persisted** columns, not a fresh mail lookup: PR0 plus §4.3 mean the columns can only have been written by a verified approval, and re-deriving at merge time would read a mail table that may have changed for unrelated reasons.

**Why the settings check belongs in the gate.** PR0 ships with `mail_capability_tokens_required = False` so deploying it breaks nothing (§3.4). But in that mode a tokenless caller still supplies its own `sender_member_id`, so `ack_approver_member_id` is exactly as forgeable as it was before PR0. A gate reading a forgeable column is the failure this spec exists to prevent, so the gate refuses with `tokens_not_enforced` until the operator has restarted the panes and flipped the flag. The refusal names the setting, so the operator sees a configuration step rather than a mystery.

This is the one place the three PRs are coupled at runtime rather than only in sequence, and it is deliberate: it makes "PR0 deployed but not enforced" a *safe* state instead of a silently-degraded one.

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
11. `accept_handoff` clears all three ack fields and **keeps** the nonce; the previous owner's approval does not carry to the new owner, *and* the new owner can still be acked (proving the §4.2 deadlock is avoided).
    11b. **`_ack_satisfied` is False for the new owner after a handoff.** This is blocker 4 and it needs its own assertion, because test 11 as written in revision 2 would pass while leaving `ack_received_at` set: set `dispatched_at` in the past, record an ack, hand off, then assert `_ack_satisfied(item) is False`. Against revision 2's two-column clear this fails, since `ack_received_at > dispatched_at` still holds.
    11c. After a handoff, the monitor nudges the leader for the new owner's ack and eventually escalates `leader_ack_timeout`. This is the *consequence* of 11b — the behavior an operator would actually miss — and it is why `last_nudge_at` is cleared too (`:785` branches on `is None`).
12. Auto-merge with CI-green + fresh head but no distinct approval ⇒ falls back to human merge, `auto_merged_at` stays NULL.
13. Auto-merge with CI-green + fresh head + valid distinct approval ⇒ merges.
    13b. Same item, but `mail_capability_tokens_required = False` ⇒ refuses with `tokens_not_enforced` (§4.5).
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
| clear only the two new columns, leaving `ack_received_at` (revision 2's bug) | **11b, 11c** |
| also clear the nonce in `accept_handoff` (deadlocks the new owner) | 11 |
| reset `dispatched_at` on handoff (silently extends every timeout) | 11c |
| drop the `mail_capability_tokens_required` condition from the gate | 13b |
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
2. Install it on the target repos (`adrirubio/claude-deck`, the tizonia sandbox). No installation id to record — §5.3 resolves it per repository.
3. Note the App slug; the bot login is `<slug>[bot]`. That value goes in `github_app_bot_login`.
4. Store the App id and private key in `backend/.env`, which stays **0600 and gitignored**. The key is never logged, never echoed, never committed, never sent to a pane.

### 5.3 Token lifecycle

Revision 1 covered this in one sentence. It is a subsystem, and it needs to be specified.

**Settings** (`config.py`, alongside the existing `github_token: str = ""` at `:39`):

```python
github_app_id: str = ""
github_app_private_key_path: str = ""     # a path, not the key — keeps the key out of process env
github_app_bot_login: str = ""            # e.g. "claude-deck-agent[bot]" — §5.6 needs it
github_app_token_refresh_margin_seconds: int = 300
```

Empty values mean "App auth not configured," and the system falls back to today's `github_token` behavior. No configuration change is forced on anyone by this PR landing.

**No `github_app_installation_id` setting.** Revision 2 had one, and it was wrong. `TeamGithubScope.repo_owner` is per-scope (`app/models/database.py:215`) and nothing constrains a preset's scopes to one account. The two target repos are `tizonia/tizonia-openmax-il` (the live scope) and `adrirubio/claude-deck` — **different accounts, therefore different installations**. A single id cannot serve both, and pairing one id with "repository-scoped minting" was incoherent: it promised a per-repo scope from an installation that may not contain the repo.

Installation is instead **resolved per repository** and cached:

```python
GET /repos/{owner}/{repo}/installation   ->  installation id     (App JWT auth)
POST /app/installations/{id}/access_tokens  ->  token            (App JWT auth)
```

The first call is the App-level endpoint for exactly this question, so no configuration is needed and no assumption about account layout is baked in. A repo the App is not installed on returns `404`, which becomes a clear `app_not_installed` refusal naming the repo — not a confusing auth error at push time.

**`github_app_bot_login` is a setting, not a discovery.** §5.6's author check needs the login. It is discoverable (`GET /app` returns the App slug, and the bot login is `<slug>[bot]`), but deriving it means one more call whose failure mode is "skip the check" — and a security check that disables itself on a network error is not a check. A setting fails loudly when wrong: the first PR report refuses with the mismatch in the message. When it is empty, the author check is skipped, which is the same explicit fallback as the rest of §5.3.

**Dependencies.** App auth needs a JWT signed with RS256, which needs `pyjwt` and `cryptography`. Both are importable in the current venv (2.13.0 / 49.0.0) but **neither is in `requirements.txt`** — PyJWT is a transitive dependency of `mcp`. Relying on that is a latent break: a legitimate `mcp` release could drop it. Both must be added as explicit direct dependencies, with the extra spelled `pyjwt[crypto]`.

**Minting.** Standard two-step: sign a short-lived JWT with the App private key, exchange it at `POST /app/installations/{id}/access_tokens` for an installation token (~1h TTL). GitHub returns `expires_at`; store it.

**Caching, keyed properly.** Revision 2 said "one cached token," which contradicts per-repo installations. The cache is a dict keyed by `(installation_id, repo_full_name)` — installation because that is what the token belongs to, repo because the `repositories` narrowing below makes two tokens from one installation non-interchangeable. Each entry holds the token and its `expires_at`, and is refreshed when `expires_at - now < refresh_margin`.

Locking: **one `asyncio.Lock` per cache key**, not one global lock. A global lock would serialize dispatches across unrelated repos behind a single network round trip; a per-key lock still prevents the thundering herd that matters (concurrent dispatches on the same repo). Installation-id lookups are cached the same way, keyed by repo.

Not persisted — a backend restart mints fresh tokens, which is cheap and avoids storing live credentials at rest.

**Scoping.** Installation tokens are otherwise scoped to *every* repository in the installation. The optional `repositories` parameter narrows to one; use it, keyed on the scope's repo, so a token minted for one scope cannot write to another. This is what makes the per-repo cache key load-bearing rather than decorative.

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
git -C <workspace> config --worktree credential.https://github.com.useHttpPath true
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

**`useHttpPath` is required, and revision 2 missed it.** By default git tells a helper only the protocol and host:

```
IN: protocol=https
IN: host=github.com          <- no repo. The helper cannot scope anything.
```

With `credential.https://github.com.useHttpPath true` (git 2.43.0, measured):

```
IN: protocol=https
IN: host=github.com
IN: path=someowner/somerepo.git      <- now it can
```

Without this, the helper cannot tell which repository a push is for, so "repository authorization" is unimplementable and §5.3's per-repo token scoping has nothing to key on. The helper refuses when `path` is absent rather than guessing — a helper that guesses a repo would mint a token for the wrong one.

### 5.5 The helper endpoint, decided

Revision 2 ended with "the plan must pick one." That is a design decision, not a plan step, so it is decided here.

**No pane ever holds a token.** `GH_TOKEN` is not set in any pane, on either the spawn or the reuse path. This removes the `:575` problem by removing the thing that needed delivering, rather than by finding a second delivery channel — and it removes the one place revision 2 still exposed a live credential.

`gh` is then made to use the same helper, which it does natively:

```
git -C <workspace> config --worktree credential.https://github.com.helper "<deck helper>"
# gh reads git's credential helper when GH_TOKEN is unset
```

Measured earlier: `gh auth git-credential get` is itself just a credential helper, so `gh` and git already speak one protocol. Pointing both at Deck's helper is strictly simpler than delivering a token twice.

**Endpoint.** `POST /api/v1/agent-teams/git-credential` on the existing loopback-only backend:

| Aspect | Decision |
|---|---|
| Request | `{workspace_token, protocol, host, path}` — the last three passed straight through from git's stdin |
| Auth | `workspace_token` = the workspace's existing `lease_token` (`github_workspaces.lease_token`, `github_workspace_service.py:130`). No new secret: the lease already identifies one dispatch's exclusive hold on one checkout, which is exactly the authorization question. |
| Authorization | the lease's `scope` must own `path`. A helper asking for a repo the lease does not cover is a `403`, logged with both repos. |
| Response | `{username: "x-access-token", password: <installation token>}`, minted per §5.3 for that repo only |
| Refusals | lease released or expired ⇒ `403`; `path` absent ⇒ `400`; App not configured ⇒ `501` and git falls back to the ambient credential, preserving today's behavior |

The helper is installed **into the workspace config, not the pane**, so it applies identically to spawn and reuse — the whole point of §5.4. The `lease_token` reaches the helper through the config line itself (`--worktree --add ... "deck-credential-helper --lease <token>"`), which lives in `.git/worktrees/<name>/config.worktree`: outside the working tree, uncommittable, and already proven not to leak into `git status`.

**When it is applied, and re-applied.** Identity is a function of the *current* owner, so it is written at lease time and rewritten whenever the owner changes:

| Event | Action |
|---|---|
| workspace leased for a dispatch | write identity + helper config for the owner slot |
| `accept_handoff` | rewrite identity for the new owner slot — §4.2 already clears ack state here; this is the same event |
| workspace released | remove the helper line and the identity, so an unleased checkout has no agent identity and no path to a token |

Handoff is the case revision 2 had no answer for. Without the rewrite, commits made after a handoff carry the *previous* owner's identity — attribution that is wrong in exactly the way this spec exists to fix.

### 5.6 Verify the PR, do not trust the report

`report_pr_opened` (`github_verification_service.py:44-86`) makes **no** GitHub call. It accepts `pr_number` and records it. So an agent can report any number — including a PR in another repo, or someone else's — and Deck will thereafter verify CI and potentially auto-merge *that* PR.

With auto-merge enabled, this is the shortest path from a wrong report to a merged stranger's code. It gains a verification step via the existing `client.get_pull`:

| Check | Refuse if |
|---|---|
| repository | `head.repo.full_name` != the scope's `owner/repo` |
| author | `user.login` != the configured bot login (when App auth is configured) |
| head branch | `head.ref` does not match the expected `deck/<slot>/issue-<n>` pattern for this item |

A refusal is a `409` and leaves `pr_number` unset, so the item stays dispatched and the existing monitor handles it. When App auth is not configured, the author check is skipped rather than failing every report — otherwise this PR would break the current working flow for anyone who has not provisioned an App.

`report_pr_opened` currently takes no `client` parameter and never touches the network; adding one changes its signature and every existing test that calls it. The plan must name that.

### 5.7 A primary workspace is never given an agent identity

No review raised this. I found it by running §5.4's recipe against a primary checkout instead of a worktree:

```
$ git config extensions.worktreeConfig true
$ git config --worktree user.name "Specialist (Deck agent)"
$ git config --get user.name
Specialist (Deck agent)          <- the HUMAN's checkout, silently reassigned
$ git -C ../other-worktree config --get user.name
Human Juan                       <- and every other worktree still looks correct
```

The human's identity is overwritten in `.git/config.worktree`, and because per-worktree config is *isolated*, no other worktree shows any symptom. The operator would discover it in `git log` after committing, under the wrong name.

This is not hypothetical. Live DB workspace 1 is `kind='primary'` at `/home/juan/work/repos/tizonia/tizonia-openmax-il` — the actual human checkout. It is `dispatchable=0` today, which is the only reason §5.4 is not already dangerous. But `register_workspace` accepts `kind="primary", dispatchable=True` (`github_workspace_service.py:361`, `:382`) and the lease query filters on `dispatchable` alone (`:117`), so a single flag change would hand a dispatched agent the human's checkout and rewrite their git identity in it.

**Decision: refuse.** When a lease resolves to a `kind == "primary"` workspace, the dispatch refuses rather than writing identity:

- No identity config, no credential helper, no `GH_TOKEN` — the human's checkout is never modified by PR2, at all.
- The refusal is a `pending_reason` on the item naming the workspace, consistent with the existing fail-closed rule from G2/G3: when Deck cannot act safely, it declines and reports rather than proceeding.
- **No new `dispatch_status` value.** This is a `pending_reason`, following `queued_ambiguous_sessions`.

Primary workspaces therefore become undispatchable *for identity purposes* under PR2. That is the intended trade: `kind="primary"` exists so Deck can observe and lease a human's checkout, and `release_blocker` already treats it as a special case it must not reset (`:200`, `:231`). Treating it as somewhere an agent may assume an identity was always the wrong reading of that column.

### 5.8 Tests

1. Workspace provisioning sets all five per-worktree config values; a second worktree in the same repo is unaffected.
2. The URL-scoped helper wins over an ambient `credential.https://github.com.helper` — the exact case that failed when measured with the unscoped key.
3. A slot whose display name contains spaces and punctuation is slugified into a valid email local-part (lowercase, `[a-z0-9.-]`, collapsed runs). This is a **correctness** requirement, not a security one: `_env_flags` (`agent_bridge/spawn.py:38-44`) validates variable *names* against `[A-Z_][A-Z0-9_]*` and raises on a bad one, but does not validate values — and `subprocess.run` is called with an argv list and no `shell=True` (`:79-84`), so no shell ever interprets a value. Measured: `{'GIT_AUTHOR_NAME': 'Bad; rm -rf / $(whoami)'}` passes through untouched and harmlessly. The plan must not add shell-escaping theater; a malformed email pollutes `git log` and `Co-authored-by` trailers, and that is the real defect.
4. The token cache refreshes inside the margin and reuses outside it; concurrent callers mint once (lock held).
5. The private key, the JWT, and the token appear in no log record and no brief.
6. `pyjwt[crypto]` and `cryptography` are declared in `requirements.txt`.
7. With App auth unconfigured, dispatch still works on the existing `github_token` path.
8. `report_pr_opened` refuses a PR in a different repo (`409`, `pr_number` unset).
9. `report_pr_opened` refuses a PR whose author is not the bot, when App auth is configured.
10. `report_pr_opened` refuses a PR whose head branch does not match the item's expected branch.
11. `report_pr_opened` skips the author check when App auth is unconfigured.
12. Brief contains the `[Slot]` prefix, the `deck/<slot>/issue-<n>` branch instruction, and both trailers.

Helper endpoint (§5.5):

13. `useHttpPath` is set, and the helper receives `path=` on stdin. Without it the helper gets only protocol and host — the measured default.
14. The helper refuses (`400`) when `path` is absent rather than guessing a repo.
15. A helper call with a valid `lease_token` for repo A asking for repo B ⇒ `403`, and the message names both repos.
16. A helper call with a released lease ⇒ `403`.
17. With App auth unconfigured the helper returns `501` and git falls back to the ambient credential — today's behavior, unbroken.
18. No pane environment contains a token: assert the `extra_env` dict passed to `spawn_session` has no `GH_TOKEN` and no `GITHUB_TOKEN` key.

Owner-change and primary (§5.5, §5.7):

19. `accept_handoff` rewrites the worktree identity to the new owner slot; a commit made after the handoff carries the new owner's name.
20. Release removes the helper line and the identity from the worktree config.
21. **A lease resolving to a `kind="primary"` workspace refuses**, sets a `pending_reason`, and leaves `.git/config.worktree` absent or unchanged in that checkout. Assert on the *file*, not only on the refusal: a route that writes first and refuses after would pass a status-code-only test.
22. No new `dispatch_status` value is introduced — assert the item's `dispatch_status` is one of the existing set.

**Mutation requirement.**

| Mutant | Test that must fail |
|---|---|
| `useHttpPath` omitted | 13, and 15 becomes unimplementable |
| helper authorizes on host alone, ignoring `path` | 15 |
| primary check applied after the config write | **21** |
| handoff leaves the previous owner's identity in place | 19 |
| `GH_TOKEN` reintroduced into `extra_env` "for convenience" | 18 |

### 5.9 Deployment (gated, manual, not part of the PR)

Restoring tizonia branch protection is the hard gate the soak log records. The backup exists at `/tmp/tizonia-master-protection-backup.json` (`required_approving_review_count: 1`, `enforce_admins: true`). **Copy it somewhere durable first** — `/tmp` is not a safe home for the only copy of a gate. Restore only after PR2 is deployed and a bot-authored PR has been observed to be approvable by `juanrubio`.

---

## 6. Explicitly out of scope

- **`route_item`'s fallback is unchanged.** Refusing to route to the leader strands work when no specialist matches; the enforced gate makes leader ownership *safe* rather than forbidden.
- **No ack timeout changes.** No softening, no tiering, no idle monitor — that is #280, and mixing it in risks the C1 invariant.
- **No new `dispatch_status` values.**
- **Autonomy stays off** (`autonomy_enabled = 0`, both presets). No PR here enables it, and none restores branch protection.
- **Confidentiality of mail reads.** PR0 authenticates identity-bearing *writes*, plus `GET /agent/inbox` because that endpoint mutates (§3.5). `GET /team` and `GET /messages` stay open; any agent can still read the roster and message list. That is a real gap and a separate decision.
- **Per-slot bot accounts** — considered, rejected in §5.1.
- **Co-resident pane compromise.** Every pane runs as one user with no `hidepid`, so any pane can read any other's `/proc/<pid>/environ` — measured, 123 entries including `CLAUDE_DECK_TEAM_SLOT_ID`. §3.3's binding defeats *claiming* another slot; it does not defeat a pane that reads another's memory or files. Closing this needs OS-level isolation (separate users, `hidepid=2`, or containers) and is a hosting decision, not a code change.
- **Remotely hosted Deck.** §3.6's UI self-provisioning depends on the loopback gate, so it only works when browser and backend share a host. That is the only configuration Deck supports today (CORS is pinned to `localhost:5173`). Serving Deck remotely needs real user authentication — a project of its own.
- **Primary-workspace dispatch under PR2.** §5.7 refuses rather than assigning an identity in a human's checkout. Making primary workspaces safely dispatchable would need a way to scope git identity to a process rather than a checkout, which git does not offer for commits an agent makes itself.

## 7. Deferred

- **Approval expiry.** An ack survives an arbitrary number of pushes after it was given; only auto-merge's head-freshness check bounds it. The nonce bounds it per *dispatch*, not per *push*. Re-approval after a force-push belongs with #280's head re-confirm item.
- **External human approvers.** Attribution assumes the approver is an Agent Mail member. A GitHub PR review by a human is stronger evidence and is not read at all.
- **Timing-safe token comparison as a tested property.** Enforced by review in PR0 (§3.7), not by a test.
- **Enforcing tokens by default.** PR0 ships with `mail_capability_tokens_required = False` because a running shim cannot learn a new header without a restart (§3.4). Flipping the default to `True` is a follow-up once no pre-upgrade shim can exist, and it should be a one-line change plus a release note.
- **Non-tmux agents.** §3.3 mints an unbound token when the caller has no tmux ancestor, so such a session can send mail but can never approve. Binding them needs a different channel (a launch-issued code, or OS credentials) and no such agent exists in this deployment today.

## 8. Success criteria

1. An agent cannot post a message as another member: the §1.5 forgery returns `403`.
   1b. An agent cannot obtain a token bound to a slot it does not occupy: the §1.6 forgery (a Specialist pane claiming `team_slot_id: 4`) returns `403`.
   1c. An unauthenticated caller cannot forge another member's liveness or silence a `brief_unread` escalation through `GET /agent/inbox`.
2. A self-ack cannot set `ack_received_at`, and the live shape (`context_request` 16→16 answered by 16) is refused by a regression test.
3. Only the designated leader member's own answer can approve — not any non-owner, and not a member with no slot.
4. Evidence from a previous dispatch attempt cannot approve the current one, across both retry and handoff.
5. Every recorded ack names its approver and the message that proves it, and all three columns are visible to operators and to `deck_list_work_items`.
6. Auto-merge cannot happen without a valid distinct approval, and failing that check falls back to human merge stickily, without escalating.
7. A bot-authored PR is approvable by `juanrubio`, so branch protection can be restored to `required_reviews=1, enforce_admins=true`.
8. Commits, PR titles, and branch names identify which agent produced them, on the reuse path as well as the spawn path.
9. A reported PR that is in the wrong repo, from the wrong author, or on an unexpected branch is refused.
10. No agent pane holds a GitHub credential **at all** — no `GH_TOKEN`, no `GITHUB_TOKEN` — and no log or brief contains the App private key.
11. Deploying PR0 changes no behavior until the operator enables enforcement, and PR1's gate refuses to merge while enforcement is off.
12. A human's primary checkout is never given an agent git identity.
13. Every new guard is shown to bite by mutation.
