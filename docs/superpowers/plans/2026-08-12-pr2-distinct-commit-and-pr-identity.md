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

**Correction (2026-08-12, credential-transport seam audit) — HTTPS origin is a precondition.** The spec configures `credential.https://github.com.*` but never constrains the workspace's push URL. Git does not invoke an HTTP credential helper for `git@github.com:owner/repo.git` or `ssh://...`; such a worktree would push with the pane's SSH identity and silently defeat App authorship. PR2 must not rewrite the shared repository remote. Before configuring an App-mode helper, read `git remote get-url --push origin` and require the exact scope repository over `https://github.com/<owner>/<repo>[.git]`. SSH, another host/repo, multiple push URLs, or an unreadable origin fails closed with existing `queued_auth_mode_unresolved`, a diagnostic `status_note`, no worktree config, and the lease released. Ambient mode remains untouched and may use any existing transport.

## Global Constraints

### Working environment

- Work only in `/home/juan/work/repos/juanrubio/claude-deck-g1`.
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
- All App-mode release paths remove agent git identity and the Deck helper. A cleanup failure must fail closed: do not report a release as successful while the helper remains configured.
- Per-item PR locks and per-workspace config locks are single-process coordination only. Reconciliation and conditional DB predicates remain the correctness mechanisms.

### Code and API conventions

- Use `python3`; backend test commands use `venv/bin/pytest`.
- Preserve async boundaries and explicit type hints.
- Add one `GithubAppAuthService`; do not put JWT, installation lookup, or cache logic in route handlers.
- Keep `GithubClient` as the REST transport. App-auth service supplies an explicit token to calls that need App identity; existing ambient callers keep their current behavior.
- Use one `_classify_pull` implementation for list and single-pull payloads. It reads only `state` and the **presence/value** of `merged_at`.
- Pull-list fixtures must omit `merged`; single-pull fixtures must include it. Assert the shape explicitly.
- Worktree helper configuration uses the URL-scoped key, `useHttpPath=true`, then empty-helper and add-helper as separate commands.
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
| `backend/app/services/github_client.py` | Modify | Explicit-token headers, ref/default-branch/list/create PR methods |
| `backend/app/services/github_workspace_service.py` | Modify | Primary exclusion, per-worktree identity/helper lifecycle, config lock |
| `backend/app/services/github_dispatch_service.py` | Modify | Auth-mode resolution, brief mode, handoff identity rewrite, namespace declarations |
| `backend/app/services/github_verification_service.py` | Modify | Shared classifier, verified legacy reports, `pr_ready`, reconciliation, stage-aware failures |
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
| `backend/tests/agent_teams/test_github_verification_service.py` | Modify | PR classifier, legacy report, verifier, reconciliation, creation |
| `backend/tests/agent_teams/test_github_workspace_api.py` | Modify | Kernel-bound credential callback and lease/path refusals |
| `backend/tests/agent_mail/test_peer_process.py` | Modify | Detailed resolver and unchanged default budget |
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

The spec reuses numeric ids across PR sections. Keep PR2 tests in PR2-focused files and refer to them as “§5.8 test …” in docstrings. A later task may rerun or extend an earlier test with unnumbered integration assertions, but each numbered test has exactly one owner below.

| Task | PR2 §5.8 tests owned |
| --- | --- |
| 1 | Unnumbered migration/default/direct-dependency checks |
| 2 | 4, 5, 6, 7 |
| 3 | 1, 2, 3, 23, 24, 25, 28, 28b, 28c, 28d, 30, 30c, 30d, 30e, 31, 32, 33, 34, 35 |
| 4 | 19, 20, 21, 22, 30b, 31b, 46r, plus the peer-budget correction |
| 5 | 8, 9, 10, 11, 11b, 11c, 11d, 11e, 29c, 29d, 29e, 29f, 29g, 29g-1, 29h, 29h-1, 29h-2, 36, 37, 37b, 37c; complete merged PR1 test 29b |
| 6 | Unnumbered GitHub transport and pure template/base helper tests |
| 7 | 13, 14, 15, 16, 17, 17b, 18, 38, 39, 40, 41, 42, 43, 44, 45, 46, 46b, 46c, 46d, 46e, 46f, 46g, 46h, 46i, 46j, 46k, 46l, 46m, 46n, 46o, 46o-1, 46o-2, 46o-3, 46p, 46q, 47, 48, 49, 49b, 50 |
| 8 | 12, 26, 27, plus unnumbered lifecycle integration assertions that rerun 25 and 46r |
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

