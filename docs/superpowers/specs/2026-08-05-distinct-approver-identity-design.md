# Distinct Approver Identity — Design (Findings #1 and #6)

**Date:** 2026-08-05
**Status:** Design, revision 5 — revised after a fourth implementer review of `732e48d` found eight further blockers, all confirmed against source, live data, or measurement. **Not yet approved for implementation planning.**
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
| 5 | "the backend mints and refreshes tokens" | one sentence standing in for a subsystem; no settings, no JWT, no cache | full lifecycle, and a **credential-helper callback** so no token is placed in a pane's environment (§5.3) — revision 3's stronger phrasing here is retracted below |
| 6 | `extra_env` at spawn carries identity | the **reuse** path returns at `:575`, before `spawn_session` at `:616` | per-worktree git config, not env (§5.4); `report_pr_opened` verifies the PR (§5.6) |

**What revision 3 changed.** The second review found six blockers in revision 2. All six confirmed; two were worse than reported.

| # | Revision 2 said | Measured reality | Now |
|---|---|---|---|
| 1 | registration "validates" the claimed slot, so the token is bound honestly | `_slot_matches_registration` (`:295-305`) checks **only** provider + `repo_id`, and all three Tizonia slots share the identical pair — the check cannot separate Leader from Specialist even in principle | token bound to the **tmux pane**, derived from the kernel, never from the request body (§3.3) |
| 2 | rotate the token on every registration; a stolen token dies in one heartbeat | `_ensure_registered` has **5** call sites including a 60s heartbeat thread; rotating the only valid hash invalidates a header a concurrent call already built | token is **stable for the session**; rotation only on explicit re-bind (§3.4) |
| 3 | read endpoints are untouched, so `GET /agent/inbox` needs no auth | that GET hardcodes `refresh_mcp_session=True` (`agent_mail.py:147`) and writes `last_seen_at`, `mailbox_status`, `receipt.read_at`, `last_inbox_checked_at` — all inputs to liveness and to `brief_unread` | it is a **write** endpoint; `member_id` derived from the token (§3.5) |
| 4 | handoff clears "both ack columns", keeps the nonce | `ack_received_at` is a **third** column and `_ack_satisfied` reads it against `dispatched_at`, which handoff does not change — a stale ack stays valid | clear **all three** ack fields plus `last_nudge_at` (§4.2) — revision 4's `ack_enforcement_epoch` makes this **four**, and §4.2 states the current list |
| 5 | one `github_app_installation_id`, one cached token | `TeamGithubScope.repo_owner` is per-scope; `tizonia` and `adrirubio` are different accounts → different installations. No setting defined the bot login | installation resolved **per repository**, cache keyed by installation (§5.3) |
| 6 | "the plan must pick one" for `GH_TOKEN` delivery | that is an unresolved design decision wearing a plan's clothes | decided here: **askpass + helper, no token in any pane env** (§5.4) |

Revision 3 also answers a question no review raised: applying §5.4's recipe to a `kind="primary"` workspace silently overwrites the human's git identity. Measured, and now refused (§5.7).

**What revision 4 changed.** The third review found eight blockers in revision 3. All eight confirmed; two were worse than reported, and one invalidated a decision revision 3 had just made.

| # | Revision 3 said | Measured reality | Now |
|---|---|---|---|
| 1 | a leader-authored `answer` in the linked thread is approval | there is **no decision field** in `mail_messages` — 81 `answer` rows, all prose. Live rows 82 and 92 are the Leader **refusing** ("*not approved for implementation yet*", "*superseded… I am not treating this stub*") and both would have passed | approval is an explicit **decision**, not a reply: `deck_approve_work_item` writes a structured verdict the gate reads (§4.3a) |
| 2 | re-registration "returns the same token" | only the sha256 hash is stored, so the plaintext is unrecoverable by construction | the **shim** caches the plaintext and re-authenticates; the backend returns a token only when it mints one (§3.4) |
| 3 | pane pid → launch item → slot | launch rows are historical, carry no `proc_start`, and the only `db.commit()` is at `agent_team_service.py:530` — **after the entire slot loop**, so a shim can register before its own row exists | an **active** `(pane_pid, proc_start)` binding table written before spawn returns, plus a retryable `bind_pending` (§3.3) |
| 4 | `/proc/net/tcp` → peer pid | Linux-only, and an IPv4 connection appears **only** in `/proc/net/tcp` while IPv6 appears **only** in `/proc/net/tcp6` — reading one table silently fails half the cases | stated Linux-only platform contract; resolver reads **both** tables; non-Linux fails closed (§3.3) |
| 5 | grace mode is safe because the gate refuses while it is off | approver columns are still **written** while enforcement is off, so flipping the flag on retroactively legitimizes forged evidence | evidence carries an **enforcement epoch**; `record_ack_received` refuses entirely while enforcement is off (§3.4a) |
| 6 | UI provisions one `deck-ui` actor | `token_hash` is a single column and `create_actor` overwrites it, so two tabs invalidate each other in a loop. The URL was also wrong: the real prefix is `/api/v1/external/agent-mail` | per-tab random `actor_key`, correct prefix (§3.6) |
| 7 | point `gh` at the same credential helper | **measured false.** `gh api` and `gh pr create` never invoked the helper (0 log lines) and demanded `gh auth login`/`GH_TOKEN`. `gh auth git-credential` is the *reverse* direction. So no pane can open a bot-authored PR at all | **Deck creates the PR** through the App API; the agent only pushes the branch (§5.5) |
| 8 | helper returns `501` and git falls back | **measured false.** The empty-reset wipes the ambient helper, so a silent helper yields `could not read Username`. Also: refusing a primary workspace without releasing it leaves `acquire` returning it forever (`:103-109`) | configure **no** Deck helper when App auth is unavailable (§5.5); refuse-and-release primary — *superseded by revision 5 row 1, which does not lease the primary at all* (§5.7) |

Revision 4 also answers a question no review raised, found while tracing every writer of `pr_number` for blocker 7: the `/dispatch-status` route's `in_progress` branch writes `item.pr_number` directly, bypassing `report_pr_opened` and therefore every verification check — and because `_ack_satisfied` short-circuits on a non-NULL `pr_number`, one such report also silences the leader-ack gate. Now refused (§5.6). This is blocker 1's shape one branch over: the named path was hardened while an unnamed side door wrote the same column unchecked.

**One retraction.** Revision 3 claimed "no pane ever holds a token." That overstates it: git receives the helper's plaintext password, and an agent can run `git credential fill` to print it. The defensible guarantee — and what §8 now says — is that the credential is short-lived, repository-scoped, not persisted, and not inherited in the pane environment. Absence is not achievable while the agent runs git itself.

**What revision 5 changed.** The fourth review found eight blockers in revision 4. All eight confirmed; **none refuted**. One of them falsified a claim revision 4 had invented to justify a decision, and the corrected measurement changed the fix rather than only the test.

| # | Revision 4 said | Measured reality | Now |
|---|---|---|---|
| 1 | refuse a primary workspace, release the lease, let the next attempt find a worktree | `release` sets `leased_item_id = None`, so the primary re-matches `acquire`'s filter and `order_by(id)` returns it again — forever. Revision 4's own test 28c **could not pass against revision 4's design** | `acquire(..., allow_primary=False)` **excludes** `kind == "primary"` from the scan; nothing is leased and nothing needs releasing (§5.7) |
| 2 | a rejection increments `approval_round_count`; approval evidence is not revisited | `record_approval_round` is 4 lines that identify nothing and clear nothing, and revision 4's own one-request-per-item `409` **blocks** the documented recovery: the owner cannot open a round-2 request | decisions are **round-scoped**: `approval_round` on the request and the decision, `ack_approval_round` on the item, and `revision_requested` increments the round *and* clears all five ack columns (§4.3a.1) |
| 3 | no binding row ⇒ `bind_pending`, retried "every 60s" | a hand-started pane has no binding row and never will, so **every mail tool fails for its whole life** (`_guard` re-registers before each one). And the failing heartbeat backs off to `HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS = 300.0`, not 60 | "no row **and** no claimed team context" ⇒ mint **unbound**; `bind_pending` is reserved for a pane claiming a Deck launch; the retry interval is stated as **300s** with `_guard` as the fast path (§3.3a) |
| 4 | table row 4 refuses a tokenless re-registration; the next paragraph re-mints when the pane binding matches | the same request, two opposite answers. And the case the paragraph existed to rescue **cannot occur**: `session_key` is minted per process (`agent_mail_server.py:26`), so a restarted shim is a *first* registration | the rescue rule is **withdrawn**; row 4 stands unqualified, and the reasoning is pinned by tests 14b/14c (§3.4) |
| 5 | deriving `reporting_slot_id` from a token fixes dispatch-status trust | authentication is not authorization: **1 of 9** branches compares the reporter to the item. A Specialist could withdraw another slot's approval, accept a foreign handoff, or plant a `pr_number` | an explicit owner/leader/target **matrix** for every branch, plus the current lease token on the two GitHub-writing branches (§3.5a) |
| 6 | "on the `pr_opened` path App auth is by definition unconfigured, so `github_app_bot_login` is empty" | **outright false, and in the direction that disables a check.** The setting is global; App auth is per repository. The combination declared impossible is the normal case for any uninstalled repo | a persisted per-repo `github_auth_mode` (`unknown`/`app`/`ambient`), and **transient** lookup failures refuse instead of silently selecting the ambient credential (§5.6a) |
| 7 | `pr_ready` is idempotent because `item.pr_number` is checked first | `pr_number` is a **cache** of a GitHub fact. A crash between `create_pull` and the commit leaves a live PR Deck has no record of; the retry then creates again and hits an unhandled `422` | reconcile by **head/base** before creating *and* after a timeout or `422`; adopt a single match through §5.6's checks; per-item lock (§5.5.4). `GithubClient` has no by-head method today — that is why revision 4's "reconcile" had nothing to reconcile with |
| 8 | create the PR as a draft, with the agent owning the title | a **draft PR cannot be approved**, and `mark_pull_ready_for_review`'s only caller is `_promote_verified_item` — which design items never reach (`_process_review_item` returns early). So a design PR would be announced "ready for human review" and stay a permanent draft. The report also carries only `head_ref`, so Deck could not apply a title it was never sent | `draft = item.issue_type != "design"`, and Deck composes the title and body from the item row (§5.5.5) |

Revision 5 also answers a question no review raised, found while writing §5.5.5's field table: `scope.base_ref` holds a git **refspec** — `origin/master` live, `origin/HEAD` by default — and `POST /pulls` takes a **branch name**. Sent unchanged, `create_pull` would be rejected and §5.5.4's `base` filter would match nothing, which is the same silent-no-match failure §5.5.4 exists to prevent. Now normalized in one helper (§5.5.5), with tests 46 and 49b.

**A second retraction, and the lesson behind it.** Revision 4 rejected the scan-exclusion fix for blocker 1 by asserting that narrowing `acquire`'s filter "would change behavior for callers that are not doing identity work, because `acquire` is also how Deck leases a primary checkout for observation purposes." Measured: `acquire` has **exactly one** non-test caller, `github_dispatch_service.py:277`, the dispatch path. There is no observation caller. The sentence was invented to justify a choice already made, and it is retracted in §5.7.

That is now twice in this spec that the alternative dismissed in a "deliberately not chosen" note turned out to be the right answer, both times dismissed on an unverified claim about callers. A rejected alternative needs a measurement, or it is just a confident sentence — and a confident sentence is what a reviewer has no way to check.

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
# agent_mail_service.py:295-305 — the whole check
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
     registration returns a token bound to the caller's tmux pane, or
     an unbound one for a pane Deck did not launch; identity-bearing
     writes require it and derive the actor server-side; every
     /dispatch-status branch gets an authority rule. Ships disabled;
     the operator enables it.

PR1  Approval attribution + a real gate         (pure code, testable offline)
     1. link ack requests to work items with a per-dispatch nonce
     2. an explicit leader decision, recorded as a column, not prose
     3. record who approved; require the designated leader; reject replay
     4. scope decisions to an approval round, so a rejection withdraws
        the previous round's approval by construction
     5. make auto-merge require a valid distinct approval
     6. surface the new fields in the work-item response

PR2  Distinct commit/PR identity                (needs a GitHub App)
     one bot as PR author because DECK opens the PR through the App API,
     composing the title, body and draft flag itself and reconciling by
     head/base so a crash cannot open a second one; per-slot commit
     identity via per-worktree git config; push credentials minted at use
     time by a credential-helper callback, scoped to one repo; a persisted
     per-repo auth mode that fails closed on an unresolved lookup;
     every writer of pr_number verified, including the in_progress side door
```

**Why PR0 is separate and first.** PR1's entire value is that its evidence cannot be fabricated. Shipping PR1 without PR0 produces a gate that logs an approver id an agent chose for itself — worse than no gate, because it reads as enforcement. PR0 is also a strictly larger blast radius (every mail write path, the shim, the UI, ~13 test call sites), and a reviewer must be able to reject the auth change without rejecting the dispatch change. PR0 additionally closes the separately-tracked `/dispatch-status` auth gap, which is the same defect one router over.

**PR0 ships inert and is switched on by hand.** A pre-upgrade shim cannot learn to send a header it has never heard of, so enforcement is behind `mail_capability_tokens_required`, default `False` (§3.4). Deploying PR0 changes no behavior. The operator restarts the agent panes, confirms every live session has a token, then flips the flag. PR1's gate refuses to merge anything while the flag is `False` (§4.5), so the inert state is safe rather than silently degraded.

**Why PR2 is last.** Its failure mode is a *deadlocked* merge, not a *bad* merge. If PR2 slips, autonomy is strictly safer than today rather than blocked on provisioning.

**PR2 grew a responsibility in revision 4.** Deck now opens the PR itself (§5.5.2), because `gh` in a pane provably cannot do it with App credentials. That moves one action from the agent to Deck, which is a larger change than revision 3 described — but it also *removes* §5.6's whole reason for existing on that path, since Deck no longer has an agent-supplied `pr_number` to distrust. Net, PR2 is a little bigger and materially simpler to reason about.

**And revision 5 makes that responsibility carry a cost revision 4 did not price.** Once Deck performs the `POST /pulls`, Deck owns its idempotency, and GitHub offers no idempotency key for pull creation. §5.5.4 pays that cost with a reconcile-by-head step and one new read method; §5.6a pays a second one, because Deck must now know per repository whether it *can* act as the App before it writes any credential config. Both are consequences of moving the action, not separate features — worth naming here so a reviewer sizing PR2 sees the whole of what §5.5.2 bought.

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

`agent_pane_bindings` (§3.3) is a **new table**, so it is created by `create_all` rather than by a migration rung — the project has no migration system beyond the additive `ALTER TABLE` ladder, and new tables have always arrived this way. No rung is needed; the ladder is only for columns on existing tables.

**Storage is a hash, and that has a consequence revision 3 missed.** `capability_token_hash` stores sha256 only, matching `mail_external_actors.token_hash`. So the plaintext is **unrecoverable by construction** — see §3.4, where revision 3's "returns the same token" turned out to be impossible.

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

**Platform contract, which revision 3 left implicit.** This mechanism is Linux-specific: `/proc/net/tcp` does not exist on macOS or Windows, and nothing in Deck's README or `CLAUDE.md` declares a supported platform. Revision 3 simply assumed Linux. Stated explicitly:

- **PR0 requires Linux** for token binding. This is a new documented requirement, and it goes in `README.md` as part of PR0, not as a follow-up.
- On a platform where the peer pid cannot be derived, registration refuses with `bind_unverifiable` (§3.3 rung 1). Deck remains usable — mail still works in grace mode — but `mail_capability_tokens_required = True` is unsupported there, and therefore so is auto-merge. Fail closed, consistent with the standing G2/G3 rule.
- The resolver must read **both** `/proc/net/tcp` and `/proc/net/tcp6`. Measured on this host: an IPv4 loopback connection appears **only** in `tcp`, an IPv6 one **only** in `tcp6`.

```
IPv4 client (127.0.0.1) -> found in /proc/net/tcp, absent from tcp6
IPv6 client (::1)       -> found in /proc/net/tcp6, absent from tcp
```

The live backend binds `127.0.0.1:8000` (measured: `uvicorn pid=2206652`), so IPv4 is today's path — but that is a config value, not a guarantee. A resolver reading one table would silently refuse every client the day someone binds `::1`, and the failure would look like a broken token rather than a missing table. Read both; match on the inode either way.

**From the peer pid to a slot.** Measured on the three live Codex shims:

```
149263 (codex) -> ppid 149190 (MainThread) -> ppid 149167 (tmux: server)
159024 (codex) -> ppid 159009 (MainThread) -> ppid 149167 (tmux: server)
379563 (codex) -> ppid 379552 (MainThread) -> ppid 149167 (tmux: server)

