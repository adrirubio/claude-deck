# Distinct Approver Identity — Design (Findings #1 and #6)

**Date:** 2026-08-05
**Status:** Design, revision 18 — **approved for implementation planning.**

**What revision 18 changed** — revised after an eighteenth review, of the PR0 *implementation plan* (`0490035`) rather than of this spec. That review returned six blockers; five are plan defects and are fixed there. The one that lands here is blocker 1, and it lands as a whole new section because the plan had **replaced this spec's identity model rather than implemented it**: Task 10 widened the mail dependency to admit the operator credential and let the browser send an arbitrary `sender_member_id`, so a human typing in the mail UI produced a row indistinguishable from one an agent's authenticated session wrote — the exact confusion Finding #1 exists to remove. The review's recommendation is adopted verbatim: *preserve operator attribution and extend external-actor thread capabilities, not let the operator impersonate agent members.* Four things follow, and three of them are measurements the review did not have.

**(1) §3.6's load-bearing claim was false, and the gap it hid is wider and points the other way.** Revision 17 said the UI's ack "uses the actor ack endpoint that already exists, so no new route is needed." Measured, *every* actor capability — read, ack, reply — refuses any thread the calling actor did not create (`external_agent_mail_service.py:396-402`, `:339-340`, `:258-259`). So the plan was right that a capability gap exists. But the threads the operator must act in are the ones **agents** created, for which "threads they created" is an **empty** predicate — meaning the fix is not a loosened ownership comparison but permission into threads *no actor created at all*. And because §3.6 provisions one actor per **tab**, capability follows the tab: measured, a second tab is refused read, ack and reply on its own operator's thread from one tab earlier. New §3.6b states the three route requirements; §3.6's false bullet is struck rather than deleted, so the next reader sees which claim failed.

**(2) The plan's inference did not follow from its own measurements, and the two credentials were never in competition.** Both facts it cited are true: an actor cannot post `kind="answer"`, and an actor cannot reply in a thread it did not create. Neither implies the operator must post *as a member* — the reply need not be an answer-of-record to be useful, and §4.3 rule 4 is precisely the rule requiring it not to be. §3.6a's minting measurement is likewise narrower than the plan read it: a self-minted actor token buys only *actor-authored* writes, whose `sender_member_id` is NULL by construction and whose request schemas have no such field (`schemas.py:1931-1948`), so a pane that mints one gains no slot identity, no dispatch authority, no approval and no lease authority. That measurement is fatal for gating force-release and irrelevant to the mail UI. §3.6a now says so in the paragraph that reports it, because the plan read it as licence to hand the browser the *destructive* credential instead.

**(3) Two defects of my own, in code this design touches, neither raised by any review.** First, `reply_in_thread` routes its reply to `root.recipient_member_id` (`:265`) — on an agent-created `context_request` that is the member who was **asked**, not the member who **asked**, so the agent waiting for the operator's reply is the one member not notified of it (measured: receipts `[2]`, asker `1` absent). Passing `None` notifies both, and it works *because* an actor's NULL `sender_member_id` excludes nobody from the fan-out — the same NULL that makes the row unable to carry approval. Second, an operator ack implemented via `MailReceipt` would write `read_at`, which is the **only** mail field any dispatch service reads (`github_dispatch_service.py:824`) and the one suppressing the `brief_unread` ladder — so the cheap implementation reports that an agent read a brief it has never seen. Both are normative in §3.6b rather than left to a plan, because both are the shortest path to green.

**(4) The review's own test set had a gap, and finding it is what the mutation table is for.** Its eight required tests all use a single actor, so an implementation that relaxes ownership to "any actor, any thread" — one deleted comparison instead of a conditional one, the shorter edit — passes every one while granting every browser tab access to every other tab's threads. Test **6i** is added for that mutant. Also from the review, and confirmed: §3.3's `AgentPaneBinding` sketch wrote `slot_id`/`preset_id` as `Mapped[int]` while specifying `ondelete="SET NULL"`, which are two different schemas; the codebase is unanimous the other way, seven `SET NULL` FKs and seven `Mapped[int | None]`. Corrected, with the `create_all`-vs-`ALTER` distinction stated alongside it.

Approval covers this design, not a plan that changes its contracts — which is the rule this revision exists to enforce.

**What revision 17 changed** — **approved for implementation planning.** The sixteenth implementer review of `3726942` (revision 16) found no remaining design blocker and approved the architecture, closing the path A test gap and the criterion 29 attribution. Revision 17 changes **no design decision**; it converts that review's fourth planning caution into normative spec text, because a caution addressed to the implementation plan is a requirement the spec failed to state. The caution: do not let requirement 8's `lease_token = <token>` be "fixed" into null-safe equality (`IS`, `IS NOT DISTINCT FROM`, or a spelled-out both-NULL branch) without revisiting the documented NULL-token decision. Measured, it is worth more than a review checklist item, for two reasons the caution does not name. **(a) The rewrite is invisible to every test that can exist** — across all five token pairings the two forms differ on *exactly* the both-NULL row and agree on the four reachable ones, and `IS` is measured identical to the spelled-out branch. It is also **not** a hole in the contact stamp: the owner `EXISTS` clause still refuses a non-owner with a retained live token and a non-owner calling tokenless (`0` rows each). Harmless enough to pass review, invisible enough to erase a decision. **(b) Requirement 1 permits a shared conditional-update helper, which is the propagation path** — measured, a null-safe helper makes a **tokenless** release match `1` row on a NULL-token lease where ordinary equality matches `0`, clearing the lease. Not an ex-owner hole; the *owner* releasing without presenting the acquisition id, gated only by the route's preliminary `:339` presence check — the same "the check is not the control" shape §4.6a exists to remove. So the equality is normative for **both** writes and a shared helper may not offer a null-safe mode. The review's other four cautions (PR sequence, the (i-b) interleaving point, branch-arrival assertions, and keeping the transfer's correctness independent of the claim) were verified already normative and needed no edit. Approval covers this design, not a future plan that changes its contracts.

**What revision 16 changed** — revised after a fifteenth implementer review of `f64e154` returned one blocker and one correction. **Both confirmed by measurement, both worse than reported, and one finding of my own that no review has raised.** (1) The blocker: **requirement 5's Path A demands a fresh read of stored ownership, and revision 15 gave that requirement no case in which it can fail.** 37r-9 case (i) was a same-owner duplicate, so the cached and the stored owner *agree by construction* — measured, an implementation that diagnoses path A from the route's cached `item` returns `200 → 200` and passes case (i) unchanged. The review found the contradiction by reading (case (i) was required to expect `200` **and** to make the two owners disagree, which is unsatisfiable: if path A's stored owner differs from the caller, path A must return `403`). Measurement made it a defect rather than a wording slip: the cached mutant hands `200` to an agent that no longer owns the item, in exactly the ordering the freshness requirement exists for. **Two further findings of my own change how the new case must be built.** First, the suspension recipe used by every other interleaving test in this section *does not exist on path A*: 37r-8 and path C both suspend inside `release_blocker`, but on path A `workspace` is `None`, so `release_blocker` sits inside `if workspace is not None` and is never awaited — measured branch offsets place `get_leased_workspace` at `739`, unconditional, as path A's only interleaving point. Second, a version of the case that **seeds** the handoff before the request instead of interleaving it is green against everything: after §3.5a the preliminary `:334` refusal is *also* `403 not_item_owner`, so the response cannot distinguish "path A diagnosed a stale owner" from "the request never reached the lookup" (measured: `reached get_leased_workspace? False`). Revision 14's 37r-9 defect, reproduced on the branch introduced to fix it. 37r-9 is now **four** orderings, with a new case (i-b) carrying two mandatory build rules and a branch-arrival assertion, plus four new mutation rows. (2) The correction: criterion 29 credited `claim-continuation` with the repair `accept_handoff` performs. Confirmed, and it is not merely stale wording — **the criterion asserts in prose the design the spec's own mutation table at `:2824` lists as the mutant test 37r-4 must kill.** The two readings are not equivalent on a real reclaim: deferred, the backstop clears the lease out from under the live owner B the moment the item turns terminal (`reclaimed 1`); with §4.6b's transfer, `reclaimed 0` **with no claim call anywhere**. Corrected, and swept — one further site (`:2019`) carried the same wording. (3) Mine: **requirement 8's SQL predicate is not behaviour-preserving with respect to the Python guard it replaces.** Shipped `touch_owner_contact` guards on *mismatch only* (`:264`), so on a lease whose own `lease_token` is NULL a tokenless call **stamps**, while `lease_token = <token>` matches `0` rows because `NULL = NULL` is `NULL`. Stated deliberately, bounded (unreachable via `acquire`; the pid branch at offset `224` precedes the contact branch at `328`, so a missing stamp is consulted only for a lease whose recorded owner is already dead), and explicitly **not** generalisable to requirement 2 — I predicted by analogy that it was, and `release_by_token`'s unconditional guard at `:190` refuted me. **Not yet approved for implementation planning.**

**What revision 15 changed** — revised after a fourteenth implementer review of `2932ec9` returned two sequencing blockers and one correction, all in §4.6a.1. **All three confirmed by measurement, and one of them exposed a defect in my own test suite that the review did not report.** (1) **The idempotent release path cannot be a zero-row result of the conditional write.** Revision 14 wrote it as the first row of a table headed *"zero rows because…"* — but the write is keyed on a captured `workspace_id`, and measured, after the first release the route's own `get_leased_workspace` returns **`None`**, so no statement is issued at all. A result table can only describe outcomes of a statement that ran. Requirement 5 now sequences three paths, with the idempotent one *above* the write. (2) **"Re-read ownership inside the same transaction as the stamp" is not a control**, and revision 14 offered it as acceptable. Measured on Deck's own file-backed WAL engine, which `database.py:23-34` configures precisely so readers and writers do not block each other: A fresh-reads owner `1`, B commits the handoff on another connection, and A's unconditional stamp lands with `rowcount=1` on B's lease. **Transaction membership is not an ordering guarantee against another connection's commit.** Requirement 8 now specifies one owner-and-token-conditional `UPDATE` and offers no alternative. (3) The correction, confirmed and worse than stated: "one follow-up read" grants no freshness at all — measured, `db.get(GithubWorkItem, id)` returns the identity-mapped object the route bound at `:291` **without emitting a query** (`again is item` → `True`, owner `1` where the stored value is `2`), so the mechanism must be a scalar `SELECT`, `populate_existing`, or `refresh`. Revision 14 fell into the exact trap its own requirement 8 named one paragraph later. **What the review did not say, and it is the more serious finding:** revision 14's mutation table credited test 37r-9's late-ex-owner case with killing "zero rows ⇒ `200` unconditionally". Measured, that request is refused by the preliminary `:334` check having reached neither `release_blocker` nor the write, so it cannot kill a mutant inside a branch it never enters — and the `409` it asserted arrives from the preliminary check, making the assertion green against `master`, the fix, and the mutant alike. **An assertion satisfied by two different mechanisms discriminates neither.** 37r-9 is rewritten as three orderings and 37r-10 gains the interleaving that fails the two-step implementation (measured: revision 14's 37r-10 **passes** it). Two additions of my own: the contact stamp needs the `lease_token` clause as well as the owner clause (measured, owner-only matches `1` row and owner-plus-token `0` when the acquisition is replaced under one owner), and its missing workspace-row clause is safe **by schema** rather than by care — `UNIQUE(leased_item_id)` bounds it to one row — which the spec states so that a later implementer does not drop the constraint and keep the sentence. **Not yet approved for implementation planning.**

**What revision 14 changed** — revised after a thirteenth implementer review of `5ab0f63` returned one blocker and four corrections. All five confirmed by measurement, and the blocker is **broader than reported** in a way that lands against my own revision-13 reasoning rather than the review's. The review says the agent's release path checks owner, token and destructive write in separate operations while criterion 30's no-rotation proof depends on that path being current-owner-gated. Confirmed, and three measurements follow. (1) **My deferral measured the wrong boundary.** Revision 13 deferred the fix on the grounds that "the window is a DB round trip, not two `git` subprocesses" — true of `release_by_token`'s internals, false of the route whose guarantee criterion 30 states: `release_blocker` sits between the owner check (`agent_teams.py:334`) and the write (`:363`) and awaits `self._runner` **twice** (`github_workspace_service.py:203`, `:211`), so the window is the *same* two subprocesses as force-release's. **A guarantee is measured at the boundary it is stated about, not at the helper's internals.** (2) **The owner predicate is the only one that discriminates**, and it is load-bearing *because* of the no-rotation decision: measured on the same post-handoff row, a conditional `UPDATE` keyed on workspace + item + token matches **1** row and the same statement plus `EXISTS (… owner_slot_id = derived)` matches **0**. Token atomicity stops a replacement *acquisition* and cannot stop an admitted ex-*owner*. (3) **Criterion 30's table had a second false row**, found by sweeping the class rather than fixing the reported instance: `touch_owner_contact` is reachable by an admitted ex-owner too (measured, `token='TOK-KEPT'`, contact stamped), because the tail's comparison reads the `item` bound at `:291`. Bounded honestly as a delayed backstop reclaim, not a destroyed lease. One of the review's own requirements was **improved rather than adopted**: its "zero affected rows ⇒ `409`" would regress idempotency, since a duplicate release report from the true owner is measured `200 → 200` today (`:188-189`), so the zero-row case is diagnosed rather than refused by constant (§4.6a.1 requirement 5). One control it lists is **kept but demoted**: `_RELEASABLE_STATUSES` in the predicate is not a race guard — `reset_for_retry` defers while a lease is held (`github_dispatch_service.py:48-63`), measured — and a control nobody can trip reads as coverage, so the spec now says which it is. All four corrections confirmed: the captured token is mandatory in force-release's predicate (`datetime.utcnow()` self-collided **63 098** times in 200 000 pairs, so `leased_at` is not an acquisition id); the seven cleared columns are enumerated; the affected-row bound is the **primary key**, not `UNIQUE(leased_item_id)` (measured `1` row vs `2`); and 37r-4's "in one test" becomes the disposable probe. **Not yet approved for implementation planning.**

**What revision 13 changed** — revised after a twelfth implementer review of `7c850a9` returned three blockers and three corrections. All six confirmed, and two of the blockers are **broader than reported**, both by measurement rather than by reading. (1) The force-release race is not scoped to the same item: `release` selects `WHERE leased_item_id == item_id` with **no** workspace predicate and **no** scope predicate (`github_workspace_service.py:148-152`), so a request that inspected workspace X clears a lease held by workspace **Y** — the fix cannot confirm "the same acquisition of this item," it has to name the row (§4.6a). (2) The operator token's honest bound depends on **where the value is stored**: `spawn_session` calls `tmux new-session` with no `env=`, so the tmux server inherits the backend's whole environment as its *global* environment, and any pane reads it back with one documented command — measured on a throwaway socket, `/proc/self/environ` shows nothing and `tmux show-environment -g` returns the value. The review offered "the backend-only environment or `backend/.env`" as interchangeable; they are not, so `.env` is a requirement with its measurement attached (§3.6a). One recommendation was **improved rather than adopted**: the review's `deck_operator_token` would bind `DECK_OPERATOR_TOKEN`, which no convention in `config.py` produces — 24 settings, no `env_prefix`, so the setting is `operator_token` (§3.6a). One of my own hypotheses was **refuted and kept**: I predicted `scalar_one_or_none` would raise `MultipleResultsFound` on two matching rows, and measured `IntegrityError` from `UniqueConstraint("leased_item_id")` (`database.py:319`) — being wrong is what makes the fix small, because the affected-row count can be exactly one on a schema guarantee. The organising correction: **a comparison is not a concurrency control unless the comparison IS the write** — revision 12 called `expected_leased_at` an optimistic-concurrency guard and specified only a value comparison, two awaited `git` subprocesses above the write, which is the same defect class as the token it replaces, one layer over (§4.6a). **Not yet approved for implementation planning.**

**What revision 12 changed** — revised after an eleventh implementer review of `b49d78b` returned four blockers and three corrections. All four confirmed, three of them by end-to-end measurement rather than by reading, and two are **broader than reported**: the review says force-release is unauthenticated, and measured, `agent_teams.py` has **zero** non-`get_db` dependencies across all 27 `Depends(...)` — there was no operator surface for a route to sit "on" (§3.6a); and the NULL-pid lease leak is not a window but an absence of one, measured to release `0` at 1h, 9h and **90 days** while the same row with a dead pid recorded releases `1` (§4.6b). Two of the review's own recommendations were **improved rather than adopted**: its operator token is specified together with an honest account of what it is worth on a host where the pane and the backend share a uid (§3.6a), and `reassign_to_slot_id` is **kept** where the review offered removal, because §4.2b.1's second PREPARED row already instructs the operator to use it (§4.2b.2). The organising correction repeats revision 11's own: **a measurement of today's code is evidence about `master`, not about the PR you are writing** — and revision 11 broke that rule inside the paragraph that states it, by asserting `accept_handoff` "cannot know" the accepting pane when PR0 has just verified it (§4.6a, §4.6b). **Not yet approved for implementation planning.**
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
| 2 | a rejection increments `approval_round_count`; approval evidence is not revisited | `record_approval_round` is 4 lines that identify nothing and clear nothing, and revision 4's own one-request-per-item `409` **blocks** the documented recovery: the owner cannot open a round-2 request | decisions are **round-scoped**: `approval_round` on the request and the decision, `ack_approval_round` on the item. Revision 5 made the round advance a *separate* `revision_requested` report; revision 6 folds it into the rejection itself — see blocker 2 below (§4.3a.1) |
| 3 | no binding row ⇒ `bind_pending`, retried "every 60s" | a hand-started pane has no binding row and never will, so **every mail tool fails for its whole life** (`_guard` re-registers before each one). And the failing heartbeat backs off to `HEARTBEAT_UNAVAILABLE_INTERVAL_SECONDS = 300.0`, not 60 | "no row **and** no claimed team context" ⇒ mint **unbound**; `bind_pending` is reserved for a pane claiming a Deck launch; the retry interval is stated as **300s** with `_guard` as the fast path (§3.3a) |
| 4 | table row 4 refuses a tokenless re-registration; the next paragraph re-mints when the pane binding matches | the same request, two opposite answers. And the case the paragraph existed to rescue **cannot occur**: `session_key` is minted per process (`agent_mail_server.py:26`), so a restarted shim is a *first* registration | the rescue rule is **withdrawn**; row 4 stands unqualified, and the reasoning is pinned by tests 14b/14c (§3.4) |
| 5 | deriving `reporting_slot_id` from a token fixes dispatch-status trust | authentication is not authorization: **1 of 9** branches compares the reporter to the item. A Specialist could withdraw another slot's approval, accept a foreign handoff, or plant a `pr_number` | an explicit owner/leader/target **matrix** for every branch, plus the current lease token on the two GitHub-writing branches (§3.5a) |
| 6 | "on the `pr_opened` path App auth is by definition unconfigured, so `github_app_bot_login` is empty" | **outright false, and in the direction that disables a check.** The setting is global; App auth is per repository. The combination declared impossible is the normal case for any uninstalled repo | a persisted per-repo `github_auth_mode` (`unknown`/`app`/`ambient`), and **transient** lookup failures refuse instead of silently selecting the ambient credential (§5.6a) |
| 7 | `pr_ready` is idempotent because `item.pr_number` is checked first | `pr_number` is a **cache** of a GitHub fact. A crash between `create_pull` and the commit leaves a live PR Deck has no record of; the retry then creates again and hits an unhandled `422` | reconcile by **head/base** before creating *and* after a timeout or `422`; adopt a single match through §5.6's checks; per-item lock (§5.5.4). `GithubClient` has no by-head method today — that is why revision 4's "reconcile" had nothing to reconcile with |
| 8 | create the PR as a draft, with the agent owning the title | a **draft PR cannot be approved**, and `mark_pull_ready_for_review`'s only caller is `_promote_verified_item` — which design items never reach (`_process_review_item` returns early). So a design PR would be announced "ready for human review" and stay a permanent draft. The report also carries only `head_ref`, so Deck could not apply a title it was never sent | `draft = item.issue_type != "design"`, and Deck composes the title and body from the item row (§5.5.5) |

Revision 5 also answers a question no review raised, found while writing §5.5.5's field table: `scope.base_ref` holds a git **refspec** — `origin/master` live, `origin/HEAD` by default — and `POST /pulls` takes a **branch name**. Sent unchanged, `create_pull` would be rejected and §5.5.4's `base` filter would match nothing, which is the same silent-no-match failure §5.5.4 exists to prevent. Now normalized in one helper (§5.5.5), with tests 46 and 49b.

**A second retraction, and the lesson behind it.** Revision 4 rejected the scan-exclusion fix for blocker 1 by asserting that narrowing `acquire`'s filter "would change behavior for callers that are not doing identity work, because `acquire` is also how Deck leases a primary checkout for observation purposes." Measured: `acquire` has **exactly one** non-test caller, `github_dispatch_service.py:277`, the dispatch path. There is no observation caller. The sentence was invented to justify a choice already made, and it is retracted in §5.7.

That is now twice in this spec that the alternative dismissed in a "deliberately not chosen" note turned out to be the right answer, both times dismissed on an unverified claim about callers. A rejected alternative needs a measurement, or it is just a confident sentence — and a confident sentence is what a reviewer has no way to check.

**What revision 6 changed.** The fifth review found five blockers in revision 5. All five confirmed; **none refuted**. Four of them are the same defect wearing different clothes: revision 5 added a *new* mechanism and left the *old* text describing the world before it.

| # | Revision 5 said | Measured reality | Now |
|---|---|---|---|
| 1 | §3.5a's matrix authorizes every `/dispatch-status` branch, and three later sections cite it as `pr_ready`'s protection | the matrix has rows for the **nine branches that exist today** and no row for `pr_ready`, the tenth branch §5.5.2 adds. An implementer following the normative table lets any registered agent trigger `POST /pulls` on another slot's item | `pr_ready` is a matrix row: **owner only, current lease token required**, both checked before any GitHub call or mutation (§3.5a) |
| 2 | `deck_approve_work_item(decision="rejected")` records a verdict; `revision_requested` advances the round | two operations, two actors, contradictory authority. The matrix makes `revision_requested` leader-only; §4.3a.1 said "the leader or the owner"; the owner is told to *"revise the plan and ask again"* through a branch the matrix forbids them. Nothing obliges the leader to make the second call, so the deadlock revision 5 set out to remove survived | **the rejection *is* the transition.** One function, `advance_approval_round`, writes the decision row, opens the next round, and clears the five ack columns **in one commit** (§4.3a.1) |
| 3 | `approval_round_count` "becomes the round identifier" | it defaults to `0`, `reset_for_retry` sets it to `0`, and `record_approval_round` escalates at `>= max_approval_rounds` — while every lifecycle example in the spec starts at round 1 and nothing initialized it. The round also travelled in a payload the **caller** filled, so an owner could pre-date a request for a round that had not opened | `0` means *not dispatched*; dispatch opens round 1; a rejection of round N opens N+1 only while `N < max_approval_rounds`. The round is derived **server-side** after the owner and nonce are validated; a conflicting caller value is a `403` (§4.2a, §4.3a.1) |
| 4 | a scope's `github_auth_mode` persists, and installation ids are cached in memory "because a restart mints fresh tokens" | the **mode** survives a restart and the **id** does not. A live `app`-mode lease after a restart has no id to mint from, and §5.6a forbids re-resolving. So `git push` and Deck's own `create_pull` both fail on a workspace the spec says is configured | `github_app_installation_id` is persisted on the scope beside the mode, and the restart case is a test (§5.6a). The two contradictory `404` rules are separated by *where* the `404` happens (§5.3a) |
| 5 | reconciliation queries `state="all"` because a closed PR blocks a create | the *reason* is an unverified claim about GitHub (the REST reference documents `422` for create only as "Validation failed, or the endpoint has been spammed" — nothing about duplicate head/base), and step 2 then adopts **any** single match and advances the item. `merged` is read at `github_verification_service.py:164` and `state` is read **nowhere** in the file, so a merged match enters `verifying` and a **closed** match is presented as ready for review while its PR is closed — measured: `status='ready_for_review'`, `note='PR #5 is ready for review.'` | matches are **classified before adoption**: a unique open match is adopted, a merged match reconciles to `merged`, and a closed-unmerged match escalates `pr_closed_unmerged` with the number in `status_note` (§5.5.4a). `state="all"` is kept, for two reasons the design controls rather than one it guessed at (§5.5.4) |

Revision 6 also closes the same hole one layer downstream, found while confirming blocker 5 — and measurement made it the more serious half. `_verify_item` has no closed-unmerged branch **at all**, so a PR closed *after* Deck adopted or created it keeps being polled as if it were live. For a **draft** PR, which is what Deck creates for every code item (§5.5.5), that is an **unbounded** loop: `_promote_verified_item` calls `mark_pull_ready_for_review`, GitHub refuses it on a closed PR, and `process_scope`'s `except httpx.HTTPError` catches the raise without ever touching `retry_count` — measured at 3 polls, 3 API calls, `retry_count=0`, `status='verifying'`, note *"will retry"* forever. One condition in the verifier, one escalation reason, one test (§5.6b).

**The lesson, stated once because it now has five instances.** Every blocker in this review is a *seam* defect: revision 5 changed a mechanism and left neighbouring text describing the mechanism it replaced. A new branch was added to a route but not to the route's authorization table. A verdict was made structured but the transition that consumes it stayed where it was. A counter was given a meaning but not an initial value. A classification was persisted but not the key it implies. A query was widened but not the code that reads its results. None of these are visible in the section that introduces the change — they are only visible from the *other* side of the seam. So the check that finds them is not "is this section right?" but "what else already reads this, and does it still hold?"

**A third retraction, and it is mine rather than a reviewer's.** Revision 5 justified `state="all"` with "a closed PR on the same head still blocks creation with `422`." That is an empirical claim about GitHub's behaviour, stated without measurement, and GitHub's own reference does not support it (checked). It happens to be load-bearing for nothing — §5.5.4a's ladder is correct either way — but it was written as though it had been verified. Retracted and replaced with two reasons this design controls (§5.5.4). Same failure as the two retractions above: **a confident sentence about behaviour nobody measured**, this time about a third party's API rather than about our own callers. The rule generalizes — if a design decision rests on how an external system behaves, either measure it or write the design so the answer does not matter.

**What revision 7 changed.** The sixth review confirmed all five revision-6 blockers closed and found four more. All four confirmed against source or measurement; **none refuted**. They share a shape too, and it is a narrower one than revision 6's: each is a place where a *new* rule from revision 6 meets *existing* transaction, retry, legacy, or fixture behaviour and the two do not compose. Revision 6's seams were between sections of the spec. Revision 7's are between the spec and the repository.

| # | Revision 6 said | Measured reality | Now |
|---|---|---|---|
| 1 | `advance_approval_round` clears, increments, commits the decision, then *maybe* escalates — one sequence with a conditional tail | the cap case does not fit that sequence at all (it clears nothing and increments nothing), so test 31b asked for a fixture that cannot exist. Worse, on the cap path `escalate` has **no commit of its own** and rolls back on broadcast failure (`:1017-1018`) — measured: rejection durable on disk, escalation only in memory, `dispatch_status='dispatched'` with `ack_received_at` **still set** | **two explicit branches** (§4.3a.1). Branch A: one commit, no escalation. Branch B: decision row + escalated state in the **same** commit, notification strictly after it, requiring a no-commit mail write. Tests 31b / 31b-1 |
| 2 | recovery from `pr_closed_unmerged` is `deck_retry_work_item` | the branch `deck/<slot>/issue-<n>` is a pure function of slot and issue, so the retry pushes the **same head**, rediscovers the **same** closed PR, and escalates again. Deck refuses to reopen it and refuses to create beside it — the documented recovery was an infinite loop through a human | the head is scoped to the **attempt**: `deck/<slot>/issue-<n>/<nonce8>`. `dispatch_nonce` is re-minted at the dispatch site a retried item re-enters (`:231` → `:344`), so attempt 2 pushes a fresh head no PR is attached to. No new column (§5.5.4a). Test 46h runs the full cycle |
| 3 | a PR Deck finds is classified before use (criterion 22) | true on the `pr_ready` path and in the verifier, **false on the legacy `pr_opened` path**: `report_pr_opened` (`github_verification_service.py:44-86`) reads neither `merged` nor `state`, and its design branch broadcasts *"Design PR ready for review"* at `:66-81` before any verification. Same false-ask defect §5.5.4a removed, one stage earlier than §5.6b reaches | **one shared `_classify_pull` helper, three call sites** — reconciliation, `pr_opened`, and the verifier. Classification runs after the repo/head checks and before any write or mail (§5.6). Tests 11b-11e |
| 4 | test 29 scans "items left behind by every other test in this file" | **cannot run.** `tests/agent_teams/conftest.py:15-23` builds a fresh in-memory engine per test, and two test modules define their own identical local `db` fixture — no test sees another's rows. The invariant was also self-contradictory: "no new `pending_reason`" above an allowlist containing the new `queued_auth_mode_unresolved` | renamed to **no *undeclared* namespace value**, and split into **29-a** (three frozensets asserted against expected literals) and **29-b** (a table-driven test executing every PR2 writer in its own database). Neither depends on another test having run |

Revision 7 also answers a question no review raised, found while writing blocker 1's branch B: `record_approval_round`'s trailing `await db.commit()` at `:679` is the **only** reason today's escalation is durable, and nothing in the function or its callers says so. Any refactor that moves escalation into a helper whose caller commits *first* silently deletes that guarantee — which is precisely what revision 6's ordering did. The plan must treat that commit as load-bearing rather than incidental.

**The lesson, updated.** Revision 6 said the check is "what else already reads this, and does it still hold?" Revision 7 narrows it: **when a new rule meets an existing mechanism, the mechanism's undocumented properties are where the defect lives.** A commit nobody mentions. A branch name that happens to be deterministic. A legacy path that verifies three fields and not a fourth. A fixture whose scope makes a test unrunnable. None of these are visible in the new rule, and none are visible in the old code either — only in the join.

**What revision 8 changed.** The seventh review confirmed all four revision-7 blockers closed and found four more. All four confirmed; **none refuted**, and three came out broader than reported. The shape moved again: revision 7's seams were between the spec and the repository. Revision 8's are between the spec and systems *outside* it — the source's execution order, Git's ref model, GitHub's response schema, and what a test is able to observe. Three of the four are one failure repeated: the spec asserted a fact about a system it does not own, without measuring it.

| # | Revision 7 said | Measured reality | Now |
|---|---|---|---|
| 1 | `dispatch_nonce`, `dispatched_at`, and round 1 are minted together at the dispatch-success site (`:344`) | the brief that must **contain** the attempt branch is composed at `:290` — fifty-four lines earlier. Source order is acquire `:277` → brief `:290` → mail `:299` → launch `:306` → `:344`, so `_dispatch_brief` sees NULL every time. An in-memory-only nonce is no better: the launched agent's first `deck_request_context` runs in a different request and a different session, and would be refused `stale_nonce` on a legitimate first call | an explicit **`prepare_attempt`** step that mints **and commits** the nonce and round 1 *before* `:290` — crash-idempotent on the poll, preserved across every known launch failure. `:344` keeps only `dispatched_at` and `dispatch_status` (§4.2, §4.2a). Tests 37h-37l drive the real dispatch method and re-read in a fresh session |
| 2 | the attempt head is `deck/<slot>/issue-<n>/<nonce8>` | a ref and a directory cannot share a path, and it fails in **both** directions — the review measured one. Create the child first and the legacy parent becomes permanently unpushable, on every clone and mirror, not only during migration. `<slot>` was undefined for three revisions for a reason nobody had looked for: today's brief has **no** branch convention at all — `:410` tells the agent to invent one — so there was no existing name for `<slot>` to mean | a **sibling**, never a descendant: `deck/slot-<slot_id>/issue-<n>-<nonce16>`. Numeric `slot_id` so no display name reaches a ref, full 16-hex `token_hex(8)`, composed by one `attempt_head_ref` helper, and the brief **replaces** `:410`'s instruction instead of sitting beside it (§5.5.4a). Tests 46p/46q run real `git` |
| 3 | `_classify_pull` keys on `pull["merged"]`, and tests 46b-46g mock `merged: true/false` | `GET /pulls` — the endpoint reconciliation actually calls — omits `merged` **entirely**: 100 closed PRs, `'merged' in obj == False` for all of them. So the shared classifier raises on every listed PR, or, with a `.get("merged")` that looks defensive, sends every real merge to `pr_closed_unmerged`. The nearest merge-shaped substitute is a trap the review did not name: `merge_commit_sha` is **non-null** on a closed-unmerged PR (measured), because it is GitHub's test-merge result, not a merge record | classify on **`(state, merged_at)`** — the only pair present in both response shapes — with an explicit **refuse** row for a missing or unrecognized state. `_classify_pull` returns `str \| None` and reads none of `merged`, `mergeable`, `mergeable_state`, or `merge_commit_sha`; every fixture is copied from the measured list shape and asserts `"merged" not in` it, a rule now normative for every GitHub mock in §5.8. The verifier is routed through the same helper rather than reading the fields itself, and its refuse path consumes the retry budget instead of returning — otherwise the fail-closed branch recreates §5.6b's unbounded loop (§5.5.4a, §5.6, §5.6b). Tests 46l-46o, 29d-29f |
| 4 | three frozensets plus test 29-b are "the whole of the enforcement" | a runtime membership test cannot tell `x = CONST` from `x = "literal"` — the row written is byte-identical — and a writer omitted from 29-b's table is never executed, so the test has no observation that could reveal the omission. Broader than reported: `pending_reason` **already** carries operator free text (`agent_teams.py:785`), so revision 7's frozenset-equality assertion was not merely weak, it was **unsatisfiable** | the promise is now **per column and honest about each**. A static **AST scan** over every assignment and keyword site in `app/` is the enforcement (29-a1); `escalation_reason` has exactly one validated funnel; `pending_reason` is declared-only by design, with `agent_teams.py:785` named as the reason. The impossible structural mutant and the exhaustive-coverage claim are deleted (§5.8 tests 29-a, 29-a1, 29-b) |

Revision 8 also answers a question no review raised, found while writing `prepare_attempt`'s idempotence guard: `reset_for_retry` (`github_dispatch_service.py:41-75`) sets `pending` and zeroes `approval_round_count` but **never touches `dispatch_nonce`** — the column does not appear anywhere in `app/` today. Add the guard without adding the clear, and blocker 2's fix silently reverts: the retry reuses the old nonce, `attempt_head_ref` composes the old head, reconciliation rediscovers the same closed PR, and the item escalates again — the exact loop revision 7 set out to remove, under a suite that stays green because test 46h supplies the nonce itself. The clear is therefore normative in §4.2a and paired with a mutation row, not left as an implementation detail.

**The lesson, updated.** Revision 7 said the defect lives in the existing mechanism's undocumented properties. Revision 8 pushes past the repository boundary: **when a design rests on a system you do not own — an interpreter's execution order, Git's ref storage, an API's response schema, a fixture's power of observation — a confident sentence is worth nothing and a five-line probe settles it.** All four blockers were sentences of that kind; three were wrong in the direction that disables a check. The fourth is the same error aimed inward, at testing itself: revision 7's test 12 asserted the brief's *content* given an item that already had a nonce, so it could never observe *when* the nonce arrived — which is precisely how blocker 1 shipped. A test that pre-populates its own fixture cannot observe ordering, and a test that cannot fail is not evidence.

**What revision 9 changed.** The eighth review confirmed revision 8's four fixes correct *in isolation* and found four blockers in how they **compose with paths revision 8 did not visit** — dispatch's post-launch commit, handoff, the review stage, and response serialization. All four confirmed; **none refuted**. Two are broader than reported, and one of those is the most severe class of defect in this spec: an **auto-merge of a PR a human had reserved.**

| # | Revision 8 said | Measured reality | Now |
|---|---|---|---|
| 1 | `prepare_attempt` commits `dispatch_nonce` + round 1 before the brief, and that is enough to make a fresh session safe | it commits the attempt's **identity** and not its **owner**. `owner_slot_id` and `routing_method` are first persisted at `:332-333`, *after* `launcher` returns — and a newly watched item starts with both NULL (`github_watcher_service.py:63`, columns nullable at `models/database.py:259`, `:262`). So the launched agent's first owner-only report hits `report.reporting_slot_id != item.owner_slot_id` with `item.owner_slot_id IS NULL` and is refused — the same class of failure blocker 1 of revision 7 set out to remove, one column over. The re-poll half is worse: the next poll re-runs `route_item` (`:252`) **before** the guard, so a label edit or an operator disabling a slot re-briefs the *same* nonce to a *different* slot. Both triggers change `route_item`'s answer with no crash involved — measured — but reaching the second poll needs the item to still be `pending`, which a *successful* dispatch is not (§4.2b enumerates the two lifecycles that do leave it pending: a crash between preparation and `:344`, and the four ordinary early-exit paths that queue a prepared item). Not, as revision 9's first draft claimed, by moving the expected head: blocker 2's stored column and the guard's early return both hold it fixed. What moves is the brief's recipient (`:299`), the launch target (`:306`), and `owner_slot_id` at `:332` — so the row ends with owner slot B and a head naming slot A, while slot A holds a **committed** brief for that head (`send_direct_message` commits, `agent_mail_service.py:899`) and is refused by `agent_teams.py:334` when it reports on the work it was told to do | `prepare_attempt` persists the attempt as **one atomic identity record** — `owner_slot_id`, `routing_method`, `dispatch_nonce`, `approval_round_count` — in one commit before any mail, prompt, or pane. A prepared item **reuses** its persisted routing instead of re-running `route_item`, and a partially prepared row **fails closed** (§4.2a). Tests 37i, 37m, 37n |
| 2 | the expected head is composed from the **current** owner slot plus the current nonce, and handoff deliberately keeps the nonce | `accept_handoff` **changes `owner_slot_id`** (`github_dispatch_service.py:705`) and sends no new brief. So slot 3 is briefed `deck/slot-3/issue-42-<nonce>`, pushes it, the item is handed to slot 5, and `pr_ready` then recomposes the expectation as `deck/slot-5/issue-42-<nonce>` and `409`s the valid branch — forever, since no replacement brief ever names the new one. Keeping the nonce across handoff was correct and insufficient: the nonce was not the only slot-dependent half of the name. Measured against the real `accept_handoff`, both designs side by side | the attempt's head is **immutable for the attempt's lifetime**. A sixth column, `dispatch_head_ref`, is written **once** by `prepare_attempt` and read everywhere else; `attempt_head_ref` becomes a *composer called once at preparation* rather than a function re-evaluated per call — because one composer called twice still gives two answers when a shared input moves. Handoff preserves it; only `reset_for_retry` clears it, and the clear lives **in that function**, since two of its three callers are not the operator (§4.2a, §5.5.4a, §5.6). Tests 11f, 37o, 37p |
| 3 | an unclassifiable pull routes through `_record_failed_verification_attempt(head_sha=None)` in **both** `_verify_item` and `_process_review_item`, so the retry budget advances | that helper ends `dispatch_status = "dispatched"` (`:507`) unconditionally while budget remains, and `process_scope:114` routes `dispatched` to `_verify_item`. **Measured:** a design item in `awaiting_human_review` becomes `dispatched`; if the garble is **transient**, the next poll runs check-runs on it and calls `mark_pull_ready_for_review` — an unreviewed design PR taken out of draft. (A *persistent* garble does not promote, because the verify stage refuses too; it mislabels the item as unverified code for two polls and then escalates. Both sequences measured.) Broader than reported, and this is the auto-merge exposure: the helper also overwrites `status_note` at `:487`, which **is** the human-merge reservation (`_HUMAN_MERGE_NOTE_PREFIXES`, checked at `:235`). Measured on a code item parked by a policy `403`: control poll merges nothing; after one refuse path, `merge_pull` is called and `auto_merged_at` is SET | the refuse path is **stage-aware**. `_record_failed_verification_attempt` gains one **required** keyword-only `retry_status`, and the note write moves behind `_set_failure_note`, which refuses to overwrite a reservation. The review stage passes `item.dispatch_status`, so no item is moved between pipelines and no reservation is erased by a failure to classify. The review's proposed `preserve_note` flag is **withdrawn** — a caller that does not know a note is a safety control will not pass a flag protecting it (§5.6b, §5.6b.1). Tests 29f, 29g, 29h, 29h-1, 29h-2 — 29h is the auto-merge regression test |
| 4 | test 29-a1 collects every `ast.Assign` target and every `ast.keyword` named for the three columns | keyword name alone does not distinguish an ORM write from a response field copy. `GithubWorkItemResponse(...)` at `agent_teams.py:201` passes all three. **Ran revision 8's test exactly as written against the current tree: it fails four of its own assertions** — a non-literal RHS failure on `dispatch_status=item.dispatch_status`, two non-`None` `escalation_reason` sites instead of one, and two of the three recorded baselines wrong. The reviewer's independently measured counts match mine exactly | the scan **classifies the enclosing call**, not the keyword name: keyword writes count only for the ORM mutation constructor `GithubWorkItem(...)`, response/schema constructors are excluded by name, `update(...).values(...)` is **UNKNOWN and therefore a failure** until a human classifies it, and **any unrecognized call form fails the test** rather than being skipped — an allowlist that ignores what it does not recognize has the blind spot it was built to remove. Baselines re-measured with the corrected classifier (§5.8 test 29-a1). Test 29-a2 proves the classification itself |

Revision 9 also answers a question no review raised, found while adding blocker 2's sixth column to §4.6's list. Revision 8 named two serializers and claimed adding a column to both "makes the gate auditable by an operator in the UI *and* by the leader through `deck_list_work_items`." The first half is true. The second is false: `deck_list_work_items` does not return the response payload, it re-projects it into a hand-written five-key dict (`mcp_shim/agent_mail_server.py:667-673`), and **measured, it drops all six new columns**. So the leader — the actor this whole spec designates as the approver — would have seen none of the evidence about its own decisions. The sentence had been carried unchanged since revision 3, and the reason it survived is instructive: the *other* half of §4.6, `mail_messages.decision`, genuinely needs only the model change, because `deck_check_inbox` splats its payload (`:269`). One shim, two tools, opposite answers — so "the codebase enumerates by hand" was a correct generalization that predicted the wrong thing for the tool that mattered. §4.6 now counts three projections for work items and two for mail, test 37q asserts each, and the rule is **a field is visible only as far as the last hand-written projection between the column and the reader.**

**The lesson revision 9 adds.** Revision 8's lesson was about systems you do not own. This round's four are all inside the repository, and they share a different shape: **a fix is only as correct as the paths it was composed against.** Each blocker is a revision-8 fix that is right where it was written and wrong one call site away — the nonce is durable but its owner is not; the head is stable but the slot in it is not; the counter advances but the status it lands on belongs to another pipeline; the writer set is enumerated but the enumeration cannot tell a write from a read. So the discipline is not "measure the outside system" but **"enumerate who else touches this column, this row, this status, and run the fix down each of their paths."** Two of the four gave up a defect only when driven end-to-end rather than reasoned about — including the auto-merge, which no amount of reading the retry helper would have surfaced, because the damage is done by a `status_note` write whose significance lives 250 lines away.

**Twenty-six measurements this spec rests on, so a reviewer can re-run them rather than trust them.** The first four are throwaway pytest files against in-memory SQLite with a fake client, no network. The next three reach outside the repository, which is what revision 8's blockers required: one drives real `git` against a temporary bare repo, one is a single unauthenticated `GET` against a public repo, and one walks `app/`'s AST. The next eight are revision 9's: seven are in-repo compositions driven end-to-end through the shipped functions rather than reasoned about, and one returns to the live API to settle a question the first pass did not ask.

The **last eleven are revision 10's**, and they share a shape worth naming, because it is the shape of this revision's findings. Each one takes a claim that is true in isolation and puts it back where it will actually run — a fix inside a control-flow graph, a mechanism inside the API that must reach it, a lease inside the passes that bound it, a fixture inside its pragma's lifetime, a status inside the set it is compared against, a frozenset entry inside the branch two levels below it. Seven of the eleven **changed this design** rather than confirming it: the review's own Solution 2 was measured to break its Solution 1, the mechanism this spec had claimed for the unresolvable-owner branch was measured unreachable and replaced, the fixture that proves the deleted-owner case was measured to pass wrongly under a plausible ordering, a one-name mutation was measured to end two branches away from where it was written, blocker 3's premise was measured to be narrower than the defect underneath it, the review's rotate-or-prove-it-useless choice was measured to have a third answer, and this spec's own sentence about the `**`-splat was measured to be false. Counting revision 9's, that is ten rows that corrected this spec's own text rather than code — **a claim is only as good as the position you measure it in.**

**The last five cover blocker 3 and the AST corrections**, and they add one more turn of the same screw. Blocker 3 asked for a *delivery* mechanism; driving the handoff end to end showed that delivery is not an ergonomic gap but the missing half of an **authority that the handoff splits between two processes** — identity moves to the target, capability stays in the original owner's brief, and the release route demands both, so no agent can finish the item. That reframing is why three of these rows are about *who may act* rather than *what may be read*: an endpoint that hands over a capability is only as sound as the identity check in front of it, and that check was measured to bind at repo granularity while every owner check it feeds is written at slot granularity. The fifth row is the AST pair, and it belongs here for the same reason: a scan is only as good as the *nodes it visits*, and revision 9 had written a guarantee for a form its scan never reaches.

| Claim | How it was measured | Result |
|---|---|---|
| a closed-unmerged PR is promoted as ready for review today | `_verify_item` with `merged: false, state: "closed"` and an all-green check run, `merge_policy="human"` | `dispatch_status='ready_for_review'`, `status_note='PR #5 is ready for review.'` |
| a closed **draft** PR polls forever without consuming the retry budget | `process_scope` three times over the same fixture with `draft: true`, `mark_pull_ready_for_review` raising as GitHub does for a closed PR | `ready_calls` 1→2→3, `retry_count=0` throughout, `dispatch_status='verifying'` throughout |
| adopting a merged PR sends a false review request | `report_pr_opened(…, 5)` on a **design** item, then one `process_scope` with `merged: true` | `awaiting_human_review` + one `'Design PR ready for review'` mail row; next poll corrects the status to `merged` and **leaves the mail row** |
| an escalation whose broadcast fails is **not** durable unless the caller commits | item at the approval cap, `_send_escalation_broadcast` monkeypatched to raise, `escalate` called with no trailing commit; row re-read in a **fresh session** | in memory `status='escalated'`; **on disk** `dispatch_status='dispatched'`, `escalation_reason=None`, `ack_received_at` **SET**. Adding one `await db.commit()` after `escalate` returns makes it `'escalated'` |
| a ref and a directory cannot share a path, **in either order** — and the sibling form is order-independent | a bare repo plus a work clone; the child-shaped `deck/…/issue-42` then `.../a3f9c1b2`, then the reverse order; then the sibling form against a legacy name **in the same directory**, both orders; `git push` for each | both child directions rejected. Parent-first: `fatal: cannot lock ref … 'refs/heads/deck/slot-3/issue-42' exists; cannot create …`. Child-first: the push of the **parent** is `! [remote rejected]`. The sibling form `deck/slot-3/issue-42-<16 hex>` coexists with `deck/slot-3/issue-42` in **both** orders, and `ls-remote` lists both. Note the legacy name must share the attempt ref's directory for this to test anything — a `deck/leader/…` name coexists with `deck/slot-3/…` trivially, and that version of the test passes against the child form too (test 46p) |
| `GET /pulls` does not return `merged` | one unauthenticated `GET /repos/pallets/flask/pulls?state=closed&per_page=100`, then `GET /pulls/6095`; key sets compared | `'merged' in obj == False` for all 100; `merged_at` present and correct in both shapes; `merged` appears only in the single-pull response. Also `#6118`: `merge_commit_sha='9d0293cb…'` with `merged_at=None` — non-null on a PR that never merged |
| a runtime membership test cannot enforce the namespace, and an AST scan can | `ast.walk` over `app/`, collecting every `Assign`/`AnnAssign`/keyword whose target is `dispatch_status`, `pending_reason`, or `escalation_reason` | 30 assignment sites + 4 keyword sites across 4 files, **before** classification. `escalation_reason`: exactly **1** non-`None` write (`github_dispatch_service.py:1035`, a function parameter). `pending_reason`: 5 literals + **1 `JoinedStr`** (`agent_teams.py:785`, operator free text) — which is why that column cannot be a closed set. Also: `"cancelled"` appears **nowhere** in `app/`, while `"failed"` and `"completed"` are real written statuses — the nine-value set is measured, not recalled |
| the AST scan as revision 8 wrote it **fails against the current tree**, and the corrected one passes and is mutation-proof | implemented test 29-a1 literally — bare keyword-name collection, its three stated assertions, its recorded baselines — and ran it over `app/`. Then implemented the corrected classifier (enclosing-call classification, three-tier RHS, UNKNOWN-is-failure, `setattr` baseline) and ran it, then re-ran it against `app/` copied to a temp tree with one injected violation at a time | revision 8's: **4 failed assertions** — `dispatch_status=item.dispatch_status` (`agent_teams.py:211`) trips the non-literal-RHS rule; `escalation_reason` has **2** non-`None` sites, not 1, the second being `agent_teams.py:223`; two of three baselines wrong. Corrected: **passes on arrival** with `dispatch_status` 14 write sites over 9 values, `pending_reason` 11, `escalation_reason` 6 (1 `Name` + 5 `None`), response keywords **3**, unknown call forms **0**. **All 10 mutants caught by a named assertion**, and the tier-2 constant-form case correctly does *not* fire |
| the review-stage refuse path moves a design item into the code pipeline, and a **transient** garble then promotes it | revision 8's design implemented in full (classify-refuse in **both** stages), on an `awaiting_human_review` **design** item with a draft PR; real `process_scope` polls, re-read with raw `text()` in a fresh session each time, run twice: once with the garble persisting, once with it clearing on poll 2 | persistent: `'dispatched'`, `'dispatched'`, `'escalated'` with `retry_count` 1→2→3, `mark_pull_ready_for_review` **0×** — mislabelled, not promoted. Transient: poll 1 → `'dispatched'`; poll 2 `list_check_runs_for_ref` **1×**, `mark_pull_ready_for_review` **1×**, ending `'ready_for_review'` — an unreviewed design PR taken out of draft. Under the fix both polls read `'awaiting_human_review'`, `mark_pull_ready_for_review` **0×** |
| the same path **auto-merges a PR a human had reserved** | code item in `ready_for_review` whose `status_note` is `'Auto-merge blocked by repository policy; requires human merge.'` (a real `403` fallback), `merge_policy="auto"`; one control `_process_review_item`, then one refuse path, then one poll | control: `merge_pull` **0** calls. After the refuse path the note reads `'PR #5 returned a state Deck cannot classify.'` and the sentinel is gone; next poll: `merge_pull` **1** call, `dispatch_status='merged'`, `auto_merged_at` **SET** |
| a handoff strands a valid branch under the composed head, and the stored head accepts it | both designs implemented side by side; a prepared attempt for slot A driven through the **real** `initiate_handoff` + `accept_handoff` to slot B, then B reports A's head — the only head anyone was briefed with. Write set read from `inspect.getsource(accept_handoff)` | composed: `409 head_ref_mismatch`, expected `deck/slot-2/issue-42-<nonce>`, briefed `deck/slot-1/issue-42-<nonce>`. Stored: **accepted**. `accept_handoff` writes `owner_slot_id`, `handoff_state`, `handoff_target_slot_id`, `routing_method`, `updated_at` — and neither `dispatch_nonce`, `dispatch_head_ref`, nor `dispatched_at` |
| `merged_at` is always **present**, so its absence is a garble and not a "no" | `GET /repos/pallets/flask/pulls` for `state=open` **and** `state=closed`, `per_page=100`; key presence and value checked separately from truthiness. Then `_classify_pull` run in both forms over all nine fixtures §5.8 commits to, plus the two new shapes | `merged_at` present in **105 of 105** entries and null on exactly the 5 open ones; `merged` absent from all of them; `state="open"` with a non-null `merged_at`: **zero** occurrences. Under `pull.get("merged_at")` a closed PR with the key *missing* classifies `closed_unmerged` and **escalates `pr_closed_unmerged`** on a payload the code could not read; under the presence guard it refuses. All nine committed fixtures classify **unchanged** — only the two new shapes move, each to `None` |
| adding the columns to the two named serializers leaves the leader — the approver — seeing none of them | the real `deck_list_work_items` called with `_dispatch_request` stubbed to return an item payload carrying all six new columns; separately, `deck_check_inbox`'s return form read from source | the leader receives exactly `['dispatch_status', 'escalation_reason', 'issue_number', 'status_note', 'work_item_id']` — **all six dropped** by a third hand-written projection (`mcp_shim/agent_mail_server.py:667-673`). `deck_check_inbox` splats (`:269`), so the *mail* half of §4.6 needed no shim change and the *work-item* half needed one. Also `GithubWorkItemResponse`: 27 fields, no `extra=allow`, so an unlisted field is dropped rather than passed through |
| a re-routed prepared attempt does **not** acquire a different head — the divergence is in the brief's recipient and the owner column | the real `route_item` driven twice over two slots with disjoint `area_labels`; then the dispatch ordering (route → acquire → prepare → brief → launch) driven end to end with a recording brief spy and a fake `launcher`, in both the reuse and recompute forms; then `_send_dispatch_brief_to_slot` called with **no** trailing commit and `mail_messages` read from a fresh session | `route_item` re-routes on a label edit (`(1,'label')` → `(2,'label')`) **and** on an operator disabling slot 1 (`(1,'leader_fallback')` → `(2,'leader_fallback')`) — neither needs a crash. Recompute: briefs `[1, 2]`, launched `[2]`, `owner_slot_id=2`, but `dispatch_head_ref` **still names slot 1** and exactly **1** nonce is minted. Reuse: briefs `[1, 1]`, launched `[1]`, `owner_slot_id=1`, head agrees. And the first brief is durable before the crash — **1** `mail_messages` row naming attempt 1's head, readable from a separate session with no commit from the dispatch loop, because `send_direct_message` commits (`agent_mail_service.py:899`). So the failure is that slot 1 is really told to push a branch and then loses ownership of it at `:332`, which refuses its report at `agent_teams.py:334` |
| a clear written in the retry route misses two of the three callers, and the guard as first drafted refuses every retry | `reset_for_retry`'s callers enumerated from `app/`, then the **watcher's** `_upsert_item` edit path driven with the clear inside the function vs. in the route; separately, the five-field `any()` guard evaluated against the row the real reset leaves behind | callers: `agent_teams.py:783` (operator), `github_dispatch_service.py:98` (`promote_deferred_retries`), `github_watcher_service.py:79` (**an issue edit — no operator**). Clear inside: `pending`, nonce and head NULL. Clear in the route: `pending` with attempt 1's nonce and head still set. Guard: the reset leaves `(None, None, 1, 'role_match', False)` — `all()` false, `any()` **true**, so preparation raises `PartiallyPreparedAttempt` on **every** genuine retry |
| the ninth review's own Solution 2 breaks its Solution 1: the raise escapes `dispatch_pending` and costs the **scope**, not the batch | the `try`'s extent taken from the AST and compared against the proposed call site; then two `pending` items (one torn, one healthy) polled with and without a per-item `try`; then the real `run_repo_once` driven with a raising `dispatch_pending`, recording which passes ran | `try covers 286-316`; the call site at the top of the loop body is **49 lines above it**, outside. No catch: `PartiallyPreparedAttempt` propagates, **0** items reached after the torn one, both still `pending`. With a per-item catch: the torn row is `escalated` with its nonce kept and item 42 dispatches. At scheduler level the passes that ran are exactly `['poll_scope', 'dispatch_pending']` — `monitor_dispatched`, `remind_held_leases` and `process_scope` all skipped, and `run_repo_job:96-97` swallows the exception, so the stall is silent and repeats every poll |
| reparenting a slot is **unreachable** through the API, so the unresolvable-owner branch needed a different mechanism — and `accept_handoff` is it | both update schemas' `model_fields` read from Pydantic; every `.preset_id` assignment in `agent_team_service.py` collected by AST; then a `pending`, prepared item driven through the real `initiate_handoff` + `accept_handoff` to a slot in another preset; separately `report_dispatch_status`'s preamble read for a status gate | `preset_id` absent from `AgentTeamSlotUpdate` (13 fields) and `TeamGithubScopeUpdate` (15), and **0** post-construction assignments — reparenting is raw SQL only. The handoff lands: `dispatch_status='pending'`, `owner_slot_id=2`, `routing_method='reassigned'`, head still `deck/slot-1/…`, `preset_slots=[1]`, resolvable **False** — no crash and no operator SQL, because the route has no `item.dispatch_status` gate and `accept_handoff` checks no preset, scope or `enabled` |
| escalating without releasing the lease is **bounded**, but two holes weaken the bound | an escalated item holding a real lease driven through `remind_held_leases` and `reclaim_stale`, with `_owner_process_is_alive` forced both ways; then repeated with `kind='primary'`; then with the owner slot having no `MailTeamMember` | `'escalated'` is in both status tuples, so the reminder fires (**1**, subject `Release needed: issue #42`) and the backstop reclaims **only** when the pane is dead (alive → 0, dead → 1, nonce untouched). Hole 1: `kind='primary'` → **0** reclaimed even when aged and dead (`reclaim_stale:292-293`) — reminder plus operator force-release is the entire bound. Hole 2: with no mail member, `remind_held_leases` returns **1** and **0** messages are sent (`notify_owner:1052-1053`), so the count is not evidence of delivery |
| the deleted-owner row is torn by the **FK**, and the fixture that proves it has an ordering trap | a prepared item's owner deleted through the real `agent_team_service.delete_slot`, with the `foreign_keys` pragma listener registered before `create_all` and again after; both classifiers evaluated on the resulting row | with the pragma on: `owner_slot_id=None` while `routing_method`, nonce, head and round all survive — revision 9's three-field guard reads **PREPARED**, the asymmetric model reads **PARTIAL**. With it off (SQLite's default, or a listener registered after `create_all` — `StaticPool` opens its one connection there): the slot is deleted and `owner_slot_id` is left **dangling at 1**, which reads PREPARED under *both* classifiers and silently reroutes the test into the not-in-preset branch |
| a disabled owner is not refused anywhere downstream, and `skipped_disabled` is recorded as a **successful dispatch** | the real `agent_team_service.launch` called with the exact `AgentTeamLaunchRequest` the dispatch loop builds at `:306-316`, against a disabled slot; the result status compared to `_LAUNCH_FAILED_STATUSES` | `action='skip' status='skipped_disabled' tmux_target=None`, and `'skipped_disabled' in _LAUNCH_FAILED_STATUSES` is **False** — so `:338` misses, `:342` runs, and the item is recorded `dispatched` with `dispatched_at` set, a held lease and no pane. `_selected_slots:1244-1250` drops disabled slots only when `slot_ids is None`, and the loop always passes an explicit list, so nothing below the dispatch loop will refuse the owner on its behalf |
| adding this reason to the `pr_opened` recovery list is not a lost escalation but a **promotion into the auto-merge pipeline** | an item escalated `prepared_owner_unavailable` with a disabled owner, `report_pr_opened` called as designed and then with one name added to `_PR_OPENED_RECOVERABLE_ESCALATIONS` | as designed: `ValueError`, row unchanged (`escalated` / reason kept / `pr_number` NULL). Mutant: `escalation_reason=None`, `pr_number=7`, and `dispatch_status='verifying'` — §5.6's auto-merge input — with `owner_slot_id` still the disabled slot and `team notified=[]`. The effect is two branches below the mutated line, which is why the row is measured rather than reasoned |
| the handoff target cannot learn what it now owns through **any** tool it has, and the gap is a missing read rather than missing state | a dispatched item with a real lease handed to slot B through the **real** `report_dispatch_status` both halves, then the real `deck_list_work_items` driven against the actual `_work_item_response` payload with only the HTTP transport stubbed; separately `_dispatch_brief`'s token interpolation counted from `inspect.getsource`, and B's own reports replayed with and without a token | the HTTP layer returns **27** fields carrying `owner_slot_id`, `routing_method`, `approval_round_count` and `workspace_path`; the tool returns exactly `['dispatch_status', 'escalation_reason', 'issue_number', 'status_note', 'work_item_id']`, and the head B must push appears nowhere in its output. The token is interpolated **4×** into the brief and returned by **no** tool, so B reporting `workspace_released` is a **400**, and B reporting `triaging` writes the note but leaves `lease_last_owner_contact_at` NULL (`touch_owner_contact` returns early by design). `accept_handoff` never touches the workspace, so `leased_owner_pid` still names A's process. The backstop **does not read it while the item is `dispatched`** — `_RECLAIMABLE_STATUSES` excludes that status, measured `dispatched → reclaimed 0` against `escalated → reclaimed 1` under identical conditions — so the wrong pane is recorded from the moment the handoff lands and consulted from the moment the item turns terminal. Latent, not benign, and stated this way in all three places the spec mentions it (§4.6b). Separately measured and worse: while A's pane is **alive**, `reclaim_stale` releases nothing whether B's contact stamp is NULL or fresh, because the PID branch short-circuits before the contact branch. Control: the original owner with its briefed token **does** stamp contact |
| the handoff **splits the authority to release**, so neither party can finish the item — and the fix is delivery, not rotation | an item handed A→B through the real route, then three real `workspace_released` calls (A with the live token, B with none, B with a guess), the workspace re-read each time; then B with the **actual** token; then A's retained token replayed against the *other* consumer through the route | A → **409** `only the owner slot may release its workspace`; B → **400** `lease_token required`; B guessing → **409** `lease_token does not match`; `leased_item_id` still set after all three. B **with** the token → `ok`, lease fully cleared — so the token is a bearer capability on the acquisition, not bound to the slot that received it. A's retained token stamps **nothing** (`:371-373` skips `touch_owner_contact` for a non-owner) and was **never invalidated**. So rotation protects against nothing the owner checks do not already refuse, while destroying the only copy of a capability that has no channel to the new owner — **do not rotate; deliver** |
| `reporting_slot_id` is server-**stored**, not server-**verified**, and the check in front of it binds at repo granularity while every owner check is written at slot granularity | the real `report_dispatch_status` driven twice by a slot in **another preset** to take ownership of a preset-1 item; the nonexistent-target case parametrized over `PRAGMA foreign_keys`; then the real `register_session` called by one slot's process claiming another slot's id, plus a different-`cwd` control | Charlie (preset 2) ends as `owner_slot_id` of a preset-1 item with **two unauthenticated calls** — `handoff_initiated` reads only `reassign_to_slot_id`, and `accept_handoff` checks no preset, scope or `enabled`; the owner's preset ≠ the scope's preset, which is §4.2b.1's shape produced by shipped code. Nonexistent target: `[fks=True]` → uncaught **`IntegrityError`** (a 500 — the route has no handler; the three at `:508/530/621` are elsewhere), `[fks=False]` → **accepted**, column pointing at a slot that never existed. Registration: Bravo's process claiming `team_slot_id=1` becomes member `'Alpha'`, because `_slot_matches_registration` compares only `provider` and `repo_id` — identical for every slot on the repo. Control: the same claim from `cwd=/tmp` yields `team_slot_id=None`, `participant_kind='repo'` — real power at repo granularity, **none** at slot granularity |
| a `**`-splat into an ORM constructor is invisible to a name-triggered scan, so the spec's claim that it "fails on the UNKNOWN rule" was false — and the replacement rule fails on arrival unless it is scoped | `GithubWorkItem(**{"dispatch_status": "x"})` parsed and its `ast.keyword` nodes inspected; the 29-a1-shaped collector run over the explicit and splat forms side by side; a callee-keyed rule run over six synthetic forms; then that rule run over all of `app/` at two scopes; separately, `.values(<column>=…)` sites counted and the `.values()` keyword's name-visibility checked | the splat yields **1** keyword with `arg=None`, and `dispatch_status` appears only as a `Dict` **key** — the sole identifier in the call is `GithubWorkItem`. The name-triggered collector returns `['dispatch_status']` for the explicit form and **`[]`** for the splat, so it never reaches the constructor and no UNKNOWN verdict is possible. The callee-keyed rule catches both splat shapes and passes the explicit keyword, `GithubWorkItemResponse(**{…})`, a bare helper, and `AgentTeamSlot(preset_id=…, **slot_data)`. Scoped to four models it flags **2 legitimate shipped sites** (`agent_team_service.py:107`, `:312`); scoped to `GithubWorkItem` — the only class declaring any of the three columns — it flags **0**. And `update(…).values(dispatch_status="x")` **is** name-visible, so UNKNOWN is a real verdict there, with **0** such sites today: visible-but-unrecognized and invisible need opposite fixes |
| delivering a live lease token to an agent by server-authored mail is an **existing** pattern, but its gate makes it unusable for a handoff | after a real A→B handoff, `remind_held_leases` run against the real scope with `send_direct_message` captured, at `dispatch_status='merged'` and at `'dispatched'`; then repeated with **no** `MailTeamMember` for the new owner | `merged`: **1** reminder, **1** message, recipient = Bravo's member row (`notify_owner` resolves from the *current* `owner_slot_id`), and the **live** token present in the body — so capability-by-mail is precedent, not novelty. `dispatched` — the whole working life of the target — `'dispatched' not in _RELEASABLE_STATUSES`, so **0** reminders and **0** messages: the existing channel fires only once the work is already terminal, which is why widening it is the wrong fix. No member: returns **1**, sends **0**, and stamps `lease_release_reminded_at` anyway, so the count is not evidence of delivery and the undelivered reminder waits a full grace period |

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

**PR0's *mail enforcement* ships inert and is switched on by hand — but PR0 as a whole is not inert.** A pre-upgrade shim cannot learn to send a header it has never heard of, so mail enforcement is behind `mail_capability_tokens_required`, default `False` (§3.4). The operator restarts the agent panes, confirms every live session has a token, then flips the flag. PR1's gate refuses to merge anything while the flag is `False` (§4.5), so the inert state is safe rather than silently degraded.

**What is *not* behind that flag, stated here because revision 12 said "deploying PR0 changes no behavior" three times while moving three immediate changes into PR0** (§2.1, §3.6a, §4.6a): `require_operator` gates force-release and the workspace listing from the moment PR0 deploys; force-release's request body changes from `expected_lease_token` to `force` + `expected_leased_at`; `lease_token` leaves `GithubWorkspaceResponse`; and an install with no operator token configured loses both operator routes entirely (`503`, §3.6a). None of these consults `mail_capability_tokens_required`, and none can — a flag whose purpose is "let the old shim keep working" has no bearing on a route the shim never calls.

The correct claim is therefore narrower and is the one used from here on: **PR0's Agent Mail enforcement is backward-compatible while the flag is `False`; PR0's operator-route hardening and force-release API migration take effect immediately.** The blast radius of the immediate half is small — measured, the only callers of force-release are 6 backend tests and there is no workspace UI (§3.8) — but *small blast radius is not unchanged behaviour*, and conflating them is how an API break reaches a release note that says "no behavior change." The distinction costs one sentence and buys an accurate rollout claim.

**Why PR2 is last.** Its failure mode is a *deadlocked* merge, not a *bad* merge. If PR2 slips, autonomy is strictly safer than today rather than blocked on provisioning.

**PR2 grew a responsibility in revision 4.** Deck now opens the PR itself (§5.5.2), because `gh` in a pane provably cannot do it with App credentials. That moves one action from the agent to Deck, which is a larger change than revision 3 described — but it also *removes* §5.6's whole reason for existing on that path, since Deck no longer has an agent-supplied `pr_number` to distrust. Net, PR2 is a little bigger and materially simpler to reason about.

**And revision 5 makes that responsibility carry a cost revision 4 did not price.** Once Deck performs the `POST /pulls`, Deck owns its idempotency, and GitHub offers no idempotency key for pull creation. §5.5.4 pays that cost with a reconcile-by-head step and one new read method; §5.6a pays a second one, because Deck must now know per repository whether it *can* act as the App before it writes any credential config. Both are consequences of moving the action, not separate features — worth naming here so a reviewer sizing PR2 sees the whole of what §5.5.2 bought.

### 2.1 Exact PR boundaries for the shared attempt machinery

The ninth review's correction 7 is the last structural one, and it is right: `dispatch_head_ref`, `prepare_attempt`, and `attempt_head_ref` are all *argued* in the PR1 chapter while their loudest consumer — `pr_ready`'s head check — lives in PR2. Left implicit, an implementer either builds half of PR2 inside PR1 or ships a PR1 whose tests cannot run. So the assignment is stated here, normatively, and the rule that produces it is: **each artifact ships in the earliest PR that has a consumer for it, and every artifact's tests ship with the artifact.**

| Artifact | PR | Why that boundary |
|---|---|---|
| All **six** `github_work_items` columns, including `dispatch_head_ref` (§4.1) | **PR1** | One migration ladder edit, not two. Splitting a six-rung ladder across PRs means PR2 must re-check which rungs exist — and the ladder is idempotent by construction (`if work_item_columns and "x" not in work_item_columns`), so adding a column PR1 does not yet read costs nothing and cannot fail |
| `attempt_head_ref(item, slot_id)` — the composer | **PR1** | Called exactly **once**, by `prepare_attempt`, which is PR1's. A composer whose only caller is in PR1 belongs in PR1 |
| `prepare_attempt` — the atomic identity record (owner, routing, nonce, head, round 1) | **PR1** | PR1's own gate reads `dispatch_nonce` and `approval_round_count`; blocker 1's `owner_slot_id`/`routing_method` atomicity is what makes an owner-only report answerable at all. Not deferrable: without it PR1's `deck_request_context` linkage has nothing to link to |
| `attempt_state` (unprepared / prepared / partial) and the fail-closed branch | **PR1** | It is the guard on `prepare_attempt`'s own output. Same PR as the thing it classifies |
| Brief wording: the branch instruction naming the stored head, replacing `github_dispatch_service.py:410` | **PR1** | The brief is composed by PR1's prepared-attempt path. **The agent is told the branch one PR before anything checks it** — deliberately, and harmless: an unchecked instruction that agents follow is how PR2 arrives to a population already pushing conforming refs |
| `reset_for_retry` clearing the new columns, below the deferred-lease early return | **PR1** | It clears columns PR1 adds. Note the shipped function already returns early while a lease is held and already zeroes `approval_round_count`, so PR1 extends an existing sequence rather than inventing one |
| §4.6a's `POST .../claim-continuation` + `deck_get_work_item_context`, and `initiate_handoff`'s owner check | **PR1** | It delivers `approval_round_count`, the stored head, and the lease token — and the split-authority deadlock it repairs (§4.6a) exists in **shipped** code today, independent of PR2. Its write-side half must ship in the same PR as its read-side half, because a read-side owner check on a column any caller can currently write authorizes nothing |
| **`require_session_slot`** — the dependency that resolves `X-Deck-Session-Token` to `(session, member, slot_id)` and confirms the pane binding | **PR0**, and it is a **hard prerequisite of PR1** | Stated as a row because leaving it implicit is what produced blocker 1: revision 10 measured "no capability token exists on the dispatch surface" and wrote that into PR1, which lands *after* PR0 supplies one. PR1's claim route, `initiate_handoff`'s owner check and §3.5a's whole matrix are all authorization theatre without it. An implementer who takes PR1 in isolation must be told, here, that the authority they need already exists one PR back |
| **`require_operator`** — the `X-Deck-Operator-Token` dependency (§3.6a) | **PR0** | Revision 11 put this in PR1 and the eleventh review's blocker 1 moved it, correctly, for a reason that is a measurement rather than a preference: the two defects it addresses are **live on `master` right now**. Force-release is unauthenticated and its mismatch response discloses the live lease token (measured end to end, not merely in the f-string), so the oracle is exploitable today by any local process, with or without PR1. A fix for a shipped hole does not wait behind two feature PRs. It is also the row that makes the PR0/PR1 split coherent: PR0 supplies **both** credentials — `require_session_slot` for agents, `require_operator` for humans — and PR1 consumes them |
| Force-release's contract change: `expected_lease_token` → `force: Literal[True]` + `expected_leased_at`, and `lease_token` leaves `GithubWorkspaceResponse` (`schemas.py:2245`) and `_workspace_response` (`agent_teams.py:185`) | **PR0**, moved from PR1 | These are one change, not two, and revision 11 split them across the fork it left open. The projection exists *because* force-release requires the token; remove the requirement and the projection has no remaining consumer, so both sides move together or neither can. **PR0 for the same reason as the row above** — the disclosure is live. Note this reverses revision 11's PR1 assignment and its stated justification ("PR1 is the PR whose authorization is decorative without it"), which was true of the *deletion* considered alone and false once the deletion became possible: after PR0, nothing agent-reachable projects the token, so PR1's authorization is not decorative, it is simply later |
| The **operator token setting** (`operator_token`, `.env` only, `503` when unset) and the **release-note split** between PR0's inert mail half and its immediate operator half | **PR0**, with the code that reads it | Stated as its own row because it is the row that was missing: revision 12 assigned three immediate behavioural changes to PR0 while three separate places still claimed PR0 changes nothing (§3.2, §4.6a, criterion 11). The setting is not a configuration detail here, it is the difference between a deployed PR0 whose operator routes work and one that serves `503` on both — and the fix for that (`export`, restart) is the one §3.6a forbids, for a measured reason. An implementer who reads only §2.1 must learn from this row that PR0 has a deployment prerequisite |
| Force-release's **compare-and-release write**: one conditional `UPDATE` keyed on workspace id + scope id + captured `leased_item_id` + `expected_leased_at` + the server-captured `lease_token`, clearing all seven release-state columns at one `now`, issued after `pending_work`, exactly one affected row or `409 lease_changed`; plus `force: Literal[True]` | **PR0**, with the contract change above | The same PR as the schema change, and for the reason the twelfth review's blocker 2 gives: shipping the new *body* without the new *write* is a route that asks for an optimistic-concurrency value and then does not have one. Measured, the natural port destroys a replacement acquisition, and the existing `release(db, item_id)` helper is not workspace-scoped, so it clears a lease on a workspace the operator never inspected (§4.6a). Note this is the row that makes PR0's force-release work a *rewrite* of the route body rather than a swap of two fields — relevant to sizing, since §3.8 lists 6 tests that call it |
| The **agent release write**: `release_by_owner` — one conditional `UPDATE` binding workspace row + `leased_item_id` + `lease_token` + an `EXISTS` predicate on the *derived* owner, clearing the same seven columns, with three sequenced paths and **four** outcomes rather than a two-row result table — path A alone returns either `200` or `403` depending on whether ownership moved while its own lookup was in flight (§4.6a.1 requirement 5); **and the contact stamp rewritten as one owner-and-token-conditional `UPDATE`**, which is not behaviour-preserving on a NULL-token lease and is deliberate (requirement 8) | **PR1**, moved out of §7 | Revision 13 deferred this on a severity argument measured at the wrong boundary (§7 records the withdrawal). It is PR1's for a reason that is not sizing: **PR1 is the PR that claims a retained lease token grants an ex-owner nothing** (criterion 30), and that claim is exactly what this write is the proof of. Measured, a token-keyed predicate matches `1` row after a handoff and the same predicate plus the owner clause matches `0` — so PR0's token atomicity, which stops a replacement *acquisition*, cannot stop an admitted ex-*owner*. It also needs `require_session_slot`'s derived slot, which is PR0's. PR0 may factor out a shared conditional-update helper; PR1 does not require one to exist |
| §4.2b.2's `POST .../resume-attempt`, behind `require_operator` | **PR1** | It is the only route out of `prepared_owner_unavailable`, which PR1 introduces. Measured: `dispatch_pending` selects `pending` by equality, so PR1 without this endpoint ships an escalation with **no** exit that preserves the attempt — the sole existing route to `pending` clears `approval_round_count` and `last_verified_sha` (§4.2b.1). An escalation whose recovery ships later is an escalation with no recovery. The route is PR1's; the dependency it hangs on is PR0's |
| `accept_handoff` setting `leased_owner_pid` / `leased_owner_proc_start` / `lease_last_owner_contact_at` from the verified pane, in one transaction with `owner_slot_id` (§4.6b) | **PR1** | It reads `require_session_slot`'s output, so it cannot ship before PR0 — and it must not ship *after* PR1's handoff authorization, because the two are the same transaction. Measured: the HTTP route is the only production caller of `accept_handoff` (`agent_teams.py:311`), so this is one call site, not a service-wide change |
| **Grace mode is closed for `/dispatch-status`**: every call returns `409 tokens_not_enforced` while `mail_capability_tokens_required` is false, plus the deployment ordering (deploy PR0 → restart panes → enable enforcement → deploy PR1; autonomy off throughout) | **PR1** | This is the row that makes PR0's "behavior-preserving while deployed alone" and PR1's "identity is a hard prerequisite" both true instead of contradictory. PR0 alone must not break a shipped shim, so it keeps the fallback; PR1 is the point at which the fallback becomes a bypass, because `initiate_handoff` has no authorization of its own (`github_dispatch_service.py:689-695`). The refusal ships with the PR whose guarantees it protects, and the ordering ships as prose in the same PR because a correct implementation deployed in the wrong order exhibits exactly the bypass it removed |
| `pr_ready` and its head **check** (equality against the stored head) | **PR2** | `pr_ready` does not exist in `app/` today — grep-verified — and it is the branch that opens a PR. The *check* goes where the *branch* goes |
| `_classify_pull`, reconcile-by-head, per-repo auth mode, credential helper, commit identity | **PR2** | All GitHub-facing; none is readable by PR1's gate |

**"Independently green" is a claim about tests, not about authority, and revision 10 conflated the two.** PR1's tests run without PR2's routes existing — that is what the phrase means and it remains true. It has never meant PR1 stands alone: PR1 depends on PR0 for identity, and a reviewer reading PR1 in isolation and asking "where does the caller's slot come from?" must find the answer in the row above rather than concluding, as revision 10 did, that no answer exists. **The measurement that matters for a PR is taken against the tree that PR lands on, not against `master`** — one level up from [[invariant-evidence-freshness]], which is about the freshness of the data a rule reads; this is about the freshness of the codebase a design reasons about.

**What "PR1 is independently green" means concretely.** PR1 ships the columns, the composer, the preparation step, the state classifier, the brief wording, the reset semantics, the continuation claim, the resume route, and every test in §4.8 — including 11f and 37o, which assert the head survives a handoff. Those tests do **not** need `pr_ready`: 11f's final assertion is that the *stored* head equals the head the brief named and that the equality check would accept it, which is a comparison against a column, not a call into a route PR2 adds. Where a §4.8 test as drafted reads `pr_ready`, it asserts the comparison directly instead and §5.8's test 14 covers the route. That is the whole content of the boundary: **PR1 owns the record; PR2 owns the enforcement that reads it.**

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
    slot_id: Mapped[int | None]          # FK agent_team_slots, ondelete SET NULL, nullable
    preset_id: Mapped[int | None]        # FK agent_team_presets, ondelete SET NULL, nullable
    tmux_target: Mapped[str | None]
    created_at: Mapped[datetime]
```

**Both FKs are nullable, and revision 17's sketch was self-contradictory in writing them `Mapped[int]`.** `ondelete="SET NULL"` requires a column that can hold NULL, so the annotation and the FK argument described two different schemas. The convention is unanimous in this codebase — every `SET NULL` foreign key in `app/models/database.py` is declared `Mapped[int | None]` with `nullable=True` (`:36-37`, `:191-192`, `:256-265`, `:302-303`, `:356-357`), seven for seven. Corrected here rather than left to the plan because a nullable-vs-not decision on the column §3.3's whole binding rung reads is a design fact, not an implementation detail: a deleted slot must leave the binding row discoverable so the pane resolves to §3.3's *unbound* rung rather than vanishing, which is the fail-closed direction §3.3 chose everywhere else.

**The table is created by `create_all` and needs no migration rung.** `app/database.py:479` runs `Base.metadata.create_all`, which issues `CREATE TABLE` for any model without a table — so a **new table** is free, while a new **column on an existing table** needs the additive `ALTER` ladder (`:421-440`), because `create_all` does not alter. Stated because those two cases look alike in a diff and only one of them needs the ladder: PR0 adds a table (nothing to write) and PR1 adds columns (six rungs, §4.1).

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

§3.5 makes `reporting_slot_id` **derived** rather than claimed. The fourth review is right that this answers "who is calling" and leaves "may they do this" unanswered, and the gap is measurable: of the nine branches in `report_dispatch_status` **today**, exactly **one** compares the reporter to the item.

```python
# agent_teams.py:333-338 — the only authorization check in the whole endpoint
elif report.status == "workspace_released":
    if report.reporting_slot_id != item.owner_slot_id:
        raise HTTPException(status_code=409, detail="only the owner slot may release its workspace")
```

Every other branch reads `report.work_item_id` and acts. Deriving the slot from a token turns "any process with curl" into "any *registered agent*," which is a real narrowing and still not authorization — the population that matters here is other agents on the same team, and they are all registered. A Specialist can currently mark another slot's item `blocked`, accept a handoff aimed elsewhere (guarded only by `handoff_target_slot_id`, which is the one other comparison in the service), or report `pr_opened` on an item it has nothing to do with.

**The matrix.** Roles are: **owner** = `item.owner_slot_id`; **leader** = `_leader_slot(preset_slots)` (`github_dispatch_service.py:534-539`); **target** = `item.handoff_target_slot_id`. A row's authority is checked *after* the token resolves the caller's slot and *before* any state change.

The table covers **every** status the route accepts after this spec lands — the nine branches that exist today plus `pr_ready`, which §5.5.2 adds. That completeness is the point: a status absent from this table is unauthorized by omission, and revision 5 proved that failure mode by adding `pr_ready` to §5.5.2 and not to this table, while three later sections cited the table as its protection.

| Branch | Who may report it | Lease token | Refusal |
|---|---|---|---|
| `triaging` | owner | not required | `403 not_item_owner` |
| `in_progress` | owner | not required | `403 not_item_owner` |
| `blocked` | owner | not required | `403 not_item_owner` |
| `handoff_initiated` | **owner** only (see point 4a) | not required | `403 not_item_owner` |
| `handoff_accepted` | **target** only | not required | `403 not_handoff_target` (in addition to the existing `409` when `handoff_target_slot_id` disagrees) |
| `revision_requested` | **nobody** — retired as an agent-reportable status (§4.3a.1) | — | `409 use_deck_approve_work_item` |
| `ack_received` | owner | not required | `403 not_item_owner` |
| `pr_opened` | owner | **required** | `403 not_item_owner`; `409` on token mismatch |
| `pr_ready` | owner | **required** | `403 not_item_owner`; `409` on token mismatch |
| `workspace_released` | owner — enforced **in the write**, not only at the top of the route (§4.6a.1) | **required** (already enforced) | `403 not_item_owner` for a caller who is not the owner *when the request arrives* — measured, that request never reaches the write — and equally for one admitted with **no** lease to release and staled during path A's diagnosis; `409 lease_changed` only for a request that **captured** an acquisition as owner and lost it during execution (§4.6a.1 requirements 5–6) |
| unknown status | — | — | `400` (unchanged) |

Five points where the shape of that table is a decision rather than a transcription:

**1. `revision_requested` is nobody's, because a round advance is no longer a report.** Revision 5 made this row leader-only, which was the right instinct and the wrong mechanism: it left round advancement as a second, optional leader action that nothing obliged the leader to take, and §4.3a.1 then contradicted this row in prose. §4.3a.1 now makes the rejection itself advance the round, in one commit, so there is nothing left for this branch to do. It is retained in the route as an explicit `409` naming `deck_approve_work_item` — not deleted — because a shim released before this change still lists it in `deck_report_dispatch_status`'s docstring (`mcp_shim/agent_mail_server.py:612`), and an agent following that docstring deserves a message that tells it where the operation went. A silent `400 unknown status` would read as a Deck bug.

**2. `handoff_accepted` belongs to the target, not the owner.** The existing `ValueError` in `accept_handoff` (`:697-702`) compares the accepting slot against `handoff_target_slot_id` and does discriminate correctly — this row mostly makes an existing implicit rule explicit and gives it a `403` instead of a `409`. Keep both checks: the `403` says "you are not the target," the `409` says "there is no handoff to accept," and collapsing them loses the distinction an agent needs to act on.

**3. The lease token is required exactly where the branch reaches GitHub, which is both `pr_opened` and `pr_ready`.** Measured: `report_pr_opened` (`github_verification_service.py:44-86`) makes no GitHub call itself, but it sets `item.pr_number`, which is what admits the item to `process_scope`'s query (`:95-110`) and from there to `_verify_item` and `_promote_verified_item` — the merge. So `pr_opened` is the entry point to the write path even though it writes nothing itself. `pr_ready` is stronger still: it makes Deck call `GET /git/ref`, `GET /pulls`, and `POST /pulls` synchronously, so an unauthorized report burns rate limit and can create a public artifact. Requiring the current lease token on both means a stale attempt cannot inject a PR into a re-dispatched item, which is precisely the class of bug the lease token was introduced for in G2.

  **Order matters more on `pr_ready` than anywhere else in this table.** Both checks — owner, then current lease token — run before the first GitHub call and before any column is written. On the other branches an out-of-order check leaks a local mutation that a test can catch by reading the row; here it leaks a PR on someone's repository, which no rollback undoes. §5.8's test 17b asserts the mock was never invoked, and §3.5a's tests **7h** and **7i** assert the same rule from the authorization side — 7h for a non-owner slot, 7i for the owner with a dead lease. (Not 7f, which is the `pr_opened` branch: the sixth review caught the same mis-citation at §5.8's test 17b, and this was its second instance.)

  `in_progress` is **not** on the required list, because §5.6 removes its `pr_number` write entirely. If a future change restores that write, this row must change with it — noted here because the two facts are only safe together.

**4. `pr_ready` is owner-only.** The branch being turned into a PR was pushed by the owner's credential from the owner's leased worktree, and the lease token the row requires is the owner's. A leader holding no lease could not satisfy the second check anyway, so admitting them would produce a `409` that reads like a Deck fault instead of a `403` that states the rule. (Revision 10 argued this row by *contrast* with `handoff_initiated` — "the leader is admitted there because it is a management act on someone else's item, and creating a PR is not." Point 4a withdraws that contrast, so the row is now argued on its own terms, which is what it always rested on.)

**4a. `handoff_initiated` is owner-only too, and revision 10 said both.** The tenth review's blocker 2 is confirmed: this matrix said **owner or leader** with `403 not_owner_or_leader`, while §4.6a required the initiator to be the current owner with `409` otherwise, and §4.8's test 37r-2 required *any* non-owner to be refused. Tests 7b/7c enforce this matrix exhaustively, so the two families could not both pass — one of them would have failed on the implementer's first run, and which one depended on which section they read first.

Resolved **owner-only**, and the reason is not merely that one of the two had to go:

- A handoff transfers a **live workspace lease** along with the identity — that is the whole content of §4.6a and §4.6b. Under §4.6b the target must then prove a bound pane before the lease's liveness evidence is restored. A leader initiating a handoff *away from* an owner who may still be running does not know whether A has uncommitted work in the worktree, and nothing in the route can find out; `_worktree_is_quiescent` exists but is a backstop input, not a precondition anyone checks here. A leader-initiated handoff is therefore a workspace-safety decision dressed as a routing decision.
- The genuine need behind the leader row — *the owner is wedged and a human wants the item moved* — is an **operator** action, not an agent one, and it needs the safety check the agent route cannot perform. §4.2b.1's `prepared_owner_unavailable` recovery is the same need arriving from a different direction, and §4.2b.2 now specifies one operator endpoint that serves both, with an explicit live-pane check. Routing an operator repair through an agent's authorization matrix is what made this row look reasonable.
- Refusal code: `403 not_item_owner`, matching every other owner row. Not `409` — §4.6a's `409` was chosen when this was framed as a state conflict; it is an authorization outcome, and §3.5a is where authorization outcomes are named. §4.6a is amended to match rather than the reverse, because the matrix is the exhaustive artifact that test 7c enumerates.

§4.8's test 37r-2 keeps its shape and gains a sibling: the **leader** is also refused on this route (37r-2a). A test that only exercises an unrelated third slot would pass against an implementation that still admits the leader — which is precisely the implementation revision 10's matrix asked for.

**5. Everything else takes no token deliberately.** Requiring a lease token on `triaging` or `blocked` would break the one path that most needs to work: an agent reporting that it is stuck. `blocked` escalates to a human, and a gate that can refuse an escalation because a lease rotated is a gate that hides failures. Authority without a token is the right trade for reports that only ever *reduce* Deck's confidence.

**Where the check lives.** In `report_dispatch_status`, as a small resolver called once before the branch chain — not inside each service function. The services are also called from the monitor loop and from operator paths that have no reporting slot, and pushing agent authorization into them would either block those callers or grow an `if caller_is_agent` parameter through five signatures. The endpoint is the trust boundary; the check belongs at the boundary.

**What this does not fix.** `touch_owner_contact` runs in the endpoint tail for any report whose `reporting_slot_id` equals the owner's (`agent_teams.py:371-377`). With derived slots that is now honest, so no change is needed — but note it stamps contact evidence as a *side effect* of an authorized report, and its docstring already accepts a stale token as a no-op (`github_workspace_service.py:255-259`). That is consistent with point 4: contact evidence is not a gate input for merging, only for nudge timing ([[ack-is-liveness-not-approval]]).

**Tests** (offline, in §3.7's file since they are token-dependent):

7b. Each branch in the matrix, reported by a non-authorized slot ⇒ the stated `403`, and the item's columns are **unchanged**. Assert the state, not just the status code — a route that mutates then refuses returns the same code. **One exception, and it is not a hole:** `revision_requested` is retired (§4.3a.1) and refuses **every** caller with `409 use_deck_approve_work_item`, authorized or not. So the table this test iterates must carry the expected status per branch rather than a single `403` constant — a test hardcoding `403` fails on the one branch whose refusal is stronger than authorization.
7c. **The matrix is exhaustive.** Enumerate the route's accepted statuses from the branch chain itself and assert every one appears in the authorization resolver's table; a status the resolver does not know refuses rather than defaulting to allowed. This is the blocker-1 test in its general form: revision 5's `pr_ready` hole was one missing row, and a per-row test would have to be written for each future branch to catch the next one. Written to fail against a resolver whose fall-through is "no rule ⇒ proceed."
7d. `revision_requested` from **any** slot — owner, leader, or a third — ⇒ `409 use_deck_approve_work_item`, and `approval_round_count`, the five ack columns, and `dispatch_status` are all unchanged. This is the withdrawal-spam test in its final form: against revision 4 any agent could drive the counter to `max_approval_rounds`, and against revision 5 the leader could advance a round without deciding anything.
7e. `handoff_accepted` from a slot that is neither target nor owner ⇒ `403 not_handoff_target`; from the target ⇒ `200`. Both against an item whose `handoff_target_slot_id` is set, so the existing `409` path is not what produces the refusal.
7f. `pr_opened` from the owner with a **stale** lease token ⇒ `409`, and `item.pr_number` stays `NULL`. Then the same call with the current token ⇒ `200`. The `NULL` assertion is the point: if `pr_number` is set before the token check, the item enters `process_scope` and the refusal is cosmetic.
7g. `blocked` from the owner with **no** lease token ⇒ `200` and the escalation is recorded. Written to fail against an implementation that requires the token everywhere "for consistency."
7h. **`pr_ready` from a non-owner slot** holding *its own* valid lease on *another* item ⇒ `403 not_item_owner`, `item.pr_number` stays `NULL`, and the mocked client records **zero** calls — not even the `GET /git/ref` existence check. The foreign-but-valid lease is the point: an implementation that checks "is this token current for some workspace" instead of "does this token lease *this* item" passes a naive test and fails this one.
7i. **`pr_ready` from the owner with a stale lease token** ⇒ `409`, `pr_number` stays `NULL`, and again zero client calls. Paired with 7h so the two failure modes stay distinguishable: 7h is "wrong agent," 7i is "right agent, dead lease."

| Mutant | Test that must fail |
|---|---|
| authorization checked after the state change | **7b, 7f** |
| a branch with no matrix row falls through to allowed (revision 5's `pr_ready`) | **7c, 7h** |
| `revision_requested` still advances the round for the leader (revision 5) | **7d** |
| `handoff_accepted` authorized to the owner instead of the target | 7e |
| lease token required on every branch | **7g** |
| lease token dropped from `pr_opened` | 7f |
| lease token dropped from `pr_ready` | **7i** |
| lease validated as "current for any workspace" rather than for this item | **7h** |
| `pr_ready` authorization checked after the ref-existence call | **7h, 7i** — both assert zero client calls |

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
- On `401` the tab re-provisions **its own** key once and retries. With per-tab keys a `401` now means "my actor was pruned," not "another tab stole my slot." Once only, and only on `401`: a `403`, a `404` or a `500` must surface, because a retry loop on a non-auth error is indistinguishable from a hung UI.
- ~~The ack path uses the actor ack endpoint that already exists (`external_agent_mail.py:218`), so no new route is needed for §3.6's second write path.~~ **False, and it was the load-bearing claim of this section.** See §3.6b: every actor capability is scoped to threads the actor *created*, and the threads the operator needs to act in are the ones *agents* created. Revision 18 replaces this bullet with three route requirements.

**One consequence to accept:** per-tab actors accumulate rows in `mail_external_actors`. That is a cosmetic cost — the table has no unique constraint problem and the rows are inert once their `sessionStorage` dies. If the roster view becomes noisy, prune actors whose `last_used_at` is older than a threshold and whose key matches `deck-ui-*`. Out of scope for PR0; noted so a reviewer does not mistake it for an oversight.

**Remotely hosted Deck.** The loopback gate means this self-provisioning only works when the browser and the backend share a host — the normal case, and the only case Deck currently supports (CORS is pinned to `localhost:5173`). If Deck is ever served remotely, the frontend cannot mint its own actor and an operator must provision one out of band. That is a real limitation and it is recorded in §8 rather than solved here: solving it means real user authentication for Deck, which is a project, not a section of this spec.

### 3.6b The actor capability gap, and why the operator must not close it by becoming a member

Revision 17's §3.6 said the UI authenticates as an external actor and that its ack "uses the endpoint that already exists." The eighteenth review found that the PR0 plan had abandoned that design entirely: Task 10 widened the mail dependency to admit an operator credential and let the operator send an arbitrary `sender_member_id`, so a human typing in the browser produced a row indistinguishable from one an agent's authenticated session wrote. The review's recommendation is adopted verbatim — *preserve operator attribution and extend external-actor thread capabilities, not let the operator impersonate agent members* — and this section is the spec text that must exist before a plan may name it.

The plan's reasoning was not baseless; it rested on two measured facts and one inference that does not follow from them. **The facts.** An external actor cannot post `kind="answer"` today, and an external actor cannot reply in a thread it did not create. Both confirmed below. **The inference that fails:** that the operator must therefore post as a member. It fails because the operator's reply does not need to *be* an answer-of-record to be useful, and §4.3 rule 4 is precisely the rule that requires it not to be.

**The gap is wider than "answer," and in the opposite direction from the one §3.6 assumed.** Every actor capability compares `sender_actor_id` against the calling actor and refuses on mismatch — read (`_require_actor_owns_thread`, `external_agent_mail_service.py:396-402`), ack (`:339-340`), reply (`:258-259`). Measured on a thread an actor created and an agent answered, a *second* actor is refused all three:

```
tab A actor id=1  tab B actor id=2  distinct? True
tab A created root id=1 sender_actor_id=1 sender_member_id=None
agent answered -> root request_status='answered'

--- tab B (a NEW tab, same operator) on tab A's thread ---
  read  thread:    REFUSED -- PermissionError: External actors can only read threads they created
  ack   request:   REFUSED -- ValueError: External actors can only acknowledge requests they created
  reply in thread: REFUSED -- ValueError: External actors can only reply in threads they created
```

Two consequences, and the second is the one §3.6 missed.

1. **Per-tab actor keys and thread-scoped capability compose badly.** §3.6 provisions one actor row per tab, on purpose, so that tabs cannot rotate each other's token. Capability then follows the *tab*, not the operator: the same human in a new tab is a stranger to their own thread.
2. **The scope is backwards for the primary use case.** The operator's main job in this UI is replying to questions *agents* asked — `context_request` roots with `sender_member_id` set and `sender_actor_id = NULL`. For those threads, "threads they created" is an **empty** predicate. Relaxing ownership from "this actor" to "any actor" would not help; the requirement is to permit an actor into threads *no actor created at all*.

So the capability PR0 needs is not a loosened ownership comparison. It is a distinct, deliberately narrow permission: **an authenticated actor may participate in an agent-created thread, and participation never confers member identity.**

**The three route requirements.** Each replaces the deleted `:763` bullet, and each maps to one of the UI's three measured mail writes — compose (`AgentMailPage.tsx:174`), reply (`ThreadDialog.tsx:165`), ack (`ThreadDialog.tsx:137`); `updateAgentMailMember` at `:163` is member configuration, not mail, and is out of scope.

| | requirement | why it is not the existing route |
|---|---|---|
| **compose** | unchanged — the four `ComposeDialog` kinds already map 1:1 onto `send_direct_message`, `send_broadcast`, `send_context_request`, `send_handoff`, and none of their request schemas has a `sender_member_id` field at all (`schemas.py:1931-1948`) | no change needed; this is the row that shows how little of PR0's frontend work is new |
| **reply** | relax `reply_in_thread`'s refusal so an actor may reply in a thread whose root is **agent-created**, persisting `sender_actor_id` with `sender_member_id = NULL`. An actor may still not reply in another *actor's* thread | `:258-259` refuses every thread the actor did not create, which is every thread that matters here |
| **ack** | a new actor-scoped acknowledgement that records the actor's acknowledgement and writes **no** member `MailReceipt.read_at`, no `acked_at`, no `last_seen_at`, no `mailbox_status` | `acknowledge_external_request` (`:330-346`) refuses on the same ownership check, and the *member* ack (`agent_mail_service.py:1293-1295`) writes exactly the fields that must not move |

**Why the ack requirement is a safety rule and not tidiness.** `read_at` is the only mail field any dispatch service reads. Grep across `github_dispatch_service.py`, `github_workspace_service.py`, `github_watcher_service.py` and `agent_team_service.py` for `acked_at|read_at` returns exactly one hit — `github_dispatch_service.py:824` — and it is the return value of `_brief_delivered`, which gates the `brief_unread` escalation ladder at `:762-776`. Measured, a member ack sets it:

```
receipt before ack: [(None, None)]
receipt after  ack (read_at set?, acked_at set?): [(1, 1)]
```

So an operator ack that reached a member receipt would tell the dispatcher an agent had read a brief the agent has never seen — silently suppressing the escalation that exists to catch a dead owner. The cheap implementation is the unsafe one, which is why the prohibition is normative here rather than left to a plan. It is [[invariant-evidence-freshness]] in its most direct form: the rule is only as good as who is allowed to write the evidence.

Note the shape of the safety here, because it decides how much work this is. `authenticate_actor` writes exactly one column — `actor.last_used_at` (`external_agent_mail_service.py:117`) — and no member field. The actor path is therefore already clean by construction; the requirement is to *not* reach for a member receipt when adding the ack, not to retrofit isolation onto something leaky.

**An actor answer may move conversation state, and is not approval evidence.** An actor cannot post `kind="answer"` today, and the refusal comes from the shared member service rather than the external one — `send_message` compares `root.recipient_member_id != request.sender_member_id` (`agent_mail_service.py:859-860`), and an actor row has `sender_member_id = NULL`, so the comparison can never succeed:

```
(1) actor answer attempt:  ValueError: only the context request recipient can answer it
```

PR0 may relax that check to admit an actor-authored answer, and if it does, the answer may move the root to `answered`. Two bounds on that permission, both measured.

- **It creates no false dispatch evidence.** `request_status` is read by *nothing* in the four dispatch/workspace/team services — zero grep hits. It is conversation state, consumed by the UI and by `request_status`/`wait_for_request_status` for the actor's own polling. Moving a root to `answered` therefore cannot influence a dispatch decision.
- **It is not approval.** §4.3 rule 4 requires an `answer` whose `sender_member_id` equals the designated leader member's id. An actor answer has `sender_member_id = NULL`, so it fails that predicate by construction rather than by a check someone must remember to write. This is the invariant the feature is named for, and it is why the actor design is *safer* than the operator-as-member one it replaces: the operator cannot approve because there is no field in which their approval could be recorded.

**The reply must be routed to `None`, not to the root's recipient — and today's code gets this wrong.** `reply_in_thread` passes `recipient_member_id=root.recipient_member_id` (`:265`). On an agent-created `context_request` that is the member who was **asked**, not the member who **asked**, so the agent waiting for the operator's reply is the one member not notified of it. Measured:

```
(3) reply_in_thread passes recipient_member_id=2 (the member ASKED);
    the member who ASKED is 1. differ? True

(2) actor reply id=2 sender_member_id=None sender_actor_id=1 sender_type='external_actor'
    receipts: [(1, None, None), (2, None, None)]
    both participants notified? True
    current reply_in_thread routing notifies: [2] -- asker 1 included? False
    root request_status after two actor replies: 'pending'
```

Passing `recipient_member_id=None` instead selects `send_message`'s thread fan-out branch (`agent_mail_service.py:881-886`), which adds both of the root's participants and excludes `request.sender_member_id` — and that exclusion removes nobody, precisely *because* an actor's `sender_member_id` is NULL. The property the fan-out needs is the same NULL that makes the row unable to carry approval. **The amended reply requirement is therefore `recipient_member_id=None`, and an implementer who preserves the current argument ships a reply the asking agent never receives.**

**Attribution stays visible, and this part is already built.** `MailMessageResponse` carries `sender_actor_id`, `sender_type` and `sender_actor_kind` (`schemas.py`), `_sender_identity` returns `(actor.display_name, "external_actor", actor.kind)` (`agent_mail_service.py:957-971`), and `ThreadDialog`'s `MessageBlock` already renders both the name and a `sender_type` badge (`:72-78`). No new response field and no new table is needed for the reply or the answer. **If an implementation finds it needs either — in particular an actor-receipt table for the ack — this spec must name it before the plan does; the plan may not invent persistence.** For the ack as specified, no new table is required: the acknowledgement is recorded on the root's `request_status`, which is where `acknowledge_external_request` already records it.

**What stays out of the browser.** `operator_token` is not placed in Agent Mail's `sessionStorage` and no Agent Mail route requires it. It remains the credential for force-release and the workspace listing (§3.6a) — routes with no frontend caller today (§7). The two credentials answer different questions and were never in competition: an **actor** token buys actor-authored mail writes, which carry no authority by construction, so a pane minting one gains nothing; the **operator** token gates destructive and topology routes, where the minting measurement in §3.6a is fatal. §3.6a's conclusion that "the external-actor token cannot be the operator credential" is correct and is *not* an argument for handing the browser the operator credential instead. Deck's UI holds the narrow credential for the narrow job.

### 3.6a "Operator only" needs a credential, and the external-actor token is not it

Revision 11 wrote §4.2b.2 as "operator only" and implemented that phrase as *absence* — no dependency, on "the same unauthenticated-but-human surface as force-release." That is not an authorization rule. This spec's own threat model has every pane holding `curl` and reaching the loopback backend (§1.6, §3.3), so omitting a route from the MCP shim decides which tools an agent has, not which URLs it can POST. **Confirmed and worse than the eleventh review states**, in three measurements.

**1. `agent_teams.py` has no authentication at all.** Not "force-release is unauthenticated" — grep for a non-`get_db` dependency across the file returns **zero**. All 27 `Depends(...)` are `Depends(get_db)`. So there is no operator surface to put a route "on"; the phrase named a surface that does not exist.

**2. Force-release is a token oracle.** The mismatch branch interpolates the *live* lease token into the message (`agent_teams.py:695-696`), and `_conflict` (`:84-88`) nests it under `detail.message`, which FastAPI serialises verbatim. Driven through the real ASGI app with a deliberately wrong token:

```
POST force-release with a WRONG token -> HTTP 409
  {"detail":{"message":"Lease token mismatch: expected i-am-guessing,
   current LIVE-SECRET-abc123. Refresh and re-check before forcing.",
   "block_code":"lease_token_mismatch"}}
  live lease token present in the response: True
```

Two unauthenticated calls — guess, read, replay — force-release any agent's workspace. This also **refutes §4.6a's claim** that the `:569` listing projection is the only way the token can be learned: the error path is a second disclosure channel, and it is the one nobody audits. The correct pattern already exists one file over: `release_by_token` refuses with `"lease_token does not match the current lease for item {item_id}"` (`github_workspace_service.py:191-193`) — the item id, never the secret. **A mismatch message must never contain either the supplied or the stored value; the caller already knows what it sent, and the whole point is that it must not learn what it did not.**

**3. The external-actor token cannot be the operator credential.** §3.6 uses it for the UI, so it is the obvious candidate, and it fails for a measured reason: `POST /external/agent-mail/actors` gates only on `_is_loopback_request` (`external_agent_mail.py:76-78`), and an agent pane *is* a loopback caller. Measured, with no credential presented at all:

```
POST /api/v1/external/agent-mail/actors (NO credential) -> 200
  token minted: True (len 43)
  GET /actors/me with it -> 200, kind='supervisor'
```

An agent mints its own "supervisor" actor in one call. **An authentication scheme is only as strong as the cheapest way to obtain a credential**, and here that way is an unauthenticated POST. The loopback gate excludes remote callers; every adversary this spec models is local.

**Read this measurement for exactly what it bounds, because the PR0 plan over-read it and inverted §3.6 as a result.** It says a self-minted actor token cannot gate a route whose authority the minter must not have — force-release, the workspace listing, `resume-attempt`. It does **not** say the actor token is worthless, and it is not an argument against §3.6's use of it for mail. The reason is that the two routes buy different things. An actor token buys only *actor-authored* writes: `sender_member_id` is NULL on every row it can produce, the external request schemas have no such field to set (`schemas.py:1931-1948`), and `send_message` refuses a row carrying both a member and an actor sender (`agent_mail_service.py:849-850`). So a pane that mints one gains the ability to say something *as an external tool* — which it could already do by asking its own member session — and gains no slot identity, no dispatch-reporting authority, no approval and no lease authority. The escalation this measurement describes has nowhere to escalate *to* on the mail routes. **Two credentials for two route families were never in conflict**; §3.6b states the separation and §3.7's test 20 keeps this row honest by minting a real token rather than fabricating one.

**The requirement.** PR0 ships a second dependency beside `require_session_slot` — `require_operator` — reading `X-Deck-Operator-Token` and comparing it with `hmac.compare_digest` against a value from `settings`. No header, or a mismatch ⇒ `401 operator_token_required` / `401 operator_token_invalid`. It is a sibling of `require_session_slot`, not a variant: one authenticates agents by what the kernel says about them, the other authenticates the operator by a secret agents are not given.

PR0 applies it to **force-release** and to the **workspace listing**; PR1 applies it to **`resume-attempt`** (§4.2b.2). Tests are §3.7's 20-22 for the PR0 routes and §4.8's 37n-11 for the PR1 one, per §2.1's rule that a test ships with its artifact.

**The credential's full contract, because "one setting" is not deployable.** Revision 12 named the mechanism and left five things an implementer would have to invent. Each has one answer:

| | |
|---|---|
| the setting | `operator_token: str = ""` in `Settings` (`config.py`), so pydantic-settings reads it from `.env` as `operator_token` (`case_sensitive=False`, `:11`). **Not** `deck_operator_token`: there is no `deck_` prefix anywhere in the existing 24 settings, and `env_prefix` is unset, so the review's recommended name would read `DECK_OPERATOR_TOKEN` and match nothing the file's own convention produces. Note the trap the *existing* names set: `github_token` binds `GITHUB_TOKEN`, which is the variable GitHub Actions injects automatically — a collision this spec inherits and does not fix, and the reason to check a proposed name against the loader rather than against taste |
| generation | at least 32 random bytes, e.g. `openssl rand -hex 32`. Stated as a floor because `hmac.compare_digest` protects the comparison and nothing protects a short secret from being guessed at loopback speed |
| where it lives | `backend/.env`, mode `600`, gitignored — **never exported**, for the measured reason two paragraphs down |
| unconfigured | the empty default must refuse **every** request, and it must refuse *distinguishably*: empty setting ⇒ **`503 operator_token_unconfigured`**, so an operator who forgot the step gets a diagnosis instead of debugging their own header. Configured but no header ⇒ `401 operator_token_required`; configured but wrong ⇒ `401 operator_token_invalid`. **An empty header must never compare equal to an empty setting** — with `hmac.compare_digest("", "")` returning `True`, the unconfigured install would authorize every caller, which is the precise inversion of the fail-closed intent, and it is why the empty case is checked *before* the comparison rather than left to it |
| rotation and reload | `settings = Settings()` is constructed at **import time** (`config.py:57`), so the value is read once per process. Replacing it therefore requires a **backend** restart, and after that restart the old value is dead with no overlap window — acceptable here because the population holding the old token is one human, not 150 live panes. **Say this in the same breath as the pane restarts, because they are different restarts for different credentials:** panes restart to obtain *session* tokens (§3.4); the backend restarts to load the *operator* token. An operator who reads "restart the panes" and stops has provisioned nothing |

This is also the row that makes the `503` more than a nicety: an unconfigured install has *no* working operator route, so force-release and the workspace listing are unreachable until the setting exists. That is the correct posture — a destructive route with no credential should be closed, not open — but it is a real change for anyone who deployed PR0 without reading the notes, which is why §2.1 now lists it as an immediate behavioural change rather than filing it under "inert."

Note what the listing row does *not* mean. Revision 11's version of this requirement said "any workspace projection carrying `lease_token`", and after §4.6a's decision no projection carries it — so read literally, that clause guards nothing. The listing is still gated, for a different and smaller reason: it enumerates every workspace's path, lease holder and dispatchability, which is reconnaissance for choosing a force-release target, and there is no agent workflow in this spec that reads it (agents learn their own workspace from the brief and from §4.6a's claim). Gating it costs nothing and removes the survey step. **Stated separately because the two rows are now justified differently** — force-release because it mutates and used to leak, the listing because it discloses topology — and a single sentence covering both would leave an implementer who deletes the projection believing the listing no longer needs the dependency.

The disclosure removal in (2) is independent of all of this and lands in PR0 regardless, because it is a deletion with no consumer.

**What this credential is worth, stated honestly, because the eleventh review's amendment overstates it.** The review says a token "configured outside agent panes" suffices. On this host that phrase has no referent, and the measurement is the same one §6 already accepts for co-resident compromise:

| | |
|---|---|
| backend uid vs pane uid | **identical** — both `juan` (pid 2206652 and every pane pid) |
| `hidepid` in `/proc/mounts` | **absent** |
| `/proc/2206652/environ` readable by a pane | **yes — 114 entries** |
| `backend/.env` | mode `600`, owner `juan` — and the pane *is* `juan` |

So a determined pane can read the operator token from the backend's environment or its `.env`, whichever holds it. **The credential is therefore not a boundary against a co-resident adversary; it is a boundary against an opportunistic one.** It moves the attack from *knowing a URL* — which every agent does, since this spec publishes them — to *deliberately reading another process's memory or a `600` file*, which is a different kind of act: it cannot happen by an agent improvising, and it is the specific residual §6 scopes out and refers to OS-level isolation. That is worth shipping, and it must not be written up as authentication of a human. **§8's criterion says "not reachable by an agent following its brief," not "not reachable by an agent."** Overclaiming here would be this spec's own [[check-name-vs-discriminating-power]] defect, one layer up: a dependency named `require_operator` that a reader assumes excludes agents, when what it excludes is agents that have not gone looking.

**And the deployment note that follows from it:** the token must not be placed anywhere the launch path passes into panes. Measured, `spawn_session` builds `tmux new-session -e KEY=VALUE` flags from `platform_env` plus `extra_env` (`agent_bridge/spawn.py:74-80`), so a pane's environment is an allowlist, not an inheritance — the token is absent from panes by default and stays absent as long as nobody adds it to either dict. `pty_relay.py:98` does `os.environ.copy()`, but that is the operator's own attach path, not a pane launch.

**The allowlist claim is true of the pane's environment and false of the tmux server's, and that decides where the token goes.** The paragraph above was measured on the `-e` flags and is correct about them, but it stops one layer short of the question it is answering, which is *what a pane can read*. `spawn_session` calls `subprocess.run(["tmux", "new-session", ...])` with **no `env=`** (`agent_bridge/spawn.py:78-83`), so the tmux client inherits the backend's whole environment, and if that client starts the server the server keeps it as its **global** environment — which every pane can read back with one documented command. Measured on a throwaway socket (`tmux -L`, so no live session was touched), with a sentinel variable exported to the spawner:

```
sentinel exported to the process that ran `tmux new-session`
  pane's own /proc/self/environ                 -> 0 matches   (the -e allowlist holds)
  `tmux show-environment -g SENTINEL` in a pane -> SENTINEL=sentinel-do-not-use-12345
  `tmux show-environment -t <session> SENTINEL` -> unknown variable
```

And the live server already carries six secret-shaped keys this way (`CHANGELOG_GITHUB_TOKEN`, `GEMINI_API_KEY`, `TIZONIA_COVERITY_SCAN_TOKEN`, `TIZONIA_BINTRAY_API_KEY`, `DEB_SIGN_KEYID`, plus one more), so this is the host's actual behaviour and not a hypothetical. `update-environment` does not help: it lists eight variables, all of them `DISPLAY`/`SSH_*`-class, and it governs what an *attaching client* refreshes, not what the server inherited at start.

This matters because it is **the exact bound the section above claims**. Reading the token out of `/proc/2206652/environ` is "deliberately reading another process's memory"; running `tmux show-environment -g` is not — it is one documented command, in a shell every agent has, against a server the agent is already living inside. Had the token been exported to the backend's environment, the honest bound would have collapsed from *opportunistic adversary* to *no adversary at all*.

So provisioning is a requirement, not a runbook note: **the operator token lives in `backend/.env` and is never exported into the backend's process environment.** Measured, that is strictly safer rather than merely equivalent — `pydantic-settings` reads `env_file` without writing to `os.environ`:

```
.env holds probe_secret=from-the-env-file
  settings value read                  -> 'from-the-env-file'
  key present in os.environ afterward  -> False
  any os.environ key holding the value -> []
```

The value is therefore absent from the backend's `environ`, absent from the tmux global environment, absent from pane environments, and readable only from a `600` file. The eleventh review offered "the backend-only environment or `backend/.env`" as interchangeable; they are not, and the difference is one `tmux show-environment -g` away. `backend/.env` is already `600` and gitignored (§6), so this adds no new mechanism — it adds the reason the existing one must be used, and a prohibition on the obvious alternative.

### 3.7 Tests

With `mail_capability_tokens_required = True` unless a test says otherwise.

1. Registration returns a token; the hash is stored and the plaintext is not.
2. `POST /messages` without a token ⇒ `401`.
3. With a valid token ⇒ `sender_member_id` equals the token's session member, even when the body omits it.
4. With a valid token and a *conflicting* `sender_member_id` ⇒ `403`.
5. The forgery from §1.5 — posting an `answer` claiming to be another member — ⇒ `403`. Written directly from the live self-ack shape.
6. An external actor's token can still send, and lands in `sender_actor_id` with `sender_member_id = NULL`.
7. `POST /dispatch-status` derives `reporting_slot_id` from the token; a body claiming a different slot ⇒ `403`.

The actor thread capability (§3.6b). These are the eighteenth review's eight required discriminating tests, and they are numbered under 6 because they extend that test's subject rather than PR0's token model:

- **6a. Compose stays actor-authored.** The UI actor composes each of `ComposeDialog`'s four kinds and every stored row has `(sender_member_id = NULL, sender_actor_id = <actor>)`.
- **6b. Reply into an agent-created thread stays actor-authored.** An agent creates a `context_request`; the actor replies; the reply row has `sender_actor_id` set and `sender_member_id = NULL`. **Assert the receipts, not only the row:** both thread participants receive one, because the reply is routed with `recipient_member_id=None`. A reply routed the way `reply_in_thread` routes it today notifies the member who was *asked* and not the member who *asked* (measured, §3.6b), and a test that asserts only the row's authorship is green against that defect.
- **6c. An actor answer moves conversation state and fails the approval predicate.** If PR0 admits the actor `answer`, the root reaches `answered` **and** PR1's leader-approval predicate rejects it. Assert both halves in one test: the first alone would let an implementer conclude the answer counts, the second alone would not prove the capability exists.
- **6d. The actor ack touches no member evidence.** Before/after snapshot over the recipient's `MailReceipt.read_at` and `acked_at`, the member's `last_seen_at`, and `mailbox_status` — all unchanged. **The discriminating assertion is `read_at`**, because `_brief_delivered` reads exactly that field (`github_dispatch_service.py:824`) and a member-receipt implementation of this ack would suppress the `brief_unread` ladder. Pair it with the positive half so the test cannot pass by acking nothing: the root's `request_status` does reach `acknowledged`.
- **6e. An actor token cannot buy a member-authored row.** Present a valid actor token *and* a body carrying `sender_member_id`. The row must not be member-authored. Note where the guard already is — `send_message` refuses a row with both senders (`agent_mail_service.py:849-850`) — so this test is a regression lock on an existing invariant, and it is the test that would have caught the design this section replaces.
- **6f. A self-minted actor token grants nothing beyond actor-authored mail.** Mint one with no credential (§3.6a's measurement), then assert it buys **no** member identity, **no** slot identity, **no** `POST /dispatch-status`, **no** approval, and **no** lease authority. Mint it rather than fabricating one, for §3.7's test-20 reason: if that route ever gains a credential, this test should stop building.
- **6g. Two tabs do not evict each other.** Provision two distinct `deck-ui-*` keys; both tokens authenticate afterwards. This is the revision-3 defect §3.6 fixed, kept as a test because the fix lives in the frontend key generator where nothing else guards it.
- **6h. Re-provision once on `401`, and not on anything else.** A pruned/invalid actor token re-provisions once and the retried write succeeds; a `403` or a `500` surfaces without a retry. The negative half is the point — an unbounded retry is [[bounded-retry-only-on-paths-through-the-counter]] in the browser, where the only symptom is a UI that appears to hang.
- **6i. The relaxation is scoped to agent-created threads, not to all threads.** A *second* actor attempting to reply in the first actor's thread is still refused. **This test is an addition to the review's eight, and the mutation table says why it is needed:** all eight use a single actor, so an implementation that relaxes ownership to "any actor may reply in any thread" — the shorter edit, one deleted comparison instead of a conditional one — passes every one of them and hands every browser tab access to every other tab's threads. The requirement in §3.6b is *agent-created*, and this is the only case that can tell the two relaxations apart.

**One caveat on 6b, 6d and the ownership scope generally.** §3.6's per-tab actor keys mean capability follows the tab. Write 6b and 6d against a thread the *agent* created, not one the test's own actor created: an actor-created root satisfies the existing ownership check by construction, so those tests would pass without the relaxation they exist to verify. Measured, a second actor is refused read, ack and reply on the first actor's thread (§3.6b) — which is the shape a fixture falls into if it provisions the actor and the thread together. This is [[requirement-with-no-failing-case]]: the case must be the one where the two identities differ.

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

Operator authentication (§3.6a). These are PR0's because the routes they guard are PR0's — force-release's disclosure is live on `master`, not introduced by this spec:

20. **`require_operator` refuses every credential an agent can obtain, and an unconfigured install refuses distinguishably.** For **each** of force-release and the workspace listing, eight cases. The first two set `operator_token = ""`; the rest configure it:

    | Caller | Expected |
    |---|---|
    | **setting empty**, any header or none | `503 operator_token_unconfigured` — and assert the **code**, not merely a 4xx/5xx. This is the row that catches the natural implementation: with the empty case left to the comparison, `hmac.compare_digest("", "")` returns `True` and an unconfigured install **authorizes every caller** while its source still reads fail-closed. The mutant is not a refusal with the wrong status, it is an admission wearing a refusal's shape, which is why the empty check must precede the comparison (§3.6a) |
    | **setting empty**, an *empty* `X-Deck-Operator-Token` header | `503`, not `200`. Written as its own row because it is the exact input that makes the mutant above fire, and a suite that only ever sends a non-empty header never reaches it |
    | no `X-Deck-Operator-Token` header at all | `401 operator_token_required` |
    | a wrong operator token | `401 operator_token_invalid` |
    | a **prefix** of the real token, and the real token plus one trailing byte | `401 operator_token_invalid` for both — these are the rows a `startswith`, `in`, or truncating comparison fails, and they are the executable half of the review item §3.7's mutation table has to leave to review for `hmac.compare_digest` itself |
    | a valid **agent session token** in `X-Deck-Session-Token`, no operator header | `401 operator_token_required` — an agent's own credential must not admit it to an operator route. This is the assertion that fails if someone "unifies" the two dependencies on the grounds that both authenticate somebody |
    | a **self-provisioned external-actor token** — mint it in the test with `POST /external/agent-mail/actors` and present it | `401`. Measured: that mint needs no credential at all and returns a working 43-character `kind='supervisor'` token. It is the cheapest escalation on the host and the one an implementer is most likely to mistake for operator auth, because §3.6 already uses it for the UI. **Mint it rather than fabricating one** — if a later change adds a credential to that route, this test should start failing to build, which is the signal that §3.6a's argument needs re-measuring |
    | the configured operator token | `200`/`204` — the positive control, without which a dependency that refuses everything passes every row above |

21. **Force-release no longer names a lease token, and the listing no longer projects one.** §4.6a's decision, asserted as a schema fact rather than a behaviour: `GithubWorkspaceForceReleaseRequest` has no `expected_lease_token` field, and the workspace listing's response body contains **no** `lease_token` key for any caller, operator included. The operator credential is not a licence to keep projecting the secret — it was the *requirement* to replay it that made the projection necessary, and 20 without 21 would pass an implementation that merely put the oracle behind a password.

22. **The optimistic-concurrency check bites, and its failure discloses nothing.** With `force: true` and an `expected_leased_at` that does not match `workspace.leased_at` ⇒ `409 lease_changed`, the lease **unchanged**; with a matching value ⇒ released. Then the disclosure assertion, which is the one that carries §3.6a's finding: the `409` body contains neither the stored `lease_token` nor any 43-character opaque string. Written as a substring assertion over the whole serialised response, not over the message the implementation intended to build — measured, the live disclosure reaches the wire through `_conflict`'s `detail.message` nesting, so an assertion that reads only the top-level `message` misses it.

    **And the case the stale-value check cannot see, which is the one §4.6a's contract exists for.** The two cases above both present their value at request start, so both pass against a route that compares at the top and writes at the bottom — the shape that has the ABA race. So drive the interleaving: stub `pending_work` (or `_runner`) to suspend, and while it is suspended **release the workspace and reacquire it for the same item id** with a new `leased_at` and a new token; resume the request. Assert `409 lease_changed`, the replacement lease **intact** (`leased_item_id` and `lease_token` both still the replacement's), and no success line logged. Measured against today's code, the replacement is cleared:

    ```
    checked  leased_at=16:37:39.341 token='ACQ-1-aaa'
    replaced leased_at=18:37:39.349 token='ACQ-2-bbb'
    after    leased_item_id=None    token=None
    ```

    Then the **cross-workspace** case, because the release predicate is not workspace-scoped: two dispatchable workspaces, the operator inspects X, and during the suspension the item's lease moves to Y. Assert Y's lease survives. This is the case that distinguishes a fix keyed on "the same acquisition of this item" from one keyed on the workspace row, and only the second is correct — measured, `release(db, item_id)` clears Y when the operator confirmed X.

    Both cases assert on rows **read back with raw SQL**, not on the ORM objects the request held: with `expire_on_commit=False` in the fixture, a stale identity-map object can report the pre-release values and turn a real clearing into a passing test. Also assert the **affected-row count is exactly one** on the positive path. That is meaningful rather than tautological, and for the reason revision 13 mis-stated: the bound is `id` being the **primary key**, measured at `1` row where the same statement keyed on `scope_id` measures `2`. `UNIQUE(leased_item_id)` (`database.py:319`) is what makes the *many*-rows case unreachable, which is a different fact and is why no defensive branch is needed for it.

    **The same-timestamp case, which is why the captured token is mandatory rather than optional.** Two acquisitions can share a `leased_at`: measured, `datetime.utcnow()` returned equal values for back-to-back calls **63 098 times in 200 000 pairs**, and the column carries neither a UNIQUE constraint nor any monotonicity guarantee. So drive the interleaving again with the replacement acquisition given the **identical** `leased_at` as the one the operator inspected and a **different** `lease_token`. Assert `409 lease_changed` and the replacement intact. Against a predicate that omits the token this is a `200` and the replacement dies while every other case in this test still passes — which is exactly the shape revision 13's "may be added as a further discriminator" would have shipped. Write the timestamp explicitly rather than hoping for a natural collision, and assert alongside that microseconds survive the round trip (`'…12:00:00.123456'` read back verbatim), since a predicate comparing a truncated value would fail the positive path for an unrelated reason and mask this one.

    **And the release-state reset, which is the assertion that catches a partial port.** On the positive path assert **all seven** columns `release()` clears are cleared (`github_workspace_service.py:155-165`): `leased_item_id`, `released_at`, `lease_token`, `leased_owner_pid`, `leased_owner_proc_start`, `lease_last_owner_contact_at`, `lease_release_reminded_at` — plus `released_at` and `updated_at` carrying the **same** timestamp. Enumerate them; do not assert "matches what `release` would do," because the implementation under test is the thing that replaced `release` on this path. The columns an implementer drops are the liveness ones, and a row with a NULL `leased_item_id` and a stale `leased_owner_pid` is the shape §4.6b exists to prevent.

    Finally, `force`: send `force: false` and an otherwise valid body ⇒ `422`, with the lease **unchanged**; and omit `force` entirely ⇒ `422`. `Literal[True]` makes both refusals validation-level, so the test is pinning the schema rather than a branch — which is the point, since a route that ignores the field passes every other case in this test.

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
| the operator dependency accepts the external-actor token, or any authenticated caller | **20** |
| the operator token compared with `startswith` / `in` / a length-truncating slice | **20**'s prefix and trailing-byte rows |
| force-release keeps `expected_lease_token`, moved behind the new dependency | **21** — authenticating the operator does not stop the operator having to read the agent's live bearer credential out of a projection to call the route at all |
| the mismatch response is "tidied" to print only the supplied token | **22** — the supplied value is asserted too: an attacker's own guess echoed back confirms nothing, but an operator's mistyped paste of a real token is still a secret in a log |
| `expected_leased_at` accepted but never compared (`force: true` alone releases) | **22**'s mismatch case — the optimistic-concurrency value becomes decoration and the operator overwrites a lease that changed under them |
| `expected_leased_at` compared at the top of the route, then released by item id (the natural port of today's code) | **22**'s interleaving case — the check passes against a value that was true when read and false when written, and the replacement acquisition is destroyed. Measured, and note *why* the row is needed: the mismatch case above is satisfied by exactly this implementation, so without the interleaving the mutation is invisible |
| the conditional write keyed on `leased_item_id` alone, without the workspace id (i.e. `release(db, item_id)` with a `WHERE leased_at` bolted on) | **22**'s cross-workspace case — `release`'s selector has no workspace or scope predicate (`github_workspace_service.py:148-152`), so the operator confirms X and clears Y. The narrower-looking mutant is the one an implementer reaches for, because it reuses the existing helper |
| the captured `lease_token` omitted from the predicate, leaving `expected_leased_at` as the only acquisition discriminator (revision 13's "may be added") | **22**'s same-timestamp case — and *only* that case. The plain interleaving above gives the replacement a later `leased_at`, so a timestamp-only predicate refuses it correctly and the mutant survives every other row in this test. Measured, two acquisitions sharing a `leased_at` are not a contrived state: `datetime.utcnow()` self-collided 63 098 times in 200 000 pairs, and the column has no UNIQUE and no monotonicity constraint |
| the conditional write clears `leased_item_id`, `lease_token` and `released_at` but not the three liveness columns (the natural hand-port of `release`) | **22**'s release-state reset assertions — the lease *is* released and every concurrency case passes, while the row keeps a `leased_owner_pid` naming a process that no longer owns anything. It is invisible until the workspace is re-acquired or `reclaim_stale` reads the row, which is the class §4.6b covers |
| `force: bool` retained, or the field parsed and ignored | **22**'s `force: false` and omitted-field cases — a destructive confirmation that the route never reads is documentation. `Literal[True]` moves both refusals into validation |
| the success `logger.warning` left where it is, before the write | **22**'s interleaving case asserts no success line on the `409` path — today the log fires before `release` (`agent_teams.py:701-710`), so a force-release that did not happen is recorded as one, and the audit trail is worse than absent because it is confidently wrong |
| the `503` unconfigured branch omitted, so an empty setting reaches the comparison | **20**'s no-header row, *provided* the test asserts the code and not merely a 4xx — `hmac.compare_digest("", "")` returns `True`, so on an unconfigured install this mutant does not refuse with the wrong code, it **admits every caller** while the source still reads fail-closed. That is why §3.6a puts the empty check *before* the comparison and why 20 must distinguish `503 operator_token_unconfigured` from `401 operator_token_required`: a test that accepts any 4xx passes the version of this route that authorizes the world |
| the operator token exported into the backend's environment instead of read from `backend/.env` (the natural "make it configurable" move) | **none — and it is listed here as a *deployment* mutation precisely because no test can see it.** Every assertion in this section still passes; what changes is that `tmux show-environment -g` returns the secret to any pane (measured, §3.6a), so criterion 32's bound silently drops from *opportunistic adversary* to *none*. Recorded as a row rather than a runbook line because the mutation table is where this spec keeps the defects a green suite would hide, and this is the only one whose test column is honestly empty |
| token compared with `==` instead of `hmac.compare_digest` | — (not observable by test; enforce in review) |
| the operator writes mail as a member — the widened dependency plus a caller-supplied `sender_member_id` (the design §3.6b replaces) | **6e**, and note that 6a/6b are *not* sufficient: both assert what the actor path produces, and this mutant adds a second path rather than changing the first. The discriminating case is a request that presents an actor token **and** a member id |
| the actor ack implemented by writing the recipient's `MailReceipt` (the one-line implementation, since `ack_message` already exists) | **6d**'s `read_at` assertion — and only that assertion. The root still reaches `acknowledged`, so every positive half of 6d passes while `_brief_delivered` (`github_dispatch_service.py:824`) starts reporting that an agent read a brief it has never seen, silently suppressing the `brief_unread` escalation |
| the actor reply keeps `recipient_member_id=root.recipient_member_id` (today's argument, carried over unchanged) | **6b**'s receipt assertion. Measured, the asking member gets no receipt (`asker 1 included? False`), so the reply is authored correctly and delivered to the wrong agent. Invisible to any assertion about the row itself, which is why 6b must assert receipts |
| the actor `answer` relaxation implemented by also clearing the `sender_member_id`/`sender_actor_id` exclusivity check | **6e** — the two checks sit four lines apart (`agent_mail_service.py:849-850` and `:859-860`) and an implementer relaxing the second can take the first with it, which reopens the member-authored row this whole section exists to prevent |
| the ownership relaxation written as "any actor may reply in any thread" rather than "an actor may reply in an **agent-created** thread" | **6i** — which exists *because* of this row. None of the review's eight tests catch it: they all use one actor, so a blanket relaxation passes every one. The mutant is also the shorter edit (delete one comparison rather than make it conditional), so it is the one an implementer reaches for, and its effect is cross-tab actor access with no test objecting |

The last row is deliberate, and so is the export row two above it — the only two in this table whose test column is empty. A timing-safe comparison is not test-observable, and neither is *where a settings value was read from*, so listing them as review and deployment items is honest; claiming a test covers either would not be. Note the distinction from test 20's prefix and trailing-byte rows: those catch a comparison that is *wrong*, which is observable; only a comparison that is right-but-not-constant-time is invisible, and that is the residue the review item covers.

Revision 5 had one further row here, "rotation leaves the old hash valid | 6," and it is **removed** rather than repointed. Test 6 is the external-actor test (`sender_actor_id` set, `sender_member_id` NULL) and has nothing to do with rotation; and after §3.4 ordinary re-registration does not rotate at all, so the mutant describes a mechanism this spec no longer has. The rotation-adjacent behaviour that *does* still need covering — that re-registration authenticates without re-issuing, and that an interleaved header stays valid — is already pinned by tests 13 and 14 above. A mutation row pointing at an unrelated test is worse than no row: it reads as coverage during review and bites nothing.

### 3.8 Blast radius, stated plainly

- `backend/mcp_shim/agent_mail_server.py` — store the token in `_state` at registration, send it as a header in `_request`/`_dispatch_request`. The shim already does exactly this for the Agent Bridge terminal token (`_bridge_request_with_token`, `:117-132`), so the pattern is in-file. Note the token is stored **once** and not replaced on later registrations (§3.4). Every tool that sends `_state["member_id"]` as its own identity keeps working unchanged, because §3.5's "derive, do not compare" accepts a value that agrees with the token. Those call sites are: `deck_send_message` (`:284`), `deck_reply` (`:316`), `deck_request_context` (`:369`), `deck_create_handoff` (`:407`) — all four as `sender_member_id` — plus `deck_ack_message` (`:341`, as `member_id` in the body) and `deck_check_inbox` (`:264`, as a `member_id` **query parameter**, which §3.5 removes from the signature rather than validating).
- `backend/app/services/agent_team_service.py` — write and commit an `agent_pane_bindings` row on both paths (`:569`, `:637`), per §3.3.
- `frontend/src/features/agent-mail/api.ts` — three write calls gain actor auth, plus the `sessionStorage` provisioning helper (§3.6). Measured, those three are the whole surface: `sendAgentMailMessage` (called from `AgentMailPage.tsx:174` for compose and `ThreadDialog.tsx:165` for reply) and `ackAgentMailMessage` (`ThreadDialog.tsx:137`). `updateAgentMailMember` (`:163`) is member configuration, not mail. Note two exports that look like they belong and do not: `fetchAgentMailInbox` and `markAgentMailRead` are **dead** — no component calls either — which matters because `agent/inbox` is the route §3.5 makes a write, so a reader who assumes the UI calls it will over-scope this file's change.
- `backend/app/services/external_agent_mail_service.py` — the §3.6b capability: `reply_in_thread`'s ownership refusal (`:258-259`) becomes conditional on the root being agent-created, its `recipient_member_id` argument becomes `None` (`:265`), and a new actor-scoped acknowledgement lands beside `acknowledge_external_request` (`:330-346`) writing no member receipt. `authenticate_actor` is unchanged and already writes only `actor.last_used_at` (`:117`), which is what makes the ack requirement small.
- `backend/app/api/v1/external_agent_mail.py` — one new route for the actor ack; the existing 12 are untouched. All are already `Depends(external_actor)`, so no dependency work here.
- `backend/app/services/agent_mail_service.py` — if PR0 admits the actor `answer`, the recipient check at `:859-860` gains an actor branch. The exclusivity check four lines above it (`:849-850`) must **not** move — see the mutation table.
- ~13 test call sites hitting `agent-mail/messages` across 5 test files.
- `backend/app/api/v1/agent_teams.py` — `require_operator` on force-release and the workspace listing; the mismatch message loses both token values; `_workspace_response` (`:185`) stops projecting `lease_token` (§3.6a, §4.6a). This is the file's **first** non-`get_db` dependency, so the import and the pattern are new here even though the pattern is old elsewhere.
- `backend/app/models/schemas.py` — `lease_token` off `GithubWorkspaceResponse` (`:2245`); `GithubWorkspaceForceReleaseRequest` (`:2255-2258`) swaps `expected_lease_token` for `force` + `expected_leased_at`.
- `backend/app/config.py` — `operator_token: str = ""` (§3.6a names it; **not** `deck_operator_token`, which no existing setting's convention would produce). Defaults matter here: an empty default must refuse **every** request rather than admit every request, because the shipped posture of an unconfigured install is the one nobody chose deliberately. That is the same fail-closed direction as `bind_unverifiable`. Two consequences beyond the one line: the empty case must be checked **before** `hmac.compare_digest`, since comparing two empty strings returns `True` and would authorize everyone; and because `settings` is built at import time (`:57`), the value is loaded once per process, so rotation is a **backend** restart and not a pane restart.
- `backend/app/api/v1/agent_teams.py`, force-release body — the route is **rewritten**, not adjusted: the lease comparison moves from before `pending_work` to a single conditional `UPDATE` after it, keyed on the workspace row (§4.6a), and the `logger.warning` moves to after the write, since today it fires before `release` (`:701-710`) and would otherwise log a force-release that returned `409`.
- `backend/tests/agent_teams/test_github_workspace_api.py` — the **only** current caller of force-release, at 6 tests (`:176`, `:201`, `:225`, `:251`, `:271`, `:305`). Each needs the operator header, and the three that send `expected_lease_token` need the new body shape. Measured, because I asserted the opposite first and it was wrong: `grep` for `force-release`, `forceRelease`, and `lease_token` across `frontend/src` returns **nothing**, and there is no workspace UI — `frontend/src/features/agent-teams/api.ts` reaches `github-scopes` for scope CRUD only (`:130-154`). So the frontend change §4.6a's decision seemed to imply does not exist, and the projection can be deleted without a UI migration. This is worth recording rather than quietly correcting, because "the UI must be the caller, it is an operator route" is exactly the plausible inference [[check-name-vs-discriminating-power]] warns about — the route's *audience* is the operator; its *callers* are tests. **Note the consequence for the deployment story:** removing `lease_token` from the projection breaks no shipped client, so the ordering constraint in §2.1 is about enforcement flags only.
- The frontend workspace-lease UI is **deferred** (§7) and inherits the operator header when it is built. A future UI needs the token in the browser, which means either an operator paste or a server-rendered injection — a real design question, and it is smaller to answer once the UI exists than to guess at now.
- **Operator action required at deploy:** write the operator token into `backend/.env` (mode `600`, never exported — §3.6a), restart the **backend** so it is loaded, restart agent panes so they register, then flip `mail_capability_tokens_required` to `True` (§3.4). Live: 150 `mcp` session rows, 7 currently connected. Two restarts for two credentials, in that order (§4.6a's ordering).

If PR0's cost proves larger than this in practice, the fallback is to weaken the threat model explicitly in §1.5 and file the auth work separately — **not** to ship PR1 with unverifiable evidence and call it a gate.

---

## 4. PR1 — approval attribution and the distinct-approver gate

### 4.1 Schema

`github_work_items` gains **six** nullable columns, following `app/database.py:421-440` exactly. Three are shown first because they follow the existing rungs directly:

```python
if work_item_columns and "ack_approver_member_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approver_member_id INTEGER"))
if work_item_columns and "ack_evidence_message_id" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_evidence_message_id INTEGER"))
if work_item_columns and "dispatch_nonce" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_nonce TEXT"))
```

…plus three more rungs: the epoch §3.4a requires, the round §4.3a.1 requires, and the immutable head §5.5.4a requires. All belong here with the others rather than in the chapters that motivate them:

```python
if work_item_columns and "ack_enforcement_epoch" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_enforcement_epoch INTEGER"))
if work_item_columns and "ack_approval_round" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN ack_approval_round INTEGER"))
if work_item_columns and "dispatch_head_ref" not in work_item_columns:
    await conn.execute(text("ALTER TABLE github_work_items ADD COLUMN dispatch_head_ref TEXT"))
```

All six nullable, so existing rows migrate silently — and a pre-upgrade row with `dispatch_nonce = NULL` cannot be acked until re-dispatched, which §4.3 rule 3 makes explicit and correct. The same is true of `dispatch_head_ref`: a NULL head means *no attempt has been prepared*, and `pr_ready` refuses rather than composing one (§5.5.4a consequence 3).

**Why `dispatch_head_ref` is a column and not a function of the other two.** Revision 8 composed the expected head on demand from the item's *current* `owner_slot_id` plus its nonce. `accept_handoff` changes `owner_slot_id` (`github_dispatch_service.py:705`) and sends no new brief, so the composed expectation drifts away from the branch the agent was actually told to push — the eighth review's second blocker, and a permanent `409` because nothing ever re-briefs the new name. Storing the head makes the attempt's branch immutable for the attempt's lifetime, which is the property the design needs and the composed form cannot provide. §5.5.4a carries the reasoning; this rung carries the column.

`ack_approval_round` records which round's approval is on file. It is **not** redundant with `approval_round_count`: the counter says which round the item is *in*, and this column says which round the evidence *came from*. The gate compares them (§4.5), which is what makes a stale approval visible instead of merely absent — the same reasoning that made `ack_enforcement_epoch` a column rather than an inference.

`mail_messages` gains `decision` (§4.3a) and `approval_round` on the same ladder:

```python
if message_columns and "approval_round" not in message_columns:
    await conn.execute(text("ALTER TABLE mail_messages ADD COLUMN approval_round INTEGER"))
```

A column rather than a payload key, because the gate filters on it and `payload` is JSON that SQLite cannot index usefully here. The `context_request`'s round also goes in its `payload` — that is what the shim sends and what §4.3 rule 3 matches — but the *decision* row carries it as a column, so an operator reading a thread can see which round each decision belongs to.

### 4.2 The dispatch nonce

`secrets.token_hex(8)`, minted at dispatch, following `workspace.lease_token` (`github_workspace_service.py:130`) — same generator, same lifecycle shape, same purpose: bind a claim to one attempt.

Minted in the **prepare-attempt step**, which runs *before* the brief is composed (§4.2a's "Where the attempt is prepared"). Revisions 5-7 all said `:344`, where `dispatched_at` is set, and the seventh review measured why that cannot work: `:344` runs *after* the brief has already been composed, mailed, and injected into a launched pane. One nonce per dispatch attempt either way; the difference is whether the brief can name it. Cleared or replaced at every point where the attempt's identity changes:

| Event | Site | Action |
|---|---|---|
| dispatch | prepare-attempt, before `:290` | mint a fresh nonce **and head ref**, record **owner + routing method**, **open round 1**, and **commit** — all readable by the brief (§4.2a) |
| retry | `reset_for_retry:64-75` | clear nonce **+ head ref** + the four new ack columns alongside the existing `ack_received_at = None`; `approval_round_count` is already set to `0` here (`:73`) |
| handoff accepted | `accept_handoff:705` | clear **all five** ack fields + `last_nudge_at`; **keep the nonce**, **keep the head ref**, and **keep the round** — see below |
| rejection **below the cap** | `advance_approval_round` branch A (replacing `record_approval_round:672-679`) | increment the round, clear **all five** ack fields + `last_nudge_at`, **keep the nonce** — one commit, no escalation (§4.3a.1) |
| rejection **at the cap** | `advance_approval_round` branch B | counter unchanged, ack fields **kept** for the operator, `dispatch_status = escalated` / `approval_rounds_exhausted` in the *same* commit as the decision row (§4.3a.1) |

The nonce is a *correlation* value, not a secret — PR0 provides the authentication. It exists so that evidence from attempt N cannot satisfy attempt N+1, which no amount of authentication would prevent on its own.

### 4.2a The round has an initial value, and revision 5 never gave it one

Revision 5 said `approval_round_count` "becomes the round identifier" and left three questions unanswered. The fifth review's third blocker is all three, and each is measurable.

**1. `0` is the live default and no lifecycle example uses it.** `approval_round_count` defaults to `0` (`app/models/database.py:267`), `reset_for_retry` sets it to `0` (`github_dispatch_service.py:73`), and every example in revision 5 — §4.8's tests 29-37, §4.3a.1's prose — begins at round 1. Nothing initialized it. An implementer reading only the mechanism would ship a first dispatch whose request payload says `approval_round = 0` while the spec's tests all assert `1`.

**2. The cap's arithmetic changes with the starting value.** `record_approval_round` escalates at `>= scope.max_approval_rounds` (`:676`) with the default `3` (`app/models/database.py:221`). Starting at `0`, three rejections reach `3` and escalate — so the item gets rounds 0, 1, 2 and dies entering round 3. Starting at `1`, three rejections reach `4`, which never triggers `>= 3` on the third and triggers it on the second. The same constant means different things depending on an initial value the spec did not state, and the existing test asserts the `0`-based arithmetic (`tests/agent_teams/test_github_dispatch_service.py:2334-2355`: `max_approval_rounds = 2`, two calls, escalates on the second).

**3. The round travelled in a payload the caller filled.** §4.3a.1 had `deck_request_context` read the item's counter and put it in the payload. The shim is the honest caller; `POST /agent-mail/messages` is not the only writer ([[deck-mail-writes-are-unauthenticated]]). An owner could post a `context_request` with `approval_round = 5` before round 5 opened, and it would become the matching request the moment the counter arrived — an approval pre-dated for a round that had not happened.

**Decision: `0` means not dispatched; dispatch opens round 1; the server derives the round.**

| Value of `approval_round_count` | Meaning |
|---|---|
| `0` | the item has never been dispatched, or has been reset for retry. **No round is open**, so no approval request is valid and the gate has nothing to compare |
| `1` | the first dispatch's round — set by the prepare-attempt step below, in the same commit as the nonce |
| `n` where `1 < n <= max_approval_rounds` | the round opened by the (n-1)th rejection |

Setting the round to `1` rather than leaving it `0` is what makes "which round is open" answerable without consulting `dispatched_at`, and it means a pre-upgrade row (`0`, no nonce) refuses on both counts rather than accidentally matching a request that omitted the round.

**Where the attempt is prepared, and why not where revisions 5-7 said.** Revisions 5, 6, and 7 all put the mint at `github_dispatch_service.py:344`, beside `dispatched_at`. The seventh review measured the ordering and it is fatal:

```
:277   workspace = await github_workspace_service.acquire(...)
:290   brief = self._dispatch_brief(item, scope, workspace, ...)   <-- needs the nonce
:299   await self._send_dispatch_brief_to_slot(..., brief=brief)   <-- brief is now mailed
:306   result = await launcher(..., slot_prompt_overrides={owner_slot_id: brief})
                                                          ^^^ agent is running with it
:343   item.dispatch_status = "dispatched"
:344   item.dispatched_at = datetime.utcnow()                      <-- revision 7's mint site
```

The brief that must name the attempt branch (§5.5.4a consequence 2) is built at `:290` and *delivered twice* — by mail at `:299` and as the launch prompt at `:306` — before `:344` runs. A nonce minted at `:344` is NULL at `:290`. Worse, this is invisible to a unit test that hands `_dispatch_brief` a pre-populated item: the test passes and every real dispatch sends a brief naming the wrong branch, which `pr_ready` then refuses with a `409`. Confirmed the line numbers directly, and confirmed `dispatch_nonce` appears nowhere in `app/` today, so there is no existing behaviour to preserve.

**Decision: an explicit `prepare_attempt` step, committed before the brief is composed.** Revision 8 committed the attempt's *identity* here and left its *owner* at `:332`. The eighth review's first blocker is that gap, and it is confirmed: `owner_slot_id` and `routing_method` are first persisted after `launcher` returns (`:332-333`), a newly watched item is created with neither (`github_watcher_service.py:63`), and both columns are nullable (`models/database.py:259`, `:262`). So the fresh-session scenario revision 8 set out to make safe still fails one column over — the launched agent's first owner-only report meets `report.reporting_slot_id != item.owner_slot_id` with `item.owner_slot_id IS NULL` (`agent_teams.py:334`) and is refused.

**The record is the whole attempt, not just its name.**

```python
# `_ATTEMPT_MARKERS` is exactly what reset_for_retry clears (rule 4).
_ATTEMPT_MARKERS = ("dispatch_nonce", "dispatch_head_ref")


class AttemptState(enum.Enum):
    UNPREPARED = "unprepared"
    PREPARED = "prepared"


class PartiallyPreparedAttempt(ValueError):     # see "the exception's base class" below
    def __init__(self, item_id: int, detail: str):
        super().__init__(f"work item {item_id} is partially prepared: {detail}")
        self.item_id, self.detail = item_id, detail


def attempt_state(item) -> AttemptState:
    """Classify the row. Raises rather than returning a third value: a torn
    attempt is not a state the dispatch loop may branch on."""
    markers = [getattr(item, c) for c in _ATTEMPT_MARKERS]
    if all(m is None for m in markers) and item.approval_round_count == 0:
        return AttemptState.UNPREPARED       # stale owner/routing may remain; see rule 4
    markers_complete = all(m is not None for m in markers) and item.approval_round_count >= 1
    identity_complete = item.owner_slot_id is not None and bool(item.routing_method)
    if markers_complete and identity_complete:
        return AttemptState.PREPARED
    raise PartiallyPreparedAttempt(
        item.id,
        f"nonce={markers[0] is not None} head={markers[1] is not None} "
        f"round={item.approval_round_count} owner={item.owner_slot_id} "
        f"routing={item.routing_method!r}",
    )


@dataclass(frozen=True)
class PreparedAttempt:
    """Returned whole, so no caller can mix a persisted field with a stale local."""
    owner_slot_id: int
    routing_method: str
    dispatch_nonce: str
    dispatch_head_ref: str
    approval_round: int


def prepared_attempt_from_row(item) -> PreparedAttempt:
    return PreparedAttempt(item.owner_slot_id, item.routing_method,
                           item.dispatch_nonce, item.dispatch_head_ref,
                           item.approval_round_count)


async def prepare_attempt(self, db, item, *, owner_slot_id, routing_method) -> PreparedAttempt:
    """Persist this attempt's complete identity, atomically, before anyone is told of it.

    Accepts only an UNPREPARED row. A PREPARED one is returned by the caller's
    own `attempt_state` call, which happens before any routing (§4.2b).
    """
    if attempt_state(item) is not AttemptState.UNPREPARED:   # raises on partial
        return prepared_attempt_from_row(item)
    item.owner_slot_id = owner_slot_id      # the owner is part of the identity, not a result
    item.routing_method = routing_method
    item.dispatch_nonce = secrets.token_hex(8)
    item.dispatch_head_ref = attempt_head_ref(item, owner_slot_id)   # composed ONCE, §5.5.4a
    item.approval_round_count = 1
    item.updated_at = datetime.utcnow()
    await db.commit()                       # durable BEFORE any brief, mail, or pane
    return prepared_attempt_from_row(item)
```

`dispatch_head_ref` is the sixth column, and §5.5.4a explains why the head must be stored rather than recomputed.

**The classification is asymmetric, and neither a single `all()` nor a single `any()` can express it.** Two earlier revisions each got one half right and shipped the other half wrong, which is why this is a state function rather than a tuple:

- Revision 9's **first draft** put all five fields in one tuple. That is fatal, because `reset_for_retry` **deliberately does not clear** `owner_slot_id` or `routing_method` (rule 4 below, and the existing `:64-75` block, verified). After a genuine retry the row holds `(None, None, 1, 'role_match', False)`: `all()` false, `any()` **true**, so preparation raises on **every** retried item.
- Revision 9 as **committed** then dropped those two fields entirely and guarded on the three markers. That admits the opposite defect, which this review found: a row can hold every marker and **no owner**. `GithubWorkItem.owner_slot_id` is `ForeignKey("agent_team_slots.id", ondelete="SET NULL")` (`models/database.py:259-261`), so **deleting the owner slot nulls the column and leaves the nonce, head, round and routing string intact.** Measured through a real `DELETE`:

```
after DELETE of the owner slot (ondelete='SET NULL'):
    owner_slot_id  = None
    routing_method = 'label'
    dispatch_nonce = '629877f7d9855057'
    head           = 'deck/slot-1/issue-42-629877f7d9855057'
    round          = 1
    revision 9's three-field guard -> PREPARED     <- returns the head, owner NULL
    the asymmetric model           -> PARTIAL      <- refuses
```

So the correct rule is not "which fields are in the guard" but **which fields are mandatory in which state**: owner and routing may be *stale* on an unprepared row and must be *present* on a prepared one. `attempt_state` above tests `markers_empty` first, which is what preserves the auditability decision rule 4 makes — the same retried row that the five-field tuple rejected still classifies `UNPREPARED`, measured:

```
after a genuine retry (reset keeps owner/routing):
    owner=1 routing='label' nonce=None round=0
    revision 9's three-field guard -> UNPREPARED
    the asymmetric model           -> UNPREPARED
```

The round is the one member that is a comparison rather than a presence check, and it is what makes a torn row fail closed in the direction that matters: `reset_for_retry` zeroes it at `:73` **today**, so a retry that cleared the round but not the nonce reads as partial rather than as prepared.

**`attempt_state` raises rather than returning a third enum member.** A `PARTIAL` return value would be a state the dispatch loop could branch on, and every branch it could take is a guess about which half of the row is authoritative. Raising forces the decision to one place. The exception derives from **`ValueError`** so it lands in the existing `except ValueError` cleanup at `:317-323` — but that inheritance is load-bearing and must be stated, not assumed: the review is right that the previous revision claimed the `ValueError` path without making the exception a `ValueError`. An implementer who writes `class PartiallyPreparedAttempt(Exception)` gets the `except Exception` branch at `:325` instead, which escalates `launch_outcome_unknown` and **re-raises**, aborting the whole poll for every later item in the batch. One base class, two very different blast radii. Note also that the `:317` branch releases the workspace, which is correct here and *not* correct for the unavailable-owner case in §4.2b — see that section for why the two paths differ.

**Why a torn row is reachable at all, since no code writes half an attempt.** Three ways, none hypothetical: the FK `SET NULL` above; a hand-edited row (an operator repairing a stuck item, which this project's own history contains); and a future clear that adds a column to `_ATTEMPT_MARKERS` without adding it to rule 4's reset, or the reverse. The third is why the markers live in a shared constant that the reset iterates: **a guard and the clear it depends on must read the same list, or the clear can shrink without the guard noticing.**

Six properties, each answering something a review asked for:

1. **Committed, not just assigned.** The launched agent can call `deck_request_context` before the dispatch loop reaches `:344`, and a route in another request reads a different session. An in-memory nonce is invisible to that read, so the agent's first legitimate call would refuse `stale_nonce`. The commit is the fix, and it is why this is a step rather than two lines moved upward.
2. **Idempotent on the poll.** Preparation is guarded on the whole record being present. A crash between preparation and launch leaves the item `pending` with a prepared attempt; the next poll **reuses** it rather than minting a second nonce. Without the guard, an agent relaunched after a crash would be briefed with nonce B while its first (possibly still-live) pane holds nonce A.

    **The guard is not enough on its own, because `route_item` runs above it.** `route_item` is called at `:252`, before the workspace is acquired at `:277` and therefore before preparation. It is a pure function of the slot list, the issue's labels, and the classifier (`:103-128`) — every one of which can change between polls. Measured against the real function, two ordinary events re-route the same item: an edit to the issue's area labels (`route_item:120-123` matches `slot.area_labels & issue_label_set`), and an operator disabling the first slot (`:113-117` filters on `slot.enabled`, then sorts by `position`). Neither requires a non-deterministic classifier.

    **A re-poll does require something, though, and revision 9 named the wrong thing.** That draft said an operator disabling a slot "needs no crash at all," which conflated *calling `route_item` twice* — which the measurement did — with *re-polling a prepared item*, which it did not. `dispatch_pending` selects `dispatch_status == "pending"` (`:227-234`), so a **successfully dispatched item is never re-polled**: measured, 0 pending rows after a successful dispatch. The ninth review is right about that, and about my having overstated it. But its conclusion — that only a crash reaches this path — is also incomplete, and the gap matters because it is the same gap as blocker 2. **Two lifecycles leave a prepared item `pending`:**

    - the crash paths of property 6, where `launcher` raises after preparation; and
    - an **early-exit `continue`** at `:259-284`. A prepared item that finds its owner busy, its sessions ambiguous, or no workspace free is left `pending` deliberately — that is the queue working — and the *next* poll re-routes it. Measured: with no dispatchable workspace row, `acquire()` returns `None`, the `:279` branch commits, and the row is still `pending`.

    The second is the one worth stating, because it is not a failure at all. It is the ordinary queueing path, it happens on every poll while a slot is busy, and it is the *same branch* that overwrites `owner_slot_id` with the fresh candidate. So the re-route hazard does not need a crash and does not need an operator error: it needs a busy slot.

    **The consequence is not the one revision 9's first draft wrote, and measuring it moved the fix's justification.** That draft said the reused attempt "quietly acquires a different expected head." It does not: blocker 2 made the head a **stored column**, and the guard returns early, so `prepare_attempt` never reassigns it. What actually diverges is everything the loop derives from the *local* `owner_slot_id` variable rather than from the row — the brief's recipient (`:299`), the launch target (`:306`, `slot_ids=[owner_slot_id]` and `slot_prompt_overrides`), and the owner column itself at `:332`, which overwrites the persisted decision *after* the launch. Driven through the real dispatch ordering with a recording launcher:

    ```
    prepare under labels ['area:api'] -> slot 1, then crash before launch;
    re-poll under labels ['area:ui']  -> slot 2

    reuse persisted routing        recompute (revision 8)
      briefs sent to slots [1, 1]    briefs sent to slots [1, 2]
      launched            [1]        launched            [2]
      row.owner_slot_id    1         row.owner_slot_id    2      <- :332
      row.dispatch_head_ref          row.dispatch_head_ref
        deck/slot-1/...-<nonce>        deck/slot-1/...-<nonce>   <- still slot 1
      nonces minted        1         nonces minted        1
    ```

    So the row ends up self-contradictory in a way no single field reveals: `owner_slot_id` is 2 and the head it is expected to push names slot 1. And the first brief is already durable when this happens — `_send_dispatch_brief_to_slot` calls `send_direct_message`, which **commits** (`agent_mail_service.py:899`), so it survives the crash in `launcher` regardless of what the dispatch loop does afterward. Measured: one `mail_messages` row naming `deck/slot-1/issue-42-<nonce>`, readable from a separate session, before the loop's own commit at `:333`. Two slots therefore hold a committed brief for the same branch, and `:332` makes the *second* one the owner — so slot 1's report, from the slot that was told first and may already have pushed, is refused by `report.reporting_slot_id != item.owner_slot_id` (`agent_teams.py:334`). That is blocker 1's own failure mode arriving through a different cause: not a NULL owner, but a *reassigned* one.

    The fix is that the dispatch loop must **read the persisted routing decision instead of the freshly computed one** whenever the item is already prepared. Revision 9 wrote that fix as an override placed after the existing guards, and kept `route_item` running for prepared items on the grounds that "the guards between `:252` and `:277` need a candidate slot to report against." **Both halves of that were wrong, and the ninth review's second blocker is exactly this.** An override at `:277` protects nothing, because `:262`, `:270` and `:279` have each already written the fresh candidate into `item.owner_slot_id` and **committed**; and the guards do not need a *fresh* candidate, they need *the* candidate — which for a prepared item is the persisted owner. Running `route_item` and then checking its answer means the guards clear slot B while the override launches slot A. Both directions are measured in §4.2b, which replaces the sketch revision 9 put here with the ordering the whole loop must have.
3. **Partial preparation fails closed.** A row with a nonce and no owner, or an owner and no round, is not a state to interpret — it is a torn write from a crash inside the commit, or a hand-edited row. Preparation refuses it rather than filling in the blanks, because every plausible repair guesses at which half is authoritative. This is the same rule as `pr_ready` on a NULL-nonce item (§5.5.4a consequence 3): **when the evidence is incomplete, refuse and say so.**
4. **`reset_for_retry` is the only thing that authorizes a new nonce, and the clear belongs *below* its early return.** It must *clear* `dispatch_nonce` **and `dispatch_head_ref`** — which §4.2's table already requires (`reset_for_retry:64-75`, where `approval_round_count = 0` is already set at `:73`). Clearing them is what makes the guard above fall through on a genuine retry and hold on a crash-retry of the same attempt. Note the existing reset block **already** clears neither `owner_slot_id` nor `routing_method` (`:64-75`, verified) — and it should not start: they are overwritten by the next preparation, and keeping them lets an operator see who last held a retried item. That decision is what fixes the guard's membership above, so the two must be read together.

    **The consequence of missing the clear depends on the guard, and revision 9's first draft carried revision 8's answer.** Under a guard on `dispatch_nonce` alone the retried attempt is silently reused: attempt 1's head is recomposed, reconciliation rediscovers the closed PR, and the item escalates again. Under the three-field guard above it is **not** silent, because `reset_for_retry` already zeroes the round at `:73` — the row reads as partial and preparation refuses. Measured, both guards, same missed clear:

    ```
    after a retry with the nonce/head clear missed:
        nonce='a3f9c1b2d4e5f607'  head='deck/slot-1/issue-42-a3f9c1b2d4e5f607'
        status='pending'  round=0

    nonce-only guard  -> returned head 'deck/slot-1/issue-42-a3f9c1b2d4e5f607'
                         0 new nonces minted   <- attempt 1's head, reused silently
    three-field guard -> raised PartiallyPreparedAttempt(nonce, head, round=False)
                         0 new nonces minted   <- refuses, and says why
    ```

    Both are bugs and neither is acceptable, but they need different tests and different mutation rows: the reuse is invisible until a second escalation, and the refusal is visible on the first poll. Stating the wrong one would send an implementer looking for a silent regression that the design no longer produces. This is the same correction as revision 9's blocker-3 finding — **a consequence is a claim about the whole composed design, not about the line being changed** — and it is the second time in this revision that a sentence inherited from an earlier guard survived the guard it described.

    **The clear must live in `reset_for_retry`, not in the retry route, because two of the three callers are not the operator.** Measured caller set:

    ```
    app/api/v1/agent_teams.py:783                    the operator's retry endpoint
    app/services/github_dispatch_service.py:98       promote_deferred_retries
    app/services/github_watcher_service.py:79        an ISSUE EDIT -- no operator at all
    ```

    The watcher's path is the instructive one: `_upsert_item` retries an `escalated`/`failed` item whenever the issue's `updated_at` advances (`github_watcher_service.py:74-79`), so an operator editing the issue text of a failed item triggers a re-dispatch nobody asked for by that name. A clear written in the route leaves that path holding attempt 1's nonce and head. Measured, driving the real `_upsert_item`:

    ```
    clear inside reset_for_retry:            status='pending' nonce=None head=None round=0
    clear written in the retry ROUTE only:   status='pending'
                                             nonce='a3f9c1b2d4e5f607'
                                             head='deck/slot-1/issue-42-a3f9c1b2d4e5f607'
    ```

    Test 37p covers it. Note also that `reset_for_retry` **assigns without committing** — all three callers commit (`:97-98`, `agent_teams.py:786`, and the watcher's poll) — so a test that re-reads in a fresh session without committing first sees the *pre-reset* row and passes no matter what the function does. That cost a false green while writing this.

    Position matters as much as presence, because `reset_for_retry` is **two functions in one**. When the item still holds a workspace lease it takes the deferred branch (`:56-63`): it sets `retry_requested_at`, writes a status note, and **returns without resetting anything** — the `return` is at `:63`, verified. The reset block starts at `:64`. Putting the clear above that return would strip the nonce from an item whose previous attempt is *still running* — its pane holds the old nonce, so every `deck_request_context` and every ack from a live agent would refuse `no_linkage`, and the item would sit in `escalated` until `promote_deferred_retries` (`:77-101`) re-entered the function later. The nonce must survive until the lease is released and the real reset runs. Same rule as property 6, and the same reason: **while a pane may still be alive, its attempt identity must stay valid.**
5. **Handoff preserves the whole record.** `accept_handoff` (`:697-710`) changes `owner_slot_id` and must **not** touch `dispatch_nonce` or `dispatch_head_ref` — the reason is §5.5.4a's, and it is the eighth review's second blocker: the head was minted for the *original* owner and the new owner was never briefed with a replacement. See §4.4's table row and §5.5.4a's immutability paragraph.
6. **Launch failure keeps the prepared attempt.** Both the `_LAUNCH_FAILED_STATUSES` path (`:338-341`, `dispatch_status = "failed"`) and the `launch_outcome_unknown` path (`:325-331`) leave the record in place. For `launch_outcome_unknown` this is required, not merely convenient: the pane may be live, so its nonce must stay valid — clearing it would make a running agent's evidence unmatchable while telling nobody. Recovery from either goes through `deck_retry_work_item`, which clears the nonce as rule 4 requires. `plan_blocked` (`:317-324`) is the same: escalate, release, keep the prepared attempt.

`:344` keeps `dispatched_at` and `dispatch_status`, and the `owner_slot_id` / `routing_method` writes at `:332-333` become **redundant** rather than merely late — preparation already committed them, and the lines may stay as harmless re-assignments or be deleted, but a plan must say which. Delete them: leaving a second writer for a column that now has an authoritative one is how the two come to disagree, and 29-a1's baseline counts them. The split of *what stays* at `:344` is deliberate: `dispatched_at` records **when the pane started**, which is only knowable after `launcher` returns, while the attempt record says **which attempt this is and who owns it**, which must be knowable before anyone is told about it. Revisions 5-7 conflated the two because they are set twelve lines apart today.

**The cap, restated for a 1-based counter.** `advance_approval_round` (§4.3a.1) checks *before* it increments, so the counter never holds a round that did not happen:

```python
if item.approval_round_count >= scope.max_approval_rounds:
    # the round we would open does not exist; leave the counter on the last real round
    await self.escalate(db, item, "approval_rounds_exhausted")
else:
    item.approval_round_count += 1
```

The comparison keeps its `>=` and the **structure** changes instead. That is the point worth stating plainly, because the obvious fix is to leave `record_approval_round`'s shape alone and flip `>=` to `>`:

```python
item.approval_round_count += 1                        # DO NOT ship this form
if item.approval_round_count > scope.max_approval_rounds:
    await self.escalate(db, item, "approval_rounds_exhausted")
```

Both forms escalate on exactly the same rejection — measured, not reasoned: with `max_approval_rounds = 3` from a start of `1`, both allow rounds 2 and 3 and escalate on the attempt to open 4, and both fail the same three existing tests. They differ only in what they leave in the row. Increment-then-compare ends at `4`, a round no request can ever match; the precondition form ends at `3`, the last round that really happened. Choose the precondition form, because §4.5's `ack_approval_round == approval_round_count` comparison and §4.3 rule 3's `stale_round` refusal both read this column, and a column holding a fictional round makes both unreadable during an incident. Revision 5's inherited `>=` was wrong about the *arithmetic* (it reduced the available rounds by one under a 1-based counter); flipping the operator fixes the arithmetic and leaves the state wrong. Fix both.

**Three existing tests must be updated, and the plan must name all three.** Measured by applying each candidate form to `:672-679` and running the suite (`tests/agent_teams/test_github_dispatch_service.py`, 106 tests): both forms give 103 pass and exactly these three fail.

| Test | Line | Why it fails | What it must become |
|---|---|---|---|
| `test_approval_round_cap_escalates` | `:2335` | `max_approval_rounds = 2`, item starts at `0`, two calls reach `2` — which escalated under the old 0-based rule and does not under either new form | start the item at `1` (dispatch's value) and assert the *rounds* available: rejections open 2 then 3, and the rejection that would open 4 escalates. Assert the final counter is `3`, not `4` — that assertion is what separates the two candidate forms |
| `test_escalation_creates_agent_mail_broadcast` | `:2359` | `max_approval_rounds = 1` and one call reached `1`; it uses the cap only as a convenient way to *trigger* an escalation | keep testing the broadcast, not the arithmetic: set the item's round to the cap first, so one rejection crosses it |
| `test_escalation_state_persists_when_notification_fails` | `:2393` | same trigger, same reason | same fix |

The last two are the instructive ones. Neither is a cap test — they are a mail test and a rollback test that borrow the cap as a trigger, so a plan that only looks for tests *named* after approval rounds will find one of the three and leave two red. That is the same seam the whole review is about: the change is in the arithmetic, and two of its three consequences live in sections about something else. **Do not** repair them by reverting to `>=` locally or by loosening an assertion; the second and third tests should stop depending on the exact cap value at all.

**The round is derived, never accepted.** Both tools that carry a round derive it server-side:

- `deck_request_context(work_item_id, dispatch_nonce)` — the **route** reads `item.approval_round_count` after resolving the item and confirming the caller is its current owner, and writes that value into the payload. The tool signature gains no `approval_round` parameter, so the shim cannot supply one.
- A caller that posts `POST /agent-mail/messages` directly with a payload `approval_round` that disagrees with the item's current count ⇒ `403 approval_round_mismatch`. Not silently overwritten: the same "derive, do not compare" rule §3.5 applies to `sender_member_id`, and for the same reason — silently correcting a wrong value hides a misconfigured or hostile caller behind a success.
- A payload `approval_round` that *agrees* is accepted, which keeps a future shim's explicit value valid and keeps this rule from being a version tripwire.
- `deck_approve_work_item` (§4.3a) takes the round from the **resolved request's** payload, which is now itself server-derived, so the leader cannot choose it either.

**Why not drop `approval_round` from the payload entirely** and have the gate read only `item.approval_round_count`? Because then a request carries no record of the round it was made in, and §4.3 rule 3's `stale_round` refusal becomes unimplementable: every request would match every round. The payload value is the request's own statement of when it was made; the derivation rule is what makes that statement trustworthy.

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

**Why handoff keeps the nonce — and the head with it.** Clearing the nonce would deadlock the item. `accept_handoff` sends **no new brief**, so the new owner never learns a replacement nonce, and every subsequent ack attempt would refuse with `no_linkage` forever. Clearing the *ack* fields is what matters: the new owner must obtain their own approval, and §4.3 rule 3 requires the `context_request` to have been sent **by the current owner member**, so the previous owner's request cannot satisfy the new one even though the nonce is unchanged. Retry is different — it re-dispatches through `prepare_attempt`, which mints a fresh nonce, so clearing is both safe and necessary there.

The eighth review's second blocker is that "keep the nonce" was necessary and **not sufficient**. The nonce was not the only slot-dependent half of the name: `accept_handoff` changes `owner_slot_id` (`:705`), and revision 8 composed the expected head from the *current* owner's `slot_id`, so the surviving nonce was carried into a name the agent had never been given. `dispatch_head_ref` (§4.1) closes it by making the head part of the attempt record rather than a function of mutable state: handoff changes who is working and does not change what they were told to push. §5.5.4a carries the measurement and the general rule; this rung records that handoff must keep **both** columns, and test 11f proves it by driving the real `accept_handoff`.

**Why handoff keeps the round too.** A handoff is not a rejection: nobody has declined anything, so no new round should open, and the cap must not be consumed by an event the leader did not cause. Handing an item back and forth three times would otherwise exhaust `max_approval_rounds` without a single review ever happening. The *owner* changed and the *round* did not, which is exactly the state §4.3 rule 3 already handles — the request must come from the current owner member, so the new owner opens a fresh `context_request` **in the same round** and the previous owner's request in that round no longer matches. That is also why §4.3a's duplicate-request `409` is scoped to `(work item, nonce, round, owner)` and not to `(work item, nonce, round)`: two requests in one round from two different owners is the normal shape of a handoff, not a shim bug.

**The deferred-retry path is already covered.** `reset_for_retry` returns early at `:56-63` when the item still holds a lease, setting only `retry_requested_at`. `promote_deferred_retries` (`:77-101`) later re-selects those items — `escalated`/`failed`, non-NULL `retry_requested_at`, no lease row — and calls `reset_for_retry` **again** once the lease is gone, and that second call reaches the clearing block. So the deferred path clears the columns too, with no extra work — but a test must prove it, because "the early return skips the clear" is exactly the kind of thing that looks broken and is not (test 10b).

### 4.2b The loop classifies before it routes, and a prepared item is never re-routed

Revision 9 put the fix for §4.2a property 2 in the wrong place: an override at `:277` that ran *after* `route_item`, kept the fresh candidate for the guards, and swapped it back only for the launch. The ninth review's second blocker is that this protects nothing, and both failure directions are measurable.

**Direction 1 — the guards clear one slot and the launch takes another.** Prepared for slot A; slot A is now busy; `route_item` returns slot B, which is free. The busy check at `:259` tests B, passes, and the override at `:277` then hands A to the launcher:

```
slot_is_busy(A=1) = True   slot_is_busy(B=2) = False
poll outcome: through:1
    -> guards cleared B; the override launches A, which IS busy.
```

That is the exact hazard `slot_is_busy` exists to prevent, reintroduced by the fix meant to preserve routing. **A guard is only meaningful if it tests the value the code afterwards uses.**

**Direction 2 — every early exit commits the fresh candidate before the override is reached.** `:262-263`, `:270-271` and `:279-280` each assign `item.owner_slot_id = owner_slot_id` and `item.routing_method = method` and then `await db.commit()`, and every one of them ends in `continue`. The override at `:277` is downstream of two of the three and is skipped by all three:

```
prepared for slot 1; poll under labels ['area:ui'] -> queued_no_workspace
    owner_slot_id now = 2   (prepared for 1)
    routing_method    = 'label'
    head still        = 'deck/slot-1/issue-42-eb1df1d1ca287cab'
    -> owner=2 but head names slot 1. No crash, no launch.
```

No exception, no launch, no log line: the row is simply self-contradictory afterwards, and the next poll starts from the corrupted owner. This is the queueing path, not an error path — measured, `acquire()` returning `None` is enough — so it runs on every poll while a slot is busy.

**Decision: classification is the first thing the loop does with an item, and routing is conditional on it.** The ordering, stated as the sequence a plan must produce:

```python
# once, above the loop: the list the scheduler handed us, indexed. NOT a db.get --
# a slot outside this preset must read as absent, not be fetched. See below.
slots_by_id = {s.id: s for s in preset_slots}

for item in pending:
    # 1. scope-wide gates first: they are properties of the scope and the host,
    #    not of this item's owner. Order unchanged (:237-250).
    #      repo cap        -> pending_reason = "queued_repo_cap";  continue
    #      available memory-> pending_reason = "queued_low_memory"; continue

    # 2. classify THIS row before anything reads or writes an owner.
    try:
        state = attempt_state(item)                      # §4.2a
    except PartiallyPreparedAttempt as exc:
        await self.escalate(db, item, "plan_blocked", str(exc))
        await db.commit()
        continue                                         # per-item, see below

    # 3. establish the authoritative owner/routing for this poll.
    if state is AttemptState.PREPARED:
        attempt = prepared_attempt_from_row(item)        # route_item NOT called
        owner_slot_id, method = attempt.owner_slot_id, attempt.routing_method
        if (owner_slot := slots_by_id.get(owner_slot_id)) is None or not owner_slot.enabled:
            await self._escalate_prepared_owner_unavailable(db, item, owner_slot)
            continue                                     # no release; see below
    else:
        issue_labels = issue_labels_by_number.get(item.issue_number, [])
        owner_slot_id, method = await self.route_item(
            db, item, preset_slots, issue_labels, classify=classify
        )
        if owner_slot_id is None:
            await self.escalate(db, item, "plan_blocked")
            await db.commit()
            continue

    # 4. the owner-dependent guards, unchanged in content, now reading the
    #    authoritative owner: busy (:259), ambiguity (:268), workspace (:277).
    #    Their `item.owner_slot_id = owner_slot_id` writes become no-ops for a
    #    prepared item, which is the point: nothing can diverge.

    # 5. prepare (UNPREPARED only) or reuse, then brief, then launch.
    attempt = await self.prepare_attempt(
        db, item, owner_slot_id=owner_slot_id, routing_method=method
    )
```

Four things about that shape are load-bearing, and each of them is a correction to revision 9.

**`route_item` is not called for a prepared item at all.** Revision 9 kept calling it "because the guards need a candidate slot to report against." They need *the* candidate, and for a prepared item the persisted owner is it. Calling `route_item` and then discarding its answer is worse than not calling it: it is a decision the code makes and then throws away, so any future reader sees a routing call and reasonably assumes routing happened. It also spends a classifier call — `route_item` invokes `classify` for an unlabelled issue (`:103-128`) — on an answer that is discarded, which for the real classifier is a model call. Not calling it is the simpler code *and* the honest one.

**Steps 1 and 2 are in that order deliberately, and swapping them is tempting.** The scope gates could go after classification, and putting them first means a torn row in a capped scope is not noticed until the cap clears. That is the right trade: the cap and the memory gate are refusals to start *any* work, and spending a classification — which can raise, escalate and broadcast — on an item the loop was never going to dispatch this poll turns a queue-full condition into a burst of escalations. The scope gates write only `pending_reason`, never an owner, so they cannot corrupt the attempt record. Both orderings are safe; this one is quieter.

**The `attempt_state` call must be caught per item, and the exception's base class does not do that for it.** §4.2a chose `ValueError` so a partial row would land in the existing cleanup at `:317-323`. That reasoning is correct about the *class* and wrong about the *position*, because the try block does not open until `:285`:

```
dispatch_pending's for-loop body: lines 237-368
Try statements DIRECTLY in the loop body: 1
    try covers 286-316, handlers=['ValueError', 'Exception']

first statement of the loop body : line 237
first line INSIDE the try        : line 286
-> 49 lines of the loop body run OUTSIDE the try
```

An `attempt_state` call at the top of the loop body is 49 lines above the handler that was chosen for it. **An exception's catch site is a property of where it is raised, not of its base class.** Uncaught, it propagates out of `dispatch_pending` — and the blast radius is not the batch, it is the scope. `run_repo_once` calls the passes in sequence and `run_repo_job` wraps the whole thing in `except Exception: logger.exception` (`github_dispatch_scheduler.py:96-97`), so one torn row silences four later passes:

```
run_repo_once with a raising dispatch_pending:
    calls that ran : ['poll_scope', 'dispatch_pending']
    propagated out : PartiallyPreparedAttempt
```

`monitor_dispatched`, `remind_held_leases` and `process_scope` never run — so for as long as that row sits in `pending`, no ack timeout fires, no held lease is reminded, no PR is verified and nothing is merged, for **every item in the scope**, on **every poll**. A per-item catch confines it, measured both ways:

```
Solution 2 verbatim (no per-item catch):
    raised out of the poll: PartiallyPreparedAttempt
    items reached after the torn one: 0
    still pending: [41, 42]  <- 42 never examined

with a per-item catch around attempt_state:
    items reached after the torn one: [42]
    torn row: status='escalated' reason='plan_blocked' nonce kept=True
```

So the `ValueError` base class stays — §4.2a's reason for it is still valid for a partial row discovered *inside* the try, and a future reader who moves the call inherits a working handler — but it is **not** the mechanism here. The per-item `try` in step 2 is, and a plan that omits it ships the scope-wide stall.

**The torn row escalates `plan_blocked` and does not release the workspace.** `plan_blocked` because the item genuinely cannot be planned and the reason namespace should not grow for a case an operator handles identically; the exception's `detail` string carries which halves were present, through `escalate`'s `note` parameter, which lands in both `status_note` and the broadcast. No release, for the reason below — the same reason as the unavailable-owner case, and the one place §4.2a's `:317` cleanup would be actively wrong if it were reached.

#### 4.2b.1 `prepared_owner_unavailable`, and why it is not one condition

The review's Solution 2 wrote the availability check as `owner_slot is None or not owner_slot.enabled` with a single `status_note` saying "missing or disabled." Those are two mechanisms with different states and different operator actions, and the more obvious of the two never reaches this branch at all.

**Deletion does not arrive here.** `GithubWorkItem.owner_slot_id` is `ForeignKey("agent_team_slots.id", ondelete="SET NULL")` (`models/database.py:259-261`), `PRAGMA foreign_keys=ON` is set on every connect (`database.py:28-34`), and the deployed database really carries the constraint — read out of the live schema, not the ORM. So deleting the owner slot nulls the column, `attempt_state` classifies the row **PARTIAL**, and step 2 escalates before step 3 runs. Measured side by side:

```
owner slot DELETED : owner_slot_id=None attempt_state -> PARTIAL(raised)
owner slot DISABLED: owner_slot_id=1    attempt_state -> PREPARED
                     resolvable=True enabled=False
```

**Disabling does arrive here, because the slot list is unfiltered.** `run_repo_once` selects `AgentTeamSlot.preset_id == scope.preset_id` with no `enabled` predicate (`github_dispatch_scheduler.py:125-131`, verified), so a disabled slot is still in `preset_slots` and still resolvable by id. That is what makes "disabled" distinguishable from "gone" — and it is why the check must be `slots_by_id.get(...)`, a lookup in the list the loop was actually handed, rather than a `db.get(AgentTeamSlot, ...)`, which would find a slot that this scope no longer contains.

**The `is None` half is reachable, and not by the mechanism the review implied.** I first measured it with a reparent (`slot.preset_id = other`) and then checked whether reparenting is reachable at all: `AgentTeamSlotUpdate` exposes 13 fields and none is `preset_id`, `TeamGithubScopeUpdate` exposes 15 and none is either, and `agent_team_service.py` contains **zero** `.preset_id = ` assignments outside construction. Reparenting is an operator-SQL act — real, but not a mechanism to design a branch around. The reachable one is `accept_handoff`:

```
after handoff of a PENDING, PREPARED item to slot 2 (preset 2):
    dispatch_status = 'pending'   <- still pending, still polled
    owner_slot_id   = 2     (was 1)
    routing_method  = 'reassigned'
    nonce / head    = 'd2fb1f4216212745'
                      'deck/slot-1/issue-42-d2fb1f4216212745'   <- still names slot 1
    round           = 1
    preset_slots for this scope: [1]
    owner resolvable in preset_slots: False
```

`accept_handoff` (`:697-710`) checks only that the accepter equals `handoff_target_slot_id`; it validates no preset, no scope and no `enabled` flag. `POST /dispatch-status` reads `item.dispatch_status` only in the `workspace_released` branch (`agent_teams.py:341`), so there is no gate stopping a handoff from landing on a `pending` row. The result is a prepared item whose owner is a slot the dispatch loop was never handed — reached with no operator SQL and no crash. §4.2b's `slots_by_id.get(...) is None` branch is the thing that catches it. **The looser writer decides which states the reader must handle**, and this is the third time in this spec that `initiate_handoff`/`accept_handoff`'s missing validation sets the requirements for code elsewhere (see also §4.2a rule 5 and blocker 3's authorization discussion below).

**Two conditions, one reason, two notes.** The escalation reason is `prepared_owner_unavailable` for both, because the operator's next action is the same shape — remove the cause, then resume the attempt through §4.2b.2 — but the note must say which cause, and must name the owner. It is deliberately **not** "re-enable or retry": retry is the one action this branch forbids, for the reason three paragraphs down, and an earlier revision of this table said "retry" in the same breath as the prose that prohibits it.

| Row shape | `attempt_state` | Where it is caught | `status_note` must say |
|---|---|---|---|
| owner deleted (FK nulled the column) | **PARTIAL** (raises) | step 2, `plan_blocked` | which markers survived and that the owner is NULL — the exception's `detail` |
| owner disabled | PREPARED | step 3, `prepared_owner_unavailable` | slot *N* (`display_name`) is disabled; the attempt's head; **re-enable the slot, then resume via §4.2b.2** |
| owner not in this preset's slots | PREPARED | step 3, `prepared_owner_unavailable` | slot *N* is not a slot of this scope's preset (a handoff, or a reparent); the attempt's head; **move the item back into the preset via §4.2b.2** |

**The escalation keeps the nonce, the head, the round, the owner id and the workspace lease.** The nonce and head for §4.2a property 6's reason: a hard death after `launcher` returned but before `:333` leaves a **live pane** with a `pending` row, so the attempt identity must stay valid or that pane's every `deck_request_context` and every ack refuses `no_linkage`. The owner id because it is the only record of who was told, and the operator needs it to decide whether the pane is theirs. The **lease** because releasing it is how a second agent gets handed a worktree the first one may still be writing in. §4.2a's `:317` `except ValueError` branch releases the workspace — correct there, because the exception means `launcher` refused and no pane exists — and wrong here, because here the pane may be exactly what is holding the tree.

**Not releasing is only defensible if something else bounds the hold, and something already does.** `"escalated"` is a member of both `_RELEASABLE_STATUSES` (`github_dispatch_service.py:29`) and `_RECLAIMABLE_STATUSES` (`github_workspace_service.py:28`), so both existing lease passes already cover an escalated item that still holds one. Measured end to end:

```
after escalate() with no release: lease held by item 1, status='escalated'
remind_held_leases -> 1 reminder(s); subjects=['Release needed: issue #42']

escalated item, lease aged past the backstop:
    pane reported ALIVE -> reclaimed 0, leased_item_id=1
    pane reported DEAD  -> reclaimed 1, leased_item_id=None
    item's nonce after reclaim: '4463ca302d1d6004'  <- untouched
```

The pane-live guard (`reclaim_stale:296`) is doing the discrimination the dispatch loop cannot do, and `release` touches the workspace row only, so the attempt record survives for whoever investigates. **Two caveats a plan must carry, both measured, because both make the bound weaker than it looks:**

- **A `primary` workspace is never reclaimed.** `reclaim_stale:292-293` skips `kind == "primary"` unconditionally, so under identical aged-and-dead conditions it releases nothing: `reclaimed 0, leased_item_id=1`. For a primary workspace the reminder is the only automatic bound and an operator force-release (`agent_teams.py:693-697`) is the only exit. That is consistent with §5.7 — a primary workspace is never given an agent identity — but it means "the backstop covers it" is true for worktrees and false for the primary.
- **The reminder is counted even when nobody receives it.** `notify_owner` resolves the recipient through `_owner_member` → `owner_slot_id` and returns silently when there is no member (`:1051-1053`). With the owner slot's member missing, `remind_held_leases` returns `1` and **zero** messages are sent. So for precisely the population this section is about — items whose owner is unavailable — the mail channel may be empty, and §4.6's operator visibility is the only place the escalation can be seen. That is why the visibility rows are part of this section's work and not a nicety.

**The broadcast's "do not retry" warning does not fire for anything the dispatch loop escalates, and it must not be reused.** `escalate` computes `owner_may_be_active = item.dispatch_status == "dispatched" and item.owner_slot_id is not None` (`:996-998`), and `_send_escalation_broadcast` gates the "this item's owner session may still be working. Do NOT retry it" paragraph on that flag (`:1101-1109`). Every escalation raised from inside `dispatch_pending` is on a row whose status is `pending` **by construction** — that is the query the loop selects on (`:227-234`) — so the flag is always `False` there:

```
pending  + owner set    : owner_may_be_active=False warning present=False
dispatched + owner set  : owner_may_be_active=True  warning present=True
pending  + owner NULL   : owner_may_be_active=False warning present=False
```

This is inherited, not new — the existing `:321` `plan_blocked` escalation has the same blind spot — but it matters more here, because a `pending` prepared item is exactly the shape that can have a live pane, and retrying it mints a fresh nonce, which §4.2a rule 4 and property 6 both forbid while a pane may be alive. **Do not widen `owner_may_be_active`**: it is read by other escalation sites whose semantics would change, and `pending` items with no prepared attempt genuinely have no pane. Put the caution in the `note` instead, which `_send_escalation_broadcast` appends with no gate (`:1110-1111`) and `_apply_escalation` also writes to `status_note` (`:1037-1038`) — one string, both channels, no new flag. Widening the flag is listed as a mutation in §5.8.

So the whole branch is one helper, and every line of it is a decision made above:

```python
async def _escalate_prepared_owner_unavailable(
    self, db, item, owner_slot: AgentTeamSlot | None
) -> None:
    """A prepared item's owner is disabled or no longer a slot of this preset.

    Keeps the attempt record AND the workspace lease: the previous attempt's pane
    may still be alive in that worktree (§4.2a property 6). The lease is bounded
    by remind_held_leases and reclaim_stale, both of which already select
    'escalated' — except for a primary workspace, which only an operator releases.
    """
    if owner_slot is None:
        what = (f"slot {item.owner_slot_id} is not a slot of this scope's preset "
                f"(handed off, or moved)")
    else:
        what = f"slot {owner_slot.id} ({owner_slot.display_name}) is disabled"
    note = (
        f"{what}. This attempt is prepared and its pane may still be live: "
        f"head {item.dispatch_head_ref}, round {item.approval_round_count}. "
        f"Do NOT retry it until you have confirmed the session is gone — a retry "
        f"mints a new attempt identity, orphans the old one, and clears this "
        f"item's round count and verified head. To continue this attempt: fix "
        f"the cause above, then POST resume-attempt (§4.2b.2). The dispatch loop "
        f"will not pick an escalated item up on its own."
    )
    await self.escalate(db, item, "prepared_owner_unavailable", note)
    await db.commit()          # escalate() does not commit; §4.3a.1's rule
```

The trailing commit is not decoration. `escalate` assigns and notifies and does **not** commit (measured in §1.3's table and relied on by §4.3a.1), so a caller that omits it leaves the escalation in memory only — and here the caller's next statement is `continue`, which reaches the loop's next item and its next `commit()`, at which point the escalation would be committed by *something else's* transaction. Explicit is the difference between "escalated" and "escalated, unless the next iteration rolls back." Driven through the real `escalate` with the broadcast raising, and re-read in a **fresh session** — the whole helper, all three claims at once:

```
broadcast RAISED, caller committed -- read in a fresh session:
    dispatch_status    = 'escalated'
    escalation_reason  = 'prepared_owner_unavailable'
    dispatch_nonce     = '2c2bb39d1c9261bf'
    dispatch_head_ref  = 'deck/slot-1/issue-42-2c2bb39d1c9261bf'
    owner_slot_id      = 1   round=1
    status_note starts = 'slot 1 (Alpha) is disabled. This attempt is prepared'...
    workspace lease    : leased_item_id=1 token_present=True

broadcast fine, caller did NOT commit -- fresh session:
    dispatch_status   = 'pending'   <- unchanged
    escalation_reason = None
    workspace lease   : leased_item_id=1
```

Three things that had to be measured rather than reasoned about. First, `escalate`'s failure path calls `await db.rollback()` and then re-applies the escalated state with `preserve_existing_reason=False` (`:1013-1018`) — so a dead mail server does not cost the escalation, but only because the caller commits afterwards. Second, that rollback does **not** release the lease: `acquire` committed it at `github_workspace_service.py:136`, so it is already durable and outside the transaction being rolled back. Third, the no-commit control is the one that shows why this is load-bearing rather than tidy: the row stays `pending`, so the next poll re-runs the same classification, hits the same disabled slot, and escalates again — forever, because nothing about the slot changed. An escalation that does not persist is not an escalation; it is a busy loop with a log line.

**Recovery is not a retry, and this is the one escalation where that distinction is inverted.** Every other reason on the list recovers through `deck_retry_work_item`; this one must not. A retry runs `reset_for_retry`, which clears the attempt columns and lets the next dispatch mint a fresh nonce (§4.2a rule 4) — and the entire premise of this branch is that the previous pane **may still be alive** in the leased worktree. Retrying is therefore the one action that turns a recoverable pause into an orphaned attempt plus a second agent pushing a different head for the same issue.

**But "let the next poll continue the same attempt unchanged" was a design that did not exist, and revision 10 asserted it as though it did.** Blocker 5 of the tenth review, confirmed, and confirmed harder than reported. Three measurements, each of which closes a door the previous revision assumed was open:

| Claim revision 10 needed | Measured |
|---|---|
| the dispatch loop will pick the row up once the slot is re-enabled | **No.** `dispatch_pending` selects `dispatch_status == "pending"` only — one equality, no `.in_()` (`:227-234`). An `escalated` row is never examined, so an operator can re-enable the slot and poll indefinitely with nothing happening. 37n-3's second half, as written, tests a transition no code performs |
| some existing writer moves the row back to `pending` | **One** literal `dispatch_status = "pending"` in the whole service, at `reset_for_retry:64`, reachable by two paths — a direct retry request, and `promote_deferred_retries`, which calls the same function. Two paths, one body, one effect |
| so worst case the operator retries and loses only time | **No.** That single body clears `approval_round_count` (3 → 0), `last_verified_sha` (set → `None`) and `escalation_reason` (set → `None`) on the way through (`:66-73`). The only reachable route to `pending` **destroys** the evidence 37n-3 asserts survives. `owner_slot_id` and `routing_method` do survive, which is the one thing a new transition can reuse |

And the deferral branch does not save it either, because two individually sound choices are jointly a deadlock: `reset_for_retry` early-returns and only sets `retry_requested_at` while a lease is held (`:41-50`), leaving the row `escalated`; the promoter that would later pick it up requires `GithubWorkspace.id IS NULL` (`:52`); and §4.2b.1 **deliberately keeps the lease** so the possibly-live pane's worktree survives. Measured: `promote_deferred_retries` returns `0` while the lease is held. Holding the lease to protect the attempt is exactly what blocks the only promoter that could move the row.

So the amendment **adds** a transition rather than redirecting to an existing one. Two design questions follow, and both are settled by measurement rather than preference.

**Where it runs: an explicit operator action, not a pre-pass inside `dispatch_pending`.** The tempting shape is a pre-pass beside `reclaim_stale` that promotes any `prepared_owner_unavailable` row whose cause has cleared. It is tempting because it needs no new endpoint. It is wrong, and the reason is one function call upstream:

```
_pending_issues_by_number, status='escalated' -> asked GitHub for [], dict keys=[]
_pending_issues_by_number, status='pending'   -> asked GitHub for [42], dict keys=[42]

brief WITH issue_details : 2398 chars, issue body present=True
brief WITHOUT            : 2377 chars, issue body present=False
the substituted text     : '(No issue body provided.)'
labels line WITH / WITHOUT: True / False
```

`github_dispatch_scheduler.py:151-160` fetches issue bodies for `pending` rows and hands them to `dispatch_pending` as `issue_details_by_number` — **before** the loop runs, and short-circuiting to `{}` on an empty list without calling GitHub at all. A row promoted *inside* the loop is selected by the loop's own query but is absent from the dict the brief is built from. And `_dispatch_brief` does not fail on the gap; it **fills** it, substituting `"(No issue body provided.)"` (`:389`) and dropping the labels (`:384-388`). The resumed agent gets a well-formed prompt containing an affirmative false statement about the issue it is resuming. That is a worse failure than an exception, because nothing observes it. A pre-pass would therefore need to either re-fetch inside the loop or be placed before the prefetch — at which point it is a scheduler-order change, not a small local one.

An explicit operator transition avoids all of it: the row is `pending` before the scheduler's next tick begins, so the prefetch sees it and the brief is whole.

**What it must not do: release and re-acquire.** The single most likely wrong implementation is to release the lease and let the resumed dispatch take it again, which reads as symmetric and is destructive. Measured:

```
acquire() on an item already holding a lease:
    same workspace row      : True
    lease_token             : 'tok-original'   (unchanged)
    reset_workspace called  : []
control, lease NOT held -> token='84c6a2c535ed7d25' (minted), reset_workspace called=[2]
```

`acquire` returns the held workspace at `:103-109`, **before** the token mint at `:129` and before `reset_workspace` at `:138`. So a resumed prepared item walks through the existing guard untouched — same row, same token, and critically **no worktree reset**. Release-then-reacquire would run `reset_workspace` over a tree the previous pane may still be writing in, which is the precise harm §4.2b.1 keeps the lease to prevent. The control proves the early return did that work rather than a stubbed-out path. The resume transition therefore touches `github_work_items` only, and the lease is carried by doing nothing to it.

#### 4.2b.2 `POST /agent-teams/{preset_id}/work-items/{item_id}/resume-attempt` — operator only, behind `require_operator`

This endpoint serves §4.2b.1's `prepared_owner_unavailable` recovery, in both of that section's PREPARED shapes: an owner that has come back, and an owner that has left the preset and must be replaced. Either way it is an operator saying "I have looked at this and the attempt should continue" — a claim no agent can make on its own behalf, which is why §3.5a's matrix has no leader row for it and why §3.6a's credential, not the absence of one, is what makes "operator only" true.

**Scope, narrowed from revision 11.** This route serves `prepared_owner_unavailable` **only**. Revision 11 opened this section by saying it served "two needs that arrive from different directions," the second being §3.5a point 4a's wedged owner, and then narrowed the scope three lines later — the withdrawal and the claim it withdraws sat one paragraph apart. The claim is gone from both places now. Revision 11 also advertised it for a generally "wedged" owner, and that claim was unreachable against its own precondition: a wedged *dispatched* owner escalates as `owner_offline` (`github_dispatch_service.py:760`) or `owner_idle_timeout` (`:803`), neither of which passes a check requiring `escalation_reason == "prepared_owner_unavailable"`. The prose promised a case the table refused. Supporting those two reasons is a different design — their attempts are *dispatched*, so a live pane may hold the worktree and the recovery question is about killing a session, not resuming a preparation — and it is not attempted here. §3.5a point 4a's leader case is served for the prepared state and recorded as out of scope for the dispatched ones (§6).

| | |
|---|---|
| Caller | **operator only, enforced by `require_operator`** (§3.6a). Not "the unauthenticated surface force-release sits on" — that phrase described an absence, and `agent_teams.py` has zero non-`get_db` dependencies today. No session token and no slot derivation, because the caller is not an agent; the point of the dependency is that an agent cannot mint the credential |
| Body | `resume: true`, and optionally `reassign_to_slot_id` |
| Precondition | `dispatch_status == "escalated"` **and** `escalation_reason == "prepared_owner_unavailable"`. Any other row ⇒ `409 not_a_resumable_attempt`. This is not a general un-escalate button |
| Effective owner | `effective_owner = reassign_to_slot_id or item.owner_slot_id`. **One definition, stated before any check reads it** — revision 11 said "the owner slot" while offering a reassignment field, leaving both readings live and neither specified. Every check below is about `effective_owner` |
| Owner validation | **Three predicates on `effective_owner`, and they are the same three whether or not a reassignment was supplied:** it must **exist**, be **`enabled`**, and satisfy `slot.preset_id == scope.preset_id`. Only the refusal code differs, because only the operator's next action differs — with a reassignment, `409 invalid_resume_target`; without one, `409 owner_still_unavailable`. Both name which of the three failed and which slot. Two codes rather than one because *your target is wrong* and *the cause you were told to fix is still there* send the operator to different places, and a single code would make the more common case read like a bad request |
| Why one rule and not two | Revision 12's first draft of this table wrote target validation and the cause check as separate rules, the cause check testing `enabled` alone — and that was wrong for §4.2b.1's **second** PREPARED row. Its cause is *owner not in this preset's slots*, and such an owner is typically enabled, in another preset. So a same-owner resume passed the cause check with the cause fully intact, flipped the row to `pending`, and the next poll re-escalated it with the identical reason: precisely the bounce the cause check exists to prevent, described in that draft's own text one cell away. **The cause is whatever §4.2b.1's step 3 refused on, so the check has to be step 3's predicate, not a subset of it.** Collapsing the two rules is what makes that true by construction instead of by remembering. The cross-preset predicate is load-bearing in both directions: `reassign_to_slot_id` is an integer from a request body, and §4.8's 37r-3 measured that the analogous handoff field accepts a nonexistent id outright when `PRAGMA foreign_keys` is off |
| The old owner | With a reassignment, the **previous** owner may stay unavailable — disabled, deleted, or in another preset. That is the entire purpose of the field, and requiring otherwise would defeat the recovery it exists for. Note this is the one asymmetry between `effective_owner` and `item.owner_slot_id`: the checks above never look at the row's stored owner, only at the slot that will own it next. The stored owner is read exactly once more, by the liveness check below, and for a different question |
| Liveness check | **required, and this is the check the agent route could not perform.** If the previous owner's pane is still alive, resuming hands a live agent's work to a second one. Read §4.6b's evidence on the leased workspace and resolve the recorded `(leased_owner_pid, leased_owner_proc_start)` through `agent_pane_bindings` (§3.3) to a slot — **do not infer a slot from a pid alone**, which is what revision 11's "the recorded pane is not the slot being resumed to" silently required of columns that store no slot id. Three outcomes: resolves to a *different* slot and `_owner_process_is_alive` is true ⇒ `409 previous_owner_still_alive` with the pid and slot in the detail; resolves to `effective_owner` ⇒ proceed, this is the same-owner resume; **does not resolve, or the pid is NULL ⇒ `409 previous_owner_liveness_unknown`** for a reassignment, and proceed for a same-owner resume. The asymmetry is deliberate and is the fail-closed direction: reassignment hands the worktree to a *second* process, so unknown liveness must refuse, while a same-owner resume gives it back to the slot that already had it. An operator who genuinely wants to override force-releases first — an action that already exists and already reads as dangerous |
| Writes | `dispatch_status = "pending"`, `escalation_reason = None`, `pending_reason = None`. On reassignment also `owner_slot_id = effective_owner` and `routing_method = "operator_resume"`. The new owner learns what it owns through §4.6a's authenticated claim, exactly as a handoff target does — this route delivers no context and no token |
| Must **not** write | `approval_round_count`, `last_verified_sha`, `dispatch_nonce`, `dispatch_head_ref`, `retry_count`, and **nothing at all** on `github_workspaces`. Explicitly: it does not call `reset_for_retry`, and it does not call `release` |
| Commits | once, at the end. The row is `pending` before the next scheduler tick, so the issue prefetch sees it |

`routing_method = "operator_resume"` is a **new value in an existing column**, not a new column and not a new `dispatch_status` — the standing no-new-status rule holds. Measured, the column carries four values today: `label`, `classified`, `leader_fallback` (`route_item`, `:120/:126/:114+:128`) and `reassigned` (`accept_handoff:708`), and unlike `dispatch_status` and `escalation_reason` it has **no** declared frozenset in §5.8's 29-a and no runtime funnel. So there is nothing to add the value to and nothing to break — but that also means an implementer who writes a different string here breaks no test. If the value matters to anyone downstream, the enforcement has to be a test in §4.8 that reads the column after a resume, which is what 37n-9 does. Do not invent a `ROUTING_METHODS` frozenset for this one value; three of the four existing values come from one function's return tuples, so the equality set would be enforcing a shape nothing else needs.

**Why the reassign case belongs here and not on `initiate_handoff`.** A handoff transfers a live lease between two agents and is initiated by the party giving it up (§3.5a point 4a). This is the opposite situation: the giving-up party is *gone*, so there is nobody to initiate. The two look similar in the database and are different in the only respect that matters — whether the previous owner is around to consent, and whether anything has checked that its worktree is safe to hand over. The liveness check above is what makes this operation different in kind from the agent route, not merely differently authorized.

**And why `reassign_to_slot_id` is kept rather than dropped.** The eleventh review offered removal as the alternative to full specification, and that would be the right call if the field served only the unreachable wedged-owner claim. It does not. §4.2b.1's table has **two** PREPARED rows, and the second is *owner not in this preset's slots* — a handoff or a reparent — whose own `status_note` already instructs the operator to "**move the item back into the preset via §4.2b.2**." Re-enabling recovers the first row; only reassignment recovers the second, and it is the reassignment the note has been promising since revision 11. Dropping the field would leave that row's stated recovery pointing at a route that cannot perform it, and the operator's only remaining action would be the retry that clears `approval_round_count` and `last_verified_sha` — the exact defect the tenth review's blocker 5 raised. The field is load-bearing for one of the two conditions this escalation covers; what was wrong was the specification, not the option.

**Residual risk, stated.** The liveness check reads the same PID evidence §4.6b repairs, so this endpoint inherits that section's correctness: if a handoff has left the workspace naming a stale pane, `previous_owner_still_alive` can be wrong in either direction. That is one more consumer of the evidence and one more reason §4.6b lands in the same PR, not a later one.

For the same reason the reason is **not** added to `_PR_OPENED_RECOVERABLE_ESCALATIONS` (`github_verification_service.py:29-37`). Its six members all mean *the agent got stuck and a late PR resolves it*; this one means *the owner is gone while its attempt may still be running*, which a PR report does not resolve — and the most likely sender of that report is the departed owner's own pane. Measured, adding it is not a lost escalation but a promotion: `escalation_reason` cleared and `dispatch_status = 'verifying'`, the auto-merge pipeline's input, with the owner still unavailable and no notification sent. Test 37n-8 covers both halves; §5.8's mutation table carries the row.

**What this does not change.** The guards' content is untouched: `slot_is_busy`, `_session_ambiguity_note` and `acquire` are called in the same order with the same arguments, and their `pending_reason` values are unchanged. Their `item.owner_slot_id = owner_slot_id` / `item.routing_method = method` writes stay as written and simply become no-ops on a prepared item — deleting them would be the more elegant change and the riskier one, because those same lines are the *only* owner write on the unprepared early-exit paths, which is how a queued item gets an owner recorded before it is ever dispatched. `:332-333` is different: §4.2a already deletes it, because there preparation is the authoritative writer and the line is a second one.

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
3. Find `context_request` rows whose payload `work_item_id` equals `item.id`, sent by the owner member and addressed to the leader member. If **no** row matches the work item at all ⇒ refuse `no_linkage`. If a row matches the work item but **none** matches `item.dispatch_nonce` ⇒ refuse `stale_nonce`. If a row matches the nonce but **none** carries `approval_round == item.approval_round_count` ⇒ refuse `stale_round` (§4.3a.1) — the owner is replaying an approval from before a revision was requested. Evaluate in that order, so the three reasons stay distinguishable: `no_linkage` means "they never asked," `stale_nonce` means "they are replaying an older *attempt*," `stale_round` means "they are replaying an older *round* of this attempt." A NULL `item.dispatch_nonce` (a pre-upgrade row) can never match, so it refuses `stale_nonce` — correct, and §4.1 already states such items must be re-dispatched. A NULL payload `approval_round` likewise never matches, refusing `no_linkage` per §4.3a.1. `item.approval_round_count == 0` means no round is open (§4.2a), so it too can never match a stated round and refuses `stale_round` rather than matching a request that said `0`.
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
    """Record an explicit approval decision for a dispatched work item.

    Only the designated team leader's decision counts, and it only counts for
    the dispatch attempt named by dispatch_nonce, in the approval round that is
    currently open.

    decision="rejected" also opens the next approval round: it clears the
    previous round's approval so the merge gate no longer passes, and the owner
    revises and sends a new deck_request_context. No other call is needed by
    anyone. If no round remains under the scope's max_approval_rounds, the item
    escalates for a human instead (approval_rounds_exhausted).
    """
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

**The tool does not choose the thread; the server resolves it.** `deck_approve_work_item` takes a work item and a nonce, not a `thread_root_id`, so it needs one new route: `POST /agent-mail/decisions`, which resolves the `context_request` whose payload matches `(work_item_id, dispatch_nonce, item.approval_round_count)` **and** whose `recipient_member_id` is the authenticated caller. It then branches on the verdict:

- `approved` ⇒ delegate to `send_message` with `kind="answer"` and the decision. Nothing on the work item changes; §4.3's ack path is what reads the row.
- `rejected` ⇒ call `advance_approval_round` (§4.3a.1), which writes that same `answer` row **and** opens the next round in one commit. The route does not write the decision row itself in this branch, because splitting the write from the transition is exactly the defect §4.3a.1 exists to remove.

Resolution is server-side on purpose:

- The leader cannot post a decision into the wrong thread by mistyping an id.
- The existing `send_message` answer guard (`:859`, "only the context request recipient can answer it") is preserved rather than bypassed — the leader *is* the recipient of the owner's request, so the guard passes for exactly the right party and fails for everyone else.
- Zero matching requests ⇒ `404` (nobody asked for this item under this nonce **in the current round**). More than one *from the current owner* ⇒ `409` with both ids; do not guess. Multiple matches mean the owner opened two threads for one round, which is a shim bug worth surfacing rather than papering over. Two matches from *different* owners is the handoff shape (§4.2) and resolves to the current owner's, not a `409`.

#### 4.3a.1 The rejection *is* the transition — one function, one commit

Revision 4 told a rejected owner to "revise the plan and ask again," and the fourth review's second blocker was that this does not work as specified. Three problems, all confirmed then and all still worth stating because the fix must close all three:

1. **The second request collides with my own `409`.** §4.3a resolved the thread from `(work_item_id, dispatch_nonce)`, and the nonce does *not* change on revision — only on re-dispatch (§4.2). So an owner who asks again has two `context_request` rows matching the same pair, which is precisely the "more than one ⇒ `409`; do not guess" case. The documented recovery path was unreachable through the documented tool.
2. **`record_approval_round` does not identify anything.** Measured, it is four lines: increment the counter, escalate at the cap, commit (`github_dispatch_service.py:672-679`). It does not name the active request, does not touch the ack columns, and does not know a decision exists.
3. **Approve-then-reject still permits auto-merge.** Revision 4 argued a recorded approval should stand because the owner may already have pushed. True as far as it goes — but revision 4 offered `revision_requested` as the leader's remedy, and `revision_requested` clears no ack columns. The leader's stated lever did nothing to the gate.

**Revision 5 split the fix across two operations and thereby kept the deadlock.** It made the verdict structured (`deck_approve_work_item`) and left the transition where it was (`revision_requested` → `record_approval_round`). The fifth review's second blocker is what that split produces:

- The §3.5a matrix made `revision_requested` **leader-only**, while this section said "the leader or the owner" — a flat contradiction between two sections of one spec.
- The owner was told to *"revise the plan and ask again"* through a branch the matrix forbids them to call.
- **Nothing obliged the leader to make the second call.** A leader who rejects and stops has done everything the tool contract asks; the round never advances, the ack columns are never cleared, and the owner cannot legally open round 2. Same deadlock, one layer further in.

**Decision: `deck_approve_work_item(decision="rejected")` advances the round itself.** There is no second call to forget. One function on the dispatch service replaces `record_approval_round`:

```python
async def advance_approval_round(
    self,
    db: AsyncSession,
    item: GithubWorkItem,
    scope: TeamGithubScope,
    *,
    decision_message: MailMessageCreate,
) -> None:
    """Record a rejection and open the next approval round in one commit."""
```

It is called from the `POST /agent-mail/decisions` route (§4.3a) when and only when `decision == "rejected"`, after that route has resolved the thread and authenticated the leader. An `approved` decision does not call it: approval ends the round, it does not open one.

**Two branches, not one sequence.** Revision 6 wrote this as a universal order — clear, increment, commit the decision, then *maybe* escalate — and the sixth review is right that the cap case does not fit it. At the cap nothing is cleared and nothing is incremented, so "step 4 is conditional" understates the difference: the two paths share only the decision row. They are specified separately, and each one's commit boundary is stated because in this codebase the commit boundary is where the correctness lives.

**Branch A — below the cap (`item.approval_round_count < scope.max_approval_rounds`).** One commit, no escalation:

1. Clear the five ack columns and `last_nudge_at` on `item` — **pending, not committed**.
2. Increment `item.approval_round_count` — pending.
3. Call `send_message` with the `answer` row carrying `decision = 'rejected'`. `send_message` ends in `await db.commit()` (`agent_mail_service.py:899`) on the **same** `AsyncSession`, so that one commit persists the decision row *and* steps 1-2 together. Verified directly: mutate an item without committing, call `send_broadcast` on the same session, then read the row back through a raw `text()` query that bypasses the identity map — the mutation is present.

Nothing escalates on this branch, so there is no rollback to order around. The ordering still matters for a different reason, recorded here because revision 6 measured it: putting an `escalate` call *before* step 3 would discard steps 1-2 entirely, since `escalate` calls `await db.rollback()` when its broadcast raises (`github_dispatch_service.py:1017`, inside `except Exception` at `:1013-1018`). Measured with the broadcast monkeypatched to raise: `approval_round_count` unchanged and `ack_received_at` **still set**, while the `answer` row persists from its own commit — the leader's rejection on the record beside a live approval. Branch A avoids it by construction.

**Branch B — at the cap (`item.approval_round_count >= scope.max_approval_rounds`).** The counter does not move, the ack columns are **not** cleared (an operator needs to see what the leader last approved), and the item escalates. The hazard here is real, and revision 6's ordering did not address it because revision 6 treated escalation as a tail-call on branch A.

`escalate` applies the escalation in memory, and on broadcast failure it **rolls back and re-applies in memory without committing** (`:1017-1018`). It has no `commit` of its own. So "write the decision through `send_message`, then call `escalate`" leaves the escalation *only* in the session. **Measured** — the probe is in the table at the top of this spec:

```
IN MEMORY after escalate: status='escalated' reason='approval_rounds_exhausted'
ON DISK:                  dispatch_status='dispatched' escalation_reason=None
ON DISK:                  ack_received_at=SET  round=3  note='REJECTED by leader (round 3)'
```

The rejection is durable and the escalation is not. Worse than the review states: `ack_received_at` is still set on disk, so the item is not merely un-escalated — it is un-escalated *with a live approval*, which is the exact state §4.3a exists to prevent.

**Why today's code does not have this bug, and why the plan must not inherit it.** `record_approval_round` calls `escalate` and then `await db.commit()` at `:679`. That trailing commit is load-bearing and unremarked — it is the only reason the current escalation is durable. Any refactor that moves the escalation into a function whose caller commits *first* silently removes it. That is precisely the seam this spec keeps finding: the commit that makes a neighbour correct is invisible from the neighbour.

So branch B is specified as **one commit containing both**, with the notification strictly after it:

1. Build the `answer` row carrying `decision = 'rejected'` and add it to the session — **do not** call `send_message` (its internal commit is what splits the transaction).
2. Apply the escalated state on `item`: `dispatch_status = "escalated"`, `escalation_reason = "approval_rounds_exhausted"`, `pending_reason = None`. Reuse `_apply_escalation` (`:1020-1040`), which does exactly this and does not commit.
3. `await db.commit()` — **one** commit, decision row and escalated state together.
4. Send the escalation broadcast as **post-commit best effort**, inside its own `try/except` that logs and swallows. A failed notification must not roll back a committed escalation.

This needs a no-commit variant of the mail write. The plan must add `send_message(..., commit=False)` (or a `_build_answer_row` helper the route adds to the session itself) rather than calling the committing version — and PR1's task for this must state that the parameter exists **for** branch B, because a future reader deleting an "unused" flag would reintroduce the split silently.

**The exposure, characterized precisely.** The review calls the un-escalated state an auto-merge exposure via `process_scope`. That needs one correction: `process_scope`'s query also requires `pr_number IS NOT NULL` (`github_verification_service.py:99`), and an item at the approval cap has not opened a PR yet, so `process_scope` does not select it. The real exposure is the **monitor**, which selects `dispatch_status == "dispatched"` with `pr_number IS NULL` (`github_dispatch_service.py:738-746`) — exactly this item. With `ack_received_at` still set, `_ack_satisfied` returns `True` (`:902-912`), so the item skips the ack gate at `:778` and falls through to the idle-timeout branch at `:792`. The item is not auto-merged; it is treated as **an item whose plan the leader approved**, and the next thing that can happen is the owner proceeding on a rejected plan. That is a worse outcome than the review's framing, by a different mechanism, and it is why branch B is one commit rather than two.

**The cap is a precondition, not a post-check** — the arithmetic is stated once, normatively, in §4.2a. Branch A and branch B above *are* that `if`/`else`; neither is a modifier on the other.

One measured caveat that applies to both branches: `escalate` returns early without notifying when the item is *already* `escalated` with a reason (`_apply_escalation:1020-1040`, whose `preserve_existing_reason=True` default makes the guard at `:1028-1033` return `False`, and `escalate:1000-1001` then returns). Verified — a rejection against an item already escalated as `leader_offline` advanced the counter to `2` and kept `escalation_reason = "leader_offline"`, sending no broadcast. `advance_approval_round` must therefore refuse before doing anything when `item.dispatch_status == "escalated"`: `409 item_escalated`. A leader deciding on an escalated item is acting on stale information, and the round must not move underneath a human who has already been called in.

The bound worth keeping from revision 6: `approval_rounds_exhausted` is **not** in `_PR_OPENED_RECOVERABLE_ESCALATIONS` (`github_verification_service.py:29-37`), and `process_scope` never polls `escalated` (`:96-107`). So a correctly-escalated item stalls for a human rather than proceeding — which is the right failure, and the reason branch B's durability matters.

**What `revision_requested` becomes: a `409`.** It is retired as an agent-reportable status (§3.5a), refusing with `use_deck_approve_work_item` for **every** caller — leader, owner, and third party alike. The branch is not deleted, because the shim's docstring still advertises it (`mcp_shim/agent_mail_server.py:612`) and a deployed agent will call it; a named refusal that tells the agent which tool to use instead is strictly better than a `422` on an unknown enum value. This is what closes the contradiction: there is no longer a question of *who* may report `revision_requested`, because nobody may, and the authority that used to attach to it now attaches to the decision itself — which only the designated leader can write (§4.3a).

**Withdrawal is implicit and total.** The leader needs no second tool to revoke, because opening the round drops the previous round's evidence by construction. And this resolves problem 3 without the retroactive-un-approval hazard revision 4 was right to avoid: the approval is not reversed, it is *superseded*, by the single act the leader already performs.

**Approve-then-reject within one round** keeps revision 4's rule with a correction to its reasoning. The `approved` row stays in the thread — history is not rewritten — but the *rejection* is now a real transition, so it clears the ack columns and opens the next round exactly as any other rejection does. Revision 4 said the approval "stands"; that was correct only because it had no working lever. With `advance_approval_round` the lever exists, and a leader who changes their mind gets the behavior they obviously intend: no merge on the approval they just withdrew. The owner may already have pushed a PR — that PR simply needs approval in round 2, which is the whole point of the gate.

**A NULL `approval_round` in the payload** — from a pre-upgrade shim, or `deck_request_context` called without it — cannot match round 0 by accident. Treat NULL as "no round stated" and refuse `no_linkage`, on the same reasoning §4.3 rule 3 already applies to a NULL nonce: an item whose evidence predates the linkage requirement must be re-dispatched, not grandfathered.

**Why not a separate `approval_rounds` table.** A round is one integer per item with a cap of 3, and every question the gate asks is answerable from the counter plus the payload. A table would add a migration, a join, and a second source of truth for "which round are we in" — and the counter would still exist, because the cap reads it. Rejected on that measurement, not on taste.

**`deck_reply` is unchanged and still writes `decision = NULL`.** The leader keeps a way to say "I read this, here are my questions" without approving — which is what rows 82 and 92 were actually doing. Their author was behaving correctly; the *gate* was wrong to read them as approval. A `deck_reply` does **not** advance the round: only a structured rejection does.

**The brief, the nudge, and the tool docstring must all say the same thing.** `_leader_ack_instruction` (`:541-573`) currently tells the owner to wait for "acknowledgment." It now tells the owner to wait for the leader's `deck_approve_work_item` decision, **and that a rejection opens the next round automatically — the owner revises and sends a fresh `deck_request_context`, calling nothing else.** `_nudge_leader_for_ack` (`:920-943`) asks the leader for a decision by name, passing `work_item_id` and `dispatch_nonce` (the nudge payload already carries `work_item_id` at `:939`). `deck_approve_work_item`'s own docstring (§4.3a) states that `decision="rejected"` advances the approval round and clears the previous round's approval. Wording carries no enforcement weight — but the whole of blocker 2 was an actor not knowing which call to make, and three pieces of copy are where that is prevented.

**Refusal is not escalation** (until the cap). A `decision = 'rejected'` below the cap leaves the item `dispatched` in a fresh round with no approval, and the existing monitor path handles the rest: nudge, then `leader_ack_timeout` (`:785-791`) if the next round also goes unanswered. No new `dispatch_status` value, and the only escalation reason involved is the existing `approval_rounds_exhausted`.

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

The round comparison is what makes a *withdrawn* approval fail the gate rather than merely being absent. §4.3a.1 has `advance_approval_round` clear the ack columns, so in the ordinary case the approval is gone and `ack_approver_member_id is the leader` already fails. The comparison is the belt to that suspenders: if a future change to `advance_approval_round` forgets the clear — the exact off-by-one that revision 2 committed with `accept_handoff` — the round mismatch still refuses. There is a second, measured reason to keep both guards: `advance_approval_round`'s clears and its increment ride the decision row's commit, and an escalation on the same call can `rollback` (§4.3a.1). The specified ordering keeps both together, but *any* future edit that reorders them can persist one without the other. Two independent guards mean either survivor refuses. Fail closed twice on the path where the cost of failing open is a merge nobody approved.

The check reads the **persisted** columns, not a fresh mail lookup: PR0 plus §4.3 mean the columns can only have been written by a verified approval, and re-deriving at merge time would read a mail table that may have changed for unrelated reasons.

**One exception to "read the persisted columns."** The gate does *not* re-read `mail_messages.decision`, and that is safe for the same reason: `ack_approver_member_id` is only ever written by §4.3 rule 5, which only runs after rule 4 has found an `approved` row. The persisted column is a *record* of a decision check that already happened under enforcement, and `ack_enforcement_epoch` is what proves the regime it happened under. Re-reading the mail row at merge time would add nothing and would introduce a second code path that could disagree with the first.

**Why the settings check belongs in the gate.** PR0 ships with `mail_capability_tokens_required = False` so deploying it breaks nothing (§3.4). But in that mode a tokenless caller still supplies its own `sender_member_id`, so `ack_approver_member_id` is exactly as forgeable as it was before PR0. A gate reading a forgeable column is the failure this spec exists to prevent, so the gate refuses with `tokens_not_enforced` until the operator has restarted the panes and flipped the flag. The refusal names the setting, so the operator sees a configuration step rather than a mystery.

This is the one place the three PRs are coupled at runtime rather than only in sequence, and it is deliberate: it makes "PR0 deployed but not enforced" a *safe* state instead of a silently-degraded one.

**Do not route this through `_ack_satisfied`.** That function short-circuits on `if item.pr_number is not None: return True` (`:903-904`), which is correct for its actual job — once a PR exists, nudging the leader for an ack is pointless. But auto-merge only ever runs on items that **have** a `pr_number` (`github_verification_service.py:99` filters on `pr_number.is_not(None)`), so reusing `_ack_satisfied` as the merge gate would return `True` unconditionally, every time. The gate would be a no-op that reads like enforcement — the same failure mode as a silent test.

So the new condition is a **separate** predicate reading `ack_approver_member_id` directly, and `_ack_satisfied` keeps its one existing caller and its current behavior. Test 12 is the one that catches this: an item with a PR, CI-green, fresh head, and no approval must **not** merge. Written against `_ack_satisfied` it would pass while proving nothing.

Failing it routes to the existing `_fallback_to_human_merge` (`:421-432`), which sets `ready_for_review` and a note — and because that note is matched by `_HUMAN_MERGE_NOTE_PREFIXES` (`:20-25`), the new note **must** start with `"Auto-merge blocked"` so the fallback is sticky and does not re-run every poll. Revision 1 missed this; a note with any other prefix would loop.

A leader-owned code item therefore cannot auto-merge; it waits for a human. Finding #1 is closed by construction rather than by prompt discipline.

### 4.6 Operator and agent visibility

`GithubWorkItemResponse` (`schemas.py:2272-2299`) and `_work_item_response` (`agent_teams.py:196-229`) both enumerate every field by hand — 27 each, no `**kwargs` splat, no `model_config` allowing extras — so a new column is invisible until added in **both** places. All **six** new columns are added to both: `ack_approver_member_id`, `ack_evidence_message_id`, `dispatch_nonce`, `ack_enforcement_epoch`, `ack_approval_round`, and `dispatch_head_ref` (§4.1's sixth rung, without which an operator diagnosing a `head_ref_mismatch` cannot see the head the item is being measured against). `approval_round_count` is already exposed at `agent_teams.py:218`.

**Two surfaces are not enough, and the previous revision said they were.** Adding a field to those two makes it visible over HTTP and therefore in the UI. It does **not** make it visible to the leader, because `deck_list_work_items` does not return the response payload — it re-projects it into a hand-written five-key dict (`mcp_shim/agent_mail_server.py:667-673`). Measured by driving the real shim function against an HTTP layer stubbed to return a payload carrying all six:

```
GithubWorkItemResponse   27 fields, hand-enumerated, no extra=allow
_work_item_response      27 keywords, no splat
deck_list_work_items ->  ['work_item_id', 'issue_number', 'dispatch_status',
                          'escalation_reason', 'status_note']

leader receives:     ['dispatch_status', 'escalation_reason', 'issue_number',
                      'status_note', 'work_item_id']
dropped by the shim: all six
```

So the shim's projection is a **third** enumeration, and the leader-facing half of the plan has to name it. It gains three of the six — `ack_approval_round`, `ack_enforcement_epoch`, and `dispatch_head_ref`. Not all six: the leader is the *approver*, and what it needs when an item it believes it approved will not merge is which round its approval was filed under, which regime it was filed under, and which head the owner's PR is being checked against. The two `ack_*_id` columns and the nonce are diagnostic plumbing for the operator, and the leader has no call that takes them.

`mail_messages.decision` needs the same treatment one table over, and its surface count is genuinely two rather than three — for a reason worth stating, because it is what makes the work-item case a finding instead of an oversight. `MailMessageResponse` enumerates its fields by hand too (`schemas.py:1877-1894`), so the column must be added there; but `deck_check_inbox` returns `{"ok": True, **result["data"]}` (`agent_mail_server.py:269`), a splat of a `MailInboxResponse` whose `messages` are `MailMessageResponse` objects. A field added to the model therefore reaches the agent with no shim change at all. Without the model addition the decision is invisible in the thread view, in `deck_check_inbox`, and in the UI — the operator would see a gate refusing an item and an approval-looking reply, with no way to tell which reply carried the decision.

An unaudited safety gate is a claim, not a control. The rule this section is really about: **a field is visible only as far as the last hand-written projection between the column and the reader.** Two tools in one shim file, both nominally "read Deck state," differ in whether they pass a new field through — because one splats and one re-projects. Counting the layers means reading each reader's own code, not assuming a house style; test 37q asserts all three projections, and a mutation row covers the shim.

**§4.2b.1's escalation needs no new column, and that is a conclusion, not an assumption.** `prepared_owner_unavailable` travels in `escalation_reason` and its diagnosis in `status_note`, and the transcript above shows both are already in all three projections — including the shim's five-key dict, which carries exactly these two. So the operator sees it in the UI and the leader sees it in `deck_list_work_items` with no plumbing added. This is the practical argument for making it a *reason* rather than a distinguishing note on `plan_blocked`: the visibility already exists, and the reason is what an operator can filter and act on.

That coverage matters more here than elsewhere, because for this population the UI may be the **only** channel. Measured in 37n-6: when the unavailable owner slot has no `MailTeamMember`, `remind_held_leases` returns `1` and sends **zero** messages, because `notify_owner` returns silently on an unresolvable member (`:1052-1053`). A deleted or handed-off owner is exactly the case most likely to have no resolvable member — so "the owner was reminded" cannot be read off that return value, and the escalation row is what remains. §4.6 is load-bearing for §4.2b.1, not decorative.

### 4.6a Continuation context: the handoff target has no way to learn what it now owns

Blocker 3 of the ninth review asks for "a server-derived continuation-context mechanism," tested "through the real agent interface rather than by injecting fixture knowledge." Confirmed, and the gap is worse than a missing read — the handoff **splits the authority to act on a work item across two processes, leaving neither able to finish it.** That is a liveness defect in shipped code, and it sets this section's requirements.

**What the target can read today: nothing it needs.** Driven through the real `deck_list_work_items` against the real `_work_item_response` payload for a genuinely handed-off item:

```
HTTP layer exposes 27 fields, including:
    owner_slot_id          = 2          <- the handoff landed
    routing_method         = 'reassigned'
    approval_round_count   = 2
    workspace_path         = '/tmp/r'
    issue_url              = 'https://gh/42'
    handoff_state          = 'accepted'

the target calls deck_list_work_items -> keys it receives:
    ['dispatch_status', 'escalation_reason', 'issue_number', 'status_note',
     'work_item_id']
absent: dispatch_head_ref, approval_round_count, workspace_path, issue_url,
        owner_slot_id, dispatch_nonce, lease_token
```

So the state exists on the server and is already serialized over HTTP; §4.6's five-key shim re-projection (`agent_mail_server.py:664-676`) is what strips it. **The continuation-context gap is not missing server state — it is a missing agent-facing read of state the server already has.** That distinction sizes the work: a new projection and a new tool, not a new source of truth.

**The split-authority defect.** The release path applies two checks in sequence (`agent_teams.py:334-365`): `report.reporting_slot_id != item.owner_slot_id` → `409`, then the lease token → `400`/`409` via `release_by_token`. After a real handoff A→B, driven end to end through `POST /dispatch-status`:

```
item owner handed off slot 1 (Alpha) -> slot 2 (Bravo); live token '90d43ee5...'
Alpha  (has the token, no longer owner) -> 409 'only the owner slot may release its workspace'
Bravo  (is the owner, no token)         -> 400 'lease_token required'
Bravo  (is the owner, guessed token)    -> 409 'lease_token does not match the current lease'
workspace afterwards: leased_item_id=1  token_present=True    <- still held
```

Identity moved to B; capability stayed in A's brief. The route requires both, so **no agent can release the workspace** — it is held until an operator force-releases or the backstop reclaims it. And the token is delivered exactly once, at launch: `_dispatch_brief` interpolates `workspace.lease_token` in plaintext four times (`:447-455`), and no shim tool returns it (grep-verified across all 18 tools). A target that never received a brief has no path to it.

**This settles the lease-token rotation question the review left open, in the negative.** The proposal was: rotate on handoff, or prove the retained token is useless against every consumer. Measured, the retained token is *already* useless to the ex-owner, and not because of anything about the token:

**Every lease-token consumer across PR0–PR2, normatively — the enumeration revision 10 got wrong by scoping it to shipped code.** Revision 10 built this table from `grep -rn 'lease_token' app/`, concluded "both agent-facing consumers are behind an owner check," and wrote that into success criterion 30. The tenth review's blocker 3 is confirmed, and the reason it was missed is worth more than the miss: **a spec's own later PR is not in `app/` yet.** `git-credential` / `git_credential` appears **nowhere** in `app/` — measured — so PR2's helper was not a consumer the grep overlooked, it is a consumer *this spec adds* which falsifies a claim *this spec makes* one PR earlier. An enumeration of consumers must range over the design, not over the tree.

| Consumer | PR | Ex-owner holding the live token | Why |
|---|---|---|---|
| `release_by_token` (`:364`) | shipped, **rewritten in PR1** | `409 lease_changed`, the live lease intact | the *write* carries the owner predicate (§4.6a.1). The route's `:334` owner check does not: measured, it is true when it runs and false when the write lands |
| `touch_owner_contact` (`:376`) | shipped, **rewritten as a conditional stamp in PR1** | zero rows, a silent no-op | the *stamp* carries owner **and** token predicates (§4.6a.1 requirement 8). Revision 14 said "re-read the owner inside the write's transaction" and that is not a control: measured on Deck's WAL engine, a fresh read followed by an unconditional stamp still lands on the new owner's lease |
| operator force-release (`:693`) | shipped | not an agent path | compares against the current token deliberately |
| continuation claim (§4.6a) | **PR1** | `403` — not the owner | returns the token; owner-gated on the derived slot, and strict in grace mode |
| `POST /agent-teams/git-credential` (§5.5.6) | **PR2** | **`200` as revision 10 specified it** — mints a fresh installation credential | authorized on `lease_token` + repo path only; **no current-owner check** |

The last row is the finding. Under revision 10, an ex-owner who retained the token from its brief could still obtain a working GitHub credential for the repository after the handoff, indefinitely, because the helper never asks who is calling. §5.5.6 is amended to close it, and **the "do not rotate" decision survives only because of that amendment** — the sentence "the token grants nothing" was false the moment PR2 landed, and rotation-versus-not was never the real axis. The real axis is whether each consumer checks *current* ownership.

**And the first two rows were point-in-time observations, which is the thirteenth review's blocker and the reason PR1 owns them.** Revision 13 wrote both as achieved facts — "`403` before the token is read," "never called" — on the strength of reading the two checks at `agent_teams.py:334` and `:371-373`. Both checks are real; neither is in the same operation as the write it is supposed to authorize, and this table is where that difference decides the design, because the whole no-rotation decision is the claim that *the retained token grants an ex-owner nothing*. Measured through the real route, with the handoff interleaved at an await the branch actually has:

```
release: A admitted as owner, hands off to B inside release_blocker's await
  owner after  : slot 2 (B)
  A's response : 200
  row after    : leased_item_id=None token=None      <- B's live lease, destroyed by A

touch: A admitted as owner, hands off to B inside escalate's await
  live owner   : slot 2 (B); reporter was slot 1 (A)
  touch called : True   token='TOK-KEPT'
  contact       : stamped
```

So an ex-owner both releases B's lease and refreshes the lease's liveness evidence, in the design that retains the token by decision. **A guarantee is measured at the boundary it is stated about, not at the helper's internals** — and revision 13's §7 deferral got that boundary wrong in its own favour, which is corrected below (§4.6a.1) and removed from §7.

Two bounds, because the two rows are not equally severe and the spec should not flatten them. The release case destroys a live lease and is the blocker. The `touch_owner_contact` case only *delays* a backstop reclaim — it stamps freshness on a lease whose owner has legitimately changed, and `_RECLAIMABLE_STATUSES` has no reader at all until the item is terminal (§4.8 test 37r-4a) — so it is a correctness defect in the table's claim rather than a lost lease. Both are fixed in PR1; only the first justifies a conditional write.

**Decision, restated with its dependencies: do not rotate the lease token on handoff — deliver it, and owner-gate every consumer *in the operation that acts*.** Rotation was rejected because it would invalidate the only copy of a capability with no delivery channel to the new owner, making B's position strictly worse; that reasoning is unchanged. What changes is that "no rotation" is now conditional on §5.5.6's owner check existing, and §5.8's test 46r is what makes the condition checkable rather than asserted. Measured confirmation that delivery is sufficient for release: B, holding the actual live token, releases successfully and the lease clears (`leased_item_id=None`, `token_present=False`) — the token is a bearer capability on the *acquisition*, not bound to the slot that received it. That property is exactly why the acquisition alone cannot be the helper's authorization.

**Delivering a live token by server-authored mail is an existing pattern, not a new one.** `remind_held_leases` (`:826-850`) already does exactly this: it resolves the recipient through `notify_owner` → `_owner_member` from `item.owner_slot_id`, and interpolates `workspace.lease_token` into the body (`:878`). Measured after a real handoff:

```
item 'merged', still leased, owner is now Bravo
remind_held_leases -> 1 reminder, 1 message
    recipient member = 2   (Bravo, resolved from the CURRENT owner)
    live token in the body? True
```

So this design is not introducing a new class of capability disclosure. It is doing at handoff time what shipped code already does at release time. **But that channel cannot be reused**, and the reason is a status gate:

```
_RELEASABLE_STATUSES = ['merged', 'completed', 'escalated', 'failed']
item is 'dispatched' (the entire working life of the target):
    remind_held_leases -> 0 reminders, 0 messages
```

The one existing delivery fires only once the work is already terminal. The target needs its context at the *start*. That is why a new mechanism is required rather than a widened selector — widening `_RELEASABLE_STATUSES` to include `dispatched` would make the release reminder fire at agents who have not finished, which is the opposite of its purpose.

**The mechanism.** One endpoint and one tool:

`POST /api/v1/agent-teams/github-work-items/{id}/claim-continuation` returns the server's own view of what the caller owns: `work_item_id`, `issue_number`, `issue_title`, `issue_url`, `issue_type`, `repo_owner`/`repo_name`, `dispatch_status`, `approval_round_count`, `dispatch_nonce`, `dispatch_head_ref`, `workspace_path`, `lease_token`, `leader_member_id`, and `status_note`. Every field is read from the row — nothing is recomputed, so the head the target is told is by construction the head `pr_ready` will check it against (§4.1's rung).

**Why `POST` and not the `GET` revision 10 specified.** Three independent reasons, and the third is the one that makes it structural rather than stylistic:

- The response body carries a live bearer secret. A `GET` invites caching, `Referer` leakage, and history retention, and revision 10 put `reporting_slot_id` in the **query string** — so the identity claim landed in access logs too. The response carries `Cache-Control: no-store` and the token appears in no URL, no log line, no exception message, and no `status_note` (§4.8 test 37r-7 asserts the negative).
- It is not nullipotent. See below: it **re-stamps** the caller's pane identity onto the lease — a refresh of what `accept_handoff` already wrote (§4.6b), not the write that makes the row truthful.
- **It refreshes the liveness evidence, and revision 11's version of this bullet was the same mistake one layer up.** Revision 11 wrote that `accept_handoff` "cannot stamp the target's pane pid because it has no way to know it — the accepting call may arrive from anywhere," and made the claim the *first* moment ownership became truthful. That sentence is true of `master` and false of PR1: after PR0, `handoff_accepted` arrives through `/dispatch-status` behind `require_session_slot`, and §3.5a's target-only check has already derived and verified the accepting pane before the service is called. Writing it in this section is the sharpest available instance of the rule this section names two paragraphs down — **a measurement of today's code is evidence about `master`, not about the PR you are writing** — because the section states the rule and then breaks it. §4.6b now puts the transfer in `accept_handoff`, where the identity is already known, and this endpoint's write becomes an idempotent **refresh** of the same pane plus the contact stamp: still not nullipotent, so still a `POST`, but no longer the only thing standing between a handoff and a truthful owner.

`deck_get_work_item_context(work_item_id)` in the shim. It takes no slot argument at all — the derived identity replaces the `reporting_slot_id` fill that `deck_report_dispatch_status` does at (`:626`). The tool name keeps `get_` for the agent's sake: from the agent's side it is "tell me what I am working on," and naming it `claim_` would invite an agent to believe it must not call it twice. It is idempotent for the caller that owns the item — repeated calls re-stamp the same pane and return the same context.

**Authorization: PR0's derived identity, not a claimed slot id.** Revision 10 wrote this paragraph as an honesty statement — "there is no capability token on either agent-facing router, so the check is `reporting_slot_id == item.owner_slot_id` and that is the best available." Every measurement in it was correct and the conclusion was wrong, because it measured **pre-PR0 `master`** and then wrote the result into a PR that lands *after* PR0. The tenth review's blocker 1 is confirmed: §3.5 already gives `POST /dispatch-status` a token-derived slot (`:599-607`), §3.5a runs authorization *after* the token resolves the caller (`:634-647`), test 7 requires a conflicting body claim to fail `403` (`:744`), and the architecture says PR0 closes exactly this gap (`:325`). A PR1 endpoint cannot simultaneously be later in the sequence and poorer in authority than the thing before it.

This is a general failure mode worth naming, because it produced two blockers in this review and it will recur in any staged design: **a measurement of today's code is evidence about `master`, not about the PR you are writing.** Every "measured: there is no X" in a later PR's chapter has to be re-asked as "does an earlier PR in this same spec add X?" — see the [[invariant-evidence-freshness]] rule one level up: not the freshness of the data a rule reads, but the freshness of the *codebase* a design reasons about.

**The shared dependency.** PR0 defines one FastAPI dependency, `require_session_slot`, and both routers use it. It is not new work — it is §3.4's resolver given a name and a second consumer:

| Step | Source | Failure |
|---|---|---|
| read `X-Deck-Session-Token` | header | `401 capability_token_required` (or grace-mode branch below) |
| resolve → `MailAgentSession` | sha256 + `hmac.compare_digest` (§3.4) | `401 capability_token_invalid` |
| confirm the session's pane binding | `agent_pane_bindings`, kernel peer pid (§3.3) | `403 bind_unverifiable` / retryable `409 bind_pending` (§3.3a) |
| project → `(session, member, slot_id)` | the bound row | — |

`reporting_slot_id` **stops being an authority input everywhere it is one today.** The request schema keeps the field, because the shipped shim sends it and PR1 must not break a released shim (the same compatibility reasoning as §3.5's `403`-on-disagreement rule): a value that *agrees* with the derived slot is accepted and grants nothing extra, a value that *disagrees* is `403 slot_claim_mismatch`, and a value that is absent is filled from the derivation. §3.5a's matrix is unchanged in content and becomes enforceable rather than nominal.

**Grace mode does not grant a bearer secret, and — corrected — it does not grant a write either.** §3.4a lets PR0 deploy with `mail_capability_tokens_required = False` so nothing breaks on rollout, and a tokenless caller then falls back to today's behaviour.

Revision 11 made only `claim-continuation` strict in grace mode, on the ground that the fallback is acceptable "for reports, which only *reduce* Deck's confidence." **That is false for the matrix as a whole, and the eleventh review is right to call it a blocker.** Read against the shipped route, four of the branches are not confidence-reducing reports:

| branch | what a tokenless caller does |
|---|---|
| `handoff_initiated` | sets `handoff_target_slot_id` to any slot — `initiate_handoff` (`:689-695`) has **no** authorization of any kind on `master`: four assignments and a commit |
| `handoff_accepted` | takes ownership; the only check is `handoff_target_slot_id == accepting_slot_id` (`:700`), and the previous row let the caller choose that value |
| `pr_opened` | admits the item to verification, which is the auto-merge pipeline's input |
| `workspace_released` | releases the checkout, gated only on caller-supplied `reporting_slot_id == item.owner_slot_id` (`agent_teams.py:333`) |

So during grace mode a tokenless same-repo caller can claim to be owner A, initiate a handoff to B, accept as B, and then present B's legitimately-upgraded session to the strict continuation endpoint and receive the lease token. **A strict read does not repair a forgeable write** — and this contradicts §2.1's new claim that PR1's matrix is enforceable because `require_session_slot` shipped in PR0. The dependency does exist; grace mode routes around it.

**The rule, and it is deliberately blunt.** Once PR1 is installed, **every** `/dispatch-status` call returns `409 tokens_not_enforced` while `mail_capability_tokens_required` is false, naming the setting. Not a per-status allowlist: an allowlist is a claim that each permitted branch is monotonic and non-destructive, and the table above shows that claim is hard to make and easy to get wrong — `triaging` looks harmless until one notices it writes `status_note`, the field §4.2b.1's operator instructions are delivered in. One refusal for the whole route is a rule an implementer cannot misread, and the cost is a deployment ordering rather than a lost capability.

**Deployment ordering, therefore, is part of PR1 and not a runbook footnote:** set the operator token in `backend/.env` (§3.6a) → deploy PR0 → restart panes so every agent registers and mints a session token → set `mail_capability_tokens_required = True` → deploy PR1. Autonomy stays off throughout (§6), so nothing dispatches into the window. The operator token comes **first** because it is read at import time (`config.py:57`): a backend that starts without it serves `503` on both operator routes until it is restarted, and the natural response to that — export the variable and restart in place — is the one thing §3.6a forbids.

PR0's *mail* half remains backward-compatible, which is that half's entire design goal; its operator-route half changes behaviour on deploy (§2.1). **PR1 is the point at which identity becomes a hard runtime prerequisite**, and saying so is more honest than shipping a matrix that silently degrades to today's behaviour whenever a flag is false.

The continuation claim keeps its own separate strictness for its own reason — its response body *is* a bearer secret, so it must refuse even in a world where reports were permitted. That reasoning survives; it was just never sufficient on its own.

**What the pre-PR0 check was worth, and why it is kept as the second half of the rule.** The derived slot answers *who is calling*. `owner_slot_id` still answers *may they*. Both run. The measurement below is retained because it explains why the derived half is load-bearing rather than belt-and-braces — a self-asserted slot id is worth nothing at slot granularity:

```
slots 1 (Alpha) and 2 (Bravo): same preset, same provider, same repo_id
Bravo's process registers with team_slot_id=1:
    member.team_slot_id  = 1   display_name='Alpha'
    session.team_slot_id = 1
same claim with cwd=/tmp (a different repo):
    member.team_slot_id  = None  participant_kind='repo'
```

`_slot_matches_registration` (`agent_mail_service.py:295-305`) compares `provider` and `derive_repo_identity(cwd)["repo_id"]` against the slot. Both are identical for every slot on one repo, so it cannot tell Alpha from Bravo; the caller's own `CLAUDE_DECK_TEAM_SLOT_ID` decides which slot it is. The negative control shows the check is not vacuous — it binds a registration to a **repo**. So the honest statement is narrow, and it goes in the spec rather than in a commit message: **`reporting_slot_id` is server-stored, not server-verified. It identifies the repo and provider a caller runs in, and nothing finer. Within one repo's team, any slot can claim any other slot's identity.** This is the same property [[check-name-vs-discriminating-power]] records for `_slot_matches_registration`, now measured at slot granularity — which is the granularity every owner check in the dispatch flow is written at.

That is the measurement revision 10 stopped at, and it is why `reporting_slot_id` cannot carry authority on its own. Under PR0 the picture changes, and the consequences change with it. Revision 10 listed three "accepted consequences"; two of them were consequences of the *absence* it wrongly assumed, and only the third survives:

1. **Withdrawn, and it leaves an obligation behind.** Revision 10 accepted disclosing a lease token to a caller whose slot identity is self-asserted, on the ground that `GET /github-scopes/{id}/workspaces` (`:569`) already leaks the token with no auth at all. The premise is true — `GithubWorkspaceResponse.lease_token` (`schemas.py:2245`), filled unconditionally by `_workspace_response` (`agent_teams.py:185`) — and the inference was wrong twice over: an existing hole is not a licence to add a second one, and PR0 removes the need for either. Post-PR0 the caller's slot is kernel-derived, so the token goes only to the pane bound to the owning slot.

  So the `:569` leak becomes an obligation rather than a precedent — **but not the one-line deletion it looks like, and this is measured rather than assumed.** No frontend code reads the field (grep across `frontend/src/`: zero hits for `lease_token`/`leaseToken`; there is no workspaces UI yet). The blocker is on the backend: operator force-release requires `expected_lease_token` in its request body (`schemas.py:2256`, compared at `agent_teams.py:693`), and this listing route is the **only** way an operator can learn that value. Deleting the field would remove the sole exit path from a stuck lease — the exit path §4.2b.1 leans on twice — to close a hole PR0 has already made unnecessary to close this way.

  **The choice, made here rather than delegated.** Revision 11 named two shapes and wrote "whichever is chosen," which is an unresolved design decision wearing the clothes of implementation freedom — an implementer choosing under time pressure would pick the smaller diff, and the smaller diff is the wrong one. **Force-release stops requiring the lease token.** `GithubWorkspaceForceReleaseRequest` (`schemas.py:2255-2258`) replaces `expected_lease_token: str` with `force: Literal[True]` and `expected_leased_at: datetime`, compared against `workspace.leased_at` — in the conditional write itself, not before it, for the measured reason four paragraphs down; a mismatch is `409 lease_changed` naming both timestamps, which are not secrets. `lease_token` then leaves `GithubWorkspaceResponse` (`schemas.py:2245`) outright, and `_workspace_response` (`agent_teams.py:185`) stops filling it.

  Three reasons this beats an operator-only token projection:
  - **It removes a secret rather than relocating one.** A projection behind `require_operator` still puts a live bearer token in an HTTP response and a terminal scrollback, for a caller who needs optimistic concurrency, not authority. `leased_at` gives the same staleness check with nothing worth stealing.
  - **It removes the oracle at the root.** §3.6a's disclosure fix stops the mismatch message printing the token; dropping the field means the route never holds the value to print. The two changes are independent and both ship — one deletes the leak, the other deletes the reason the leak was tempting.
  - **It stops the operator replaying an agent's credential.** `lease_token` is what authorizes the *agent's* `workspace_released` report (`agent_teams.py:359-366`). Requiring the human to read and replay it conflates two roles: the operator's authority should come from `require_operator`, not from possessing the agent's bearer secret. §4.2b.2's liveness check is the safety here, and it is stronger than a token comparison ever was.

  PR0 owns this, not PR1: force-release and the projection both exist today, `require_operator` ships in PR0 (§3.6a), and PR1's §4.2b.2 is a *consumer* of the dependency rather than its introducer. Revision 11 assigned it to PR1 on the reasoning that "PR1 is the PR whose authorization is decorative without it" — true of §4.2b.2, and not of a leak and an oracle that are live on `master` right now.

  **And the replacement contract needs one more thing, because a comparison is not a concurrency control.** Revision 12 called `expected_leased_at` an optimistic-concurrency guard and then specified only a value comparison — which is the same shape of error as the token it replaces, one layer over: the *check* was made safe and the *write* was left alone. The current route compares the lease at the top, then awaits `pending_work`, which runs **two** `git` subprocesses (`github_workspace_service.py:234-241`), then calls `release(db, released_item_id)`. Everything the check established is stale by the time the write happens. Measured end to end:

```
same-item ABA
  request checked   : leased_at=16:37:39.341 token='ACQ-1-aaa'
  replacement was   : leased_at=18:37:39.349 token='ACQ-2-bbb'
  row after release : leased_item_id=None token=None
```

  A `expected_leased_at` matched at request start authorizes the destruction of an acquisition that did not exist when it was matched. **And the race is wider than the twelfth review states**, which is the part worth measuring rather than reading: `release` selects `WHERE leased_item_id == item_id` with **no workspace id and no scope id** (`github_workspace_service.py:148-152`), so the write is not scoped to the row the operator inspected at all:

```
cross-workspace
  operator aimed at workspace X, which held 'ON-X-aaa'
  during the await, the item's lease moves to workspace Y
  after release(item):  X free (already), Y also cleared -- 'ON-Y-bbb' gone
```

  The operator inspected X, confirmed X, and destroyed a lease on Y. So the guard cannot be "the same acquisition of this item" as the review frames it; **the predicate must name the workspace row**, or the confirmation still authorizes a write the operator never saw.

  The contract, therefore:

  1. **Confirmation is non-optional in the schema:** `force: Literal[True]`. Omitted or `false` ⇒ `422` from validation, with no route code to forget. Revision 12 left `force: bool` undefined for `false`, and an implementation that never reads the field passes every test in §3.7 — the field would be documentation, not a control.
  2. **The lease is cleared by one conditional mutation whose predicate is the acquisition that was inspected**, issued after the awaited inspection, not before it: `UPDATE ... WHERE id = <workspace_id> AND scope_id = <scope_id> AND leased_item_id = <captured> AND leased_at = <expected_leased_at> AND lease_token = <captured_token>`. The stored `lease_token` is **mandatory** in the predicate — captured server-side at the same moment as `leased_item_id`, and **never** returned to the operator. Revision 13 wrote "may be added as a further discriminator," and that optionality is wrong, because `leased_at` is a timestamp and not an acquisition identifier. Measured on this platform: `datetime.utcnow()` returned equal values for two back-to-back calls **63 098 times in 200 000 pairs**; the column has neither a UNIQUE constraint nor any monotonicity guarantee (`models/database.py:295-320`); and a replacement acquisition carrying an identical `leased_at` with a fresh token is representable and stores cleanly. Microseconds *do* survive the SQLite round trip (`'2026-08-08 12:00:00.123456'` read back verbatim), so the comparison is not useless — it is simply not sufficient, and the value that *is* unique per acquisition is already in hand at zero cost.
  3. **Exactly one affected row, or nothing happened.** Zero rows ⇒ `409 lease_changed`, the current lease untouched, and **no success log** — the existing `logger.warning` fires *before* the release today (`agent_teams.py:707-716`), so a naive port would record a force-release that did not occur. Exactly one is a guarantee rather than a hope, and the guarantee comes from `id` being the **PRIMARY KEY**: measured, `WHERE id = <pk>` affects `1` row and the same statement keyed on `scope_id` affects `2`. Revision 13 credited this to `leased_item_id` being `UNIQUE` (`database.py:319`, `uix_workspace_leased_item`), which proves a *different* fact — that one item cannot be leased by two workspaces at once — and would not bound the count for a predicate that omitted the workspace id. Both facts are load-bearing here, for different halves of this requirement: the unique constraint is what makes the many-rows case unreachable (see the closing paragraph of this section), and the primary key is what makes the count exactly one.
  3a. **The write clears the whole release state, not just the lease pointer.** `release()` sets seven columns at one `now` (`github_workspace_service.py:155-165`): `leased_item_id`, `released_at`, `lease_token`, `leased_owner_pid`, `leased_owner_proc_start`, `lease_last_owner_contact_at`, `lease_release_reminded_at`, plus `updated_at`. A conditional `UPDATE` that replaces the helper must set **all** of them, and the enumeration belongs here rather than being left to "do what `release` does," because the columns a reader forgets are the liveness ones — and a row left with a stale `leased_owner_pid` and a NULL `leased_item_id` is exactly the shape §4.6b spends a section on. `released_at` and `updated_at` take the same `now` as the clear, so the audit trail says one thing.
  4. **`pending_work` stays fail-open and becomes advisory about the inspected acquisition only.** It already refuses to gate (`:226-229`), and that is right; what changes is that its output may not travel with a write that lands on a different acquisition.

  One measurement bounds all of this, and it refutes a hypothesis of my own rather than the review's. I predicted that `release`'s `scalar_one_or_none` made a two-row state unreleasable forever — every force-release raising `MultipleResultsFound` with no way out. That state is unreachable: the `UNIQUE` constraint refuses the second acquisition at the database (`IntegrityError`, measured). The prediction was a claim about a predicate made without reading the constraint three lines from it, which is the same error this spec has now recorded twice. It matters because being wrong here is what makes the fix *small*: requirement 3's "exactly one row" needs no defensive handling for the many-rows case, because there is no many-rows case.

  **The sweep for the same shape found a second instance, and revision 14 fixes it in PR1 rather than deferring it.** `release()` has eight callers; seven pass an item id they own outright and have no check to go stale. The eighth is `release_by_token` (`github_workspace_service.py:178-194`), which has the route's exact structure — `get_leased_workspace` (await), compare `lease_token`, `release(db, item_id)` (await) — and a docstring that states the guarantee the structure cannot give: *"Requiring the acquisition token prevents that report from releasing a replacement owner's live lease"* (`:181-185`). Measured by interleaving at the await the code actually has:

```
release_by_token, interleaved at its own await
  agent presented  : ACQ-1-aaa (the token it was given)
  live lease was   : ACQ-2-bbb (a replacement acquisition)
  row after        : leased_item_id=None token=None
```

  The replacement dies. Revision 13 recorded this and deferred it to §7 on a severity argument — *"the window is a DB round trip rather than two `git` subprocesses"* — and **that argument measured the wrong boundary.** It is true of `release_by_token`'s own internals and false of the route whose guarantee criterion 30 states. The route's window runs from the owner check at `agent_teams.py:334` to the write at `:363`, and `release_blocker` sits inside it (`:352`), awaiting `self._runner` **twice** for a worktree (`github_workspace_service.py:203`, `:211`). Measured on the real source: `owner check at offset 150, release_blocker at 891, release_by_token at 1367` in the branch, and `release_blocker awaits self._runner 2x`. So the agent path's window is *the same two `git` subprocesses* as force-release's `pending_work`, plus two DB round trips. The severity argument that justified the deferral does not survive, and the deferral goes with it. The full contract is §4.6a.1.

  Two things the deferral got right and revision 14 keeps: the fix is the same *shape* as requirement 2, and it does not belong in PR0. It belongs in **PR1**, because PR1 is the PR that (a) already rewrites this branch's authorization onto the derived slot (§3.5a) and (b) makes the no-rotation claim that this write is the proof of. **PR1 cannot assert that a retained token grants an ex-owner nothing until the owner predicate is in the write.**

#### 4.6a.1 The agent's own release must bind acquisition, row, and current owner in one write

Everything in requirements 1–4 above transfers, with one predicate added and one refusal semantic changed. This is the PR1 contract.

  1. **The caller's slot is the derived one.** `require_session_slot` has already resolved it (§3.5a); the helper takes it as an argument rather than re-reading `report.reporting_slot_id`, which is corroboration only. A new service method — `release_by_owner(db, item_id, *, lease_token, workspace_id, owner_slot_id)` — replaces `release_by_token`'s two-step body. `workspace_id` is **required and non-optional**: the helper is only called on the path that captured a leased workspace, and requirement 5's path A returns before reaching it. Making the parameter optional would reintroduce exactly the confusion revision 14 wrote into its own result table — a write "keyed on the row" that has no row. PR0 may factor out a shared conditional-update helper if the force-release work makes one natural; PR1 does not depend on it existing. **If one is factored out, its token comparison is ordinary SQL equality with no null-safe mode** — requirement 8 states why, and measured, a null-safe helper makes a tokenless release clear a NULL-token lease (`1` row where ordinary equality matches `0`).
  2. **One conditional `UPDATE github_workspaces`**, issued after `release_blocker` returns, whose predicate is the whole authorization:

     ```
     WHERE id            = <captured workspace_id>       -- the row inspected (PK: bounds to 1)
       AND scope_id      = <the item's scope>
       AND leased_item_id = <item.id>                     -- still this item's acquisition
       AND lease_token   = <report.lease_token>           -- still this acquisition
       AND EXISTS (SELECT 1 FROM github_work_items wi
                    WHERE wi.id = <item.id>
                      AND wi.owner_slot_id = <derived_slot_id>   -- still the owner
                      AND wi.dispatch_status IN <_RELEASABLE_STATUSES>)
     ```

     with the seven-column clear of requirement 3a in the same statement.
  3. **The owner predicate is load-bearing *because* the token is retained, and this is the measurement that proves it.** A reader will reasonably ask why the token is not enough, given that requirement 2 above treats it as the discriminator force-release was missing. The answer is the no-rotation decision: after a handoff the token is deliberately still the live one, so a token-keyed predicate is *satisfied* by the ex-owner. Measured side by side against the same post-handoff row:

     ```
     token-keyed  (id + scope + leased_item_id + lease_token)  -> 1 row(s)
     + owner      (EXISTS ... owner_slot_id = derived)          -> 0 row(s)
     ```

     Token atomicity stops a replacement **acquisition**; only the owner predicate stops an admitted ex-**owner**. This is the inverse of force-release, where the operator is not an owner at all and the token is the only acquisition identity available — which is why the two writes have different predicates rather than one shared one.
  4. **The status predicate is a restatement, not a race guard — and the spec says so, because a control nobody can trip reads as coverage.** `_RELEASABLE_STATUSES` appears in the predicate above so that the write is self-describing and cannot be lifted into a context that skipped the `:341` check. It is *not* claimed to guard a transition inside the window, and the obvious candidate was measured and cannot fire: `reset_for_retry` **defers** while a lease is held (`github_dispatch_service.py:48-63`) — measured, the status stays `escalated` with `retry_requested_at` set, and only reaches `pending` once the lease is gone. The transition that *can* fire while leased moves an item **into** the set, not out of it: the `abandon` route escalates a `dispatched` item (`agent_teams.py:792-831`). That direction is harmless here — it can only turn a `409` into a legal release, and the release is by the current owner with the current token — so the predicate is retained for legibility and the honest claim about it is this paragraph, not a coverage claim.
  5. **Three outcomes, not two — and the idempotent one is a branch above the write, not a row of its result table.** Revision 14 departed from the thirteenth review's "zero affected rows ⇒ `409`" for a reason that still holds, and then stated the departure in a shape that cannot execute. The reason first: measured through the real route, a **duplicate** `workspace_released` report from the true owner with the true token returns `200 → 200` today, because `release_by_token` returns silently when the workspace is already unleased (`:188-189`). A retrying agent — one whose first report timed out after the server committed — would read a `409` with no correct next action, on the one path whose entire purpose is to let go of a resource. So a flat `409` is still wrong.

     **The shape was wrong, and this is the fourteenth review's first blocker.** Revision 14 wrote the idempotent case as a row in a table headed *"zero rows because…"*, the first row being "no workspace currently leases this item." That state cannot be a zero-row result of this write, because the write is keyed on a captured `workspace_id` (requirement 2) and there is no `workspace_id` to capture: measured, after the first release the route's own `get_leased_workspace(item.id)` returns **`None`**, so the statement is never issued at all. A result table can only describe outcomes of a statement that ran. The three paths are therefore sequenced explicitly:

     | Path | Condition | Response |
     |---|---|---|
     | **A. No workspace at the initial lookup** | `get_leased_workspace` returns `None`, so no conditional write is attempted — there is no row id to key one on | fresh-read the stored `owner_slot_id` (see below). Still the derived caller ⇒ `200`; otherwise the matrix's `403 not_item_owner` |
     | **B. Workspace captured, write affects exactly one row** | the whole predicate held | `200`, released |
     | **C. Workspace captured, write affects zero rows** | the request was admitted and went stale during execution | fresh-read the owner **and** whether any workspace now leases the item. No lease and still the owner ⇒ `200`; anything else ⇒ `409 lease_changed`, nothing written, no success log |

     **Path A has two outcomes, not one, and the fifteenth review's blocker is that revision 15 gave the second one no test.** The table's `403` is not a formality: it is the case the fresh read exists for, and it is reachable. Measured through the real route — A admitted at `:334` as owner, the handoff committing while the request is inside the lookup — the two implementations of "fresh-read" diverge on the response an agent receives:

     ```
     Path A, stale-owner interleaving:
       diagnosis = fresh scalar SELECT   -> reads owner 2 (B) -> 403
       diagnosis = db.get / cached item  -> reads owner 1 (A) -> 200
     ```

     A `200` there tells an agent that no longer owns the item that its release succeeded. So path A's outcomes are enumerated separately, and §4.8's 37r-9 gains the case that fails the second line: **A1** the same-owner duplicate ⇒ `200`, **A2** the admitted-then-staled request that captured *no* workspace ⇒ `403 not_item_owner`.

     **Where such a test can suspend, because the recipe used everywhere else in this section does not exist here.** 37r-8 and path C's case both suspend inside `release_blocker`. On path A `workspace` is `None`, so that call is never awaited at all — measured on the real branch, `release_blocker` sits inside `if workspace is not None` and only two awaits separate the owner check from the write:

     ```
     owner check :334 -> offset 12      get_leased_workspace -> 739  (unconditional)
     if workspace is not None -> 812    release_blocker      -> 860  (inside the guard)
                                        release_by_token     -> 1336
     ```

     `get_leased_workspace` is therefore path A's only interleaving point in the real route, and the spec names it so the test is writable rather than merely required.

     **And the `403` path A returns is the same code the preliminary check returns, which makes the branch-arrival assertion structural rather than decorative.** After §3.5a the `:334` refusal is also `403 not_item_owner`. So a path A test that seeds the ownership disagreement *before* the request proves nothing: measured, the request is refused at `:334` having never reached the lookup — a fresh session's `db.get` at `:291` emits a real query and binds the *stored* owner, so there is no cached-versus-stored disagreement to exploit until the request is already in flight. That test would be green against a cached diagnosis, against no diagnosis at all, and against `master` — the identical "assertion satisfied by two different mechanisms" defect revision 14's 37r-9 had, one revision later and on the branch introduced to fix it. The disagreement must be created *during* the request.

     **Path C is the admitted-stale-request path, and it is the only ordering that reaches the write's zero-row branch at all.** A *fresh* report from a non-owner never gets there: measured, it is refused by the preliminary `:334` check having reached neither `release_blocker` nor the write. The reachable ordering is the one the review names — A passes `:334`, captures the workspace, and B takes ownership *and releases* while A is suspended in `release_blocker`; measured, A's conditional write then affects **0** rows with both facts true at once (no lease, and the caller is not the owner). That is precisely why C needs a diagnosis rather than a constant.

     **Paths A2 and C reach the identical stored state and return different codes, so the asymmetry needs a reason.** Measured, both end with no lease on the item and ownership moved to B — A2 because there was nothing to release, C because B released it. The discriminator is not the row, it is the request's own history: C captured an acquisition and then failed to release it; A2 captured nothing. Two honest statements, and the second bounds the first:

     - A2 is `403` because the authorization answer does not depend on arrival time. A non-owner is refused `403` whether it arrives after the handoff or is staled just after the check, so the code stays the matrix's. C is `409` because it reports something an authorization code cannot: an acquisition this request held was lost underneath it.
     - What the spec does **not** claim is that the two codes give the agent different next actions *on this state*. Both mean stop: a `409`-driven retry with fresh state converges to the `403` one round later. The distinction is for the operator reading logs and for the matrix's vocabulary staying single-valued — not a behavioural difference being engineered for.

     **Path A's `200` means "no lease of yours exists," not "your earlier release succeeded" — and the spec must not overstate it.** Measured, the route cannot distinguish a retry from a report on an item that was *never* leased: both reach the `None` lookup and both are `200` today, and a token that was never issued is compared against nothing. Nor is there stored evidence to distinguish them, because requirement 3a clears `lease_token` on release. So path A is deliberately silent about *why* there is no lease, and the owner check is its only discriminator.

     **"Fresh-read" is a mechanism, not a location — and this is the review's important correction.** Revision 14 said "one follow-up read inside the same transaction," which grants no freshness whatever: measured, `db.get(GithubWorkItem, item_id)` returns the *identity-mapped object the route bound at `:291`* without emitting a query, reporting the **pre-handoff** owner (`owner 1` where the stored value is `2`, and `again is item` → `True`). Under `expire_on_commit=False` transaction membership invalidates nothing. Both diagnoses above must therefore use a mechanism that goes to the database — a scalar `SELECT`, `populate_existing=True`, or an explicit `refresh` (measured, the raw scalar and `populate_existing` both return the stored `2`). This is the same trap requirement 8 names for the tail, and revision 14 fell into it one paragraph earlier.

     The reads in paths A and C are diagnoses, not authorizations. In C the write has already refused and no ordering of a subsequent read can turn a refusal into an admission. In A no write was attempted, so the read *is* the decision — which is why it must be the fresh one. Requirement 4's fail-open logic is unchanged.
  6. **Every preliminary check stays, and every one of them is a diagnostic.** The route's `:334` owner check, `:339` token-presence check and `:341` status check are kept: they give an agent a specific, actionable refusal (`403 not_item_owner`, `400 lease_token required`, `409` naming the legal statuses) instead of a bare `409 lease_changed`, and they keep `release_blocker`'s two subprocesses off the obviously-unauthorized path. What changes is their status in the argument. **They are error messages; the predicate is the control.** Criterion 30 may cite only the predicate.

     **Keeping them decides which orderings the write ever sees, which is why requirement 5 has three paths rather than two.** The `:334` check reads the `item` bound at `:291`, and measured, nothing re-reads that row in between — the only intervening await on the way to this branch fetches the *scope*. So for a request that arrives **after** a handoff the check is fresh at the moment it runs, and it refuses: measured, a late ex-owner is turned away with neither `release_blocker` nor the write reached. The staleness lives entirely in the window *after* the check. Two consequences the spec must state together, because each is what makes the other's response code correct: a **direct non-owner keeps the matrix's `403`** and never reaches a conditional write, and the zero-row `409` belongs exclusively to a request that was **admitted and then staled**. Revision 14 conflated the two, which is what made test 37r-9 unable to discriminate anything (§4.8).
  7. **The docstring's absolute claim becomes true rather than softened.** Revision 13 deferred this and left a note asking whoever next edited the function to "either make the claim true or soften it." PR1 makes it true, and the docstring is rewritten to name what the write binds — row, acquisition, and current owner — because the previous text is precisely the failure mode this spec keeps finding: a comment asserting a guarantee the code does not provide.
  8. **The tail's `touch_owner_contact` gate becomes one conditional write. There is no acceptable read-then-write form, and revision 14 was wrong to offer one.** The route's `:371-373` comparison reads the `item` object bound at `:291`, and `expire_on_commit=False` means that object is never invalidated by another session's commit. Revision 14 required that comparison to be made against ownership "re-read inside the same transaction as the stamp," **or** the stamp to carry the owner predicate, and called either acceptable. That is the fourteenth review's second blocker, and it is confirmed: a fresh read followed by an unconditional write is still a point-in-time comparison, and *nothing* about sharing a transaction orders it against another connection's commit. Measured on Deck's own engine — file-backed, `journal_mode=WAL`, which `database.py:23-34` sets precisely so readers and writers do not block each other:

     ```
     A fresh-reads owner (raw SQL, its own transaction) -> 1  (A)
     B commits the handoff on another connection        -> owner now 2 (B)
     A, having "verified" ownership, stamps             -> rowcount=1
     lease_last_owner_contact_at                        -> stamped by A
     ```

     So the requirement is a single statement whose predicate is the whole authorization:

     ```
     UPDATE github_workspaces
        SET lease_last_owner_contact_at = <now>, updated_at = <now>
      WHERE leased_item_id = <item.id>                  -- one row by schema, see below
        AND lease_token    = <report.lease_token>       -- still this acquisition
        AND EXISTS (SELECT 1 FROM github_work_items wi
                     WHERE wi.id = <item.id>
                       AND wi.owner_slot_id = <derived_slot_id>)
     ```

     Zero rows stays a **silent no-op**, matching the advisory contract the docstring already states (`github_workspace_service.py:255-259`) — this is liveness evidence, not a state change an agent is waiting on, and requirement 4's fail-open discipline applies unchanged.

     **The token clause is required, not decorative, and it is the mirror of requirement 3.** The review asserts it; measured, with A still the owner throughout and the acquisition replaced `TOK-1 → TOK-2`, the owner-only predicate matches **1** row and owner-plus-captured-token matches **0**. Requirement 3 showed the token alone cannot stop an ex-owner; this shows the owner alone cannot stop a stamp against an acquisition the caller never held. Neither clause covers for the other, in either write.

     **Why there is no workspace-row clause here, unlike requirement 2 — stated because the omission looks like the force-release defect and is not.** `release()`'s missing workspace predicate let a request that inspected workspace X clear a lease held by workspace **Y** (§4.6a), so the lesson recorded there is that a predicate must name the row rather than the logical entity. That lesson does not transfer, and the reason is schema rather than care: `UNIQUE(leased_item_id)` (`database.py:319`) makes `WHERE leased_item_id = <item.id>` a one-row predicate. Measured, a second workspace claiming the same item raises `IntegrityError`, and the statement above affects exactly one row and touches exactly the intended workspace id. An implementer who has the captured workspace id to hand *may* add `id = <captured>` and it is mildly preferable — self-describing, and it survives the constraint being dropped — but the spec does not credit it with preventing a cross-workspace write, because the constraint already does. A rationale that misnames its own mechanism is the defect this spec keeps finding.

     **Replacing the Python guard with a SQL predicate changes behaviour on one row shape, and the change is deliberate.** Not raised by any review; found while re-verifying criterion 29's evidence. The shipped guard does not require the token to be *supplied* — it refuses only a *mismatch*, and only when the lease itself has a token (`github_workspace_service.py:264`): `workspace.lease_token is not None and lease_token != workspace.lease_token`. So on a lease whose own `lease_token` is `NULL`, a tokenless call **stamps** today. In SQL, `lease_token = <report.lease_token>` never matches that row, because `NULL = NULL` is `NULL` — measured, shipped stamps and the predicate affects **0** rows on the same inputs. Three things make this a sentence rather than a redesign:

     - **The shape is not produced by the current acquisition path** — `acquire` always writes a token. It survives only as a pre-column row or an operator/migration edit, the same population §4.8's NULL-pid mutation guard is kept for.
     - **The direction is safe.** A missing contact stamp can only make the backstop *more* willing to reclaim, and measured on the ordered conjunction, the contact branch is reached only after the pid branch has already found the recorded owner dead. A live owner is protected by the pid branch regardless of the stamp. For the missing stamp to matter the row needs a NULL token *and* a dead recorded pid *and* to be aged past the backstop *and* be terminal *and* have a quiescent tree.
     - **It does not generalize to requirement 2, and I predicted wrongly that it would.** `release_by_token`'s check is written *without* the presence guard — an unconditional `workspace.lease_token != lease_token` (`:190`) — so a NULL-token lease is already unreleasable by any token an agent can present: measured, shipped raises the mismatch `409` and the lease stays held, and requirement 2's predicate matches 0 rows on the same row. Requirement 2 changes nothing there; only the contact stamp changes. The two guards look interchangeable and are not, which is why this was found by reading them side by side rather than by reasoning from one to the other.

   **The comparison is ordinary SQL equality in both writes, and null-safe equality is refused — normatively, not as a review preference.** The sixteenth review raised this as a caution for the implementation plan: do not let the predicate be "fixed" into `IS`, `IS NOT DISTINCT FROM`, or an explicit `(lease_token = :k OR (lease_token IS NULL AND :k IS NULL))` branch without revisiting the decision above. A caution addressed to the plan is a requirement the spec failed to state, so it is stated here instead — and measured, it is worth more than a review checklist item, for two reasons the caution does not name.

   First, **the rewrite is invisible to every test that can exist.** Measured across all five token pairings, ordinary and null-safe equality differ on **exactly one** row — both sides NULL — and agree on the four that matter: the owner's live token matches (`1`), a genuine mismatch refuses (`0`), a tokenless call against a real lease refuses (`0`), and a token presented for a tokenless lease refuses (`0`). The `IS` form and the spelled-out both-NULL branch are measured identical, so the prohibition must name both or it will be read narrowly. And the honest half: the rewrite is **not** a hole in the contact stamp — the owner `EXISTS` clause still refuses a non-owner with a retained live token (`0` rows) and a non-owner calling tokenless (`0` rows). It restores an advisory stamp on an unreachable shape. That is precisely what makes it dangerous: harmless enough to pass review, invisible enough to erase a decision nobody will remember was made.

   Second, **requirement 1 permits a shared conditional-update helper, and that is the propagation path.** If one helper serves both writes and spells the comparison null-safe, requirement 2's write inherits it — and requirement 2's write is *destructive*. Measured on a NULL-token lease with the owner clause satisfied: with a real token presented both forms refuse (`0`, `0`), but with **no** token, ordinary equality matches `0` and null-safe matches **`1`**, clearing the lease. The owner clause holds, so this is not an ex-owner hole; it is the *owner* releasing without presenting the acquisition id, which is the property criterion 30 rests on, gated only by the route's preliminary `:339` token-presence check. That is the same "the check is not the control" shape this entire section exists to remove. So the equality is normative for **both** writes, and a shared helper must not offer a null-safe mode at all.

     **One ordering constraint applies to every conditional write in this section, and it is not obvious:** `AsyncSessionLocal` is built with `autoflush=False` (`database.py:36-42`), and measured, a raw conditional `UPDATE` evaluates its predicate against **stored** values, not the session's pending ORM changes — a pending `owner_slot_id = 2` reads as `1` in the predicate until an explicit `flush()`. Neither branch mutates `item` before its write today, so nothing is broken now; the requirement is that any conditional write whose predicate names a column the same request has modified must be issued after an explicit flush. Stated because the natural implementation of a shared helper is to call it wherever it reads well.

2. **Withdrawn.** "The check is only as good as the registration, so pair it with the write-side fix" was a statement about a check that no longer stands alone. The write-side fix below is still required — for its own reasons, stated there — but not as a prop for this one.
3. **Retained, narrowed.** The threat model this closes is **confusion, not intrusion**: a team-mate agent that does not know what it owns. PR0's pane binding raises the floor from "any registered agent on this repo" to "the process in the bound pane," so a *co-resident* process inside that same pane is the residual, and §6 scopes it out explicitly.

**The write side must be fixed first, or the read side authorizes nothing.** A check reading `item.owner_slot_id` is only meaningful if becoming the owner requires something. Measured, it requires nothing — through the real route:

```
item 1: owner=slot 1 (Alpha, preset 1); slot 3 (Charlie) is in preset 2
Charlie sends handoff_initiated(reassign_to_slot_id=3, reporting_slot_id=3):
    handoff_state='pending' target=3 owner=1        <- accepted
Charlie sends handoff_accepted(reporting_slot_id=3):
    owner_slot_id  = 3      <- was 1
    routing_method = 'reassigned'
    nonce/head unchanged
    owner's preset=2  scope's preset=1  -> owner is OUTSIDE the scope's preset
```

`initiate_handoff` (`:689-695`) writes `handoff_target_slot_id` without reading `reporting_slot_id` at all — the route's branch checks only `reassign_to_slot_id is not None` (`agent_teams.py:303-306`). `accept_handoff` (`:697-710`) validates only `handoff_target_slot_id == accepting_slot_id`. So two unauthenticated calls move ownership of any work item to any slot in any preset, and produce §4.2b.1's "not a slot of this scope's preset" shape with no operator SQL. PR1 therefore adds to `initiate_handoff` the check it never had: **the initiator must be the current owner** — the *derived* slot, not a claimed `reporting_slot_id`, per §3.5a's resolver — refusing with `403 not_item_owner` (the matrix's code, and §3.5a point 4a is where that rule is decided; this section does not restate it as `409`). The target must be a slot of the same preset as the item's scope, resolved through the loaded row rather than trusted from the request.

That second half matters more than it looks. I expected the target to be unvalidated entirely and was wrong — it *is* rejected, but by the database:

```
[fks=True]  handoff_initiated to slot 999999 -> IntegrityError, column stays None
[fks=False] handoff_initiated to slot 999999 -> accepted, column = 999999
```

The only check on the handoff target is the `ondelete="SET NULL"` FK on `handoff_target_slot_id` (`models/database.py:264-266`), so it depends on a per-connection pragma — the same dependence 37n found on `owner_slot_id` — and it surfaces as an **uncaught `IntegrityError`**, since the dispatch-status route has no handler (the three at `agent_teams.py:508/530/621` are on other routes). An agent sees a `500` with no actionable detail. Validating the target in application code replaces a `500` with a `409` and removes the pragma dependence.

### 4.6b The handoff must transfer the liveness evidence, not compensate for it

`accept_handoff` touches no workspace column, so the lease's liveness evidence still describes the previous owner's process:

```
after the real handoff: owner_slot_id 1 -> 2
    leased_owner_pid        = 424242  (unchanged)
    leased_owner_proc_start = '999999' (unchanged)
    accept_handoff mentions leased_owner_pid? False
_owner_process_is_alive with a pid that does not exist -> False
```

`_owner_process_is_alive` (`github_workspace_service.py:83-95`) is answering a question about the wrong process from the moment the handoff lands. That much revision 10 had right. **What it got wrong was the repair, and separately its own account of the severity — and the second error was in the spec's favour, which is the kind worth stating loudly.**

**The repair revision 10 claimed does not reach the failure.** It said: deliver the token, B's ordinary reports then stamp `lease_last_owner_contact_at`, and the evidence tracks the working agent. `reclaim_stale`'s guards are an **ordered** conjunction, not a set of interchangeable signals (`github_workspace_service.py:291-303`):

```
if kind == "primary":                          continue
if leased_at is None or leased_at > threshold: continue
if _owner_process_is_alive(workspace):         continue   <- reads the PID
if contact_at is not None and > threshold:     continue   <- reads the stamp
if not await _worktree_is_quiescent(...):      continue
release
```

The PID branch short-circuits **before** the contact branch is evaluated. So with A's pane alive and B gone, the contact stamp is unreachable — measured on an `escalated` item aged past the backstop with a quiescent tree: `reclaimed 0` with no stamp, and `reclaimed 0` again with a **fresh** stamp. The stamp is not weaker evidence than the PID, it is *downstream* of it. Delivery fixes who may act; it does not fix whose liveness is observed.

Delivery does repair the mirror case, and that half stands: with A's pane dead and B alive but quiet, `reclaimed 1` and the lease is pulled out from under a live worker — unless B has stamped, and stamping needs the token (`reclaimed 0` with a 5-second-old stamp). So the honest statement is that revision 10's repair covers one of the two directions.

**The severity was overstated in the spec's own favour, and the reason is a selector.** Revision 10 wrote that "once A's pane exits, the backstop reads 'owner dead' about an item B is actively working." It does not, because it never looks: `_RECLAIMABLE_STATUSES = ("escalated", "failed", "merged", "completed")` (`:28`) excludes `dispatched`, which is the item's status for the entire working life of the target. Measured under otherwise identical aged/dead/quiescent conditions: `dispatched → reclaimed 0`, `escalated → reclaimed 1`. This is [[check-name-vs-discriminating-power]] in the direction that flatters the design — the guard the prose credited with restraint was not the guard doing the work, and the actual reason nothing bad happens during the handoff window is that the only reader of the PID is not running. The stale PID is therefore **latent, not benign**: it becomes live evidence the instant the item reaches a terminal status, which is exactly when the operator is trying to work out whether the worktree is safe to reclaim.

That also means this defect is invisible to any test that seeds a `dispatched` item — the first probe written for it did exactly that and returned three green "reclaimed 0" results that proved nothing, because a selector that returns no rows and a conjunction that correctly refuses are indistinguishable from the outside. **§4.8's tests pin the selector's own verdict first** (37r-4a), so a future change to `_RECLAIMABLE_STATUSES` cannot silently make the rest of the group vacuous.

**The requirement.** The evidence transfers with the authority, **in the request that carries the authority** — not in a later one.

Revision 11 required `accept_handoff` to *clear* the three columns and let §4.6a's continuation claim stamp them, on the stated ground that "the accepting call may arrive from anywhere" so the service cannot know B's pane. **That ground is revision 10's stale-codebase mistake committed one revision later, inside the very section that names the mistake.** It is a true statement about `master` and a false one about PR1: after PR0, `handoff_accepted` arrives through `/dispatch-status` behind `require_session_slot`, whose third step has *already* resolved the caller to a pane via `agent_pane_bindings` and whose target-only matrix check (§3.5a) has already compared that slot to `item.handoff_target_slot_id`. The accepting request does not merely have access to B's pane identity — the route cannot authorize the call without deriving it first. Measured, the HTTP route is the only production caller of `accept_handoff` (`agent_teams.py:311`; the other two callers are service tests at `test_github_dispatch_service.py:2446-2448`), so passing the verified pane into the service changes one call site.

And clearing is not the fail-safe half revision 11 claimed it was. It cited `_owner_process_is_alive` returning `True` on a NULL pid (`:85-86`) as protection for a live B, which is correct and is one side of a two-sided property. The other side, measured on a terminal item with a quiescent tree:

```
terminal item, NULL owner pid, lease aged 1h       -> reclaimed 0, still leased
terminal item, NULL owner pid, lease aged 9h       -> reclaimed 0, still leased
terminal item, NULL owner pid, lease aged 90 days  -> reclaimed 0, still leased
control, same age but a DEAD pid recorded          -> reclaimed 1, released
```

The `True` at `:86` makes `reclaim_stale` `continue` at `:297` **before it ever reads the age**, so a workspace whose accepting agent died before claiming context is leased forever. The control is the discriminating half: identical age, identical quiescent tree, identical terminal status — the only difference is that the pid is *recorded and dead* rather than absent, and that row releases. So the leak is caused by the clearing, not by the fixture. Revision 11 called the window "bounded by the brief"; **a prompt is not a bound, because the thing it asks for is exactly what a crashed process does not do.** There is no timeout on this path and none is proposed — the fix is to not create the window.

1. `accept_handoff` takes the accepting pane's `(pid, proc_start)` as a parameter and **sets** `leased_owner_pid`, `leased_owner_proc_start` and `lease_last_owner_contact_at` in the same transaction as `owner_slot_id` and `routing_method`. One commit: ownership and the evidence about ownership are never separately observable. The route supplies the values from `require_session_slot`'s verified binding, never from the request body.
2. If **no workspace is leased**, update the item only and write no liveness columns. Do not invent evidence for a lease that does not exist — the columns live on `github_workspaces`, and there is nothing to be truthful about.
3. §4.6a's continuation claim still stamps the same three columns, now **idempotently refreshing** what the handoff already wrote rather than being the first moment the row becomes truthful. It stays a `POST` and stays authenticated for its own reason (the payload is a bearer secret), and a target that never calls it is no longer a stuck lease. Requirement 3 is now a convenience; requirement 1 is the correctness.
4. **No new column.** Measured: with the row corrected to a live pid, `_owner_process_is_alive` returns `True` and `reclaim_stale` releases nothing; with it pointing at a dead pid, `False` and the row is released. The predicate is already correct — it was pointed at the wrong process. Transfer the evidence; do not add a second channel to compensate for stale evidence.
5. **Nothing clears these columns, and the case that looks like an exception is not one.** A `handoff_accepted` call whose session resolves to an *unbound* pane — §3.3 rung 2, a tmux pane Deck never launched — cannot be the handoff target, because the target is a slot and an unbound session has none, so §3.5a's matrix refuses it (`403`) before the service is reached. There is therefore no "the pane is unknown" branch to write: the columns keep pointing at A until either the target authenticates properly or the backstop reclaims on A's death, and both of those are correct. Stated explicitly because the natural defensive instinct — *I do not know who the new owner is, so I will null the stale values* — reintroduces exactly the unreclaimable lease the measurement above records. **When the pane is unknown, the call does not happen.**

`touch_owner_contact` still no-ops without the token (`:264-270`) — measured: B reports `triaging`, `status_note` is written, `lease_last_owner_contact_at` stays `NULL` — so delivery is still required for B's *ongoing* contact stamps. Delivery and transfer are two fixes for two halves, and revision 10 offered one of them for both.

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
    11f. **A handoff does not invalidate the head the agent was briefed with — the blocker-2 test.** Prepare an attempt for slot A and record the head `prepare_attempt` returned. Drive the **real** `initiate_handoff` and `accept_handoff` to slot B (not a hand-written `owner_slot_id` assignment — the point is what the shipped function does). Re-read in a fresh session and assert `dispatch_nonce` and `dispatch_head_ref` are **both** unchanged and `owner_slot_id` is now B's. Then apply the head check to **A's head** — the only head anyone was ever told — and assert it is **accepted**. Against revision 8's composed form this is a `409 head_ref_mismatch` whose expectation is `deck/slot-<B>/issue-42-<nonce>`, a name no brief ever contained; measured both ways in the same test file, parametrized over the two designs, so the comparison is in the record rather than in the commit message. **In PR1 the check is the comparison itself** — `reported_head == item.dispatch_head_ref` against the re-read row — because `pr_ready` is PR2's route (§2.1). §5.8's test 14 asserts the same rule through the route once that route exists. The equality is the invariant; the route is one caller of it.

    Assert the *write set* too, from `inspect.getsource(accept_handoff)`: `owner_slot_id` present, `dispatch_nonce` and `dispatch_head_ref` absent, and `dispatched_at` absent (§4.2a: the ack deadline is not re-anchored). That assertion is what makes 11f fail loudly rather than mysteriously if someone later "fixes" handoff by clearing the head.

    11g. **The target obtains A's head through the real tool, not from the test's own variable — the blocker-3 test.** 11f proves the head *survives* a handoff; it does not prove B can ever *learn* it, and as written it hands B the head out of a local variable. That is fixture-injected knowledge: it would pass against a design in which no agent-facing read exposes the head at all, which is exactly today's state. So 11g re-runs 11f's second half with one change — B's head comes from `deck_get_work_item_context`, called as the shim function with only the HTTP transport stubbed, and `reporting_slot_id` supplied by the stubbed registration rather than by the caller. Assert the returned `dispatch_head_ref` **equals** the head `prepare_attempt` returned for A, then feed *that returned value* into `pr_ready`'s check and assert acceptance. The test must never name the head literally after the prepare step.

    Its discriminating power is in the negative control, which is the shipped tool: the same probe through `deck_list_work_items` receives exactly `['dispatch_status', 'escalation_reason', 'issue_number', 'status_note', 'work_item_id']` and therefore **cannot** complete the flow — measured, and the reason §4.6a is a new mechanism rather than a widened projection. Assert that key set exactly, so the control fails if someone later adds the head to the five-key dict and makes the new tool redundant without saying so.

    37r. **The split-authority deadlock, driven through the real route.** After a real handoff A→B on an item in a releasable status, all three of: A with the live token → `409` naming the owner check; B with no token → `400 lease_token required`; B with a plausible wrong token → `409 lease_token does not match`. Then assert the lease is *still held* (`leased_item_id` unchanged, `lease_token` non-NULL) — the assertion that makes this a liveness bug rather than three independent refusals. Stub `release_blocker` only (it shells to real git); leave both checks live. This test fails against current `master` and is the regression guard for §4.6a's reason to exist.

    37r-1. **Delivery is sufficient, and rotation would break it.** The same fixture, B reporting `workspace_released` with the **actual** live token ⇒ succeeds, `leased_item_id` NULL, `lease_token` NULL. This is the positive control for 37r and the evidence behind the no-rotation decision: nothing binds the token to the slot that received it. Pair it with the two-consumer assertion — A, still holding the live token, reports `triaging` as a non-owner and `lease_last_owner_contact_at` stays NULL (the route's `reporting_slot_id == item.owner_slot_id` guard at `:371-373` skips `touch_owner_contact`), while the workspace's stored token is *unchanged*. Both halves matter: the retained token grants no authority, and it was never invalidated — so rotation protects against nothing and destroys the only copy.

    37r-2. **`initiate_handoff` refuses a non-owner, and the target must be in the preset.** Three cases through the real route. (i) A slot that is not the owner sends `handoff_initiated` ⇒ **`403 not_item_owner`**, and `handoff_target_slot_id` stays NULL — assert the column, not just the status, since a route that writes then refuses would pass a status-only check. (ii) The owner sends `handoff_initiated` targeting a slot in a **different preset** ⇒ `409`, column unchanged. (iii) The owner targeting a sibling slot in the same preset ⇒ accepted. Against current `master`, (i) and (ii) both succeed and (ii) ends with `owner_slot_id` on a slot outside the scope's preset — measured, and the same shape §4.2b.1's third row exists to catch.

    **Case (i) said `409` through revision 12 and that was wrong**, against three places in this spec: §3.5a's matrix row for `handoff_initiated` (`:668`), its point 4a (`:697`, which explicitly rejects `409` for this case), and 37r-2a immediately below, which asserts `403 not_item_owner` for the same refusal reached by a different caller. Two adjacent tests demanding different codes for one branch is worse than either code being wrong, because whichever the implementer writes, a test fails and neither test tells them which is authoritative. **The two codes are two different facts and the split is deliberate:** `403 not_item_owner` says *you are not the owner*, which is about the caller; `409` says *your target is unusable*, which is about the request. Case (i) is the first, cases (ii) and 37r-3 are the second — so the `409` stays exactly where the object of the refusal is the target rather than the caller.

    37r-2a. **The leader is refused on `handoff_initiated` too.** Blocker 2's resolution, tested at the point where the two candidate designs differ. 37r-2 case (i) uses an unrelated third slot, which passes against an implementation that refuses everyone *except* the leader — the implementation revision 10's matrix asked for. So: the preset's **leader** slot, which is not the item's owner, sends `handoff_initiated` ⇒ `403 not_item_owner`, `handoff_target_slot_id` still NULL. Assert the refusal **code** and not merely a 4xx, because §3.5a's matrix names it and tests 7b/7c check the matrix exhaustively — a `409` here fails those instead, and the implementer would then have two failing tests pointing in opposite directions. (That is exactly the collision 37r-2 case (i) carried until revision 13; see its second paragraph.)

    **The positive control, corrected.** Revision 12 wrote it as "the same leader slot calling §4.2b.2's operator route succeeds," and that route cannot authenticate a leader slot: §4.2b.2's caller row specifies `require_operator` with **no session token and no slot derivation**, so "the leader calls it" names an actor the route has no way to recognise — the call succeeds or fails on whether an operator token was presented, and the leader's identity is not read at any point. Keeping the sentence would have taught an implementer that `resume-attempt` distinguishes callers by slot, which is the opposite of §3.6a's design. So the control becomes: **a call carrying the operator token, on a proper `prepared_owner_unavailable` fixture, succeeds** — and the sentence the test is making is *the recovery exists and is reachable*, not *the leader is the one who reaches it*. The leader's genuine need is **served by** the operator; the leader is not the authorized caller. Stated this way because the distinction is the whole of §3.6a: an authority that agents can invoke on their own behalf is not an operator authority, and a "positive control" that shows an agent succeeding on an operator route would have been evidence for the defect rather than the fix.

    37r-3. **A nonexistent target is refused by application code, not by a pragma.** Parametrized over `PRAGMA foreign_keys` ON and OFF: `handoff_initiated` to a slot id that does not exist ⇒ `409` in **both** cases, with `handoff_target_slot_id` NULL in both. This is the mutation-resistant form of a finding whose current behavior is pragma-dependent: measured on `master`, FKs on gives an uncaught `IntegrityError` (a `500` to the agent, since the dispatch-status route has no `IntegrityError` handler) and FKs off *accepts* the write and stores `999999`. Parametrizing is the point — a test written only with the pragma on would pass today and prove nothing about the validation.

    37r-4a. **Pin the selector before testing the conjunction.** This test exists because the first probe written for 37r-4 was vacuous and its three green results were worthless. Assert `_RECLAIMABLE_STATUSES == ('escalated', 'failed', 'merged', 'completed')` by equality, and then the discriminating pair: under *identical* aged-lease, dead-owner-pid, clean-tree conditions, `reclaim_stale` releases **1** on `escalated` and **0** on `dispatched`. Measured:

    ```
    _RECLAIMABLE_STATUSES = ('escalated', 'failed', 'merged', 'completed')
        status=dispatched   aged 9h, owner pid dead, tree clean -> reclaimed 0
        status=escalated    aged 9h, owner pid dead, tree clean -> reclaimed 1
    ```

    Two things follow, and both belong in the suite rather than in a comment. First, a `dispatched` fixture makes every "reclaimed 0" in the group unfalsifiable — the selector returns nothing and no guard is ever evaluated, so a correct conjunction and a broken one look identical. Any later test in this group that seeds a status must justify it against this equality. Second, this is the measurement that bounds blocker 4's severity in the direction *against* the spec: while the item is `dispatched` — the whole of the target's working life — the stale PID has no reader, so the defect is **latent** and becomes live evidence at the moment the item turns terminal. Revision 10's severity account had this backwards in its own favour.

    37r-4. **The handoff transfers the liveness evidence, and delivery alone does not.** Rewritten: revision 10's version asserted that B's contact stamp repairs the stale PID, and the ordered conjunction makes that unreachable in the case that matters.

    **First, what does *not* belong in this test, because revision 12 left the contradiction it says it removed.** Revision 12 replaced revision 11's clear-the-columns ending with §4.6b's set-the-columns behaviour, and left part (i) in place: an assertion that the real `accept_handoff` leaves the pid columns untouched and that `inspect.getsource(accept_handoff)` mentions neither them nor `workspace`. §4.8's tests ship **with PR1**, so both halves run against the same post-PR1 function, and §4.6b requires that function to write exactly those columns and to touch exactly that object. `inspect.getsource` makes it unarguable — it is a direct assertion about the implementation's text. The two cannot both pass; an implementer would have had no way to satisfy the file. **The same shape as revision 11's, surviving the revision that names it**, which is the third time this spec has caught a stale claim inside the paragraph correcting one: a test that pins `master`'s behaviour is evidence for the design, and it stops being a test the moment it ships in the PR that changes that behaviour.

    So parts (i) and (ii) below move **out of the normative PR1 suite** and become design evidence, recorded here and reproducible as a **disposable probe run against the pre-PR1 commit** — where they are true, checkable, and harmless. What remains in §4.8's 37r-4 is only the post-PR1 contract, listed at the end of this entry. The measurements keep their place in the spec because they are what makes §4.6b's requirement legible; what they lose is their status as assertions the final suite must satisfy.

    (i) **The defect** (pre-PR1 evidence, not a PR1 assertion): `leased_owner_pid` and `leased_owner_proc_start` are untouched by `master`'s `accept_handoff`, and `inspect.getsource(accept_handoff)` mentions neither them nor `workspace` at all. (ii) **The refutation of the claimed repair** (same status) — with A's pane *alive* and recorded on the row, `reclaim_stale` releases `0` whether `lease_last_owner_contact_at` is NULL or freshly stamped:

    ```
    A's pane alive (pid 859398), B gone, no contact ever stamped,
    lease aged 9h, tree quiescent -> reclaimed 0, leased_item_id=1
    same case with a FRESH contact stamp   -> reclaimed 0
    ```

    **The disposable pre-PR1 probe asserts both, in that order** — they are evidence, not normative PR1 assertions, and saying "in one test" here would put them back in the suite this entry just moved them out of. The identical outcome is the finding: `_owner_process_is_alive` is evaluated **before** the contact branch (`:296` before `:299`), so the stamp is read by a branch this case has already short-circuited past. Delivery fixes *who may act*; it does not fix *whose liveness is observed*. And (iii) **the repair**, which needs no new column: with the row corrected to B's live pane, `_owner_process_is_alive` flips `False → True` and `reclaim_stale` releases `0` for the right reason:

    ```
    row says A (dead)      -> _owner_process_is_alive = False
    row corrected to B     -> _owner_process_is_alive = True
    reclaim with B recorded and alive -> reclaimed 0
    ```

    Keep revision 10's dead-A/live-B half as a **separate labelled case** rather than deleting it, because it is the half revision 10 got right and it is what makes delivery load-bearing: A dead and B never stamped ⇒ reclaimed `1`, the lease pulled out from under a live B; the same case with B stamping 5s ago ⇒ reclaimed `0`. Both measured. The pair states the actual division of labour — delivery covers dead-A, evidence transfer covers alive-A — so a reader cannot conclude that either fix alone is sufficient.

    **The normative test — this list and nothing above it.** Every assertion here is about the **post-PR1 implementation**; the pre-PR1 material above is evidence, and the boundary is drawn where it is so that a single coherent implementation satisfies the whole entry. Revision 11 ended this test by requiring `accept_handoff` to leave all three columns `NULL`, which §4.6b now requires it to **set**; revision 12 fixed that ending and kept a `master`-pinning opening; revision 13 keeps only the ending. Assert:

    - after an authenticated `handoff_accepted` for target B, the workspace records **B's** pane: `leased_owner_pid == B_pid`, `leased_owner_proc_start == B_proc_start`, `lease_last_owner_contact_at` is not NULL, and `item.owner_slot_id == B`. One transaction — assert the item write and the workspace writes are both visible after a single commit, because the defect this replaces was precisely that they were not simultaneous.
    - A is **gone from the evidence**: assert the recorded pid is not A's. Stating it separately from "is B's" matters, because a partial implementation that writes only `lease_last_owner_contact_at` satisfies a NULL-check but leaves A recorded.
    - **the terminal-lease reclaim now works even if B never claims context.** With B dead, the item terminal, the tree quiescent and the lease aged past the backstop, `reclaim_stale` releases `1`. This is the assertion that would have caught revision 11's design: run it against the cleared-columns behaviour and it returns `0` at any age, measured out to 90 days.
    - the **control against the unbounded leak**: the same row with a NULL pid returns `0` from `reclaim_stale` while a recorded-dead pid returns `1`, identical in every other respect. Keep it as a labelled case rather than a comment — it is the evidence that `_owner_process_is_alive`'s `True`-on-NULL is not fail-safe in the terminal direction, and without it a later reader may "simplify" back to clearing.
    - and the mutation guard revision 11 was right to add, restated for the new behaviour: an implementer who makes `_owner_process_is_alive` return `False` on a NULL pid "to fix the leak" must fail a test. Assert the predicate still returns `True` for a NULL-pid row, because that path is still reached by workspaces leased before the pid columns existed, and flipping it would start reclaiming those live.
    - **`claim-continuation` refreshes this evidence, it does not establish it.** B calls the claim after accepting: `leased_owner_pid` and `leased_owner_proc_start` are **unchanged** (same pane, so the refresh is a no-op on those two) and `lease_last_owner_contact_at` moves forward. Then the assertion that pins the ordering rather than the values: run the *same* claim against a workspace whose pid columns were never written, and it must still be the case that ownership was truthful before the claim — i.e. assert the columns were already correct immediately after `accept_handoff`'s single commit, with **no** claim call in between. Stated as its own case because §4.6a's endpoint and §4.6b's write both touch these three columns, and the whole of blocker 4 was the belief that the *claim* is the moment ownership becomes true. A test that only ever asserts the columns after a claim cannot tell the two designs apart.

    37r-5. **The continuation claim is authorized on the derived slot, and a same-repo sibling cannot take it.** **Replaced.** Revision 10's version pinned the *scope* of `reporting_slot_id`'s weakness — that a caller's own `CLAUDE_DECK_TEAM_SLOT_ID` decides which slot it claims — as an honesty assertion behind a paragraph admitting the endpoint was not authenticated. PR0 removes the premise: the claim route derives identity from the pane binding, so a test that documents the weakness of a field the route no longer reads guards nothing. Blocker 1's class, one test over.

    The replacement is adversarial and same-repo on purpose, because same-repo is the case with no discriminating power *before* PR0: `_slot_matches_registration` compares `provider` and `repo_id`, identical across every slot of one preset (§1's finding). Four cases through the real route, all with the item owned by slot A:
    - slot **B**, a sibling of the same preset on the same repo, with a valid session token bound to B's own pane, calls `claim-continuation` ⇒ **`403 not_item_owner`**. This is the whole test: pre-PR0 this call is indistinguishable from A's. The code matters and revision 11 had it wrong — B sends no conflicting claim, so nothing *mismatches*; the derivation succeeds and the authorization fails. `slot_claim_mismatch` is reserved for the next case, where a body claim disagrees with the derived slot. Two different refusals for two different facts: *you are not the owner* and *you are not who you say you are*. Collapsing them would make the matrix's own vocabulary unreadable in logs, and would let an implementation that never derives a slot at all pass by returning the mismatch code for everything.
    - slot B with a valid token **and** `reporting_slot_id: A` in the body ⇒ `403 slot_claim_mismatch`, the derived slot governing and the body's claim being at most corroboration (§4.6a). Assert no payload and, specifically, that the response body contains no `lease_token` substring — a route that computes the payload and then refuses would leak on the error path.
    - slot **A** with a token bound to a pane that is **not** A's ⇒ `403 bind_unverifiable`, not `200`. The token identifies a session; the pane binding is what ties it to a slot.
    - slot A, correctly bound ⇒ `200` with the payload. The positive control, without which every assertion above is satisfied by a route that refuses everything.

    Keep the registration measurement itself — one slot's process registering as another and being *named* as that other slot, with the different-`cwd` control resolving to `team_slot_id=None` / `participant_kind='repo'` — but move it to where it is still load-bearing: it is the evidence for §4.6a's rule that `reporting_slot_id` is never an authority input, and for §5.5.6's three-check requirement. It is a **fact about the codebase**, not a property of this design, so it belongs in the section that cites it rather than in a test that would now be asserting the absence of a defence nobody claims.

    37r-6. **The existing delivery channel cannot be reused, and the reason is a status gate.** With the item `dispatched` (the target's entire working life), `remind_held_leases` returns `0` and sends `0` messages; with the item `merged` after the same real handoff, it returns `1`, the recipient is the member resolved from the **current** owner, and the live `lease_token` appears in the body. Assert `"dispatched" not in _RELEASABLE_STATUSES` alongside, so the test names the mechanism rather than the observation. Pair with the undelivered-reminder control: no `MailTeamMember` for the new owner ⇒ returns `1`, sends `0`, and `lease_release_reminded_at` is stamped anyway, so the next poll skips it for a full grace period. Second instance of 37n-6's shape, and the reason §4.6a delivers context at handoff time instead of widening this selector.

    37r-7. **The live token appears in no URL, no log, no exception and no `status_note`.** The non-blocking correction the tenth review raised, made checkable. The claim route returns a bearer secret in its response body, so every other place that value could come to rest is a leak, and four of them are reachable by accident rather than by design:
    - **URL.** Assert the route's path and its request model expose no token-bearing query parameter — the `GET ...?reporting_slot_id=<n>` shape revision 10 specified put the *identity claim* in access logs, and the same mistake with the token in a redirect or a retry URL is one refactor away. Assert `Cache-Control: no-store` is on the response while here, since it is the same concern.
    - **Log.** Capture logging with `caplog` at `DEBUG` across the whole call and assert the token string does not appear in any record. `DEBUG`, not `INFO`: a debug line added later is exactly how this regresses.
    - **Exception.** Drive the route to each of its refusal paths and assert the token appears in no `detail`. The `bind_pending` path is the one to check hardest — it is retryable, so its message is the one most likely to be made helpful.
    - **`status_note`.** After a successful claim, assert the item's `status_note` is unchanged. The claim also writes the pane identity (§4.6b), so it is a route that both touches the row and holds the secret.
    - **A fifth resting place, and the only one that is live on `master` today: the force-release mismatch response.** Measured end to end through the real ASGI app, an unauthenticated `POST` with a deliberately wrong `expected_lease_token` returns `409` whose `detail.message` contains the **current** token verbatim (`agent_teams.py:695-696` through `_conflict` at `:84-88`). Assert the token appears nowhere in that response, and assert it for the **supplied** value too — echoing back what the caller sent is harmless in itself and is how the stored value gets reintroduced by a later "symmetrical" edit. This case belongs in *this* test rather than only in §3.6a's operator-auth tests, because it is a disclosure defect, not an authorization one: fixing the auth without fixing the message leaves the oracle in place for anyone who obtains the operator credential, and fixing the message without the auth still leaves force-release open. Two independent fixes, and this assertion is the one that pins the disclosure half. The refusal shape to assert against is the one that already exists one file over — `release_by_token` names the item, never the secret (`github_workspace_service.py:191-193`).

    Use one token value seeded into the fixture and search for that exact string, rather than a regex for token-shaped text: `secrets.token_hex(8)` output is 16 hex characters, which a plausible pattern will also match in a nonce or a sha, and a test that passes for the wrong reason here is worse than no test.

    37r-8. **An admitted ex-owner cannot release the new owner's lease — the thirteenth review's blocker, and the assertion criterion 30 rests on.** Two interleavings through the **real** route, both against rows read back with raw SQL. In each, the handoff is driven by the real `initiate_handoff` / `accept_handoff` rather than by assigning `owner_slot_id`, because what is being tested is that the token is *legitimately* retained.

    (i) **Owner changes, token does not.** A is the owner of a terminal item on a leased worktree and reports `workspace_released` with the live token. Suspend the request inside `release_blocker` — stub `_runner`, which the branch really awaits twice for a worktree (`github_workspace_service.py:203`, `:211`) — and hand the item off A→B while it is suspended. Resume. Assert `409` (`lease_changed`), `owner_slot_id == B`, and B's lease **fully intact**: `leased_item_id == item.id` **and** `lease_token` still the same value. Assert the token separately from the item pointer; an implementation that clears one and not the other is a state no code path produces deliberately. Measured against `master`, this returns **`200`** and the row reads `leased_item_id=None token=None`.

    (ii) **Acquisition changes, owner does not.** Same shape, but during the suspension release the workspace and re-acquire it for the same item with a **new** token, leaving A as owner throughout. Assert `409` and the replacement intact. This is the case a token-keyed predicate catches and the owner predicate alone would not, so the pair proves both clauses are load-bearing rather than one covering for the other.

    **Positive control, without which both of the above pass against a route that refuses everything:** B, the current owner, releases with the current token ⇒ `200`, the lease cleared, and the conditional write's **affected-row count exactly one**. Assert the count, not only the end state: it is what distinguishes "this acquisition was released" from "some acquisition was."

    Also assert, in (i), that the ex-owner's request wrote **nothing at all** — the seven release-state columns are byte-for-byte what they were before the call. A `409` that has already cleared `lease_last_owner_contact_at` is a refusal that damaged the lease it protected.

    37r-9. **A retried release still succeeds, and the `409` belongs to a request that was admitted and then staled — four orderings, because revision 14's two could not tell each other apart and revision 15's three left one of its own branches untested.** The thirteenth review specified "zero affected rows ⇒ `409`", and measured, that regresses a live behaviour: today the true owner reporting `workspace_released` twice with the true token gets `200 → 200`, because `release_by_token` returns silently when the workspace is already unleased (`:188-189`). That much revision 14 had right. What it had wrong is which request reaches the zero-row branch, and the correction changes what this test can prove. Four cases, two of them on path A:

    (i) **The retry — path A's first outcome.** Same owner, same token, two identical reports ⇒ **`200` both times**. On the second, assert the route took requirement 5's **path A** — `get_leased_workspace` returned `None` and no conditional write was issued at all. Assert that positively (spy on the helper, or assert an affected-row count was never recorded), because "no write attempted" and "a write that matched nothing" are the two states revision 14 conflated, and a test that only checks the status code cannot separate them.

    (i-b) **Path A's *second* outcome, which revision 15 required and left untested — the fifteenth review's blocker.** The item has **no** leased workspace. A is admitted at `:334` as owner, and the handoff A→B commits while the request is inside `get_leased_workspace`; A resumes on path A and diagnoses ⇒ **`403 not_item_owner`**. Assert that neither `release_blocker` nor the conditional write ran, and that the diagnosis read **B**. Measured, this is the case that separates the two implementations of "fresh-read": a scalar `SELECT` reads `2` and refuses, while `db.get`/the cached `item` reads `1` and returns **`200`** — telling an agent that no longer owns the item that its release succeeded.

    Two things about how this case must be built, both measured, and neither optional:

    - **Suspend at `get_leased_workspace`, not inside `release_blocker`.** On path A the workspace is `None`, so `release_blocker` sits inside `if workspace is not None` and is never awaited — the recipe (i) borrows from 37r-8 does not exist on this path. Measured offsets in the real branch: owner check `12`, `get_leased_workspace` `739` (unconditional), the guard `812`, `release_blocker` `860`, the write `1336`.
    - **Interleave the handoff; do not seed it.** Measured, a handoff committed *before* the request is refused at `:334` having never reached the lookup, because a fresh request session's `db.get` at `:291` emits a real query and binds the stored owner. And after §3.5a that refusal is *also* `403 not_item_owner` — the same code this case asserts. A seeded version is therefore green against a cached diagnosis, against no diagnosis, and against `master`: revision 14's 37r-9 defect exactly, reproduced on the branch that fixed it. The branch-arrival assertion is what makes the case discriminate at all.

    (ii) **The admitted-then-staled request — the only ordering that reaches the zero-row branch.** A passes `:334` as the owner and captures the workspace, then, suspended inside `release_blocker`, B takes ownership **and releases**. A resumes ⇒ **`409 lease_changed`**, nothing written. Measured, A's conditional write affects **0** rows here with both facts true at once: no lease exists, and the caller is not the owner. This is requirement 5's **path C**, and it is what the `409` is *for*.

    (iii) **The direct non-owner keeps the matrix's `403`.** A fresh late report from A after the handoff ⇒ `403 not_item_owner` from the preliminary `:334` check, having reached neither `release_blocker` nor the write. Assert both non-arrivals, not just the code.

    **Revision 14's version of this test asserted (iii) while claiming to test (ii), and was therefore green against everything.** Measured, that late report is refused at `:334` and never reaches the write, so the `409` it asserted came from the preliminary check — the same `409` on `master`, under the intended write, and under a `zero rows ⇒ 200` mutant alike. It is recorded here rather than quietly replaced because the failure mode is the one this spec keeps finding in its own tests: **an assertion satisfied by two different mechanisms discriminates neither.** Case (ii) is the version that can only pass if the conditional write exists and its zero-row branch diagnoses rather than assumes; case (i) is the version a flat `409` fails; case (i-b) is the version a cached path-A diagnosis fails; case (iii) pins the refusal that must *not* migrate to `409` (§4.6a.1 requirements 5 and 6). One case per branch outcome, and the two path-A cases differ *only* in whether ownership moves mid-request — which is the whole of what the fresh read is for.

    **Which cases can assert freshness, and why it is not (i).** Revision 15 said "in (i) and (ii) alike, assert the diagnosis reads stored ownership: seed the interleaving so the route's cached `item` and the stored row disagree." Those two conditions cannot describe the same case, and that is the review's blocker: if path A's stored owner differs from the cached caller, path A must return `403`, not case (i)'s `200`. Case (i) is a same-owner duplicate, so cached and stored *agree* by construction — measured, it is green against the cached-diagnosis mutant, which reads owner `1` and returns `200 → 200` exactly as required. The freshness assertions therefore belong to **(i-b)** on path A and **(ii)** on path C, one per branch, since the two are separate control flow and a mutant may be introduced in either alone. Case (i)'s job is narrower and still necessary: it is the case a flat `409` fails.

    37r-10. **The liveness stamp is owner-gated in the operation that writes it — and the test must fail a fresh-read-then-stamp implementation, not only the cached-`item` one.** The second false row in criterion 30's table, and it needs its own test because it is on a *different* branch from 37r-8. Two interleavings, because the two implementations this must reject fail at different points:

    (i) **Handoff before the tail runs.** With A the owner of a `dispatched` item on a leased worktree and `lease_last_owner_contact_at` NULL, A reports `blocked`; suspend inside `github_dispatch_service.escalate`, which that branch really awaits, and hand off A→B during the suspension. Assert `lease_last_owner_contact_at` is **still NULL** afterwards. Measured against `master` it is stamped, with `touch_owner_contact` receiving the retained token (`token='TOK-KEPT'`), because the tail's comparison at `:371-373` reads the `item` bound at `:291` and `expire_on_commit=False` never invalidates it.

    (ii) **Handoff between the ownership read and the stamp — the case (i) cannot reach.** Suspend at the *last* await before the contact write and commit the handoff there, then let the stamp proceed. Assert `lease_last_owner_contact_at` is still NULL. **Measured, revision 14's permitted two-step implementation passes (i) and fails only this**: with the handoff landing at `escalate`, a fresh re-read afterwards correctly sees B and skips the stamp, so (i) is green while the race survives at smaller scale. Against a single conditional write there is no gap to suspend in and the case is trivially green — which is the point. It exists to make the difference between the two implementations *observable*, and it is the reason requirement 8 no longer offers a choice.

    Two controls, because the assertion is a negative: B reporting `blocked` on the same item **does** stamp the column, and A reporting `blocked` with **no** handoff interleaved also stamps it. Without those, an implementation that never calls `touch_owner_contact` at all passes.

    **A third control for the token clause**, which is the mirror of 37r-8 case (ii) on this branch: A remains the owner throughout, but the acquisition is replaced `TOK-1 → TOK-2` during the request. A's report carries `TOK-1` ⇒ the column stays NULL. Measured on the row itself, the owner-only predicate matches **1** and owner-plus-token matches **0**, so without this case a stamp keyed on ownership alone refreshes an acquisition the caller never held.

    Bound the claim in the test's own docstring rather than overstating it: the consequence is a **delayed backstop reclaim**, not a destroyed lease, and it has no reader until the item is terminal (`_RECLAIMABLE_STATUSES`, test 37r-4a). It is in the suite because criterion 30 asserts the row, not because the row is severe.

    46r. **The credential helper's owner check, and the token's insufficiency.** §5.5.6's third check, tested at the case that motivates it. After a real handoff A→B on a dispatched item, with the **same** live `lease_token` in the worktree config throughout:
    - A's helper calls `POST /agent-teams/git-credential` from a pane bound to A ⇒ `403`. A holds a valid token for a current lease on the right path, and is refused on identity alone. This is the assertion; the other three are controls.
    - B's helper, from a pane bound to B ⇒ `200`, credential minted.
    - a pane with **no** binding ⇒ `403 pane_unresolved`, and — the part worth asserting separately — the refusal detail names the measured ancestor distance and the walked chain. A bare `403` satisfies the check and makes a denied push undiagnosable, which §5.5.6 calls out as the liveness risk of a 1-hop margin.
    - the token **absent** ⇒ refused before any pane walk, so the token remains a required attempt binding and the owner check is an addition rather than a replacement.

    Stub the installation-credential mint; leave both authorization checks live. For the ancestry, spawn the caller through a real nested-shell chain rather than monkeypatching the resolver — the depth arithmetic in §5.5.6 was measured, and a test that stubs the walk cannot notice when a git upgrade adds a hop. Assert the resolver's cap is the credential path's cap (**16**) and not the mail path's (**8**) in the same test, because a single shared constant is the mutation that silently loosens mail registration to fix a git problem.
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
21. `deck_approve_work_item` resolves the thread from `(work_item_id, dispatch_nonce, item.approval_round_count)` — the round included, since round-scoped resolution is what makes the recovery path in test 29 legal. Correct triple ⇒ answer posted in the owner's thread with `decision` set. No matching request ⇒ `404`. Two matching requests **from the current owner, in the current round** ⇒ `409` naming both ids. Two matching requests from *different* owners is the handoff shape (§4.2) and resolves to the current owner's — assert that too, since a resolver that ignores the owner would raise `409` on an ordinary post-handoff approval.
22. A **Specialist** calling `deck_approve_work_item` (or posting `decision` directly to `POST /messages`) ⇒ `403`, and no `mail_messages` row is written with a non-NULL `decision`. Assert the row state, not only the status code — a route that writes then refuses would pass a status-only assertion.
23. A **tokenless** caller supplying `decision` ⇒ `403` even with `mail_capability_tokens_required = False`. §3.4a's rule applied to the decision column.
24. `decision` outside `{'approved','rejected'}` (e.g. `'maybe'`, `'APPROVED'`) ⇒ `422`. Case is not normalized; an unrecognized value is never treated as approval.
25. `deck_reply` still works and writes `decision = NULL`; the leader can ask questions without approving, and that reply does not satisfy the gate.
26. **Approve, then reject in the same round ⇒ the withdrawal takes effect.** Approve, then post `decision = 'rejected'` on the same nonce ⇒ the `approved` answer row is still in the thread (history is not rewritten), but the item's ack columns are cleared, `approval_round_count` has advanced, and the gate refuses. Revision 4 asserted the opposite here ("the ack stands"); that was only defensible while no working lever existed, and §4.3a.1 now gives the leader one. Assert both halves — the surviving row and the cleared columns — because an implementation that "fixes" this by deleting or mutating the earlier row would otherwise pass.
27. **Grace mode records nothing.** With `mail_capability_tokens_required = False`, a fully valid approval flow ⇒ `record_ack_received` refuses `tokens_not_enforced` and `ack_approver_member_id`, `ack_evidence_message_id`, `ack_enforcement_epoch` are all still NULL. Then flip the flag to `True` and re-run the ack ⇒ accepted. Proves the refusal is not merely time-shifted.
28. An item whose ack columns are populated with `ack_enforcement_epoch` NULL or `0` (hand-built fixture simulating a pre-enforcement or refactor-regressed write) ⇒ gate refuses `evidence_predates_enforcement`, even with tokens enforced and every other condition green.

Round scoping (§4.3a.1) — the rejection-recovery lifecycle revision 4 had none of:

29. **A second round's request is legal.** Round 1: `deck_request_context` with a server-derived `approval_round = 1`, leader posts `decision = "rejected"`. Round 2: the owner opens a *new* request, which the route stamps `approval_round = 2` ⇒ accepted, **no `409`**, and `deck_approve_work_item` resolves to the round-2 thread. Against revision 4 the second request is a duplicate-linkage `409`, and against revision 5 the round never advances because the leader made no second call — this is the blocker-2 test, and the owner calls **only** `deck_request_context` to recover.
30. **Two requests, two rounds, no ambiguity.** With round-1 and round-2 requests both present on the item, `deck_approve_work_item(work_item_id, dispatch_nonce)` for round 2 resolves to exactly one thread. Test 21's "two matching requests *from the same owner* ⇒ `409`" still holds *within* a round — assert both, since a fix that stops filtering by round entirely would pass one and fail the other.
31. **One rejection clears and increments, with no second call.** Record a valid approval for round 1, then post exactly one `deck_approve_work_item(decision="rejected")` and call **nothing else** ⇒ `approval_round_count` becomes 2, and `ack_approver_member_id`, `ack_evidence_message_id`, `ack_received_at`, `ack_enforcement_epoch`, `ack_approval_round` are **all** NULL, and `last_nudge_at` is NULL. The nonce is **unchanged** (§4.3a.1 — clearing it would deadlock the next round exactly as it would on handoff). "Nothing else" is the assertion that distinguishes revision 6 from revision 5: this test must be written so that inserting a `revision_requested` report would be a *change* to it, not a prerequisite of it.
    31b. **Branch A lands in one commit (below the cap).** `max_approval_rounds = 3`, item at round `1`, so the rejection opens round 2 and does **not** escalate. Assert through a raw `text()` query — not the identity map, since a rolled-back-but-still-in-memory object reads correctly from the session and would make this test pass while proving nothing — that `approval_round_count == 2`, all five ack fields are NULL, `last_nudge_at` is NULL, the nonce is unchanged, `dispatch_status` is still `dispatched`, and the `answer` row carrying `decision='rejected'` exists. Also assert `escalate` was never called: monkeypatch it and assert zero calls. Revision 6's version of this test asked for an item "one round below the cap" whose rejection *also* escalated — a fixture that cannot exist under §4.2a's arithmetic, which is why it is replaced.
    31b-1. **Branch B is durable when the broadcast fails (at the cap).** `max_approval_rounds = 3`, item at round `3`, `_send_escalation_broadcast` monkeypatched to raise. This is the failure-injection test the sixth review required, and it is the one that fails against revision 6's ordering. Re-read the row in a **fresh session** (a new `async_sessionmaker` checkout, not just raw SQL on the same session — the point is what survived the commit boundary) and assert **all** of: `dispatch_status == 'escalated'`, `escalation_reason == 'approval_rounds_exhausted'`, `approval_round_count == 3` (**not** 4 — the counter stops on the last real round), the ack fields are **still set** (branch B keeps them deliberately), and the `answer` row exists. Then assert the consequence, because the status alone is not the hazard: with `dispatch_status == 'escalated'` the item is **not** selected by the monitor's query (`dispatch_status == "dispatched"` and `pr_number IS NULL`, `github_dispatch_service.py:738-746`). Against the wrong ordering the measured on-disk state is `dispatch_status='dispatched'`, `escalation_reason=None`, `ack_received_at` **set** — so the monitor selects it, `_ack_satisfied` returns `True` (`:902-912`), the ack gate at `:778` is skipped, and a rejected plan is treated as an approved one.
    31c. **A rejection against an already-escalated item refuses.** Item `escalated` with `escalation_reason = "leader_offline"`, leader posts a rejection ⇒ `409 item_escalated`, `approval_round_count` unchanged, `escalation_reason` still `leader_offline`, and **no decision row written**. Measured against today's code the counter advances to 2 and the reason is silently preserved with no broadcast, so this test fails without the guard.
32. **The gate refuses after a withdrawal.** The item from 31, CI-green with a fresh head ⇒ no auto-merge, and the fallback note starts with `"Auto-merge blocked"`. This is the consequence test for 31; a clear that happened but left the gate passing would be invisible without it.
33. **Round mismatch alone refuses — the belt-and-suspenders test.** Hand-build an item with every gate condition green, valid approver columns, `ack_enforcement_epoch = 1`, but `ack_approval_round = 1` while `approval_round_count = 2` ⇒ refuses `stale_round`. This fixture is the state a *forgetful* `advance_approval_round` would leave behind — or a reordered one whose increment persisted while its clears rolled back — so it tests the second guard independently of the first. §4.5's whole argument for having two guards rests on this test existing.
34. **Approval in the current round still merges.** The item from 31, then a valid round-2 approval ⇒ `ack_approval_round == 2 == approval_round_count`, and it merges. Proves the round check refuses staleness rather than everything.
35. An ack attempt against a **round-1** thread after the round has advanced to 2 ⇒ `409 stale_round`, distinguishable in the response detail from `stale_nonce` and `no_linkage`. All three refusals exist because they need different operator responses: re-dispatch, wait, or open a new request.
36. `approval_round` NULL in a request's payload (a pre-upgrade or hand-posted row) ⇒ treated as `no_linkage`, not as round 0 and not as "any round." Fail closed on an unstated round.
37. **The cap still escalates, and the counter stops at a real round.** From a dispatched item (round 1, `max_approval_rounds = 3`), reject three times ⇒ rounds 2 and 3 open, the third rejection escalates `approval_rounds_exhausted`, **`approval_round_count == 3` and not `4`**, and the ack columns are **not** cleared on the escalating call (§4.3a.1 — the operator needs to see what was last approved). The `== 3` assertion is what separates the two candidate cap forms in §4.2a; without it both pass.
    37b. **Dispatch opens round 1.** A freshly dispatched item has `approval_round_count == 1`, set in the same commit as `dispatch_nonce` by the prepare-attempt step (§4.2a). Against revision 5 it is `0`, and every round-scoped test above would then be asserting a round the code never opened.
    37c. **Retry closes the round.** `reset_for_retry` on a live item leaves `approval_round_count == 0`, and a `deck_request_context` against it refuses rather than being stamped round 0 — `0` means *no round is open* (§4.2a, §4.3 rule 3).
    37d. **A caller cannot pre-date a round.** `POST /agent-mail/messages` with `kind="context_request"` and a payload `approval_round = 5` on an item whose count is `1` ⇒ `403 approval_round_mismatch`, no row written. Then the same post with `approval_round = 1` ⇒ accepted. Proves the rule refuses disagreement rather than refusing the key, and that a future shim sending an honest value is not broken by it.
    37h. **The attempt is durable before the brief is composed — the blocker-1 test.** This is an **integration-level** test that drives the real pending-dispatch method with a mocked launcher and a mocked mail send, *not* a unit test of `_dispatch_brief`. Capture the brief actually passed to both delivery points (`_send_dispatch_brief_to_slot`'s `brief=` and the launcher's `slot_prompt_overrides`), then re-read the item in a **fresh session** and assert: the persisted `dispatch_nonce` is non-NULL, `approval_round_count == 1`, and **the branch name in the captured brief contains that exact persisted nonce**. The spec's own §5.5.4a helper composes the expected name; assert string equality against it, not a regex. Against revision 7 the brief is composed at `:290` while the nonce is minted at `:344`, so the captured brief names `None` or an empty suffix while the row eventually holds a real nonce — and the two never agree.

    Do **not** satisfy this by constructing an item that already has a nonce and calling `_dispatch_brief` on it. That test passes against the broken ordering, which is exactly how revision 7 shipped this defect: test 12 asserts brief *content* given an item, and can never observe *when* the nonce arrived.
    37i. **Preparation is committed before delivery, not merely assigned — and the second session must exercise both readers.** Same fixture, but the mocked `_send_dispatch_brief_to_slot` opens a **second session** on the same database mid-dispatch, i.e. before `launcher` is called and long before the loop's own commit at `:333`. Assert two things from that session, not one:

    - **The context reader.** `deck_request_context` for the owner slot succeeds and the item it resolves carries the nonce and `approval_round_count == 1`. This is the visibility property the review named: the launched agent's first call runs in a different request and session, so an uncommitted nonce refuses `stale_nonce` on a legitimate first call.
    - **The owner-only reader.** An owner-only report — `deck_report_dispatch_status` with `reporting_slot_id` equal to the routed slot — is **accepted**. This is the half blocker 1 is actually about, and the context lookup does not cover it: the predicate is `report.reporting_slot_id != item.owner_slot_id` (`agent_teams.py:334`), which with `item.owner_slot_id IS NULL` refuses the true owner. A design that commits the nonce but leaves `owner_slot_id` for `:332` passes the first assertion and fails the second, which is exactly the gap revision 8 shipped.

    Assert both against the *same* second session, in the mock, before the outer call returns. A test that re-reads after `dispatch_pending` completes sees `:332`'s writes and cannot distinguish the two designs.
    37j. **A crash between preparation and launch reuses the attempt.** Prepare, then make `launcher` raise; the item escalates `launch_outcome_unknown` with its nonce **intact** (§4.2a property 4). Now clear the escalation to `pending` *without* `reset_for_retry` — simulating a redispatch of the same prepared attempt — and run the poll again ⇒ `prepare_attempt` **reuses** the existing nonce (assert it is unchanged and `token_hex` was called zero additional times) and the round is still `1`. Against an unguarded implementation the second poll mints nonce `B` while a possibly-live pane holds nonce `A`.
    37l. **A deferred retry does not strip a live attempt's nonce.** Prepare an attempt and leave a `GithubWorkspace` row with `leased_item_id == item.id`, then call `reset_for_retry`. It takes the deferred branch (`github_dispatch_service.py:56-63`): assert `retry_requested_at` is set, `dispatch_status` is **unchanged**, and `dispatch_nonce` **and `dispatch_head_ref`** are **still the prepared values**. Then release the lease, run `promote_deferred_retries` (the real method name — `complete_deferred_retries` does not exist), and assert both are now NULL. This is the pair to 37k: 37k proves the clear exists, 37l proves it is on the right side of the early return. A clear written at the top of the function passes 37k and fails only here.
    37k. **`reset_for_retry` clears the nonce, so a real retry gets a new one.** Prepare an attempt, note the nonce, `deck_retry_work_item` ⇒ `dispatch_nonce IS NULL` and `approval_round_count == 0` in a fresh session; then poll ⇒ a **different** nonce is minted and round 1 reopens. This is the pair to 37j and the two must be written together: 37j asserts preparation is sticky, 37k asserts retry breaks the stickiness. An implementation that gets either alone is broken — sticky-without-clearing reintroduces blocker 2's loop (attempt 2 reuses attempt 1's head), and clearing-without-stickiness reintroduces the crash race.

    **`reset_for_retry` does not commit.** All three callers do (`github_dispatch_service.py:97-98`, `agent_teams.py:786`, and the watcher's poll). So 37k, 37l and 37p must `commit()` before re-reading in a fresh session, or the read returns the *pre-reset* row and the test passes against a function that clears nothing. Measured while writing these — it produced a false green.
    37o. **The head does not move for the life of the attempt.** The positive companion to 11f, and the one that pins the *column* rather than the handoff. Prepare, hand off, and assert `dispatch_head_ref` still equals the prepared value. Then set it NULL and assert `pr_ready` refuses `stale_dispatch` rather than composing a head (§5.5.4a consequence 3). Against the composed design there is no stored head to preserve, so this test is not merely red — it is inexpressible, which is the point: the property being tested is that a record exists.
    37q. **A new column is visible to the reader that needs it, through every projection in between.** Three assertions, one per layer, because the layers are three separate hand-written enumerations (§4.6). (i) `GithubWorkItemResponse` lists all six new fields — and assert the model has no `extra`-allowing `model_config`, since that is what makes the enumeration a filter rather than a default. (ii) `_work_item_response` passes all six as explicit keywords, with no `**kwargs` splat. (iii) Call the real `deck_list_work_items` with `_dispatch_request` stubbed to return a payload carrying all six, and assert the leader actually receives `ack_approval_round`, `ack_enforcement_epoch`, and `dispatch_head_ref`. The third assertion is the one that fails against revision 8, which named two surfaces and believed they covered the leader: measured, the shim's five-key re-projection (`mcp_shim/agent_mail_server.py:667-673`) drops **all six**. Assert on the value the leader receives, not on the presence of the field in the shim's source — a projection that passes the key through with the wrong value is the same defect. Pair it with the negative control: the same probe against `deck_check_inbox` needs **no** shim change, because it splats (`:269`), so a test written to the house style would find nothing wrong here.
    37p. **The clear lives in `reset_for_retry`, not in the retry route.** Two of the three callers are not the operator. Drive the **watcher's** path: an `escalated` item with a prepared attempt, then `github_watcher_service._upsert_item` with a newer `updated_at` (`github_watcher_service.py:74-79` — `_RECOVERABLE_STATUSES` plus a newer timestamp calls `reset_for_retry`) ⇒ `dispatch_status == 'pending'` **and** `dispatch_nonce` / `dispatch_head_ref` both NULL. With the clear written in the route instead, this path measures `pending` with attempt 1's nonce and head still set. Then the same for `promote_deferred_retries`, which is the third caller. Neither path has an operator in it, so neither would be found by testing the endpoint.

    37m. **A re-poll of a prepared attempt does not re-route it.** Two enabled slots with disjoint `area_labels`. Poll once under labels `['area:api']` ⇒ slot 1 is routed, prepared, and briefed; make `launcher` raise so the loop crashes after the brief is sent. Release the workspace lease, edit the labels to `['area:ui']`, and poll again. Assert, on the persisted row: `owner_slot_id`, `routing_method`, `dispatch_nonce` and `dispatch_head_ref` are **all** unchanged, and `secrets.token_hex` was called zero additional times.

    **Assert on the brief's recipient and the launch target, not only on the row.** This is the whole point of the test, and a version that checks only the columns passes against the defect. Measured against the real dispatch ordering: with the recompute the row's head still names slot 1 (blocker 2's stored column protects it) while the brief goes to slot 2, the launcher is asked to launch slot 2, and `:332` sets `owner_slot_id = 2`. So the negative control is `briefs_sent_to == [1, 1]` and `launched == [1]`; against revision 8 they measure `[1, 2]` and `[2]`. Record both with a spy on `_send_dispatch_brief_to_slot` and a fake `launcher`.

    Pair it with the durability half, because it is what makes the mis-brief permanent rather than merely wasteful: assert that after the first poll's crash a `mail_messages` row naming attempt 1's head is readable **from a separate session**. It is — `send_direct_message` commits (`agent_mail_service.py:899`) — so slot 1 was really told to push that branch, and under the recompute `:332` then makes slot 2 the owner, which refuses slot 1's report at `agent_teams.py:334`.

    37m-1. **The early-exit paths do not re-route either — four cases, and none of them needs a crash.** 37m as written reaches the re-poll through a crash, which is the rarer trigger. §4.2b's measurement is that the *ordinary queueing paths* corrupt the owner too, because each one writes the fresh candidate and commits before any override could run. Parametrize a prepared item's second poll over all four early exits and assert in every case that `owner_slot_id`, `routing_method` and `dispatch_head_ref` are **unchanged** and that the expected `pending_reason` was still recorded — the guard must still do its job, on the right slot:

    | Case | How to arrange it | `pending_reason` |
    |---|---|---|
    | fresh route returns `None` | remove the prepared owner's `area_labels` match and give the classifier no answer | *n/a* — must **not** escalate `plan_blocked`, because a prepared item's routing is not in question |
    | fresh candidate is busy | `slot_is_busy(B)` false, `slot_is_busy(A)` true | `queued_slot_busy` — on **A**, the real owner |
    | fresh candidate is ambiguous | two live sessions on B, none on A | must **not** fire; the note is about B, who is not the owner |
    | no workspace free | no dispatchable `GithubWorkspace` row | `queued_no_workspace` |

    The first row is the one that catches the most tempting wrong implementation: keeping `route_item` and merely overriding its result leaves the `owner_slot_id is None` check at `:255` in the path, so an item whose labels no longer match anything escalates `plan_blocked` **even though it is already routed, prepared and possibly running**. Measured negative controls, both from §4.2b: the busy case reports `through:1` (guards cleared B, the launch takes busy A), and the no-workspace case ends with `owner_slot_id = 2` while `dispatch_head_ref` still names slot 1.

    37n. **A partially prepared row fails closed.** Prepare an attempt, then tear exactly one member of the record — `dispatch_nonce = NULL`, or `dispatch_head_ref = NULL`, or `approval_round_count = 0`, or **`owner_slot_id = NULL`**, or **`routing_method = NULL`** — and poll. Each case raises `PartiallyPreparedAttempt` naming which members were present, and mints **no** replacement nonce, sends **no** brief and calls the launcher **zero** times. Parametrize over all five: a guard written as `if item.dispatch_nonce is None: prepare(...)` passes the nonce case and silently repairs the rest, which is the failure mode the guard exists to prevent. Do not assert on the exception's message text; assert on the raised type and on the nonce being unchanged, so the test survives a reworded error.

    The last two cases are the ninth review's first blocker and must be torn the way production tears them, not with an `UPDATE`. Add a sixth case that **deletes the owner slot** through the real `agent_team_service.delete_slot` and asserts the FK did the tearing: `owner_slot_id IS NULL` with the nonce, head, round and `routing_method` all intact, and `attempt_state` raising. Measured:

    ```
    [fixture] PRAGMA foreign_keys = 1
    delete_slot(1) -> preset response, slots=[]
    after DELETE of the owner slot (ondelete='SET NULL'):
        slot rows remaining = 0
        owner_slot_id  = None
        routing_method = 'label'
        dispatch_nonce = '5afdad59045a4edb'
        head           = 'deck/slot-1/issue-42-5afdad59045a4edb'
        round          = 1
        revision 9's three-field guard -> PREPARED
        the asymmetric model           -> PARTIAL
    ```

    A hand-written `owner_slot_id = None` proves the classifier; the real `DELETE` proves the *mechanism*, and it is the mechanism the review disputed. The column carries `ForeignKey("agent_team_slots.id", ondelete="SET NULL")` (`models/database.py:259-261`) and `delete_slot` is a plain `await db.delete(slot)` (`agent_team_service.py:384-392`) — it never touches the work item, so the FK is the entire mechanism.

    **The fixture has a trap, and it is an ordering trap, not a missing-line trap.** SQLite's `foreign_keys` default is **off** and the pragma is per-*connection*. Production sets it from a `"connect"` event listener (`app/database.py:28-34`), so it fires for every connection. An in-memory test engine uses `StaticPool` — exactly **one** connection, opened on first use — so a listener registered *after* `create_all` attaches to an engine whose only connection already exists and never runs. Measured, that is not a test that fails; it is a test that passes wrongly:

    ```
    [fixture] PRAGMA foreign_keys = 0     (the default, or a late-registered listener)
    same delete: slot rows remaining = 0   <- still deleted
                 owner_slot_id       = 1   <- DANGLING, not NULL
    ```

    A dangling `owner_slot_id` reads as `PREPARED` under **both** classifiers and then fails the `slots_by_id` lookup, so the test would exercise §4.2b.1's not-in-preset branch while claiming to exercise the deleted-owner one. Assert the pragma's value inside the fixture rather than trusting that the listener was wired.

    37n-1. **One torn row does not stop the batch — the blast-radius test.** Two `pending` items in one scope: item 41 torn, item 42 healthy and unprepared, ordered so 41 is examined first (`:232` orders by `created_at, id`). Poll once and assert **all** of: 41 is `escalated` with its nonce **kept**, 42 is `dispatched`, and `dispatch_pending` **returned normally** rather than raising. Then the negative control in the same test, with the per-item `try` removed: the call raises, 42 is **still `pending`** and was never examined. Measured both ways:

    ```
    Solution 2 verbatim (no per-item catch):
        raised out of the poll: PartiallyPreparedAttempt
        items reached after the torn one: 0
        still pending: [41, 42]  <- 42 never examined

    with a per-item catch around attempt_state:
        items reached after the torn one: [42]
        torn row: status='escalated' reason='plan_blocked' nonce kept=True
    ```

    37n-2. **The blast radius is the scope, not the batch — the scheduler-level test.** The one above bounds the damage inside `dispatch_pending`; this one measures what an escape costs, and it is the reason the per-item catch is a requirement rather than a nicety. Drive the **real `run_repo_once`** with `dispatch_pending` replaced by a stub that raises `PartiallyPreparedAttempt`, and record which passes ran:

    ```
    run_repo_once with a raising dispatch_pending:
        calls that ran : ['poll_scope', 'dispatch_pending']
        propagated out : PartiallyPreparedAttempt
    ```

    Assert the recorded call list equals exactly `['poll_scope', 'dispatch_pending']` — so `monitor_dispatched`, `remind_held_leases` and `process_scope` are all provably skipped — and assert that `run_repo_job` swallows the exception (`github_dispatch_scheduler.py:96-97`), which is what makes the stall silent. Write it as a **regression guard on the scheduler**, not on the dispatch service: it stays valid for any future raise out of any pass, and it is the test that would have caught this design if the per-item catch were ever removed.

    37n-3. **A prepared item whose owner is disabled is neither re-routed nor launched.** Prepare for slot 1, disable slot 1 through the real `update_slot`, and poll. Assert: `dispatch_status == 'escalated'`, `escalation_reason == 'prepared_owner_unavailable'`, `status_note` naming slot 1 by `display_name` **and** containing the attempt's head, `owner_slot_id` still 1, nonce/head/round unchanged, the launcher called **zero** times, no brief sent, and — the assertion that separates this from a release-and-escalate implementation — the workspace row still has `leased_item_id == item.id` with a non-NULL `lease_token`.

    **The second half of this test is now the opposite assertion, and the change is the point.** Revision 10 ended it with "re-enable the slot and poll again: the item must dispatch on the same attempt." No code does that, so as written the test would have failed on the first honest implementation and been "fixed" by weakening it. Replace it with the negative that is true of PR1 and is worth pinning forever: **re-enable slot 1, poll again, and assert nothing happened** — `dispatch_status` still `escalated`, the launcher still called zero times, `secrets.token_hex` still never called a second time. Then in the same test call §4.2b.2's `resume-attempt` and assert the dispatch happens on the same attempt. Two polls and one explicit action, because the resume is an action and not a consequence.

    That ordering is what makes the test discriminating. A pre-pass implementation inside `dispatch_pending` passes the "resume then dispatch" half and **fails** the "re-enable alone does nothing" half — which is the outcome we want, since §4.2b.1 measured that a mid-loop promotion briefs the agent with `"(No issue body provided.)"`. The test is therefore not merely checking the feature; it is rejecting the wrong architecture for it.

    Two negative controls belong in this test, because both wrong implementations look right:

    - **`skipped_disabled` is not a launch failure.** Without this branch, the loop launches a disabled slot and the real launcher answers, measured with the exact request the loop builds at `:306-316`:

      ```
      real launch() on a DISABLED slot -> 1 result item(s)
          slot=1 action='skip' status='skipped_disabled' tmux_target=None
                 message='Slot is disabled'
      _LAUNCH_FAILED_STATUSES = ['blocked', 'blocked_agent_mail_not_configured',
                                 'blocked_provider_unavailable', 'failed']
      'skipped_disabled' in it? False
      -> the loop would record dispatch_status = 'dispatched' with tmux_target=None
      ```

      So the check at `:338` does not match, the loop takes the `else` at `:342`, and the item is recorded `dispatched` with `dispatched_at` set, a held lease and **no pane** — a state nothing else in the system can distinguish from a real dispatch. Assert that outcome does **not** occur. It is only reachable through the **real** launcher path (`launch:473` → `_selected_slots:1235` → `_plan_slot:677`'s `if not slot.enabled` at `:686` producing `action="skip"` at `:694` → `_execute_plan_item:544`'s `status="skipped_disabled"` at `:582`); a fake launcher returning a plausible object cannot produce it, so the test must use the real one with tmux stubbed.
    - **The disabled slot is still in `preset_slots`, and the launcher accepts it too.** `run_repo_once`'s slot query has no `enabled` filter (`:125-131`), so the fixture must build the slot list the same way — unfiltered. A fixture that filters disabled slots out turns this case into 37n-4's `owner_slot is None` case and tests the wrong branch. The same asymmetry is why the launcher never rejects the request: `_selected_slots:1244-1250` drops disabled slots only when `slot_ids is None`, and the loop always passes an explicit `slot_ids=[owner_slot_id]`, so `include_disabled` is never consulted. Nothing downstream of the dispatch loop will refuse a disabled owner on its behalf.

    37n-4. **A prepared item whose owner left the preset escalates the same reason with a different note.** The `owner_slot is None` half.

    **Seed the row directly; do not drive the handoff route.** Revision 10 reached this state by driving the real `initiate_handoff` and `accept_handoff` to a slot in another preset, on the stated ground that a test should reach a state the way production reaches it. That ground was correct *against `master`* and is self-contradictory *against PR1*, because 37r-2 in this same suite asserts the target must be a slot of the item's preset — so after PR1 the setup path 37n-4 depends on is a path 37r-2 requires to fail. Two tests in one suite cannot both pass while one uses as a fixture what the other forbids. This is the same defect class as blocker 1: a fact measured on `master` written into a PR that changes it.

    So set `owner_slot_id` to an out-of-preset slot id directly in the fixture and say why in a comment. It is a **less** faithful setup and a **correct** one, and the faithfulness it gives up is already covered: 37r-2 case (ii) is the test that proves the route cannot produce this state, which is a stronger statement about production than reaching it through the route would have been. Assert `escalation_reason == 'prepared_owner_unavailable'`, `status_note` containing "not a slot of this scope's preset" and **not** the word "disabled", the launcher called zero times, and the lease still held.

    The state remains reachable in production for the reason §4.2b.1 gives — an item handed off before PR1 ships, a reparent by operator SQL, a preset edit — so the branch is not dead code guarded by a test of an impossible state. What changed is that `initiate_handoff` stops being one of the routes to it. Measured setup, as `master` produced it, kept because it is the evidence that the state is real:

    ```
    after handoff of a PENDING, PREPARED item to slot 2 (preset 2):
        dispatch_status = 'pending'   <- still pending, still polled
        owner_slot_id   = 2     (was 1)
        routing_method  = 'reassigned'
        head            = 'deck/slot-1/issue-42-d2fb1f4216212745'
        preset_slots for this scope: [1]
        owner resolvable in preset_slots: False
    ```

    Do **not** write this test by reparenting a slot (`slot.preset_id = other`) either. Measured: neither `AgentTeamSlotUpdate` nor `TeamGithubScopeUpdate` exposes `preset_id` and `agent_team_service.py` never assigns it post-construction. Reparenting and direct seeding both produce the state by fiat, but they are not equally honest: seeding `owner_slot_id` writes the exact column the branch reads, whereas reparenting writes a *different* column and relies on a chain of inference to arrive at the same place — so a future change to `preset_slots`'s construction could silently stop the fixture from producing the state while the test kept passing for the wrong reason.

    37n-5. **The escalation is durable when the broadcast fails, and the lease survives it.** `_send_escalation_broadcast` monkeypatched to raise; re-read in a **fresh session** and assert `dispatch_status == 'escalated'`, `escalation_reason == 'prepared_owner_unavailable'`, the note in `status_note`, the nonce and head intact, and `leased_item_id` still the item's. Then the control that makes the trailing commit load-bearing: with the helper's `await db.commit()` removed, the same fresh session reads `dispatch_status == 'pending'` and `escalation_reason IS NULL`, and the next poll repeats the whole cycle. Both transcripts are in §4.2b.1. The mail-failure half matters because `escalate` calls `db.rollback()` on that path (`:1013-1018`) — a rollback in the middle of an escalation is exactly the kind of thing that quietly takes a neighbouring write with it, and here it must not.

    37n-6. **The lease is bounded even though the dispatch loop does not release it.** The claim §4.2b.1 rests on, tested rather than asserted. On an item escalated `prepared_owner_unavailable` with its lease held: (i) `remind_held_leases` returns `1` and sends a `Release needed` message — `'escalated'` is in `_RELEASABLE_STATUSES` (`:29`); (ii) `reclaim_stale` with the lease aged past `github_stale_lease_backstop_seconds` releases it **only** when `_owner_process_is_alive` is false, and the item's nonce is untouched afterwards; (iii) with `_owner_process_is_alive` true it releases nothing. Then the two caveats, both of which are the test's real value because both weaken the bound:

    - **`kind='primary'` is never reclaimed.** Identical aged-and-dead conditions, `kind='primary'` ⇒ `reclaimed 0`, lease still held (`reclaim_stale:292-293`). Assert it, and assert the reminder still fires — for a primary workspace the reminder plus an operator force-release is the entire bound.
    - **The reminder is counted even when nobody receives it.** With the owner slot having no `MailTeamMember`, `remind_held_leases` returns `1` and **zero** messages are sent, because `notify_owner` returns silently when `_owner_member` is `None` (`:1052-1053`). Assert the count and the empty outbox together. This is the population the whole section is about, so "the owner was reminded" is not a safe reading of that return value — and it is why §4.6's operator visibility is part of this work.

    37n-7. **The do-not-retry caution reaches the operator through `note`, not through `owner_may_be_active`.** Assert that a `prepared_owner_unavailable` escalation's broadcast body contains the caution **and** that `payload['owner_may_be_active']` is `False`. The second assertion is the interesting one: it pins that the caution arrived through the ungated `note` append (`:1110-1111`) rather than through the flag, so a later change to the flag's definition cannot silently remove it. Measured, the flag cannot fire here at all — `escalate` requires `dispatch_status == "dispatched"` (`:996-998`) and every escalation from inside the dispatch loop is on a `pending` row by construction:

    ```
    pending  + owner set    : owner_may_be_active=False warning present=False
    dispatched + owner set  : owner_may_be_active=True  warning present=True
    pending  + owner NULL   : owner_may_be_active=False warning present=False
    ```

    37n-8. **A `pr_opened` report does not clear this escalation.** The recovery-path test, modelled on 46d, and it matters more here than there because the plausible sender is the *previous owner's still-live pane* — the exact thing §4.2b.1 keeps the attempt for. On an item escalated `prepared_owner_unavailable`, `report_pr_opened` must **raise**, with `dispatch_status` still `escalated`, `escalation_reason` still set and `pr_number` still NULL. Measured as designed:

    ```
    _PR_OPENED_RECOVERABLE_ESCALATIONS = ['brief_unread', 'leader_ack_timeout',
        'leader_offline', 'owner_idle_timeout', 'owner_offline', 'plan_blocked']
    'prepared_owner_unavailable' on the list? False
    report_pr_opened -> refused: "pr_opened is only valid for dispatched work items,
                                  or escalated items with a recoverable reason..."
    on disk afterwards: status='escalated' reason='prepared_owner_unavailable'
                        pr_number=None
    ```

    Write the mutant half in the same test, because the consequence of one name added to a frozenset is not guessable from reading `report_pr_opened`:

    ```
    MUTANT (prepared_owner_unavailable added to the recoverable set):
        dispatch_status   = 'verifying'      <- left 'escalated'
        escalation_reason = None             <- CLEARED
        pr_number         = 7
        owner_slot_id     = 1   (slot enabled=False)
        dispatch_nonce    = 'c7fa4db8a2eaa573'
        team notified     = []
    ```

    `verifying` is not a parking state — it is the **auto-merge pipeline's** input (§5.6). So the mutant does not merely lose an escalation: it silently promotes an item whose owner is gone into the path that can merge it, on the word of a pane nobody has confirmed is authorized to speak for it, and notifies no one (`team notified = []`). Assert `escalation_reason is None` and `dispatch_status == 'verifying'` against the mutant and the refusal against the design, so the test states both what must happen and what it is preventing.

    37n-9. **§4.2b.2's resume transition preserves the attempt, and the wrong implementations are named.** The test for the endpoint blocker 5 adds. Seed an item escalated `prepared_owner_unavailable` with a held lease, `approval_round_count = 3`, a `last_verified_sha`, and its owner slot disabled.

    First the two refusals, because an endpoint that resumes unconditionally passes every positive assertion below:
    - owner still disabled ⇒ `409 owner_still_unavailable`, and the row is **unchanged** — assert `dispatch_status == 'escalated'`, not just the status code. Without the cause check the item flips to `pending`, gets re-escalated by the next poll, and the operator sees a row that oscillates.
    - a **different** escalation reason (use `plan_blocked`) ⇒ `409 not_a_resumable_attempt`. This is what stops the endpoint becoming a general un-escalate button, which is the shape it will drift into if nothing pins it.

    Then the success path, with the assertions that separate a correct implementation from `reset_for_retry`:

    | Assert | Why this one |
    |---|---|
    | `dispatch_status == 'pending'`, `escalation_reason is None`, `pending_reason is None` | the transition happened |
    | `approval_round_count == 3` | `reset_for_retry` sets this to `0` (`:66-73`). This single assertion fails against the most likely wrong implementation — calling the existing helper — and it is the reason the blocker is a blocker |
    | `last_verified_sha` unchanged | same writer, same measurement |
    | `retry_count` unchanged | a resume is not an attempt |
    | `leased_item_id == item.id` **and** `lease_token` byte-identical to before | the release-and-reacquire implementation. §4.2b.1 measured that `acquire` returns a held lease untouched, so a correct resume leaves the token alone; an implementation that released would mint a new one and run `reset_workspace` over a possibly-live tree |
    | `reset_workspace` called **zero** times | the same wrong implementation, caught at the call rather than at its trace. Assert both: the token pins the outcome, this pins the mechanism |
    | `secrets.token_hex` never called | no fresh nonce, §4.2a rule 4 |

    Then poll and assert the dispatch happens on the same attempt **and** that the brief contains the real issue body — the assertion that carries §4.2b.1's prefetch measurement into the suite. A pre-pass implementation delivers a brief containing `"(No issue body provided.)"` while every other assertion in this test passes, so this is the only assertion that distinguishes the two architectures. Take the body from the stub client and assert its presence, not the brief's length.

    Finally the liveness refusal, which needs §4.6b to be right: with the workspace's `leased_owner_pid` naming a **live** process and `reassign_to_slot_id` pointing at a different slot ⇒ `409 previous_owner_still_alive`, row unchanged. Use `os.getpid()` and this test process's real `proc_start` as the live pane, the way §4.8's other liveness tests do, and add the negative control that makes the assertion mean something — the same call with a dead pid must **succeed** — otherwise a resume that refuses everything passes.

    37n-10. **The reassignment path works, and its target is validated.** 37n-9 covers same-owner recovery and one liveness refusal; both are satisfiable by an implementation whose `reassign_to_slot_id` is dead code, which is exactly what §4.2b.2's under-specified precondition invited. The positive case first, because it is the one revision 11 advertised and never tested: owner **A disabled and its recorded pane confirmed dead**, `reassign_to_slot_id = B` where B is enabled and in the scope's preset ⇒ `200`; `owner_slot_id == B`, `routing_method == 'operator_resume'`, `dispatch_status == 'pending'`, and every attempt-preservation assertion from 37n-9's table still holding. Note what this case proves that no other test does: **A stays disabled throughout.** An implementation that reads the cause check as applying to the current owner rather than to `effective_owner` refuses this call, and refusing it is what makes the escalation's own `status_note` instruction unfulfillable.

    Then the four target refusals, each `409 invalid_resume_target`, and each is a distinct wrong implementation rather than a variation on one:
    - `reassign_to_slot_id` naming a **nonexistent** slot. Parametrize over `PRAGMA foreign_keys` ON and OFF for 37r-3's measured reason — with the pragma off the write is accepted and stores the bogus id, so a test written only with it on proves nothing about application-level validation.
    - a slot that exists but is **disabled**. The resume would then dispatch to a slot the launcher will refuse, converting an escalation the operator can act on into one they cannot.
    - a slot of a **different preset**. This is the case with no natural defence: `reassign_to_slot_id` is an integer from a request body and the FK constrains it only to *some* slot. Same-repo is the adversarial choice here for §1's reason — `_slot_matches_registration` compares provider and `repo_id`, identical across presets on one repo — so a cross-preset target is indistinguishable from a sibling by every check except the explicit `preset_id` comparison.
    - **`reassign_to_slot_id` equal to the current owner while that owner is still disabled** ⇒ `409 owner_still_unavailable`, not `invalid_resume_target`. The `effective_owner` definition makes this identical to the no-reassignment case, and asserting the *code* is what proves one definition is in force rather than two parallel code paths that agree by accident.

    Then the case that catches the hole revision 12's own first draft would have shipped, and it is the most valuable test in this block because the wrong implementation is the natural one: **a same-owner resume of §4.2b.1's second PREPARED row.** Seed an item escalated `prepared_owner_unavailable` whose `owner_slot_id` names a slot that is **`enabled` but belongs to a different preset** — the handoff-or-reparent shape, and the one an operator reaches by following that row's own `status_note`. Call `resume-attempt` with **no** `reassign_to_slot_id` ⇒ `409 owner_still_unavailable` naming the preset mismatch, and `dispatch_status` still `escalated`.

    An implementation whose cause check tests `enabled` alone returns `200` here, flips the row to `pending`, and the next poll re-escalates it with the identical reason — a silent bounce that leaves the operator re-reading a note they already followed. Assert the refusal **and** the unchanged status, because the bounce is only visible in the second assertion: the `200` looks like success. Then the positive control that stops this becoming a test that refuses everything — the same row with `reassign_to_slot_id` pointing at an enabled same-preset slot ⇒ `200`. Same stored owner, same cause, two outcomes, and the difference is whether a valid future owner was named.

    And the liveness asymmetry, which is the fail-closed direction §4.2b.2 states and nothing else checks: with `leased_owner_pid` **NULL** (or resolving to no `agent_pane_bindings` row), a **reassignment** ⇒ `409 previous_owner_liveness_unknown`, while a **same-owner** resume on the identical row ⇒ `200`. Assert both halves in one test. Same input, two outcomes, and the difference is whether the worktree is about to be handed to a second process — an implementation with one liveness rule for both cases fails exactly one of these assertions whichever rule it picks, which is the property that makes the pair worth writing.

    37n-11. **`resume-attempt` refuses every credential an agent can obtain.** §3.6a's dependency applied to PR1's own route. The caller matrix, the unconfigured `503` rows and the `hmac.compare_digest` cases are specified once, in §3.7's test 20, because force-release and the workspace projection ship in **PR0** and §2.1's rule is that a test ships with its artifact. What ships here is the same matrix aimed at `resume-attempt`, and one assertion 20 cannot make: a caller holding a valid **agent session token for the very slot being resumed to** is still refused. That is the closest thing to a legitimate agent caller this route has, and an implementer who reasons "the target slot may as well resume itself" writes exactly that bypass — which hands the item's routing decision to the party the escalation exists to route *around*.

    37n-12. **Grace mode refuses the whole of `/dispatch-status`, not a permitted subset.** With `mail_capability_tokens_required = False` and PR1 installed, drive **every** branch of §3.5a's matrix tokenlessly — `triaging`, `revision_requested`, `handoff_initiated`, `handoff_accepted`, `blocked`, `ack_received`, `pr_opened`, `in_progress`, `workspace_released` — and assert each returns `409 tokens_not_enforced`. Then the assertion that is the actual point: **no column changed on the work item or its workspace.** Snapshot both rows before and after the whole sweep and compare field by field, rather than asserting per-branch side effects; a per-branch assertion tests the branch an implementer remembered to guard, and a whole-row comparison tests the ones they did not.

    Include `triaging` explicitly even though it looks harmless, and say why in the test: it writes `status_note` (`agent_teams.py:296-300`), which is the field §4.2b.1's operator recovery instructions are delivered in (`:1038`). A tokenless caller that can overwrite `status_note` can erase the instructions telling the operator not to retry — which is how a "confidence-reducing report" turns into a destructive one, and why the blunt rule is the right rule.

    Then the ordering control: with the flag `True`, the same sweep with a **valid** session token returns the matrix's own results (`200` or the matrix's `403`s), proving the refusal is the flag's doing and not a broken route. This pair is also the executable form of §3.5's deployment ordering — if the four steps are performed out of order, this test's first half is what production would exhibit.

    Note what 37n does **not** cover on the unprepared side: `owner_slot_id` and `routing_method` may be **stale** on an `UNPREPARED` row, because `reset_for_retry` keeps them (§4.2a rule 4). A version of 37n that demanded a refusal for a retried row with a surviving owner would contradict the design — and revision 9's first draft of the guard did exactly that, making preparation raise on every genuine retry. That draft was caught by measurement, not review; the mutation rows below keep it caught. The asymmetry is the property: **torn on a prepared row, tolerated on an unprepared one.**

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
| a later `rejected` leaves the recorded approval intact (revision 4's rule) | **26, 32** |
| one request per item regardless of round (revision 4's `409`) | **29** |
| stop filtering linkage by round at all | 30 |
| rejection records a verdict but does not advance the round (revision 5's split) | **29, 31** |
| `advance_approval_round` increments the round but clears nothing (revision 4) | **31, 32** |
| `advance_approval_round` clears the ack columns but not `ack_approval_round` | 33 |
| `advance_approval_round` also clears the nonce | 31 (the next round's request cannot link) |
| escalate *before* committing the decision row, so a mail failure rolls back the clears | **31b** |
| allow a rejection on an already-escalated item | **31c** |
| branch B calls `send_message` (which commits) and then `escalate`, with no commit after | **31b-1** — the escalation is in memory only; the fresh-session re-read finds `dispatched` |
| branch B commits the escalation but rolls back the decision row on notification failure | **31b-1** — the `answer` row is missing |
| branch B clears the ack columns like branch A does | **31b-1** — the ack fields must still be set |
| branch B increments the counter past the cap | **31b-1** — asserts `approval_round_count == 3`, not 4 |
| branch A calls `escalate` at all | **31b** — asserts zero `escalate` calls |
| the notification is sent inside the same `try` as the commit, so a mail failure rolls both back | **31b-1** |
| gate compares only the columns, not the round | **33** |
| gate compares the round but treats NULL `ack_approval_round` as matching | 33, 36 |
| round scoping bypasses `max_approval_rounds` | **37** |
| keep the increment-then-`> cap` form, leaving the counter on a fictional round | **37** (the `== 3` assertion) |
| clear the ack columns on the escalating rejection too | 37 |
| dispatch leaves `approval_round_count` at `0` (revision 5) | **37b** |
| mint the nonce at `:344` beside `dispatched_at` (revisions 5, 6, and 7) | **37h** — the brief is composed at `:290` and names a nonce that does not exist yet |
| `prepare_attempt` assigns without committing | **37i** — a second session mid-dispatch sees NULL |
| `prepare_attempt` commits the nonce and round but leaves `owner_slot_id` to `:332` (revision 8) | **37i** — the context lookup still succeeds; the owner-only report is refused at `agent_teams.py:334` with a NULL owner. The first assertion alone cannot see this |
| the dispatch loop uses `route_item`'s fresh answer for a prepared item | **37m** — the brief goes to the newly routed slot while the stored head names the original, and `:332` reassigns the owner away from the slot that was already briefed |
| the reuse rule is applied to `owner_slot_id` but the brief and `launcher` still take the local variable | **37m** — assert on the brief's recipient and `slot_ids`, not only on the row; the columns are already protected by the stored head |
| the reuse rule special-cases label edits | **37m-1** — the busy-slot trigger needs no label change, no operator error and no crash: it needs a second slot that happens to be free, and it reports `through:1` |
| guard written as `if item.dispatch_nonce is None: prepare(...)` | **37n** — a row torn at `dispatch_head_ref` or `approval_round_count` is silently repaired instead of refused |
| `prepare_attempt` is called after `_dispatch_brief` rather than before | **37h** |
| preparation is unguarded, so every poll mints a new nonce | **37j** — the reused attempt's nonce changes |
| `reset_for_retry` does not clear `dispatch_nonce` | **37k** — under the three-field guard this refuses `PartiallyPreparedAttempt` on the next poll rather than reusing attempt 1's head; both are bugs, and 37k asserts the fresh nonce either way |
| `reset_for_retry` clears the nonce but not `dispatch_head_ref` | **37k, 37p** — the row is partial, so preparation refuses; a clear must cover every member of `_ATTEMPT_COLUMNS` |
| the clear is placed **above** `reset_for_retry`'s deferred-branch return (`:62`) | **37l** — a leased item's nonce is stripped while its pane is still live |
| the clear is written in the **retry route** instead of in `reset_for_retry` | **37p** — the watcher's issue-edit path and `promote_deferred_retries` both retry without an operator, and both keep attempt 1's head |
| guard on `dispatch_nonce` alone, ignoring `approval_round_count` | 37j, 37k — a half-prepared row must not read as prepared |
| the preparation guard also reads `owner_slot_id` / `routing_method` (revision 9's first draft) | **37k**, and **37n**'s note — the reset deliberately keeps those two, so `any()` is true on every genuine retry and preparation raises instead of minting |
| `accept_handoff` clears `dispatch_head_ref` along with the ack columns | **11f** — the new owner's valid push is refused with an expectation no brief ever named |
| the `pr_ready` head check recomposes from `owner_slot_id` instead of reading `dispatch_head_ref` (revision 8) | **11f** — passes without a handoff, `409`s forever after one |
| `attempt_head_ref` is called per request rather than once at preparation | **11f, 37o** — one composer called twice still gives two answers when a shared input moves |
| `pr_ready` composes a head when `dispatch_head_ref` is NULL | **37o** — must refuse `stale_dispatch` |
| `launch_outcome_unknown` clears the prepared attempt | 37j — a live pane's nonce must stay valid |
| trust a caller-supplied `approval_round` | **37d** |
| silently overwrite a conflicting caller `approval_round` instead of refusing | 37d |
| add the six columns to the response model and the serializer but not to `deck_list_work_items`'s projection (revision 8) | **37q** — the operator sees the gate's evidence and the leader, who is the approver, sees none of it |
| add `dispatch_head_ref` to the schema but not to `_work_item_response` | **37q** — Pydantic drops what the serializer does not pass |
| declare `model_config = ConfigDict(extra="allow")` instead of listing the fields | **37q** — assert the config's absence; an allow-extras model makes the enumeration stop being a filter and hides which fields are contract |
| expose only five new columns, omitting `dispatch_head_ref` | **37q** — a `head_ref_mismatch` becomes undiagnosable, since the expectation is invisible |
| the prepared-routing override is placed **after** the guards instead of before them (revision 9's proposal) | **37m-1** — the busy row reports `through:1`: the guards clear the fresh slot and the launch goes to the busy owner. The no-workspace row is the second witness: `owner_slot_id = 2` with the head still naming slot 1 |
| `route_item` is still called for a prepared item and its answer discarded | **37m-1**'s first row — the discarded answer still costs a classifier call, and the `owner_slot_id is None` check at `:255` stays in the path, so a prepared, possibly-running item escalates `plan_blocked` when its labels stop matching |
| `attempt_state` is called at the top of the loop body, above the `try` at `:285`, with no per-item catch (Solution 2 verbatim) | **37n-1** and **37n-2** — the raise is 49 lines above the try, so it leaves `dispatch_pending` entirely: no item after the torn one is examined, and `run_repo_once` skips `monitor_dispatched`, `remind_held_leases` and `process_scope` for the whole scope, every poll, silently |
| the per-item handler is `except ValueError` relying on `PartiallyPreparedAttempt`'s base class instead of a `try` that encloses the classification | **37n-1** — the base class decides nothing; the enclosing `try`'s extent does. Measured: `try covers 286-316`, the call site is at `237` |
| `attempt_state` collapsed to `all(...)` / `any(...)` over five fields | **37n** — `any()` is true on every genuine retry, because `reset_for_retry` keeps `owner_slot_id` and `routing_method`; `all()` never sees a torn deleted-owner row as partial |
| the deleted-owner case is tested with `UPDATE ... SET owner_slot_id = NULL` rather than the real `delete_slot` | **37n**'s sixth case — pins the classifier while leaving the disputed *mechanism* (`ondelete='SET NULL'`) unmeasured |
| the FK pragma listener is registered **after** `create_all`, or omitted | **37n**'s sixth case — `StaticPool` opens its one connection during `create_all`, so a late listener never fires; the delete then leaves `owner_slot_id` **dangling** rather than NULL, which reads as `PREPARED` under both classifiers and silently reroutes the test into §4.2b.1's not-in-preset branch. Assert the pragma's value in the fixture |
| `owner_slot is None or not owner_slot.enabled` collapsed into one note | **37n-3** / **37n-4** — the two notes must differ; an operator told "disabled" for a handed-off owner goes looking for a toggle that is not the problem |
| the disabled-owner branch is omitted, letting the loop launch a disabled slot | **37n-3** — `launch` returns `skipped_disabled`, which is **not** in `_LAUNCH_FAILED_STATUSES`, so the item is recorded `dispatched` with a held lease and no pane. Only the real launcher path exposes this |
| the fixture filters disabled slots out of `preset_slots` | **37n-3** — `run_repo_once:125-131` has no `enabled` filter, so the filtered fixture silently converts this into the not-in-preset case and the disabled branch goes untested |
| release the workspace on `prepared_owner_unavailable` (copying §4.2a's `ValueError` branch) | **37n-3** — a live pane's worktree is handed to another item. §4.2a releases because that path has already failed to launch; this one may not have |
| the helper omits its trailing `await db.commit()` | **37n-5** — `escalate` does not commit, so a fresh session still reads `pending` and the next poll re-escalates forever: a busy loop with a log line |
| the do-not-retry caution is carried by widening `owner_may_be_active` instead of by `note` | **37n-7** — the flag requires `dispatch_status == "dispatched"` (`:996-998`) and the dispatch loop only ever holds `pending` rows, so the caution disappears; widening the flag instead makes every torn-row escalation claim a live pane |
| the owner is resolved with `await db.get(AgentTeamSlot, item.owner_slot_id)` instead of `slots_by_id` | **37n-4** — a slot in another preset is *fetched successfully*, so the unresolvable case reads as available and the loop briefs and launches a stranger slot outside this scope |
| the not-in-preset case is arranged by reparenting a slot (`slot.preset_id = other`) | **37n-4** — measured unreachable through the API: no `preset_id` on either update schema, zero post-construction assignments in the service. The test would pin a state the API cannot produce while the handoff path that can goes untested |
| the continuation-context test hands the target its head from a local variable (revision 9's 11f) | **11g** — passes against a design with no agent-facing read of the head at all, which is today's state. The head must come back from the tool |
| `dispatch_head_ref` is added to the shim's five-key work-item projection instead of a new tool | **11g**'s negative control — asserts the five keys exactly, so making the new tool redundant fails loudly rather than silently |
| the claim endpoint omits `lease_token` from its payload ("a read should not hand out capabilities") | **37r-1** and **37r-4** — B can then never release the workspace nor stamp contact evidence, which is the whole defect 37r measures. The objection is answered by making it a `POST` that carries `Cache-Control: no-store`, not by withholding the capability (§4.6a) |
| the claim endpoint ships as a `GET` with `reporting_slot_id` in the query string (revision 10's shape) | **37r-7** — the identity claim lands in access logs and the bearer secret becomes cacheable; and the write that repairs blocker 4 has nowhere to live in a nullipotent verb |
| rotate `lease_token` in `accept_handoff` instead of delivering it | **37r-1** — rotation invalidates the only copy of a capability with no channel to the new owner; the two-consumer half shows the retained token already grants the ex-owner nothing, so rotation protects against nothing |
| the claim endpoint checks `handoff_target_slot_id` instead of `owner_slot_id` | **37r-5**'s positive control — the target column is NULL after `accept_handoff` (`:704`), so a target-based check refuses the very caller it exists for |
| the claim endpoint authorizes on the body's `reporting_slot_id` instead of the derived slot | **37r-5** case 2 — a same-repo sibling with a valid token of its own claims A's id and is accepted; `_slot_matches_registration` gives the pre-PR0 path no discriminating power at slot granularity |
| `accept_handoff` leaves `leased_owner_pid` set to **A** instead of overwriting it with B's | **37r-4** — an alive ex-owner then pins the lease through `reclaim_stale`'s PID branch regardless of contact stamps, which is the ordered-conjunction finding |
| `accept_handoff` **clears** the three liveness columns instead of setting them (revision 11's design) | **37r-4**'s NULL-vs-dead-pid case — measured, a terminal item whose workspace has a NULL owner pid is reclaimed at **no** age: 1h, 9h and 90 days all release `0`, while the same row with a dead pid recorded releases `1`. `_owner_process_is_alive` returning `True` on NULL is fail-safe for a live B and fail-open for a dead one, and revision 11 stated only the first half. A prompt asking B to call the claim is not a bound, because making that call is exactly what a crashed B does not do |
| `accept_handoff` writes the pane identity from the **request body** rather than from `require_session_slot`'s verified binding | **37r-4** — the body is caller-supplied, so this is `sender_member_id` again ([[deck-mail-writes-are-unauthenticated]]): B can name A's pid, or any pid, and the liveness evidence becomes an assertion by the party it is meant to constrain. The pid must come from the dependency that resolved the token |
| the agent release keeps the route's owner check at `:334` and then calls `release_by_token` unchanged (revision 13's deferral) | **37r-8** case (i) — the check is true when it runs and false when the write lands, so the ex-owner destroys B's lease with a `200`. Measured. This is the mutant the whole of §4.6a.1 exists for, and note it passes 37r, 37r-1 and every other release test in this section, because they all present a *current* owner |
| the release write is keyed on the workspace row and `lease_token` but **not** on the current owner ("the token already names the acquisition") | **37r-8** case (i) — and only that case. Measured on the same post-handoff row, the token-keyed predicate matches `1` and the owner clause takes it to `0`, because no-rotation means the token is still live. Case (ii) passes against this mutant, which is why the two interleavings are specified as a pair |
| the release write is keyed on the current owner but **not** on `lease_token` (the mirror mutant) | **37r-8** case (ii) — a replacement acquisition under the same owner is destroyed. Listed because "the owner predicate is the load-bearing one" is a true sentence in the blocker's context and becomes a wrong generalization here |
| zero affected rows ⇒ `409` unconditionally (the thirteenth review's literal contract) | **37r-9** case (i) — measured, the true owner's retried release is `200` today, so this mutant turns the one path whose purpose is releasing a resource into a refusal with no correct next action |
| zero affected rows ⇒ `200` unconditionally (the over-correction) | **37r-9** case (ii), and *only* case (ii) — a caller admitted as owner and staled mid-request reads success for a release it did not perform. Revision 14 credited this kill to a late ex-owner's fresh report, which measured never reaches the write at all: it is refused at `:334`, so that case is green against this mutant, against `master`, and against the fix alike. The kill requires the interleaving, not the ordering of two separate requests |
| the idempotent no-lease case is expressed as a zero-row *result* of `release_by_owner`, with `workspace_id` made optional so the helper can be called anyway (revision 14's own table) | **37r-9** case (i)'s path-A assertion — there is no row to key the predicate on, so an implementer either passes `None` and matches nothing (making a retry a `409`) or drops the `id` clause and reintroduces the cross-row write §4.6a's force-release finding is about |
| the **path C** zero-row diagnosis reads ownership with `db.get(GithubWorkItem, item_id)` or the route's cached `item` | **37r-9** case (ii) — measured, `db.get` returns the identity-mapped pre-handoff object without querying (`again is item` → `True`, owner `1` where the stored value is `2`), so the diagnosis sees the caller as owner and the `409` becomes a `200`. The mechanism must be a scalar `SELECT`, `populate_existing=True`, or `refresh` |
| the **path A** diagnosis reads ownership with `db.get` or the cached `item` — the *same* mutant on the other branch | **37r-9** case (i-b), and only that case. Measured through the real route in the stale-owner interleaving: the fresh scalar reads `2` and returns `403`, the cached read reads `1` and returns **`200`**. Listed separately because paths A and C are separate control flow, so a fix applied to one leaves the other open — and revision 15 required freshness on both while giving path A no case in which cached and stored disagree |
| the path-A stale-owner case is built by committing the handoff **before** the request instead of interleaving it | **37r-9** case (i-b)'s branch-arrival assertion — measured, the seeded version is refused at `:334` having never reached the lookup, because a fresh session's `db.get` at `:291` queries and binds the *stored* owner. And after §3.5a that refusal is the same `403 not_item_owner` the case asserts, so the seeded test is green against the cached diagnosis, against no diagnosis, and against `master`. This is revision 14's 37r-9 defect reproduced on the branch introduced to fix it |
| path A's stale-owner outcome is folded into case (i), asserting `200` and a cached/stored disagreement in one case | **37r-9** cases (i) and (i-b) *as a pair* — the two conditions are unsatisfiable together: a stored owner that differs from the cached caller must return `403`, not case (i)'s `200`. Revision 15 wrote both into one case, which is why the requirement at path A had no executable test |
| path A2's refusal is changed to `409 lease_changed` "so both stale-during-execution paths agree" | **37r-9** case (i-b) — measured, A2 and path C reach the identical stored state (no lease, ownership moved), and the reason they differ is the request's own history rather than the row: C lost a captured acquisition, A2 captured nothing. Collapsing them makes a `403` unreachable on a path whose answer does not depend on arrival time |
| the contact stamp's SQL predicate is treated as behaviour-preserving with respect to the Python guard it replaces | no test fails today, and requirement 8 states the change instead — measured, shipped `touch_owner_contact` **stamps** a lease whose own `lease_token` is `NULL` (its guard is mismatch-only: `workspace.lease_token is not None and ...`), while `lease_token = NULL` in SQL matches `0` rows. The direction is safe (a missing stamp only makes the backstop more willing, and only after the pid branch found the owner dead) and the shape is unreachable through `acquire`. Listed because the mirror assumption is false: `release_by_token`'s guard has **no** presence clause (`:190`), so requirement 2 changes nothing on that row — the two guards look interchangeable and are not |
| the direct non-owner's refusal is changed from `403 not_item_owner` to the write's `409 lease_changed` for uniformity | **37r-9** cases (iii) and (i-b) — two facts collapse into one code: *you are not the owner* and *the lease moved under an admitted request*. The matrix's vocabulary is what makes a `409` mean "retry with fresh state" and a `403` mean "stop". Both cases are needed: (iii) pins the refusal before the branch, (i-b) the one inside it, and after §3.5a they return the same code by different mechanisms |
| the conditional write issued **before** `release_blocker` ("check authorization first, then inspect") | **37r-8** case (i) — the window closes but the lease is cleared before the dirty-tree inspection that was supposed to block it, so `release_blocker`'s refusal arrives after the fact. The write must be last, which is requirement 2's "issued after `release_blocker` returns" |
| the tail's `touch_owner_contact` gate left reading the `item` bound at `:291` | **37r-10** case (i) — measured, an admitted ex-owner stamps the lease's liveness evidence with the retained token. Note the bound: this delays a backstop reclaim rather than destroying a lease, so a reviewer weighing it against 37r-8 should not treat them as equally severe |
| the contact gate re-reads ownership *freshly* and then stamps unconditionally (revision 14's permitted option 1) | **37r-10** case (ii) — measured on Deck's own file-backed WAL engine, the handoff commits between the read and the write and A's stamp lands with `rowcount=1` on B's lease. Case (i) is **green** against this mutant, which is why the second interleaving exists and why requirement 8 no longer offers the choice |
| the contact write carries the owner predicate but not `lease_token` | **37r-10**'s third control — measured, owner-only matches `1` row and owner-plus-token matches `0` when the acquisition is replaced under the same owner, so the stamp refreshes a lease the caller never held |
| the token comparison is made null-safe — `IS`, `IS NOT DISTINCT FROM`, or an explicit both-NULL branch — to "preserve the shipped behaviour" requirement 8 documents changing | no test can fail, and that is the finding: measured across all five token pairings the two forms differ on **exactly** the both-NULL row and agree on the four reachable ones, so the rewrite is invisible to any test constructible through `acquire`. It is refused normatively instead, and for a reason bigger than the advisory stamp: requirement 1 permits a shared conditional-update helper, and measured, a null-safe helper makes a **tokenless** release match `1` row on a NULL-token lease where ordinary equality matches `0` — the owner releasing without presenting the acquisition id, gated only by the route's `:339` presence check. `IS` and the spelled-out branch are measured identical, so both are named |
| the contact write adds `id = <captured workspace_id>` and the spec credits that clause with preventing a cross-workspace stamp | no test fails, and that is the point of the note in requirement 8 — measured, `UNIQUE(leased_item_id)` (`database.py:319`) already bounds the predicate to one row (`IntegrityError` on a second claimant). The clause is harmless and mildly preferable; the *rationale* is the mutant, because a design that misnames its own mechanism will drop the constraint later and keep the sentence |
| `accept_handoff` writes ownership and liveness in **two** commits | **37r-4**'s single-commit assertion — a crash between them leaves `owner_slot_id = B` with A's pid still recorded, which is the exact stale-evidence state the transfer exists to remove, now reachable by interruption rather than by design |
| the resume transition calls `reset_for_retry` (or copies its body) | **37n-9** — `approval_round_count` 3 → 0 and `last_verified_sha` → NULL, the evidence the resume exists to preserve |
| the resume transition releases and re-acquires the lease | **37n-9** — a new `lease_token` and `reset_workspace` run over a tree the previous pane may still be writing in |
| the resume is implemented as a pre-pass inside `dispatch_pending` instead of an operator route | **37n-3**'s second half (re-enable alone must do nothing) and **37n-9**'s brief assertion — the scheduler's issue prefetch has already run, so the brief carries `"(No issue body provided.)"` and no labels |
| `resume-attempt` omits the cause check | **37n-9** — the row flips to `pending` and the next poll re-escalates it, forever |
| `resume-attempt` omits the liveness check | **37n-9**'s last case — a live previous owner's work is handed to a second agent |
| the credential helper is authorized on `lease_token` + path only (revision 10's specification) | **46r** — the ex-owner mints a fresh installation credential for the repo after handing the item off |
| one shared ancestor-depth cap for the mail and credential paths | **46r** — raising it for git silently loosens `_pids_related` on mail registration, which needs 0–2 hops |
| `pane_unresolved` returns a bare `403` with no depth detail | **46r** — a legitimate denied push, at a 1-hop margin, becomes undiagnosable |
| the claim response carries the token into a log line, an exception detail, or `status_note` | **37r-7** — four resting places, all reachable by a later "helpful" edit rather than by design |
| `initiate_handoff` keeps its missing owner check while the context endpoint's owner check ships | **37r-2** — the read-side check reads a column any caller can write, so shipping it alone authorizes nothing |
| the handoff target is validated by the FK alone (today's behavior) | **37r-3** — parametrized on the pragma: FKs on gives an uncaught `IntegrityError` (a `500`), FKs off *accepts* a nonexistent slot id. A test with the pragma on only would pass and prove nothing |
| `_owner_process_is_alive` is "fixed" to return `False` on a NULL pid, to close the leak the row above measures | **37r-4**'s retained guard — the predicate is not wrong; it is read by workspaces leased **before** these columns existed, whose pid is legitimately NULL, and flipping it starts reclaiming those while they are live. The leak is fixed by never leaving the columns NULL after a handoff, not by reinterpreting NULL |
| the continuation claim is treated as the moment ownership becomes truthful, with `accept_handoff` deferring the write | **37r-4** — this is revision 11's design, and it passes every assertion about the *claim* while leaving the crash-before-claim window open. The discriminating assertion is the one that never calls the claim at all: after acceptance alone, B must already be the recorded process |
| a new column added to carry the new owner's pane identity | none — and that is the point. `_owner_process_is_alive` was never wrong, it was pointed at the wrong process. Transfer the evidence; do not compensate for stale evidence with more state (§4.6b requirement 4) |
| `_RELEASABLE_STATUSES` widened to include `dispatched` to reuse the reminder as the delivery channel | **37r-6** — the release reminder then fires at agents who have not finished, and `remind_held_leases`'s own contract ("the work is already terminal for the owner", `:829-833`) no longer holds |
| the reminder's return count is read as evidence of delivery | **37r-6**'s control — returns `1`, sends `0`, and stamps the grace clock anyway. Second instance of 37n-6 |
| `resume-attempt` is "operator only" by omission from the MCP shim, with no dependency on the route | **37n-11**'s tokenless row — measured, `agent_teams.py` has **zero** non-`get_db` dependencies across all 27 `Depends(...)`, so absence is the entire current mechanism. Omitting a route from the shim decides which *tools* an agent has, not which *URLs* it can POST from a pane that has `curl` |
| `require_operator` accepts the **external-actor** token as the operator credential | **37n-11**'s self-provisioned row — measured, `POST /external/agent-mail/actors` mints a working 43-character `kind='supervisor'` token with **no credential at all**, gated only by `_is_loopback_request` (`external_agent_mail.py:76-78`), and every adversary this spec models is loopback. The temptation is real because §3.6 already uses that token for the UI |
| `require_operator` compares the token with `==` or `startswith` | **37n-11**'s prefix and trailing-byte rows — `hmac.compare_digest` is required, and a substring comparison additionally admits a token that merely *contains* the secret |
| force-release keeps `expected_lease_token` but moves behind `require_operator` | **37n-11**'s no-`lease_token`-in-the-projection assertion plus **37r-7**'s fifth resting place — authenticating the operator does not stop the operator having to *read* the agent's live bearer credential from a projection in order to call the route, and the mismatch response still discloses it. §4.6a's decision removes the requirement rather than relocating the secret |
| the force-release mismatch message keeps either token, or is "tidied" to print only the supplied one | **37r-7**'s fifth resting place — the supplied value is asserted too, because an attacker's guess echoed back confirms nothing but an operator's mistyped paste is still a secret, and the measured message prints both (`agent_teams.py:695-696`) |
| PR1 keeps a per-status grace allowlist for the "harmless" branches | **37n-12** — `triaging` writes `status_note` (`agent_teams.py:296-300`), the same field §4.2b.1's operator recovery instructions occupy (`:1038`), so the most innocuous-looking branch is the one that erases the instruction telling the operator not to retry |
| PR1's strictness is applied to `claim-continuation` only, leaving `/dispatch-status` in grace mode | **37n-12** — `initiate_handoff` has zero authorization (`github_dispatch_service.py:689-695`: four assignments and a commit), so a tokenless caller claims A, hands off to B, accepts as B, and then calls the strict endpoint with B's legitimate session. A strict read does not repair a forgeable write |
| `resume-attempt` reads the cause check against `item.owner_slot_id` when `reassign_to_slot_id` is supplied | **37n-10**'s positive case — A stays disabled throughout, which is the whole point of reassignment, so an owner-keyed check refuses the one call §4.2b.1's `status_note` instructs the operator to make |
| the cause check tests `enabled` alone instead of §4.2b.1 step 3's full predicate | **37n-10**'s same-owner cross-preset case — this is the mutant revision 12's own first draft of §4.2b.2 contained, and it is the natural implementation, because "the cause was a disabled owner" is what the *first* PREPARED row says and the second row is easy to forget. The row flips to `pending` with the cause fully intact and re-escalates on the next poll, so the test needs the unchanged-status assertion and not only the status code |
| `reassign_to_slot_id` is validated by the FK alone | **37n-10**'s nonexistent case, parametrized on the pragma for 37r-3's measured reason; and its **cross-preset** case, which no FK can catch — `_slot_matches_registration` compares provider and `repo_id`, identical across every preset on one repo ([[check-name-vs-discriminating-power]]) |
| the pre-PR1 source inspection left in 37r-4 (revision 12's state) | none — and that is the point of criterion 38. `inspect.getsource(accept_handoff)` asserting the absence of `workspace` cannot fail *usefully*: it fails for the implementer who did the work correctly. A test that only a wrong implementation passes is not a weak test, it is an inverted one |
| the previous owner's liveness is inferred from the recorded pid alone | **37n-10**'s unknown-liveness pair — a pid is not a slot; the resolution goes through `agent_pane_bindings`, and an unresolvable binding refuses a **reassignment** while still permitting a **same-owner** resume. One rule for both cases fails exactly one half of that pair whichever rule is chosen |

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
Branch:         deck/slot-6/issue-827-a3f9c1b2d4e5f607   <- §5.5.4a; numeric slot, per-attempt
Commit author:  Specialist (Deck agent) <specialist+slot6@claude-deck.local>
Trailers:       Deck-Agent-Slot: 6 (Specialist)
                Deck-Work-Item: 41
```

The branch is the one line here that is **not** a display name. The commit author, the title prefix and the trailers all carry "Specialist" because a human reads them; the ref carries `slot-6` because Git parses it, and a display name is not guaranteed to be a legal ref (§5.8 test 46q).

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

The first call is the App-level endpoint for exactly this question, so no configuration is needed and no assumption about account layout is baked in. A repo the App is not installed on returns `404` — and **what a `404` means depends on which of the two calls returned it**, which revision 5 left contradictory. §5.3a settles it.

#### 5.3a A `404` from the lookup and a `404` from the mint are different facts

Revision 5 said two opposite things about the same status code, and the fifth review is right that both cannot stand:

- §5.3: a repo the App is not installed on returns `404`, "which becomes a clear `app_not_installed` refusal naming the repo."
- §5.6a: a `404` from `GET /repos/{o}/{r}/installation` writes mode `ambient` and **proceeds** with the ambient credential — today's behavior, which §5.3 elsewhere promises not to break.

Neither sentence is wrong about its own case; they are about **different moments**, and revision 5 wrote them as though there were one rule. The discriminator is *where* the `404` occurs:

| Where | What a `404` proves | Behaviour |
|---|---|---|
| `GET /repos/{o}/{r}/installation` during **mode resolution** at lease time (§5.6a) | the App is not installed on this repo, which is a legitimate configuration and the majority case for a fresh install | write mode `ambient`, leave `github_app_installation_id` NULL, configure identity only, **proceed** |
| `POST /app/installations/{id}/access_tokens` during a **mint**, on a scope already stored `app` with an id | the installation the id names is gone — uninstalled or suspended *after* this scope resolved | **refuse.** `app_not_installed` naming the repo and the id. The helper returns nothing and the push fails hard (§5.5.6), which is the intended outcome by §5.6a's stale-`app` rule |
| `GET /repos/{o}/{r}/installation` on a scope already stored `app` | not reached — resolution does not re-run for a resolved scope (§5.6a, test 34) | n/a |

So `app_not_installed` is a **mint-time** refusal, not a resolution-time one. Revision 5's §5.3 sentence described it as the outcome of the lookup, which is the one place it must never be: refusing there would break every repo the App is legitimately not installed on, which is exactly the path §5.3 promises to preserve.

The asymmetry is not arbitrary. At resolution time Deck is *asking* whether App auth applies, and "no" is an answer it can act on. At mint time Deck has already **acted** on a previous yes — the worktree carries Deck's credential lines and the ambient helper has been evicted (§5.5.6) — so there is no ambient credential left to fall back to, and silently downgrading would change PR authorship mid-dispatch on a repo whose whole point is bot authorship.

**`github_app_bot_login` is a setting, not a discovery.** §5.6's author check needs the login. It is discoverable (`GET /app` returns the App slug, and the bot login is `<slug>[bot]`), but deriving it means one more call whose failure mode is "skip the check" — and a security check that disables itself on a network error is not a check. A setting fails loudly when wrong: the first PR report refuses with the mismatch in the message. When it is empty, the author check is skipped **on `ambient` and `unknown` scopes only** — where there is no bot to expect. On an `app`-mode scope an empty login is a configuration error and `pr_opened` refuses (§5.6's table, row 2): otherwise installing the App without setting the login would silently disable attribution on exactly the repos that require it.

**Dependencies.** App auth needs a JWT signed with RS256, which needs `pyjwt` and `cryptography`. Both are importable in the current venv (2.13.0 / 49.0.0) but **neither is in `requirements.txt`** — PyJWT is a transitive dependency of `mcp`. Relying on that is a latent break: a legitimate `mcp` release could drop it. Both must be added as explicit direct dependencies, with the extra spelled `pyjwt[crypto]`.

**Minting.** Standard two-step: sign a short-lived JWT with the App private key, exchange it at `POST /app/installations/{id}/access_tokens` for an installation token (~1h TTL). GitHub returns `expires_at`; store it.

**Caching, keyed properly.** Revision 2 said "one cached token," which contradicts per-repo installations. The cache is a dict keyed by `(installation_id, repo_full_name)` — installation because that is what the token belongs to, repo because the `repositories` narrowing below makes two tokens from one installation non-interchangeable. Each entry holds the token and its `expires_at`, and is refreshed when `expires_at - now < refresh_margin`.

Locking: **one `asyncio.Lock` per cache key**, not one global lock. A global lock would serialize dispatches across unrelated repos behind a single network round trip; a per-key lock still prevents the thundering herd that matters (concurrent dispatches on the same repo).

**Tokens are not persisted; the installation id is.** A backend restart mints fresh tokens, which is cheap and avoids storing live credentials at rest. The **installation id** is a different kind of value — a stable non-secret integer naming which installation to mint from — and revision 5's decision to keep it in memory alongside the tokens is blocker 4. It is persisted on the scope as `github_app_installation_id`, in the same commit as the mode; §5.6a has the trace and the reasoning. The in-memory id cache remains as a cache, keyed by repo, but it is no longer the only copy.

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

**There is no §5.5.3.** Revision 5 moved that section's content to §5.5.6 and left the number unused. It is not renumbered because ~51 live `§` references point into this subtree, and renumbering to close a cosmetic gap is the kind of churn that silently breaks one of them. The gap is deliberate; nothing is missing.

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
agent (in the workspace):  git push -u origin deck/slot-6/issue-827-a3f9c1b2d4e5f607
                           -> the branch named in its brief, and nothing else
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

1. Validates `head_ref` against the item's **stored `dispatch_head_ref`** — the head this attempt was prepared with and briefed with (§4.2a, §5.5.4a). Compared as a **string equality against the stored value**, not recomposed and not matched as a regex: recomposing drifts when ownership changes (the eighth review's second blocker), and a regex over `[0-9a-f]{16}` accepts a previous attempt's nonce, which is the case this check exists to catch. A mismatch is a `409`; Deck does not open a PR from a branch it did not ask for, and a *previous* attempt's nonce is a mismatch. A NULL `dispatch_head_ref` is `stale_dispatch`, not an invitation to compose one.
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

This does not exist today — measured: the client has `get_pull` (`github_client.py:98`) and no by-head or list-pulls method at all (`:36-165`), so revision 4's "reconcile" had nothing to reconcile with. The `head` parameter must be qualified `owner:branch`; unqualified it silently matches nothing, which would make the reconciliation a no-op that always says "no PR exists" — a failure mode indistinguishable from the bug it fixes.

**Why `state="all"`, corrected.** Revision 5 justified it with *"a closed PR on the same head still blocks creation with `422`."* That is an **unverified empirical claim about GitHub**, and it should not be load-bearing: GitHub's REST reference documents `422` for the create endpoint only as *"Validation failed, or the endpoint has been spammed"* and says nothing about duplicate head/base, open or closed. Confirming it would mean creating PRs against a live repo, which is not something this spec's verification budget should spend. So the reason is restated from facts this design does control:

1. A **merged** PR on the item's head must be found, or §5.5.4a cannot reconcile the item to `merged` — and `state="open"` hides every merged PR by definition.
2. A **closed-unmerged** PR on the item's head must be found, because §5.5.4a escalates on it rather than creating a replacement. Not seeing it is what makes Deck re-create a PR a human deliberately closed.

Both hold whether or not a closed PR blocks creation, and §5.5.4a's ladder is written so that the answer to that question changes nothing. If the claim happens to be true, step 5's post-`422` reconciliation absorbs it; if false, no branch is reached that depended on it.

The `pr_ready` handler becomes:

| Step | Action | On match |
|---|---|---|
| 1 | `item.pr_number` set? | return it — the cheap path, no network call |
| 2 | `list_pulls_for_head(head=f"{owner}:{head_ref}", base=scope base)` | **classify the match by state before doing anything with it — §5.5.4a.** Only an open, unmerged match is adopted |
| 3 | more than one match | **§5.5.4a's rule**, not a blanket `409`: closed history alone must not make an open PR ambiguous |
| 4 | no match ⇒ `create_pull` | record `pr_number` |
| 5 | `create_pull` raises timeout **or** returns `422` | re-run step 2 **once**, classification included. A match means the create actually landed (or a concurrent one did) ⇒ handle it by its state. Still nothing ⇒ refuse and leave the item dispatched for the monitor. |

Step 5 is the crash-safety half: the same reconciliation runs *after* an ambiguous failure, so "the request timed out but GitHub committed" converges on the next attempt instead of diverging. Step 2 is the restart half. Both are the same call, which is why this is one method and not a special case per failure mode.

**Adoption re-runs §5.6's checks, and that is not redundant.** A PR found by head/base was not necessarily created by Deck — an agent could have opened one by hand. So an adopted PR goes through the repository and head-branch checks (§5.6) before its number is recorded, and on an `app`-mode repo through the author check too. Adoption is not trust; it is discovery followed by the same verification a report gets.

**Revision 5 wrote steps 2 and 3 as state-blind, and that is blocker 5.** "Adopt the single match" and "more than one match ⇒ `409`" are both written as though every PR on a head were equivalent. §5.5.4a is the classification they were missing; the table above now delegates to it rather than restating half a rule.

**Serialization: one item at a time.** Two concurrent `pr_ready` reports for one item can both pass step 1 and both reach `create_pull`. Deck already has the right lock for this and it needs no new mechanism: the **workspace lease token**. §3.5a requires the current lease token on `pr_ready`, and a lease is by construction exclusive to one attempt on one item (`github_workspace_service.py:127-136`). Two concurrent reports carrying the *same* token are the same agent retrying, which steps 1–5 already handle; a report carrying a stale token is refused with `409` before any GitHub call. So the exclusion is a consequence of §3.5a's authorization rule rather than an added lock.

That leaves one genuine race — the same agent's two in-flight retries with the same valid token. An `asyncio.Lock` keyed on `item.id`, held across steps 1–5, closes it. Per-item, not global: a global lock would serialize PR creation across every repo behind one network round trip, the same mistake §5.3 avoided for token minting. This is single-process only, which is correct here because Deck is a single uvicorn process (measured: PID 2206652, one worker) — and if that ever changes, the reconciliation in steps 2 and 5 is what keeps the outcome correct without the lock. The lock is an optimization to avoid a wasted `422`; the reconciliation is the correctness argument.

#### 5.5.4a A PR found on the head is not necessarily a PR to adopt

Blocker 5. §5.5.4 widened the query to `state="all"` and then handed whatever came back to a step that only knew how to adopt. Widening a query without teaching its consumer the new cases is the same seam defect as blockers 1-4: the change is correct where it was written and wrong one line later.

Three states come back, and they need three different actions.

| Match state | `state` | `merged_at` | Action |
|---|---|---|---|
| open | `"open"` | `null` | **adopt** — §5.5.4's step 2 as written. Record the number after §5.6's checks; the item advances to `verifying` (code) or `awaiting_human_review` (design) |
| merged | `"closed"` | a timestamp | **reconcile to `merged`** — `_mark_merged(item)` (`github_verification_service.py:415-419`) plus the `_notify_blocker_merged` broadcast, exactly as `_verify_item` does at `:164-168`. Record `pr_number` first, so the merged item carries the PR that closed it |
| closed, unmerged | `"closed"` | `null` | **escalate `pr_closed_unmerged`**, with the number in `status_note`. No adoption, no create, `pr_number` left NULL |
| anything else | missing, or an unrecognized value | — | **refuse.** Do not adopt, do not create, do not escalate on a classification Deck could not make; §5.5.4's step returns a `409` and the item is untouched. A `state` Deck does not recognize is a schema change, and the fail-closed default is the only safe reading |

**The discriminator is `(state, merged_at)`, not `merged` — and revisions 6 and 7 both got this wrong in a way the mocks concealed.** Both said "`merged` is the discriminator, not `state`," which is true of `GET /pulls/{n}` and **false of the endpoint reconciliation actually calls.** `GET /repos/{o}/{r}/pulls` does not return a `merged` key at all. Measured against the live API, unauthenticated, on a public repo:

```
LIST   /repos/pallets/flask/pulls?state=closed&per_page=100
       100 closed PRs; 'merged' in obj == False for ALL of them
       3 have a merged_at timestamp, 97 have merged_at = None
  #6095  state='closed'  merged_at='2026-07-30T17:05:05Z'  'merged' present: False
  #6118  state='closed'  merged_at=None                    'merged' present: False
SINGLE /repos/pallets/flask/pulls/6095
       state='closed'  merged_at='2026-07-30T17:05:05Z'  merged=True   <-- only here

LIST   keys matching /merge/:  auto_merge, merge_commit_sha, merged_at
SINGLE keys matching /merge/:  auto_merge, merge_commit_sha, mergeable,
                              mergeable_state, merged, merged_by, merged_at
```

So a classifier keyed on `pull["merged"]` raises `KeyError` on every listed PR, or — with a `.get("merged")` that looks defensive — silently classifies **every merged PR as closed-unmerged**, which sends a real merge to `pr_closed_unmerged` escalation. And revisions 6/7's mocked matches (`merged: true/false`) encode a shape that endpoint never returns, so all of tests 46b-46g would have passed against exactly that bug. This is the same failure class as revision 5's retracted `422` claim: **a confident sentence about a third party's API, written without measuring it.** Third time; the rule is now in §5.8's fixture requirement rather than only in prose.

`merged_at` is present and correctly populated in **both** shapes, so `(state, merged_at)` is the one contract that classifies list entries and single-pull responses identically. `merged` is not read at all — not even where it exists — because a helper that prefers `merged` when present and falls back otherwise has two behaviours and only one of them gets tested.

**One trap worth naming, because it is the obvious wrong substitute.** `merge_commit_sha` is **non-null on a closed-unmerged PR** — measured on #6118 above, `merge_commit_sha='9d0293cbf6c255a7ddd9ff1f68bcfd0d63613746'` with `merged_at=None`. It is GitHub's *test*-merge result, not a record that anything landed. An implementer reaching past the missing `merged` key for the nearest merge-shaped field picks precisely the one that classifies every abandoned PR as merged, and auto-merges on it. Read `merged_at`.

The existing code reads `merged` at `github_verification_service.py:164` on a `get_pull` response, where the key does exist. That call site is correct today and is **not** changed by this spec beyond routing through the shared helper — but the helper it routes into must key on `merged_at`, so the single-pull path keeps working while the list path starts working.

**Why the merged row is not just tidiness.** Measured: adopt a merged PR the way revision 5 says, on a design item, and `report_pr_opened`'s design branch (`:66-81`) sets `awaiting_human_review` and broadcasts *"Design PR #5 is ready for human review"*. The next poll reads `merged: true` and corrects the status to `merged` — but the mail row has already been sent and nothing retracts it:

```
Q5 after adoption:  status='awaiting_human_review'  mail_rows=1  ['Design PR ready for review']
Q5 after next poll: status='merged'                 mail_rows=1  ['Design PR ready for review']
```

So the self-correction is real and the notification is not corrected with it. A human is asked to review a merged PR, and the item that asked them looks fine by the time they check. Classifying at adoption costs one `if` and removes the false ask entirely.

**Why the closed-unmerged row escalates rather than recovering.** Three candidate policies, and the third is the one to take:

1. **Reopen it** (`PATCH .../pulls/{n}` with `state: "open"`). Rejected: a human closed that PR, and reopening is Deck overriding a human decision with no signal that it understood why. It also needs a client method that does not exist.
2. **Create a fresh branch and a new PR.** Rejected for the same reason plus a worse one: it produces a second PR for an issue whose first PR was deliberately abandoned, and the abandoning human gets no notification at all.
3. **Escalate with the number in the note.** Taken. A closed-unmerged PR is a *human decision Deck cannot interpret* — could be "wrong approach," could be "superseded," could be "close it and I'll redo it myself." The operator action differs per case, so the operator is who must choose. Escalation is exactly the mechanism this codebase already uses for "Deck is stuck and a human must decide."

`pr_closed_unmerged` is a new **`escalation_reason`**, not a new `dispatch_status` — `escalate()` sets `dispatch_status = "escalated"`, which already exists (`github_dispatch_service.py:1034`). It joins the eleven already in use, enumerated from the `escalate()` call sites rather than from memory: `plan_blocked` (`:256`, `:321`, `agent_teams.py:315`), `launch_outcome_unknown` (`:329`), `approval_rounds_exhausted` (`:677` — already present, and §4.2a only changes when it fires), `leader_offline` (`:752`), `owner_offline` (`:760`), `brief_unread` (`:776`), `leader_ack_timeout` (`:790`), `owner_idle_timeout` (`:803`), `retry_count_exhausted` (`github_verification_service.py:367`, `:500`), `dispatch_label_removed` (`github_watcher_service.py:113`), and `abandoned_by_operator` (`agent_teams.py:824`). So the standing "no new `dispatch_status` values" rule is respected, and the reason namespace is a flat string column with no enum to extend.

It is deliberately **not** added to `_PR_OPENED_RECOVERABLE_ESCALATIONS` (`github_verification_service.py:29-37`). Every reason on that list means *the agent got stuck and a late PR resolves it*; this one means *a human closed the PR*, which a subsequent `pr_opened` does not resolve. Recovery is `deck_retry_work_item`, which clears `pr_number` and `escalation_reason` and re-dispatches from `pending` (`reset_for_retry:64-74`) — the operator's explicit "try again," which is the right shape for a decision only they can make.

**Escalation is the report, not the recovery — and revision 6 left the recovery in a loop.** The sixth review found it: `deck_retry_work_item` returns the item to `pending` and clears `pr_number`, but the *branch name is deterministic*. `deck/<slot>/issue-<n>` is a pure function of the slot and the issue (§5.5.4 step 1, §5.6's head check), so the next dispatch pushes the same head, reconciliation finds the same closed PR, and §5.5.4a escalates `pr_closed_unmerged` again. Deck refuses to reopen it and refuses to create beside it. The documented recovery was an infinite loop through a human: escalate, operator retries, escalate again.

Revision 6 did not see this because §5.5.4a and the branch-naming rule are in different sections and neither mentions the other — the same seam this spec keeps tripping over, this time between a *policy* and a *name*.

**The fix: the head is scoped to the attempt, not to the issue.** Revision 7 got the *policy* right and the *name* wrong, and the seventh review measured why. Its shape was `deck/<slot>/issue-<n>/<nonce>` — the attempt ref as a **child** of the legacy ref. Git cannot store both: one path would have to be a ref and a directory at once. Reproduced in a bare repo, and it fails in **both** directions, which is worse than the review reported:

```
$ git branch deck/slot-3/issue-42                      # legacy ref exists
$ git branch deck/slot-3/issue-42/a3f9c1b2
fatal: cannot lock ref 'refs/heads/deck/slot-3/issue-42/a3f9c1b2':
       'refs/heads/deck/slot-3/issue-42' exists; cannot create ...

$ git push origin HEAD:refs/heads/deck/x/issue-9/aaaa1111   # child first, OK
$ git push origin HEAD:refs/heads/deck/x/issue-9            # then the parent
remote: error: cannot lock ref 'refs/heads/deck/x/issue-9': ... cannot create
 ! [remote rejected] HEAD -> deck/x/issue-9 (failed to update ref)
```

So a child-shaped attempt ref does not merely break on legacy migration — it makes the legacy name permanently unpushable in the other order too, on every clone, fork, and mirror. **The attempt ref must be a sibling, never a descendant.**

Note what the two names in that first transcript have in common: the **same parent directory**. That is the only arrangement in which Git has an opinion, because loose refs are files and a path cannot be a file and a directory at once. A legacy ref under some *other* directory coexists with the attempt ref no matter which shape the attempt ref has — which is why test 46p's positive case must use `deck/slot-3/issue-42` and not a `deck/leader/…` name, and why the version of 46p that used one would have passed against the very design this section rejects.

| | Revision 6 | Revision 7 (broken) | Revision 8 |
|---|---|---|---|
| head branch | `deck/<slot>/issue-<n>` | `deck/<slot>/issue-<n>/<nonce8>` | `deck/slot-<slot_id>/issue-<n>-<nonce16>` |
| vs. the legacy ref | is the legacy ref | **child — Git refuses** | **sibling — coexists** |
| slot identity | `<slot>`, undefined | `<slot>`, undefined | numeric `slot_id`, ref-safe by construction |
| attempt identity | none | first 8 hex of the nonce | **all 16 hex** of `token_hex(8)` |
| after a retry | same head — rediscovers the closed PR | fresh head | **fresh head** — no PR is attached to it |

Three things changed and each has a measured or structural reason:

- **Sibling, not child** — the collision above. Verified the replacement form coexists: `deck/slot-3/issue-42` and `deck/slot-3/issue-42-a3f9c1b2` both push to the same bare repo and both appear in `git ls-remote`.
- **`slot-<slot_id>`, not `<slot>`** — the seventh review is right that `<slot>` was never defined, and the reason is worse than an omission: **today's brief has no branch name at all.** `github_dispatch_service.py:410` tells the agent *"Create your own branch with `git switch -c <branch>`"* — the agent invents one. So there is no existing convention to inherit, and revision 6 and 7 both wrote `<slot>` as though there were. Using the numeric `slot_id` means no display name — with its spaces, slashes, and `..` — can ever reach a ref, and it needs no slug function, no collision rule, and no rename-stability rule. Slot display names are for humans; refs get the id.
- **The full 16 hex** — truncating `token_hex(8)` to 8 characters halves the attempt identity for no benefit. Nothing about the ref is length-constrained, and the pattern check compares against the stored nonce rather than eyeballing it.

**What `slot-<slot_id>` in the ref means — and what it deliberately does not.** It names the slot the attempt was **prepared for**: the attempt's *origin*, fixed at `prepare_attempt` and never rewritten. It is **not** a claim about who owns the item now, and it must not be read as one. A handoff moves `owner_slot_id` while `dispatch_head_ref` stays put (blocker 2, tests 11f/37o), so the moment an item is handed over the ref names one slot and the owner column names another — and both are correct, because they answer different questions. Read the ref as current ownership and you get blocker 2's permanent `409` back; read the column as attempt origin and a legitimate re-dispatch looks like a stale push.

The consequence is a rule for anything that reads the ref: **the ref is a name, not an authorization input.** Nothing may derive a slot id from `dispatch_head_ref` and compare it to a reporting slot — ownership is `owner_slot_id`, and the head is checked by equality against the stored string (§5.5.4a rule 1, §5.8 test 14). Parsing the slot back out of a ref would reintroduce exactly the recomposition blocker 2 removed, one layer down. Test 37o's assertion that the head survives a handoff is what pins this; §4.6a's continuation context is what lets the new owner *learn* the name rather than derive it.

This costs no new column and no new state, because the attempt already has an identity: `dispatch_nonce`, minted with the prepare-attempt step of §4.2a. A retry sets `dispatch_status = "pending"` (`reset_for_retry:64`), the next poll selects `pending` at `:231`, and preparation mints a **new** nonce for the new attempt. Verified `dispatch_nonce` does not exist in `app/` today, so the prepare step is the only site that will ever write it.

What the loop becomes:

```
attempt 1:  head deck/slot-3/issue-42-a3f9c1b2d4e5f607  -> PR #5  -> human closes it
            reconciliation -> closed-unmerged   -> escalate pr_closed_unmerged (#5)
operator:   deck_retry_work_item                -> pending, nonce cleared
attempt 2:  head deck/slot-3/issue-42-7d2e4f81c0b9a3e6  -> list_pulls_for_head finds NOTHING
                                                        -> create_pull -> PR #9, open
```

**Legacy refs are left alone.** A `deck/<display-name>/issue-<n>` branch from before this spec is never reused, never parsed, and never pushed to again. It is not deleted either — deleting a branch a human may still be looking at is not Deck's call. It simply stops being a name Deck knows, and because the new form is a sibling in a different second segment (`slot-<id>` vs. a display name), the two namespaces cannot collide even if a slot is literally named `slot-3`: that would produce `deck/slot-3/...` from the *display* path, which Deck no longer writes.

The closed PR keeps its head and stays exactly as the human left it. Deck neither reopens it nor creates a second PR on the same branch — the objection that killed candidate policies 1 and 2 above does not apply, because attempt 2 is not competing for attempt 1's head.

**Three consequences the plan must carry, or the fix is cosmetic:**

1. **§5.6's head check reads `item.dispatch_head_ref`** and compares for equality. It does not recompose, and it does not match a pattern. A `head_ref` carrying a *previous* attempt's nonce is a `409`, because that is an agent pushing from a stale worktree, which is precisely the case this check exists to catch. The immutability paragraph below is why equality against a stored value, rather than equality against a freshly composed one, is the whole point.
2. **The brief** must state the full attempt-scoped branch name — specifically, the value `prepare_attempt` returned and committed (§4.2a). An agent cannot derive its own nonce; it has to be told. This *replaces* the `git switch -c <branch>` instruction at `github_dispatch_service.py:410` rather than sitting beside it — two branch instructions in one brief is how an agent ends up pushing a head `pr_ready` will refuse.
3. **A pre-upgrade item with `dispatch_nonce = NULL`** has no attempt suffix, and equally a NULL `dispatch_head_ref` means *no attempt has been prepared*. Neither may silently fall back to the unsuffixed name, because that reintroduces the collision for exactly the rows most likely to have history — and, as measured above, it would also make the legacy ref unpushable. §4.1 already requires such rows to be re-dispatched before they can be acked; the same rule applies here, and `pr_ready` on such an item refuses `stale_dispatch` rather than guessing a head.
4. **The ref shape is validated at the boundary, not assumed.** `slot_id` is an integer column and the nonce is `token_hex`, so the composed name is ref-safe by construction — and the composition happens in **one** place, `attempt_head_ref(item, slot_id)`, called **once**, by `prepare_attempt`. Nothing else calls it in the request path. That is stronger than revision 8's "one shared helper, called by both the brief and the validator": a single composer called twice still produces two answers when its inputs diverge, which is exactly what happened. One composer called once, with its output persisted, cannot.

**Why the head is stored rather than composed — the eighth review's second blocker.** `accept_handoff` writes `owner_slot_id` (`github_dispatch_service.py:705`) and sends **no new brief**. Revision 8 composed the expected head on demand from the item's *current* owner, so the moment ownership moved, the expectation moved to a name nobody had ever been given:

```
slot 3 briefed:      deck/slot-3/issue-42-a3f9c1b2d4e5f607     <- pushed, PR-ready
handoff to slot 5:   nonce preserved, no new brief sent
slot 5 reports:      pr_ready(head_ref="deck/slot-3/issue-42-a3f9c1b2d4e5f607")
Deck recomposes:     deck/slot-5/issue-42-a3f9c1b2d4e5f607     <- 409, forever
```

Measured, driving the real `initiate_handoff` and `accept_handoff` against a database, with both designs implemented side by side:

```
rev8  briefed  deck/slot-1/issue-42-a3f9c1b2d4e5f607
      expected deck/slot-2/issue-42-a3f9c1b2d4e5f607
      -> 409 head_ref_mismatch, and no future brief ever names the expectation
rev9  briefed  deck/slot-1/issue-42-a3f9c1b2d4e5f607  accepted after handoff
```

and the write set that causes it, read from the function rather than assumed:

```
accept_handoff writes: ['handoff_state', 'handoff_target_slot_id',
                        'owner_slot_id', 'routing_method', 'updated_at']
```

So **the attempt's head is immutable for the attempt's lifetime.** `dispatch_head_ref` is written once by `prepare_attempt` and read by everything else; handoff preserves it for the same reason it preserves the nonce (§4.2a: the new owner was never briefed with a replacement, so changing what Deck expects strands work that was done correctly); only `reset_for_retry` clears it, because a retry *is* a new attempt and is entitled to a new head.

The general shape is worth naming, because revision 8's version of this section was not careless — it was consistent, and wrong: **a value composed from mutable state is only as stable as the least stable field it reads.** `attempt_head_ref` was correct, was called in exactly one helper, and still produced two different answers, because one of its inputs was a column another code path owns. The fix is not a better composer; it is to stop composing at read time. The existing handoff tests could not have caught this — they assert ownership and approval state and never drive `pr_ready` afterwards, which is why test 11f exists and drives the real handoff.

**A bound on the claim, so this is not oversold.** Attempt-scoping removes the *loop*; it does not make a closed PR recoverable without a human. The escalation still happens on attempt 1, and it still requires an operator to decide. What changes is that their decision now leads somewhere: one `deck_retry_work_item` produces a usable open PR instead of the same escalation a second time. It also does not help if the human closes *every* attempt's PR — but that is a human repeatedly saying no, which is not a state Deck should engineer around.

**The multiple-match rule, restated by state.** The fifth review asked that closed history not make an open PR ambiguous. Applied in order:

| Matches | Action |
|---|---|
| exactly one open, any number of closed/merged alongside | **adopt the open one.** The closed ones are history; an item's live PR is the open one |
| no open, exactly one merged (any number of closed alongside) | **reconcile to `merged`** on that PR |
| no open, **two or more merged** | **reconcile to `merged`** on the highest-numbered merged PR, and name every merged number found in `status_note`. Not a `409`: two merged PRs on one head both represent work that landed, so there is no ambiguity about the *outcome* — only about which row to cite. The highest number is the most recent. Attempt-scoping makes this rare (each attempt has its own head), but a force-push or a squash-merge-then-remerge can still produce it, and revision 6 left it undefined |
| no open, no merged, one or more closed-unmerged | **escalate `pr_closed_unmerged`**, `status_note` naming every closed number found |
| **two or more open** | **`409`**, `status_note` naming both open numbers. This is the only genuinely ambiguous case, and it is what revision 5's blanket `409` was reaching for |

So "more than one match" was never the right predicate — "more than one *open* match" is. An item retried three times has closed PRs on the head by construction, and revision 5's rule would `409` every one of them.

**Ordering, and why it is not arbitrary:** open, then merged, then closed. Read as a precedence: a live PR outranks history; a merge outranks an abandonment; an abandonment is the only remaining fact. Two open PRs is the one state no precedence resolves, because both are live and Deck has no basis to prefer either.

**Tests (offline, mocked client) in §5.8:**

38. `pr_ready` with `item.pr_number` already set ⇒ returns it, and `create_pull` is **never called**. Assert the mock, not the response.
39. `pr_number` NULL, one existing **open** PR on the head ⇒ adopted, `create_pull` never called, `pr_number` recorded, and the item advances (`verifying` for code).
40. `pr_number` NULL, **two open** PRs on the head ⇒ `409`, `pr_number` stays NULL, both numbers appear in `status_note`.
41. `pr_number` NULL, no PR ⇒ `create_pull` called exactly once, number recorded.
42. **The crash window.** `create_pull` raises a timeout, and the reconciliation call that follows returns an open PR ⇒ that PR is adopted, `create_pull` is **not** retried, and the item advances. This is the blocker-7 test.
43. `create_pull` returns `422` and reconciliation finds the PR ⇒ adopted. Same path, different trigger — an implementation can easily handle one and not the other.
44. `create_pull` raises a timeout and reconciliation finds **nothing** ⇒ `409`, `pr_number` NULL, `dispatch_status` still `dispatched` (not escalated — the monitor owns that decision).
45. An adopted PR whose `head.repo.full_name` is a different repo ⇒ refused by §5.6's check, `pr_number` NULL. Adoption must not bypass verification.
46. Reconciliation is called with a **qualified** head (`owner:branch`), a **normalized** base (`master`, from a scope whose `base_ref` is `origin/master`), and `state="all"`. Assert the call arguments; all three mistakes here silently produce "no match."

Classification (§5.5.4a) — the blocker-5 tests:

46b. **A merged match reconciles to `merged`, and asks nobody to review it.** `pr_number` NULL, one match in the **list shape** — `state: "closed"`, `merged_at: "<ts>"`, and **no `merged` key** (§5.5.4a's measurement) ⇒ `dispatch_status == "merged"`, `pr_number` recorded, `create_pull` never called, and the item never passes through `verifying` or `awaiting_human_review`. Run it on a **design** item and assert **no** `github_dispatch_design_pr_ready` mail row exists — that is the false ask measured above, and a status-only assertion misses it because the next poll repairs the status.
46c. **A closed-unmerged match escalates.** One match, `state: "closed"`, `merged_at: null`, no `merged` key ⇒ `dispatch_status == "escalated"`, `escalation_reason == "pr_closed_unmerged"`, the PR number present in `status_note`, `pr_number` still **NULL**, and `create_pull` never called. Against revision 5 this PR is adopted and the item advances with a closed PR.
46d. **The escalation is not `pr_opened`-recoverable.** On the item from 46c, `report_pr_opened` ⇒ raises (the reason is not in `_PR_OPENED_RECOVERABLE_ESCALATIONS`), then `deck_retry_work_item` ⇒ the item returns to `pending` with `pr_number` and `escalation_reason` cleared. Both halves: the wrong recovery is refused and the right one works. This test stops at `pending`, which is why it did not catch blocker 2 — see 46h, which carries on past it.
46e. **Closed history does not make an open PR ambiguous.** Three matches on one head — two closed-unmerged, one open ⇒ the **open** one is adopted, no `409`, and `create_pull` is never called. Note what this test is and is not: under attempt-scoped heads (§5.5.4a) this shape no longer arises from a *retry*, because each attempt has its own head. It arises from a force-push, a manually-opened PR on the same branch, or a pre-upgrade item. The rule is still needed and revision 5's blanket "more than one match ⇒ `409`" still fails it — but revision 6 justified this test by the retry path, and after blocker 2 that justification is wrong even though the test is right.
46h. **End-to-end recovery: a closed PR does not trap the item.** The test the sixth review required, and the one that fails against revision 6. Full cycle in one test, offline: dispatch (nonce `A`) ⇒ `pr_ready` ⇒ `create_pull` returns PR #5 ⇒ mock the PR closed-unmerged ⇒ poll ⇒ `escalated` / `pr_closed_unmerged` ⇒ `deck_retry_work_item` ⇒ `pending` ⇒ next dispatch mints nonce `B` ⇒ `pr_ready` with the attempt-`B` head. Assert three things: the attempt-`B` `head_ref` **differs** from attempt `A`'s, `list_pulls_for_head` was called with the **`B`** head and returned no match, and `create_pull` was called (total calls now 2) yielding an **open** PR with the item in `verifying`. Against revision 6 the second `pr_ready` re-finds PR #5 on the identical head and escalates `pr_closed_unmerged` a second time — assert against that specifically, so the test cannot pass by accident.
46i. **The head carries *this* attempt's nonce, not any nonce.** `pr_ready` whose `head_ref` is well-formed and attempt-scoped but carries the **previous** attempt's nonce ⇒ `409`, zero client calls, `pr_number` NULL. A pattern check written as a regex over `[0-9a-f]{8}` passes this and must not.
46j. **A NULL-nonce item refuses rather than guessing a head.** A pre-upgrade item (`dispatch_nonce IS NULL`) reporting `pr_ready` ⇒ refused `stale_dispatch`, zero client calls, `pr_number` NULL. The failure mode this prevents is falling back to a legacy unsuffixed name, which would reintroduce the closed-PR collision for exactly the rows most likely to have history — and, as §5.5.4a measures, would also make that legacy ref unpushable in the other order.
46k. **Two or more merged matches, no open.** Two matches, both `state: "closed"` with a `merged_at` timestamp, numbers #5 and #9 ⇒ reconciled to `merged` on **#9**, with both numbers in `status_note`, and **not** a `409`. Revision 6 left this state undefined.
46f. **Merged wins over closed when no open PR exists.** Two matches, one with a `merged_at` timestamp and one with `merged_at: null` ⇒ reconciled to `merged` on the merged number, **not** escalated. Pins the precedence order; a classifier that checks closed-unmerged first fails here.
46g. **`state` alone is not the discriminator.** Two separate one-match cases whose `state` is identically `"closed"`, differing only in `merged_at` ⇒ one reconciles to `merged`, the other escalates. Written as a pair on purpose: any implementation keyed on `state` passes one and fails the other.

**The list-response contract (§5.5.4a's measurement) — the blocker-3 tests.** These exist because revision 7's fixtures encoded a response shape `GET /pulls` does not serve, so tests 46b-46g would all have passed against a classifier that misread every merged PR.

46l. **A merged PR in the *documented list shape* classifies as merged.** The fixture is copied from GitHub's List-pull-requests response and asserted to be that shape: `state="closed"`, `merged_at="2026-07-30T17:05:05Z"`, `merge_commit_sha` set, and **`"merged" not in pull`**. Assert the absence explicitly with `assert "merged" not in fixture` — that line is the whole point of the test, and a fixture that later grows a `merged` key must fail here rather than silently start testing the other endpoint. Result: `merged`, item reconciled, no design-review mail. Against a classifier reading `pull["merged"]` this raises `KeyError`; against one reading `pull.get("merged")` it escalates `pr_closed_unmerged` on a PR that actually landed.
46m. **A closed-unmerged PR in the same shape, with a non-null `merge_commit_sha`.** `state="closed"`, `merged_at=None`, `merge_commit_sha="9d0293cb…"`, no `merged` key ⇒ `closed_unmerged`, escalated. The non-null sha is deliberate and measured (§5.5.4a): it is GitHub's test-merge result on an abandoned PR, so this test kills a classifier that substitutes `merge_commit_sha` for the missing `merged` key.
46n. **The same helper still handles the single-pull shape.** Feed `_classify_pull` a `get_pull`-shaped dict — `state="closed"`, `merged=True`, `merged_at="<ts>"` — and a second with `merged=False`, `merged_at=None` ⇒ `merged` and `closed_unmerged`. Both shapes through one helper, which is what makes the three call sites safe: reconciliation passes list entries, the verifier and `pr_opened` pass single-pull responses.
46o. **An unrecognized or missing state refuses.** Three cases: `state` absent entirely, `state="unknown"`, and `pull={}` ⇒ `_classify_pull` returns `None` and the caller **refuses** — `409`, `pr_number` NULL, `dispatch_status` unchanged, no escalation, `create_pull` never called. Asserting "no escalation" matters as much as "no adoption": failing closed means doing nothing, not escalating on a fact Deck does not have.

    46o-1. **An absent `merged_at` key refuses instead of escalating.** `{"state": "closed"}` — every other field of the list shape present, `merged_at` **not a key** ⇒ `None`, and the caller refuses: no escalation, `escalation_reason` still NULL, `dispatch_status` unchanged. Under `pull.get("merged_at")` this measures `closed_unmerged` and the item escalates `pr_closed_unmerged`, which is a *verdict* rendered on a payload the code could not read — and an operator seeing that reason has no way to tell it from a real human-closed PR. Write it with `del pull["merged_at"]` from the 46m fixture, so the test cannot pass by having built a differently-broken dict.

    46o-2. **An open PR carrying a `merged_at` timestamp refuses.** `{"state": "open", "merged_at": "<ts>"}` ⇒ `None`. Measured zero times in 105 live PRs, which is the reason to refuse rather than pick a side: the two fields disagree and Deck has no basis for preferring either. A `state`-first classifier returns `"open"` and adopts it.

    46o-3. **The tightening moved nothing else.** Assert all nine previously-committed fixtures — 46b, 46c, 46l, 46m, 46n's two, and 46o's three — still classify as their own tests require, in one parametrized case over `_classify_pull` alone. This is the test that makes 46o-1 and 46o-2 safe to add rather than merely correct: a refusal added to a classifier is one edit away from refusing something that used to work.

**The ref namespace (§5.5.4a) — the blocker-2 tests. These use real `git`, not mocks**, and that is the whole point: 46h and 46j mock GitHub's PR history and never create a ref, so neither could have caught a name Git refuses to store. `subprocess` against a `tmp_path` bare repo, no network.

46p. **The attempt ref coexists with a legacy ref *in the same directory*.** The positive case must use the legacy name that shares the attempt ref's parent — `deck/slot-3/issue-42` against `deck/slot-3/issue-42-<nonce16>` — and **not** a `deck/leader/…` name as revision 9's first draft wrote it. A legacy ref under a different directory coexists trivially: nothing in Git's ref storage relates `refs/heads/deck/leader/…` to `refs/heads/deck/slot-3/…`, so that version of the test passes against a child-shaped scheme too and asserts nothing the design is about. The collision Git actually enforces is between a ref and a *directory at the same path*, so the test has to put both names where that could happen. Init a bare repo and a work clone; create and push the legacy name; then create and push the attempt-scoped `attempt_head_ref` name for slot 3, issue 42 ⇒ both succeed, and `git ls-remote` shows **both**. Measured:

```
$ git push origin deck/slot-3/issue-42                       # the legacy name
$ git branch deck/slot-3/issue-42-a3f9c1b2d4e5f607           # created OK
$ git push origin deck/slot-3/issue-42-a3f9c1b2d4e5f607      # pushed OK
$ git ls-remote --heads origin
505a0077  refs/heads/deck/slot-3/issue-42
505a0077  refs/heads/deck/slot-3/issue-42-a3f9c1b2d4e5f607
505a0077  refs/heads/master
```

    Then the negative that motivates the design, in that same directory: creating `deck/slot-3/issue-42/<nonce>` — revision 7's child-shaped name — **fails**. Assert on the message, not merely on a non-zero exit:

```
$ git branch deck/slot-3/issue-42/a3f9c1b2
fatal: cannot lock ref 'refs/heads/deck/slot-3/issue-42/a3f9c1b2':
       'refs/heads/deck/slot-3/issue-42' exists; cannot create ...
```

    Add the reverse order as a third case, because it is the half the review did not report and it is worse. For the sibling form it must **succeed**: push `deck/slot-9/issue-7-bbbb2222cccc3333` first, then create and push the legacy `deck/slot-9/issue-7` ⇒ both OK, measured — the sibling form is order-independent, which is the property that makes it safe to deploy against a repo whose history is unknown. For the child form it fails: push `deck/x/issue-9/aaaa1111` first, then attempt the parent `deck/x/issue-9` ⇒ `! [remote rejected] ... failed to update ref`. A child-shaped scheme does not merely break on migration; it makes the legacy name permanently unpushable on every clone and mirror.
46q. **No display name ever reaches a ref.** Parametrize `attempt_head_ref` over slot display names that are hostile to Git: `"Team Lead"` (space), `"feat/x"` (slash), `"a..b"` (double dot), `"~tilde"`, `"lead\ner"` (newline), and `""` ⇒ the composed name is **byte-identical** in every case, because it is built from the numeric `slot_id`. Then assert each composed name passes `git check-ref-format --branch`. This is a pure-function test and cheap; it exists because `<slot>` was undefined through three revisions and the obvious reading — the display name — makes an invalid ref.

| Mutant | Test that must fail |
|---|---|
| idempotency keyed only on `item.pr_number` (revision 4) | **42, 43** |
| reconciliation before create, but not after a failure | **42, 43** |
| `422` treated as a hard error with no reconciliation | 43 |
| adopted PR skips §5.6's checks | **45** |
| head passed unqualified, `state="open"`, or `base` passed as the raw refspec | **46** — and 39, which then finds nothing and creates a duplicate |
| two or more open matches ⇒ pick the lowest number | 40 |
| adopt any single match without classifying it (revision 5) | **46b, 46c** |
| classify on `state` alone | **46g** |
| classifier reads `pull["merged"]` (revisions 6 and 7) | **46l** — `KeyError` on the list shape |
| classifier reads `pull.get("merged")`, treating absence as `False` | **46l** — a merged PR escalates as closed-unmerged |
| classifier substitutes `merge_commit_sha` for the missing `merged` key | **46m** — non-null on an abandoned PR |
| separate classifiers for the list and single-pull shapes | **46n** — one helper must serve both |
| unknown or missing `state` defaults to `"open"` | **46o** |
| unknown `state` escalates instead of refusing | **46o** — asserts no escalation |
| a merged match adopted and left to the next poll to repair | **46b** (the mail-row assertion) |
| a closed-unmerged match adopted and advanced | **46c** |
| `pr_closed_unmerged` added to `_PR_OPENED_RECOVERABLE_ESCALATIONS` | **46d** |
| closed-unmerged reopened via `PATCH` instead of escalated | 46c |
| "more than one match ⇒ `409`" kept for closed history (revision 5) | **46e** |
| closed-unmerged checked before merged | **46f** |
| `pr_closed_unmerged` introduced as a `dispatch_status` rather than an `escalation_reason` | §5.8 test **29-a** — `DISPATCH_STATUSES` no longer equals its expected literal |
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
| Auth | `workspace_token` = the workspace's existing `lease_token` (`github_workspaces.lease_token`, `github_workspace_service.py:130`). No new secret: the lease identifies one dispatch's exclusive hold on one checkout. **It is attempt binding, not caller identity** — see the owner check below. |
| Authorization | **three checks, all required.** (1) the lease's `scope` must own `path` — a helper asking for a repo the lease does not cover is a `403`, logged with both repos; (2) the lease must be current; (3) **the calling pane's slot must equal the leased item's current `owner_slot_id`**, derived from the kernel, never from the request. |
| Response | `{username: "x-access-token", password: <installation token>}`, minted per §5.3 for that repo only |
| Installation id | read from the lease's scope row (`team_github_scopes.github_app_installation_id`, §5.6a), with the in-memory dict as a cache in front of it. **Never resolved here** — the helper runs per git command and must not make a lookup call; a scope stored `app` with a NULL id is a fault, not a prompt to resolve (§5.6a's state table, row 3). This is the line that makes the helper survive a backend restart. |
| Refusals | lease released or expired ⇒ `403`; `path` absent ⇒ `400`; App not configured ⇒ `501`, and **no helper is configured in the first place** — see below; the mint itself returning `404` ⇒ `app_not_installed`, the installation is gone (§5.3a, and the mode is **not** downgraded) |

The helper is installed **into the workspace config, not the pane**, so it applies identically to spawn and reuse — the whole point of §5.4. The `lease_token` reaches the helper through the config line itself (`--worktree --add ... "deck-credential-helper --lease <token>"`), which lives in `.git/worktrees/<name>/config.worktree`: outside the working tree, uncommittable, and already proven not to leak into `git status`.

**Why the lease token cannot be the whole authorization, and what replaces it.** The config file is readable by anything running as that user in that worktree, and after a handoff **both** panes can read it — so the token identifies the *attempt*, not the *agent*. Revision 10 authorized the helper on the token plus the repo path alone, which means an ex-owner retaining the token from its brief could mint a fresh installation credential for the repository after handing the item off. Blocker 3 of the tenth review, confirmed. Rotating the config token does not fix it, for the reason the review gives: both panes read the same file.

So the third check derives the caller from the kernel with PR0's resolver (§3.3): peer pid from the loopback socket, walk `ppid` until a pid appears in tmux's pane list, look up `agent_pane_bindings`, and compare that slot to `item.owner_slot_id`. **The review asserts this works because "the helper process is a descendant of the tmux pane." Descendant is necessary and not sufficient — the resolver has a depth cap — so it was measured end to end, and the margin is the thinnest quantity in this spec:**

| Quantity | Measured |
|---|---|
| largest ancestor distance `_pid_is_descendant` will confirm | **7** — not the 8 that `range(8)` suggests; the equality test sits at the top of the loop body, so distance 8 is refused (`agent_mail_service.py:477-500`) |
| helper → the process that ran `git` | **5** hops: `helper → sh → git-remote-http → git → git → invoker` |
| helper → **pane**, through a realistic pane→agent→git nesting | **6** hops |
| margin | **1 hop** |
| does dropping `--lease <token>` from the config line buy a hop back? | **No.** Git runs a helper through `sh` whether or not it has arguments — 5 hops both ways. The budget cannot be widened from the config side. |

**The design consequences of a 1-hop margin, stated rather than discovered:**

1. **The fix is feasible and it is tight.** One more wrapper between the pane and `git` — `timeout`, `script`, `npm run`, `uv run`, a nested `sh -c` — exhausts the budget.
2. **Exhaustion fails closed, which is the right direction and a liveness risk.** An unresolvable caller is refused, so the failure mode is a *denied legitimate push*, never an allowed bad one. But a denied push mid-dispatch is an escalation an operator has to read, so it must be legible: the refusal is `403 pane_unresolved` naming the measured depth and the walked chain, not a generic auth failure. An implementer who returns a bare `403` here has technically satisfied the check and made the failure undiagnosable.
3. **PR2 must raise the cap, and this is the one place a shipped constant changes.** The cap of 8 was written for `_pids_related` on mail registration, where the caller *is* the pane process and the distance is 0–2. A credential helper is 6 away before anything unusual happens. PR2 raises the cap to **16** for the credential path — measured to be enough for the observed chain plus a wrapper or two — and keeps 8 for the mail path, because widening a security walk for a caller that does not need it is scope this spec does not want. A single shared constant would silently loosen the mail binding to fix a git problem.
4. **The `--lease <token>` argument stays.** It is still the attempt binding, and dropping it would cost a database lookup to find which lease covers this path — with no depth benefit, per the measurement above. It is now one of three checks rather than the only one.
5. **This is the only agent-facing surface where the resolver runs against a caller that is not the pane.** §3.3's design assumed the pane process itself calls Deck. The credential path is the exception, and the depth arithmetic is the whole of why it needed measuring rather than asserting.

If a future git or platform change breaks the walk (a reparenting `git` release, a container boundary between the helper and the pane), the fallback is **not** to trust the token: it is to issue the helper an owner-bound capability of its own at continuation-claim time and put *that* in `config.worktree`, rotated on every handoff. That is strictly more machinery, which is why it is the fallback and not the design — but it is the shape that survives losing the kernel channel, and a plan should not have to invent it under pressure.

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
| head branch | `head.ref` does not equal the item's stored `dispatch_head_ref` — the head this attempt was prepared with (§4.2a) and briefed with. Not recomposed per call; see §5.5.4a's immutability paragraph. A NULL `dispatch_head_ref` refuses `stale_dispatch` | both paths |
| author | `user.login` != the configured bot login | `pr_opened` only, and only when `github_app_bot_login` is set |
| **state** | the PR is not open — see the classification below | **both paths** |

**The state check is new in revision 7, and it is blocker 3.** Revision 6 classified PR state on the `pr_ready` reconciliation path (§5.5.4a) and in both verifier stages (§5.6b), and left the legacy `pr_opened` registration path checking *who* and *where* but never *what state*. Confirmed against source: `report_pr_opened` (`github_verification_service.py:44-86`) reads neither `merged` nor `state`. It sets `pr_number`, and for a design item sets `awaiting_human_review` and broadcasts *"Design PR ready for review"* at `:66-81` — before any verification runs.

So an agent on an `ambient`-mode repo reporting a merged or closed PR number produces the identical false broadcast §5.5.4a exists to remove. The measured evidence is the same probe, because it is the same function:

```
Q5 after adoption:  status='awaiting_human_review'  mail_rows=1  ['Design PR ready for review']
Q5 after next poll: status='merged'                 mail_rows=1  ['Design PR ready for review']
```

The next poll repairs the *status*. Nothing repairs the *mail*. And §5.6b's verifier fix does not help, because the broadcast already went out during registration — one stage earlier than anything §5.6b touches.

**Resolution: one classifier, both paths.** `report_pr_opened` already fetches the PR via `get_pull` for the repository, head, and author checks above. It classifies that same response before recording anything, using the *same* three-way function as §5.5.4a rather than a second copy:

| Reported PR state | `pr_opened` behaviour |
|---|---|
| open | today's transition, unchanged — `verifying` (code) or `awaiting_human_review` + broadcast (design) |
| merged | record `pr_number`, reconcile **directly** to `merged` via `_mark_merged` (`:415-419`) plus the `_notify_blocker_merged` broadcast. **No** design-review mail |
| closed, unmerged | **escalate `pr_closed_unmerged`** with the number in `status_note`. `pr_number` left NULL, no mail of any kind |

The plan must implement this as a shared helper — `_classify_pull(pull) -> "open" | "merged" | "closed_unmerged" | None` — called from §5.5.4a's reconciliation, from `report_pr_opened`, and from §5.6b's verifier condition. Three call sites, one rule. Two copies of a three-way branch is how the `pr_ready` path came to be classified while the `pr_opened` path was not; a shared helper is the only version of this fix that cannot drift again.

**Its input contract is `(state, merged_at)` and nothing else** (§5.5.4a's measurement). This is what makes one helper serve both response shapes: `GET /pulls` omits `merged` entirely, `GET /pulls/{n}` includes it, and `merged_at` is present and correct in both. The helper must therefore not read `merged`, `mergeable`, `mergeable_state`, or `merge_commit_sha` — the last being the trap that reads as merged on an abandoned PR.

```python
def _classify_pull(pull: dict) -> str | None:
    """Classify a PR from fields present in BOTH the list and single-pull shapes.

    Returns None when the (state, merged_at) pair is absent, unrecognized, or
    self-contradictory; every caller must treat None as a refusal, never as
    "open".
    """
    if "merged_at" not in pull:          # not the shape Deck measured; do not guess
        return None
    state, merged_at = pull.get("state"), pull["merged_at"]
    if state == "open":
        return None if merged_at else "open"     # an open PR has never merged
    if state == "closed":
        return "merged" if merged_at else "closed_unmerged"
    return None
```

`None` is a fourth outcome, not an error to swallow: a missing or unknown `state` means Deck cannot classify, and §5.5.4a's table requires a refusal rather than a guess. Returning `"open"` on an unknown state would adopt a PR of unknown status — the exact fail-open this spec refuses everywhere else.

**The helper tests `merged_at` for *presence* before reading it, and that is not defensive padding.** `pull.get("merged_at")` gives the same answer — falsy — for two facts that demand opposite handling: *this PR did not merge*, and *this payload is not the shape Deck measured*. The first is a real classification; the second is an unreadable response, and turning it into `closed_unmerged` **escalates `pr_closed_unmerged` on a PR whose status Deck never learned** — the same fail-open-shaped-as-a-verdict that §5.5.4a's missing `merged` key produced, one field over. Measured on the live API, unauthenticated: `merged_at` is present on **all 105** open and closed list entries and is null exactly on the open ones, so absence is genuinely anomalous and is safe to refuse. The second guard covers the incoherent pair: `state="open"` with a non-null `merged_at` occurs **zero** times across those 105, and under a `state`-first form it returns `"open"` — adopting a PR whose own two fields disagree.

Both corrections are pure additions of refusal. Run against every fixture §5.8 already commits to — 46b, 46c, 46l, 46m, both halves of 46n, all three of 46o, and 29e — **all nine classify exactly as before**, and only the two new shapes move, each from a verdict to `None`. That is the property to check when tightening a classifier: not that the new cases refuse, but that no existing case silently changed answer while you were looking at them.

Note the ordering requirement: classification happens **after** the repository and head checks (a PR on the wrong repo should be refused as a wrong-repo report, not reconciled as a merge) and **before** any column write or mail send. Both halves are testable and both are asserted in §5.8.

The author check is the one that shrinks. On the `pr_ready` path Deck *is* the author, so checking it verifies only that GitHub attributed a PR to the credential that created it — a tautology.

**Revision 4 then wrote a false sentence here, and the fourth review is right to call the section contradictory.** It said: *"On the `pr_opened` path App auth is by definition unconfigured, so `github_app_bot_login` is empty."* Both halves are wrong, and they are wrong in the direction that disables a security check.

- `github_app_bot_login` is a **global setting** (`config.py`, §5.3). Nothing links its value to whether *this repository* has a resolvable installation. An operator who configures App auth at all has it set, for every repo.
- App auth is configured or not **per repository**, because the installation is resolved per repository (§5.3, and this is exactly why revision 2's single `github_app_installation_id` was removed). A `404` on `tizonia/tizonia-openmax-il` says nothing about `adrirubio/claude-deck`.

So the two facts the sentence conflated are independent, and the case revision 4 declared impossible — `pr_opened` arriving while `github_app_bot_login` is set — is the *normal* case for any repo the App is not installed on. Under revision 4's reasoning an implementer would skip the author check there, or worse, treat a set `github_app_bot_login` as proof the PR should have come from `pr_ready` and refuse a legitimate report.

Stated correctly: **the author check applies on the `pr_opened` path whenever `github_app_bot_login` is set, and it must compare against the right expectation for that repo.** For a repo with no App installation, the PR is authored by the human's ambient credential, so a bot-login mismatch is *expected* and must not refuse. The check therefore keys on the repo's auth mode, not on the global setting:

| Repo auth mode (§5.6a) | `github_app_bot_login` | `pr_opened` author check |
|---|---|---|
| `app` | set | require `user.login == github_app_bot_login`. An `app`-mode repo should be using `pr_ready`; a `pr_opened` report authored by anyone else means something is wrong, and refusing is right. |
| `app` | **empty** | **refuse the report** — `409 app_mode_bot_login_unset`, `pr_number` unset. See below. |
| `ambient` | either | **skipped.** There is no bot; the author is whoever the ambient credential is. Refusing here would break the path §5.3 promises not to break. |
| `unknown` | either | **skipped**, and the report is accepted. An unresolved scope has never dispatched under App auth, so there is no bot expectation to check against. |

That table is only writable because a per-repo auth mode exists to key on. It did not in revision 4 — which is why the sentence had to invent a relationship between a global setting and a per-repo condition.

**Row 2 is new in revision 6, and it closes a partial-configuration hole the fifth review found.** Revision 5 said two things that combine badly: §5.3 said an empty `github_app_bot_login` means "the author check is skipped," and this table said App mode requires the configured bot login. An operator who installs the App but never sets the login therefore gets an `app`-mode scope on which **every `pr_opened` report bypasses attribution entirely** — the exact check this section exists to add, disabled by an unset string rather than by a decision.

Fail closed instead. On an `app`-mode scope the check is not optional, so a missing expectation is a configuration error, not permission to skip: refuse with a message naming the setting. This costs nothing in the normal case (an operator configuring App auth sets the login in the same sitting, §5.3 step 3) and it converts a silent bypass into one legible refusal on the first report.

§5.3's "when it is empty, the author check is skipped" is therefore scoped to the modes where there is no bot to expect — `ambient` and `unknown`. It is not a global escape hatch.

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

**The mode, persisted on the scope — and the id with it.** `team_github_scopes` gains **two** columns, on the existing ladder (`app/database.py:384-417`):

```python
if scope_columns and "github_auth_mode" not in scope_columns:
    await conn.execute(
        text("ALTER TABLE team_github_scopes ADD COLUMN github_auth_mode VARCHAR DEFAULT 'unknown' NOT NULL")
    )
if scope_columns and "github_app_installation_id" not in scope_columns:
    await conn.execute(
        text("ALTER TABLE team_github_scopes ADD COLUMN github_app_installation_id INTEGER")
    )
```

**Why the id must be persisted, and why revision 5 got this wrong.** Revision 5 persisted the *classification* and cached the *key that classification implies* in memory only, on the reasoning that "a backend restart mints fresh tokens, which is cheap" (§5.3). That reasoning holds for the **token** and fails for the **installation id**, because the two have different sources: a token is minted from the id, and the id comes from a network lookup that §5.6a deliberately runs **once per dispatch, at lease time** — not per git command.

Trace the restart: a workspace is leased, its scope resolves `app`, the id is cached, the worktree gets Deck's `credential.*` lines. The backend restarts. The lease is still live and the worktree is still configured, so the agent's next `git push` calls the helper — which needs an installation id, finds an empty cache, and may not re-resolve, because §5.6a's stale-`app` rule forbids re-resolution and the helper is explicitly the wrong place for a network lookup. So the push fails, and so does Deck's own `create_pull` (§5.5.2), on a workspace this spec describes as configured. The mode said "App auth works here" and nothing left could act on it.

This is the seam again: the *fact* was made durable and the *key implied by the fact* was not. A classification that outlives the data it depends on is not a classification, it is a claim. `github_app_installation_id` is therefore written in the **same commit** as the mode, whenever a lookup returns `200`, and it is what the helper mints from.

It stays nullable, and the nullability is meaningful rather than incidental:

| `github_auth_mode` | `github_app_installation_id` | State |
|---|---|---|
| `unknown` | NULL | never resolved — resolve at the next lease |
| `app` | an integer | resolved; the helper mints from this id |
| `app` | NULL | **unreachable by construction**, and treated as a fault: refuse exactly as an unresolved repo does (`queued_auth_mode_unresolved`), because an `app` scope with no id can mint nothing. A pre-upgrade row cannot land here — the migration default is `unknown` — so this covers a partial write or a hand-edited row |
| `ambient` | NULL | the App is not installed here; nothing to mint |
| `unknown` | an integer | **normalize, do not trust.** Clear the id to NULL and resolve the mode from scratch at the next lease. An id without a mode says a resolution was interrupted between the two writes, or that a hand-edit set one column and not the other (§5.9 step 1 updates exactly this pair). The id may name an installation that no longer exists, and `unknown` is the value that means *go and find out* — so the safe action discards the unverified half rather than keeping it |
| `ambient` | an integer | **normalize, do not trust.** Same treatment: clear the id to NULL, leave the mode `ambient`. An `ambient` scope must never mint, and an id sitting on one is the raw material for a helper that mints anyway should a later refactor key on the id instead of the mode. Removing it removes the possibility rather than relying on the check |

**Why this table has six rows and not four.** The sixth review found `unknown`/id and `ambient`/id undefined, and §5.9's deployment step warned about the first while this normative table did not cover it — a rule living in the deployment section and missing from the section that governs behaviour. Both now resolve the same way, and the principle is worth stating once: **the mode is authoritative and the id is derived, so when they disagree the id loses.** Normalizing rather than refusing is deliberate, and it differs from the `app`/NULL row directly above on a real distinction — `app`/NULL cannot mint at all and must fail closed, while `unknown`/id and `ambient`/id can both proceed correctly once the stale id is dropped. Fail closed when you cannot act; normalize when you can act correctly by discarding the untrustworthy input.

The token cache stays in memory, unchanged and correctly so: tokens expire within the hour, they are live credentials, and §5.3's reason not to store them at rest is sound. It is only the id — a stable, non-secret integer that identifies *which* installation, not a credential — that is persisted. Stating that split explicitly is what keeps a later reader from "fixing" the inconsistency by persisting the tokens too.

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

**Tests (offline, mocked client).** These are numbers 30-37 of **PR2's** list, which §5.8 indexes. PR1's list (§4.8) numbers from 1 independently and has its own `31b`, `37b`, `37c` — different tests. Every cross-reference in this spec carries its `§`, and the plan must keep two separate test files rather than merging the numbering.

30. Lookup returns `200` ⇒ mode `app`, **`github_app_installation_id` persisted to the returned id**, worktree gets identity **and** the three `credential.*` lines. Assert the id by re-reading the scope row, not the in-memory cache.
    30b. **The restart case — this is the blocker-4 test.** Resolve a scope to `app` with a live lease and a configured worktree, then **clear the in-memory installation-id cache** to simulate a backend restart (construct a fresh service instance, or clear the dict directly — the test must not restart a process). Now call the helper endpoint. It mints successfully, using the id read from the scope row, with **no** `GET /repos/{o}/{r}/installation` call — assert the lookup mock was never invoked, since re-resolving here is the behaviour §5.6a's stale-`app` rule forbids. Against revision 5 the cache is empty, there is no persisted id, and the mint has nothing to work from: the push and `create_pull` both fail on a workspace the spec calls configured.
    30d. **`unknown` with an id normalizes.** Hand-build `github_auth_mode = 'unknown'`, `github_app_installation_id = 4242`, then dispatch ⇒ the id is **NULL** afterwards and the mode was resolved by an actual lookup call (assert the lookup mock *was* invoked, which is the opposite of test 30b's assertion and is why the pair is worth having). The failure mode this excludes: an implementation that sees a non-NULL id and mints from it without ever checking whether the mode agrees.
    30e. **`ambient` with an id normalizes and still does not mint.** `github_auth_mode = 'ambient'`, `github_app_installation_id = 4242` ⇒ after dispatch the id is **NULL**, the mode is still `ambient`, no `credential.*` line is written to `config.worktree`, and the token-minting mock was **never** called. Assert the mock: the whole point is that an id on an ambient scope is inert.
    30c. **An `app` scope with a NULL id refuses rather than re-resolving.** Hand-build the unreachable row (`github_auth_mode = 'app'`, `github_app_installation_id = NULL`), then dispatch ⇒ `pending_reason == "queued_auth_mode_unresolved"`, lease released, no worktree `credential.*` lines written. Proves the fault case fails closed instead of falling through to a lookup or to the ambient credential.
31. Lookup returns `404` ⇒ mode `ambient`, **`github_app_installation_id` left NULL**, worktree gets identity and **no** `credential.*` line. Assert on the absence, by reading `config.worktree`. Assert too that this is *not* an `app_not_installed` refusal — the dispatch proceeds (§5.3a row 1).
    31b. **`app_not_installed` is a mint-time refusal.** A scope stored `app` with an id whose `POST /app/installations/{id}/access_tokens` returns `404` ⇒ the helper refuses `app_not_installed` naming the repo and the id, the mode is **not** downgraded to `ambient`, and the id is **not** cleared. Paired with 31 this is the §5.3a test: the same status code, two behaviours, keyed on which call returned it. A single shared `404` handler passes one of the two and fails the other.
32. **Lookup times out ⇒ mode is unchanged (`unknown`), NO worktree config is written at all, `pending_reason == "queued_auth_mode_unresolved"`, the lease is released, and `dispatch_status` is a pre-existing value.** This is the blocker-6 test.
33. Same for `500` and for a `403` rate-limit response — three separate cases, because an implementation can easily catch one and not the others.
34. A repo already stored as `app` whose lookup then times out ⇒ **no** lookup-driven change of mode, and the dispatch proceeds using the stored mode. Distinguishes "fail closed on an unresolved repo" from "re-resolve every time," which are different bugs.
35. `github_app_id` empty ⇒ mode `ambient` with **no** network call at all. Assert the mock was never invoked; a spurious call here would burn rate limit on every dispatch for operators who never configured the App.
36. `pr_opened` on an `ambient` repo with `github_app_bot_login` set ⇒ accepted, author check skipped (§5.6). This is the false-sentence test: revision 4's reasoning would refuse it or skip for the wrong reason.
37. `pr_opened` on an `app` repo with a non-bot author ⇒ `409`, `pr_number` unset.
    37b. **`app` mode with an empty `github_app_bot_login` refuses.** Same `app`-mode scope, `github_app_bot_login = ""`, a `pr_opened` report whose author is anyone at all ⇒ `409 app_mode_bot_login_unset`, `pr_number` **unset**, item still `dispatched`. Against revision 5 this report is accepted with the author check skipped — the partial-configuration bypass in §5.6's row 2. Assert the column, not only the status: a route that records the number and then refuses would pass a status-only assertion.
    37c. **`unknown` mode accepts and skips.** A never-resolved scope (`github_auth_mode = 'unknown'`, id NULL) with `github_app_bot_login` set ⇒ the report is **accepted**, `pr_number` recorded, no author comparison made. Paired with 37b this pins that the refusal is keyed on `app` mode specifically and does not leak onto the unresolved scopes every pre-upgrade row starts as — which would break `pr_opened` for every existing installation on the day PR2 lands.

| Mutant | Test that must fail |
|---|---|
| every lookup exception treated as `404` ⇒ `ambient` | **32, 33** |
| mode re-resolved on each use instead of read from the scope | 34 |
| mode stored globally in `config.py` instead of per scope | 36 (two scopes, different modes, one setting cannot serve both) |
| the lookup runs even with `github_app_id` empty | 35 |
| author check keyed on `github_app_bot_login` being set rather than on the repo's mode | **36** |
| worktree config written before the mode resolves | 32 (asserts the config file is absent, not just the refusal) |
| installation id cached in memory only, not persisted (revision 5) | **30b** |
| id persisted but the helper still reads only the cache | **30b** (the fresh-instance assertion) |
| helper re-resolves the installation when its cache misses | **30b** (asserts the lookup mock was never called) |
| `app` + NULL id falls through to a lookup, or to the ambient credential | **30c** |
| a mint-time `404` downgrades the stored mode to `ambient` | **31b** |
| one shared `404` handler for the lookup and the mint | **31, 31b** — one of the pair always fails |
| an empty `github_app_bot_login` skips the author check on an `app` scope (revision 5) | **37b** |
| the `app_mode_bot_login_unset` refusal applied to `unknown` scopes too | **37c** |

### 5.6b The verifier has no closed-unmerged condition either, and today it loops

§5.5.4a stops Deck *adopting* a closed PR. It does not help an item whose PR is open when adopted and closed by a human an hour later — the ordinary case, since that is when humans close PRs. The fifth review names the gap: *"The current verifier only special-cases `merged`; it does not reject a closed-unmerged PR."*

Confirmed by reading rather than assumed: `merged` is read at exactly two places (`github_verification_service.py:164` in `_verify_item`, `:228` in `_process_review_item`) and `state` is read **nowhere** in the file — the only other `.get("state")` is the combined-status state at `:326`, a different field on a different object.

**Measured, on today's code.** A closed-unmerged PR with green checks, `merge_policy="human"`:

```
Q1 human policy: status='ready_for_review'  note='PR #5 is ready for review.'
```

The item is presented as ready for review with its PR closed — the review's stated concern, reproduced. Under `merge_policy="auto"` the fake client's `merge_pull` is then called and succeeds, because a mock cannot refuse what GitHub would; against real GitHub that call fails, `405` is in `_MERGE_TRANSIENT_STATUS_CODES` (`:26`), and the item burns `max_verification_retries` before landing in `ready_for_review` with a misleading "transient merge failure" note. Measured across four polls: three `merge_pull` calls, then `'Auto-merge retry budget exhausted after transient merge failure'`. Bounded, but wrong on every line — the failure is permanent and the note says transient.

**And the draft case is not bounded at all.** This is the one worth the section. Deck creates code PRs with `draft=True` (§5.5.5), so a *closed draft* PR is the default shape of this failure. It reaches `_promote_verified_item` (`:375-398`), which calls `mark_pull_ready_for_review` — and GitHub refuses that mutation on a closed PR. `github_client` raises `HTTPStatusError` for a GraphQL body carrying `errors` (`github_client.py:154-159`), and `process_scope`'s handler catches it (`:118-124`):

```
Q4 poll 1: ready_calls=1  status='verifying'  retry_count=0  note='GitHub verification failed; will retry: Pull request is closed'
Q4 poll 2: ready_calls=2  status='verifying'  retry_count=0
Q4 poll 3: ready_calls=3  status='verifying'  retry_count=0
```

`retry_count` never moves, so the budget that bounds every other failure on this path does not bound this one — the counter lives in `_record_failed_verification_attempt` (`:465-508`) and this exception never reaches it. The item polls the GitHub API forever, and its `status_note` says "will retry" truthfully and forever. **A bounded retry loop is only bounded on the paths that route through the counter**; an `except` block added for transient HTTP quietly created an unbounded one.

**The fix: classify once, through §5.6's shared helper, where `merged` is read today.** In `_verify_item` (`:163`):

```python
verdict = _classify_pull(pull)              # (state, merged_at) only -- see §5.6
if verdict is None:                         # unrecognized or missing state
    await self._record_failed_verification_attempt(
        db, scope, item,
        None,                               # head_sha: not fetched yet, and see below
        f"PR #{item.pr_number} returned a state Deck cannot classify.",
        subject="GitHub verification could not classify the PR",
        body_markdown="...",
        payload={"pull_state": pull.get("state")},
        retry_status="dispatched",           # this stage's own status -- see §5.6b.1;
    )                                        # _process_review_item passes
    return                                  # item.dispatch_status instead
                                            # fail closed, consume the retry budget
if verdict == "merged":
    ...                                     # today's :164-168 block, unchanged
if verdict == "closed_unmerged":
    await github_dispatch_service.escalate(
        db, item, "pr_closed_unmerged",
        f"PR #{item.pr_number} was closed without being merged.",
    )
    await db.commit()
    return
```

Four things are load-bearing here, and only the second was in revision 7.

1. **Position:** before `_head_sha`/`list_check_runs_for_ref`, so no check-run call, no promotion, and no `mark_pull_ready_for_review` happens on a closed PR.
2. **One escalation reason** (§5.5.4a's) and **no new `dispatch_status`**.
3. **The classification comes from the helper, not from an inline field read.** Revision 7 wrote this condition as `pull.get("merged")` then `pull.get("state") == "closed"`, which happens to work here — `_verify_item` holds a `get_pull` response, where `merged` exists — and is still wrong, for the reason §5.6 gives: two copies of a three-way branch is how the `pr_ready` path came to be classified while `pr_opened` was not. A local read that works on this shape is exactly what makes the next copy on the *other* shape look safe. It also removes the ordering question entirely: `merged`-before-`state` cannot be got wrong in a caller that does not compare either field.
4. **`head_sha=None` is the argument that makes the counter move, and it costs one column.** `_record_failed_verification_attempt` opens with `if head_sha and item.last_verified_sha == head_sha: ... return` (`:477-483`) — a same-sha early return that **does not increment**. Passing the item's real head sha would therefore reproduce the unbounded loop on the second poll onward, which is the whole defect. Passing `None` makes the guard falsy and the increment unconditional. The price is the next line, `item.last_verified_sha = head_sha` (`:485`): the recorded sha is wiped. That is acceptable and deliberate — a NULL `last_verified_sha` makes the auto-merge head-freshness check treat the next verification as new work, which is the conservative direction — but it must be *stated*, because an implementer who "tidies" this by passing the real sha silently restores the loop, and the test suite stays green unless test 29f asserts the counter across three polls.

The `None` branch consumes the retry budget deliberately rather than escalating at once. An unclassifiable response is either a schema change or a transient garbled reply; escalating on the first one is too eager, and returning without touching the counter would recreate the unbounded loop this section exists to remove — the defect measured above is precisely a failure path that never reaches the counter. When the budget does run out, the existing `retry_count_exhausted` escalation fires (`:499-505`); no new reason and no new status.

`_process_review_item` (`:219`) needs the same condition, and that is worth stating so an implementer does not assume `_verify_item` covers it: `_verify_item` is the only route into it for a `verifying` item (`:216-217`, via `_promote_verified_item:398`), but `process_scope` sends `ready_for_review` / `awaiting_human_review` items to it **directly** (`:114-117`). Those can arrive with a newly-closed or newly-unclassifiable PR. So the condition goes in **both**, at the same position relative to each function's `merged` check — `_verify_item` for the pre-promotion path, `_process_review_item` for an item already promoted whose PR changes afterwards. Two call sites, one helper, one reason.

#### 5.6b.1 The refuse path must be stage-aware, and revision 8's was not

That second call site is where revision 8 broke, and the eighth review is right about it. `_record_failed_verification_attempt` does not merely count — it **parks the item somewhere**, and where it parks it is hardcoded for one pipeline:

```python
# github_verification_service.py:506-508, today
else:
    item.dispatch_status = "dispatched"
    item.updated_at = datetime.utcnow()
```

`process_scope:112-115` routes `dispatched` to `_verify_item`. So calling this helper from the *review* stage relabels the item as unverified code and hands it to the code verifier.

**Which garble reaches the promotion, measured.** Revision 8 puts the classify-refuse in **both** stages, so the two failure shapes do not end the same way, and only one of them promotes. Both measured through real `process_scope` polls, re-read with raw `text()` in a fresh session each time:

```
issue_type='design', dispatch_status='awaiting_human_review', draft PR, retries=2

(a) PERSISTENTLY unclassifiable
    poll 1  review stage refuses    'awaiting_human_review' -> 'dispatched'   retry 1
    poll 2  verify stage refuses too                          'dispatched'    retry 2
    poll 3                                                    'escalated'     retry 3
            list_check_runs_for_ref 0x   mark_pull_ready_for_review 0x
            -> no promotion. The item is merely mislabelled as unverified code
               for two polls while it waits for a human, then escalates.

(b) TRANSIENTLY unclassifiable  <- this is the one that promotes
    poll 1  review stage refuses    'awaiting_human_review' -> 'dispatched'   retry 1
    poll 2  GitHub answers normally; process_scope routes 'dispatched' to
            _verify_item, which finds green checks:
            list_check_runs_for_ref      1x
            mark_pull_ready_for_review   1x        <- draft flag removed
            ends dispatch_status='ready_for_review'
```

A design PR nobody reviewed is taken out of draft because GitHub returned one garbled response and then recovered. §5.5.5 makes design PRs non-draft deliberately so a human can approve them; this makes Deck do it on the code path's behalf, and the human-review request has already been sent. Under the fix, (b) reads `awaiting_human_review` on both polls with `mark_pull_ready_for_review` **0×**.

That distinction is worth stating precisely rather than reporting the worst case flatly, because a persistent garble looks *safer* than it is and a transient one looks *milder* than it is. The mislabelling in (a) is not harmless either: for two polls the row claims the design item is unverified code, which is what any operator, dashboard, or supervising agent reading `dispatch_status` will believe.

**The second half is worse, and the review did not name it.** The same helper overwrites `status_note` at `:487`. On a `ready_for_review` code item that note is not a message — it is **the only thing standing between the item and auto-merge**. `_HUMAN_MERGE_NOTE_PREFIXES` (`:20-25`) is checked at `:235`, and every path that reserves a PR for a human writes one of those four prefixes through `_fallback_to_human_merge:429`. Measured end-to-end on a code item parked by a real repository-policy `403`, `merge_policy="auto"`:

```
control poll, sentinel intact:  merge_pull  0 calls        <- :235 returns early
one refuse path:                status_note = 'PR #5 returned a state Deck cannot classify.'
                                dispatch_status 'ready_for_review' -> 'dispatched'
next poll:                      merge_pull  1 call
                                dispatch_status='merged'   auto_merged_at SET
```

Deck merged a pull request a human had explicitly reserved, because a classification failure erased the reservation. This is the most severe defect class in this spec, and it was invisible from the retry helper: the helper's own code is correct, and the write's significance lives 250 lines away in a constant it never mentions.

**The fix.** `_record_failed_verification_attempt` learns the item's stage, and the note write learns what a note can mean:

```python
# github_verification_service.py:465 -- signature
async def _record_failed_verification_attempt(
    self, db, scope, item, head_sha, note, *,
    subject, body_markdown, payload,
    retry_status: str,                    # REQUIRED, no default: where this item parks
) -> None:
    if head_sha and item.last_verified_sha == head_sha:       # :477, guard unchanged
        if item.dispatch_status != retry_status:              # was: == "verifying"
            item.dispatch_status = retry_status
            self._set_failure_note(item, note)
            item.updated_at = datetime.utcnow()
            await db.commit()
        return

    item.last_verified_sha = head_sha                          # :485, unchanged
    item.retry_count += 1                                      # :486, unchanged
    self._set_failure_note(item, note)                         # was: item.status_note = note
    await github_dispatch_service.notify_owner(...)            # :488-498, unchanged
    if item.retry_count > scope.max_verification_retries:
        await github_dispatch_service.escalate(
            db, item, "retry_count_exhausted", note,           # was: item.status_note
        )
    else:
        item.dispatch_status = retry_status                    # was: "dispatched"
        item.updated_at = datetime.utcnow()
    await db.commit()

def _set_failure_note(self, item, note: str) -> None:
    """A human-merge reservation outranks a failure note. See :20-25 and :235."""
    if item.status_note and item.status_note.startswith(_HUMAN_MERGE_NOTE_PREFIXES):
        return
    item.status_note = note
```

Four call sites, each stating its own stage:

```python
item.status_note = note                       # NOT this, anywhere -- use the helper
                                              # (illustrative: the mutant 29h kills)

retry_status="dispatched",                     # :193  failed check runs  (verify stage)
retry_status="dispatched",                     # :332  failed commit status (verify stage)
retry_status="dispatched",                     # new, _verify_item's classify-refuse
retry_status=item.dispatch_status,             # new, _process_review_item's classify-refuse
```

Six things are load-bearing, and an implementer who drops any of them restores a measured defect:

1. **`retry_status` has no default.** A default is what made this blocker possible: `"dispatched"` was right for the two callers that existed and silently wrong for the third. A required keyword-only parameter makes an omission a `TypeError` at the call, which no reviewer and no fixture can miss — enforcement by the interpreter rather than by discipline. Test 29g asserts the absence of the default with `inspect.signature`, so a later "tidy-up" that adds one fails.
2. **The review stage passes `item.dispatch_status`, not a literal.** `_process_review_item` serves `ready_for_review` (code) and `awaiting_human_review` (design), and both routes into it — `process_scope:117` and `_promote_verified_item:398` — leave the correct value on the row. Hardcoding `"ready_for_review"` would move a design item into the code review stage, which is blocker 3 one step smaller.
3. **The note guard lives in the helper, keyed on the same constant the reader at `:235` uses — not in a caller-passed flag.** The review proposed `preserve_note`; that is withdrawn, and the reason matters. A caller that does not know a note is a safety control will not pass a flag protecting it — which is exactly how `:487` came to erase the reservation. Two readers of one constant, side by side in one file, is checkable; a convention every future caller must remember is not. Test 29h-1 drives the helper with the *pre-existing* callers' arguments and asserts the note still survives, which a flag design fails.
4. **The failure is still reported, just not through `status_note`.** `notify_owner` (`:488-498`) already carries `subject`, `body_markdown`, and the `payload` with `retry_count` and `head_sha`. Preserving the reservation costs the operator nothing: they get the mail, and the column keeps saying the more important of the two true things — *this PR needs a human to merge it*.
5. **`escalate` is passed `note`, not `item.status_note`.** Today those are the same string, because `:487` had just assigned it; with the guard they can differ, and passing the row's value would escalate a reserved item under the reservation's own text instead of the real reason. This also makes escalation a safe terminal for a reserved item: `_apply_escalation:1037-1038` does overwrite the note, but `escalated` is not in `process_scope`'s status filter (`:98-105`), so the item stops being selectable at the same moment its reservation stops being read.
6. **The early return generalizes with it, and this one is a consistency change with no behaviour behind it — measured, and stated so nobody claims otherwise.** `:478`'s `if item.dispatch_status == "verifying"` becomes `!= retry_status`. For the two existing callers it is behaviour-identical (`verifying → dispatched`; no write when already `dispatched`), and the two classify-refuse callers pass `head_sha=None`, so they never reach this branch at all. I mutated it back to the literal and **all three tests still passed** — because the only state where the two forms differ is `dispatch_status == "verifying"` reaching the *review* stage, and `process_scope:112-115` sends every `verifying` item to `_verify_item`. So the change is made for one reason only: leaving the literal leaves a second place that decides which pipeline owns the item, and the first future caller to pass a real sha from the review stage would find the two branches disagreeing. It is guarded by 29h-2 below, which drives the helper directly on that unreachable pair; the mutation table records it as unkillable by the behavioural tests rather than pretending otherwise.

**Mutation requirement for this section.** Every row below was run: the fix applied, then the single mutation, then 29g / 29h / 29h-1 executed against it.

| Mutant | Test that must fail | Measured |
|---|---|---|
| `retry_status` given a default of `"dispatched"`, so the review-stage caller omits it | **29g, 29h** | 29g: design item at `'dispatched'` on polls 1-2, and the `inspect.signature` assertion trips. 29h: reserved item at `'dispatched'`, **`merge_pull` 1 call, `auto_merged_at` SET** |
| review stage passes the literal `"ready_for_review"` instead of `item.dispatch_status` | **29g** | design item parked in `'ready_for_review'` — the code review stage |
| the whole stage-aware fix reverted, checked by the promotion rather than the status | **29g-1, not 29g** | 29g's persistent garble is `mark_pull_ready_for_review` **0×** under the defect too, because the verify stage also refuses; only 29g-1's recovering client reaches the promotion — **1×**, ending `'ready_for_review'` |
| no note guard: `item.status_note = note` as today | **29h, 29h-1** | 29h: reservation replaced by `'PR #5 returned a state Deck cannot classify.'`, then `merge_pull` **1** call and `auto_merged_at` SET. 29h-1: the failed-check caller erases it too |
| `escalate(…, item.status_note)` instead of `escalate(…, note)` | **29h** | the escalation is filed under `'Auto-merge blocked by repository policy; requires human merge.'` — the reservation's text, not the reason |
| same-sha early return keeps the `"verifying"` literal | **none — unkillable, deliberately recorded** | all three pass. Both forms agree on every state `process_scope` can produce; 29h-2 is a direct-call unit assertion, not a behavioural one |
| classify-refuse omitted from `_process_review_item`, on the theory `_verify_item` covers it | **29g** | the design item is never polled by `_verify_item` at all, so nothing consumes the budget: `retry_count` stays `0` |

**One cost, stated so nobody "fixes" it.** `head_sha=None` still wipes `last_verified_sha` (`:485`), on the review stage as well, and §5.6b point 4 explains why passing the real sha is not available. For a design item this is inert: `_process_review_item` returns at `:231-232` before reading the column. For an unreserved `auto`-policy code item it costs exactly one extra cycle — the next review poll finds `current_head != item.last_verified_sha` at `:252`, sets `verifying`, and the item re-verifies from green checks before becoming mergeable again. That is the conservative direction and it is bounded. For a **reserved** code item it is inert too, because `:235` returns before `:252` is reached.

**Tests (§5.8):**

**One fixture requirement for all three, and it is not ceremony.** The item's `owner_slot_id` must point at an `AgentTeamSlot` that has a `MailTeamMember` row, because `notify_owner` returns silently when `_owner_member` is `None` (`github_dispatch_service.py:1051-1053`, via `_slot_member:1224` selecting on `MailTeamMember.team_slot_id`). Without both rows the "one mail row" assertion passes vacuously against every implementation, including ones that send nothing. Measured: my first run of 29h reported `mail=0` under the fix *and* under revision 8, and the cause was the missing member row, not the code. A fixture that cannot produce the effect cannot assert its absence either.

29g. **A design item's refuse path does not enter the code pipeline.** `issue_type="design"`, `dispatch_status="awaiting_human_review"`, `pr_number=5`, a **draft** PR whose `state` is absent so `_classify_pull` returns `None`, `max_verification_retries=2`. Across three `process_scope` polls, re-reading with raw `text()` in a **fresh session** each time: `retry_count` reads `1`, `2`, `3`; `dispatch_status` is `"awaiting_human_review"` on the first two and `"escalated"` / `retry_count_exhausted` on the third; `list_check_runs_for_ref` was called **0** times and `mark_pull_ready_for_review` **0** times over the whole run. Plus one static assertion in the same test: `inspect.signature(GithubVerificationService._record_failed_verification_attempt).parameters["retry_status"].default is inspect.Parameter.empty`. Measured against revision 8: polls 1 and 2 read `'dispatched'`. The fresh session is not ceremony — the identity map returns the in-memory value, and the whole question is what the *next poll's* query will select.
    29g-1. **The garble must clear, or the promotion assertion proves nothing.** A second fixture, identical except that the client returns a normal `state: "open"` from poll 2 onward: poll 1 refuses, poll 2 finds a healthy PR. Assert `mark_pull_ready_for_review` **0** calls and `dispatch_status == "awaiting_human_review"` after poll 2. **This is the test that sees the promotion, and 29g is not.** Measured: under revision 8, 29g's persistent garble ends `escalated` with `mark_pull_ready_for_review` **0×** — because the verify stage refuses too, the item never reaches the promotion it was mislabelled into, so 29g's `0×` assertion is satisfied by the *defect* as well as the fix and bites only through its status assertions. Flip the garble off on poll 2 and revision 8 calls `list_check_runs_for_ref` **1×** and `mark_pull_ready_for_review` **1×**, ending `ready_for_review`. Two fixtures, because the transition out of `dispatched` needs a poll in which the code pipeline can actually run: an always-failing dependency hides what a recovering one exposes.
    29h. **A reserved PR is not auto-merged by a classification failure.** The regression test for the measurement above, in three phases. Fixture: code item, `merge_policy="auto"`, `dispatch_status="ready_for_review"`, `status_note="Auto-merge blocked by repository policy; requires human merge."`, `last_verified_sha` equal to the PR's head, PR open with all-green checks and `max_auto_merges_per_day` not exhausted.
    **Control** — one `_process_review_item`: `merge_pull` **0** calls. This assertion is mandatory and comes first; without it a later phase asserting "0 calls" could be passing because the fixture was never mergeable.
    **Phase 2** — one classify-refuse: `status_note` still `.startswith(_HUMAN_MERGE_NOTE_PREFIXES)`, `dispatch_status` still `"ready_for_review"`, `retry_count == 1`, and **one** mail row whose body names the classification failure (so the guard is not hiding the failure, only keeping it out of that column). Then two more `process_scope` polls: `merge_pull` **0** calls total, `auto_merged_at` **NULL**.
    **Phase 3** — run to exhaustion: `dispatch_status == "escalated"`, `escalation_reason == "retry_count_exhausted"`, `status_note` naming the **classification failure** and not the reservation (that is the `escalate(…, note)` assertion), and one final `process_scope` making **zero** client calls of any kind, proving `escalated` leaves the auto-merge filter. Assert on `merge_pull`'s call count throughout rather than on `dispatch_status != "merged"`: merging is a legitimate outcome for this item once a human does it, so the status is not the invariant — *Deck not merging it* is.
    29h-1. **The reservation guard protects callers that do not know about it.** Call `_record_failed_verification_attempt` directly with the *failed-check* caller's arguments (`retry_status="dispatched"`, a real `head_sha`, `last_verified_sha` set to something else so the early return does not fire) on an item whose `status_note` is a reservation ⇒ the note survives. This is the test that distinguishes the guard-in-helper design from the withdrawn `preserve_note` flag: under the flag, this call site passes nothing and the note dies. One assertion, and it is the only one that pins *where* the guard lives. Measured: survives under the fix, replaced by `'GitHub check failed: ci'` without it.
    29h-2. **The same-sha branch honours `retry_status` too.** A direct call, because no reachable state distinguishes the two forms (point 6). Item `verifying`, `last_verified_sha` **equal** to the passed `head_sha`, `retry_status="awaiting_human_review"` ⇒ `dispatch_status == "awaiting_human_review"`. Against the `"verifying"` literal it reads `'dispatched'` — measured both ways. Label this test as pinning a *consistency* rule rather than a behaviour, so a future reader does not go looking for the scenario it protects.

**Test (§5.8):**

29c. **A closed-unmerged PR escalates instead of promoting.** An item in `verifying` whose PR is `state: "closed", merged_at: null` with **all-green checks** ⇒ `dispatch_status == "escalated"`, `escalation_reason == "pr_closed_unmerged"`, `status_note` naming the PR number, and — the assertions that make it bite — `list_check_runs_for_ref` was **never called**, `mark_pull_ready_for_review` was **never called**, and `merge_pull` was never called. Green checks are deliberate: they are what carries the item to promotion today, so a fixture with failing checks would pass against the unfixed code for the wrong reason. Run the same fixture with the PR as a **draft** and assert the item does not stay `verifying` across three polls — that is the unbounded loop above, and it is the assertion revision 5's design fails.
    29d. **A merged PR still reconciles.** Same fixture with `state: "closed", merged_at: "<ts>"` ⇒ `dispatch_status == "merged"`, no escalation. Because this is a `get_pull` response, set `merged: true` **as well** — the real shape carries it — and that is what makes this test bite: it passes only if the verifier classified on `merged_at`. A `merged: true` / `merged_at: null` fixture is not constructible from GitHub and would prove nothing.
    29e. **An open PR is unaffected.** `state: "open", merged_at: null` with green checks ⇒ promotes exactly as today. The regression guard: a condition written as `state != "open"` rather than a `_classify_pull` verdict would also catch the absent-field case and escalate healthy items — under this design that case is the helper's `None` branch, which consumes the retry budget instead.
    29f. **An unclassifiable response does not loop.** `state` absent entirely (or `"draft"`, an invented value) ⇒ `_classify_pull` returns `None`, and across **three** polls `retry_count` reads `1`, `2`, `3` — assert the sequence, not just that it is non-zero. Neither `list_check_runs_for_ref` nor `escalate` is called until the budget is exhausted; on the poll after `max_verification_retries`, `escalation_reason == "retry_count_exhausted"`. Keep `item.last_verified_sha` set in the fixture, because the mutant this test exists to kill (passing the real `head_sha`) is only distinguishable when the same-sha early return at `github_verification_service.py:477` can fire — with `last_verified_sha` NULL the mutant increments too and the test passes against it. This is the assertion that separates this design from revision 7's: assert the counter *moved every time*, not that the status looks sane, because `verifying` with a "will retry" note is exactly what the unbounded loop reports.

| Mutant | Test that must fail |
|---|---|
| no closed-unmerged condition at all (today's code) | **29c** |
| condition placed **after** the check-runs call | 29c (the never-called assertions) |
| classified inline on `merged` instead of through `_classify_pull` | **29d** — a `merged_at` fixture on a PR whose `merged` key is absent or stale classifies wrong; also **46n**, which requires one helper for both shapes |
| condition added to `_verify_item` only | 29c, run on a `ready_for_review` item |
| written as `state != "open"` | **29e** |
| `None` verdict returns without touching `retry_count` | **29f** — three polls, counter still `0` |
| `None` verdict passes the item's real `head_sha` instead of `None` | **29f** — the same-sha early return at `:477` skips the increment from poll 2 onward, so the counter reaches `1` and stops |
| `None` verdict escalates immediately instead of retrying | **29f** — `escalate` called on poll 1 |
| read `merged_at` with `.get()` instead of testing key presence first | **46o-1** — an unreadable payload escalates `pr_closed_unmerged`, a verdict indistinguishable to an operator from a real human-closed PR |
| branch on `state` before testing `merged_at`'s presence | **46o-1, 46o-2** — the presence guard must dominate both state branches, or `{"state": "open"}` still returns `"open"` |
| treat an open PR's non-null `merged_at` as merged rather than refusing | **46o-2** — either side of an incoherent pair is a guess; measured zero times in 105 live PRs |
| add the two refusals but tighten a working case with them | **46o-3** — nine committed fixtures must classify unchanged |

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

**One requirement over all of them, because it is what the seventh review's blocker 3 turned on.** Every fixture standing in for a GitHub response must be *the shape the endpoint being mocked actually returns* — not the shape the code under test happens to read. Concretely, for pull requests:

| Mocked call | Fixture must carry | Fixture must **not** carry |
|---|---|---|
| `list_pulls_for_head` (`GET /pulls`) | `state`, `merged_at`, `merge_commit_sha`, `head`, `base`, `number`, `draft` | **`merged`** — assert `"merged" not in pull` explicitly |
| `get_pull` (`GET /pulls/{n}`) | all of the above **plus** `merged`, `mergeable`, `mergeable_state`, `merged_by` | — |

Both key sets are copied from the measurement in §5.5.4a, and the `not in` assertion is the load-bearing half: revisions 6 and 7 mocked `merged: true/false` on the *list* path, so six tests passed against a classifier that raises `KeyError` on every real response. A fixture that quietly grows a `merged` key must fail a test rather than silently start exercising the other endpoint. Where a shared helper is asserted to serve both shapes, the two fixtures must be **separate objects** and the same helper called on each (test 46n); one fixture with a superset of keys proves nothing about the shape that lacks them.

The same rule generalizes past this spec: **a mock's job is to reproduce the interface, not to satisfy the implementation.** Three of this spec's revisions were falsified by a response schema nobody had fetched.

1. Workspace provisioning sets all five per-worktree config values; a second worktree in the same repo is unaffected.
2. The URL-scoped helper wins over an ambient `credential.https://github.com.helper` — the exact case that failed when measured with the unscoped key.
3. A slot whose display name contains spaces and punctuation is slugified into a valid email local-part (lowercase, `[a-z0-9.-]`, collapsed runs). This is a **correctness** requirement, not a security one: `_env_flags` (`agent_bridge/spawn.py:38-44`) validates variable *names* against `[A-Z_][A-Z0-9_]*` and raises on a bad one, but does not validate values — and `subprocess.run` is called with an argv list and no `shell=True` (`:79-84`), so no shell ever interprets a value. Measured: `{'GIT_AUTHOR_NAME': 'Bad; rm -rf / $(whoami)'}` passes through untouched and harmlessly. The plan must not add shell-escaping theater; a malformed email pollutes `git log` and `Co-authored-by` trailers, and that is the real defect.
4. The token cache refreshes inside the margin and reuses outside it; concurrent callers mint once (lock held).
5. The private key, the JWT, and the token appear in no log record and no brief.
6. `pyjwt[crypto]` and `cryptography` are declared in `requirements.txt`.
7. With App auth unconfigured, dispatch still works on the existing `github_token` path.
8. `report_pr_opened` refuses a PR in a different repo (`409`, `pr_number` unset).
9. `report_pr_opened` refuses a PR whose author is not the bot **on an `app`-mode scope** (§5.6a). Keyed on the scope's `github_auth_mode`, not on `github_app_bot_login` being non-empty — tests 36 and 37 are the pair that pin this distinction, and 37b/37c pin what happens when the expectation itself is missing.
10. `report_pr_opened` refuses a PR whose head branch does not match the item's expected branch.
11. `report_pr_opened` skips the author check on an **`ambient`-mode** scope even when `github_app_bot_login` is set. This is the false-sentence test; see §5.6 and test 36.
    11b. **A merged PR reported through `pr_opened` on a design item asks nobody to review it.** `ambient`-mode scope, design item, `pr_opened` with a number whose `get_pull` returns the **full single-pull shape** — `state: "closed"`, `merged_at: "<ts>"`, **and** `merged: true`, because that is what GitHub returns and a fixture missing `merged_at` would pass against a classifier reading only `merged` ⇒ `dispatch_status == "merged"`, `pr_number` recorded, and **zero** `github_dispatch_design_pr_ready` mail rows. Count the mail rows; the status assertion alone passes against today's code by the next poll, which is exactly how this defect survived revision 6.
    11c. **A closed-unmerged PR reported through `pr_opened` escalates and notifies nobody.** Same fixture, `state: "closed"`, `merged_at: null`, `merged: false`, and — the field that makes this bite — a **non-null `merge_commit_sha`**, as GitHub returns on an abandoned PR (§5.5.4a's `#6118` measurement) ⇒ `escalated` / `pr_closed_unmerged`, the number in `status_note`, `pr_number` still **NULL**, and zero mail rows of any kind. Against revision 6 this is `awaiting_human_review` with a review request for a PR the human already closed.
    11d. **The shared classifier is shared.** Assert the same function object backs all three call sites — §5.5.4a's reconciliation, `report_pr_opened`, and §5.6b's verifier condition — by monkeypatching `_classify_pull` to a sentinel and driving each of the three paths, asserting the sentinel was consulted every time. This is a structural test, and it is deliberate: two independent copies of the three-way branch is the exact mechanism by which revision 6 classified one path and not the other. A behavioural test cannot catch a *duplicate* that currently agrees.
    11e. **State is classified after repo/head, not before.** A `pr_opened` report whose PR is merged (`state: "closed"`, `merged_at: "<ts>"`) **and** in the wrong repository ⇒ refused as a wrong-repo report (`409`, `pr_number` unset), **not** reconciled to `merged`. Pins the ordering requirement; a classifier called first would accept a foreign merged PR as this item's outcome.
12. Brief contains the `[Slot]` prefix, the **attempt-scoped** branch instruction, and both trailers — and instructs `pr_ready` with `head_ref`, not `pr_opened` with a number, on an `app`-mode scope. It must **not** claim the agent owns the PR title (§5.5.5). **Assert the brief contains the item's persisted `dispatch_head_ref`, re-read from the row; do not recompose the expected name inside the assertion.** Revision 8's version of this test called `attempt_head_ref` in the assertion, which makes the test and the code share a composer — so when a shared input moves (blocker 2: `accept_handoff` moves `owner_slot_id`), both produce the same wrong answer and the test stays green on a brief naming a branch nobody will accept. Reading the column instead makes the test an independent witness: it fails if the brief and the record disagree, which is the only property the agent's push depends on. Also assert the old `git switch -c <branch>` line at `github_dispatch_service.py:410` is **gone**, not merely joined.

Deck creates the PR (§5.5.2):

13. `pr_ready` with a valid `head_ref` ⇒ Deck calls `POST /repos/{o}/{r}/pulls` **once**, records the returned `pr_number`, and the item lands in `verifying` (code) or `awaiting_human_review` (design), matching `report_pr_opened`'s existing behavior.
14. `pr_ready` with a `head_ref` that is **not byte-equal to the item's stored `dispatch_head_ref`** ⇒ `409`, **no** pulls call made, `pr_number` unset. Assert the call was not made, not merely the status code. The wording matters: "outside the expected *pattern*" was revision 8's framing and it describes a **weaker check than §5.5.4a rule 1 requires** — a pattern match accepts any well-formed attempt name, including another slot's and another attempt's, which is exactly what tests 46i and 46j exist to refuse. State the check as equality against the stored value, and use the plainly-wrong branch name here (46i is a *previous* attempt's nonce, 46j a NULL head).
15. `pr_ready` for a ref absent on the remote ⇒ refuses with "branch not found," no pulls call.
16. `pr_ready` twice for the same item ⇒ one pulls call total, second returns the existing `pr_number`. Test 38 is the stronger form of this (it asserts the reconciliation call is skipped too); keep both, since 16 is the behavior an operator sees and 38 is the mechanism.
17. On an **`ambient`-mode** scope, `pr_ready` refuses and `pr_opened` still works — the legacy path is intact.
17b. `pr_ready` from the owner with a **stale lease token** ⇒ `409` before any GitHub call (test 7i — introduced by §3.5a, living in §3.7's file — asserts the same rule from the authorization side; this one asserts the mock was never invoked).
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
29. **No undeclared namespace value.** The invariant, renamed. Revision 6 called this "no new `dispatch_status` and no new `pending_reason`" and then listed `queued_auth_mode_unresolved` — a value PR2 introduces — in its own allowlist. The sixth review is right that the heading contradicted the test. What PR2 actually promises is narrower and checkable: **every status/reason value the code can produce is one this spec declares**, and the count of `dispatch_status` values does not grow.

    Revision 6 also specified this as a scan over "items left behind by every other test in this file," which **cannot run**. Confirmed against the fixtures: `tests/agent_teams/conftest.py:15-23` builds a fresh `sqlite+aiosqlite:///:memory:` engine per test, and `test_github_dispatch_service.py:32-40` and `test_github_verification_service.py:26-34` each define their own identical local `db` fixture. No test observes another test's rows, and making the fixture session-scoped would trade a missing assertion for order dependence across ~90 tests. Withdrawn.

    **Revision 7's replacement was still overclaiming, and the seventh review is right.** It said three frozensets plus a runtime membership test were "the whole of the enforcement," and asserted a mutation row for *"a path writes a string literal instead of drawing from the frozensets."*

    That mutation row is **withdrawn rather than reassigned to the AST scan**, and the distinction matters because revision 8 half-implied the scan kills it. It does not. `item.pending_reason = "queued_repo_cap"` and `item.pending_reason = QUEUED_REPO_CAP` write the identical row, so no *runtime* test can tell them apart — and 29-a1 deliberately accepts **both** (tier 1 and tier 2 of the RHS rule), because failing the constant form would punish the tidier code. Measured: rewriting an existing literal as a same-file module constant produces **no** failure in 29-a1, by design.

    So the accurate statement is narrower than either revision: **nothing enforces that a writer selects *through* the frozenset, and nothing needs to.** What is enforced is that the *value* is declared, wherever it comes from and however it is spelled — which is the property the invariant actually cares about. Style is not the invariant; the set of reachable values is. And a writer omitted from 29-b's table is never executed, so the table cannot reveal its own omissions either. A frozenset that nothing is forced to select through is documentation — and that is fine, provided the enforcement lives somewhere that does not depend on the selection.

    **What is actually enforceable differs per column, so the promise is now stated per column.** Counts below are **write** sites under 29-a1's classifier, not raw name matches — the raw counts revision 8 quoted (30 assignments + 4 keywords) included the three serializer keywords at `agent_teams.py:201` and were wrong for two of the three columns as a result. Writers live in four files: `api/v1/agent_teams.py`, `services/github_dispatch_service.py`, `services/github_verification_service.py`, `services/github_watcher_service.py`.

    | Column | Write sites today | Enforceable? | What PR2 promises |
    |---|---|---|---|
    | `escalation_reason` | **6** = 1 non-`None` (`_apply_escalation:1035`, the `reason` **parameter**) + 5 `= None` clears. **Zero** string literals anywhere | **yes, fully.** One funnel already exists, and no literal competes with it | validated at the funnel **and** an AST test that no other site writes it |
    | `dispatch_status` | **14** = 13 `Assign` literals + 1 ORM-constructor keyword (`github_watcher_service.py:63`, the `GithubWorkItem(` call; the keyword itself is on `:70`), over **9** distinct values | **yes, for growth.** Every value is a resolvable literal | the set of values written anywhere in `app/` is unchanged by PR2 |
    | `pending_reason` | **11** = 5 literals + 5 clears + **1 f-string** | **no.** `agent_teams.py:785` writes `f"retry requested: {request.reason}"` — operator free text | PR2's own reasons are declared; the column is **not** a closed set, and this is pre-existing |

    Two of these numbers moved from revision 8 for the same reason: `escalation_reason` reads **6** total and not 7, and the `= None` clears are 5 and not 6, because the serializer keyword no longer inflates the count. The `dispatch_status` keyword count stays 1 — `github_watcher_service.py:63` really is an ORM constructor — which is the case that shows why the answer is "classify the call", not "drop keywords".

    That f-string is the finding the review did not reach, and it is the one that decides the design: `pending_reason` **already** carries arbitrary operator text on the retry path. A frozenset over that column can never be exhaustive, so revision 7's `PENDING_REASONS` equality assertion was unsatisfiable as written — it would fail on the first operator who retried an item with a reason. Narrowing the promise is not a concession; it is the only true statement available.

    Replaced with three tests, needing no cross-test residue and no impossible mutant:

    29-a. **The declared-values test — three sets, two of them closed.** PR2 introduces three module-level frozensets next to the code that uses them, and asserts **equality** for two and **membership only** for the third. Say "three sets, two closed" rather than "three frozensets", because the asymmetry is the design and a reader who skims it will write the unsatisfiable version:
    - `DISPATCH_STATUSES` — **equality**, and the set is the existing one, unchanged by PR2. Spelled out, because "the existing set" is not a test. Measured over `app/` today, exactly **nine** literals are written to the column:

      ```python
      DISPATCH_STATUSES = frozenset({
          "pending", "dispatched", "verifying", "ready_for_review",
          "awaiting_human_review", "merged", "completed", "escalated", "failed",
      })
      ```

      Two of these are easy to omit from a hand-written list and both are real: **`"failed"`** (`github_dispatch_service.py:339`, a launch that came back in `_LAUNCH_FAILED_STATUSES`) and **`"completed"`** (`github_watcher_service.py:170`, `_complete_and_notify`). Verified `"cancelled"` appears **nowhere** in `app/` — do not include it because it sounds like it belongs. The set is also closed in the other direction: every literal compared against `dispatch_status` anywhere in `app/` is one of these nine, and none is read-only. `ready_for_review` reads as write-only under a naive scan for `_STATUSES`-named constants — its only reader is the inline `.in_()` tuple at `github_verification_service.py:99-107`. This is the assertion that carries the standing "no new `dispatch_status` values" rule, and it is the one that fails if `pr_closed_unmerged` is implemented as a status.
    - `ESCALATION_REASONS` — **equality**. The eleven enumerated in §5.5.4a, plus the two this design adds: `pr_closed_unmerged` (PR2, §5.5.4a) and **`prepared_owner_unavailable`** (PR1, §4.2b.1) — thirteen. Note this column has **zero** string literals written to it anywhere in `app/` today; every value arrives through `_apply_escalation`'s `reason` parameter, which is precisely why equality is enforceable here and why the runtime funnel is the other half of the enforcement.

      `prepared_owner_unavailable` is an `escalation_reason` for the same reason `pr_closed_unmerged` is: `_apply_escalation` sets `dispatch_status = "escalated"` (`:1034`), a value that already exists, so the standing **no new `dispatch_status` values** rule is respected. It is likewise **not** added to `_PR_OPENED_RECOVERABLE_ESCALATIONS` (`github_verification_service.py:29-37`) — that list means *the agent got stuck and a late PR resolves it*, and this reason means *the owner is gone while its attempt may still be live*, which a `pr_opened` report does not resolve. Its recovery is not `deck_retry_work_item` either, and this is the one reason on the list where retry is the **wrong** answer: a retry mints a fresh nonce and orphans an attempt whose pane may still be running (§4.2a property 6). The recovery is to re-enable the slot, or to hand the item back into the preset, and let the next poll continue the same attempt — which is why 37n-3's second half asserts the re-enable path dispatches without minting.
    - **`PENDING_REASONS` — membership only, not equality.** The test asserts `queued_auth_mode_unresolved` is a member and that PR2's other reasons are members, and it does **not** assert equality. A comment names `agent_teams.py:785` as the reason, so the next person does not "tighten" it into a failing test. Measured: 5 literals written today, plus that one f-string.

    Spelling the expected sets as literals is the point: the test fails when someone *adds* a value, which is when a human should look, rather than tautologically re-deriving whatever the code contains. Note these are conventions, not database constraints — both columns are plain nullable `String` (`models/database.py:255`, `:278`), verified.

    29-a1. **The static assignment-site test — this is the enforcement.** Parse every module under `app/` with `ast`. Revision 8 collected "every `ast.Assign` target and every `ast.keyword` with those names", and the eighth review is right that this does not work: **a keyword's name does not tell you whether it writes the column or reads it.** `GithubWorkItemResponse(...)` at `agent_teams.py:201` passes all three names, and it is a serializer. Revision 8's test, implemented literally and run against the current tree, **fails four of its own assertions** — measured, table in §1.

    So the scan classifies the **enclosing call**, not the keyword name. Three-way, and the third way is the important one:

    | Form | Classified | Why |
    |---|---|---|
    | `item.<col> = …` (`Assign`, `AnnAssign` on an `Attribute`) | **write** | direct ORM mutation, no call to classify |
    | keyword to a call whose base name is in `ORM_WRITE_CALLS` (`{"GithubWorkItem"}`) | **write** | constructing a mapped row |
    | keyword to a call whose base name is in `NOT_WRITE_CALLS` (`{"GithubWorkItemResponse"}`) | **not a write** | copying a column out to a caller |
    | **any other call form** | **test failure** | see below |

    **UNKNOWN is a failure, not a skip.** An allowlist that silently ignores what it does not recognize has exactly the blind spot it was built to remove — the same defect as revision 7's frozenset, one layer up. So `update(GithubWorkItem).values(dispatch_status=…)`, a helper like `set_state(item, dispatch_status=…)`, and an aliased `SomeOtherResponse(dispatch_status=…)` all **fail the test** until a human classifies them into one of the two sets. Measured: all three land in UNKNOWN, and the current tree has **0** unknowns, so the test passes today and fails the moment a new call form appears.

    **`update(...).values(...)` is UNKNOWN — the single policy, stated once.** Revision 9 said two different things about this form: the summary table called explicit `update()` a counted ORM mutation form, and this section called it UNKNOWN-and-failing. The ninth review's correction 6 is right that both cannot hold, and the contradiction is resolved **in favour of UNKNOWN**, on a measured basis rather than a preference: `.values(<column>=…)` over the three columns has **0 occurrences in `app/` today**, so failing it costs nothing on arrival and refuses the first use until a human decides whether that use is legitimate. The summary line is the half that changed. Note this is the *opposite* fix from the splat's, and for a reason worth stating: a `.values()` keyword **is** a named identifier, so the scan reaches the call and can return a verdict — measured, the name-triggered collector sees `['dispatch_status']` for `update(GithubWorkItem).values(dispatch_status="x")`. UNKNOWN is therefore a real classification here, whereas for the splat the scan never arrives at all. Visible-but-unrecognized needs UNKNOWN-is-failure; invisible needs a callee-keyed rule. Two defects, two mechanisms.

    Then assert:
    - every `dispatch_status` value written anywhere is a member of `DISPATCH_STATUSES`, under the RHS resolution rule below;
    - `escalation_reason` is written at **exactly one** non-`None` site, `_apply_escalation`, whose parameter is validated against `ESCALATION_REASONS` at runtime;
    - the file×column write-site counts match a recorded baseline, so a **new** writer in a new file fails the test even if its value happens to be declared;
    - the UNKNOWN list is **empty**.

    **The RHS rule needs three tiers, not two, and revision 8's two-tier version was backwards.** Revision 8 said "string literals resolved directly; a `Name` or other non-literal RHS is a **failure**." Measured against the forms an implementer would actually write, that rule **rewards the bare literal and punishes the named constant** — the opposite of what `DISPATCH_STATUSES` exists to encourage:

    ```
    item.pending_reason = "queued_repo_cap"              ast Constant   -> checkable, PASS
    item.pending_reason = QUEUED_REPO_CAP                ast Name       -> FAILURE
    item.pending_reason = PendingReason.QUEUED_REPO_CAP  ast Attribute  -> FAILURE
    ```

    So the rule is:

    - **Tier 1 — `ast.Constant` string.** Check membership directly.
    - **Tier 2 — `ast.Name` bound to a module-level `X = "…"` string in the same file.** Resolve it by a single pass over the module body, then check membership. Measured: a same-file constant resolves cleanly (`QUEUED_REPO_CAP` → `'queued_repo_cap'`); a cross-module or class-attribute reference does not, because `ast` has no interpreter.
    - **Tier 3 — anything else.** A **failure**, unless in an explicit, commented allowlist.

    The allowlist has exactly two entries today, and both are *deliberately* unresolvable:
    - `github_dispatch_service.py:1035`, `item.escalation_reason = reason` — a **function parameter**, which no static pass can resolve. This is not a gap in the scan; it is the design. That line is the single validated funnel, and the runtime check inside `_apply_escalation` is what constrains it. A static scan and a runtime funnel are covering different halves of one column, and the allowlist entry is where that division is recorded.
    - `agent_teams.py:785`, the `JoinedStr` operator free text, with the reason in the comment beside it.

    Tier 2 matters because without it the test would fire on the first implementer who does the tidier thing. That is the failure mode where a test teaches the wrong lesson: it would be read as "the scan wants literals", and the frozensets would quietly become decoration.

    **29-a1 was implemented as specified above and run against the current tree: it passes, with every assertion live** — 0 unknown call forms, 0 tier-3 failures outside the two-entry allowlist, 0 undeclared `dispatch_status` values, exactly 1 non-`None` `escalation_reason` site, and the `setattr` baseline matching. A green scan proves nothing on its own, so it was then mutation-tested by copying `app/` to a temp tree and injecting one violation at a time. **All ten mutants are caught by a named assertion**, and the two that must *not* fire do not:

    | Mutant | Caught by |
    |---|---|
    | an undeclared `dispatch_status` literal added | `undeclared-dispatch_status`, **and** the site-count baseline |
    | a second `escalation_reason` write, bypassing the funnel | `escalation_reason-funnel` (2 sites ≠ 1) |
    | a new writer via `update(GithubWorkItem).values(...)` | `UNKNOWN-call-form` |
    | a new writer via a helper keyword, `set_state(item, dispatch_status=…)` | `UNKNOWN-call-form` |
    | a new write via `setattr(item, "dispatch_status", v)` | the `setattr` baseline — nothing else can see this form |
    | a new ORM-constructor writer whose value **is** declared | the site-count baseline alone (this is why that baseline exists) |
    | an unresolvable cross-module constant RHS | `RHS-tier-3` |
    | an existing literal changed to an undeclared value | `undeclared-dispatch_status` |
    | an existing literal **rewritten as a same-file module constant** | **nothing — correct.** Tier 2 resolved it and membership held |
    | *(control)* the unmutated tree | nothing — the test passes on arrival |

    One methodological note for whoever implements this, because it cost a wrong result here: the last two rows must **replace** an existing write rather than add one. Any *added* site moves the site-count baseline, which fires regardless of the RHS rule and therefore masks whether tier 2 accepted the constant or rejected it. My first attempt added the tier-2 case as a new function and read the resulting failure as a tier-2 defect; it was the count guard doing its job. Hold the count constant when the RHS rule is what you are testing.

    **Baselines, re-measured with the corrected classifier** (revision 8's were wrong in two of three columns):

    | Column | Write sites | Breakdown |
    |---|---|---|
    | `dispatch_status` | **14** | 13 `Assign` string literals + **1** ORM keyword (`github_watcher_service.py:63`, the call node; the keyword is on `:70`) |
    | `pending_reason` | **11** | 5 literals + 5 `None` + **1 `JoinedStr`** (`agent_teams.py:785`) |
    | `escalation_reason` | **6** | **1 `Name`** (`github_dispatch_service.py:1035`) + 5 `None` |

    Plus **3** response-constructor keywords at `agent_teams.py:201`, all classified *not a write*, and **0** unknown call forms. The `JoinedStr` is the one allowlisted entry, with the operator-free-text reason in the comment beside it. Note `escalation_reason` is 5 `None` writes and not 6 — revision 8 said 6, and the count moved because response keywords no longer inflate it.

    This is what kills the undeclared-**value** mutant that 29-b cannot, and the wording matters: the scan checks the value, resolving it through tier 1 or tier 2, so a literal and a same-file constant are treated identically and neither can name something undeclared. It does **not** kill "wrote a literal instead of selecting from the frozenset" — that mutation row is withdrawn, not relocated here. It also derives the writer set **from code** rather than from the same hand-maintained table whose omissions it is meant to catch, which is the review's requirement.

    29-a2. **The classifier is itself tested, on synthetic sources.** 29-a1's value rests entirely on the claim that it can tell a write from a read. That claim gets its own test rather than being asserted in prose: parse twelve one-line synthetic sources and assert each classification. Measured as specified — `GithubWorkItemResponse(dispatch_status=item.dispatch_status)` → *not a write*; `GithubWorkItem(dispatch_status="brand_new_status")` → *write*; `item.dispatch_status = "x"` and the `AnnAssign` form → *write*; `update(...).values(...)`, a bare `set_state(...)` helper, and an aliased response model → **UNKNOWN, i.e. failure**; `GithubWorkItem(**{"dispatch_status": "x"})` and `GithubWorkItem(**payload)` → **splat violation** under the callee-keyed rule below, with `AgentTeamSlot(preset_id=p, **slot_data)` as the negative control that must pass. This is the test that would have caught revision 8's design, and it needs no fixture and no database.

    **What the scan cannot see, named rather than left implicit.** Three forms are invisible to any name-based AST scan, measured as invisible: `setattr(item, "dispatch_status", v)`, `GithubWorkItem(**{"dispatch_status": …})`, and a loop doing `setattr(item, col, val)` over pairs. The first is not hypothetical — **`setattr` in a loop is already an idiom in this codebase**, at `agent_team_service.py:377` (`setattr(slot, key, value)`) and `mcp_service.py:307` (`setattr(cache_entry, key, value)`). Neither touches a work item, but an implementer following the local idiom would write a namespace mutation this scan reports as absent.

    So 29-a2 carries a third assertion: **the set of `(file, first-argument)` pairs for every `setattr` call in `app/` equals a recorded baseline** of exactly those two sites. Measured: the baseline matches today, and adding `setattr(item, "dispatch_status", v)` to the verifier breaks it. This does not make the invisible forms visible — it makes *introducing* one fail a test, which is the enforceable version of the claim. State the limit plainly in the test's docstring: a determined writer can still evade the scan, and the guard is that they cannot do so *quietly*.

    **The splat needs its own rule, because the sentence revision 9 wrote here was false.** Revision 9 claimed the `**`-splat form "stays out of the baseline, so its first use also fails on the UNKNOWN rule at the constructor." Measured, it does not and cannot: `GithubWorkItem(**{"dispatch_status": "x"})` parses to exactly **one** `ast.keyword` whose `.arg` is **`None`**, and the column name survives only as a `Dict` **key** — `dispatch_status` appears nowhere as an identifier in the call. A scan that triggers on `keyword.arg in COLUMNS` therefore never visits that constructor at all, so there is no UNKNOWN verdict to reach. The name-triggered collector returns `['dispatch_status']` for the explicit form and `[]` for the splat, side by side in one assertion — the ninth review's correction 5 is **confirmed**.

    The fix is a rule keyed on the **callee** rather than on the keyword name: **fail any call to `GithubWorkItem(...)` that carries a keyword with `arg is None`.** It refuses the splat *without* knowing which columns are inside it, deliberately — an opaque payload spread into the mutation constructor cannot be audited, so it is refused rather than inspected. Measured against six forms: both splat shapes (`**{...}` and `**payload`) fail; the explicit keyword, `GithubWorkItemResponse(**{...})`, a bare helper, and `AgentTeamSlot(preset_id=p, **slot_data)` all pass — the same write/read split 29-a1 makes for named keywords.

    **And the rule is scoped to `GithubWorkItem`, which is a measurement and not a convenience.** My first draft named four ORM models; that version **fails on arrival**, flagging two shipped and correct sites (`agent_team_service.py:107` and `:312`, both `AgentTeamSlot(preset_id=preset.id, **slot_data)`, building slots from an operator's payload). Scoped to `GithubWorkItem` the count is **0**, so the rule ships green with the scan. The scoping is principled because `GithubWorkItem` is the **only** class in `app/models/database.py` that declares any of `dispatch_status`, `pending_reason`, or `escalation_reason` — so it is the only constructor through which an unaudited splat could introduce one of these values. `AgentTeamSlot` carries none of the three, and flagging it would enforce scope this criterion never claimed. 29-a2 gains `GithubWorkItem(**{"dispatch_status": "x"})` → **write-form violation** as an eleventh synthetic case, plus the `AgentTeamSlot` splat as its negative control.

    29-b. **The behavioural path test, narrowed to what it can prove.** A table-driven test, one fresh database per case, executing each PR2 path capable of writing one of the three columns and asserting the written value is declared: `pr_ready` (open / merged / closed-unmerged / no-match / two-open / unclassifiable), `pr_opened` (open / merged / closed-unmerged), the verifier's closed-unmerged condition (§5.6b), the auth-mode refusal (§5.6a), and the no-dispatchable-workspace refusal (§5.7). Each case runs in its own `db` fixture and asserts on rows it created itself. It promises **"these paths produce declared values"** — not exhaustiveness, which 29-a1 supplies instead. The claim that an omission from this table is self-revealing is withdrawn; it was false.

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
| head stays `deck/<slot>/issue-<n>` (revision 6's name) | **46h** — attempt 2 rediscovers the closed PR and escalates a second time |
| head is a **child** of the legacy ref, `deck/<slot>/issue-<n>/<nonce>` (revision 7's name) | **46p** — Git refuses the ref outright |
| the slot's display name is interpolated into the ref instead of `slot-<slot_id>` | **46q** |
| the nonce is truncated to 8 of its 16 hex characters | 46i — halving the attempt identity for no benefit; the composed name must match the stored nonce in full |
| attempt suffix matched as any `[0-9a-f]{8}` rather than against `item.dispatch_nonce` | **46i** |
| NULL `dispatch_nonce` falls back to the unsuffixed head | **46j** |
| the brief prints the unsuffixed branch name | **12** — asserts the actual nonce appears |
| `report_pr_opened` records `pr_number` before classifying the PR's state | **11b, 11c** |
| `_classify_pull` duplicated rather than shared across the three call sites | **11d** — the sentinel is not consulted on every path |
| classification runs before the repository check | **11e** — a foreign merged PR is accepted as the outcome |
| `pr_closed_unmerged` on the `pr_opened` path still sends the design-review mail | **11c** — asserts zero mail rows |
| `unknown`/`ambient` scope with a stale id mints from the id | **30d, 30e** |
| two-or-more-merged treated as a `409` | **46k** |
| `queued_auth_mode_unresolved` declared in `DISPATCH_STATUSES` rather than as a `pending_reason` | **29-a** — the status set no longer equals its expected literal |
| `pr_closed_unmerged` added to `DISPATCH_STATUSES` | **29-a** |
| `prepared_owner_unavailable` implemented as a new `dispatch_status` | **29-a** — the status set no longer equals its expected literal, which is how the standing no-new-status rule is carried |
| `prepared_owner_unavailable` omitted from `ESCALATION_REASONS` | **29-a** (the set no longer equals thirteen) **and 37n-3/37n-4 at runtime** — `_apply_escalation`'s validation rejects the reason, so the escalation raises and the torn item stays `pending`, re-escalating every poll |
| `prepared_owner_unavailable` added to `_PR_OPENED_RECOVERABLE_ESCALATIONS` | **37n-8** — a `pr_opened` report from the previous owner's still-live pane clears the reason and lands the item in **`verifying`**, the auto-merge pipeline's input, with the owner still gone and no notification sent |
| a PR2 path writes an **undeclared** `dispatch_status` literal | **29-a1** — the AST scan sees the literal wherever it is written |
| a PR2 path assigns `escalation_reason` directly, bypassing `_apply_escalation` | **29-a1** — asserts exactly one non-`None` assignment site |
| `_apply_escalation` accepts an undeclared reason | **29-a1**'s runtime validation at the funnel |
| a new writer added in a new module, with a declared value | **29-a1** — the per-file site-count baseline moves |
| the scan collects keywords **by name**, so `GithubWorkItemResponse(...)` counts as three writes (revision 8's design) | **29-a2** — the response constructor must classify as *not a write*; and 29-a1's `escalation_reason` count reads 6 non-`None` sites instead of 1 |
| an unrecognized call form is **skipped** rather than failing | **29-a2** — `update(...).values(...)`, a bare helper, and an aliased response model must all land in UNKNOWN |
| a new namespace write introduced via `setattr(item, "dispatch_status", v)`, following the existing idiom at `agent_team_service.py:377` | **29-a2**'s `setattr` baseline — the AST scan itself cannot see this form, which is why the baseline exists |
| a namespace write introduced as `GithubWorkItem(**{"dispatch_status": …})` or `GithubWorkItem(**payload)` | **29-a2**'s callee-keyed splat rule. The name-triggered collector cannot catch this — measured, `keyword.arg is None` and the column name survives only as a dict key — so revision 9's claim that it "fails on the UNKNOWN rule at the constructor" was false and this row replaces it |
| the splat rule keyed on the keyword **name** rather than the callee | **29-a2** — the splat case returns clean while the explicit-keyword case is caught, so the two synthetic rows disagree |
| the splat rule extended to every ORM model rather than `GithubWorkItem` | **29-a1** fails on arrival: `agent_team_service.py:107` and `:312` (`AgentTeamSlot(preset_id=…, **slot_data)`) are legitimate and carry none of the three columns |
| `update(...).values(dispatch_status=…)` reclassified as a *supported* write form, per revision 9's summary line | **29-a2** — the form must land in UNKNOWN; there are **0** such sites today, so nothing legitimate is refused by failing it |
| `PENDING_REASONS` asserted as a closed set | **29-a** — `agent_teams.py:785`'s operator free text makes equality unsatisfiable; the test asserts membership only |
| leave `in_progress`'s `pr_number` write in place (today's code) | **29b** |
| route `in_progress`'s `pr_number` through verification instead of dropping it | 29b — the report must succeed *and* leave the column NULL |
| open a second PR on a retried `pr_ready` | 16 |
| handoff leaves the previous owner's identity in place | 26 |
| `GH_TOKEN` reintroduced into `extra_env` "for convenience" | 25 |

**Tests 29c-50 live in this file too**, and are specified where their design is argued rather than repeated here: 29c, 29d, 29e in §5.6b (the verifier's closed-unmerged condition), 30-37 plus 30b, 30c, 31b, 37b, 37c in §5.6a (per-repo auth mode, the persisted installation id, and the transient-failure refusal), 38-46 in §5.5.4 and 46b-46g in §5.5.4a (`pr_ready` reconciliation and match classification), 47-50 plus 49b in §5.5.5 (title, body, draft, and the base-ref normalization). Their mutation tables are with them, for the same reason: a mutant list separated from the guard it describes goes stale silently.

Revision 4 closed this section with a paragraph defending a `release_by_token` mutation row. That row is **gone** — §5.7 no longer leases the primary at all, so there is no release call to distinguish and no untestable guard to excuse. The paragraph is deleted rather than reworded, because the honest summary is simply that the design change removed the problem.

### 5.9 Deployment (gated, manual, not part of the PR)

**Step 1 — reset every scope that resolved before the App was installed.** This is first because skipping it makes every later step measure the wrong thing. §5.6a's mode is sticky by design: a scope that resolved `ambient` keeps dispatching under the human's ambient credential forever, and nothing re-resolves it (§7 records the missing operator control). So an operator who installs the App and immediately tests the bot-authorship gate will see a human-authored PR and conclude the App is misconfigured — when the real cause is a cached `ambient` from before the installation existed.

Before testing anything, set the affected scopes back to the state that means *resolve now*:

```sql
-- inspect first
SELECT id, repo_owner, repo_name, github_auth_mode, github_app_installation_id
  FROM team_github_scopes;

-- then, for each scope on a repo the App was just installed on:
UPDATE team_github_scopes
   SET github_auth_mode = 'unknown', github_app_installation_id = NULL
 WHERE repo_owner = ? AND repo_name = ?;
```

Both columns, not just the mode. §5.6a's state table now *does* define `unknown` with a stale id — it normalizes the id to NULL at the next lease — so clearing it here is no longer the difference between defined and undefined behaviour. It is still the right `UPDATE` to write: it makes the operator's intent explicit in one statement rather than relying on a self-healing rule to tidy up afterwards, and an operator reading the row back sees the state they asked for. The next dispatch re-resolves and writes `app`. `unknown` is the only value that means "ask again"; `ambient` means "already asked, the answer was no."

This must happen while **no dispatch is in flight** on those scopes, since a live `app`-mode lease reads the id the `UPDATE` clears. With autonomy off (§6) that is the normal state, but check `github_workspaces` for a non-NULL `leased_item_id` first.

**Step 2 — restore tizonia branch protection.** The hard gate the soak log records. The backup exists at `/tmp/tizonia-master-protection-backup.json` (`required_approving_review_count: 1`, `enforce_admins: true`). **Copy it somewhere durable first** — `/tmp` is not a safe home for the only copy of a gate. Restore only after PR2 is deployed, step 1 is done, and a bot-authored PR has been observed to be approvable by `juanrubio`.

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
- **Timing-safe token comparison as a tested property.** Enforced by review in PR0 (§3.7), not by a test. Applies to both PR0 credentials. Note the boundary §3.7 draws: a comparison that is outright *wrong* (`startswith`, `in`, a truncating slice) is caught by tests 20's prefix and trailing-byte rows; only right-but-not-constant-time is invisible, and that residue is what this defers.
- **A frontend workspace-lease UI, and how it would get the operator token.** No such UI exists — measured while writing §3.8: `frontend/src` contains no reference to force-release, to `lease_token`, or to the workspace routes at all, so §3.6a's dependency currently gates routes whose only callers are backend tests. When the UI is built it needs the operator credential in the browser, which means an operator paste into `sessionStorage` (the §3.6 pattern) or a server-side injection — a real decision, and cheaper to make against a real screen than in advance. Recorded here so the next person does not read the `require_operator` requirement as implying UI work that PR0 does not contain.
- **Operator authentication that survives a co-resident adversary.** §3.6a states plainly what `X-Deck-Operator-Token` is worth on this host: the backend and every pane run as `juan`, `hidepid` is absent, `/proc/<backend>/environ` is readable, and `.env` is `600` owned by the same user. A pane that goes looking can read the token. Closing that needs a separate uid for agent panes, or `hidepid`, or a real user-authentication layer — the same OS-level isolation §6 already scopes out. What ships is a boundary against an opportunistic agent, not a determined one, and §8's criterion is worded to match: *not reachable by an agent following its brief*. **What is not deferred is the storage location**, because that decides whether the bound above is real: measured, the tmux server holds the backend's whole environment as its global environment and any pane reads it with `tmux show-environment -g`, so an exported token would be reachable by an agent following *any* brief. §3.6a states `backend/.env` as a requirement with that measurement attached, not as a preference.
- **~~Making `release_by_token`'s guarantee structural.~~ Withdrawn in revision 14 — it is now PR1 work (§4.6a.1).** Recorded here rather than deleted, because *why* it was deferred is the more useful artifact. Revision 13 measured the race, wrote it down, and deferred it on the grounds that "the window is a DB round trip, not two `git` subprocesses." That was measured at `release_by_token`'s own await and the guarantee is stated about the **route**: the window runs from the owner check at `agent_teams.py:334` to the write at `:363`, and `release_blocker` awaits `self._runner` twice inside it — the same two `git` subprocesses as force-release. **A guarantee is measured at the boundary it is stated about, not at the helper's internals**, and a severity argument taken at the wrong boundary reads as a bound while providing none. The second half of the deferral — "the caller is an agent reporting on a lease it holds" — was also load-bearing and also wrong under this design's own no-rotation decision: the ex-owner still holds the token by construction (§4.6a's five-row table).
- **Enforcing tokens by default.** PR0 ships with `mail_capability_tokens_required = False` because a running shim cannot learn a new header without a restart (§3.4). Flipping the default to `True` is a follow-up once no pre-upgrade shim can exist, and it should be a one-line change plus a release note.
- **Non-tmux agents.** §3.3 mints an unbound token when the caller has no tmux ancestor, so such a session can send mail but can never approve. Binding them needs a different channel (a launch-issued code, or OS credentials) and no such agent exists in this deployment today.
- **A decision UI for the operator.** §4.3a gives the leader a tool and exposes `decision` in the API (§4.6), but adds no approve/reject control to the Deck frontend. An operator who wants to approve does it by merging, per §3.6. A UI button would need the operator to act *as* the leader member, which is exactly the actor/member distinction PR0 draws — worth doing, and a separate decision. **The eighteenth review's blocker 1 is the evidence that this deferral is load-bearing rather than tidy:** the PR0 plan reached for operator-as-member to solve the much smaller problem of replying in a thread, and the reply did not need it (§3.6b). A decision button would need it for real, which is why closing this deferral means designing persisted authentication provenance first — amendment C's item 1 — and not adding a button.
- **Pruning per-tab UI actors.** §3.6 accumulates one `mail_external_actors` row per operator tab. Inert, but noisy in the roster over months. A `last_used_at` sweep is the obvious fix and is not in PR0.
- **Re-resolving a scope's auth mode.** §5.6a writes `github_auth_mode` at lease time when the lookup answers, and leaves it `unknown` when it does not. Nothing re-resolves a mode that is *already* set: a scope recorded `ambient` before the App was installed keeps dispatching under the human's credential until an operator clears the column. §5.6a explains why this is the safe direction (a stale `app` is caught by the author check; a stale `ambient` is merely the pre-PR2 behavior), but the operator has no control for it — no UI, no endpoint, only a manual `UPDATE`. A "re-check auth mode" action belongs with the workspace UI and is not in PR2.
- **A cross-process lock for PR creation.** §5.5.4 serializes creation with the lease token plus a per-item `asyncio.Lock`, which is correct for one uvicorn process (today: PID 2206652, single worker). Two workers or two hosts would each hold their own lock, and the reconcile-before-create step becomes the only defense — it narrows the window to the round trip between `list_pulls_for_head` and `create_pull` but does not close it. Closing it needs a DB-level advisory lock or a unique constraint on (item, head), and SQLite gives neither cheaply. Stated so a future multi-worker deployment knows what it inherits.
- **Retiring the `pr_opened` path.** Once App auth is provisioned everywhere, `pr_ready` makes `pr_opened` and most of §5.6 dead code. Removing it is a cleanup that should wait until no scope depends on the ambient-credential flow.
- **The spec's structural sweep stays out of the repo.** The tenth review's third correction asked whether the checker that validates this document — balanced fences, resolvable §-refs, every bolded test id in a mutation row defined somewhere, every `file.py:NNN` citation in range — should live in the repo. Deliberately **no**, on the stated condition: it belongs in the repo only if it becomes a maintained CI invariant, and it would not be one. It validates *one* document that stops changing when this design ships, its rules are tuned to this document's conventions (the bare-numeral-at-cell-boundary rule exists because measured quantities are bolded mid-cell here), and an unmaintained checker in CI is worse than none — it fails on the next spec that does not share those conventions and gets disabled, taking its credibility with it. What survives instead is the class of defect it catches, written into §5.8 as test-level requirements: cited ids must resolve, cited line numbers must be in range. Those are checkable by a reader without the tool. The tool itself is in `/tmp` and its output is quoted where it is load-bearing; if a future spec wants the same discipline, it is 200 lines and re-deriving it against that document's conventions is the honest cost.

## 8. Success criteria

1. An agent cannot post a message as another member: the §1.5 forgery returns `403`.
   1b. An agent cannot obtain a token bound to a slot it does not occupy: the §1.6 forgery (a Specialist pane claiming `team_slot_id: 4`) returns `403`.
   1c. An unauthenticated caller cannot forge another member's liveness or silence a `brief_unread` escalation through `GET /agent/inbox`.
2. A self-ack cannot set `ack_received_at`, and the live shape (`context_request` 16→16 answered by 16) is refused by a regression test.
3. Only the designated leader member's own answer can approve — not any non-owner, and not a member with no slot.
   3b. **A reply is not an approval.** Only an explicit `decision = 'approved'` written by the leader satisfies the gate; live rows 82 and 92 — the Leader refusing in prose — are refused by regression tests, and row 40's genuine approval is accepted despite containing negative words.
4. Evidence from a previous dispatch attempt cannot approve the current one, across both retry and handoff.
5. Every recorded ack names its approver, the message that proves it, and the round it belongs to — and the evidence reaches **each reader through its own projection**. All **six** new columns reach the operator (response model **and** serializer, both hand-enumerated); the three the approver acts on — `ack_approval_round`, `ack_enforcement_epoch`, `dispatch_head_ref` — reach the leader through `deck_list_work_items`'s separate re-projection; and `mail_messages.decision` reaches `deck_check_inbox` through the model alone, because that tool splats. Revision 8 named two surfaces and would have shipped a gate whose evidence the designated approver could not see (§4.6, test 37q).
6. Auto-merge cannot happen without a valid distinct approval, and failing that check falls back to human merge stickily, without escalating.
7. A bot-authored PR is approvable by `juanrubio`, so branch protection can be restored to `required_reviews=1, enforce_admins=true`.
8. Commits and PR titles identify which agent produced them, on the reuse path as well as the spawn path. **Branch names identify the slot the attempt was *prepared for*, which is not the same claim** — after a handoff the ref still names the origin slot while `owner_slot_id` names the current one, and both are correct because the ref is fixed for the attempt's lifetime (§5.5.4a). Revision 9 stated this criterion as though the ref tracked the producer; measured, it cannot, since `accept_handoff` moves ownership and sends no replacement brief. Who is working on an item is answered by `owner_slot_id` and by nothing parsed out of a ref.
9. `pr_number` is never taken on trust, on **any** path: Deck reads it from its own `POST /pulls` response; the legacy `pr_opened` path refuses a PR in the wrong repo or on an unexpected branch; and `in_progress` no longer writes the column at all (§5.6), so it cannot plant an unverified PR or silence the ack gate through `_ack_satisfied`'s `pr_number` short-circuit.
10. **No pane holds a *persistent* GitHub credential.** No `GH_TOKEN`, no `GITHUB_TOKEN`, nothing in `extra_env`, nothing written to disk in the working tree, and no log or brief containing the App private key. The credential an agent can reach is minted at use time, scoped to one repository, expires within the hour, and dies with the lease.
    **This is deliberately weaker than revision 3's claim** that "no pane ever holds a token." That was not achievable: git receives the helper's plaintext password on every push, and an agent with a shell can run `git credential fill` and read it. Since the agent must push, some reachable credential is unavoidable. What PR2 guarantees is the four properties above — short-lived, repo-scoped, unpersisted, not inherited in the pane environment — which is what actually bounds the damage. Claiming absence would have been a claim a reviewer could disprove in one command, and a success criterion that can be disproved in one command is worse than a modest one that holds.
11. **PR0's Agent Mail enforcement** changes no behavior until the operator enables it; PR1's gate refuses to merge while enforcement is off, **and no approver evidence is recorded during that period** — so flipping the flag cannot legitimize anything written before it.
    **Scoped deliberately to the mail half, because the rest of PR0 is not inert.** Revision 12 stated this criterion over the whole PR while assigning `require_operator`, force-release's body change, and the `lease_token` projection deletion to PR0 — none of which the flag governs (§2.1, §3.6a). A success criterion that claims more than the PR delivers is not met by the implementation; it is met by nobody, and the failure surfaces as a release note that reads "no behavior change" over an API break. Met when the release notes state both halves separately and the operator token is configured before the PR0 backend starts.
12. A human's primary checkout is never given an agent git identity, and refusing it does not strand the item: a primary is **excluded from the dispatch scan**, so it is never leased at all, and the next dispatchable worktree is leased on the first attempt.
13. Every new guard is shown to bite by mutation, and the guards that cannot be tested (`hmac.compare_digest`, a per-item lock's global/per-key distinction) are named as review items rather than claimed as covered.
14. **Every `/dispatch-status` branch states who may report it — including the one revision 5 added and forgot to authorize.** Authentication is not authorization: an agent that is not the item's owner, leader, or handoff target is refused, the refusal happens before any state change, and **both** GitHub-writing branches — `pr_opened` and `pr_ready` — appear as owner-only rows in §3.5a's matrix and require the current lease token, checked before any GitHub call or item mutation. A status absent from that matrix is the defect: it defaults to *allowed* in any implementation whose resolver falls through.
15. **A rejection has a workable next round, opened by the rejection itself.** One `deck_approve_work_item(decision="rejected")` clears the previous round's approval and opens the next, in one commit and with no second call by anyone; the owner recovers by sending a fresh `deck_request_context` and nothing else; the previous round's approval no longer satisfies the gate; and `max_approval_rounds` still bounds the loop, leaving the counter on the last round that really opened (§4.2a, §4.3a.1).
16. **A tmux pane Deck did not launch keeps working.** It registers, mints an unbound token, and can send mail; it can never approve. `bind_pending` is reserved for a pane that claims a Deck launch (§3.3a).
17. **A transient GitHub failure never silently changes authorship.** An unresolved installation lookup refuses the dispatch and leaves the workspace unconfigured, rather than falling back to the human's ambient credential (§5.6a).
18. **A crash between `create_pull` and the commit does not produce a second PR or an orphaned one.** The retry reconciles by head/base, adopts the existing PR through §5.6's checks, and records its number (§5.5.4).
19. **A design PR is immediately reviewable.** It is created non-draft, because nothing in the design path would ever mark it ready, and a draft PR cannot be approved (§5.5.5).
20. **Deck's PR calls speak GitHub's vocabulary, not git's.** `scope.base_ref` is a refspec (live value `origin/master`, column default `origin/HEAD`) and every existing consumer treats it as one. It is normalized to a branch name before it reaches `create_pull` or `list_pulls_for_head`, in one shared helper, so the base filter cannot silently match nothing (§5.5.5).
21. **An App-mode workspace survives a backend restart.** The installation id is persisted beside the mode it implies, so a live lease whose in-memory cache was lost still mints a credential — without re-resolving, and without a lookup call from the credential helper. An `app` scope with no id refuses rather than falling through to the human's credential (§5.3a, §5.6a).
22. **A PR is classified before it is used on *every* path, and a PR closed by a human is never presented as ready.** Reconciliation adopts only an open match, reconciles a merged match to `merged` without asking anyone to review it, and escalates `pr_closed_unmerged` on a closed-unmerged one; the verifier applies the same condition to a PR closed *after* adoption, before any check-run call or draft-to-ready mutation; and the **legacy `pr_opened` path** classifies the reported PR too, so an `ambient`-mode repo cannot produce the false design-review broadcast either. All three call the **same** `_classify_pull` helper — the criterion is not met by three correct copies, because revision 6 had two correct copies and one missing one. That helper classifies on **`(state, merged_at)`**, the only pair present in both the list and single-pull response shapes: `GET /pulls` omits `merged` entirely (measured), so a helper keyed on it is broken on the very path reconciliation uses. The pair must be **present and coherent**, not merely truthy: `merged_at` is checked for presence before it is read, because absence means *unreadable payload* and not *did not merge* — measured present in 105 of 105 live entries — and `state="open"` with a non-null `merged_at` refuses rather than picking the field it prefers. An unrecognized, absent, or self-contradictory state refuses rather than defaulting to open, and the refusal **consumes the verification retry budget** — a fail-closed branch that returns without incrementing is the unbounded loop of §5.6b wearing a safety label. Closed history does not make a live PR ambiguous, and no new `dispatch_status` value is introduced (§5.5.4a, §5.6, §5.6b).
23. **An escalation that is reported is an escalation that is durable.** A rejection at the approval cap persists the leader's decision and the escalated state in one commit, so a failed notification loses the notification and nothing else. Measured against the alternative: the item stays `dispatched` with a live `ack_received_at`, which the monitor reads as an approved plan (§4.3a.1).
24. **A closed PR does not trap a work item.** One operator `deck_retry_work_item` after a `pr_closed_unmerged` escalation produces a usable open PR, because the retried attempt pushes an attempt-scoped head that no closed PR is attached to. Deck neither reopens a PR a human closed nor opens a second PR on that PR's branch (§5.5.4a).
25. **Namespace growth is caught statically, per column, with an honest promise for each — and the scan can tell a write from a read.** `dispatch_status`'s set of written literals is unchanged by PR2 and `escalation_reason` has exactly one validated write funnel, both asserted by an AST scan over `app/` that classifies the **enclosing call** rather than the keyword name, treats any unrecognized call form as a **failure**, and covers the two mutation forms no name-based scan can see: a pinned `setattr` baseline, and a **callee-keyed rule refusing any `**`-splat into `GithubWorkItem(...)`** — measured necessary, because a splat keyword has `arg is None`, so the name-triggered scan never reaches that constructor and revision 9's claim that it would was false. The splat rule is scoped to `GithubWorkItem`, the only model declaring these columns; broadened to other models it fails on two legitimate shipped sites. `update(...).values(...)` is UNKNOWN-and-failing, one stated policy rather than two, with **0** such sites today so nothing legitimate is refused (§5.8 tests 29-a1, 29-a2). Keyword-name collection alone does not meet this criterion: measured, it counts `GithubWorkItemResponse(...)`'s three serializer fields as writes and fails four of its own assertions against the current tree. `pending_reason` is explicitly **not** a closed set, because `agent_teams.py:785` already writes operator free text; the criterion for that column is that PR2's own reasons are declared, not that the column is exhaustive. Not enforced by a runtime membership test, which cannot distinguish a constant from the identical literal, and not by a scan over other tests' leftover rows, which the per-test database fixtures make impossible.
26. **A dispatched agent is told the branch it must push, and that branch is durable before it is told.** `prepare_attempt` commits the attempt's whole identity — owner, routing, nonce, head, round 1 — in **one** commit before the brief is composed, mailed, or injected into a pane. The name in the brief and the name `pr_ready` accepts are not composed twice and compared; they are **one stored value**, written once and read everywhere (§4.2a, §5.5.4a). A crash before launch reuses the prepared attempt rather than minting a second identity, and a partially prepared row refuses rather than being repaired by guesswork. **Reuse covers the routing decision, not just the nonce:** a prepared item is briefed and launched against the slot it was prepared for, even when a label edit or a disabled slot would route it elsewhere on the next poll — measured, both triggers re-route the real `route_item`, and under the recompute the brief reaches a second slot while the first keeps a committed brief for the same branch and then loses ownership of it at `:332`. Only `reset_for_retry` authorizes a new attempt; its clear sits below the deferred-branch return so a still-leased attempt keeps its identity, and it lives **in that function** rather than in the retry route, because two of its three callers have no operator in them (§4.8 tests 37h-37p).
27. **The attempt ref is a sibling of any legacy ref, never a descendant, and no display name reaches it.** Verified against real `git` in both orders: a child-shaped name is unstorable, and it makes the legacy name unpushable too. Slot identity in a ref is the numeric `slot_id` (§5.5.4a, §5.8 tests 46p, 46q).

28. **A handoff moves who is working on an item and never moves what they were told to push.** The attempt's head is immutable for the attempt's lifetime: `accept_handoff` changes `owner_slot_id` and sends no replacement brief, so the expected head must be a **record** rather than a value recomposed from the current owner. Measured with both designs side by side against the real `initiate_handoff`/`accept_handoff`: the composed form refuses the new owner's valid branch with an expectation no brief ever named, permanently; the stored form accepts it. A NULL head refuses `stale_dispatch` rather than composing one (§4.1, §5.5.4a, §4.8 tests 11f, 37o).

29. **A handoff target can finish the item it now owns, because the handoff transfers authority and not just identity.** Today it cannot, and the defect is in shipped code: `owner_slot_id` moves to the target while the lease token — delivered *only* in the launch brief, interpolated four times — stays with the original owner, and the release route requires both. Measured through the real route: the ex-owner is refused `409 only the owner slot may release its workspace`, the new owner is refused `400 lease_token required`, a guess is refused `409 lease_token does not match`, and the workspace stays leased through all three. The target's own reports cannot even record liveness, because `touch_owner_contact` returns early without the token — so `leased_owner_pid`, which `accept_handoff` never re-stamps, keeps naming the previous owner's process. Measured, the backstop does **not** read it while the item is `dispatched` (`_RECLAIMABLE_STATUSES` excludes that status), which makes the stale evidence latent rather than harmless: it becomes live the moment the item turns terminal, and until then an *alive* ex-owner pins the lease through a branch that short-circuits before any contact stamp is consulted (§4.6b).

    The criterion is met when the target obtains its work item's nonce, exact stored head, workspace path, approval round, and **live lease token** through an authenticated agent-facing **claim** — `POST .../claim-continuation`, surfaced as `deck_get_work_item_context`, §4.6a — and releases with them. "Authenticated" is now literally true rather than aspirational, and that is a change from revision 10: it said "authenticated" here while §4.6a admitted the path was not, and the contradiction resolves in *this* direction because PR0 ships `require_session_slot` before PR1 needs it. "Claim" rather than "read" because the call is a write. Asserted through the real tool, never by injecting fixture knowledge, with `deck_list_work_items`'s exact five keys as the negative control (§4.8 tests 11g, 37r, 37r-1, 37r-4, 37r-4a, 37r-7).

    **Which operation performs the repair, because revision 15 said the claim does and that is the fifteenth review's correction.** It read: *"it stamps the new owner's pane identity onto the lease, which is what repairs the stale evidence above."* §4.6b assigns the repair to `accept_handoff`, which transfers ownership and the three liveness columns in **one** commit, leaving the claim to refresh evidence that is already truthful (`:2286`, `:2376`, criteria 34 and 38). The corrected division:

    - **`accept_handoff` performs the atomic correctness repair** — ownership and the evidence about ownership are never separately observable.
    - **`claim-continuation` delivers the continuation context and the live lease token, and idempotently refreshes the already-transferred pane and contact evidence.**
    - It stays a `POST` because it writes that refresh, **not** because correctness waits for it.

    **This was not merely stale wording, and the distinction is worth stating because it is the same self-contradiction class the spec keeps finding in itself.** §4.8's mutation table already lists "the continuation claim is treated as the moment ownership becomes truthful, with `accept_handoff` deferring the write" as a **mutant** that test 37r-4 must kill — so the sentence an implementer reads to know when the work is done asserted the design the test suite is built to reject. Measured, the two readings are not equivalent: under the deferred reading, B owns the item and is working while `leased_owner_pid` still names A's dead process, and the moment the item reaches a terminal status the backstop reclaims — `reclaimed 1`, lease cleared out from under the live owner. Under §4.6b's reading, with **no** claim call anywhere, the same aged, dead-pid, quiescent, terminal row gives `reclaimed 0` and the lease stays held. The claim is a convenience; the transfer is the correctness.

    One detail of this criterion's evidence paragraph, re-verified rather than assumed, because PR1 rewrites the function it cites: "the target's own reports cannot even record liveness, because `touch_owner_contact` returns early without the token" stays true under requirement 8, but by a **different mechanism** — shipped it is a Python guard, and under requirement 8 it is `lease_token = NULL` never comparing true in SQL (measured, `0` rows). Same observable, different cause, and requirement 8 now records where the two forms genuinely disagree.

30. **The lease token is delivered on handoff, not rotated — and every consumer of it is owner-gated, including the one this design adds.** The ninth review offered two options: rotate, or prove the retained token useless. Measured, there is a third and it is the correct one — but revision 10 stated it as "**both** agent-facing consumers sit behind an owner check," and that enumeration ranged over the tree instead of over the design. `git-credential` appears **nowhere** in `app/`, so §5.5.6's helper is not a consumer the grep overlooked; it is a consumer *this spec adds*, one PR after the claim it falsifies. The corrected statement is a five-row normative table in §4.6a covering PR0 through PR2, and the property it asserts is conditional rather than observed: the retained token grants the ex-owner nothing **because** `release_by_token`, `touch_owner_contact` and the credential helper each check the current owner *in the operation that acts*.

    **Revision 13 claimed the first two of those already did, and both claims were false — measured, not re-read.** This is the thirteenth review's blocker, and it is broader than reported. Revision 13's table said `release_by_token` gives an ex-owner `403` "before the token is read" and `touch_owner_contact` is "never called," on the strength of two real checks at `agent_teams.py:334` and `:371-373`. Neither check is in the same operation as the write it authorizes. Interleaving a real handoff at an await each branch actually has: the ex-owner's release returns **`200`** and clears B's live lease (`leased_item_id=None token=None`), and the ex-owner's `blocked` report **does** reach `touch_owner_contact` with the retained token and stamps the lease's liveness evidence. A point-in-time comparison is not a control, so PR1 puts the owner predicate in **both** writes (§4.6a.1 requirements 2 and 8). The two are bounded differently and the criterion keeps the distinction: the first destroys a live lease; the second delays a backstop reclaim on a lease whose owner changed legitimately, and has no reader at all until the item is terminal. **What makes this criterion true is the `EXISTS (… owner_slot_id = derived)` clause in each write, and only that** — measured, the release write without it matches `1` row after a handoff and with it matches `0`, because no-rotation means the token is still the live one.

    **Revision 14 then made a weaker version of the same mistake on the contact stamp, which is the fourteenth review's second blocker.** It required the tail's comparison to be made against ownership "re-read inside the same transaction as the stamp" *or* the stamp to carry the predicate, and called either acceptable. Only the second is a control. Measured on Deck's own engine — file-backed, `journal_mode=WAL`, configured so readers and writers do not block each other (`database.py:23-34`) — a fresh raw-SQL read returns A, B's handoff commits on another connection, and A's unconditional stamp still lands with `rowcount=1` on B's lease. **Transaction membership is not an ordering guarantee against another connection's commit**, and "re-read, then write" is the same defect class as "check, then write" at smaller scale. The criterion is met only by the conditional form, and the token belongs in it too: measured, with the owner unchanged and the acquisition replaced, owner-only matches `1` row and owner-plus-token matches `0`.

    Test 46r is what makes the credential helper checkable, and its `403` for a valid-token ex-owner is the third leg the no-rotation decision rests on. Rotation would still protect against nothing while destroying the only copy of a capability with no delivery channel to the new owner. Delivery by server-authored mail is also **not a new class of mechanism**: `remind_held_leases` already interpolates the live token into a message whose recipient is resolved from the *current* owner. It cannot simply be reused, because it is gated on `_RELEASABLE_STATUSES` and `'dispatched'` is not in it — measured **0** reminders and **0** messages throughout the target's entire working life — and widening that gate would fire release reminders at agents mid-work, contradicting the function's own purpose (§4.6a, §4.6a.1, §4.8 tests 37r-1, 37r-6, 37r-8, 37r-9, 37r-10).

31. **The continuation claim derives its caller from PR0's kernel binding, and `reporting_slot_id` is never an authority input.** Revision 10 wrote this criterion as an honesty statement — the endpoint is "owner-checked, matching `agent_teams.py:334`," with the spec admitting plainly that the check is not authentication. Both halves were wrong in the same way, and the way is blocker 1: **the measurement was taken on pre-PR0 `master` and written into a PR that lands after PR0**. There is no capability token on the dispatch surface *today*; PR0 adds one, and PR1 is where this endpoint ships. A design that declines authority its own earlier PR has already supplied is not being modest, it is being stale.

    The corrected criterion: the claim route depends on `require_session_slot`, which reads `X-Deck-Session-Token`, resolves the session, confirms the pane binding, and projects `(session, member, slot_id)` — refusing with `401 capability_token_required` / `401 capability_token_invalid` / `403 bind_unverifiable` / retryable `409 bind_pending` (§4.6a's four-row table). `reporting_slot_id` in the body is corroboration only: an agreeing value is accepted, a disagreeing one is `403 slot_claim_mismatch`, and an absent one is filled from the derivation. Under the grace window before tokens are enforced the route returns `409 tokens_not_enforced` rather than handing out a bearer secret on an unauthenticated call.

    The second error was citing `agent_teams.py:334` as the owner-check precedent to match. That line compares `report.reporting_slot_id != item.owner_slot_id` — a **caller-supplied** value against a stored one, which is the pattern this criterion exists to stop, not a model for it. The registration measurement behind that judgement stands and is retained where it is load-bearing (§4.6a, §5.5.6): one slot's process registering as another is *named* as that other slot, because `_slot_matches_registration` compares only `provider` and `repo_id` — identical for every slot on one repo — with the different-`cwd` control refused down to `participant_kind='repo'`. Real discriminating power at repo granularity, none at slot granularity, which is the granularity every owner check in the dispatch flow is written at.

    Two consequences from revision 10 are withdrawn as unnecessary rather than accepted (§4.6a), one is retained and narrowed, and the `:569` `lease_token` projection is **deleted outright** — revision 11 left it as an obligation with a constraint ("it must leave the agent-reachable projection *and* stay reachable to the operator, because force-release requires `expected_lease_token`"), which was a real constraint under revision 11's force-release contract and stops being one under revision 12's: §4.6a's decision removes the token from that contract, so the projection has no remaining consumer and the fork revision 11 left open is closed by deletion rather than by relocation (§2.1, criterion 32). The endpoint is a **`POST .../claim-continuation`**, not a `GET`, for three reasons: the response holds a live bearer secret, the call is not nullipotent, and it refreshes the owner's liveness evidence — **not**, as revision 11 had it, because it is the only place that write can live. §4.6b puts the authoritative write in `accept_handoff`, where PR0's dependency has already verified the accepting pane. And because the old check read a column the caller population can write, `initiate_handoff` ships its **missing owner check** — on the *derived* slot, refusing `403 not_item_owner` per §3.5a point 4a — plus application-level target validation, in the **same** PR: measured, a non-owner from another preset takes ownership in two calls, and the only existing validation on the target is a **pragma-dependent** FK surfacing as an uncaught `IntegrityError`, a 500 (§4.6a, §2.1, §4.8 tests 37r-2, 37r-2a, 37r-3, 37r-5, 37r-7).

32. **An operator route is one an agent following its brief cannot reach — and the spec says exactly that, not more.** Revision 11 wrote "operator only" and implemented it as *absence*: no dependency, on a surface described as "unauthenticated but human." Measured, that surface does not exist — `agent_teams.py` has **zero** non-`get_db` dependencies across all 27 `Depends(...)` — and every pane in this deployment has `curl` and loopback, so omission from the MCP shim decides which tools an agent has and not which URLs it can POST.

    The criterion is met when `require_operator` (§3.6a) gates force-release and the workspace listing in PR0 and `resume-attempt` in PR1, comparing `X-Deck-Operator-Token` with `hmac.compare_digest`; when a tokenless caller, an agent's own session token, and a **self-provisioned external-actor token** are each refused, the last mattering because measured, `POST /external/agent-mail/actors` mints a working 43-character `kind='supervisor'` token with no credential at all — **an authentication scheme is only as strong as the cheapest way to obtain a credential**; and when force-release neither **requires** nor **discloses** an agent's bearer lease token: `force` plus `expected_leased_at` replaces `expected_lease_token`, `lease_token` leaves `GithubWorkspaceResponse`, and the mismatch body contains neither the supplied nor the stored value. The disclosure was measured on the wire, not inferred from the f-string — two unauthenticated calls, guess then replay, force-release any agent's workspace today.

    **And the criterion is bounded deliberately.** It says *following its brief*, because on this host the backend and every pane run as `juan`, `hidepid` is absent, `/proc/<backend>/environ` is readable, and `.env` is mode `600` owned by that same user — so a pane that goes looking can read the token. What the dependency buys is the difference between *knowing a published URL* and *deliberately reading another process's memory*: the first happens by improvisation, the second does not. Claiming more would make this spec's own [[check-name-vs-discriminating-power]] mistake one layer up, in a dependency whose name invites the stronger reading. The stronger boundary is deferred to §7 and belongs to OS-level isolation, which §6 already scopes out (§3.6a, §3.7 tests 20-22, §4.8 test 37n-11).

    **The bound is also conditional on where the token is stored, and that condition is now a requirement rather than an assumption.** "Deliberately reading another process's memory" describes `/proc/<backend>/environ`. It does not describe `tmux show-environment -g`, which is one documented command in a shell every agent already has — and measured, the tmux server inherits the environment of whatever process started it (`spawn_session` runs `subprocess.run(["tmux", ...])` with no `env=`), a pane can read that global environment back, and the live server already holds six secret-shaped keys this way. So an operator token exported into the backend's environment would collapse this criterion from *opportunistic adversary* to *no adversary at all*, while every sentence above it stayed literally true. §3.6a therefore **requires** `backend/.env` and forbids exporting: measured, `pydantic-settings` reads `env_file` without writing `os.environ`, so the value never reaches the tmux server at all. A criterion whose truth depends on a deployment detail has to name the detail.

33. **PR1's authorization is not switchable off from outside PR1.** PR0 keeps a tokenless fallback so a shipped shim survives its deployment, and that fallback is a bypass of everything PR1 asserts: measured, `initiate_handoff` performs four assignments and a commit with **no authorization of any kind** (`github_dispatch_service.py:689-695`), so while `mail_capability_tokens_required` is false a tokenless caller claims owner A, hands off to B, accepts as B, and then presents B's now-legitimate session to the strict continuation endpoint. **A strict read does not repair a forgeable write.**

    Met when, with PR1 installed, **every** `/dispatch-status` call returns `409 tokens_not_enforced` while the flag is false — the whole route, not a per-status allowlist. No allowlist, on a measured basis rather than out of caution: `triaging` looks like the safest branch and writes `status_note` (`agent_teams.py:296-300`), which is the field §4.2b.1's operator recovery instructions are delivered in (`:1038`), so the most innocuous branch is the one that erases the instruction telling the operator not to retry. Met also when the deployment ordering is followed — deploy PR0, restart panes, enable enforcement, then deploy PR1, autonomy off throughout — because a correct implementation deployed in the wrong order exhibits precisely the bypass it removes (§3.5a, §2.1, §4.8 test 37n-12).

34. **A handoff leaves no window in which the recorded owner is a process that no longer exists.** `accept_handoff` writes `owner_slot_id`, `routing_method`, `leased_owner_pid`, `leased_owner_proc_start` and `lease_last_owner_contact_at` in **one** transaction, taking the pane identity from `require_session_slot`'s verified binding and never from the request body. Revision 11 instead cleared the three liveness columns and waited for the continuation claim to stamp them, on the stated grounds that "the accepting call may arrive from anywhere" — a measurement of `master` written into a PR that lands after PR0, in the section that names that exact error class.

    The cost of the two-step design was measured, and it is not a window but the absence of one: a terminal item whose workspace has a NULL owner pid is reclaimed at **no age** — `0` released at 1h, 9h and 90 days — while the identical row with a dead pid recorded releases `1`. `_owner_process_is_alive` returning `True` on NULL is fail-safe for a live B and fail-open for a dead one, and revision 11 stated only the first half. **A prompt is not a bound, because making the follow-up call is exactly what a crashed process does not do.** The predicate is not changed — pre-column workspaces legitimately have NULL pids and flipping it would reclaim those while live; the fix is to never leave the columns NULL after a handoff. The continuation claim keeps an idempotent refresh of the same evidence, as a convenience rather than as the correctness (§4.6b, §4.8 test 37r-4).

35. **`resume-attempt` has one effective owner, one target-validation rule, and one liveness rule — and its advertised recovery is reachable.** Revision 11 claimed the route served both a disabled prepared owner and a generally wedged one; measured, the wedged case is unreachable, because `owner_offline` (`github_dispatch_service.py:760`) and `owner_idle_timeout` (`:803`) never set `escalation_reason` to `prepared_owner_unavailable`, which is the route's only accepted cause. That claim is **withdrawn** rather than implemented: an unreachable promise is worse than a missing feature, because a reader plans around it.

    `reassign_to_slot_id` is **kept**, against the review's offered removal, for a reason found by reading §4.2b.1 rather than by preference: its second PREPARED row — owner not in this preset's slots — already instructs the operator, in the `status_note` the agent and operator both read, to *move the item back into the preset via §4.2b.2*. Dropping the field would leave that row's stated recovery pointing at a route that cannot perform it.

    Met when `effective_owner = reassign_to_slot_id or item.owner_slot_id` is defined once, before any check reads it; when the target must exist, be `enabled`, and share the scope's `preset_id`, refusing `409 invalid_resume_target` — the cross-preset case being the one no FK and no existing check can catch, since `_slot_matches_registration` compares provider and `repo_id`, identical across every preset on one repo; when a reassignment permits the old owner to stay disabled (that being its purpose) but requires its recorded process to be **confirmed dead**, resolved through `agent_pane_bindings` because a pid is not a slot; and when unresolvable liveness refuses a **reassignment** while still permitting a **same-owner** resume — the asymmetry being the fail-closed direction, since only one of the two hands a worktree to a second process (§4.2b.2, §4.8 tests 37n-9, 37n-10).

36. **PR0's rollout claim distinguishes the half a flag governs from the half it cannot.** `mail_capability_tokens_required` makes PR0's Agent Mail enforcement backward-compatible; it has no bearing on `require_operator`, on force-release's request body, on the deletion of the `lease_token` projection, or on an unconfigured install's `503`. Revision 12 asserted "deploying PR0 changes no behavior" in three places (§3.2, §4.6a, criterion 11) while moving all four of those into PR0 — a claim about a PR's blast radius substituted for a claim about its behaviour, which are different properties: measured, the immediate half breaks **no shipped client** (6 backend tests, no workspace UI, §3.8) and still changes the HTTP contract.
    Met when the release notes state both halves separately, when the operator token is configured **before** the upgraded backend starts (because it is read at import time, so the alternative is a second restart), and when the two restarts are never conflated — panes restart for *session* tokens, the backend restarts for the *operator* token (§2.1, §3.6a, §4.6a, criterion 11).

37. **A force-release destroys only the acquisition the operator inspected.** The confirmation value and the destructive write are one conditional mutation, not a comparison followed by a helper call. Measured on `master`: the lease check sits above two awaited `git` subprocesses in `pending_work`, and `release(db, item_id)` selects `WHERE leased_item_id == item_id` with **no workspace id and no scope id** (`github_workspace_service.py:148-152`), so a request that inspected workspace X clears a replacement lease — including one held by a **different workspace Y**, which is broader than the twelfth review's same-item framing.
    Met when `force` is `Literal[True]` (so an ignored field is a validation error rather than a silent no-op), when the write is one `UPDATE` predicated on workspace id + scope id + captured `leased_item_id` + `expected_leased_at` + the server-captured `lease_token` issued **after** the inspection, when it clears all seven release-state columns at one `now`, when zero affected rows ⇒ `409 lease_changed` with the lease untouched and **no success log**, and when the interleaving and cross-workspace cases are both tested against rows read back rather than ORM objects (§4.6a, §3.7 test 22).

    **The captured token is mandatory rather than optional, and the "exactly one row" bound comes from the primary key.** Revision 13 got both halves wrong in the same direction — it treated `expected_leased_at` as sufficient to name an acquisition and credited the row count to `UNIQUE(leased_item_id)`. Measured: `datetime.utcnow()` returned equal values for back-to-back calls **63 098 times in 200 000 pairs**, the column has no UNIQUE and no monotonicity constraint, and a replacement acquisition with an identical `leased_at` and a fresh token stores cleanly — so a timestamp is not an acquisition identifier. And `WHERE id = <pk>` affects `1` row where the same statement keyed on `scope_id` affects `2`, so the bound is the primary key. The unique constraint is still cited, for the fact it actually proves: the many-rows case is unreachable, which is what makes the fix small. That one refuted my own prediction that two matching rows could wedge the route permanently.

38. **No test in the final suite asserts both a defect and its repair.** A test that pins `master`'s behaviour is design evidence; it stops being a test the moment it ships in the PR that changes that behaviour. Revision 11's 37r-4 required `accept_handoff` to leave the liveness columns NULL; revision 12 corrected the ending and kept an opening that asserted `inspect.getsource(accept_handoff)` mentions neither those columns nor `workspace` — an unarguable claim about implementation text, contradicting §4.6b in the same entry, in the revision whose stated purpose was removing that shape.
    Met when 37r-4's normative assertions are exclusively post-PR1, when the stale-A transcripts and the source inspection live as evidence or in a disposable pre-PR1 probe, and when the suite includes the one assertion that distinguishes the two designs: the columns are correct after `accept_handoff`'s single commit with **no** `claim-continuation` call in between, so the claim is shown to *refresh* ownership rather than *establish* it (§4.6b, §4.8 test 37r-4).