Read `requirements.txt` and `pyproject.toml` as data. Require direct entries for `pyjwt[crypto]` and `cryptography`; do not accept transitive importability as proof. Verify `uv.lock` identifies both packages after refresh.

- [ ] **Step 3: Run the red tests and record collection count.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_app_auth_service.py tests/test_sqlite_compat_migrations.py -q -p no:warnings
```

- [ ] **Step 4: Add settings, ORM columns, and migration rungs.**

Use `String(default="unknown", nullable=False)` and nullable `Integer`. The migration order is mode then id. Do not expose either field in `TeamGithubScopeCreate` or `Update`; mode changes remain the manual/operator rollout action §5.9 describes.

- [ ] **Step 5: Declare and lock direct dependencies.**

Update both manifests, then refresh the lock with the repository's existing uv workflow. Do not upgrade unrelated packages.

- [ ] **Step 6: Run focused and migration tests.**

```bash
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

- [ ] **Step 3: Write token mint/cache tests (spec tests 4–7).**

Assert:

- Mint JSON narrows with `repositories=[repo]`.
- Cache key is `(installation_id, "owner/repo")`.
- Outside refresh margin the same token is reused.
- Inside margin a fresh token is minted.
- Concurrent same-key calls mint once under one lock.
- Different keys do not wait on one global lock.
- Token/JWT/private key are absent from logs and returned error text.
- Mint `404` produces `app_not_installed` naming repo and id, without a mode mutation side effect.

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
  tests/agent_teams/test_github_client.py -q -p no:warnings
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

- [ ] **Step 1: Write primary-exclusion tests 28–28d first.**

Use a lower-id `primary` and a later `worktree`, both `dispatchable=True`. Default acquire must lease the worktree on the first call and leave every primary lease field untouched. Primary-only dispatch returns existing `queued_no_workspace`, includes skipped-primary count in `status_note`, and succeeds after a worktree is added. `allow_primary=True` is the sole positive primary case.

- [ ] **Step 2: Write real-git identity/config tests 1–3 and 23–24.**

In linked temporary worktrees with an isolated temporary `HOME`/global git config assert:

- `extensions.worktreeConfig=true`.
- Worktree-only `user.name` and slugged `user.email`.
- Punctuation/spaces collapse into lowercase `[a-z0-9.-]` local-part plus `+slot<ID>@claude-deck.local`.
- A sibling worktree and primary checkout remain unchanged.
- App mode writes `useHttpPath`, empty helper, then Deck helper in that order.
- Ambient mode writes identity only, leaves the global helper reachable, and has no URL-scoped helper entry.
- No helper/identity write happens before mode resolution succeeds.
- App mode refuses before config when `origin` pushes through SSH, another host/repo, multiple push URLs, or an unreadable remote. Ambient mode does not inspect or rewrite the remote.

- [ ] **Step 3: Write owned auth-mode tests 30, 30c–30e, and 31–35.**

Cover all six persisted `(mode, id)` combinations and lookup outcomes. `200` stores `app` and id in one commit. Lookup `404` stores `ambient` and NULL id and proceeds. Unconfigured settings store ambient without a network call. Transient/auth failures leave unknown unchanged, clear/release the acquired worktree, set `queued_auth_mode_unresolved`, and write no config. Stored `app/id` never re-resolves. `unknown/id` clears then resolves; `ambient/id` clears and never mints; `app/NULL` refuses without lookup.