$ tmux list-panes -a -F "#{pane_id} #{pane_pid}"
%2 149190   %3 159009   %4 379552
```

Every shim's parent **is** a tmux pane pid. So the chain is: peer pid → walk `ppid` until it hits a pid in tmux's pane list → that pane. `_resolve_pane_pid` (`github_dispatch_service.py:181-200`) already does the tmux half of this, and `_pid_is_descendant` (`agent_mail_service.py:477`) already walks ppids with a depth cap of 8.

**From the pane to a slot — and why a launch item cannot answer it.** Revision 3 proposed adding `pane_pid` to `AgentTeamLaunchItem` and looking the slot up there. The third review showed that is wrong on three counts, all confirmed:

1. **Launch rows are historical, not current.** `agent_team_launch_items` accumulates one row per slot per launch forever. A pid appearing in an old row proves only that some pane once had it. With pid reuse, a *new* unrelated process can match an old row — and multiple rows can match one pid across launches, with no rule saying which wins.
2. **They carry no process identity.** The row has no `proc_start`, so it cannot distinguish "the pane I spawned" from "a different process that inherited the number." §3.2 argues this exact point for sessions and then revision 3 failed to apply it here.
3. **The write is not committed when the shim registers.** `_record_launch_item` only calls `db.add`; the sole `await db.commit()` is at `agent_team_service.py:530`, **after the entire slot loop finishes**. So the spawned agent for slot 1 can register while slots 2-6 are still spawning, and its own row is not yet visible to the registration transaction. The review called this a race with one insert; measured, the window is the whole launch.

So the binding needs a table whose rows mean *this pane is running this slot right now*:

```python
# new table, written at spawn, deleted when the pane dies
class AgentPaneBinding(Base):
    __tablename__ = "agent_pane_bindings"
    id: Mapped[int]                      # pk
    pane_pid: Mapped[int]                # unique together with proc_start
    pane_proc_start: Mapped[str]         # /proc/<pid>/stat field 22, as elsewhere
    slot_id: Mapped[int]                 # FK agent_team_slots, ondelete SET NULL
    preset_id: Mapped[int]
    tmux_target: Mapped[str | None]
    created_at: Mapped[datetime]
```

`UNIQUE(pane_pid, pane_proc_start)` — the pair is the identity, per §3.2's own reasoning. A lookup by pid alone that finds rows with differing `proc_start` values resolves to the one whose `proc_start` matches the live `/proc/<pid>/stat`; if none matches, the pane is gone and the rows are stale.

**Written before spawn returns, committed immediately.** `_execute_plan_item` computes the pane pid on both paths already — `spawned.get("pid")` at `agent_team_service.py:637` and `plan_item.matching_session.get("pid")` at `:569`. The binding row is written and **committed on its own** at those two points, not deferred to `:530`. That is a deliberate departure from the surrounding transaction style, and it is the point: the row must be visible to a different request before the loop that created it finishes. A comment must say so, or a later refactor will fold it back into the outer commit and reintroduce the race silently.

Reuse writes a binding too, so spawn and reuse are identical for binding purposes — the reason this approach beats a spawn-time secret, and why **there is no `:575` problem here.**

**Registration then binds:**

1. Derive the peer pid from the connection (both `/proc/net/tcp` tables). If it cannot be derived, refuse — `bind_unverifiable`.
2. Walk to the owning tmux pane pid. If no ancestor is a pane, this is not a tmux-hosted agent: mint a token with **no slot binding** (`team_slot_id` stays `NULL`). Such a session can send mail as a repo member; it can never be an approver.
3. Look up `agent_pane_bindings` by `(pane_pid, live proc_start)`.
   - **Exactly one row** ⇒ that row's `slot_id` is the slot.
   - **No row, and the request claims no team context** ⇒ mint unbound, as rung 2. A tmux pane Deck never launched is an ordinary repo member, not a broken team agent (§3.3a).
   - **No row, but the request claims team context** ⇒ `bind_pending`, a **retryable** refusal (`409`, not `403`): Deck may not have committed the binding yet. A `403` here would permanently strand a correctly-launched agent that merely registered early. On retry timing, see §3.3a.
   - **Row exists but its `slot_id` is NULL** (slot deleted) ⇒ mint unbound, as rung 2.
4. A `team_slot_id` in the body that disagrees with the derived slot is a `403` — derive, do not compare (§3.6).
5. Record `bound_pane_pid` and `bound_pane_proc_start` on the session.

**Cleanup.** Stale bindings are pruned the way session rows already are: a row whose `(pid, proc_start)` no longer matches a live process is deleted on the next registration sweep. This reuses `_read_proc_start`'s existing distinction between *process gone* (`FileNotFoundError` ⇒ prune) and *cannot observe* (`OSError` ⇒ keep, fail closed) at `github_workspace_service.py:83-95`. Do not write a new liveness check.

**Residual risk, stated plainly.** All panes run as one user with no `hidepid`, so any pane can read `/proc/<other>/environ` and `/proc/<other>/stat` — measured: 123 environment entries readable from another pane, including `CLAUDE_DECK_TEAM_SLOT_ID`. A pane that wanted to impersonate another slot could therefore *read* the target's secrets. It still cannot **use** them for registration, because binding is derived from its own connection, not from anything it can present. What it cannot do is make the kernel say its socket belongs to a different process.

This is the honest limit: pane binding defeats *claiming* another slot, not *co-resident compromise*. Defeating co-residency needs OS isolation (separate users, `hidepid=2`) and is out of scope. §8 records it as accepted.

### 3.3a `bind_pending` is for Deck's own launches, and it retries slower than revision 4 said

Revision 4's rung 3 returned `bind_pending` for **every** pane with no binding row. The fourth review is right that this strands panes that are not doing anything wrong, and the retry figure it quotes was also wrong. Both confirmed.

**The population revision 4 stranded.** Most tmux panes on this host were never launched by Deck. A developer opens a pane, starts `codex` or `claude` by hand in a repo, and the shim registers — that is how the `repo member` participant kind exists at all (`_get_or_create_repo_member`, `agent_mail_service.py:142`). Such a pane has no `agent_pane_bindings` row and never will, because nothing will ever write one for it. Under revision 4 it receives `409 bind_pending` on registration, and `_guard` (`agent_mail_server.py:201-203`) calls `_ensure_registered` **before every tool**, so *every* mail tool fails for the lifetime of that pane. Revision 4 turned a working feature into a permanent failure for the common case, in the name of a refusal that can never resolve.

**The discriminator already exists in the request body.** The shim sends `team_preset_id` / `team_slot_id` only when `CLAUDE_DECK_TEAM_PRESET_ID` / `_SLOT_ID` are in the pane's environment (`agent_mail_server.py:148-153`, and the same pair in `agent_mail_hook.py:72-73` and the installed JS at `agent_mail_install_service.py:587-588`). Measured: the only writer of those variables is `_execute_plan_item`'s spawn env (`agent_team_service.py:620-625`). So a body claiming team context is a pane asserting *"Deck launched me into a team slot"*, and a body claiming none is a pane asserting nothing.

That claim is not trusted for **identity** — §3.3's rule stands, the slot is derived and a disagreeing claim is a `403`. It is used only to choose between two *refusal* policies, which is a strictly weaker use. Getting it wrong in the attacker's favour buys nothing: claiming team context you don't have yields `bind_pending`, i.e. no token at all, which is worse for the caller than the unbound token they would otherwise get. There is no version of this lie that gains a slot binding.

So rung 3 splits:

| Binding row | Body claims team context | Result |
|---|---|---|
| exists, `slot_id` set | either way | bound to that slot (derived; a disagreeing claim is `403`) |
| exists, `slot_id` NULL | either way | unbound token |
| none | **no** | unbound token — an ordinary repo member |
| none | **yes** | `409 bind_pending`, retryable |

An unbound session can send mail and be a repo member. It can never be an approver, because §4.3's evidence requires `ack_approver_member_id` to resolve to the leader's **slot** member. Minting unbound is therefore not a weakening of the gate; it is the pre-PR0 behaviour, preserved for panes the gate was never about.

**The retry interval is 300 seconds on the failing path, not 60.** Revision 4 wrote that the shim "retries on its next heartbeat, which it already performs every 60s." Measured — `_heartbeat_once` (`agent_mail_server.py:164-168`):

```python
def _heartbeat_once() -> float:
    result = _ensure_registered()
    if result["ok"]:
        return HEARTBEAT_INTERVAL_SECONDS            # 60.0  (:18)
    return HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS    # 300.0 (:19)
```

The interval it returns is the *sleep before the next attempt* (`_heartbeat_loop`, `:171-173`). A refused registration is not `ok`, so the heartbeat backs off to **300s** — the very case where 60s was claimed. Revision 4 quoted the success interval to describe the failure path.

Three consequences, all of which PR0 must state rather than discover:

1. **`bind_pending` resolves within 300s, not 60s, via the heartbeat.** That is the honest worst case for a legitimately-launched agent that registers before its binding commits.
2. **In practice it resolves much faster, because `_guard` also re-registers.** Every mail tool call runs `_ensure_registered` first (`:201-203`), so an agent that does anything at all retries immediately. The 300s figure bounds an *idle* agent.
3. **The binding write is what makes this rare.** §3.3 commits the row at spawn (`agent_team_service.py:569`, `:637`) precisely so the window is the round trip, not the launch loop. `bind_pending` is the safety net for that window, not the normal path.

PR0 does not change either heartbeat constant. Shortening the failure backoff would be a plausible-looking fix that trades a 5-minute worst case in a rare window for a tighter poll against an unreachable backend, which is what that constant exists to avoid.

### 3.4 Minting: stable for the session

Revision 2 rotated the token on every registration. That is a race. `_ensure_registered` (`agent_mail_server.py:139`) is called from **five** places — `_guard` before every tool call (`:202`), `deck_report_dispatch_status` (`:618`), `deck_list_work_items` (`:640`), `deck_retry_work_item` (`:686`), and the 60-second heartbeat thread (`:165`). Its `threading.Lock` serializes the shim's own calls but not the round trip: the heartbeat can rotate the stored hash after a concurrent tool call has already built its header, and that call then fails `401` for no reason the agent can act on.

So: **mint once per session row, on first registration.** But revision 3 then said re-registration "returns the *same* token," which is **impossible as written** — only the sha256 hash is stored, so the backend cannot reproduce a plaintext it has already discarded. Recoverable storage would mean encrypting live credentials at rest, which is strictly worse than the problem it solves.

The fix is that the backend does not need to return it. **The shim already has state.** `_state` holds `session_key` and `member_id` (`agent_mail_server.py:145`, `:160`), so it holds the token too:

| Case | Backend | Shim |
|---|---|---|
| first registration (row has no `capability_token_hash`) | mint, store hash, **return plaintext once** | store plaintext in `_state["capability_token"]` |
| re-registration, token presented and valid | return **no** token field; touch `last_seen_at` | keep the cached token |
| re-registration, token presented but invalid | `401`, mint nothing | clear `_state` and fail the tool call |
| re-registration, no token presented but a hash exists | refuse `token_required_for_rebind` (`409`) | cannot occur — see below |

So the token travels **exactly once per session row**, and re-registration *authenticates* with the token it already holds rather than asking for a replacement.

**Revision 4 contradicted itself here, and the fourth review is right.** Row 4 of the table refused a tokenless caller whose row has a hash; the paragraph that followed said re-mint whenever "the peer-derived pane binding matches the stored binding." Those are the same request with opposite answers — a restarted shim presents no token, has a hash on file, and matches the binding. An implementer would have had to pick one, and nothing in the spec said which.

**The measurement that dissolves it.** The paragraph existed to rescue a shim that restarts inside a live pane. That case cannot reach row 4, because the session key is per **process**:

```python
# agent_mail_server.py:24-29 — evaluated once, at module import
_state: dict[str, Any] = {
    "member_id": None,
    "session_key": f"mcp:{uuid.uuid4().hex[:12]}",
    ...
}
```

A stdio MCP server is spawned by its client, so "crash" and "MCP reconnect" both mean a new process, hence a fresh `session_key`. The backend looks the session up by `session_key` (`agent_mail_service.py:176-178`), finds nothing, and creates a new row — which is a **first** registration, row 1, and it mints. The restarted shim is never a rebind.

So the rescue rule is **withdrawn**, and row 4 stands unqualified. What actually reaches row 4 is a caller presenting *someone else's* `session_key` with no token — and that key is readable by every agent from the unauthenticated `GET /agent-mail/team` (§3.2). Refusing is the only correct answer. Revision 4's rule would have handed a fresh token to any co-resident caller that replayed a known session key from the bound pane; deleting it narrows the surface rather than widening it.

Two consequences to state rather than leave for an implementer to notice:

- **A dead shim's row keeps its hash forever, and PR0 deliberately leaves it there.** Measured: the only session-deleting code in the service is `_remove_stale_observed_sessions`, and it selects `source == "observed"` (`agent_mail_service.py:565-568`, delete at `:576`). **No path ever deletes an `mcp` session row** — which is precisely why 150 of them exist with 7 connected. So a dead shim's `capability_token_hash` persists indefinitely. That is safe, because nobody holds the plaintext: it lived only in the dead process's memory and the backend discarded it at mint time. The hash is an unusable artifact, not a live credential.

  The tempting cleanup — null the hash when a session goes offline, so the row looks tidy — is a **hole**, and PR0 must not do it. A hashless row with a known `session_key` is a *first* registration (row 1), so any co-resident caller replaying that key would be minted a fresh token. Keeping the hash is what makes row 4's refusal permanent for that row. Stale-looking state is the safe state here; §8 records it as accepted rather than fixed.
- **One pane can therefore own several session rows over its life.** Already true today, and it does not weaken the gate, because approval evidence resolves to a **member**, not a session (§4.3). Deck's roster already tolerates this.
- **`agent_pane_bindings` is different and does get pruned**, on `(pid, proc_start)` liveness (§3.3), because a stale binding row *would* mislead a live registration into a slot claim. Two tables, two retention rules, for a stated reason.

There is no "binding changed" case to handle. The peer pid is the shim's own pid, so a changed pane binding under a *stable* `session_key` would require the shim to be reparented while running — at which point it no longer walks up to any pane and rung 2 mints unbound. Adding a rebind path for it would be a rule with no reachable trigger, which is how revision 4 got here.

This also removes any need for a grace window or current-plus-previous hashes. There is no rotation to be caught mid-flight.

**Deployment.** A pre-upgrade shim cannot self-heal: its loaded code has no idea the header exists, so it will never send one, no matter how many times it heartbeats. Revision 2's claim that this "self-heals without operator action" was wrong. PR0 therefore requires a **grace mode**:

- `mail_capability_tokens_required: bool = False` in `config.py`.
- With it `False` (the default PR0 ships), a request with no token falls back to today's caller-supplied behavior and the response logs `capability_token_missing` once per session. Nothing breaks on deploy.
- The operator restarts the agent panes at their convenience, confirms every live MCP session has a `capability_token_hash`, then flips it `True`.
- PR1's merge gate requires `True`. §4.5 states this as a precondition, and the gate refuses (`tokens_not_enforced`) when it is `False` — a gate whose evidence is optional is not a gate.

Live blast radius: 150 `source='mcp'` session rows, of which 7 are `connected` with a recent `last_seen_at`. Restarting agent panes is a normal operation here, but it is the operator's to schedule — and it is one more reason autonomy stays off until this lands.

### 3.4a Grace mode must not accumulate approval evidence

Revision 3 argued grace mode was safe because PR1's gate refuses while enforcement is off (§4.5). That reasoning has a hole the third review found, and it is a real one.

While enforcement is off, ack reporting still **runs** and still **writes** `ack_approver_member_id` and `ack_evidence_message_id`. Those writes are unauthenticated, so an agent can forge a leader answer and have Deck record it as approver evidence. The gate correctly refuses *at that moment*. But the columns persist. The instant the operator flips `mail_capability_tokens_required` to `True`, the gate starts trusting columns that were populated when nothing was verified — and it cannot tell the difference, because the columns carry no record of the regime they were written under.

The refusal was time-shifted, not enforced. Two changes close it:

**1. Refuse to record at all while enforcement is off.** `record_ack_received` returns `AckEvidence(ok=False, reason="tokens_not_enforced")` before evaluating anything when `mail_capability_tokens_required` is `False`. No approver columns are written in grace mode, ever. Items dispatched during grace mode are acked after the flip, or they wait — which is correct, because during grace mode an ack genuinely cannot be attributed. This also makes the flag's meaning uniform: it is not "check tokens on writes," it is "approval attribution is operational."

**2. Stamp the epoch anyway, as defense in depth.** A third column records the regime:

```python
if work_item_columns and "ack_enforcement_epoch" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_enforcement_epoch INTEGER"))
```

`1` means "recorded while tokens were enforced." NULL or `0` means "recorded before enforcement" and the gate rejects it with `evidence_predates_enforcement`. Change 1 means no row should ever be written with `0` — so the column is a *check on the implementation of change 1*, not a substitute for it. If a future refactor reintroduces grace-mode writes, the gate still refuses instead of silently trusting them.

Belt and braces is justified here because the failure is invisible: forged evidence written today becomes acceptable on a config change months later, with no log line at the moment it starts being trusted. This is the same shape as [[invariant-evidence-freshness]] — a safety rule reading data whose trustworthiness changed after it was written.

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

### 3.5a Authentication is not authorization: who may report what

§3.5 makes `reporting_slot_id` **derived** rather than claimed. The fourth review is right that this answers "who is calling" and leaves "may they do this" unanswered, and the gap is measurable: of the nine branches in `report_dispatch_status`, exactly **one** compares the reporter to the item.

```python
# agent_teams.py:333-338 — the only authorization check in the whole endpoint
elif report.status == "workspace_released":
    if report.reporting_slot_id != item.owner_slot_id:
        raise HTTPException(status_code=409, detail="only the owner slot may release its workspace")
