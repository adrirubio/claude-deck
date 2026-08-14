# PR2 — Distinct Commit and PR Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Track progress with the checkbox steps below.

**Goal:** Give each dispatched slot a distinct commit identity, create App-authored pull requests through Deck, deliver short-lived repository-scoped push credentials without pane environment secrets, and make every PR registration, reconciliation, and verification path classify the same GitHub object before it can advance or merge.

**Architecture:** PR2 builds on PR0 capability tokens and PR1's durable attempt identity. At lease time Deck resolves and persists a repository's authentication mode, configures only the leased worktree, and never leases a primary checkout by default. App-mode worktrees receive a URL-scoped Git credential helper whose callback is bound to the live lease and the kernel-derived current owner. The agent pushes the exact persisted attempt branch and reports `pr_ready`; Deck reconciles by head/base, creates the PR with an installation token when necessary, classifies it through one shared helper, and records only GitHub-returned PR numbers. Ambient repositories retain the verified legacy `pr_opened` path.

**Tech Stack:** FastAPI, async SQLAlchemy + aiosqlite, Pydantic, httpx, PyJWT/RS256, `cryptography`, git worktree config, Linux `/proc` peer resolution, pytest + pytest-asyncio, the Python MCP shim, and real local git repositories for ref/config tests.

**Spec:** `docs/superpowers/specs/2026-08-05-distinct-approver-identity-design.md` — revision 19, spec commit `8d7321b`, especially §5.1–§5.9 and success criteria 7–10, 12–14, 17–22, 24–25, 27–28, and 30. Implementation baseline is integration commit `84d327f` (merged PR0 #313 and PR1 #314). This plan implements **PR2 only**.

**PR boundary:** PR0 authenticates mail and operator actions. PR1 owns the immutable dispatch attempt, authenticated current owner, continuation token, approval record, and conditional lease writes. PR2 consumes those records to configure git, mint repository credentials, create or verify PRs, and classify PR lifecycle state. PR2 does not provision a real GitHub App or modify a public repository.

## Precedence and Source Corrections

| Situation | Required action |
| --- | --- |
| Plan and spec disagree, and this plan marks a **Correction** | Follow the plan. The correction was measured against the merged PR1 tree after the spec was frozen. |
| Plan and spec disagree without a marked correction | Stop and report. Do not choose an interpretation. |
| Plan and code disagree on a function shape, dependency, transaction boundary, or caller set | Stop and report. A moved line is harmless; a changed contract is not. |

**Correction (2026-08-12, merged-source audit) — peer walk budgets.** The spec's §5.5.6 and test 46r describe an old `AgentMailService._pid_is_descendant` loop with an effective seven-hop budget and prescribe “credential 16 / mail 8.” PR0 no longer authenticates Agent Mail through that helper. The shipped path is `app.utils.peer_process.resolve_peer_pane`, whose default `_MAX_PARENT_WALK` is **32**, and `agent_mail.resolve_request_pane` uses it. PR2 must not reduce that shipped mail budget or alter the unrelated legacy `_pids_related` logic. Add a keyword-only `max_parent_walk` argument to the shared resolver, keep its default at **32**, and pass **16 only from the credential route**. Test 46r therefore asserts `credential=16` and unchanged Agent Mail default `32`, not `8`.

**Correction (2026-08-12, merged PR1 review) — `in_progress`.** PR1 review commit `bcdbb87` already removed the `in_progress` branch's `pr_number` write and added the regression in `tests/agent_mail/test_dispatch_status_tool.py` (spec §5.8 test 29b). That test currently proves the column remains NULL, but it does not call `_ack_satisfied`. PR2 makes no duplicate production edit; extend the existing test with the missing `False` consequence assertion rather than adding another test.

**Correction (2026-08-12, repository packaging audit) — direct dependencies.** The spec explicitly names `backend/requirements.txt`, but this repository also declares runtime dependencies in `backend/pyproject.toml` and locks them in `backend/uv.lock`. Add `pyjwt[crypto]` and `cryptography` to both direct-dependency manifests and refresh the lock. A requirements-only edit leaves the package metadata false.

**Correction (2026-08-12, helper placement decision).** The spec requires a small executable but does not assign a path. Put the stdlib-only helper at `backend/mcp_shim/git_credential_helper.py`. Configure git with an absolute invocation using the current Python executable, the absolute script path, the loopback Deck URL, and `--lease <token>`. The helper must need no project import path and no third-party package inside the pane.

**Correction (2026-08-12, credential-transport seam audit) — HTTPS origin is a precondition.** The spec configures `credential.https://github.com.*` but never constrains the workspace's push URL. Git does not invoke an HTTP credential helper for `git@github.com:owner/repo.git` or `ssh://...`; such a worktree would push with the pane's SSH identity and silently defeat App authorship. PR2 must not rewrite the shared repository remote. Before configuring an App-mode helper, run `git remote get-url --push --all origin`, require exactly one non-empty result, parse it as an URL, and require the exact scope repository over `https://github.com/<owner>/<repo>[.git]` with no userinfo, non-default port, query, or fragment. SSH, another host/repo, multiple push URLs, or an unreadable origin is a permanent workspace provisioning fault: set `provision_error`, disable that workspace, release only its captured acquisition, and leave the item pending so the next poll can select a later valid workspace. Ambient mode remains untouched and may use any existing transport.

**Correction (2026-08-12, persisted-App restart audit) — a durable mode is not a durable credential configuration.** An already stored `app/id` is never re-resolved or silently downgraded, but it is usable only while the configured App id is non-empty, the private-key path can be loaded for signing, and `github_app_bot_login` is non-empty. The bot login is required before an App dispatch because timeout reconciliation must distinguish a Deck-created PR from an agent-created PR on the same head. A stored App scope missing any prerequisite fails lease-time preparation with `queued_auth_mode_unresolved`, writes no config or brief, and releases the acquisition while preserving mode/id. An `unknown` scope with both App id and key absent still resolves to `ambient` as the spec requires; a partially configured App or an empty bot login remains `unknown` and refuses. A stale live helper after a backend restart gets `503 app_auth_unconfigured`; a new App `pr_ready` that needs GitHub work with an empty bot login gets `409 app_mode_bot_login_unset`. The authenticated exact-head cheap return of an already stored `pr_number` remains available because it performs no GitHub/authorship decision. None of these paths performs a lookup or mutates mode/id.

**Correction (2026-08-12, report-path compatibility audit) — `pr_opened` remains valid in App mode.** New App briefs use `pr_ready`, but the legacy route is not categorically disabled. A current owner may still report `pr_opened` on an App scope, and Task 5's repository/head/bot-author verification decides whether it is accepted. This preserves recovery for a PR opened outside the new brief without trusting its number. Every successful `pr_ready`, including the cheap idempotent path, returns the GitHub-derived `pr_number` in the `/dispatch-status` response and through the MCP tool.

**Correction (2026-08-12, cheap-path ordering audit) — idempotent does not mean unauthenticated or head-blind.** §5.5.2 requires exact persisted-head validation, while §5.5.4's shorthand table lists `item.pr_number` first. Resolve that ambiguity explicitly: route/session/lease authorization and exact `head_ref == dispatch_head_ref` happen before the cheap return; App configuration, token mint, and every GitHub call happen after it. Thus a legitimate retry works even if App settings changed, but a stale worktree cannot use a cached number to make a mismatched report look successful.

**Correction (2026-08-12, lifecycle race audit) — filesystem configuration and lease state need one sequenced transaction.** The current plain `GithubWorkspaceService.release()` is an unconditional read-then-clear by item id; there is no “existing conditional release” for Task 8 to call. Every PR2 release path must carry workspace id, scope id, item id, lease token, and the expected `leased_at` (server-captured for internal/agent release, caller-confirmed for force-release), enter the per-workspace config lock, stage the appropriate conditional `UPDATE` **without committing**, and only after one row matches remove the captured worktree config. Force-release must keep the request's `expected_leased_at`; replacing it with a fresh server read would erase the operator's confirmation control. Commit the staged release after cleanup succeeds. The uncommitted write is the cross-process row lock; “never clear DB state first” means never make the clear visible before cleanup. On cleanup or commit failure, roll back and restore the captured config best-effort; if restoration also fails, leave the lease held, best-effort persist an operator-visible repair note in a fresh transaction (and log if the database itself is unavailable), and never report success. Handoff uses the same lock/order in reverse purpose: stage the conditional owner/liveness transfer, rewrite identity, then commit; rollback restores the prior identity.

**Correction (2026-08-12, plan review) — numbered tests follow executable dependencies.** §5.8 tests 5, 6, and 7 cannot all belong to the App-auth service task: test 5's no-brief half needs the App brief from Task 8, test 6 is a manifest/lock assertion owned by Task 1, and test 7 needs lease-time dispatch integration from Task 3. Likewise, test 11d cannot be completed before Task 7 creates reconciliation. The ownership table below assigns each complete numbered test to the first task that can execute every required path; earlier tasks may add explicitly unnumbered prerequisite unit assertions.

**Correction (2026-08-12, plan review) — exact-head reconciliation is paginated.** The plan previously said to classify the “complete result set” while specifying only one default-sized GitHub request. That claim was not established. `list_pulls_for_head` must request `per_page=100` and follow GitHub's `Link: rel="next"` pages, preserving `head`, `base`, `state`, and explicit authorization on every page. Reconciliation classifies the accumulated set only after pagination finishes; a later-page open or merged PR must prevent creation.

## Global Constraints

### Working environment

- Work only in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
- Execute each fenced shell block with that worktree root as its starting directory; directory changes do not carry between blocks.
- Do not modify `/home/juan/work/repos/juanrubio/claude-deck` or any Tizonia checkout.
- Do not start or stop a live Deck, tmux server, or agent session. Tests may start isolated subprocesses on ephemeral ports and must tear them down.
- Keep autonomy off. Do not label, dispatch, create a branch in, or write to any public repository.
- Never hand-edit a non-test database. The application database URL is CWD-relative; run all backend commands from `backend/` in g1.
- `backend/.env` contains local test settings and stays mode `0600`, gitignored, and unprinted.

### Git

- This planning branch starts from integration commit `84d327f`. The implementation branch must start from the commit containing this plan and ultimately target `feature/autonomous-github-dispatch`, never `master`.
- This worktree shares a Git object store with other checkouts. Do not run `git worktree prune`, `git gc`, `git stash`, `git reset --hard`, `git branch -f`, ref deletion, or `git checkout -- <file>` on uncommitted work.
- Commit after each task with the task's specified message.
- Do not push, merge, or open a PR unless the user gives a later explicit instruction.

### Security and lifecycle invariants

- No `GH_TOKEN` or `GITHUB_TOKEN` in pane `extra_env`, prompts, work item notes, logs, or worktree files.
- Never log or persist an App JWT, private key contents, or installation token. Installation ids are non-secret and persisted; tokens are not.
- Never configure a Deck credential helper for an `ambient` or unresolved scope.
- Never configure an App helper over an SSH or mismatched push remote; the helper would not participate in that push.
- Never resolve an installation from the credential callback. It reads the persisted mode/id and either mints or refuses.
- A mint-time `404` on a stored App installation refuses `app_not_installed`; it never downgrades the scope to `ambient`.
- Never derive current ownership from `dispatch_head_ref`. Ownership is `owner_slot_id`; the head is an immutable name checked by byte equality.
- Never accept a caller-supplied PR title, body, PR number on `pr_ready`, slot id for the credential route, or repository inferred from host alone.
- Never introduce a new `dispatch_status`. PR2 adds `pr_closed_unmerged` as an escalation reason and `queued_auth_mode_unresolved` as a pending reason.
- Never add `pr_closed_unmerged` or `prepared_owner_unavailable` to `_PR_OPENED_RECOVERABLE_ESCALATIONS`.
- Never lease `GithubWorkspace.kind == "primary"` from dispatch. `allow_primary=True` is an explicit future observation door and defaults to false.
- Every managed worktree release removes agent git identity and any Deck helper, regardless of the scope's current mode. A pre-upgrade held `primary` is metadata-only cleanup: never write or remove git config in a human checkout. A cleanup failure must fail closed and must not report release success.
- Per-item PR locks and per-workspace config locks are single-process coordination only. Reconciliation and conditional DB predicates remain the correctness mechanisms.

### Code and API conventions

- Use `python3`; backend test commands use `venv/bin/pytest`.
- Preserve async boundaries and explicit type hints.
- Add one `GithubAppAuthService`; do not put JWT, installation lookup, or cache logic in route handlers.
- Keep `GithubClient` as the REST transport. App-auth service supplies an explicit token to calls that need App identity; existing ambient callers keep their current behavior.
- Use one `_classify_pull` implementation for list and single-pull payloads. It reads only `state` and the **presence/value** of `merged_at`.
- Pull-list fixtures must omit `merged`; single-pull fixtures must include it. Assert the shape explicitly.
- Worktree helper configuration uses the URL-scoped key, `useHttpPath=true`, then empty-helper and add-helper as separate commands.
- Helper commands use `http://127.0.0.1:{settings.port}` (the same value as `deck_base_url()`), never a hard-coded port or `0.0.0.0`.
- Use argument lists for git subprocesses. Quote only the helper shell command stored in git config with `shlex.join`; do not add shell escaping to display names or email values.
- Normalize git credential paths by removing one leading slash and one terminal `.git`, then require exact `owner/repo` equality.
- The credential callback accepts only loopback peers. A non-loopback request refuses before lease lookup, pane walk, or mint.
- Normalize `origin/<branch>` to `<branch>` for GitHub. Resolve `origin/HEAD` through the repository's default branch; never send literal `HEAD`.
- A fresh DB read that arbitrates a race must issue SQL. Do not rely on an identity-mapped `db.get(...)` object.

### Testing

- Baseline measured at integration commit `84d327f` on 2026-08-12:
  - `venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings` → **614 passed**.
  - `venv/bin/pytest tests/ --collect-only -q -p no:warnings` → **787 collected**.
  - `venv/bin/pytest tests/ -q -p no:warnings` → **786 passed, 1 failed**. The failure is the pre-existing #312 smoke failure, `tests/test_multi_provider_smoke.py::test_agent_bridge_session_filter_smoke`; report it and do not fix it in PR2.
- Record the collected-case delta after every task. Do not hand-adjust tests to make a planned count true; pytest is authoritative.
- Write each task's mutant list before the tests. Run the exact tests against each named mutant. A green test that also passes its mutant is not coverage.
- Use real temporary git repositories for worktree config, credential-helper, base-ref, and ref-namespace tests. No network.
- Use `httpx.MockTransport` for GitHub API tests and assert method, URL, query, headers, and payload.
- Route tests use `app.dependency_overrides[get_db]` and `httpx.ASGITransport`, except the Linux process-chain case, which uses an isolated ephemeral server because ASGITransport has no real socket peer.
- The credential ancestry integration test is Linux-only and must skip with a stated reason elsewhere. It uses a real loopback socket and `/proc`; do not monkeypatch the ancestry walk in that case.
- Read durable state with raw SQL or a fresh session where a stale identity-map value could mask a race.
- No test may call GitHub, read a real credential helper, print `~/.gitconfig`, or use a real App key.

### Stop and report

Stop before proceeding when any of these occurs:

- A required test is green against its named mutant.
- A GitHub fixture cannot be made faithful to the documented endpoint shape.
- A config cleanup requires clearing a lease before the cleanup outcome is known.
- A credential can be minted without both the live acquisition and kernel-derived current owner being checked.
- A PR path must copy the classifier instead of calling the shared helper.
- A new state string is needed outside the three declared namespaces.
- A test would need a real GitHub write or a real secret.

## File Structure

| File | Action | Responsibility |
| --- | --- | --- |
| `backend/app/config.py` | Modify | Four GitHub App settings |
| `backend/requirements.txt` | Modify | Direct PyJWT/crypto dependencies |
| `backend/pyproject.toml` | Modify | Matching direct runtime dependencies |
| `backend/uv.lock` | Modify | Locked direct-dependency graph |
| `backend/app/models/database.py` | Modify | Scope auth mode and installation id |
| `backend/app/database.py` | Modify | Additive SQLite migration rungs |
| `backend/app/models/schemas.py` | Modify | Credential request/response and `pr_ready` head field |
| `backend/app/services/github_app_auth_service.py` | Create | JWT signing, installation resolution, per-repo token cache |
| `backend/app/services/github_client.py` | Modify | Explicit-token headers, paginated ref/default-branch/list/create PR methods |
| `backend/app/services/github_workspace_service.py` | Modify | Primary exclusion, per-worktree identity/helper lifecycle, config lock |
| `backend/app/services/github_dispatch_service.py` | Modify | Auth-mode resolution, brief mode, handoff identity rewrite, namespace declarations |
| `backend/app/services/github_verification_service.py` | Modify | Shared classifier, PR presentation/base helpers, verified legacy reports, `pr_ready`, reconciliation, stage-aware failures |
| `backend/app/api/v1/deps.py` | Modify | Shared request-pane resolver without changing mail auth |
| `backend/app/api/v1/agent_mail.py` | Modify | Import the shared request-pane resolver |
| `backend/app/api/v1/agent_teams.py` | Modify | Credential callback and `pr_ready` dispatch-status branch |
| `backend/app/utils/peer_process.py` | Modify | Detailed resolution result and credential-specific walk cap |
| `backend/mcp_shim/agent_mail_server.py` | Modify | `head_ref` report field and App/ambient status wording |
| `backend/mcp_shim/git_credential_helper.py` | Create | Stdlib git credential protocol client |
| `docs/deploy/pr2-github-app-rollout.md` | Create | Manual, gated App rollout and rollback instructions |
| `backend/tests/test_sqlite_compat_migrations.py` | Modify | Two-column compatibility migration |
| `backend/tests/agent_teams/test_github_app_auth_service.py` | Create | JWT, lookup, mint, cache, secrecy, and auth-mode tests |
| `backend/tests/agent_teams/test_github_client.py` | Create | GitHub transport contracts and response-shape fixtures |
| `backend/tests/agent_teams/test_git_credential_helper.py` | Create | Helper stdin/stdout and callback API contracts |
| `backend/tests/agent_teams/test_github_workspace_service.py` | Modify | Primary exclusion and git config lifecycle |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | Modify | Lease-time mode resolution, brief, handoff, namespace paths |
| `backend/tests/agent_teams/test_agent_team_service.py` | Modify | Spawn/reuse launch environment remains credential-free |
| `backend/tests/agent_teams/test_github_watcher_service.py` | Re-run | Existing ambient `GithubClient` transport remains unchanged |
| `backend/tests/agent_teams/test_github_verification_service.py` | Modify | PR classifier, legacy report, verifier, reconciliation, creation |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | Kernel-bound credential callback and lease/path refusals |
| `backend/tests/agent_mail/test_peer_process.py` | Modify | Detailed resolver and unchanged default budget |
| `backend/tests/agent_mail/test_api.py` | Modify | Shared request-pane capture preserves Agent Mail behavior |
| `backend/tests/agent_mail/test_dispatch_status_tool.py` | Modify | `pr_ready` payload, stale lease, retained PR1 `in_progress` regression |
| `backend/tests/agent_mail/test_mcp_shim.py` | Modify | `head_ref` forwarding and no caller-owned title/body |
| `backend/tests/agent_teams/test_dispatch_state_namespaces.py` | Create | Declared sets, AST writer scan, classifier synthetic cases |

## Task Index

| Task | Deliverable | Spec |
| --- | --- | --- |
| 1 | App settings, dependencies, and durable scope state | §5.3, §5.6a |
| 2 | JWT, installation resolution, and token cache | §5.3, §5.3a |
| 3 | Lease-time auth mode and worktree identity | §5.4, §5.6a, §5.7 |
| 4 | Kernel-bound Git credential delivery | §5.5.6 |
| 5 | Shared PR classifier and verified legacy reports | §5.6, §5.6b |
| 6 | GitHub PR/ref transport and templates | §5.5.2, §5.5.5 |
| 7 | Crash-safe `pr_ready` reconciliation | §5.5.4, §5.5.4a |
| 8 | Brief, shim, handoff, and release integration | §5.4, §5.5.2 |
| 9 | Namespace enforcement and rollout documentation | §5.8, §5.9 |
| 10 | Full integration and mutation audit | §8 criteria |

### Normative test ownership

The spec reuses numeric ids across sections, and many PR2 tests are defined beside their design rule rather than under §5.8 (for example, reconciliation test 46h is in §5.5.4a and auth-mode test 30 is in §5.6a). Keep PR2 tests in PR2-focused files and qualify docstrings with the actual spec section plus test id; do not call every entry a “§5.8 test.” A later task may rerun or extend an earlier test with unnumbered integration assertions, but each numbered PR2 test has exactly one owner below.

| Task | PR2 numbered tests owned |
| --- | --- |
| 1 | 6, plus unnumbered migration/default checks |
| 2 | 4, plus unnumbered JWT, lookup, mint, cache, and log-secrecy checks |
| 3 | 1, 2, 3, 7, 23, 24, 25, 28, 28b, 28c, 28d, 30, 30c, 30d, 30e, 31, 32, 33, 34, 35 |
| 4 | 19, 20, 21, 22, 30b, 31b, 46r, plus the peer-budget correction |
| 5 | 8, 9, 10, 11, 11b, 11c, 11e, 29c, 29d, 29e, 29f, 29g, 29g-1, 29h, 29h-1, 29h-2, 36, 37, 37b, 37c; complete merged PR1 test 29b |
| 6 | Unnumbered GitHub transport and pure template/base helper tests |
| 7 | 11d, 13, 14, 15, 16, 17, 17b, 18, 38, 39, 40, 41, 42, 43, 44, 45, 46, 46b, 46c, 46d, 46e, 46f, 46g, 46h, 46i, 46j, 46k, 46l, 46m, 46n, 46o, 46o-1, 46o-2, 46o-3, 46p, 46q, 47, 48, 49, 49b, 50 |
| 8 | 5, 12, 26, 27, plus unnumbered lifecycle integration assertions that rerun 25 and 46r |
| 9 | 29, 29-a, 29-a1, 29-a2, 29-b; rollout-only §5.9 checks |
| 10 | Every mutation row in §5.8 and success-criteria cross-check |

### PR2 exclusions

- No real GitHub App creation, installation, key generation, branch protection change, or public-repository write.
- No frontend App setup, auth-mode reset, workspace-lease, or credential UI.
- No automatic re-resolution of an already stored `app` or `ambient` mode.
- No token persistence, token endpoint exposed to the browser, per-slot bot accounts, or pane API credential.
- No replacement of the existing ambient watcher token. Existing issue polling remains on `github_token`; PR2 uses installation tokens only for the App-specific push callback and PR creation path.
- No multi-worker distributed lock. Document that per-key and per-item locks are process-local; reconciliation remains safe after restart.
- No new dispatch state enum/table, PR-attempt table, or parsing ownership from branch names.

### Implementation branch setup

Before Task 1, verify the plan commit is based on the merged integration tip and create a new implementation branch:

```bash
cd /home/juan/work/repos/juanrubio/claude-deck-g1
git status --short --branch
git merge-base --is-ancestor 84d327f HEAD
git switch -c feature/distinct-approver-identity-pr2-impl
```

If the branch exists, the ancestry check fails, or tracked files are dirty, stop. Do not force, delete, or reuse a ref.

---

### Task 1: Add App configuration and durable repository auth state

**Files:**

- Modify: `backend/app/config.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `backend/app/models/database.py`
- Modify: `backend/app/database.py`
- Modify: `backend/tests/test_sqlite_compat_migrations.py`
- Create: `backend/tests/agent_teams/test_github_app_auth_service.py`

- [ ] **Step 1: Write the red schema/config tests.**

Assert `Settings.model_fields` defaults exactly:

```python
github_app_id = ""
github_app_private_key_path = ""
github_app_bot_login = ""
github_app_token_refresh_margin_seconds = 300
```

Assert new and migrated `TeamGithubScope` rows read `github_auth_mode == "unknown"` and `github_app_installation_id is None`. Extend the compatibility fixture from a pre-PR2 schema and verify both additive columns without rebuilding or dropping data.

- [ ] **Step 2: Write dependency-declaration tests.**

Read `requirements.txt` and `pyproject.toml` as data. Require direct entries for `pyjwt[crypto]` and `cryptography`; do not accept transitive importability as proof. Parse `uv.lock`, read `project.name` from `pyproject.toml` (`claude-code-registry-backend` today), locate that editable root package, and assert both package records exist **and** its `requires-dist` records both direct requirements. Merely finding transitive package nodes is insufficient.

- [ ] **Step 3: Run the red tests and record collection count.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_app_auth_service.py tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

- [ ] **Step 4: Add settings, ORM columns, and migration rungs.**

Use the repository's mapped-column form exactly:

```python
github_auth_mode: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
github_app_installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

The migration order is mode then id. Do not expose either field in `TeamGithubScopeCreate` or `Update`; mode changes remain the manual/operator rollout action §5.9 describes.

- [ ] **Step 5: Declare and lock direct dependencies.**

Update both manifests, then run the repository-local lock workflow exactly:

```bash
cd backend
uv lock
```

Inspect the lock diff. The stale root metadata is expected to refresh, but do not accept unrelated dependency upgrades. If the installed `uv` cannot produce a focused lock update, stop and report rather than hand-editing `uv.lock`.

- [ ] **Step 6: Run focused and migration tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_app_auth_service.py tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

- [ ] **Step 7: Commit.**

```bash
git add backend/app/config.py backend/requirements.txt backend/pyproject.toml backend/uv.lock \
  backend/app/models/database.py backend/app/database.py \
  backend/tests/test_sqlite_compat_migrations.py \
  backend/tests/agent_teams/test_github_app_auth_service.py
git commit -m "feat(github): add durable app authentication state"
```

---

### Task 2: Implement JWT authentication, installation resolution, and token caching

**Files:**

- Create: `backend/app/services/github_app_auth_service.py`
- Modify: `backend/app/services/github_client.py`
- Modify: `backend/tests/agent_teams/test_github_app_auth_service.py`
- Create: `backend/tests/agent_teams/test_github_client.py`
- Re-run: `backend/tests/agent_teams/test_github_watcher_service.py`

- [ ] **Step 1: Define the service contracts before implementation.**

Use explicit result/error types for:

- App unconfigured.
- Installation lookup `404` (“ambient answer”).
- Lookup auth/transient failures (“unresolved refusal”).
- Mint `404` on a persisted installation (`app_not_installed`).
- Other mint failures.

Do not collapse lookup and mint `404` into one exception.

- [ ] **Step 2: Write JWT and lookup transport tests.**

Use a generated temporary RSA key. Decode the JWT with the public key and assert `iss`, short `iat` backdating, and expiry no more than ten minutes. Assert the key path is read at call time and key contents/JWT never enter a log record.

For `GET /repos/{owner}/{repo}/installation`, assert App-JWT authorization and distinguish `200`, `404`, `401/403`, `5xx`, timeout, DNS/connection errors. No test uses GitHub.

- [ ] **Step 3: Write token mint/cache test 4 and unnumbered service-boundary tests.**

Assert:

- Mint JSON narrows with `repositories=[repo]`.
- Cache key is `(installation_id, "owner/repo")`.
- Outside refresh margin the same token is reused.
- Inside margin a fresh token is minted.
- Concurrent same-key calls mint once under one lock.
- Different keys do not wait on one global lock.
- Token/JWT/private key are absent from service logs and returned error text. This is the unit-level secrecy prerequisite; Task 7 extends installation-token log coverage to PR creation, and Task 8 completes spec test 5 against the generated brief.
- Mint `404` produces `app_not_installed` naming repo and id, without a mode mutation side effect.

Do not claim spec tests 6 or 7 here. Task 1 owns the manifest/lock assertion, and Task 3 owns the unconfigured-dispatch integration.

- [ ] **Step 4: Extend `GithubClient` for explicit authorization.**

Add a private header helper that can use an explicit token without changing existing ambient callers. Do not store an installation token on the process-global `github_client`. App-specific calls pass the token per operation.

- [ ] **Step 5: Implement `GithubAppAuthService`.**

The service owns key loading, JWT signing, lookup, mint, expiry parsing, cache, and per-key locks. Tokens stay in memory. Installation ids do not need an in-memory-only source of truth; later tasks read the scope row.

- [ ] **Step 6: Mutation-test cache and 404 boundaries.**

At minimum run mutants for global lock, repo omitted from cache key, no repository narrowing, refresh inequality reversed, one shared `404` handler, and token included in exception/log text.

- [ ] **Step 7: Run focused tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_app_auth_service.py \
  tests/agent_teams/test_github_client.py \
  tests/agent_teams/test_github_watcher_service.py -q -p no:warnings
```

- [ ] **Step 8: Commit.**

```bash
git add backend/app/services/github_app_auth_service.py \
  backend/app/services/github_client.py \
  backend/tests/agent_teams/test_github_app_auth_service.py \
  backend/tests/agent_teams/test_github_client.py
git commit -m "feat(github): mint repository scoped app tokens"
```

---

### Task 3: Resolve auth mode at lease time and configure only safe worktrees

**Files:**

- Modify: `backend/app/services/github_workspace_service.py`
- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_service.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_agent_team_service.py`
- Re-run: `backend/tests/agent_teams/test_github_watcher_service.py`

- [ ] **Step 1: Write primary-exclusion tests 28–28d first.**

Use a lower-id `primary` and a later `worktree`, both `dispatchable=True`. Default acquire must lease the worktree on the first call and leave every primary lease field untouched. Primary-only dispatch returns existing `queued_no_workspace`, includes skipped-primary count in `status_note`, and succeeds after a worktree is added. `allow_primary=True` is the sole positive primary case.

Add the pre-upgrade held-primary case separately: seed the item as already leasing a `primary`, then call default acquire. It must conditionally clear only that captured lease metadata, never invoke a git-config helper on the primary path, and continue to the eligible worktree. If the captured acquisition changed, it returns without touching either row. `allow_primary=True` may return the held primary but still must not install agent identity there.

- [ ] **Step 2: Write real-git identity/config tests 1–3 and 23–24.**

In linked temporary worktrees with an isolated temporary `HOME`/global git config assert:

- `extensions.worktreeConfig=true`.
- Worktree-only `user.name` and slugged `user.email`.
- Punctuation/spaces collapse into a lowercase slug, trim leading/trailing punctuation, and form `<slug>+slot<ID>@claude-deck.local`. The full local part is at most 64 bytes; truncate the slug before the suffix and fall back to `agent` when normalization (including an all-punctuation/non-ASCII name) is empty. Test leading dots, all punctuation, non-ASCII-only text, and an overlong display name.
- A sibling worktree and primary checkout remain unchanged.
- App mode writes `useHttpPath`, empty helper, then Deck helper in that order.
- A non-default `settings.port` appears in the helper URL; neither `8000` nor `0.0.0.0` is hard-coded.
- Ambient mode writes identity only, leaves the global helper reachable, and has no URL-scoped helper entry.
- No helper/identity write happens before mode resolution succeeds.
- App mode calls `git remote get-url --push --all origin` and refuses before config when the result is SSH, another host/repo, has credentials/port/query/fragment, contains zero or multiple URLs, or is unreadable. The bad workspace is disabled with `provision_error`; on the next poll a later valid HTTPS worktree is selected. Ambient mode does not inspect or rewrite the remote.

- [ ] **Step 3: Write owned auth-mode tests 7, 30, 30c–30e, and 31–35.**

Cover all six persisted `(mode, id)` combinations and lookup outcomes. `200` stores `app` and id in one commit. Lookup `404` stores `ambient` and NULL id and proceeds. For test 7, run a complete unconfigured dispatch: both App id and key are empty, no App lookup or mint occurs, the existing watcher/dispatch client still authenticates with configured `github_token`, the item dispatches, and no Deck credential helper is written. Partial global configuration, an unreadable/unparseable key, or an empty bot login leave `unknown` unchanged, release the acquisition, set `queued_auth_mode_unresolved`, and perform no lookup/config write. Transient/auth failures do the same. Stored `app/id` never re-resolves, but each missing prerequisite refuses while preserving its mode/id. `unknown/id` clears then resolves; `ambient/id` clears and never mints; `app/NULL` refuses without lookup.

- [ ] **Step 4: Implement safe acquisition and identity helpers.**

Add keyword-only `allow_primary: bool = False` and inject `kind != "primary"` into the selection query before any lease write. Check an idempotently held lease before returning it: a held primary under the default path is conditionally released as metadata only, then selection continues. Add helpers for slot identity, email slug, worktree config snapshot/application/restoration/removal, and a per-workspace config lock. The snapshot is lossless for the managed keys: preserve scalar absence/value and the ordered, possibly-empty multi-value helper list (use NUL-delimited git output rather than line splitting), then restore by clearing and re-adding the exact sequence. Keep helper command construction centralized so tests can assert exact commands. Build the helper command from `deck_base_url()`/`settings.port`, `sys.executable`, and an absolute path to `backend/mcp_shim/git_credential_helper.py`; do not hard-code port `8000`, rely on `PATH`'s Python, or use a relative script path. App-mode tests in this task assert the config bytes but do not execute a push before Task 4 creates the script and callback route.

- [ ] **Step 5: Integrate mode resolution after lease acquisition and before config/brief.**

The order is:

1. Acquire a non-primary workspace.
2. Normalize inconsistent stored mode/id.
3. Validate global App prerequisites, then resolve only `unknown`.
4. Persist mode and id together.
5. For `app/id`, validate the exact single HTTPS GitHub `origin` push URL without rewriting it.
6. Under the workspace config lock, snapshot the managed keys and apply identity and, only for a transport-valid `app/id`, helper config.
7. Prepare/send/launch as before.

If steps 2–5 refuse, restore any partial config and conditionally release the captured acquisition, leave the item pending with `queued_auth_mode_unresolved`, and continue without sending a brief. If any step-6 git command fails, restore the full managed-key snapshot before releasing; if restoration fails, leave the lease held with an operator-visible note rather than making a partially configured worktree available. A permanent remote mismatch additionally disables that workspace so a lower-id row cannot starve valid later rows.

- [ ] **Step 6: Assert pane launch env remains credential-free (test 25).**

Capture `spawn_session(..., extra_env=...)` on spawn and reuse-related launch tests. Assert neither `GH_TOKEN` nor `GITHUB_TOKEN` appears. This is a regression guard; do not add production env filtering for keys never supplied.

- [ ] **Step 7: Mutation-test ordering and primary selection.**

Kill: primary filter after lease, held primary returned by the default path, primary config cleaned or written, filter by `dispatchable` only, default `allow_primary=True`, empty/overlong email slug accepted, helper configured before lookup, transient failure treated as ambient, stored App prerequisites skipped, App/NULL re-resolved, only the first of multiple push URLs inspected, SSH origin accepted, invalid workspace immediately reselected, remote rewritten instead of refused, backend port hard-coded, partial config not restored, and empty-reset omitted.

- [ ] **Step 8: Run focused suites.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_workspace_service.py \
  tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_agent_team_service.py \
  tests/agent_teams/test_github_watcher_service.py -q -p no:warnings
```

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/github_workspace_service.py \
  backend/app/services/github_dispatch_service.py \
  backend/tests/agent_teams/test_github_workspace_service.py \
  backend/tests/agent_teams/test_github_dispatch_service.py \
  backend/tests/agent_teams/test_agent_team_service.py
git commit -m "feat(dispatch): configure per-worktree agent identity"
```

---

### Task 4: Deliver credentials only to the kernel-derived current owner

**Files:**

- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/v1/deps.py`
- Modify: `backend/app/api/v1/agent_mail.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/app/utils/peer_process.py`
- Create: `backend/mcp_shim/git_credential_helper.py`
- Create: `backend/tests/agent_teams/test_git_credential_helper.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`
- Modify: `backend/tests/agent_mail/test_peer_process.py`
- Modify: `backend/tests/agent_mail/test_api.py`

- [ ] **Step 1: Specify request/response and helper protocol.**

Request fields are exactly `workspace_token`, `protocol`, `host`, `path`. Response fields are exactly `username`, `password`. The script reads git credential lines until blank/EOF, acts only on the `get` operation, POSTs to `/api/v1/agent-teams/git-credential`, and prints credentials only on `200`. On refusal it prints no `password` and exits non-zero with a secret-free diagnostic.

- [ ] **Step 2: Move request-pane capture into a shared dependency helper.**

Move the current `agent_mail.resolve_request_pane` implementation to `app/api/v1/deps.py` and import it back into Agent Mail without behavior change. Route handlers still invoke it synchronously while the socket exists.

- [ ] **Step 3: Add detailed peer resolution with the corrected budgets.**

Return a structured result containing resolved pane (if any), walked pid chain, stop reason, and configured cap. Preserve `resolve_peer_pane(...) -> PeerPane | None` as the compatibility wrapper with default 32. The credential route calls the detailed form with 16. Do not change `_MAX_PARENT_WALK`, mail tests, or `AgentMailService._pids_related` to 8.

- [ ] **Step 4: Write route authorization tests 20–22 and 46r.**

Assert before minting:

- Missing path → `400`.
- Wrong protocol, host, normalized repo, stale/released token → refusal.
- Scope path `owner/repo.git` normalization is exact and repo A cannot request repo B; error names both.
- A non-loopback peer is refused before DB authorization or minting.
- Scope must be `app` with non-NULL persisted id; stale helper config gets `501` without lookup.
- A persisted App scope with missing/unloadable App id/key or an empty bot login gets `503 app_auth_unconfigured` without lookup or mode/id mutation, including a stale live helper after backend configuration changes.
- Pane binding must be selected by the full kernel identity `(pane_pid, pane_proc_start)`, not pid alone, and its slot must equal the current item owner.
- After real A→B handoff with retained token, A is `403`, B mints, unbound is `pane_unresolved`, and missing token refuses before a pane walk.
- Mint `404` returns `app_not_installed` without changing mode/id.
- Test 30b constructs a fresh `GithubAppAuthService` with an empty cache after the lease is configured, then proves the callback mints from the persisted installation id and never calls installation lookup.
- Test 31b drives a persisted App id whose mint call returns `404`, and proves `app_not_installed` is distinct from lookup `404`: mode/id remain unchanged and no ambient fallback occurs.

- [ ] **Step 5: Implement the callback as one owner-gated operation.**

Join token → workspace → item → scope, validate repo, mode, and current App prerequisites, derive the pane from the live request, load the unique `(pane_pid, pane_proc_start)` binding, compare its slot to a fresh SQL read of `owner_slot_id`, then mint from the persisted id. Use the Task-3 per-workspace config lock across authorization and mint so an in-process handoff/release cannot interleave after the owner check. Re-read acquisition/owner with SQL before returning the credential; disagreement refuses and discards the minted token.

- [ ] **Step 6: Implement and test the stdlib helper.**

Use `urllib.request`, not `httpx`, so the pane needs only Python. Accept `--deck-url`, `--lease`, and git's appended operation. Never echo the lease or response body. Test stdin parsing, `.git` path forwarding, GET/no-op behavior, refusal, malformed JSON, and credential output exactly. For §5.8 test 19, use an isolated temporary `HOME` and global git config, configure a real temporary repository with `useHttpPath=true`, point its helper at a capture script, run `git credential fill`, and assert `path=owner/repo.git` reached the helper. Run the omitted-`useHttpPath` mutant and prove the path disappears. No test may consult the user's real credential stack.

- [ ] **Step 7: Add the Linux real-process ancestry test.**

Start a minimal isolated FastAPI app on an ephemeral loopback port and a nested shell/helper process. Use a temporary SQLite database with explicit dependency overrides; include only the route/dependencies needed by the test, disable application lifespan/schedulers, and never import/run `app.main` against the CWD-relative ignored database. Seed a binding for the designated ancestor and a test lease. Use the real loopback socket and `/proc` walk; only GitHub mint is stubbed. Assert the measured chain resolves under 16 and the same call refuses under a deliberately smaller cap. Tear down the server, process tree, database, and temporary HOME in `finally`; mark non-Linux skip explicitly.

- [ ] **Step 8: Mutation-test identity versus token.**

Kill: token-only auth, caller-supplied slot, host-only repo check, stored App prerequisites skipped, installation re-lookup, mail default changed from 32, missing second owner/acquisition SQL read, and failure text containing the token.

- [ ] **Step 9: Run focused tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_git_credential_helper.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/agent_mail/test_peer_process.py \
  tests/agent_mail/test_api.py -q -p no:warnings
```

- [ ] **Step 10: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/api/v1/deps.py \
  backend/app/api/v1/agent_mail.py backend/app/api/v1/agent_teams.py \
  backend/app/utils/peer_process.py backend/mcp_shim/git_credential_helper.py \
  backend/tests/agent_teams/test_git_credential_helper.py \
  backend/tests/agent_teams/test_github_workspace_api.py \
  backend/tests/agent_mail/test_peer_process.py backend/tests/agent_mail/test_api.py
git commit -m "feat(github): bind push credentials to current owner"
```

---

### Task 5: Classify every PR once and verify the legacy report path

**Files:**

- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/app/services/github_verification_service.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/tests/agent_teams/test_github_verification_service.py`
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`

- [ ] **Step 1: Write endpoint-faithful classifier fixtures.**

Create separate list-pull and single-pull factories. List fixtures assert `"merged" not in pull`; single fixtures carry `merged`, `mergeable`, `mergeable_state`, and `merged_by`. Both carry `state`, `merged_at`, `merge_commit_sha`, `head`, `base`, `number`, and `draft`.

- [ ] **Step 2: Implement and exhaustively unit-test `_classify_pull`.**

The only accepted results are:

```text
state=open,   merged_at=None       -> open
state=closed, merged_at=<value>    -> merged
state=closed, merged_at=None       -> closed_unmerged
```

Missing `merged_at`, unknown/missing state, or `open` with non-NULL `merged_at` returns `None`. Never read `merged` or `merge_commit_sha`. Add an explicitly **unnumbered** pure classifier matrix covering the nine existing shapes plus incoherent/missing cases. Task 7 owns and completes numbered reconciliation tests 46l–46o-3 once the list/reconcile path exists.

- [ ] **Step 3: Harden `report_pr_opened` before any mutation or mail.**

Change its signature to accept a `GithubClient`. Fetch the PR; verify repository and exact stored head first; enforce the author only for persisted `app` mode; refuse `app_mode_bot_login_unset`; skip author checks for `ambient` and `unknown`; then classify. Open uses today's transition. Merged records number and marks merged with blocker notification, no design-review mail. Closed-unmerged calls a new explicit `github_dispatch_service.escalate_without_notification(...)` that delegates to `_apply_escalation` and commits without composing mail; it leaves `pr_number` NULL. `None` refuses with no writes. Do not emulate silence by calling `escalate()` and deleting mail afterwards.

- [ ] **Step 4: Add verifier classification before all CI/review work.**

Both `_verify_item` and `_process_review_item` call the shared helper before check runs, draft promotion, or merge. Closed-unmerged escalates immediately. Merged reconciles. `None` consumes retry budget with `head_sha=None`.

- [ ] **Step 5: Make failure retry stage explicit and reservation-safe.**

Add required keyword-only `retry_status` with no default to `_record_failed_verification_attempt`. Verify-stage callers pass `"dispatched"`; review stage passes `item.dispatch_status`. Add `_set_failure_note` keyed on `_HUMAN_MERGE_NOTE_PREFIXES`; still send owner mail. Route the outer `process_scope` `httpx.HTTPError` handler, `_record_transient_merge_failure`, and every other review-stage failure-note write through this helper. Escalate with local `note`, not `item.status_note`. Same-sha logic compares against `retry_status`.

- [ ] **Step 6: Write tests 8, 9, 10, 11, 11b, 11c, 11e, 29c–29h-2, and 36–37c.**

Include wrong repo/head/author, App-login unset, ambient/unknown author skip, merged design with zero review mail, closed-unmerged with non-null `merge_commit_sha` and zero mail, repository/head-before-state ordering, green-check closed PR refusing before checks, unclassifiable retry sequence, design-stage preservation, and sticky human-merge reservation. For the outer-error seam, start a reserved `ready_for_review` item, make `get_pull` fail once, recover on the next poll, and assert the reservation note is byte-identical and `merge_pull` remains uncalled. Do not claim test 11d here: Task 7 adds reconciliation, then drives all three call sites against one monkeypatched classifier sentinel.

- [ ] **Step 7: Complete the merged PR1 `in_progress` test.**

Extend the existing `pr_number=9999` liveness regression with `github_dispatch_service._ack_satisfied(item) is False`, then run it. Do not add a second production edit or duplicate test.

- [ ] **Step 8: Mutation-test every branch.**

At minimum: classify on `merged`; substitute `merge_commit_sha`; classify before repo/head; author keyed on global login rather than mode; App/empty login skipped; closed condition after checks; silent escalation routed through notifying `escalate`; `None` returns without increment; real sha passed on `None`; retry default added; outer HTTP error overwrites a reservation; transient review failure bypasses `_set_failure_note`; escalation passed stored note; duplicated classifier bypasses sentinel.

- [ ] **Step 9: Run focused tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_verification_service.py \
  tests/agent_mail/test_dispatch_status_tool.py -q -p no:warnings
```

- [ ] **Step 10: Commit.**

```bash
git add backend/app/services/github_dispatch_service.py \
  backend/app/services/github_verification_service.py \
  backend/app/api/v1/agent_teams.py \
  backend/tests/agent_teams/test_github_verification_service.py \
  backend/tests/agent_mail/test_dispatch_status_tool.py
git commit -m "fix(github): classify pull requests before advancing"
```

---

### Task 6: Add GitHub ref/PR transport and deterministic PR presentation

**Files:**

- Modify: `backend/app/services/github_client.py`
- Modify: `backend/app/services/github_verification_service.py`
- Modify: `backend/tests/agent_teams/test_github_client.py`
- Modify: `backend/tests/agent_teams/test_github_verification_service.py`
- Re-run: `backend/tests/agent_teams/test_github_watcher_service.py`

- [ ] **Step 1: Add transport tests before methods.**

Specify:

- `get_ref(owner, repo, head, token=...)` with correctly URL-encoded `heads/<head>`.
- `get_repository(owner, repo, token=...)` for `default_branch`.
- `list_pulls_for_head(..., head=f"{owner}:{branch}", base=<normalized>, state="all", per_page=100, token=...)`, following `Link: rel="next"` until exhausted.
- `create_pull(..., title, head, base, body, draft, token=...)`.

Assert explicit App token authorization and update the module docstring's writer list to include `create_pull`. Pagination tests must put the only matching open/merged PR on a later page and assert every request preserves the qualified `head`, normalized `base`, `state=all`, `per_page=100`, and explicit token; accumulated results retain endpoint-faithful list-pull shapes. Follow only a `rel="next"` URL whose origin and endpoint path equal the original GitHub API request, reject cycles, and never forward the installation token to a host/path supplied by an invalid `Link` header. Test cross-origin, wrong-path, and cyclic links.

- [ ] **Step 2: Implement one base normalization helper.**

Put the helper in `GithubVerificationService`, not the transport-only `GithubClient`. Define the accepted grammar rather than accepting every non-empty scope value:

- `origin/HEAD` calls `get_repository` and uses its non-empty `default_branch`.
- `origin/<branch>` strips exactly one `origin/` prefix.
- An already-unqualified branch is preserved.
- Bare `HEAD`, `refs/...`, an invalid `git check-ref-format --branch` value, or a resolved default branch that is invalid refuses before list/create.

The same helper result is passed to both list and create. It never sends literal `HEAD` or a git refspec to GitHub.

- [ ] **Step 3: Implement deterministic title/body/draft helpers.**

Implement these helpers in `GithubVerificationService`, which owns item/scope/slot orchestration. Title is exactly `[<current owner slot display_name>] <issue title> (#<issue number>)`. Body includes `Closes #n`, issue title, and a provenance block naming work item id, current owner slot id, dispatch nonce, and exact head. `draft = issue_type != "design"`. Reports do not influence these values.

- [ ] **Step 4: Write unnumbered pure/template helper tests.**

Cover design/non-draft, code/draft, verbatim title/body, all accepted base forms, and invalid/bare-HEAD/refspec refusal before network. Keep caller presentation data out of the pure helper signature: it accepts persisted item/current-slot inputs only. Task 7 owns the request-schema assertion that caller `title`/`body` are rejected and cannot reach these helpers. Use the same normalized base helper for list and create; monkeypatch a sentinel to prove both consult it.

- [ ] **Step 5: Mutation-test transport and normalization boundaries.**

Kill: first page only, raw cross-origin/wrong-path `Link` followed with the App token, pagination cycle ignored, later page loses query/token, raw `base_ref` sent, literal `HEAD` sent, invalid ref accepted, caller title/body used, and presentation helpers placed on `GithubClient` instead of the orchestration service.

- [ ] **Step 6: Run transport/template tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_client.py \
  tests/agent_teams/test_github_verification_service.py \
  tests/agent_teams/test_github_watcher_service.py -q -p no:warnings
```

- [ ] **Step 7: Commit.**

```bash
git add backend/app/services/github_client.py \
  backend/app/services/github_verification_service.py \
  backend/tests/agent_teams/test_github_client.py \
  backend/tests/agent_teams/test_github_verification_service.py
git commit -m "feat(github): add pull request creation transport"
```

---

### Task 7: Implement crash-safe `pr_ready` and reconciliation

**Files:**

- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/app/services/github_verification_service.py`
- Modify: `backend/tests/agent_teams/test_github_verification_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`
- Re-run: `backend/tests/agent_teams/test_github_client.py`

- [ ] **Step 1: Add `pr_ready` to the owner-only status matrix.**

It requires the current lease token exactly like `pr_opened`. `DispatchStatusReport` gains `head_ref`; it does not gain `title` or `body`. Enforce payload pairs at the route: `pr_ready` requires a non-empty `head_ref` and caller `pr_number is None`; `pr_opened` requires `pr_number` and caller `head_ref is None`; a mixed payload is `400`, not an ignored alternate authority. App mode accepts `pr_ready`; ambient/unknown refuse it. Verified `pr_opened` remains available in every mode, with Task 5's App bot-author check applied when relevant. Add `pr_number` to the successful `/dispatch-status` response projection so both the HTTP caller and MCP shim receive Deck's GitHub-derived number.

- [ ] **Step 2: Write cheap-path and authorization tests 13–18.**

Assert missing `head_ref`, caller-supplied `pr_number`, stale lease, wrong owner, NULL stored head, byte-mismatched head, incomplete App configuration, empty App bot login, mint-time installation `404`, and missing remote ref all refuse before any pull-list/create call when the stored `item.pr_number` is NULL. The mint `404` reports `app_not_installed` and preserves mode/id. If `item.pr_number` is already set and the reported head is byte-equal, return it in the route response without App-prerequisite checks, ref/list/create/mint calls. The same explicitly minted installation token is passed to ref, repository/default-base, list, create, and post-failure reconcile calls and is absent from logs.

- [ ] **Step 3: Implement per-item locks and reconciliation helpers.**

Under the lock:

1. Re-read item and lease authorization.
2. Require the reported head to equal the persisted head byte-for-byte.
3. Cheap-return a stored number in the response.
4. For App mode, validate current App prerequisites and mint from the persisted installation id without a lookup.
5. Validate the remote ref and normalize base once with the same explicit token.
6. List `state=all` by qualified head/base through every pagination page with that token.
7. Classify and verify the accumulated result set only after pagination is exhausted.
8. Create only when classification finds no history.
9. On timeout or `422`, reconcile once more with the same rules; never blind-retry create.

Add a deterministic same-item concurrency test: start two `pr_ready` reports together and make the first fake `create_pull` yield once to the event loop before returning. With the per-item lock, the second report cannot enter list/create and later cheap-returns the first recorded number; without the lock, it reaches create during that yield and the call count becomes two. Assert one create and the same returned number. Do **not** use a two-party barrier inside create—the correct lock would prevent the second party from reaching it and deadlock the test. The per-item-versus-global-lock distinction remains an honest review-only row unless a deterministic cross-item timing test is added.

- [ ] **Step 4: Implement shared-classifier test 11d and multi-match classification 38–46o-3.**

Classify every returned object first. If any member is unclassifiable, return `409` before state precedence with **no item-column writes**; include diagnostics in the HTTP detail, not `status_note`. After selecting the winning state class, verify every member of that class for repository/exact-head/App-author before mutation. Irrelevant lower-precedence history does not defeat a valid open PR. Add mixed open-plus-unclassifiable, open-plus-wrong-author, and valid-open-plus-irrelevant-closed-author cases.

For a fully classifiable, verified set, apply this single-valued table:

- Exactly one open → record its number, clear stale reconciliation note, and advance through the normal code/design transition.
- Two or more open → `409`; only `status_note` and `updated_at` may change, and the note names all open PR ids. `dispatch_status`, `pr_number`, and escalation fields stay unchanged.
- No open, one or more merged → choose the highest PR number, call `_mark_merged` first, then persist a note naming all merged ids, and notify the blocker. Assert the helper cannot erase the committed diagnostic.
- No open/merged, one or more closed-unmerged → silently escalate `pr_closed_unmerged`, leave `pr_number` NULL, and name all closed ids.
- Empty history → create.

An open PR outranks closed history. Merged outranks closed-unmerged. Multiple merged is not ambiguous. Test 11d monkeypatches `_classify_pull` to one sentinel and drives reconciliation, `report_pr_opened`, and verifier processing; no earlier task may claim this test complete.

- [ ] **Step 5: Verify adopted and created PRs with the correct check set.**

For every listed PR in the winning state class, run the shared repository, exact-head, and App-mode bot-author checks before any item mutation; discovery is not trust. Lower-precedence history is classified for coherence but does not gain veto authority over the selected open/merged outcome. For Deck's own `create_pull` response, verify repository and exact head and classify it, but **do not** run the legacy author check — Deck supplied the installation credential, so authorship is structural and checking the returned login is a tautology. Never adopt, merge-reconcile, or escalate solely because the head/base query matched.

- [ ] **Step 6: Add real-git attempt-ref tests 46p/46q.**

Against a temporary bare remote, verify sibling legacy and attempt refs coexist in both creation orders; child refs fail with the expected lock-ref message. Parametrize hostile display names and prove `attempt_head_ref` is byte-identical because it uses numeric slot id, then `git check-ref-format --branch` passes.

- [ ] **Step 7: Complete recovery test 46h and tests 47–50 through the real handler.**

For 46h, drive the real offline lifecycle: attempt A creates PR #5, verification classifies it closed-unmerged and escalates, then the owner reports `workspace_released` through the real release route before the operator calls `deck_retry_work_item`. Use a quiescent fake git runner so release blockers do not introduce unrelated pending work. Assert release succeeds, retry reaches `pending`, attempt B receives a distinct persisted head, reconciliation queries only B's qualified head, and exactly one second PR is created. Calling retry while the lease is still held must remain deferred; do not bypass `reset_for_retry` or mutate the workspace row directly.

For 47–50, design `pr_ready` creates non-draft and notifies review; code creates draft and verifies; payload fields cannot override title/body; all supported base paths reach list and create normalized; the response `pr_number` is the only number recorded. Assert the first and idempotent second HTTP/MCP responses both contain that number. Add later-page open and merged matches so pagination—not only first-page classification—prevents duplicate creation.

- [ ] **Step 8: Mutation-test crash and classification boundaries.**

Kill: cheap return before exact-head authorization, response omits `pr_number`, App token used only for create, mint `404` downgrades/clears mode, `pr_number` only idempotency, no post-timeout reconcile, hard `422`, unqualified head, raw/unsupported base_ref, first-page-only list, state=open query, single-match state-blind adoption, mixed unclassifiable set accepted, listed object verification skipped, `_mark_merged` erases diagnostics, multiple-merged 409, closed before merged, unknown defaults open, per-item lock changed to global (review-only if not directly observable), and caller-supplied PR number/title/body.

- [ ] **Step 9: Run focused tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_verification_service.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/agent_mail/test_dispatch_status_tool.py \
  tests/agent_teams/test_github_client.py -q -p no:warnings
```

- [ ] **Step 10: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/api/v1/agent_teams.py \
  backend/app/services/github_verification_service.py \
  backend/tests/agent_teams/test_github_verification_service.py \
  backend/tests/agent_teams/test_github_workspace_api.py \
  backend/tests/agent_mail/test_dispatch_status_tool.py
git commit -m "feat(github): create pull requests with reconciliation"
```

---

### Task 8: Integrate briefs, MCP reporting, handoff identity, and release cleanup

**Files:**

- Modify: `backend/app/services/github_dispatch_service.py`
- Modify: `backend/app/services/github_workspace_service.py`
- Modify: `backend/mcp_shim/agent_mail_server.py`
- Modify: `backend/tests/agent_teams/test_github_dispatch_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_service.py`
- Modify: `backend/tests/agent_teams/test_github_workspace_api.py`
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`

- [ ] **Step 1: Write secrecy test 5 and brief test 12 from persisted evidence.**

App-mode brief contains the exact persisted `dispatch_head_ref` re-read from the row, the commit identity convention, exact `Deck-Agent-Slot: <id> (<display name>)` and `Deck-Work-Item: <id>` trailers, push command, and `pr_ready(head_ref=...)`. It does not instruct `pr_opened`, claim the agent owns PR title/body, or retain the old generic branch placeholder. Ambient brief keeps verified `pr_opened(pr_number=...)` and never claims bot authorship.

Complete test 5 here, where the final missing evidence surface exists. Task 2's service tests cover private-key/JWT/token service logs, and Task 7 test 18 covers the installation token on PR creation. In this task, use the real `GithubAppAuthService` with a temporary RSA key and `httpx.MockTransport` for installation lookup. Capture the generated App JWT from the mock request, then capture the dispatch brief; assert the private-key contents and captured JWT are absent from the brief, `status_note`, and dispatch logs. Also assert installation-token minting was never called before brief delivery: a token does not exist on this path, so do not add a fake mint merely to make a vacuous “token not in brief” substring assertion. The combined Task 2, 7, and 8 assertions complete test 5.

- [ ] **Step 2: Update the MCP report tool.**

Add optional `head_ref` forwarding and return Deck's response data unchanged, including `pr_number`. Document allowed status/payload pairs and require `head_ref` for `pr_ready`. Do not expose a separate PR-title/body tool. Preserve session-token headers and lease token behavior.

- [ ] **Step 3: Rewrite worktree identity on accepted handoff (test 26).**

Use the current workspace and target slot. Under the shared config lock, snapshot the current managed identity, then stage conditional SQL updates for PR1's owner/ack fields and the workspace liveness fields without committing. Predicates include the current owner, pending target, workspace id/scope/item, lease token, and `leased_at`. After exactly one item/workspace pair matches, rewrite the worktree identity and commit the DB transfer. On config or commit failure, roll back and restore the prior identity before releasing the lock. If restoration fails, keep the old DB owner/handoff state, persist an operator-visible repair note in a fresh transaction, and refuse acceptance. Keep `dispatch_head_ref` and lease token byte-identical. The target brief must say not to work until `handoff_accepted` returns `200`. Tests inject both config failure and DB commit failure after rewrite and prove old identity/ownership remain together.

- [ ] **Step 4: Remove identity/helper on every release path (test 27).**

Centralize cleanup so `release`, token/owner release, force release, failed reset/launch cleanup, stale reclaim, and operator release cannot diverge. Replace the plain read-then-clear `release()` implementation; no caller may fall back to it after inspecting a row.

The shared release primitive receives workspace id, scope id, item id, lease token, and expected `leased_at`, plus the owner/status predicate for agent release. Internal and agent paths pass the timestamp they captured with the acquisition; force-release passes the request's confirmed timestamp while keeping the lease token server-captured. Under the config lock it takes the lossless managed-key snapshot from Task 3, issues the conditional lease-clear `UPDATE` without committing, and requires exactly one affected row before touching git. The write sets `leased_item_id=None`, `released_at=now`, `lease_token=None`, `leased_owner_pid=None`, `leased_owner_proc_start=None`, `lease_last_owner_contact_at=None`, `lease_release_reminded_at=None`, and `updated_at=now`. It then removes URL-scoped helper/useHttpPath and worktree user fields and commits. A primary uses the same conditional metadata write but skips every config command. Treat “key absent” as idempotent success. On cleanup/commit failure, roll back and restore the exact scalar/multi-value snapshot; a failed restoration leaves the lease held and records the repair note. Return an explicit released/not-released result: stale reclaim increments its count and callers emit success/logs only on a committed release. Force-release logs success only after commit. Duplicate owner reports preserve PR1's explicit idempotent path rather than interpreting every zero-row result as success.

- [ ] **Step 5: Re-check acquisition after awaited config operations.**

The uncommitted conditional write prevents a second process from replacing the row while git cleanup is awaited; the config lock prevents the in-process equivalent. A replacement token/owner before the write means zero rows, rollback, no config command, and no success. Add interleavings for plain internal release, token release, owner release, force release, and stale reclaim. Each must fail an implementation that cleans before acquiring the DB write lock, commits the clear before cleanup, drops any acquisition predicate, or delegates to the old unconditional release.

- [ ] **Step 6: Add unnumbered lifecycle integration around test 46r.**

Assert old owner retains the same lease token but cannot mint; new owner can mint and sees rewritten commit identity; ambient and App worktree release both remove identity, App release also removes the helper, and pre-upgrade primary reconciliation changes metadata only. This proves the token remains attempt binding rather than owner identity and cleanup is keyed to what PR2 may have written, not to the scope's mode at release time.

- [ ] **Step 7: Mutation-test lifecycle integration.**

Kill: old App brief wording, head recomposition, handoff leaves old identity, handoff commits DB before config, commit failure leaves target identity, target works before acceptance, release commits DB before cleanup, release cleans before staging the conditional write, plain release remains item-id-only, force-release substitutes a fresh `leased_at` for the operator's expected value, one release caller bypasses cleanup, primary config touched, ambient identity retained, replacement config stripped after race, MCP drops `head_ref` or `pr_number`, and `GH_TOKEN` reintroduced for convenience.

- [ ] **Step 8: Run focused integration suites.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_github_workspace_service.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/agent_mail/test_dispatch_status_tool.py \
  tests/agent_mail/test_mcp_shim.py -q -p no:warnings
```

- [ ] **Step 9: Commit.**

```bash
git add backend/app/services/github_dispatch_service.py \
  backend/app/services/github_workspace_service.py \
  backend/mcp_shim/agent_mail_server.py \
  backend/tests/agent_teams/test_github_dispatch_service.py \
  backend/tests/agent_teams/test_github_workspace_service.py \
  backend/tests/agent_teams/test_github_workspace_api.py \
  backend/tests/agent_mail/test_dispatch_status_tool.py \
  backend/tests/agent_mail/test_mcp_shim.py
git commit -m "feat(dispatch): complete app-auth worktree lifecycle"
```

---

### Task 9: Enforce state namespaces and document the gated rollout

**Files:**

- Modify: `backend/app/services/github_dispatch_service.py`
- Create: `backend/tests/agent_teams/test_dispatch_state_namespaces.py`
- Create: `docs/deploy/pr2-github-app-rollout.md`

- [ ] **Step 1: Declare the three namespaces.**

Declare these literal sets; do not derive them from the code under test:

```python
DISPATCH_STATUSES = frozenset({
    "pending", "dispatched", "verifying", "ready_for_review",
    "awaiting_human_review", "merged", "completed", "escalated", "failed",
})

ESCALATION_REASONS = frozenset({
    "plan_blocked", "launch_outcome_unknown", "approval_rounds_exhausted",
    "leader_offline", "owner_offline", "brief_unread", "leader_ack_timeout",
    "owner_idle_timeout", "retry_count_exhausted", "dispatch_label_removed",
    "abandoned_by_operator", "prepared_owner_unavailable", "pr_closed_unmerged",
})

PENDING_REASONS = frozenset({
    "queued_repo_cap", "queued_low_memory", "queued_slot_busy",
    "queued_ambiguous_sessions", "queued_no_workspace",
    "queued_auth_mode_unresolved",
})
```

Assert equality for the first two. Assert only that PR2's named pending reasons are members of the third because `pending_reason` already accepts operator free text. `_apply_escalation` validates its reason at runtime.

- [ ] **Step 2: Implement synthetic classifier test 29-a2 first.**

Prove the AST classifier distinguishes ORM writes from response constructors, assignments/annotated assignments, unknown helper/update forms, `setattr`, and `GithubWorkItem(**payload)`. Reject any splat into `GithubWorkItem`; allow unrelated ORM splats. Keep the known `setattr` baseline explicit and commented.

- [ ] **Step 3: Implement whole-tree writer scan 29-a1.**

Derive writers from `backend/app/`, resolve literals and same-file module constants, fail all unknown call/RHS forms except the two documented dynamic sites, assert per-file site-count baselines, exactly one non-NULL escalation funnel, zero undeclared dispatch statuses, and unchanged `setattr` baseline. Record the measured post-PR2 counts in the test, not in this plan.

- [ ] **Step 4: Implement behavioural table 29-b.**

Use one fresh DB per case for `pr_ready` open/merged/closed/no-match/two-open/unclassifiable, `pr_opened` open/merged/closed, verifier closed, auth-mode refusal, and no-worktree refusal. Assert produced values are declared without claiming this table is exhaustive.

- [ ] **Step 5: Write the deployment document.**

Document, but do not execute:

- Required GitHub App permissions and per-repository installation.
- `backend/.env` settings, private key path, bot login, mode `0600`, and backend restart.
- The manual reset safety gate: disable autonomy for affected presets, verify no affected `github_workspaces.leased_item_id` is non-NULL, then update `(github_auth_mode, github_app_installation_id)` together to `(unknown, NULL)` and read both columns back. Never reset a live scope because its helper reads the persisted installation id.
- Ambient-first rollout, one sandbox App scope, push/PR verification, then additional scopes.
- Expected `app_not_installed`, `app_auth_unconfigured`, `app_mode_bot_login_unset`, `queued_auth_mode_unresolved`, `pane_unresolved`, and stale-helper `501` diagnostics.
- Rollback: disable autonomy, remove helper config from unleased test worktrees, clear App settings, restart, reset scope mode, verify ambient path.
- Manual provisioning and branch protection remain human actions outside the PR.

- [ ] **Step 6: Mutation-test the namespace scanner itself.**

Inject every spec mutation: undeclared literal, second escalation writer, unknown `values`, helper keyword, `setattr`, declared constructor writer, cross-module constant, existing literal changed, same-file constant replacement control, and `GithubWorkItem` splat. Each named assertion must catch only the intended class where possible.

- [ ] **Step 7: Run namespace and scoped suites.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_dispatch_state_namespaces.py -q -p no:warnings
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
```

- [ ] **Step 8: Commit.**

```bash
git add backend/app/services/github_dispatch_service.py \
  backend/tests/agent_teams/test_dispatch_state_namespaces.py \
  docs/deploy/pr2-github-app-rollout.md
git commit -m "test(dispatch): enforce github state namespaces"
```

---

### Task 10: Run the complete PR2 review and validation gate

**Files:** All PR2 files.

- [ ] **Step 1: Run format/static checks already configured by the repository.**

Do not add a formatter or type checker. Run only existing commands. At minimum:

```bash
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT/backend"
venv/bin/python -m compileall -q app mcp_shim
cd "$ROOT/frontend"
./node_modules/.bin/tsc -b
```

`frontend/package.json` has no `typecheck` script. Use the already-installed local compiler above (the type phase of `npm run build`); do not use `npx`, which may fetch from the network, and do not run the Vite build merely to validate a backend-only PR. If `frontend/node_modules/.bin/tsc` is absent, stop and report the missing prerequisite rather than installing packages during validation.

- [ ] **Step 2: Run focused security/lifecycle suites.**

```bash
cd "$(git rev-parse --show-toplevel)/backend"
venv/bin/pytest \
  tests/agent_teams/test_github_app_auth_service.py \
  tests/agent_teams/test_github_client.py \
  tests/agent_teams/test_git_credential_helper.py \
  tests/agent_teams/test_github_workspace_service.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_agent_team_service.py \
  tests/agent_teams/test_github_watcher_service.py \
  tests/agent_teams/test_github_verification_service.py \
  tests/agent_teams/test_dispatch_state_namespaces.py \
  tests/agent_mail/test_api.py \
  tests/agent_mail/test_peer_process.py \
  tests/agent_mail/test_dispatch_status_tool.py \
  tests/agent_mail/test_mcp_shim.py \
  tests/test_sqlite_compat_migrations.py \
  -q -p no:warnings
```

- [ ] **Step 3: Run scoped and full suites.**

```bash
cd "$(git rev-parse --show-toplevel)/backend"
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
venv/bin/pytest tests/ -q -p no:warnings
```

The known #312 failure may remain. Any other failure is PR2 work or a newly discovered unrelated failure; diagnose and report before changing unrelated code.

- [ ] **Step 4: Re-run every named mutant.**

Use temporary copies or exact reversible edits. Do not leave mutants in Git history. Produce a table: mutant, test command, expected failing assertion, observed failure. Review-only rows (per-item versus global lock, secret comparison timing) must be labeled honestly rather than credited to a test.

- [ ] **Step 5: Audit secrets and forbidden state mechanically.**

```bash
cd "$(git rev-parse --show-toplevel)"
rg -n "GH_TOKEN|GITHUB_TOKEN|github_app_private_key|installation token|password=" \
  backend/app backend/mcp_shim docs/deploy/pr2-github-app-rollout.md
rg -n "pr_closed_unmerged|queued_auth_mode_unresolved|DISPATCH_STATUSES|ESCALATION_REASONS|PENDING_REASONS" \
  backend/app backend/tests/agent_teams/test_dispatch_state_namespaces.py
rg -n "_classify_pull" backend/app
rg -n "pr_number\s*=" backend/app
```

Inspect each hit. Settings names and response serialization are expected; secret values, pane env, duplicate classifiers, unverified `pr_number` writers, and new dispatch statuses are not.

- [ ] **Step 6: Audit all release and owner-change callers.**

Enumerate callers of `acquire`, every release primitive, `accept_handoff`, and worktree config helpers. Confirm every release cleans config under the workspace lock and every owner change rewrites identity without moving `dispatch_head_ref` or rotating `lease_token`.

- [ ] **Step 7: Verify repository cleanliness and commit any review-only fixes.**

```bash
cd "$(git rev-parse --show-toplevel)"
git diff --check
git status --short
git log --oneline --decorate -12
```

If review fixes are needed, add tests first and commit them as:

```bash
git commit -m "fix(github): close pr2 review gaps"
```

Do not add `docs/superpowers/handoffs/` or any `.env`, DB, key, log, temporary repo, or mutation artifact.

## Final Review Gate

### 1. Spec coverage review

- [ ] Every PR2 numbered test referenced across the spec's PR2 sections is owned by exactly one task or explicitly preserved from merged PR1; every docstring uses its real section, not a blanket §5.8 label.
- [ ] Every §8 PR2 criterion has at least one implementation path and one test/review artifact.
- [ ] Lookup `404` and mint `404` remain separate behaviors.
- [ ] Stored App mode refuses missing runtime prerequisites without re-resolution or downgrade.
- [ ] App/ambient/unknown mode behavior is persisted per scope, not inferred from a global setting at report time.
- [ ] Primary workspaces are excluded before lease mutation.
- [ ] Credentials require repo, acquisition, and kernel-derived current owner.
- [ ] `pr_ready` records and returns only GitHub-returned numbers, uses exact persisted head equality, and passes one explicit App token to every GitHub call.
- [ ] PR reconciliation exhausts every pagination page before it creates or mutates an item.
- [ ] List and single PR payloads call the same classifier using `(state, merged_at)`.
- [ ] Closed-unmerged PRs escalate before mail, checks, draft promotion, or merge.
- [ ] Human-merge reservation notes survive retryable classification failures.
- [ ] Handoff changes identity but not branch or lease token.
- [ ] Release stages a conditional DB write before cleanup, commits only after cleanup, and removes helper/identity before reporting success.

### 2. Completeness scan

- [ ] No placeholder (`TODO`, `pass`, `NotImplementedError`, fake token/key, unasserted mock) remains.
- [ ] No helper endpoint resolves an installation.
- [ ] No report schema accepts PR title/body.
- [ ] No App token is stored on a global `GithubClient`, model, config file, note, or prompt.
- [ ] No duplicate PR classifier, base normalizer, identity slugger, or helper command composer exists.
- [ ] Every new error has a stable, tested code/message and contains no credential.
- [ ] Deployment instructions are clearly manual and were not executed.

### 3. Type, async, and race review

- [ ] Dependency annotations match their dependency return types.
- [ ] Request-pane resolution occurs synchronously before the socket disappears.
- [ ] Cache locks are per installation/repo; PR locks are per item; config locks are per workspace.
- [ ] No lock is held while awaiting unrelated repo/item work.
- [ ] Every network timeout/422 path reconciles once and does not create again blindly.
- [ ] Every fresh race diagnosis performs SQL rather than reading the identity map.
- [ ] Every worktree cleanup and DB release preserves acquisition predicates.
- [ ] Handoff rollback restores the previous worktree identity if ownership/liveness cannot commit.
- [ ] The helper owner is rechecked after token mint before a credential is returned.

### 4. Handoff after implementation

Report:

- Branch and commit list.
- Scoped and full test results, including the exact #312 status.
- Typecheck/compile results.
- Mutation table with honest review-only rows.
- Confirmation that no public GitHub write, real App action, live DB edit, or agent dispatch occurred.
- Confirmation that the branch is pushed or unpushed according to the user's latest instruction, and that no PR was merged automatically.