- [ ] **Step 4: Implement safe acquisition and identity helpers.**

Add keyword-only `allow_primary: bool = False` and inject `kind != "primary"` into the selection query before any lease write. Add helpers for slot identity, email slug, worktree config application, and config removal. Keep helper command construction centralized so tests can assert exact commands.

- [ ] **Step 5: Integrate mode resolution after lease acquisition and before config/brief.**

The order is:

1. Acquire a non-primary workspace.
2. Normalize inconsistent stored mode/id.
3. Resolve only `unknown`.
4. Persist mode and id together.
5. For `app/id`, validate the exact HTTPS GitHub `origin` push URL without rewriting it.
6. Apply identity and, only for a transport-valid `app/id`, helper config.
7. Prepare/send/launch as before.

If steps 2–5 refuse, clean any partial config, release the acquisition, leave the item pending with `queued_auth_mode_unresolved`, and continue without sending a brief.

- [ ] **Step 6: Assert pane launch env remains credential-free (test 25).**

Capture `spawn_session(..., extra_env=...)` on spawn and reuse-related launch tests. Assert neither `GH_TOKEN` nor `GITHUB_TOKEN` appears. This is a regression guard; do not add production env filtering for keys never supplied.

- [ ] **Step 7: Mutation-test ordering and primary selection.**

Kill: primary filter after lease, filter by `dispatchable` only, default `allow_primary=True`, helper configured before lookup, transient failure treated as ambient, App/NULL re-resolved, SSH origin accepted, remote rewritten instead of refused, and empty-reset omitted.

- [ ] **Step 8: Run focused suites.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_workspace_service.py \
  tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_agent_team_service.py -q -p no:warnings
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
- Pane binding must exist and its slot must equal the current item owner.
- After real A→B handoff with retained token, A is `403`, B mints, unbound is `pane_unresolved`, and missing token refuses before a pane walk.
- Mint `404` returns `app_not_installed` without changing mode/id.

- [ ] **Step 5: Implement the callback as one owner-gated operation.**

Join token → workspace → item → scope, validate repo and mode, derive the pane from the live request, load the binding, compare binding slot to a fresh current `owner_slot_id`, then mint from the persisted id. Use a per-workspace process lock across authorization and mint so an in-process handoff/release cannot interleave after the owner check. Re-read acquisition/owner before returning the credential; disagreement refuses and discards the minted token.

- [ ] **Step 6: Implement and test the stdlib helper.**

Use `urllib.request`, not `httpx`, so the pane needs only Python. Accept `--deck-url`, `--lease`, and git's appended operation. Never echo the lease or response body. Test stdin parsing, `.git` path forwarding, GET/no-op behavior, refusal, malformed JSON, and credential output exactly. For §5.8 test 19, use an isolated temporary `HOME` and global git config, configure a real temporary repository with `useHttpPath=true`, point its helper at a capture script, run `git credential fill`, and assert `path=owner/repo.git` reached the helper. Run the omitted-`useHttpPath` mutant and prove the path disappears. No test may consult the user's real credential stack.

- [ ] **Step 7: Add the Linux real-process ancestry test.**

Start an isolated ephemeral backend and nested shell/helper process. Seed a binding for the designated ancestor and a test lease. Use the real loopback socket and `/proc` walk; only GitHub mint is stubbed. Assert the measured chain resolves under 16 and the same call refuses under a deliberately smaller cap. Mark non-Linux skip explicitly.

- [ ] **Step 8: Mutation-test identity versus token.**

Kill: token-only auth, caller-supplied slot, host-only repo check, installation re-lookup, mail default changed from 32, missing second owner/acquisition read, and failure text containing the token.

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