```

Every other branch reads `report.work_item_id` and acts. Deriving the slot from a token turns "any process with curl" into "any *registered agent*," which is a real narrowing and still not authorization — the population that matters here is other agents on the same team, and they are all registered. A Specialist can currently mark another slot's item `blocked`, accept a handoff aimed elsewhere (guarded only by `handoff_target_slot_id`, which is the one other comparison in the service), or report `pr_opened` on an item it has nothing to do with.

**The matrix.** Roles are: **owner** = `item.owner_slot_id`; **leader** = `_leader_slot(preset_slots)` (`github_dispatch_service.py:534-539`); **target** = `item.handoff_target_slot_id`. A row's authority is checked *after* the token resolves the caller's slot and *before* any state change.

| Branch | Who may report it | Lease token | Refusal |
|---|---|---|---|
| `triaging` | owner | not required | `403 not_item_owner` |
| `in_progress` | owner | not required | `403 not_item_owner` |
| `blocked` | owner | not required | `403 not_item_owner` |
| `handoff_initiated` | owner **or** leader | not required | `403 not_owner_or_leader` |
| `handoff_accepted` | **target** only | not required | `403 not_handoff_target` (in addition to the existing `409` when `handoff_target_slot_id` disagrees) |
| `revision_requested` | **leader** only | not required | `403 not_leader` |
| `ack_received` | owner | not required | `403 not_item_owner` |
| `pr_opened` | owner | **required** | `403 not_item_owner`; `409` on token mismatch |
| `workspace_released` | owner (already enforced) | **required** (already enforced) | unchanged |
| unknown status | — | — | `400` (unchanged) |

Four points where the shape of that table is a decision rather than a transcription:

**1. `revision_requested` is the leader's, and it is the one branch where the current code is actively dangerous.** It calls `record_approval_round` (`:301-302`), which under §4.3a.1 increments the round and **clears the ack columns**. Left unauthorized, any agent can withdraw an approval it does not own — or, more usefully to a blocked agent, spam the round counter to `max_approval_rounds` and force an escalation. It is also the semantic opposite of the others: a rejection is an *approver's* act, so the owner must not be able to report it. That the owner cannot self-reject is the same distinctness principle §4.5 enforces for approval, applied to the other direction.

**2. `handoff_accepted` belongs to the target, not the owner.** The existing `ValueError` in `accept_handoff` (`:697-702`) compares the accepting slot against `handoff_target_slot_id` and does discriminate correctly — this row mostly makes an existing implicit rule explicit and gives it a `403` instead of a `409`. Keep both checks: the `403` says "you are not the target," the `409` says "there is no handoff to accept," and collapsing them loses the distinction an agent needs to act on.

**3. The lease token is required exactly where the branch causes a GitHub write, and `pr_opened` is the only new one.** Measured: `report_pr_opened` (`github_verification_service.py:44-86`) makes no GitHub call itself, but it sets `item.pr_number`, which is what admits the item to `process_scope`'s query (`:95-110`) and from there to `_verify_item` and `_promote_verified_item` — the merge. So `pr_opened` is the entry point to the write path even though it writes nothing itself. Requiring the current lease token means a stale attempt cannot inject a PR number into a re-dispatched item, which is precisely the class of bug the lease token was introduced for in G2.

  `in_progress` is **not** on the required list, because §5.6 removes its `pr_number` write entirely. If a future change restores that write, this row must change with it — noted here because the two facts are only safe together.

**4. Everything else takes no token deliberately.** Requiring a lease token on `triaging` or `blocked` would break the one path that most needs to work: an agent reporting that it is stuck. `blocked` escalates to a human, and a gate that can refuse an escalation because a lease rotated is a gate that hides failures. Authority without a token is the right trade for reports that only ever *reduce* Deck's confidence.

**Where the check lives.** In `report_dispatch_status`, as a small resolver called once before the branch chain — not inside each service function. The services are also called from the monitor loop and from operator paths that have no reporting slot, and pushing agent authorization into them would either block those callers or grow an `if caller_is_agent` parameter through five signatures. The endpoint is the trust boundary; the check belongs at the boundary.

**What this does not fix.** `touch_owner_contact` runs in the endpoint tail for any report whose `reporting_slot_id` equals the owner's (`agent_teams.py:371-377`). With derived slots that is now honest, so no change is needed — but note it stamps contact evidence as a *side effect* of an authorized report, and its docstring already accepts a stale token as a no-op (`github_workspace_service.py:255-259`). That is consistent with point 4: contact evidence is not a gate input for merging, only for nudge timing ([[ack-is-liveness-not-approval]]).

**Tests** (offline, in §3.7's file since they are token-dependent):

7b. Each branch in the matrix, reported by a non-authorized slot ⇒ the stated `403`, and the item's columns are **unchanged**. Assert the state, not just the status code — a route that mutates then refuses returns the same code.
7c. `revision_requested` from the **owner** ⇒ `403 not_leader`, and `approval_round_count` is unchanged. This is the withdrawal-spam test; it must fail against revision 4, which had no authorization here at all.
7d. `revision_requested` from the **leader** ⇒ `200`, round incremented, ack columns cleared (§4.3a.1).
7e. `handoff_accepted` from a slot that is neither target nor owner ⇒ `403 not_handoff_target`; from the target ⇒ `200`. Both against an item whose `handoff_target_slot_id` is set, so the existing `409` path is not what produces the refusal.
7f. `pr_opened` from the owner with a **stale** lease token ⇒ `409`, and `item.pr_number` stays `NULL`. Then the same call with the current token ⇒ `200`. The `NULL` assertion is the point: if `pr_number` is set before the token check, the item enters `process_scope` and the refusal is cosmetic.
7g. `blocked` from the owner with **no** lease token ⇒ `200` and the escalation is recorded. Written to fail against an implementation that requires the token everywhere "for consistency."

| Mutant | Test that must fail |
|---|---|
| authorization checked after the state change | **7b, 7f** |
| `revision_requested` allowed to the owner | **7c** |
| `handoff_accepted` authorized to the owner instead of the target | 7e |
| lease token required on every branch | **7g** |
| lease token dropped from `pr_opened` | 7f |

### 3.6 The operator path stays open

The Agent Mail UI writes as an operator-chosen member (`ThreadDialog.tsx:159` sends `sender_member_id: senderId`) and holds no session token. Two write paths therefore need a non-session identity: the UI's reply/compose, and its ack.

Rather than invent a third auth scheme, the UI authenticates as an **external actor** — the mechanism that already exists for exactly this, is loopback-gated at creation (`external_agent_mail.py:76-78`), and lands in `sender_actor_id` rather than `sender_member_id`, so operator-authored messages are *distinguishable from* agent-authored ones in the data.

This has a consequence PR1 depends on and §4.3 states explicitly: an operator-authored message has `sender_member_id = NULL`, so it can never be mistaken for the leader's approval. A human who wants to approve does it by merging, not by typing into the mail UI.

**Provisioning.** No new mechanism is needed, but revision 3 got two details wrong and both are confirmed.

*The URL was wrong.* Revision 3 wrote `/external-agent-mail/actors`. The router mounts this at `prefix="/external/agent-mail"` (`app/api/v1/router.py:63`), so the real path is **`/api/v1/external/agent-mail/actors`**. A plan built on the wrong path fails at the first request.

*A fixed `actor_key` makes tabs fight.* `MailExternalActor.token_hash` is a **single** column (`app/models/database.py:409`) and `create_actor` **overwrites** it on every call (`external_agent_mail_service.py:105`), while `actor_key` is `unique`. So with a shared `deck-ui` key: tab A provisions, tab B provisions and invalidates A's token, A gets a `401` and re-provisions, invalidating B — an endless mutual-eviction loop, each round trip triggered by an ordinary mail write. Revision 3's "a rotation on the next page load is free" is true for one tab and false for two.

The fix is a **per-tab actor key**, which the existing model already supports since the key is the identity:

- On first mail write in a tab, generate `actor_key = "deck-ui-" + crypto.randomUUID().slice(0, 8)`, `POST` it to `/api/v1/external/agent-mail/actors`, and keep the returned token in `sessionStorage` alongside the key.
- `sessionStorage`, not `localStorage`: both the key and the token die with the tab, so tabs never share a key and never rotate each other's token. A new tab is a new actor, which is also more honest — two operator tabs *are* two clients.
- `ACTOR_KEY_PATTERN` allows letters, numbers, `_ . : -`, 2-80 chars (`external_agent_mail_service.py:80`), so this form validates.
- On `401` the tab re-provisions **its own** key once and retries. With per-tab keys a `401` now means "my actor was pruned," not "another tab stole my slot."
- The ack path uses the actor ack endpoint that already exists (`external_agent_mail.py:218`), so no new route is needed for §3.6's second write path.

**One consequence to accept:** per-tab actors accumulate rows in `mail_external_actors`. That is a cosmetic cost — the table has no unique constraint problem and the rows are inert once their `sessionStorage` dies. If the roster view becomes noisy, prune actors whose `last_used_at` is older than a threshold and whose key matches `deck-ui-*`. Out of scope for PR0; noted so a reviewer does not mistake it for an oversight.

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
11. A pane pid matching an **`agent_pane_bindings` row** for slot 6 ⇒ session bound to slot 6 even when the body sends no `team_slot_id`. The row is the anchor, not a launch item: §3.3 rejected `agent_team_launch_items` on three counts, and revision 4's test still named them, so this test would have driven an implementer straight back into the race it exists to avoid.
12. Pane pid reuse: a binding row whose `pane_proc_start` differs from the live `/proc/<pid>/stat` value ⇒ that row is stale and does not bind. With no other row and no claimed team context, the token is minted unbound (§3.3a); with claimed team context, `bind_pending`.
12b. **The unbound path is not a refusal.** A pane with no binding row and a body claiming no team context ⇒ `200`, a token is minted, `team_slot_id` is `NULL`, and a `POST /messages` with it succeeds. This is the blocker-3 test: it must fail against revision 4, which returned `409 bind_pending` here and made every mail tool in a hand-started pane fail forever.
12c. Same pane, but the body claims `team_preset_id`/`team_slot_id` ⇒ `409 bind_pending`, no token minted. Asserting 12b alone would pass against an implementation that never refuses at all.

Stability (§3.4):

13. **Re-registration authenticates; it does not re-issue.** Register once and keep the plaintext. Register again from the same live pane *presenting that token*: the response contains **no** token field, `capability_token_hash` on the row is byte-identical to before, and the original token still authenticates a subsequent `POST /messages`. Revision 4's version of this test demanded the *same token be returned* — which §3.4 itself proves impossible, since only the hash is stored. A test asserting an impossibility fails no matter how correct the implementation is; it is worse than no test, because the implementer's only way to pass it is to store recoverable plaintext.
14. Interleaved order — build a header, re-register, then use the header — succeeds. Written to fail against revision 2's rotate-always design.
14b. **Row 4 of the table, which is the one an attacker reaches.** Register once (row now has a hash), then register again with the **same `session_key`** and **no** token header ⇒ `409 token_required_for_rebind`, the stored hash is unchanged, and the first token still works. Mutate the implementation to re-mint when the pane binding matches — revision 4's withdrawn rescue rule — and this test must go red.
14c. **A restarted shim is a new session, not a rebind.** Register with `session_key = "mcp:aaa"`, then register from the *same* pane with `session_key = "mcp:bbb"` and no token ⇒ `200` and a freshly minted token, because that is row 1. This pins the reasoning that let 14b be unconditional: the per-process `session_key` (`agent_mail_server.py:26`) means the restart case never reaches row 4. If someone later makes `session_key` stable across restarts, this test and 14b conflict — and that conflict is the correct alarm, because the rescue rule would then be needed again.
14d. **An offline session keeps its hash.** Register, then age the row into `offline` (`last_seen_at` beyond `MCP_HEARTBEAT_TTL_SECONDS`, `agent_mail_service.py:39`), then register tokenless with that same `session_key` ⇒ still `409 token_required_for_rebind`, and `capability_token_hash` is unchanged. 14b cannot catch the tidy-up-on-offline mutant because its session is live; this one is the offline case, so the two together cover both sides of the retention rule.

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
| missing binding row always ⇒ `bind_pending` (revision 4's design) | **12b** |
| missing binding row never refuses, even on a claimed team launch | 12c |
| re-mint when the pane binding matches, without a token (revision 4's withdrawn rule) | **14b** |
| the hash is nulled when a session goes offline ("cleanup") | **14d** — and *not* 14b, whose session is live, so the mutant never fires there |
| inbox route authenticates but still honours the query `member_id` | 19 |
| inbox mutations applied before the auth check | **18** |
| token compared with `==` instead of `hmac.compare_digest` | — (not observable by test; enforce in review) |
| rotation leaves the old hash valid | 6 |

The third row is deliberate. A timing-safe comparison is not test-observable, so listing it as a review item is honest; claiming a test covers it would not be.

### 3.8 Blast radius, stated plainly

- `backend/mcp_shim/agent_mail_server.py` — store the token in `_state` at registration, send it as a header in `_request`/`_dispatch_request`. The shim already does exactly this for the Agent Bridge terminal token (`_bridge_request_with_token`, `:117-132`), so the pattern is in-file. Note the token is stored **once** and not replaced on later registrations (§3.4). Every tool that sends `_state["member_id"]` as its own identity keeps working unchanged, because §3.5's "derive, do not compare" accepts a value that agrees with the token. Those call sites are: `deck_send_message` (`:284`), `deck_reply` (`:316`), `deck_request_context` (`:369`), `deck_create_handoff` (`:407`) — all four as `sender_member_id` — plus `deck_ack_message` (`:341`, as `member_id` in the body) and `deck_check_inbox` (`:264`, as a `member_id` **query parameter**, which §3.5 removes from the signature rather than validating).
- `backend/app/services/agent_team_service.py` — write and commit an `agent_pane_bindings` row on both paths (`:569`, `:637`), per §3.3.
- `frontend/src/features/agent-mail/api.ts` — three write calls gain actor auth, plus the `sessionStorage` provisioning helper (§3.6).
- ~13 test call sites hitting `agent-mail/messages` across 5 test files.
- **Operator action required at deploy:** restart agent panes, then flip `mail_capability_tokens_required` to `True` (§3.4). Live: 150 `mcp` session rows, 7 currently connected.

If PR0's cost proves larger than this in practice, the fallback is to weaken the threat model explicitly in §1.5 and file the auth work separately — **not** to ship PR1 with unverifiable evidence and call it a gate.

---

## 4. PR1 — approval attribution and the distinct-approver gate

### 4.1 Schema

`github_work_items` gains five nullable columns, following `app/database.py:421-440` exactly:

```python
if work_item_columns and "ack_approver_member_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approver_member_id INTEGER"))
if work_item_columns and "ack_evidence_message_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_evidence_message_id INTEGER"))
if work_item_columns and "dispatch_nonce" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_nonce TEXT"))
```

…plus two more rungs: the epoch §3.4a requires, and the round §4.3a.1 requires. Both belong here with the others rather than in the chapters that motivate them:

```python
if work_item_columns and "ack_enforcement_epoch" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_enforcement_epoch INTEGER"))
if work_item_columns and "ack_approval_round" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approval_round INTEGER"))
```

All five nullable, so existing rows migrate silently — and a pre-upgrade row with `dispatch_nonce = NULL` cannot be acked until re-dispatched, which §4.3 rule 3 makes explicit and correct.

`ack_approval_round` records which round's approval is on file. It is **not** redundant with `approval_round_count`: the counter says which round the item is *in*, and this column says which round the evidence *came from*. The gate compares them (§4.5), which is what makes a stale approval visible instead of merely absent — the same reasoning that made `ack_enforcement_epoch` a column rather than an inference.

`mail_messages` gains `decision` (§4.3a) and `approval_round` on the same ladder:

```python
if message_columns and "approval_round" not in message_columns:
    await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN approval_round INTEGER"))
```

A column rather than a payload key, because the gate filters on it and `payload` is JSON that SQLite cannot index usefully here. The `context_request`'s round also goes in its `payload` — that is what the shim sends and what §4.3 rule 3 matches — but the *decision* row carries it as a column, so an operator reading a thread can see which round each decision belongs to.

### 4.2 The dispatch nonce

`secrets.token_hex(8)`, minted at dispatch, following `workspace.lease_token` (`github_workspace_service.py:130`) — same generator, same lifecycle shape, same purpose: bind a claim to one attempt.

Minted where `dispatched_at` is set (`github_dispatch_service.py:344`), so one nonce per dispatch attempt. Cleared or replaced at every point where the attempt's identity changes:

| Event | Site | Action |
|---|---|---|
| dispatch | `:344` | mint a fresh nonce |
| retry | `reset_for_retry:64-71` | clear nonce + the four new ack columns alongside the existing `ack_received_at = None` |
| handoff accepted | `accept_handoff:705` | clear **all five** ack fields + `last_nudge_at`; **keep the nonce** — see below |
| revision requested | `record_approval_round:672-679` | increment the round, then clear **all five** ack fields + `last_nudge_at`; **keep the nonce** (§4.3a.1) |

The nonce is a *correlation* value, not a secret — PR0 provides the authentication. It exists so that evidence from attempt N cannot satisfy attempt N+1, which no amount of authentication would prevent on its own.

**Handoff clears five fields, not two.** Revision 2 said "both ack columns," meaning the two new ones. That was an off-by-one with a consequence. `ack_received_at` already exists and `_ack_satisfied` reads it (`:905-911`):

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
| `ack_enforcement_epoch` | it describes the cleared evidence, not the item; leaving `1` behind would let a later grace-mode write inherit an "enforced" stamp |
| `ack_approval_round` | same reason: it describes evidence that no longer exists. Leaving a round number behind would make §4.5's `ack_approval_round == approval_round_count` comparison pass on cleared evidence the first time the counter happens to agree |
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
                                      #         "no_linkage", "stale_nonce", "stale_round",
                                      #         "no_leader", "no_owner", "no_decision", "rejected",
                                      #         "tokens_not_enforced", "evidence_predates_enforcement"
    approver_member_id: int | None = None
    evidence_message_id: int | None = None
    approval_round: int | None = None   # the round this evidence belongs to (§4.3a.1)
```