- Modify: `backend/app/services/github_verification_service.py`
- Modify: `backend/app/api/v1/agent_teams.py`
- Modify: `backend/tests/agent_teams/test_github_verification_service.py`
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`

- [ ] **Step 1: Write endpoint-faithful classifier fixtures.**

Create separate list-pull and single-pull factories. List fixtures assert `"merged" not in pull`; single fixtures carry `merged`, `mergeable`, `mergeable_state`, and `merged_by`. Both carry `state`, `merged_at`, `merge_commit_sha`, `head`, `base`, `number`, and `draft`.

- [ ] **Step 2: Implement and exhaustively test `_classify_pull`.**

The only accepted results are:

```text
state=open,   merged_at=None       -> open
state=closed, merged_at=<value>    -> merged
state=closed, merged_at=None       -> closed_unmerged
```

Missing `merged_at`, unknown/missing state, or `open` with non-NULL `merged_at` returns `None`. Never read `merged` or `merge_commit_sha`. Run the nine existing-shape regression matrix plus new incoherent/missing cases (46l–46o-3).

- [ ] **Step 3: Harden `report_pr_opened` before any mutation or mail.**

Change its signature to accept a `GithubClient`. Fetch the PR; verify repository and exact stored head first; enforce the author only for persisted `app` mode; refuse `app_mode_bot_login_unset`; skip author checks for `ambient` and `unknown`; then classify. Open uses today's transition. Merged records number and marks merged with blocker notification, no design-review mail. Closed-unmerged escalates `pr_closed_unmerged`, leaves `pr_number` NULL, and sends no mail. `None` refuses with no writes.

- [ ] **Step 4: Add verifier classification before all CI/review work.**

Both `_verify_item` and `_process_review_item` call the shared helper before check runs, draft promotion, or merge. Closed-unmerged escalates immediately. Merged reconciles. `None` consumes retry budget with `head_sha=None`.

- [ ] **Step 5: Make failure retry stage explicit and reservation-safe.**

Add required keyword-only `retry_status` with no default to `_record_failed_verification_attempt`. Verify-stage callers pass `"dispatched"`; review stage passes `item.dispatch_status`. Add `_set_failure_note` keyed on `_HUMAN_MERGE_NOTE_PREFIXES`; still send owner mail. Escalate with local `note`, not `item.status_note`. Same-sha logic compares against `retry_status`.

- [ ] **Step 6: Write tests 8–11e, 29c–29h-2, and 36–37c.**

Include wrong repo/head/author, App-login unset, ambient/unknown author skip, merged design with zero review mail, closed-unmerged with non-null `merge_commit_sha`, shared-classifier sentinel at all three call sites, repository/head-before-state ordering, green-check closed PR refusing before checks, unclassifiable retry sequence, design-stage preservation, and sticky human-merge reservation.

- [ ] **Step 7: Complete the merged PR1 `in_progress` test.**

Extend the existing `pr_number=9999` liveness regression with `github_dispatch_service._ack_satisfied(item) is False`, then run it. Do not add a second production edit or duplicate test.

- [ ] **Step 8: Mutation-test every branch.**

At minimum: classify on `merged`; substitute `merge_commit_sha`; classify before repo/head; author keyed on global login rather than mode; App/empty login skipped; closed condition after checks; `None` returns without increment; real sha passed on `None`; retry default added; reservation note overwritten; escalation passed stored note; duplicated classifier bypasses sentinel.

- [ ] **Step 9: Run focused tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_verification_service.py \
  tests/agent_mail/test_dispatch_status_tool.py -q -p no:warnings
```

- [ ] **Step 10: Commit.**

```bash
git add backend/app/services/github_verification_service.py \
  backend/app/api/v1/agent_teams.py \
  backend/tests/agent_teams/test_github_verification_service.py \
  backend/tests/agent_mail/test_dispatch_status_tool.py
git commit -m "fix(github): classify pull requests before advancing"
```

---

### Task 6: Add GitHub ref/PR transport and deterministic PR presentation

**Files:**

- Modify: `backend/app/services/github_client.py`
- Modify: `backend/tests/agent_teams/test_github_client.py`
- Modify: `backend/tests/agent_teams/test_github_verification_service.py`

- [ ] **Step 1: Add transport tests before methods.**

Specify:

- `get_ref(owner, repo, head, token=...)` with correctly URL-encoded `heads/<head>`.
- `get_repository(owner, repo, token=...)` for `default_branch`.
- `list_pulls_for_head(..., head=f"{owner}:{branch}", base=<normalized>, state="all", token=...)`.
- `create_pull(..., title, head, base, body, draft, token=...)`.

Assert explicit App token authorization and update the module docstring's writer list to include `create_pull`.

- [ ] **Step 2: Implement one base normalization helper.**

`origin/master -> master`. `origin/HEAD` calls `get_repository` and uses `default_branch`. Any other `origin/<name>` strips one prefix. A missing default branch refuses; it never sends `HEAD`.

- [ ] **Step 3: Implement deterministic title/body/draft helpers.**

Title is exactly `[<current owner slot display_name>] <issue title> (#<issue number>)`. Body includes `Closes #n`, issue title, and a provenance block naming work item id, current owner slot id, dispatch nonce, and exact head. `draft = issue_type != "design"`. Reports do not influence these values.

- [ ] **Step 4: Write unnumbered pure/template helper tests.**

Cover design/non-draft, code/draft, verbatim title/body, both base forms, and caller `title`/`body` rejected or ignored by the schema. Use the same normalized base helper for list and create; monkeypatch a sentinel to prove both consult it.

- [ ] **Step 5: Run transport/template tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_client.py \
  tests/agent_teams/test_github_verification_service.py -q -p no:warnings
```

- [ ] **Step 6: Commit.**

```bash
git add backend/app/services/github_client.py \
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
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`

- [ ] **Step 1: Add `pr_ready` to the owner-only status matrix.**

It requires the current lease token exactly like `pr_opened`. `DispatchStatusReport` gains `head_ref`; it does not gain `title` or `body`. App mode accepts `pr_ready` and rejects legacy creation authority; ambient/unknown refuse `pr_ready` and preserve verified `pr_opened`.

- [ ] **Step 2: Write cheap-path and authorization tests 13–18.**

Assert stale lease, wrong owner, NULL stored head, byte-mismatched head, and missing remote ref all refuse before any pull-list/create call. If `item.pr_number` is already set, return it without ref/list/create network calls. App token is used for create and absent from logs.

- [ ] **Step 3: Implement per-item locks and reconciliation helpers.**

Under the lock:

1. Re-read item and lease authorization.
2. Cheap-return a stored number.
3. Validate exact stored head and remote ref.
4. Normalize base once.
5. List `state=all` by qualified head/base.
6. Classify the complete result set.
7. Create only when classification finds no history.
8. On timeout or `422`, reconcile once more; never blind-retry create.

- [ ] **Step 4: Implement multi-match classification 38–46o-3.**

Rules in order:

- Exactly one open → verify repo/head/auth and adopt.
- Two or more open → `409`, item unchanged, status note names all open PR ids.
- No open, one or more merged → choose highest PR number, record all merged ids in note, mark merged, notify blocker.
- No open/merged, one or more closed-unmerged → escalate `pr_closed_unmerged`, leave `pr_number` NULL, name all ids.
- Any unclassifiable match → `409`, no create/escalation/mutation.

An open PR outranks closed history. Merged outranks closed-unmerged. Multiple merged is not ambiguous.

- [ ] **Step 5: Verify adopted and created PRs with the correct check set.**

For an adopted PR, run the shared repository, exact-head, and App-mode bot-author checks before classification/recording; adoption is discovery, not trust. For Deck's own `create_pull` response, verify repository and exact head and classify it, but **do not** run the legacy author check — Deck supplied the installation credential, so authorship is structural and checking the returned login is a tautology. Never adopt solely because the head/base query matched.

- [ ] **Step 6: Add real-git attempt-ref tests 46p/46q.**

Against a temporary bare remote, verify sibling legacy and attempt refs coexist in both creation orders; child refs fail with the expected lock-ref message. Parametrize hostile display names and prove `attempt_head_ref` is byte-identical because it uses numeric slot id, then `git check-ref-format --branch` passes.

- [ ] **Step 7: Complete tests 47–50 through the real handler.**

Design `pr_ready` creates non-draft and notifies review; code creates draft and verifies; payload fields cannot override title/body; both base paths reach list and create normalized; response PR number is the only number recorded.

- [ ] **Step 8: Mutation-test crash and classification boundaries.**

Kill: `pr_number` only idempotency, no post-timeout reconcile, hard `422`, unqualified head, raw base_ref, state=open query, single-match state-blind adoption, multiple-merged 409, closed before merged, unknown defaults open, per-item lock changed to global (review-only if not directly observable), and caller-supplied PR number/title/body.

- [ ] **Step 9: Run focused tests.**

```bash
cd backend
venv/bin/pytest tests/agent_teams/test_github_verification_service.py \
  tests/agent_mail/test_dispatch_status_tool.py \
  tests/agent_teams/test_github_client.py -q -p no:warnings