A `MailMessage | None` return cannot carry the distinct refusal reasons the tests below require — revision 1 asked for reasons it had no way to express. This type is the fix.

`record_ack_received` gains a `scope` parameter (the `/dispatch-status` route at `agent_teams.py:294` already loads it) and resolves slots itself via the existing `agent_team_service._slots_for_preset(db, scope.preset_id)` — do not write a new query. It then calls `_ack_evidence(db, item, preset_slots)` and stops trusting the reporter. Rules, in order:

1. Resolve the **designated leader member**: `_leader_slot(preset_slots)` → `_slot_member(db, leader.id)`. This is the *only* acceptable approver. Not "any member," not "any slot member" — the specific member bound to the leader slot. Live data justifies the strictness: 12 of 19 members have no slot at all. If either the leader slot or its member cannot be resolved, refuse `no_leader` — fail closed, never treat an unresolvable approver as satisfied.
2. Resolve the owner member via the existing `_owner_member(db, item)`. If the owner **is** the designated leader, refuse with `self_ack` immediately — this is Finding #1's exact shape and needs no evidence lookup to reject. If the owner member cannot be resolved, refuse `no_owner`.
3. Find `context_request` rows whose payload `work_item_id` equals `item.id`, sent by the owner member and addressed to the leader member. If **no** row matches the work item at all ⇒ refuse `no_linkage`. If a row matches the work item but **none** matches `item.dispatch_nonce` ⇒ refuse `stale_nonce`. If a row matches the nonce but **none** carries `approval_round == item.approval_round_count` ⇒ refuse `stale_round` (§4.3a.1) — the owner is replaying an approval from before a revision was requested. Evaluate in that order, so the three reasons stay distinguishable: `no_linkage` means "they never asked," `stale_nonce` means "they are replaying an older *attempt*," `stale_round` means "they are replaying an older *round* of this attempt." A NULL `item.dispatch_nonce` (a pre-upgrade row) can never match, so it refuses `stale_nonce` — correct, and §4.1 already states such items must be re-dispatched. A NULL payload `approval_round` likewise never matches, refusing `no_linkage` per §4.3a.1.
4. Among the matching threads, require an `answer` row whose `thread_root_id` is that `context_request`, whose `sender_member_id == leader_member.id`, **and whose `decision` column is `'approved'`** (§4.3a). Found ⇒ accept, recording `approver_member_id` and `evidence_message_id` (the **answer** row's id, not the request's — the answer is the approval). If more than one qualifies, take the earliest by `created_at`, so the recorded evidence is the approval that actually unblocked the owner. If a leader-authored answer exists but no row carries `decision = 'approved'`: refuse `rejected` when any of them carries `decision = 'rejected'`, otherwise refuse `no_decision`. If no leader-authored answer exists at all ⇒ refuse `not_designated_approver`.
5. Accepted ⇒ set `ack_received_at`, `ack_approver_member_id`, `ack_evidence_message_id`, `ack_enforcement_epoch = 1`, `ack_approval_round = item.approval_round_count`. Refused ⇒ **do not** set `ack_received_at`; return `409` from `/dispatch-status` with `reason` in the detail.
6. Before any of the above: if `mail_capability_tokens_required` is `False`, refuse `tokens_not_enforced` without evaluating or writing anything (§3.4a).

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

### 4.3a A reply is not a decision

Revision 3's rule 4 accepted **any** `answer` row authored by the leader. The third review's first blocker is that this makes the gate a reply-counter: an answer reading *"Do not proceed"* satisfies it, because nothing in the row represents a decision. Confirmed, and it is worse than hypothetical — the live DB already contains the exact rows that would have passed. Read-only query, 2026-08-05:

```
81 answer rows total, 75 authored by member 16 (the Leader)

id 82 (root 80, sender 16): "Acknowledged as a plan-review request, but not approved
    for implementation yet. The request only names `docs/e2e/branch-protection-human-
    fallback.md` and does not include a concrete plan. Please send the scoped plan..."

id 92 (root 88, sender 16): "Acknowledged, but this request is superseded by the more
    concrete #854 plan in request #89. I am not treating this stub as separate
    implementation approval."
```

Both are the Leader **explicitly refusing**, in prose, in production. Under revision 3 both are approvals. Row 92 is the sharper one: it refuses *while using the word "acknowledged,"* which is exactly the vocabulary the brief teaches (`_leader_ack_instruction:541-573` says "wait for acknowledgment," and `_nudge_leader_for_ack:933` asks the leader to "acknowledge so work can proceed"). The gate and the brief share a word that means "I read it" to the leader and "I approve" to the gate.

**Prose parsing is not a fallback.** Measured on the same 81 rows: 69 contain a negative token (`not`, `no`, `cannot`, `reject`, `without`, …), and **31 contain both a negative token and an approval token** — including genuine approvals such as id 40, *"Approved. Proceed with the scoped #843 plan: first verify there is no active duplicate branch/PR…"*. A keyword classifier would reject that approval and, tuned the other way, accept row 82. There is no threshold that separates these sets, and a safety gate must not depend on one. The decision has to be **stated as data by the approver**, not inferred from their words.

**The tool.** A new MCP tool, alongside `deck_reply` rather than replacing it:

```python
@mcp.tool()
def deck_approve_work_item(
    work_item_id: int,
    dispatch_nonce: str,
    decision: str,            # "approved" | "rejected"
    reason: str,
) -> dict:
    """Record an explicit approval decision for a dispatched work item. Only the
    designated team leader's decision counts, and it only counts for the dispatch
    attempt named by dispatch_nonce."""
```

It posts an `answer` row in the owner's `context_request` thread — the same shape §4.3 rules 3-4 already match on — with `decision` and `reason` carried as **columns**, not prose. `reason` is required and free text; it is what an operator reads in the UI and what the owner reads in the thread body. `decision` is what the gate reads, and the two are independent: a verbose approval and a terse one are equally valid, and a refusal with a long explanation is still a refusal.

**Where the decision lives.** One nullable column on `mail_messages`, via the ladder rung that already exists for this table at `app/database.py:469-472`:

```python
if message_columns and "decision" not in message_columns:
    await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN decision TEXT"))
```

Nullable, so every existing row — including rows 82 and 92 — reads `NULL`, which is neither approval nor rejection. That is the correct migration outcome: **no historical answer approves anything**, because none of them was written by an approver making a structured decision.

`decision` is constrained to `{'approved', 'rejected', NULL}` in the Pydantic schema, not by a DB constraint (this project uses no CHECK constraints; `dispatch_status`, `handoff_state`, and `kind` are all validated in Python). `MailMessageCreate` gains `decision: Optional[str] = None` and `MailMessageResponse` gains it too, so it appears in the thread view and in `deck_check_inbox` output — the owner can see they were refused, and why.

**Only the leader may set it.** `send_message` (`agent_mail_service.py:838`) rejects a non-NULL `decision` unless all of these hold, in this order:

1. `kind == "answer"` — a decision without a request is meaningless.
2. The caller is authenticated by a PR0 capability token, so `sender_member_id` is server-derived. A tokenless caller supplying `decision` is a `403`, **including in grace mode** — §3.4a's rule that grace mode accumulates no approval evidence applies to the column that carries it, not only to the work-item row that cites it.
3. The sender is the designated leader member for the thread's work item, resolved exactly as §4.3 rule 1 resolves it. A Specialist cannot write a decision even about their own thread.
4. `decision` is one of the two allowed values.