```

- [ ] **Step 10: Commit.**

```bash
git add backend/app/models/schemas.py backend/app/api/v1/agent_teams.py \
  backend/app/services/github_verification_service.py \
  backend/tests/agent_teams/test_github_verification_service.py \
  backend/tests/agent_mail/test_dispatch_status_tool.py \
  backend/tests/agent_teams/test_github_client.py
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
- Modify: `backend/tests/agent_mail/test_dispatch_status_tool.py`
- Modify: `backend/tests/agent_mail/test_mcp_shim.py`

- [ ] **Step 1: Write brief test 12 from persisted evidence.**

App-mode brief contains the exact persisted `dispatch_head_ref` re-read from the row, the commit identity convention, exact `Deck-Agent-Slot: <id> (<display name>)` and `Deck-Work-Item: <id>` trailers, push command, and `pr_ready(head_ref=...)`. It does not instruct `pr_opened`, claim the agent owns PR title/body, or retain the old generic branch placeholder. Ambient brief keeps verified `pr_opened(pr_number=...)` and never claims bot authorship.

- [ ] **Step 2: Update the MCP report tool.**

Add optional `head_ref` forwarding. Document allowed status/payload pairs. Do not expose a separate PR-title/body tool. Preserve session-token headers and lease token behavior.

- [ ] **Step 3: Rewrite worktree identity on accepted handoff (test 26).**

Use the current workspace and target slot. Rewrite identity under the same per-workspace config lock used by credential/release paths, then commit PR1's owner/liveness transfer. Keep `dispatch_head_ref` and lease token byte-identical. A real commit after acceptance must show the new owner identity.

- [ ] **Step 4: Remove identity/helper on every release path (test 27).**

Centralize cleanup so `release`, token/owner release, force release, failed reset/launch cleanup, stale reclaim, and operator release cannot diverge. Hold the workspace config lock, verify the captured acquisition, remove URL-scoped helper/useHttpPath and worktree user fields, then perform the existing conditional DB release. Treat git's “key absent” exit as idempotent success; any other cleanup failure leaves the lease intact and reports/raises. Never clear DB state first and clean later.

- [ ] **Step 5: Re-check acquisition after awaited config operations.**

The config lock prevents in-process replacement, but the DB predicate remains required. A replacement token/owner means no release and no success. Add an interleaving test that would strip a replacement owner's config under a cleanup-then-unconditional-release implementation.

- [ ] **Step 6: Add unnumbered lifecycle integration around test 46r.**

Assert old owner retains the same lease token but cannot mint; new owner can mint and sees rewritten commit identity; release removes the helper. This proves the token remains attempt binding rather than owner identity.

- [ ] **Step 7: Mutation-test lifecycle integration.**

Kill: old App brief wording, head recomposition, handoff leaves old identity, release clears DB before config, one release caller bypasses cleanup, replacement config stripped after race, MCP drops `head_ref`, and `GH_TOKEN` reintroduced for convenience.

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
- Query and manual reset of `(github_auth_mode, github_app_installation_id)` to `(unknown, NULL)`.
- Ambient-first rollout, one sandbox App scope, push/PR verification, then additional scopes.
- Expected `app_not_installed`, `queued_auth_mode_unresolved`, `pane_unresolved`, and stale-helper `501` diagnostics.
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
cd backend
venv/bin/python -m compileall -q app mcp_shim
cd ../frontend
npm run typecheck
```

`frontend/package.json` currently has no `typecheck` script. Use `npx tsc -b` (the type phase of `npm run build`) and record that substitution; do not run the Vite build merely to validate a backend-only PR.

- [ ] **Step 2: Run focused security/lifecycle suites.**

```bash
cd ../backend
venv/bin/pytest \
  tests/agent_teams/test_github_app_auth_service.py \
  tests/agent_teams/test_github_client.py \
  tests/agent_teams/test_git_credential_helper.py \
  tests/agent_teams/test_github_workspace_service.py \
  tests/agent_teams/test_github_workspace_api.py \
  tests/agent_teams/test_github_dispatch_service.py \
  tests/agent_teams/test_github_verification_service.py \
  tests/agent_teams/test_dispatch_state_namespaces.py \
  tests/agent_mail/test_peer_process.py \
  tests/agent_mail/test_dispatch_status_tool.py \
  tests/agent_mail/test_mcp_shim.py \
  tests/test_sqlite_compat_migrations.py \
  -q -p no:warnings
```

- [ ] **Step 3: Run scoped and full suites.**

```bash
venv/bin/pytest tests/agent_teams/ tests/agent_mail/ -q -p no:warnings
venv/bin/pytest tests/ -q -p no:warnings
```

The known #312 failure may remain. Any other failure is PR2 work or a newly discovered unrelated failure; diagnose and report before changing unrelated code.

- [ ] **Step 4: Re-run every named mutant.**

Use temporary copies or exact reversible edits. Do not leave mutants in Git history. Produce a table: mutant, test command, expected failing assertion, observed failure. Review-only rows (per-item versus global lock, secret comparison timing) must be labeled honestly rather than credited to a test.

- [ ] **Step 5: Audit secrets and forbidden state mechanically.**

```bash
cd ..
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

- [ ] Every §5.8 test id is owned by exactly one task or explicitly preserved from merged PR1.
- [ ] Every §8 PR2 criterion has at least one implementation path and one test/review artifact.
- [ ] Lookup `404` and mint `404` remain separate behaviors.
- [ ] App/ambient/unknown mode behavior is persisted per scope, not inferred from a global setting at report time.
- [ ] Primary workspaces are excluded before lease mutation.
- [ ] Credentials require repo, acquisition, and kernel-derived current owner.
- [ ] `pr_ready` records only GitHub-returned numbers and uses exact persisted head equality.
- [ ] List and single PR payloads call the same classifier using `(state, merged_at)`.
- [ ] Closed-unmerged PRs escalate before mail, checks, draft promotion, or merge.
- [ ] Human-merge reservation notes survive retryable classification failures.
- [ ] Handoff changes identity but not branch or lease token.
- [ ] Release removes helper and identity before reporting success.

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
- [ ] The helper owner is rechecked after token mint before a credential is returned.

### 4. Handoff after implementation

Report:

- Branch and commit list.
- Scoped and full test results, including the exact #312 status.
- Typecheck/compile results.
- Mutation table with honest review-only rows.
- Confirmation that no public GitHub write, real App action, live DB edit, or agent dispatch occurred.
- Confirmation that the branch is pushed or unpushed according to the user's latest instruction, and that no PR was merged automatically.