Putting the check in `send_message` rather than only in the tool matters: the tool is a convenience wrapper over the same HTTP endpoint every agent can call directly with `curl`. A guard that lives only in the shim guards nothing (§1.5's whole argument).

**The tool does not choose the thread; the server resolves it.** `deck_approve_work_item` takes a work item and a nonce, not a `thread_root_id`, so it needs one new route: `POST /agent-mail/decisions`, which resolves the `context_request` whose payload matches `(work_item_id, dispatch_nonce)` **and** whose `recipient_member_id` is the authenticated caller, then delegates to `send_message` with `kind="answer"` and the decision. Resolution is server-side on purpose:

- The leader cannot post a decision into the wrong thread by mistyping an id.
- The existing `send_message` answer guard (`:859`, "only the context request recipient can answer it") is preserved rather than bypassed — the leader *is* the recipient of the owner's request, so the guard passes for exactly the right party and fails for everyone else.
- Zero matching requests ⇒ `404` (nobody asked for this item under this nonce). More than one ⇒ `409` with both ids; do not guess. Multiple matches mean the owner opened two threads for one attempt, which is a shim bug worth surfacing rather than papering over.

#### 4.3a.1 A rejection needs a next round, and revision 4 gave it none

Revision 4 told a rejected owner to "revise the plan and ask again," and the fourth review's second blocker is that this does not work as specified. Three separate problems, all confirmed:

1. **The second request collides with my own `409`.** §4.3a resolves the thread from `(work_item_id, dispatch_nonce)`, and the nonce does *not* change on revision — only on re-dispatch (§4.2). So an owner who asks again has two `context_request` rows matching the same pair, which is precisely the "more than one ⇒ `409` with both ids; do not guess" case. The documented recovery path is unreachable through the documented tool.
2. **`record_approval_round` does not identify anything.** Measured, it is four lines: increment the counter, escalate at the cap, commit (`github_dispatch_service.py:672-679`). It does not name the active request, does not touch the ack columns, and does not know a decision exists.
3. **Approve-then-reject still permits auto-merge.** Revision 4 argued that a recorded approval should stand because the owner may already have pushed. True as far as it goes — but revision 4 then offered `revision_requested` as the leader's remedy, and `revision_requested` clears no ack columns. So the leader's stated lever does nothing to the gate, and auto-merge proceeds on the approval the leader has since withdrawn.

**Decision: decisions are scoped to an approval round.** `item.approval_round_count` already exists (`app/models/database.py:267`, default `0`) and already has a cap (`scope.max_approval_rounds`, `app/models/database.py:221`, default `3`). It becomes the round identifier:

- `deck_request_context` puts `approval_round` in the payload alongside `work_item_id` and `dispatch_nonce`, reading the item's current `approval_round_count`.
- `deck_approve_work_item` records the round it is deciding, taken from the resolved request's payload — not from the caller, who would then be able to choose it.
- **The gate considers only the current round.** §4.3 rule 3's match becomes `(work_item_id, dispatch_nonce, approval_round == item.approval_round_count)`, so the thread resolution in §4.3a is unique again: one request per round, and the `409` fires only for a genuine duplicate *within* a round, which remains a shim bug.
- `revision_requested` → `record_approval_round` increments the counter **and clears the five ack columns**, exactly as `accept_handoff` does (§4.2). The next round therefore starts with no approval, and the gate refuses `no_decision` until the leader decides again.

This makes the withdrawal implicit and total: the leader does not need a second tool to revoke, because moving the round drops the previous round's evidence by construction. And it resolves problem 3 without the retroactive-un-approval hazard revision 4 was right to avoid — the approval is not reversed, it is *superseded*, and only by an explicit act (`revision_requested`) that the leader or owner takes deliberately.

**Approve-then-reject within one round** keeps revision 4's rule: the approval stands. That case is now narrow — the leader approved and then changed their mind *without* requesting a revision — and the correct answer is still not to strand a pushed PR. The leader's lever is `revision_requested`, which now actually works.

**Who may report `revision_requested`** is blocker 5's question, answered in §3.5a. It must be the leader or the owner, not any authenticated slot: a Specialist who could increment the round could otherwise reset another item's approval at will, or drive it to `approval_rounds_exhausted` in three calls.

**A NULL `approval_round` in the payload** — from a pre-upgrade shim, or `deck_request_context` called without it — cannot match round 0 by accident. Treat NULL as "no round stated" and refuse `no_linkage`, on the same reasoning §4.3 rule 3 already applies to a NULL nonce: an item whose evidence predates the linkage requirement must be re-dispatched, not grandfathered.

**Why not a separate `approval_rounds` table.** A round is one integer per item with a cap of 3, and every question the gate asks is answerable from the counter plus the payload. A table would add a migration, a join, and a second source of truth for "which round are we in" — and the counter would still exist, because the cap reads it. Rejected on that measurement, not on taste.

**`deck_reply` is unchanged and still writes `decision = NULL`.** The leader keeps a way to say "I read this, here are my questions" without approving — which is what rows 82 and 92 were actually doing. Their author was behaving correctly; the *gate* was wrong to read them as approval.

**The brief must name the tool, and the nudge must too.** `_leader_ack_instruction` (`:541-573`) currently tells the owner to wait for "acknowledgment." It now tells the owner to wait for the leader's `deck_approve_work_item` decision, and `_nudge_leader_for_ack` (`:920-943`) asks the leader for a decision by name, passing `work_item_id` and `dispatch_nonce` (the nudge payload already carries `work_item_id` at `:939`). Wording again carries no enforcement weight — but a leader who is never told the tool exists will keep replying in prose, and the item will time out with `leader_ack_timeout`. That is a *safe* failure and an annoying one; naming the tool is how it stays rare.

**Refusal is not escalation.** A `decision = 'rejected'` answer means the leader has declined this plan. The item stays un-acked, and the existing monitor path handles it: nudge, then `leader_ack_timeout` (`:785-791`). No new `dispatch_status` value and no new escalation reason — `rejected` is an `AckEvidence.reason` returned in a `409`, not an item state. The owner's correct response is to revise the plan and ask again, which is what `revision_requested` → `record_approval_round` (`:672-679`) already models.

### 4.4 The anchor does not exist yet — PR1 must create it

There is no way to link an ack request to a work item today:

- `mail_messages` columns are `id, thread_root_id, kind, sender_member_id, sender_actor_id, recipient_member_id, subject, body_markdown, payload, request_status, created_at` — no work-item column.
- `deck_request_context` (`mcp_shim/agent_mail_server.py:349-374`) accepts `to_member_id, topic, why_needed, files_or_symbols`. No `work_item_id`.
- The work item appears in ack requests only as **prose** in `why_needed`, e.g. message 80: *"Issue #852 requires Leader acknowledgment before implementation starts."* Five such rows exist. Parsing that would be guessing.

PR1's **first** task is therefore the linkage:

1. `deck_request_context` gains optional `work_item_id: Optional[int] = None` and `dispatch_nonce: Optional[str] = None`, forwarded into the message payload. Optional keeps every existing caller working — the tool serves ordinary questions too. `deck_approve_work_item` (§4.3a) consumes the same pair from the other side, which is why both are payload keys rather than one being a column.
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
    ack_enforcement_epoch == 1                <-- NEW (§3.4a)
    ack_approval_round == approval_round_count <-- NEW (§4.3a.1)
    ack_approver_member_id is the leader      <-- NEW
    and differs from the owner's member
```

The round comparison is what makes a *withdrawn* approval fail the gate rather than merely being absent. §4.3a.1 has `record_approval_round` clear the ack columns, so in the ordinary case the approval is gone and `ack_approver_member_id is the leader` already fails. The comparison is the belt to that suspenders: if a future change to `record_approval_round` forgets the clear — the exact off-by-one that revision 2 committed with `accept_handoff` — the round mismatch still refuses. Fail closed twice on the path where the cost of failing open is a merge nobody approved.

The check reads the **persisted** columns, not a fresh mail lookup: PR0 plus §4.3 mean the columns can only have been written by a verified approval, and re-deriving at merge time would read a mail table that may have changed for unrelated reasons.

**One exception to "read the persisted columns."** The gate does *not* re-read `mail_messages.decision`, and that is safe for the same reason: `ack_approver_member_id` is only ever written by §4.3 rule 5, which only runs after rule 4 has found an `approved` row. The persisted column is a *record* of a decision check that already happened under enforcement, and `ack_enforcement_epoch` is what proves the regime it happened under. Re-reading the mail row at merge time would add nothing and would introduce a second code path that could disagree with the first.

**Why the settings check belongs in the gate.** PR0 ships with `mail_capability_tokens_required = False` so deploying it breaks nothing (§3.4). But in that mode a tokenless caller still supplies its own `sender_member_id`, so `ack_approver_member_id` is exactly as forgeable as it was before PR0. A gate reading a forgeable column is the failure this spec exists to prevent, so the gate refuses with `tokens_not_enforced` until the operator has restarted the panes and flipped the flag. The refusal names the setting, so the operator sees a configuration step rather than a mystery.

This is the one place the three PRs are coupled at runtime rather than only in sequence, and it is deliberate: it makes "PR0 deployed but not enforced" a *safe* state instead of a silently-degraded one.

**Do not route this through `_ack_satisfied`.** That function short-circuits on `if item.pr_number is not None: return True` (`:903-904`), which is correct for its actual job — once a PR exists, nudging the leader for an ack is pointless. But auto-merge only ever runs on items that **have** a `pr_number` (`github_verification_service.py:99` filters on `pr_number.is_not(None)`), so reusing `_ack_satisfied` as the merge gate would return `True` unconditionally, every time. The gate would be a no-op that reads like enforcement — the same failure mode as a silent test.

So the new condition is a **separate** predicate reading `ack_approver_member_id` directly, and `_ack_satisfied` keeps its one existing caller and its current behavior. Test 12 is the one that catches this: an item with a PR, CI-green, fresh head, and no approval must **not** merge. Written against `_ack_satisfied` it would pass while proving nothing.

Failing it routes to the existing `_fallback_to_human_merge` (`:421-432`), which sets `ready_for_review` and a note — and because that note is matched by `_HUMAN_MERGE_NOTE_PREFIXES` (`:20-25`), the new note **must** start with `"Auto-merge blocked"` so the fallback is sticky and does not re-run every poll. Revision 1 missed this; a note with any other prefix would loop.

A leader-owned code item therefore cannot auto-merge; it waits for a human. Finding #1 is closed by construction rather than by prompt discipline.

### 4.6 Operator and agent visibility

`GithubWorkItemResponse` (`schemas.py:2272-2299`) and `_work_item_response` (`agent_teams.py:196-229`) both enumerate every field by hand, so a new column is invisible until added in **both** places. All four new columns are added to both, which is what makes the gate auditable by an operator in the UI *and* by the leader through `deck_list_work_items`.

`mail_messages.decision` needs the same treatment one table over: `MailMessageResponse` enumerates its fields by hand too (`schemas.py:1877-1894`), so without the addition the decision is invisible in the thread view, in `deck_check_inbox`, and in the UI — the operator would see a gate refusing an item and an approval-looking reply, with no way to tell which reply carried the decision.

An unaudited safety gate is a claim, not a control — and this codebase's serializer style means "add the column" and "expose the column" are genuinely separate steps that a plan must both name.

### 4.7 Brief wording

The owner's brief already names the leader as "Team leader / approver" (`:428-432`). It gains one line: approval comes only from the leader calling `deck_approve_work_item` on the thread the owner opened with `work_item_id` and `dispatch_nonce`; a prose reply, however positive, is not approval; and self-approval is rejected. The leader's own brief gains the matching line, since the leader is the one who must call the tool. Wording carries no enforcement weight — §4.3 and §4.3a do.

### 4.8 Tests (all offline, no GitHub needed)

1. `deck_request_context(work_item_id=N, dispatch_nonce=X)` puts both in the payload; omitting them still works.
2. Leader-authored answer on a correctly-linked thread **with `decision = 'approved'`** ⇒ ack recorded, `ack_approver_member_id` == leader member, `ack_enforcement_epoch == 1`.
3. Owner **is** the leader (`leader_fallback` shape) ⇒ `409` `self_ack`, `ack_received_at` stays NULL.
4. Answer authored by a **non-leader** slot member ⇒ `409` `not_designated_approver`. This is blocker 3: a Specialist answering does not approve.
5. Answer authored by a member with `team_slot_id = NULL` (e.g. `juan`, member 19) ⇒ `409` `not_designated_approver`.
6. No evidence at all ⇒ `409` `no_linkage`.
7. Linkage present but `dispatch_nonce` is from a previous attempt ⇒ `409` `stale_nonce`.
8. Payload NULL or missing the key ⇒ no raise, treated as `no_linkage`.
    8b. No enabled leader slot, or a leader slot with no registered member ⇒ `409` `no_leader`, not an accepted ack.
9. A refused ack still lets the monitor nudge, then escalate `leader_ack_timeout`.
10. `reset_for_retry` clears all five columns; an ack valid before the retry is refused after it.
    10b. **Deferred retry** — `reset_for_retry` on an item that still holds a lease returns early without clearing; the monitor's second call, after release, does clear. Both halves asserted.
11. `accept_handoff` clears all five ack fields and **keeps** the nonce; the previous owner's approval does not carry to the new owner, *and* the new owner can still be acked (proving the §4.2 deadlock is avoided).
    11b. **`_ack_satisfied` is False for the new owner after a handoff.** This is blocker 4 and it needs its own assertion, because test 11 as written in revision 2 would pass while leaving `ack_received_at` set: set `dispatched_at` in the past, record an ack, hand off, then assert `_ack_satisfied(item) is False`. Against revision 2's two-column clear this fails, since `ack_received_at > dispatched_at` still holds.
    11c. After a handoff, the monitor nudges the leader for the new owner's ack and eventually escalates `leader_ack_timeout`. This is the *consequence* of 11b — the behavior an operator would actually miss — and it is why `last_nudge_at` is cleared too (`:785` branches on `is None`).
12. Auto-merge with CI-green + fresh head but no distinct approval ⇒ falls back to human merge, `auto_merged_at` stays NULL.
13. Auto-merge with CI-green + fresh head + valid distinct approval ⇒ merges.
    13b. Same item, but `mail_capability_tokens_required = False` ⇒ refuses with `tokens_not_enforced` (§4.5).
14. The fallback note starts with `"Auto-merge blocked"`, so a second poll does not re-run the fallback.
15. Replay of the live self-ack shape (`context_request` 16→16, `answer` from 16) ⇒ refused. Regression test written directly from production data.
16. All five columns appear in `GithubWorkItemResponse` for a real item, and `decision` plus `approval_round` appear in `MailMessageResponse`.

Structured decisions (§4.3a) — the negative-answer tests the third review asked for, written from production rows:

17. **Row 82 replayed.** Leader-authored answer on a correctly-linked thread, `decision = NULL`, body *"Acknowledged as a plan-review request, but not approved for implementation yet…"* ⇒ `409` `no_decision`, `ack_received_at` stays NULL. Against revision 3's rule 4 this is an accepted ack.
18. **Row 92 replayed.** Same shape, body *"Acknowledged, but this request is superseded… I am not treating this stub as separate implementation approval."* ⇒ `409` `no_decision`. Kept separate from 17 because it refuses *using the brief's own word* "acknowledged" — a keyword classifier tuned to pass row 40's approval would accept this one.
19. Leader-authored answer with `decision = 'rejected'` ⇒ `409` `rejected`, distinguishable from `no_decision` in the response detail.
20. **Row 40 replayed** — *"Approved. Proceed with the scoped #843 plan: first verify there is no active duplicate branch/PR…"* — with `decision = 'approved'` ⇒ **accepted**, despite containing "no". This is the counterpart to 17/18: it proves the gate reads the column and not the prose in the direction that would otherwise cause false refusals.
21. `deck_approve_work_item` resolves the thread from `(work_item_id, dispatch_nonce)`: correct pair ⇒ answer posted in the owner's thread with `decision` set. No matching request ⇒ `404`. Two matching requests ⇒ `409` naming both ids.
22. A **Specialist** calling `deck_approve_work_item` (or posting `decision` directly to `POST /messages`) ⇒ `403`, and no `mail_messages` row is written with a non-NULL `decision`. Assert the row state, not only the status code — a route that writes then refuses would pass a status-only assertion.
23. A **tokenless** caller supplying `decision` ⇒ `403` even with `mail_capability_tokens_required = False`. §3.4a's rule applied to the decision column.
24. `decision` outside `{'approved','rejected'}` (e.g. `'maybe'`, `'APPROVED'`) ⇒ `422`. Case is not normalized; an unrecognized value is never treated as approval.
25. `deck_reply` still works and writes `decision = NULL`; the leader can ask questions without approving, and that reply does not satisfy the gate.
26. Approve, then post `decision = 'rejected'` on the same nonce ⇒ the ack recorded by the approval **stands** (§4.3a), and the item does not become un-acked.
27. **Grace mode records nothing.** With `mail_capability_tokens_required = False`, a fully valid approval flow ⇒ `record_ack_received` refuses `tokens_not_enforced` and `ack_approver_member_id`, `ack_evidence_message_id`, `ack_enforcement_epoch` are all still NULL. Then flip the flag to `True` and re-run the ack ⇒ accepted. Proves the refusal is not merely time-shifted.
28. An item whose ack columns are populated with `ack_enforcement_epoch` NULL or `0` (hand-built fixture simulating a pre-enforcement or refactor-regressed write) ⇒ gate refuses `evidence_predates_enforcement`, even with tokens enforced and every other condition green.

Round scoping (§4.3a.1) — the rejection-recovery lifecycle revision 4 had none of:

29. **A second round's request is legal.** Round 1: `deck_request_context` with `approval_round = 1`, leader rejects (`revision_requested`). Round 2: the owner opens a *new* request with `approval_round = 2` ⇒ accepted, **no `409`**, and `deck_approve_work_item` resolves to the round-2 thread. Against revision 4 the second request is a duplicate-linkage `409`, so the documented recovery path is blocked by the spec's own guard — this is the blocker-2 test.
30. **Two requests, two rounds, no ambiguity.** With round-1 and round-2 requests both present on the item, `deck_approve_work_item(work_item_id, dispatch_nonce)` for round 2 resolves to exactly one thread. Test 21's "two matching requests ⇒ `409`" still holds *within* a round — assert both, since a fix that stops filtering by round entirely would pass one and fail the other.
31. **`revision_requested` clears and increments.** Record a valid approval for round 1, then report `revision_requested` (from the leader — §3.5a) ⇒ `approval_round_count` becomes 2, and `ack_approver_member_id`, `ack_evidence_message_id`, `ack_received_at`, `ack_enforcement_epoch`, `ack_approval_round` are **all** NULL, and `last_nudge_at` is NULL. The nonce is **unchanged** (§4.3a.1 — clearing it would deadlock the next round exactly as it would on handoff).
32. **The gate refuses after a withdrawal.** The item from 31, CI-green with a fresh head ⇒ no auto-merge, and the fallback note starts with `"Auto-merge blocked"`. This is the consequence test for 31; a clear that happened but left the gate passing would be invisible without it.
33. **Round mismatch alone refuses — the belt-and-suspenders test.** Hand-build an item with every gate condition green, valid approver columns, `ack_enforcement_epoch = 1`, but `ack_approval_round = 1` while `approval_round_count = 2` ⇒ refuses `stale_round`. This fixture is the state a *forgetful* `record_approval_round` would leave behind, so it tests the second guard independently of the first. §4.5's whole argument for having two guards rests on this test existing.
34. **Approval in the current round still merges.** The item from 31, then a valid round-2 approval ⇒ `ack_approval_round == 2 == approval_round_count`, and it merges. Proves the round check refuses staleness rather than everything.
35. An ack attempt against a **round-1** thread after the round has advanced to 2 ⇒ `409 stale_round`, distinguishable in the response detail from `stale_nonce` and `no_linkage`. All three refusals exist because they need different operator responses: re-dispatch, wait, or open a new request.
36. `approval_round` NULL in a request's payload (a pre-upgrade or hand-posted row) ⇒ treated as `no_linkage`, not as round 0 and not as "any round." Fail closed on an unstated round.
37. **The cap still escalates.** Reject `max_approval_rounds` times (default 3, `app/models/database.py:221`) ⇒ the item escalates and no further round is opened. Round scoping must not turn a bounded loop into an unbounded one.

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
| accept any leader-authored answer, ignoring `decision` (revision 3's bug) | **17, 18** |
| treat `decision = 'rejected'` as merely absent | 19 |
| classify approval from body text instead of the column | **17, 20** |
| normalize or coerce `decision` (`.lower()`, truthiness) so `'maybe'` passes | 24 |
| allow any authenticated member to write `decision` | 22 |
| enforce the leader-only decision check in the shim only, not in `send_message` | 22 |
| allow a tokenless caller to write `decision` in grace mode | 23 |
| write approver columns in grace mode (revision 3's behavior) | **27** |
| trust ack columns with a NULL/`0` epoch | 28 |
| let a later `rejected` revoke a recorded approval | 26 |
| one request per item regardless of round (revision 4's `409`) | **29** |
| stop filtering linkage by round at all | 30 |
| `revision_requested` increments the round but clears nothing (revision 4) | **31, 32** |
| `revision_requested` clears the ack columns but not `ack_approval_round` | 33 |
| `revision_requested` also clears the nonce | 31 (the next round's request cannot link) |
| gate compares only the columns, not the round | **33** |
| gate compares the round but treats NULL `ack_approval_round` as matching | 33, 36 |
| round scoping bypasses `max_approval_rounds` | **37** |

Tests 17 and 18 are the pair to write **first**. They are the only two written from rows that exist in production today, and revision 3's design passes both. A design change whose regression test is drawn from real refusals is the strongest evidence available here that the new guard bites.

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

All three are avoided by never putting a token in the pane's environment. Instead, configure the **workspace worktree**, which is per-dispatch state Deck already provisions and controls:

```
# always, for every leased worktree:
git -C <workspace> config extensions.worktreeConfig true
git -C <workspace> config --worktree user.name  "Specialist (Deck agent)"
git -C <workspace> config --worktree user.email "specialist+slot6@claude-deck.local"

# ONLY when App auth is configured for this repo — see §5.5.6:
git -C <workspace> config --worktree credential.https://github.com.useHttpPath true
git -C <workspace> config --worktree credential.https://github.com.helper ""
git -C <workspace> config --worktree --add credential.https://github.com.helper "<deck helper>"
```

The split in that block is load-bearing, not cosmetic. The `credential.*` lines are written **only** when the installation lookup for this repo succeeded at lease time; when it did not, the worktree gets the identity lines and **nothing else**. §5.5.6 gives the measurement behind that rule — the empty-then-add pattern deliberately evicts the human's ambient helper, so configuring a helper that cannot mint a token leaves git with no credential source at all rather than falling back to the previous one.

This is weaker than "the pane never holds a token," which revision 3 claimed and this revision retracts. Git receives the helper's plaintext password on every push, and the agent can run `git credential fill` itself. What §5.4 actually delivers is stated in §8, criterion 10: short-lived, repository-scoped, not persisted to disk, and not inherited by the pane's environment.

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

### 5.5 The helper endpoint, and who creates the PR

Revision 3 decided two things here. One holds; the other was **measured false** by the third review and I reproduced the measurement.

#### 5.5.1 `gh` does not read git's credential helper for API auth

Revision 3's claim — *"gh reads git's credential helper when `GH_TOKEN` is unset"* — is wrong. It confused the two directions in which `gh` and git talk to each other. Measured in an isolated probe (gh 2.96.0, git 2.43.0, a throwaway `GH_CONFIG_DIR`, a logging fake helper, and a fake token so nothing real could be used):

```
TEST A  git credential fill              -> helper INVOKED   (IN: path=someowner/somerepo.git)
TEST B  gh api /user                     -> "please run: gh auth login";  helper.log 0 lines
TEST C  gh pr create --dry-run           -> same;                          helper.log 0 lines
TEST D  gh auth git-credential get       -> gh acting AS git's helper (the reverse direction)
TEST E  git push                         -> helper INVOKED (get, then erase)
```

Git consumes the helper. `gh`'s **API** calls do not: with no `GH_TOKEN` and no `gh auth login`, `gh` refuses before it ever consults git's credential config, and the helper log stays empty. TEST D is what revision 3 mistook for evidence — `gh auth git-credential` is `gh` *serving* as a helper **to** git, not `gh` *reading* one.

So a bot-authored PR via `gh pr create` in the pane requires `GH_TOKEN` in the pane — which is exactly the delivery revision 3 removed, with all three of §5.4's measured problems back.

#### 5.5.2 Decision: Deck creates the PR

The agent pushes the branch; **Deck opens the PR** with the installation token it already mints:

```
agent (in the workspace):  git push -u origin deck/specialist/issue-827
                           -> helper supplies the installation token, per 5.5.6
agent:                     deck_report_dispatch_status(status="pr_ready", lease_token=..., head_ref=...)
Deck:                      POST /repos/{owner}/{repo}/pulls  (installation token)
                           -> PR author is claude-deck-bot[bot]
```

Why this is better than the alternative, not merely forced by it:

- **The author identity is now structural.** Revision 3's design *asked* the agent to create the PR with a bot credential and then had §5.6 verify after the fact that the author really was the bot. Deck calling the endpoint itself makes the author a property of the caller. There is no report to check because there is no reporter.
- **`pr_number` stops being agent-supplied.** Deck learns it from its own API response, which retires the entire class of defect §5.6 was written to catch (a wrong or hostile number pointing at a stranger's PR).
- **One credential path, not two.** The pane needs git push only. `gh` is not required in the pane at all for the dispatch flow.

`GithubClient` gains **two** methods beside the existing `get_pull` (`github_client.py:98`) and `merge_pull` (`:165`), using the same `_headers()`/`_client()` shape:

- `create_pull(owner, repo, *, title, head, base, body, draft)` — the write.
- `list_pulls_for_head(owner, repo, *, head, base=None, state="all")` — a read, required by §5.5.4's reconciliation and absent today.

The client's module docstring names its writers explicitly (`merge_pull`, `mark_pull_ready_for_review`) and warns the module is "NOT entirely" read-only. `create_pull` makes three writers and the docstring must be updated to say so, since that note is how a reader learns this module can mutate GitHub — and it is the note an operator relies on when deciding whether a read-only token is sufficient.

**The reported status changes shape.** `pr_opened` carried a `pr_number` the agent chose. It is replaced for this flow by `pr_ready`, carrying `head_ref` — the branch the agent pushed. Deck then:

1. Validates `head_ref` against the expected `deck/<slot>/issue-<n>` pattern for the item. A mismatch is a `409`; Deck does not open a PR from a branch it did not ask for.
2. Confirms the ref exists on the remote (`GET /repos/{o}/{r}/git/ref/heads/{ref}`), so a typo fails as "branch not found" rather than as an opaque `422` from the pulls endpoint.
3. **Reconciles before creating** — §5.5.4. A PR may already exist for this head even though `item.pr_number` is NULL.
4. Creates the PR with the title, body and draft flag from §5.5.5 — which are Deck's to compose, not the agent's.
5. Records `pr_number` from the response and proceeds exactly as `report_pr_opened` does today (`github_verification_service.py:44-86`): `verifying` for code items, `awaiting_human_review` for design items, `last_verified_sha = None`.

**`pr_opened` is not removed.** It stays for the App-unconfigured path, where there is no installation token and the agent must open its own PR with the ambient credential — today's behavior, which §5.3 promises not to break. So the two paths are: App configured ⇒ `pr_ready` ⇒ Deck creates; App not configured ⇒ `pr_opened` ⇒ as today, including §5.6's now-reduced verification. **This is not a new `dispatch_status` value** — `pr_ready` is a `DispatchStatusReport.status` string handled in the `/dispatch-status` route's branch chain (`agent_teams.py:286-340`), the same kind of value as `triaging` and `handoff_accepted`. The item's own `dispatch_status` column still moves only between existing values.

**Idempotency.** A retried `pr_ready` for an item that already has a `pr_number` must not open a second PR: return the existing number. GitHub itself returns `422` for a duplicate head/base pair, but relying on that means depending on an error path for correctness, and the agent's retry is an ordinary event (a dropped response, a nudge). Revision 4 stopped there, and §5.5.4 explains why that is not enough.

**What the brief says.** The brief's PR line (`github_dispatch_service.py:448-450`) changes from "when you open a PR, report `pr_opened` with the PR number" to "push your branch, then report `pr_ready` with `head_ref`; Deck opens the PR and composes its title and body."

The `[Slot]` prefix and trailers stay the agent's job **for commits** — they are commit content. They are *not* the agent's job for the PR title, which Deck composes per §5.5.5. Revision 4's wording ("stay the agent's job") did not draw that line and so contradicted its own step 3; the brief must not repeat the ambiguity, because an agent told it owns the title will put one in `status_note` and expect it to be used. §5.4's per-worktree `user.name`/`user.email` still supply the commit identity, which is the part of §5.1's table that was never in question.

#### 5.5.4 Idempotency by reconciliation, because `item.pr_number` is not the record

Revision 4's rule was "if `item.pr_number` is set, return it." The fourth review is right that this is not crash-safe, and the window is not small.

**The window.** `create_pull` is a network call; writing `pr_number` is a local commit. Between them the PR exists on GitHub and Deck has no record of it. Anything that ends the process there — the backend restarting, the `POST` timing out after GitHub committed, an `httpx` read timeout on a request that succeeded server-side — leaves `item.pr_number` NULL with a live PR on the branch. The agent's next `pr_ready` retry then reads NULL, and revision 4's rule says *create*.

What happens next depends on GitHub, and neither outcome is acceptable:

- **`422 Validation Failed`** for a duplicate head/base — the common case. Revision 4 has no handler for it, so the report fails and the item never learns its own PR number. The item then sits `dispatched` with a real, open, invisible-to-Deck PR until it escalates on the monitor's timeout. A human investigating finds a PR that Deck denies exists.
- **A second PR**, if base or head differ by so much as a ref-name normalization. Two PRs for one issue, and Deck tracks the wrong one.

`item.pr_number` is Deck's *cache* of a fact that lives on GitHub. Using a cache as the idempotency key means a crash between the fact and the cache is unrecoverable. The fix is to ask the source.

**Reconcile by head/base, before creating and after failing.** `GithubClient` gains one read method:

```python
async def list_pulls_for_head(self, owner: str, repo: str, *, head: str, base: str | None = None,
                              state: str = "all") -> list[dict]:
    # GET /repos/{owner}/{repo}/pulls?head={owner}:{head}&base={base}&state=all
```

This does not exist today — measured: the client has `get_pull` (`github_client.py:98`) and no by-head or list-pulls method at all (`:36-165`), so revision 4's "reconcile" had nothing to reconcile with. The `head` parameter must be qualified `owner:branch`; unqualified it silently matches nothing, which would make the reconciliation a no-op that always says "no PR exists" — a failure mode indistinguishable from the bug it fixes. `state=all` matters too: a closed PR on the same head still blocks creation with `422`, so a reconciliation that only looks at open PRs re-enters the same dead end.

The `pr_ready` handler becomes:

| Step | Action | On match |
|---|---|---|
| 1 | `item.pr_number` set? | return it — the cheap path, no network call |
| 2 | `list_pulls_for_head(head=f"{owner}:{head_ref}", base=scope base)` | adopt the single match: record its number, run §5.6's checks against it, continue as if Deck had just created it |
| 3 | more than one match | refuse: `409`, `status_note` naming every number found. Deck does not guess which PR is the item's. |
| 4 | no match ⇒ `create_pull` | record `pr_number` |
| 5 | `create_pull` raises timeout **or** returns `422` | re-run step 2 **once**. A match means the create actually landed (or a concurrent one did) ⇒ adopt it. Still nothing ⇒ refuse and leave the item dispatched for the monitor. |

Step 5 is the crash-safety half: the same reconciliation runs *after* an ambiguous failure, so "the request timed out but GitHub committed" converges on the next attempt instead of diverging. Step 2 is the restart half. Both are the same call, which is why this is one method and not a special case per failure mode.

**Adoption re-runs §5.6's checks, and that is not redundant.** A PR found by head/base was not necessarily created by Deck — an agent could have opened one by hand. So an adopted PR goes through the repository and head-branch checks (§5.6) before its number is recorded, and on an `app`-mode repo through the author check too. Adoption is not trust; it is discovery followed by the same verification a report gets.

**Serialization: one item at a time.** Two concurrent `pr_ready` reports for one item can both pass step 1 and both reach `create_pull`. Deck already has the right lock for this and it needs no new mechanism: the **workspace lease token**. §3.5a requires the current lease token on `pr_ready`, and a lease is by construction exclusive to one attempt on one item (`github_workspace_service.py:127-136`). Two concurrent reports carrying the *same* token are the same agent retrying, which steps 1–5 already handle; a report carrying a stale token is refused with `409` before any GitHub call. So the exclusion is a consequence of §3.5a's authorization rule rather than an added lock.

That leaves one genuine race — the same agent's two in-flight retries with the same valid token. An `asyncio.Lock` keyed on `item.id`, held across steps 1–5, closes it. Per-item, not global: a global lock would serialize PR creation across every repo behind one network round trip, the same mistake §5.3 avoided for token minting. This is single-process only, which is correct here because Deck is a single uvicorn process (measured: PID 2206652, one worker) — and if that ever changes, the reconciliation in steps 2 and 5 is what keeps the outcome correct without the lock. The lock is an optimization to avoid a wasted `422`; the reconciliation is the correctness argument.

**Tests (offline, mocked client) in §5.8:**

38. `pr_ready` with `item.pr_number` already set ⇒ returns it, and `create_pull` is **never called**. Assert the mock, not the response.
39. `pr_number` NULL, one existing PR on the head ⇒ adopted, `create_pull` never called, `pr_number` recorded, and the item advances (`verifying` for code).
40. `pr_number` NULL, **two** PRs on the head ⇒ `409`, `pr_number` stays NULL, both numbers appear in `status_note`.
41. `pr_number` NULL, no PR ⇒ `create_pull` called exactly once, number recorded.
42. **The crash window.** `create_pull` raises a timeout, and the reconciliation call that follows returns a PR ⇒ that PR is adopted, `create_pull` is **not** retried, and the item advances. This is the blocker-7 test.
43. `create_pull` returns `422` and reconciliation finds the PR ⇒ adopted. Same path, different trigger — an implementation can easily handle one and not the other.
44. `create_pull` raises a timeout and reconciliation finds **nothing** ⇒ `409`, `pr_number` NULL, `dispatch_status` still `dispatched` (not escalated — the monitor owns that decision).
45. An adopted PR whose `head.repo.full_name` is a different repo ⇒ refused by §5.6's check, `pr_number` NULL. Adoption must not bypass verification.
46. Reconciliation is called with a **qualified** head (`owner:branch`), a **normalized** base (`master`, from a scope whose `base_ref` is `origin/master`), and `state="all"`. Assert the call arguments; all three mistakes here silently produce "no match."

| Mutant | Test that must fail |
|---|---|
| idempotency keyed only on `item.pr_number` (revision 4) | **42, 43** |
| reconciliation before create, but not after a failure | **42, 43** |
| `422` treated as a hard error with no reconciliation | 43 |
| adopted PR skips §5.6's checks | **45** |
| head passed unqualified, `state="open"`, or `base` passed as the raw refspec | **46** — and 39, which then finds nothing and creates a duplicate |
| multiple matches ⇒ pick the lowest number | 40 |
| lock global instead of per-item | — (not observable by test; review item, same as §3.7's `compare_digest` row) |

#### 5.5.5 Title, body, and the draft flag are Deck's, and design PRs are not drafts

Revision 4 left this underspecified in a way that cannot be implemented: step 3 said "creates the PR as a draft, with the `[Slot]` title prefix and body from §5.1," while the brief change said "the `[Slot]` prefix and trailers stay the agent's job" — and the report carries only `head_ref`. Deck cannot apply a prefix to a title it was never sent. The fourth review is right, and the draft half is worse than underspecified.

**Deck composes both, from data it already holds.** The item row has everything needed:

| Field | Value |
|---|---|
| title | `[<slot display_name>] <item.issue_title> (#<item.issue_number>)` |
| body | `Closes #<issue_number>`, then the issue title, then a Deck provenance block: work item id, owner slot, dispatch nonce (§4.2), and `head_ref`. |
| base | `scope.base_ref` |
| head | the validated `head_ref` |
| draft | **`item.issue_type != "design"`** |

The `[Slot]` prefix stays a *commit* convention for the agent (§5.1's table is about commit trailers and authorship, which per-worktree `user.name` supplies) and becomes a *PR title* convention for Deck. Those were conflated in revision 4. Deterministic templates also make §5.5.4's reconciliation cheaper to reason about: an adopted PR's title need not match, because identity comes from head/base, not from text.

**Why design PRs are not drafts.** Measured, and this is the part revision 4 got actively wrong:

- A **draft PR cannot be approved or merged** on GitHub. Reviewers can comment, but the review-approval flow is unavailable until it is marked ready.
- `report_pr_opened` sends a design item straight to `awaiting_human_review` and notifies the team (`github_verification_service.py:67-82`) — the notification says *"is ready for human review."*
- The only caller of `mark_pull_ready_for_review` is `_promote_verified_item` (`github_verification_service.py:375+`, draft branch at `:384-385`), and `_process_review_item` returns early for design items (`:219+`, `if item.issue_type == "design"`). **Design items never reach the promotion path.**

So under revision 4 a design PR would be created as a draft, announced as ready for human review, and then never marked ready by anything — a permanent draft awaiting an approval GitHub will not accept. The human's only recourse is to click "Ready for review" themselves, on a PR Deck told them was ready.

`draft = item.issue_type != "design"` fixes it at the one place the distinction is known, using the same field `report_pr_opened` already branches on. Code PRs stay drafts because CI verification runs before a human should look, and the existing promotion path marks them ready — so for code items the draft state has an owner, and for design items it does not.

**Tests in §5.8:**

47. `pr_ready` on a **design** item ⇒ `create_pull` called with `draft=False`, item lands `awaiting_human_review`, and the team notification is sent. This is the blocker-8 test.
48. `pr_ready` on a **code** item ⇒ `create_pull` called with `draft=True`, item lands `verifying`.
49. Title and body are asserted verbatim against the template, including `Closes #<n>` and the dispatch nonce in the body.
    49b. **`base` is normalized.** A scope with `base_ref = "origin/master"` (the live value) ⇒ `create_pull` receives `base="master"`. A scope left at the column default `origin/HEAD` ⇒ the default branch is resolved from the repository rather than a literal `HEAD` being sent. Two cases, because an implementation that only strips the prefix passes the first and fails the second.
50. The agent's report is `{head_ref, lease_token}` only — a `title` or `body` field in the payload is ignored or rejected, not used. A caller-supplied PR body is an unaudited channel into a human-facing artifact.

| Mutant | Test that must fail |
|---|---|
| `draft=True` unconditionally (revision 4) | **47** |
| `draft=False` unconditionally | 48 |
| draft keyed on `merge_policy` instead of `issue_type` | 47 (a design item under `merge_policy=auto`) |
| title taken from the report payload | 49, 50 |
| `Closes #<n>` omitted | 49 |
| `scope.base_ref` sent to GitHub unnormalized | **49b** — and 46, whose base filter then matches nothing |
| prefix stripped but `origin/HEAD` sent as a literal `HEAD` | **49b** |

#### 5.5.6 The helper endpoint

The credential helper survives intact: it exists for `git push`, which TEST E confirms does consume it. `POST /api/v1/agent-teams/git-credential` on the existing loopback-only backend:

| Aspect | Decision |
|---|---|
| Request | `{workspace_token, protocol, host, path}` — the last three passed straight through from git's stdin |
| Auth | `workspace_token` = the workspace's existing `lease_token` (`github_workspaces.lease_token`, `github_workspace_service.py:130`). No new secret: the lease already identifies one dispatch's exclusive hold on one checkout, which is exactly the authorization question. |
| Authorization | the lease's `scope` must own `path`. A helper asking for a repo the lease does not cover is a `403`, logged with both repos. |
| Response | `{username: "x-access-token", password: <installation token>}`, minted per §5.3 for that repo only |
| Refusals | lease released or expired ⇒ `403`; `path` absent ⇒ `400`; App not configured ⇒ `501`, and **no helper is configured in the first place** — see below |

The helper is installed **into the workspace config, not the pane**, so it applies identically to spawn and reuse — the whole point of §5.4. The `lease_token` reaches the helper through the config line itself (`--worktree --add ... "deck-credential-helper --lease <token>"`), which lives in `.git/worktrees/<name>/config.worktree`: outside the working tree, uncommittable, and already proven not to leak into `git status`.

**There is no fallback to the ambient credential, and revision 3 was wrong to promise one.** The third review flagged this and the measurement confirms it. §5.4's recipe deliberately **empties** the helper list before adding Deck's:

```
git config --worktree credential.https://github.com.helper ""      <- wipes the ambient helper
git config --worktree --add credential.https://github.com.helper "<deck helper>"
```

That empty string is what makes Deck's helper win over the user's real global helper (measured: `credential.https://github.com.helper = !/usr/bin/gh auth git-credential` in their `~/.gitconfig`). But it also means the ambient helper is **no longer in the list** for git to fall back to. With the empty-then-add pattern in place and Deck's helper returning nothing:

```
fatal: could not read Username for 'https://github.com/someowner/somerepo.git':
       No such device or address
```

Git does not resume asking the wiped-out helper. A `501` therefore does not degrade to today's behavior — it produces a hard push failure with a message that points nowhere near the actual cause. The plan must not describe `501` as graceful.

**The fix is to not configure the helper at all when App auth is unavailable.** The decision belongs at lease time, not at credential time:

| At lease time | Worktree config written | Push uses |
|---|---|---|
| App auth configured for this repo (id + key present, installation resolves) | identity + `useHttpPath` + empty-then-add Deck helper | Deck's installation token |
| App auth **not** configured, or the installation lookup returns `404` | identity **only** — no `credential.*` lines whatsoever | the ambient helper, untouched — today's behavior |
| installation lookup fails **transiently** (timeout, `5xx`, `403` rate limit) | **nothing is written and the dispatch does not proceed** — see §5.6a | — |

The first two rows write identity, because per-worktree `user.name`/`user.email` need no token and are worth having either way. Only the credential lines are conditional. The `501` response stays in the endpoint as a defensive answer to a stale config line (a helper left behind by a config the operator edited, or a race with a settings change), but it is no longer part of any expected flow, and its message says so: *"Deck App auth is not configured; this worktree should not have a Deck credential helper."*

This is the same principle as §3.4a one layer down: a degraded mode that *looks* like a fallback but silently changes the failure surface is worse than a mode that never engages. Configure the helper only when it can answer.

The third row is new in revision 5 and is the subject of §5.6a. Revision 4 folded transient failures into row 2 by writing "the installation lookup returns `404`" and leaving every other failure unstated — which in practice means an implementer's `try/except` lands on row 2 and a timeout silently selects the ambient credential.

**When it is applied, and re-applied.** Identity is a function of the *current* owner, so it is written at lease time and rewritten whenever the owner changes:

| Event | Action |
|---|---|
| workspace leased for a dispatch | write identity + helper config for the owner slot |
| `accept_handoff` | rewrite identity for the new owner slot — §4.2 already clears ack state here; this is the same event |
| workspace released | remove the helper line and the identity, so an unleased checkout has no agent identity and no path to a token |

Handoff is the case revision 2 had no answer for. Without the rewrite, commits made after a handoff carry the *previous* owner's identity — attribution that is wrong in exactly the way this spec exists to fix.

### 5.6 Verify the PR, on the path that still reports one

`report_pr_opened` (`github_verification_service.py:44-86`) makes **no** GitHub call. It accepts `pr_number` and records it. So an agent can report any number — including a PR in another repo, or someone else's — and Deck will thereafter verify CI and potentially auto-merge *that* PR. With auto-merge enabled, that is the shortest path from a wrong report to a merged stranger's code.

**§5.5.2 closes this for the App-configured path by construction**, which is the better fix: Deck creates the PR and reads `pr_number` from its own API response, so there is no report to verify. Revision 3 needed all three checks below because it had the agent create the PR and then audited the claim afterwards.

The verification is still required, for two remaining cases:

1. **App auth not configured.** `pr_opened` survives for that path (§5.5.2), the agent still supplies a number, and it still must not be believed.
2. **Defense in depth on the new path.** Deck should confirm the PR it just created is the one it thinks it created, because the alternative is trusting that nothing between the request and the response changed.

| Check | Refuse if | Applies to |
|---|---|---|
| repository | `head.repo.full_name` != the scope's `owner/repo` | both paths |
| head branch | `head.ref` does not match the expected `deck/<slot>/issue-<n>` pattern for this item | both paths |
| author | `user.login` != the configured bot login | `pr_opened` only, and only when `github_app_bot_login` is set |

The author check is the one that shrinks. On the `pr_ready` path Deck *is* the author, so checking it verifies only that GitHub attributed a PR to the credential that created it — a tautology.

**Revision 4 then wrote a false sentence here, and the fourth review is right to call the section contradictory.** It said: *"On the `pr_opened` path App auth is by definition unconfigured, so `github_app_bot_login` is empty."* Both halves are wrong, and they are wrong in the direction that disables a security check.

- `github_app_bot_login` is a **global setting** (`config.py`, §5.3). Nothing links its value to whether *this repository* has a resolvable installation. An operator who configures App auth at all has it set, for every repo.
- App auth is configured or not **per repository**, because the installation is resolved per repository (§5.3, and this is exactly why revision 2's single `github_app_installation_id` was removed). A `404` on `tizonia/tizonia-openmax-il` says nothing about `adrirubio/claude-deck`.

So the two facts the sentence conflated are independent, and the case revision 4 declared impossible — `pr_opened` arriving while `github_app_bot_login` is set — is the *normal* case for any repo the App is not installed on. Under revision 4's reasoning an implementer would skip the author check there, or worse, treat a set `github_app_bot_login` as proof the PR should have come from `pr_ready` and refuse a legitimate report.

Stated correctly: **the author check applies on the `pr_opened` path whenever `github_app_bot_login` is set, and it must compare against the right expectation for that repo.** For a repo with no App installation, the PR is authored by the human's ambient credential, so a bot-login mismatch is *expected* and must not refuse. The check therefore keys on the repo's auth mode, not on the global setting:

| Repo auth mode (§5.6a) | `pr_opened` author check |
|---|---|
| `app` | require `user.login == github_app_bot_login`. An `app`-mode repo should be using `pr_ready`; a `pr_opened` report authored by anyone else means something is wrong, and refusing is right. |
| `ambient` | **skipped.** There is no bot; the author is whoever the ambient credential is. Refusing here would break the path §5.3 promises not to break. |

That table is only writable because a per-repo auth mode exists to key on. It did not in revision 4 — which is why the sentence had to invent a relationship between a global setting and a per-repo condition.

A refusal is a `409` and leaves `pr_number` unset, so the item stays dispatched and the existing monitor handles it.

`report_pr_opened` currently takes no `client` parameter and never touches the network; adding one changes its signature and every existing test that calls it. The plan must name that. The new `pr_ready` handler needs the client anyway, so both live behind one signature change rather than two.

**`pr_opened` is not the only way an agent sets `pr_number`, and revision 3 missed the other one.** Found while checking the route's branch chain for §5.5.2:

```python
# agent_teams.py:326-331 — the in_progress branch
elif report.status == "in_progress":
    now = datetime.utcnow()
    item.last_nudge_at = None
    if report.pr_number is not None:
        item.pr_number = report.pr_number      # <-- no verification, no service call
    item.updated_at = now
    await db.commit()
```

This bypasses `report_pr_opened` entirely, so **every check in the table above is skipped** — including on the App-configured path, where §5.5.2's "there is no report to verify" would otherwise hold. It also silences the leader-ack gate as a side effect, because `_ack_satisfied` returns `True` as soon as `pr_number` is non-NULL (`:903-904`). One `in_progress` report with a `pr_number` therefore both plants an unverified PR and satisfies the ack.

Two candidate fixes, and the second is the one to take:

1. Route `in_progress`'s `pr_number` through the same verification. Rejected: it makes a progress ping a PR-registration event, which is the conflation that created the hole.
2. **`in_progress` stops writing `pr_number` at all.** It keeps clearing `last_nudge_at` — its actual job, liveness. `pr_number` is set only by `report_pr_opened` (verified) or by Deck's own `create_pull` response (§5.5.2). The field is dropped from the report's handling, not from `DispatchStatusReport`, since `pr_opened` still needs it.

The brief never asks an agent to send `pr_number` with `in_progress`, so this removes a capability nothing documented uses. §5.8's test 29b asserts it.

### 5.6a The auth mode is per repository, and a lookup failure is not an answer

Two things the fourth review asked for, and both are needed for the same reason: several decisions in §5.4, §5.5.2 and §5.6 branch on "is App auth configured *here*," and revision 4 answered that question by re-running a network call and interpreting its failure inline. A network failure is not a configuration fact.

**The mode, persisted on the scope.** `team_github_scopes` gains one column, on the existing ladder (`app/database.py:384-417`):

```python
if scope_columns and "github_auth_mode" not in scope_columns:
    await conn.execute(
        text("ALTER TABLE team_github_scopes ADD COLUMN github_auth_mode VARCHAR DEFAULT 'unknown' NOT NULL")
    )
```

Three values, and the default is deliberately the one that means *no decision yet*:

| Value | Meaning | Set by |
|---|---|---|
| `unknown` | never successfully resolved | the migration default, and every pre-upgrade row |
| `app` | the App has an installation on this repo | a successful `GET /repos/{o}/{r}/installation` |
| `ambient` | the App is definitively **not** installed on this repo | a `404` from that call, or `github_app_id` / `github_app_private_key_path` empty |

The scope is the right owner because it already carries `repo_owner` / `repo_name` (`app/models/database.py:215-216`) and its unique constraint is `(preset_id, repo_owner, repo_name)` (`:235-237`) — one row per preset per repo, which is exactly the granularity of an installation question. Putting the mode in `config.py` would repeat revision 2's `github_app_installation_id` mistake in a new place: a global answer to a per-repo question.

`unknown` is not a third behaviour. It means *resolve now* — and the resolution's outcome is what §5.4's table branches on. Once a repo resolves, the stored mode is what later reads use, so a transient failure cannot silently reclassify a repo that resolved fine an hour ago.

**Transient failures fail closed.** The classification is by *outcome*, not by exception type at the call site:

| Lookup outcome | Mode written | Dispatch |
|---|---|---|
| `200` | `app` | proceeds with the Deck helper |
| `404` | `ambient` | proceeds with the ambient credential (today's behavior) |
| `401` / `403` on the **App JWT** (bad key, revoked App) | **unchanged** | refuses — this is a misconfiguration, not an answer about the repo |
| `403` rate limit, `5xx`, timeout, DNS, connection error | **unchanged** | refuses |

The last two rows are the fix. Revision 4's text named only `404`, so any implementation with a `try/except httpx.HTTPError` around the lookup would treat a timeout as "not installed" and configure the worktree for the ambient credential — on a repo whose whole point is that Deck's bot must be the author. The push would succeed, the PR would be authored by the human, and §5.6's author check would either pass (mode read as `ambient`) or refuse *after* the work was done. A rate limit is the most likely trigger, and rate limits arrive precisely when the dispatch loop is busiest.

Refusing looks like the rest of the fail-closed family: a `pending_reason` of `queued_auth_mode_unresolved` with the repo and the underlying error in `status_note`, the workspace lease **released**, and the item left queued for the next poll. **No new `dispatch_status` value** — same shape as `queued_ambiguous_sessions` (`github_dispatch_service.py:272`) and `queued_no_workspace` (`:281`).

Releasing the lease is safe here and *not* the mistake §5.7 dissects: this refusal happens on a worktree, so the released row is re-acquirable and a later attempt can succeed once the lookup works. §5.7's case was different — there the row that came back was the *primary*, and releasing it guaranteed re-selecting the same row forever.

**Where the resolution happens: once per dispatch, at lease time.** Not in the credential helper. The helper runs per git command (§5.4, measured) and must be fast and predictable; a helper that resolves an installation would fail a push on a rate limit that the dispatch already handled. The helper mints from a *known* installation id and returns `501` only for the stale-config case §5.5.6 describes.

**A stale `app` mode is a visible refusal, not a silent fallback.** If the App is uninstalled from a repo after it resolved, the stored mode stays `app`, the helper's mint fails, and the push fails with Deck's helper returning nothing — a hard failure by §5.5.6's measurement. That is the correct outcome and the reason it is stated: the alternative, re-resolving on every mint and downgrading to `ambient` on a `404`, would let an uninstall silently change PR authorship mid-dispatch. An operator re-resolves by clearing the mode to `unknown` (a settings action, or simply re-saving the scope).

**Tests (offline, mocked client):**

30. Lookup returns `200` ⇒ mode `app`, worktree gets identity **and** the three `credential.*` lines.
31. Lookup returns `404` ⇒ mode `ambient`, worktree gets identity and **no** `credential.*` line. Assert on the absence, by reading `config.worktree`.
32. **Lookup times out ⇒ mode is unchanged (`unknown`), NO worktree config is written at all, `pending_reason == "queued_auth_mode_unresolved"`, the lease is released, and `dispatch_status` is a pre-existing value.** This is the blocker-6 test.
33. Same for `500` and for a `403` rate-limit response — three separate cases, because an implementation can easily catch one and not the others.
34. A repo already stored as `app` whose lookup then times out ⇒ **no** lookup-driven change of mode, and the dispatch proceeds using the stored mode. Distinguishes "fail closed on an unresolved repo" from "re-resolve every time," which are different bugs.
35. `github_app_id` empty ⇒ mode `ambient` with **no** network call at all. Assert the mock was never invoked; a spurious call here would burn rate limit on every dispatch for operators who never configured the App.
36. `pr_opened` on an `ambient` repo with `github_app_bot_login` set ⇒ accepted, author check skipped (§5.6). This is the false-sentence test: revision 4's reasoning would refuse it or skip for the wrong reason.
37. `pr_opened` on an `app` repo with a non-bot author ⇒ `409`, `pr_number` unset.

| Mutant | Test that must fail |
|---|---|
| every lookup exception treated as `404` ⇒ `ambient` | **32, 33** |
| mode re-resolved on each use instead of read from the scope | 34 |
| mode stored globally in `config.py` instead of per scope | 36 (two scopes, different modes, one setting cannot serve both) |
| the lookup runs even with `github_app_id` empty | 35 |
| author check keyed on `github_app_bot_login` being set rather than on the repo's mode | **36** |
| worktree config written before the mode resolves | 32 (asserts the config file is absent, not just the refusal) |

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

**Decision: a primary workspace is never leased for dispatch.** The check moves earlier than revision 4 put it — into the selection query rather than into a refusal after selection:

- No identity config, no credential helper, no `GH_TOKEN` — the human's checkout is never modified by PR2, at all.
- **No new `dispatch_status` value and no new `pending_reason`.** When no dispatchable non-primary workspace exists, the existing `queued_no_workspace` path already says the right thing; the paragraph below explains why revision 4's `queued_primary_workspace` is withdrawn. This is consistent with the existing fail-closed rule from G2/G3 — when Deck cannot act safely it declines and reports — but it reuses the existing report rather than adding one.

**How to refuse: exclude primary from the dispatch scan. Revision 4's refuse-and-release does not work, and the reasoning that chose it was wrong.**

Revision 4 released the lease and continued, expecting the next attempt to find a worktree. The fourth review says that still loops forever, and the code agrees. `acquire`'s scan is:

```python
# github_workspace_service.py:111-122
select(GithubWorkspace).where(
    GithubWorkspace.scope_id == scope.id,
    GithubWorkspace.enabled.is_(True),
    GithubWorkspace.dispatchable.is_(True),
    GithubWorkspace.leased_item_id.is_(None),
).order_by(GithubWorkspace.id)
```

`release` restores `leased_item_id = None` (`:147-164`), so after a release the primary row matches the filter again — and `order_by(id)` puts a lower-id primary first, every time. The next attempt leases the same primary, refuses, releases, and the item never reaches the worktree. Releasing changes *nothing* about selection; it only makes the loop tidy. Revision 4's test 28c ("the next attempt reaches a worktree") **cannot pass** against revision 4's own design, which is exactly the defect class my own memory warns about: a planned test that is silent against the implementation it accompanies.

**The fix is the alternative revision 4 rejected**, and it rejected it for a stated reason that is false. Revision 4 said narrowing the scan "would change behavior for callers that are not doing identity work, because `acquire` is also how Deck leases a primary checkout for observation purposes." Measured: `acquire` has **exactly one non-test caller** — `github_dispatch_service.py:277`, the dispatch path. There is no observation caller. Nothing else in `app/` calls it. The claim was invented to justify a choice, and it is retracted.

So: `acquire` gains a keyword-only `allow_primary: bool = False`, and its scan excludes `kind == "primary"` unless the caller opts in:

```python
async def acquire(self, db, scope, item, *, allow_primary: bool = False):
    ...
    conditions = [
        GithubWorkspace.scope_id == scope.id,
        GithubWorkspace.enabled.is_(True),
        GithubWorkspace.dispatchable.is_(True),
        GithubWorkspace.leased_item_id.is_(None),
    ]
    if not allow_primary:
        conditions.append(GithubWorkspace.kind != "primary")
```

The parameter exists rather than a bare exclusion so a future observation caller has a documented, explicit door — and so the default is the safe one. Dispatch never passes it.

Two consequences worth stating, because they are why this is better and not merely different:

- **A primary workspace is never leased for dispatch at all**, so there is no window in which the human's checkout is leased-but-refused, and no `.git/config.worktree` write can precede the check. Revision 4's version had to be careful about ordering; this version has nothing to order.
- **The existing `dispatchable` filter and this one are independent.** Live workspace 1 is `dispatchable=0`, which already keeps it out — but `register_workspace` accepts `kind="primary", dispatchable=True` (`:361`, `:410`), and the route defaults `dispatchable` from `kind` only when the caller omits it (`agent_teams.py:600-603`). An operator passing `dispatchable: true` explicitly re-opens the hole. The `kind` check does not depend on the flag being right.

**When no dispatchable non-primary workspace exists**, `acquire` returns `None` and the **existing** `queued_no_workspace` path handles it (`github_dispatch_service.py:281`) — no release, no new refusal branch, no new `pending_reason`. Revision 4's `queued_primary_workspace` is therefore **withdrawn**: it existed only to describe a refusal that no longer happens. That also removes the `release_by_token`-versus-`release` question from this section entirely, along with the mutation row revision 4 could not test.

An operator who has explicitly marked a primary workspace `dispatchable` and wonders why nothing dispatches needs to be told. `queued_no_workspace`'s `status_note` gains a count when primaries were skipped: *"no dispatchable worktree available; 1 primary checkout was skipped (agents are never given a primary checkout — see §5.7)."* This is a message change, not a state change.

Primary workspaces are therefore undispatchable *for identity purposes* under PR2. That is the intended trade: `kind="primary"` exists so Deck can observe a human's checkout, and `release_blocker` already treats it as a special case it must not reset (`:200`, `:231`). Treating it as somewhere an agent may assume an identity was always the wrong reading of that column.

### 5.8 Tests

1. Workspace provisioning sets all five per-worktree config values; a second worktree in the same repo is unaffected.
2. The URL-scoped helper wins over an ambient `credential.https://github.com.helper` — the exact case that failed when measured with the unscoped key.
3. A slot whose display name contains spaces and punctuation is slugified into a valid email local-part (lowercase, `[a-z0-9.-]`, collapsed runs). This is a **correctness** requirement, not a security one: `_env_flags` (`agent_bridge/spawn.py:38-44`) validates variable *names* against `[A-Z_][A-Z0-9_]*` and raises on a bad one, but does not validate values — and `subprocess.run` is called with an argv list and no `shell=True` (`:79-84`), so no shell ever interprets a value. Measured: `{'GIT_AUTHOR_NAME': 'Bad; rm -rf / $(whoami)'}` passes through untouched and harmlessly. The plan must not add shell-escaping theater; a malformed email pollutes `git log` and `Co-authored-by` trailers, and that is the real defect.
4. The token cache refreshes inside the margin and reuses outside it; concurrent callers mint once (lock held).
5. The private key, the JWT, and the token appear in no log record and no brief.
6. `pyjwt[crypto]` and `cryptography` are declared in `requirements.txt`.
7. With App auth unconfigured, dispatch still works on the existing `github_token` path.
8. `report_pr_opened` refuses a PR in a different repo (`409`, `pr_number` unset).
9. `report_pr_opened` refuses a PR whose author is not the bot **on an `app`-mode scope** (§5.6a). Keyed on the scope's `github_auth_mode`, not on `github_app_bot_login` being non-empty — tests 36 and 37 are the pair that pin this distinction.
10. `report_pr_opened` refuses a PR whose head branch does not match the item's expected branch.
11. `report_pr_opened` skips the author check on an **`ambient`-mode** scope even when `github_app_bot_login` is set. This is the false-sentence test; see §5.6 and test 36.
12. Brief contains the `[Slot]` prefix, the `deck/<slot>/issue-<n>` branch instruction, and both trailers — and instructs `pr_ready` with `head_ref`, not `pr_opened` with a number, on an `app`-mode scope. It must **not** claim the agent owns the PR title (§5.5.5).

Deck creates the PR (§5.5.2):

13. `pr_ready` with a valid `head_ref` ⇒ Deck calls `POST /repos/{o}/{r}/pulls` **once**, records the returned `pr_number`, and the item lands in `verifying` (code) or `awaiting_human_review` (design), matching `report_pr_opened`'s existing behavior.
14. `pr_ready` with a `head_ref` outside the item's expected `deck/<slot>/issue-<n>` pattern ⇒ `409`, **no** pulls call made, `pr_number` unset. Assert the call was not made, not merely the status code.
15. `pr_ready` for a ref absent on the remote ⇒ refuses with "branch not found," no pulls call.
16. `pr_ready` twice for the same item ⇒ one pulls call total, second returns the existing `pr_number`. Test 38 is the stronger form of this (it asserts the reconciliation call is skipped too); keep both, since 16 is the behavior an operator sees and 38 is the mechanism.
17. On an **`ambient`-mode** scope, `pr_ready` refuses and `pr_opened` still works — the legacy path is intact.
17b. `pr_ready` from the owner with a **stale lease token** ⇒ `409` before any GitHub call (§3.5a test 7f asserts the same rule from the authorization side; this one asserts the mock was never invoked).
18. `create_pull` sends the installation token, and the token appears in no log record (extends test 5 to the new call site).

Helper endpoint (§5.5.6):

19. `useHttpPath` is set, and the helper receives `path=` on stdin. Without it the helper gets only protocol and host — the measured default.
20. The helper refuses (`400`) when `path` is absent rather than guessing a repo.
21. A helper call with a valid `lease_token` for repo A asking for repo B ⇒ `403`, and the message names both repos.
22. A helper call with a released lease ⇒ `403`.
23. **With App auth unconfigured, the worktree gets `user.name`/`user.email` and NO `credential.*` lines at all.** Assert `git config --worktree --get-all credential.https://github.com.helper` exits non-zero. This is the blocker-8 test: revision 3's design wrote the helper unconditionally and relied on a `501` fallback that does not exist.
24. On that same worktree, the ambient global helper is still reachable — `git config --get credential.https://github.com.helper` returns the user's value. Proves the empty-then-add wipe was not applied.
25. No pane environment contains a token: assert the `extra_env` dict passed to `spawn_session` has no `GH_TOKEN` and no `GITHUB_TOKEN` key.

Owner-change and primary (§5.5.6, §5.7):

26. `accept_handoff` rewrites the worktree identity to the new owner slot; a commit made after the handoff carries the new owner's name.
27. Release removes the helper line and the identity from the worktree config.
28. **A `dispatchable` primary workspace at a lower id than a dispatchable worktree is skipped, and the worktree is leased on the *first* attempt.** This is the blocker-1 test and it replaces revision 4's 28/28b/28c entirely. Build both rows with `dispatchable=True` — the point is that the `kind` check does not depend on the flag — assert `acquired.id == worktree.id`, and assert `.git/config.worktree` is absent in the primary checkout. Against revision 4's refuse-and-release design this test fails on the first assertion, because the primary is leased first and only released afterwards. Against today's code it fails too: the primary wins `order_by(id)`.
    28b. **A primary is never leased even momentarily.** Same fixture, and assert the primary row's `leased_item_id` was NULL throughout: `leased_at` and `lease_token` are still NULL after the acquire, and `released_at` is still NULL. A design that leases-then-releases leaves `released_at` and a cleared `lease_token` behind, so this distinguishes the two designs on the row state rather than on the outcome.
    28c. **Only a primary available ⇒ `queued_no_workspace`, not a loop.** With a `dispatchable` primary as the *only* workspace in scope, `acquire` returns `None`, the item takes the existing `queued_no_workspace` path, and its `status_note` names the count of skipped primaries. Then add a worktree and re-run: it dispatches. Proves the skip is not a dead end.
    28d. **`allow_primary=True` still leases it.** The opt-in door works, so a future observation caller is not silently broken — and the default remains the safe one. One line, and it is the only test that may pass a primary.
29. No new `dispatch_status` value **and no new `pending_reason`** is introduced by §5.7 — assert the item's `dispatch_status` is one of the existing set and its `pending_reason`, when set, is one of `queued_no_workspace` / `queued_ambiguous_sessions`. Revision 4's `queued_primary_workspace` is withdrawn; this test is what stops it coming back.
    29b. **`in_progress` no longer writes `pr_number`** (§5.6). Post `status="in_progress"` with `pr_number=9999` on an item whose `pr_number` is NULL ⇒ the report succeeds (it is a liveness ping), `last_nudge_at` is cleared, and `pr_number` is **still NULL**. Then assert the consequence that made it matter: `_ack_satisfied(item)` is still `False`, so the leader-ack gate was not silenced. Against today's code this test fails on both assertions.

**Mutation requirement.**

| Mutant | Test that must fail |
|---|---|
| `useHttpPath` omitted | 19, and 21 becomes unimplementable |
| helper authorizes on host alone, ignoring `path` | 21 |
| configure the Deck helper unconditionally, relying on `501` to fall back | **23, 24** |
| write the empty-then-add wipe without the Deck helper line | 24 |
| primary check applied after the config write | **28** |
| lease the primary and release it instead of excluding it from the scan (revision 4's bug) | **28, 28b** |
| exclude primary by `dispatchable` alone instead of by `kind` | **28** — the fixture sets `dispatchable=True` on both rows |
| `allow_primary` defaults to `True` | 28 |
| drop the `allow_primary` parameter entirely (hard exclusion) | 28d |
| trust the agent's `pr_number` on the `pr_ready` path | 13 |
| accept any `head_ref` without pattern-matching it | **14** |
| leave `in_progress`'s `pr_number` write in place (today's code) | **29b** |
| route `in_progress`'s `pr_number` through verification instead of dropping it | 29b — the report must succeed *and* leave the column NULL |
| open a second PR on a retried `pr_ready` | 16 |
| handoff leaves the previous owner's identity in place | 26 |
| `GH_TOKEN` reintroduced into `extra_env` "for convenience" | 25 |

**Tests 30-50 live in this file too**, and are specified where their design is argued rather than repeated here: 30-37 in §5.6a (per-repo auth mode and transient-failure refusal), 38-46 in §5.5.4 (`pr_ready` reconciliation), 47-50 plus 49b in §5.5.5 (title, body, draft, and the base-ref normalization). Their mutation tables are with them, for the same reason: a mutant list separated from the guard it describes goes stale silently.

Revision 4 closed this section with a paragraph defending a `release_by_token` mutation row. That row is **gone** — §5.7 no longer leases the primary at all, so there is no release call to distinguish and no untestable guard to excuse. The paragraph is deleted rather than reworded, because the honest summary is simply that the design change removed the problem.

### 5.9 Deployment (gated, manual, not part of the PR)

Restoring tizonia branch protection is the hard gate the soak log records. The backup exists at `/tmp/tizonia-master-protection-backup.json` (`required_approving_review_count: 1`, `enforce_admins: true`). **Copy it somewhere durable first** — `/tmp` is not a safe home for the only copy of a gate. Restore only after PR2 is deployed and a bot-authored PR has been observed to be approvable by `juanrubio`.

---

## 6. Explicitly out of scope

- **`route_item`'s fallback is unchanged.** Refusing to route to the leader strands work when no specialist matches; the enforced gate makes leader ownership *safe* rather than forbidden.
- **No ack timeout changes.** No softening, no tiering, no idle monitor — that is #280, and mixing it in risks the C1 invariant.
- **No new `dispatch_status` values.**
- **Authorizing `/dispatch-status` by anything other than team role.** §3.5a's matrix is owner / leader / handoff-target, derived from columns that already exist on the item. It has no notion of a delegated reporter, an operator reporting on an agent's behalf, or a per-branch permission grant. An operator who needs to move an item does it through the existing retry and escalation endpoints, not by impersonating a slot.
- **Autonomy stays off** (`autonomy_enabled = 0`, both presets). No PR here enables it, and none restores branch protection.
- **Confidentiality of mail reads.** PR0 authenticates identity-bearing *writes*, plus `GET /agent/inbox` because that endpoint mutates (§3.5). `GET /team` and `GET /messages` stay open; any agent can still read the roster and message list. That is a real gap and a separate decision.
- **Per-slot bot accounts** — considered, rejected in §5.1.
- **Co-resident pane compromise.** Every pane runs as one user with no `hidepid`, so any pane can read any other's `/proc/<pid>/environ` — measured, 123 entries including `CLAUDE_DECK_TEAM_SLOT_ID`. §3.3's binding defeats *claiming* another slot; it does not defeat a pane that reads another's memory or files. Closing this needs OS-level isolation (separate users, `hidepid=2`, or containers) and is a hosting decision, not a code change.
- **Remotely hosted Deck.** §3.6's UI self-provisioning depends on the loopback gate, so it only works when browser and backend share a host. That is the only configuration Deck supports today (CORS is pinned to `localhost:5173`). Serving Deck remotely needs real user authentication — a project of its own.
- **Primary-workspace dispatch under PR2.** §5.7 excludes a `kind == "primary"` workspace from the dispatch scan rather than assigning an identity in a human's checkout. Making primary workspaces safely dispatchable would need a way to scope git identity to a process rather than a checkout, which git does not offer for commits an agent makes itself. The `allow_primary=True` door exists for a future observation caller; nothing in this spec passes it.
- **Absence of any reachable credential in a pane.** §8 criterion 10 replaces revision 3's "no pane ever holds a token." An agent that pushes can read what it pushes with, so the guarantee is short-lived + repo-scoped + unpersisted + not in pane env. Removing even that reach would mean Deck performing the push on the agent's behalf — plausible, larger than PR2, and not attempted here.
- **`gh` in agent panes.** PR2 makes `gh` unnecessary for the dispatch flow, but does not remove or restrict it. A pane with the user's `gh` already authenticated can still act as the human; that is pre-existing, unchanged by this spec, and would need the same OS isolation as co-resident compromise.
- **Auto-merge of PRs Deck did not create.** The `pr_opened` legacy path still records an agent-supplied number, verified by §5.6 but not created by Deck. Requiring Deck-created PRs for auto-merge would be a stronger invariant; it is not adopted because it would make App provisioning a hard prerequisite for any autonomy at all.
  Note that §5.5.4's reconciliation makes "created by Deck" a weaker distinction than it sounds: on the crash path Deck **adopts** a PR whose creation it cannot confirm, because from GitHub's side the two are indistinguishable — the PR exists on the expected head and base, and there is no record of which process's `POST` produced it. Adoption therefore re-runs §5.6's repo/branch/author checks rather than trusting the head match, and the result is exactly as trustworthy as the `pr_opened` path plus the head/base agreement. Making auto-merge require provable Deck authorship would need an idempotency key GitHub does not offer for pull creation.

## 7. Deferred

- **Approval expiry.** An ack survives an arbitrary number of pushes after it was given; only auto-merge's head-freshness check bounds it. The nonce bounds it per *dispatch*, not per *push*. Re-approval after a force-push belongs with #280's head re-confirm item.
- **External human approvers.** Attribution assumes the approver is an Agent Mail member. A GitHub PR review by a human is stronger evidence and is not read at all.
- **Timing-safe token comparison as a tested property.** Enforced by review in PR0 (§3.7), not by a test.
- **Enforcing tokens by default.** PR0 ships with `mail_capability_tokens_required = False` because a running shim cannot learn a new header without a restart (§3.4). Flipping the default to `True` is a follow-up once no pre-upgrade shim can exist, and it should be a one-line change plus a release note.
- **Non-tmux agents.** §3.3 mints an unbound token when the caller has no tmux ancestor, so such a session can send mail but can never approve. Binding them needs a different channel (a launch-issued code, or OS credentials) and no such agent exists in this deployment today.
- **A decision UI for the operator.** §4.3a gives the leader a tool and exposes `decision` in the API (§4.6), but adds no approve/reject control to the Deck frontend. An operator who wants to approve does it by merging, per §3.6. A UI button would need the operator to act *as* the leader member, which is exactly the actor/member distinction PR0 draws — worth doing, and a separate decision.
- **Pruning per-tab UI actors.** §3.6 accumulates one `mail_external_actors` row per operator tab. Inert, but noisy in the roster over months. A `last_used_at` sweep is the obvious fix and is not in PR0.
- **Re-resolving a scope's auth mode.** §5.6a writes `github_auth_mode` at lease time when the lookup answers, and leaves it `unknown` when it does not. Nothing re-resolves a mode that is *already* set: a scope recorded `ambient` before the App was installed keeps dispatching under the human's credential until an operator clears the column. §5.6a explains why this is the safe direction (a stale `app` is caught by the author check; a stale `ambient` is merely the pre-PR2 behavior), but the operator has no control for it — no UI, no endpoint, only a manual `UPDATE`. A "re-check auth mode" action belongs with the workspace UI and is not in PR2.
- **A cross-process lock for PR creation.** §5.5.4 serializes creation with the lease token plus a per-item `asyncio.Lock`, which is correct for one uvicorn process (today: PID 2206652, single worker). Two workers or two hosts would each hold their own lock, and the reconcile-before-create step becomes the only defense — it narrows the window to the round trip between `list_pulls_for_head` and `create_pull` but does not close it. Closing it needs a DB-level advisory lock or a unique constraint on (item, head), and SQLite gives neither cheaply. Stated so a future multi-worker deployment knows what it inherits.
- **Retiring the `pr_opened` path.** Once App auth is provisioned everywhere, `pr_ready` makes `pr_opened` and most of §5.6 dead code. Removing it is a cleanup that should wait until no scope depends on the ambient-credential flow.

## 8. Success criteria

1. An agent cannot post a message as another member: the §1.5 forgery returns `403`.
   1b. An agent cannot obtain a token bound to a slot it does not occupy: the §1.6 forgery (a Specialist pane claiming `team_slot_id: 4`) returns `403`.
   1c. An unauthenticated caller cannot forge another member's liveness or silence a `brief_unread` escalation through `GET /agent/inbox`.
2. A self-ack cannot set `ack_received_at`, and the live shape (`context_request` 16→16 answered by 16) is refused by a regression test.
3. Only the designated leader member's own answer can approve — not any non-owner, and not a member with no slot.
   3b. **A reply is not an approval.** Only an explicit `decision = 'approved'` written by the leader satisfies the gate; live rows 82 and 92 — the Leader refusing in prose — are refused by regression tests, and row 40's genuine approval is accepted despite containing negative words.
4. Evidence from a previous dispatch attempt cannot approve the current one, across both retry and handoff.
5. Every recorded ack names its approver, the message that proves it, and the round it belongs to, and all five columns are visible to operators and to `deck_list_work_items`.
6. Auto-merge cannot happen without a valid distinct approval, and failing that check falls back to human merge stickily, without escalating.
7. A bot-authored PR is approvable by `juanrubio`, so branch protection can be restored to `required_reviews=1, enforce_admins=true`.
8. Commits, PR titles, and branch names identify which agent produced them, on the reuse path as well as the spawn path.
9. `pr_number` is never taken on trust, on **any** path: Deck reads it from its own `POST /pulls` response; the legacy `pr_opened` path refuses a PR in the wrong repo or on an unexpected branch; and `in_progress` no longer writes the column at all (§5.6), so it cannot plant an unverified PR or silence the ack gate through `_ack_satisfied`'s `pr_number` short-circuit.
10. **No pane holds a *persistent* GitHub credential.** No `GH_TOKEN`, no `GITHUB_TOKEN`, nothing in `extra_env`, nothing written to disk in the working tree, and no log or brief containing the App private key. The credential an agent can reach is minted at use time, scoped to one repository, expires within the hour, and dies with the lease.
    **This is deliberately weaker than revision 3's claim** that "no pane ever holds a token." That was not achievable: git receives the helper's plaintext password on every push, and an agent with a shell can run `git credential fill` and read it. Since the agent must push, some reachable credential is unavoidable. What PR2 guarantees is the four properties above — short-lived, repo-scoped, unpersisted, not inherited in the pane environment — which is what actually bounds the damage. Claiming absence would have been a claim a reviewer could disprove in one command, and a success criterion that can be disproved in one command is worse than a modest one that holds.
11. Deploying PR0 changes no behavior until the operator enables enforcement; PR1's gate refuses to merge while enforcement is off, **and no approver evidence is recorded during that period** — so flipping the flag cannot legitimize anything written before it.
12. A human's primary checkout is never given an agent git identity, and refusing it does not strand the item: a primary is **excluded from the dispatch scan**, so it is never leased at all, and the next dispatchable worktree is leased on the first attempt.
13. Every new guard is shown to bite by mutation, and the guards that cannot be tested (`hmac.compare_digest`, a per-item lock's global/per-key distinction) are named as review items rather than claimed as covered.
14. **Every `/dispatch-status` branch states who may report it.** Authentication is not authorization: an agent that is not the item's owner, leader, or handoff target is refused, the refusal happens before any state change, and the two GitHub-writing branches additionally require the current lease token (§3.5a).
15. **A rejection has a workable next round.** After `revision_requested` the owner can open a new approval request, the previous round's approval no longer satisfies the gate, and `max_approval_rounds` still bounds the loop (§4.3a.1).
16. **A tmux pane Deck did not launch keeps working.** It registers, mints an unbound token, and can send mail; it can never approve. `bind_pending` is reserved for a pane that claims a Deck launch (§3.3a).
17. **A transient GitHub failure never silently changes authorship.** An unresolved installation lookup refuses the dispatch and leaves the workspace unconfigured, rather than falling back to the human's ambient credential (§5.6a).
18. **A crash between `create_pull` and the commit does not produce a second PR or an orphaned one.** The retry reconciles by head/base, adopts the existing PR through §5.6's checks, and records its number (§5.5.4).
19. **A design PR is immediately reviewable.** It is created non-draft, because nothing in the design path would ever mark it ready, and a draft PR cannot be approved (§5.5.5).
20. **Deck's PR calls speak GitHub's vocabulary, not git's.** `scope.base_ref` is a refspec (live value `origin/master`, column default `origin/HEAD`) and every existing consumer treats it as one. It is normalized to a branch name before it reaches `create_pull` or `list_pulls_for_head`, in one shared helper, so the base filter cannot silently match nothing (§5.5.5).
