# Repository transfer runbook: Claude Deck → Synth City

**Status:** planning document for issue #790. This runbook describes a future
cutover. Writing or merging it does **not** authorize any transfer, rename,
deployment, DNS change, or code change. The transfer itself is a people-only
step on cutover day, after the gates in §3 are met.

**Parent plan:** `README.md` in this folder (Director-approved, 2026-11-06).
**Companion plans:** inventory (#788), compatibility (#789), release and
announcement (#791), website and docs (#792, merged).

## 1. What moves, and to where

| Current repository | After the transfer | Source of the decision |
|---|---|---|
| `adrirubio/claude-deck` | `albiexai/synth-city` | `README.md` decisions table in this folder |
| `adrirubio/claude-deck-website` | `albiexai/synth-city-website` | same |

Both repositories are **transferred** to the `albiexai` organisation and
renamed during the transfer. They are never recreated empty: a transfer keeps
the history, issues, stars and redirects that a new repository would lose
(§5). The public domain moves separately: `claudedeck.org` will redirect
every path to `albiex.org` (campaign `README.md:30` in this folder, and
`website-and-docs.md` in this folder). The domain switch is **not** part of
this runbook except where the website deploy depends on the repository (§6.2, §10 phase D).

Plain words for non-specialists: a *transfer* hands the existing repository —
code, issues, stars, old releases — to the new organisation in one move,
like changing the owner of a house instead of demolishing and rebuilding it.
GitHub then forwards repository web, git and API addresses from the old
location to the new one, with the exceptions listed in §5 (GitHub Pages
sites and actions hosted by the renamed repository are not redirected).

## 2. Evidence: pinned sources, live observations, and GitHub guarantees

This document uses three different kinds of fact. They must never be mixed:

| Kind | Where it applies | Meaning |
|---|---|---|
| **Pinned source fact** | All file-and-line citations | True of the cited file at the pinned commit below, forever |
| **Live API observation** | §6 settings, counts, branches, releases — each tagged "observed 2026-11-06" with the exact API field | True when observed; **not** fixed by a commit SHA, and expected to drift before cutover |
| **GitHub documented behaviour** | §5 | What GitHub's official documentation stated on 2026-11-06 (Appendix B); a documented expectation, not a tested promise about this transfer |

| Pinned source | Commit |
|---|---|
| Product repo `adrirubio/claude-deck`, branch `master` | `5e0d5d75d9091a9a6381c5540925cbef5f917e20` (merge of PR #793, 2026-11-06) |
| Website repo `adrirubio/claude-deck-website`, branch `master` | `0c35f391759633c774b7cc4ace5c52b96dd53d12` (2026-10-09) |
| GitHub behaviour claims | Official GitHub Docs, fetched 2026-11-06 (§5, Appendix B) |

File-and-line citations without a repository prefix refer to the product
repository at the product pin. Website citations are prefixed `website:` and
refer to the website pin. If either repository moves before cutover day,
re-run the pinned searches and the live observations separately (Appendix
A) and update each layer on its own — a new commit never "updates" a live
observation, and a live setting is never evidence about source content.

## 3. Gates that must be green before cutover day

None of these is satisfied by this document. Each needs a named human owner.

1. **Organisation ready.** `albiexai` exists, has Juan and Adrian as owners,
   and Adrian can create repositories in it (Director phase 0, `README.md`
   in this folder). GitHub requires create-repository permission in the
   target organisation before a transfer can start (§5). Because our move
   combines transfer **and** rename in one step, the acting operator must
   additionally be an **owner of the destination organisation**: GitHub's
   renaming documentation requires organisation-owner (or repository-admin)
   rights for the rename, so admin-plus-create on the source alone is not
   sufficient for the combined operation (§5).
2. **Trademark search.** The campaign requires a trademark search for
   "Albiex" and "Synth City" **before launch** (campaign `README.md`,
   Director phase 0). This runbook does not strengthen that into a decided
   pre-transfer clearance gate. *Proposal for the Director (not yet
   decided):* require the search result — and clearance, if the Director
   wants clearance rather than a search — before the transfer, since the
   organisation and repository names become public at transfer time. Until
   the Director decides, treat this line as a proposal, not a green/red
   gate.
3. **Announcement published** on the old repository before the move (§8).
   The exact texts are drafted in the release and announcement plan (#791);
   this runbook only fixes *when* they go out.
4. **Rename plans reconciled.** The inventory (#788) and compatibility
   (#789) plans are merged, so the team transferring knows which old names
   inside the product are handled by the code rename and which are handled
   by GitHub redirects. The website plan (#792) is already merged.
5. **Freeze windows agreed (one per repository).** A named person declares
   a short freeze for each repository separately, from its pre-transfer
   snapshot (§7 step 3) until its own phase-A checks (§10.1) pass: no
   merges, no releases, and no Deck-dispatched work *except* the specific
   bounded verification actions listed in §10 for that repository's phase
   (read-only API comparisons, scratch-clone probes on disposable branches,
   and the explicitly named workflow validations). The freeze is a
   coordination rule, not a bypass: no freeze exception may waive Director
   approval, a factory pause or HOLD, ownership or lease gates,
   independent review, or the configured merge policy.
6. **No name collisions in `albiexai`.** The organisation must not already
   contain `synth-city`, `synth-city-website`, or a fork of either project
   in the same fork network. GitHub refuses a transfer when the target
   already has a repository with the same name or a fork in the same
   network (§5). Check on the day (§7 step 4).

## 4. What this runbook deliberately does not do

- It does not rename anything inside the product (that is #788/#789 and the
  later implementation team).
- It does not choose the release number or write the announcement texts
  (that is #791; the Director decides).
- It does not switch DNS or publish the new website (that is #792 plus the
  Director's separate go-live approval).
- It records nothing about secret *values*. Secret names only appear below
  because the runbook must say which ones to verify.

## 5. GitHub behaviour this runbook relies on (verified)

Each statement below was checked on 2026-11-06 against GitHub's official
documentation: [Transferring a
repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository)
and [Renaming a
repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).
"Verified" means the documentation says it today; it is not a promise that
our transfer was tested. Anything the documentation does not settle is
marked **check on the day** in §7 and §10.

1. **Preconditions (verified).** The person transferring needs admin access
   to the repository and permission to create repositories in the target
   organisation. The target must not already hold a repository with the
   same name or a fork in the same network. The name can be changed as
   part of the same transfer; the rename half additionally requires an
   organisation owner or a repository admin, so for this combined move
   the acting operator must be an owner of `albiexai` (§3 item 1).
2. **What travels (verified).** Issues, pull requests, wiki, stars and
   watchers move with the repository. Webhooks, services, secrets and
   deploy keys stay associated. Commit history and contributions are
   preserved. Forks stay connected to the transferred repository. The
   cited pages do **not** explicitly guarantee that Discussions or a
   pinned Discussion survive a transfer; keeping them visible is a
   campaign requirement verified on the day (§10), not a documented
   guarantee claimed here.
3. **Redirects (verified).** Web links to the old repository location
   redirect to the new one, and `git clone`, `git fetch` and `git push`
   against the old address keep working through the redirect (exceptions:
   items 7 and 8 below). GitHub still recommends updating any local clone
   remote that names the transferred repository with
   `git remote set-url <remote> NEW_URL` (§9 gives direct-clone and
   fork-clone forms).
4. **The one destructive mistake (verified).** Creating a new repository
   (or fork) at the old location `adrirubio/claude-deck` **permanently
   deletes the redirects**. This is why §9 step 4 forbids recreating
   either old repository, forever, including as a placeholder or a mirror.
5. **Assignees change on personal → organisation moves (verified).** Issue
   assignments to people who are members of the new organisation stay;
   all other assignees are cleared. Expect some issue tidy-up afterwards.
6. **Organisation defaults take over (verified).** Once transferred, the
   organisation's default repository permissions and membership privileges
   apply. The original owner is added as a collaborator; other
   collaborators remain.
7. **GitHub Pages is the exception (verified, not applicable today).**
   Repository links redirect, but Pages sites do not. Neither repository
   uses GitHub Pages today (`has_pages=false` for both, §6), and the public
   site is served by Cloudflare Pages instead (§6.2).
8. **Hosted actions are not redirected (verified, not applicable).** A
   workflow that *uses an action hosted in* a renamed repository breaks.
   Neither repository publishes a reusable action for others; our workflows
   only consume public actions (§6), so this does not bite us — but anyone
   who vendored our workflows as actions would need the new address.
9. **Name retirement (verified).** GitHub permanently retires the old
   `owner/name` pair when the transferred repository **contains an action
   listed on GitHub Marketplace**, or had more than 100 clones, or more
   than 100 GitHub Actions uses in the week before transfer; a retired
   pair cannot be reused at all. Creating a repository with a retired
   pair is refused by GitHub. Neither repository's tracked tree at the
   pins publishes a Marketplace action (no action manifest is offered for
   others to consume in either tree); whether the clone/Actions-use
   thresholds are crossed is a live check-on-the-day item. Either way the
   §9 step 4 rule (never recreate) applies, and retirement would further
   constrain any transfer-back under the identical name (§11).

## 6. Current state (what the transfer must preserve)

Two layers, as defined in §2: pinned source facts carry file-and-line
citations; everything else in this section is a **live API observation
made on 2026-11-06**, labelled with the exact API field or endpoint, and
will drift before cutover. Anything an admin-only API refused to show is
marked **check on the day** (unreadable), never silently treated as absent.

### 6.1 Product repository `adrirubio/claude-deck`

Live observations (2026-11-06, `GET /repos/adrirubio/claude-deck` unless
named otherwise):

- `visibility=public`, `default_branch=master`, `license.spdx_id=MIT`,
  `archived=false`, `has_discussions=true`, `has_issues=true`,
  `has_projects=true`, `has_pages=false`, `has_wiki=true`.
- `stargazers_count=32`, `forks_count=8`, and `open_issues_count=73` —
  note that GitHub's `open_issues_count` **includes open pull requests**,
  so 73 is not an issues-only count. Fork owners (forks endpoint):
  `bclenneybev`, `hassanayoub1985`, `MinTALI`, `feelpass`, `yosiwizman`,
  `RubenAlonso-code`, `iflow-mcp/adrirubio-claude-deck`, and
  **`juanrubio/claude-deck`** (§9 covers what changes for them).
- Wiki: `has_wiki=true`, but the observed
  `git ls-remote https://github.com/adrirubio/claude-deck.wiki.git` lookup
  failed with "Repository not found" on 2026-11-06. That lookup failure is
  an observation, **not proof that no wiki content can exist** (access or
  name differences could produce the same result); access and content must
  be re-checked per repository on the day before anyone concludes there
  is nothing to preserve.
- **Tags are not Releases.** Observed tag refs (10):
  `v1.0.0`, `v1.1.0`, `v1.2.0`, `v1.3.0`, `v1.3.1`, `v2.0.0`, `v2.0.1`,
  `v3.0.0`, `v3.1.0`, and `archive/release-v3.0.0`. GitHub Releases and
  their downloadable assets are a separate API inventory and must be
  compared independently before/after (§7, §10, Appendix A) — the tag list
  alone proves nothing about release objects. The release workflow refuses
  to reuse an existing tag at a different commit
  (`.github/workflows/release.yml:66`), which is why the release-number
  question belongs to #791, not here.
- Collaborators (collaborators endpoint): `adrirubio` and `juanrubio`.
- Actions secrets present (secret **names** only, actions/secrets
  endpoint): `CLAUDE_CODE_OAUTH_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
  `CLOUDFLARE_API_TOKEN`. Actions **variables** (actions/variables
  endpoint): none returned — record as "observed empty 2026-11-06", and
  compare again after transfer (§10), because #790 explicitly requires a
  variables post-check. **Environments** (environments endpoint): none
  returned, likewise to be re-compared per repository (§10).
- **Actions permission policy:** the repository Actions permissions
  endpoint refused this token (HTTP 403). That is *unreadable*, not
  absent: the effective repository policy and, after the move, the
  destination organisation's Actions policy must both be captured with an
  admin token in the §7 step 3 snapshot and compared in §10.
- Rulesets: the API returns an empty list. Classic branch protection on
  `master`: the API returns 404 to this token — that can mean "none" or
  "not visible without admin", so it is **check on the day** with an admin
  account, not assumed absent.
- Deploy keys and webhooks: not readable with this token
  (`admin:repo_hook` scope required for hooks; keys returned 404).
  **Check on the day** before the transfer and again after (§10).
- Workflows (`.github/workflows/`, pinned source): `backend-tests.yml`,
  `claude.yml`, `codeql.yml`, `e2e.yml`, `factory-checks.yml`,
  `product-ci.yml`, `release.yml`. A pin-addressed `git grep` (Appendix A)
  finds **no** hardcoded `adrirubio/claude-deck`, `github.repository`, or
  `claudedeck.org` inside `.github/workflows/`. That supports only the
  narrow conclusion that no workflow *source* edit is demanded by the
  owner string; it does **not** guarantee the workflows will succeed
  after the move (secrets, permissions, policies and runners all still
  apply, §10). The two secret-*named* consumers in workflow source are
  the Claude Code workflow (`.github/workflows/claude.yml:37`,
  `secrets.CLAUDE_CODE_OAUTH_TOKEN`, action
  `anthropics/claude-code-action@v1` at
  `.github/workflows/claude.yml:35`) and the release workflow's built-in
  token (`.github/workflows/release.yml:151`, `secrets.GITHUB_TOKEN`).
  `factory-checks.yml` is **pull-request-triggered**, not manually
  dispatched (`.github/workflows/factory-checks.yml:3`).
- The release workflow creates the GitHub Release in whichever repository
  it runs in (`softprops/action-gh-release`,
  `.github/workflows/release.yml:138`, tag at `:140`) and names artifacts
  `claude-deck-frontend-v<version>` (`:102`, `:147`). Artifact *names* are
  a product-rename item (#788/#789), not a transfer blocker. No success
  after the move is inferred from the missing owner string; §10 validates
  the workflow explicitly.
- CodeQL triggers on pushes and pull requests to `master` and
  `release/v3.1` and on a weekly schedule
  (`.github/workflows/codeql.yml:4`), and its pull-request trigger
  **ignores** `docs/**` and `*.md` changes (`:8`), so a docs-only PR
  cannot produce a fresh scan. A transfer does not edit workflow files;
  whether the job can still run and upload `security-events` under the
  destination organisation is validated as in §10 (separately authorized
  non-docs trigger or deferred gate, never assumed).
- Dependabot is configured for npm, pip and github-actions
  (`.github/dependabot.yml:1`), and many `dependabot/*` and `deck/*`
  remote branches exist. Nothing moves branches except the transfer
  itself; stale Deck dispatch branches are housekeeping for another day.
- Hardcoded old-address links inside the tracked tree: 111 lines in 38
  files mention `adrirubio/claude-deck` (for example clone instructions at
  `README.md:168` and `DOCUMENTATION_PUBLISHING.md:41`, issue links at
  `CONTRIBUTING.md:38`, changelog compare links at `CHANGELOG.md:224`).
  GitHub redirects keep these working after the move (§5 item 3); rewriting
  them is inventory work (#788), not a cutover-day edit.

### 6.2 Website repository `adrirubio/claude-deck-website`

Live observations (2026-11-06, `GET /repos/adrirubio/claude-deck-website`):
`visibility=public`, `default_branch=master`, `has_issues=true`,
`has_discussions=false`, `has_pages=false`, `has_wiki=true`,
`stargazers_count=1`, `forks_count=1`. These were observed for the website
repository itself; no website setting in this document is inferred from a
product observation, and §10/Appendix A capture both repositories
independently.

Pinned source facts (website pin `0c35f39…`):

- Deploy is GitHub Actions → Cloudflare Pages. The workflow triggers on
  every push to `master` (`website:.github/workflows/deploy.yml:3`),
  checks out the pushed revision (`:14`), and runs
  `cloudflare/wrangler-action@v3` (`:17`) with secrets
  `CLOUDFLARE_API_TOKEN` (`:19`) and `CLOUDFLARE_ACCOUNT_ID` (`:20`),
  executing `pages deploy . --project-name=claude-deck-website` (`:21`),
  with the same two secrets repeated as environment (`:23`). Both secret
  names were present in the live actions/secrets observation. Because a
  `master` push **is** the production deployment, the §3 item 5 freeze
  covers this repository, and post-transfer validation must never use an
  unplanned `master` push as a "smoke test" (§10 phase D).
- `website:.github/workflows/check-pages.yml` triggers on pull requests
  to `master` and `release/v3.0.0` (`:3`), is read-only
  (`contents: read`, `:7`), checks out (`:14`), and runs an inline Python
  checker that parses `index.html` and fails on missing local
  `href`/`src` targets (`:16`). It uses no secrets and no owner strings.
- Observed branches include `release/v3.0.0`, `preview/website-v2` and
  Deck dispatch branches (live observation, branches endpoint). The
  Cloudflare *project name* `claude-deck-website` (deploy command,
  `website:.github/workflows/deploy.yml:21`) is a Cloudflare-side
  identifier, not a GitHub name; transferring the GitHub repository does
  not rename the Cloudflare project. Whether production moves to a
  `synth-city-website` Pages project is a Director choice recorded with
  #792; §11.2 records what this runbook must capture either way. No push
  may deploy to an unconfirmed project: the project actually served,
  its secrets' presence in the transferred repository, and the deploy
  result are verified in §10 phase D under separate authorization.

### 6.3 Deck itself (this factory) points at the old names — including its GitHub App

Deck is not a bystander: it stores a GitHub scope identity per team and
can authenticate as its own GitHub App. The pinned source facts the
migration procedure (§7 steps 6–8, §10 phase C) is built on:

- `TeamGithubScope` stores the repository identity
  (`repo_owner`/`repo_name`/`repo_path`,
  `backend/app/models/database.py:243`), the authentication mode
  (`github_auth_mode`, `:261`) and the resolved App installation
  (`github_app_installation_id`, `:262`).
- In App mode, Deck resolves the installation for a given `owner/repo`
  from GitHub (`resolve_installation`,
  `backend/app/services/github_app_auth_service.py:162`) and mints
  repository-scoped tokens from that installation
  (`mint_repository_token`, `:203`). An installation granted on
  `adrirubio` therefore does not, by itself, prove any grant on
  `albiexai`; the destination installation must be granted and resolved
  for the new owner/name when a scope uses App mode.
- Scope identity changes are guarded, not free-text edits: the update
  path computes an identity change from owner/name/path/base-ref
  (`backend/app/api/v1/agent_teams.py:2522`), treats an auth-mode change
  and an effective installation replacement as authority changes
  (`:2531`, `:2558`), and refuses with `scope_identity_in_use` (`:2551`),
  `scope_auth_in_use` (`:2553`) or `scope_workspace_authority_in_use`
  (`:2563`) while the scope is still in use.
- "In use" is wider than "a dispatch is running":
  `_scope_identity_in_use` (`:634`) blocks on any leased workspace
  (`:635`) and on work items in `pending`, `dispatched`, `verifying`,
  `ready_for_review`, `awaiting_human_review`, `escalated` or `failed`
  states (`:651`); `_scope_residual_workspace_authority` (`:684`)
  additionally blocks on residual lease fields or an unreleased lease
  (`:691`). Merely pausing *new* dispatches therefore cannot make a scope
  editable — review, failed and escalated work and leftover lease
  authority must be reconciled through the existing authorized
  procedures first.
- The Claude Code workflow (`.github/workflows/claude.yml:35`) is a
  *different* consumer: a workflow using a repository OAuth secret. It is
  not Deck's GitHub App, and an `@claude` comment exercising it proves
  nothing about Deck App access. The two are inventoried and verified
  separately (§7, §10).

Runtime scope records (which scopes exist, their auth modes, and
installation IDs) live in the factory database, not in this checkout, and
remain **unobserved day-of facts**: they are inventoried in §7 step 6 with
Deck admin access and must never be guessed from source. Under no
circumstances does this runbook authorize direct database rewriting,
forced lease release, or bypassing Deck's approval, review, ownership or
lease gates to make a scope editable.

## 7. Before cutover day (checklist, in order)

Owner for every line: a named human. Tick nothing on trust — record the
command output or settings screenshot next to each item.

1. Confirm the §3 gates, especially destination-organisation ownership
   for the acting operator (§3 item 1), the Director's position on the
   proposed pre-transfer trademark point (§3 item 2), and each
   repository's freeze window with a start and end time (§3 item 5).
2. Publish the pre-transfer announcement on the **old** product
   repository (§8). Wait long enough for watchers to see it — the exact
   lead time is a Director decision recorded in #791.
3. Take a pre-transfer snapshot of **each repository separately** with the
   parameterized Appendix A commands (run them once per repository; never
   infer one repository's settings from the other): repository fields,
   subscribers/watchers, stargazers, forks, branches, tags **and**
   Releases with assets as separate lists, issues/pull-requests counts,
   collaborators, secret *names*, **variables**, **environments**,
   rulesets and branch protection, deploy keys, webhooks, effective
   repository Actions permission policy and the applicable organisation
   Actions policy, and GitHub App installations (Settings →
   Integrations). Distinguish "absent (empty list observed)" from
   "unreadable (endpoint refused)" for every line. Keep the full snapshot
   as **protected operator evidence** outside the repositories; publish
   afterwards only safe before/after comparisons (names and counts, never
   secret values or webhook URLs). The snapshot is the yardstick for §10.
4. In `albiexai`, confirm the names `synth-city` and `synth-city-website`
   are free and no same-network fork already sits there (§3 item 6).
5. Confirm both future owners can sign in, pass 2FA, and see the
   organisation. The person performing the combined transfer-and-rename
   must be an **owner of `albiexai`** and have admin on the source
   repository plus create-repository permission in the destination
   (§5 item 1); confirm all three on the actual operator account, not on
   a bystander account.
6. **Inventory GitHub App consumers — there are two distinct kinds.**
   (a) GitHub App installations targeting either repository
   (Settings → Integrations → GitHub Apps). (b) **Deck's own GitHub App
   path:** with Deck admin access, list every `TeamGithubScope` whose
   stored owner/name is either old repository
   (`backend/app/models/database.py:243`), recording each scope's
   `github_auth_mode` (`:261`) and whether an installation is recorded
   (`:262`). In App mode Deck resolves the installation per owner/repo
   (`backend/app/services/github_app_auth_service.py:162`) and mints
   repository-scoped tokens from it (`:203`), so plan explicitly for a
   destination grant + re-resolution under `albiexai/…` (§10 phase C).
   The Claude Code workflow (`.github/workflows/claude.yml:35`, secret at
   `:37`) is a separate workflow consumer, kept inventoried under
   workflow secrets — it is not evidence about any App installation.
   Runtime scope/auth/installation values are day-of facts (§6.3), never
   filled in from source.
7. **Record the Cloudflare state and the Director's project choice**
   (merged `website-and-docs.md` assigns this record to #790). Before any
   transfer, capture as protected/day-of records: the Pages project
   currently serving production and the deploy command that targets it
   (`website:.github/workflows/deploy.yml:21`), the **verified
   known-good deployment** (its deployment identifier/URL and the commit
   it was built from — the thing a rollback would return to), the custom
   domains attached and their DNS targets, and any redirect rules already
   live. Record the Director's still-open choice: keep serving from the
   existing `claude-deck-website` project through cutover, or pre-create
   a `synth-city-website` project and switch at the separately authorized
   go-live. Do not alter website files, push, or deploy as part of this
   recording step; a `master` push deploys production (§6.2).
8. **Quiesce Deck scopes properly — pausing new dispatches is not
   enough.** For every scope inventoried in step 6(b): stop admitting new
   work, then reconcile all active, review and recovery work through the
   existing authorized Deck procedures until the scope is genuinely
   quiescent. Quiescence means what the guards actually check: no leased
   workspace and no work item in `pending`/`dispatched`/`verifying`/
   `ready_for_review`/`awaiting_human_review`/`escalated`/`failed`
   (`_scope_identity_in_use`, `backend/app/api/v1/agent_teams.py:634`,
   states at `:651`), and no residual workspace lease authority
   (`_scope_residual_workspace_authority`, `:684`). Work that cannot be
   finished or legitimately closed before the freeze **delays the
   cutover**; it is never force-released, escalated away, or
   database-edited to clear the guard. Only once quiescence is verified
   will the supported scope update path accept the identity/auth change
   instead of refusing with `scope_identity_in_use`,
   `scope_auth_in_use` or `scope_workspace_authority_in_use`
   (`:2551`, `:2553`, `:2563`). Warn all Deck operators of the per-scope
   freeze windows; a dispatch mid-transfer could otherwise clone through
   a redirect while its scope still names the old owner.
9. Prepare (but do not yet make) the remote-URL updates for known clones:
   every long-lived checkout, the website working copies, and the
   documentation-publishing flow that builds docs from the product repo
   into the website repo (`DOCUMENTATION_PUBLISHING.md:3`,
   `:41` and `:119` name both old addresses).

## 8. The announcement that goes out *before* the transfer

The campaign decision is fixed: announce before moving, in public
(`README.md` in this folder; texts drafted in #791). The runbook fixes the
mechanics and order only:

1. Post the pinned Discussion on `adrirubio/claude-deck` (Discussions are
   on, §6.1) saying the project is becoming Synth City, the date of the
   move, the new address `albiexai/synth-city`, and that old links, clones
   and installs keep working (redirects §5 item 3; product fallbacks are #789).
2. Add the README banner linking to that Discussion. Banner copy comes
   from #791; it is a normal reviewed PR into `master` **before** the
   freeze, not an edit during cutover.
3. Only after both are live on the old repository does the freeze start.
   The README banner is file content and travels with the git history;
   preservation of Discussions and of the pin itself is **not** a
   documented GitHub guarantee (§5 item 2), so it is a campaign
   requirement that §10 phase B verifies on the new home (Discussion
   present, still pinned, banner link resolving). The banner is updated
   to past tense afterwards by a normal reviewed PR, outside the freeze.

## 9. Cutover day: the transfers, in dependency order

The order below is executable without a dependency cycle. Four check
phases (§10) gate four different things, and **publication is never one of
the transfer gates**:

- **Phase A (per repository, immediate):** proves that one transfer
  landed intact. Passing phase A for the website repository — and only
  phase A — permits the second (product) transfer.
- **Phase B (product repository):** the product-only checks. Passing
  phase A + B releases the product repository's freeze for ordinary work.
- **Phase C (cross-repository / Deck):** scope migration and factory
  readback. Real Deck dispatches stay paused until phase C passes.
- **Phase D (publication, separately authorized):** the website go-live
  (one reviewed cutover merge to the website `master`, DNS and redirects).
  This needs the Director's separate approval and is only reachable after
  **both** transfers and their checks, per the merged website plan
  (`website-and-docs.md` §9: no merge of the new pages into website
  `master` before transfer verification, because that merge is the
  deployment). Phase D rows are recorded as *skipped/not-applicable
  (later launch gate)* during the transfer day, never as passed.

Sequence, in order:

1. **Website freeze on.** Confirm no Actions runs in progress
   (`gh run list`) and the §7 step 3 website snapshot is current.
2. **Website transfer:** Settings → General → Danger Zone → Transfer
   ownership to `albiexai`, renamed to `synth-city-website` in the same
   step, performed by an `albiexai` owner (§3 item 1).
3. **§10 phase A for the website repository.** Any failure stops the day
   (§11); the product transfer does not start.
4. **Product freeze on** (including Deck scope quiescence verified as in
   §7 step 8). Confirm no Actions runs in progress and the §7 step 3 product
   snapshot is current.
5. **Product transfer:** same flow, renamed to `synth-city`.
6. **§10 phase A, then phase B, for the product repository.** Passing
   both lifts the product freeze for ordinary (non-Deck-dispatch) work.
7. **§10 phase C:** Deck scope migration and bounded smoke validations.
   Passing phase C unpauses real Deck dispatches.
8. **Stop.** Publication (phase D) happens only under its own Director
   approval on its own schedule; the old site keeps serving meanwhile.

The never-recreate rule binds at steps 2 and 5 and forever after: do not
create a repository **or fork** at either old address, including a fork
*into* `adrirubio` from the new home — GitHub permanently deletes the
redirects in that case (§5 item 4). Confirm each transfer dialog exactly
(type the repository name when asked).

**Updating clone remotes — inspect first, update only what matches.**
Redirects keep old URLs working, so this is hygiene, not an emergency.
First look at what each clone actually points at (`git remote -v`, fetch
and push URLs), then update **only** remotes whose URL names a transferred
repository:

- *Direct clone of the product* (its `origin` is the transferred repo):
  `git remote set-url origin https://github.com/albiexai/synth-city.git`
- *Direct clone of the website:*
  `git remote set-url origin https://github.com/albiexai/synth-city-website.git`
- *Fork clone* (for example Juan's): **keep `origin` pointing at the
  fork** (`juanrubio/claude-deck` stays `origin`). Update only the remote
  that names the transferred upstream — conventionally `upstream`:
  `git remote set-url upstream https://github.com/albiexai/synth-city.git`
  Use whatever that remote is actually called in that clone; if a fork
  clone has no upstream remote, nothing needs changing.
- If fetch and push URLs differ (`git remote -v` shows both), update each
  matching URL (`--push` form where a separate push URL exists).

**What changes for forks (tell people this):** forks stay connected to
the transferred repository (§5 item 2); `juanrubio/claude-deck` remains a
fork of what is now `albiexai/synth-city`. Fork owners never need to
re-fork and must not delete-and-refork as "cleanup" (a fork created at
the *old* location is the destructive case above). Open pull requests
from forks are re-checked in phase B (head/base still resolve). CI
systems and bookmarks embedding the old web address ride the redirects,
but anything comparing the repository *string* (Deck scopes, §6.3) needs
the supported update path, because redirects do not rewrite
configuration.

## 10. Verification, split by phase (each phase gates something different)

Every row compares against the per-repository §7 step 3 snapshot and ends
in exactly one recorded outcome: **passed**, **failed**, or
**skipped/not-applicable** (with the reason — e.g. "Discussions off on
this repository", "later launch gate"). Skipped is never recorded as
passed. "Basis" distinguishes documented GitHub behaviour (§5) from
**check on the day** — things this document deliberately does not claim.
A written exception accepted by a named human can release a *freeze*; it
can never waive Director approval, a HOLD or factory pause, ownership or
lease gates, independent review, or the configured merge policy.

### 10.1 Phase A — immediate post-transfer checks (run for each repository right after its transfer)

Gates: website phase A passing **permits the product transfer**; product
phase A passing is required before phase B. Nothing in phase A involves
publication.

| # | Check (this repository only) | Basis | How |
|---|---|---|---|
| A1 | Old web URL redirects to the new home; this repo's old issue/PR URLs redirect | Documented §5 item 3 | Private browser window on old links of this repo |
| A2 | `git ls-remote` and a scratch-clone fetch via the **old** URL answer; no push probe against any protected branch | Documented §5 item 3 | Disposable clone outside long-lived checkouts |
| A3 | `stargazers_count` and **subscribers/watchers** count match the snapshot (watchers come from the subscribers endpoint — the REST `watchers_count` field is a stargazers alias and must not be used as the watcher figure) | Documented §5 item 2 | Appendix A per-repo commands |
| A4 | Fork list matches snapshot and each fork still names this repo as upstream (website: whatever its own snapshot says; the 8-fork list is product-only and is phase B) | Documented §5 item 2 | Forks endpoint, paginated |
| A5 | Branch list and default branch match the snapshot | Git data preserved §5 item 2; verify, don't assume | Branches endpoint + `default_branch` |
| A6 | Actions **secret names**, **variable names/values comparison**, and **environments** match the snapshot for this repository — recording absent (observed empty) vs unreadable (refused) separately | Secrets documented §5 item 2; variables/environments **check on the day** | Settings or the three Actions endpoints (Appendix A) |
| A7 | Rulesets and classic branch protection on the default branch match whatever the admin snapshot found (including "none observed") | **Check on the day** (unreadable at planning time, §6.1) | Settings → Branches/Rules vs snapshot |
| A8 | Deploy keys and webhooks match the admin snapshot by identity/target. **No replay here:** replaying a delivery re-fires the consumer and is a real action, validated in phase C only against a named, expected effect | Associated per §5 item 2; inventory **check on the day** | Settings → Deploy keys/Webhooks, compare only |
| A9 | Collaborators and organisation-default permissions: intended people hold intended roles, nothing silently widened/narrowed | Documented §5 item 6 | Settings → Collaborators and teams vs snapshot |
| A10 | Nothing exists at the old address: it redirects, does not 404, and is not a fresh repo/fork | Documented §5 item 4 | Open the old URL |

### 10.2 Phase B — product-repository checks (after product phase A)

Gates: lifting the product freeze for ordinary (non-Deck-dispatch) work.

| # | Check | Basis | How |
|---|---|---|---|
| B1 | All snapshot forks (8 observed 2026-11-06) still upstream-connected, incl. `juanrubio/claude-deck`; one open fork PR's head/base resolve | Documented §5 item 2 | Forks endpoint + open that PR |
| B2 | **Tags** complete vs snapshot — and, separately, **Releases and assets** complete (list compared; one pre-transfer asset downloads) | Git data §5 item 2; release objects compared independently, never inferred from tags | `git ls-remote --tags` at the pin + releases endpoint (Appendix A) |
| B3 | Issues and PRs compared with correct counting (snapshot's `open_issues_count` includes PRs; compare issues-only and PRs separately); cleared assignees (non-`albiexai` members) listed for tidy-up | Documented §5 items 2, 5 | Issues/PR search vs snapshot |
| B4 | Discussions present on the new home and the §8 announcement still pinned; banner link resolves | **Campaign requirement, check on the day** — not a documented guarantee (§5 item 2) | Open Discussions + README |
| B5 | Wiki access/content re-checked for this repository (the planning-time lookup failure was an observation, not proof of absence) | **Check on the day** | Wiki tab + wiki git remote probe |
| B6 | Effective repository Actions permission policy and applicable organisation Actions policy compared with the admin snapshot (absent vs unreadable recorded) | **Check on the day** (403 at planning time, §6.1) | Admin token, Actions permissions endpoints |
| B7 | Product workflow *source* unchanged by the move and one bounded validation run observed: a pull request opened for an already-planned change exercises the PR-triggered `factory-checks` (`.github/workflows/factory-checks.yml:3` — PR-triggered, not manually dispatchable). If no legitimate PR exists, record this as *deferred to first post-freeze PR*, not passed. No empty "no-op push" is used as a test | Runner behaviour **check on the day** | That PR's hosted checks |
| B8 | Release workflow validated by dry run: `workflow_dispatch` with `dry_run=true` (`.github/workflows/release.yml:14`), supplying the required full 40-char commit and a version whose four version files agree, as the workflow itself enforces (`:6` inputs, `:56`–`:74` checks). **Precise expectation:** dry run still *uploads Actions artifacts* for review (`:126`); only tag creation and Release publication are skipped (conditional at `:136`) — it does not "publish nothing" | **Check on the day** | Actions → Release → Run workflow; confirm artifact present, no tag/Release created |
| B9 | CodeQL: either (a) a **separately authorized non-docs change** on a PR or push to `master`/`release/v3.1` produces a fresh completed analysis visible under Security → Code scanning, or (b) the row is recorded as a **deferred gate** with a named owner/date. A docs-only PR cannot satisfy this (`.github/workflows/codeql.yml:8` ignores `docs/**`, `*.md`), and waiting for the weekly schedule (`:10`) may exceed the freeze — deferred is honest, passed-by-assumption is not | **Check on the day** | Security tab shows the run's commit and date, or the deferred record exists |

### 10.3 Phase C — cross-repository and Deck checks (after phase B)

Gates: unpausing real Deck dispatches.

| # | Check | Basis | How |
|---|---|---|---|
| C1 | Deck scope migration completed through the **supported scope API/UI only** for every scope inventoried in §7 step 6(b): quiescence re-verified immediately before the edit (no leased workspace/work in the guard states, no residual lease authority — `backend/app/api/v1/agent_teams.py:634`, `:684`); in App mode the destination installation is granted on `albiexai` and resolved for the new owner/name (`backend/app/services/github_app_auth_service.py:162`) as part of the update; any `scope_identity_in_use` / `scope_auth_in_use` / `scope_workspace_authority_in_use` refusal (`:2551`, `:2553`, `:2563`) stops the phase — never worked around by force-release or database edits | **Check on the day** (runtime records) | Deck admin UI/API; refusal codes recorded verbatim if hit |
| C2 | Readback: re-read each updated scope through Deck and confirm owner/name/path/base-ref, auth mode and (App mode) installation now name the destination; policies, labels and limits unchanged from the §7 inventory unless separately decided | **Check on the day** | Scope readback screenshot/API response in operator evidence |
| C3 | Bounded factory smoke **after** C1–C2: exactly one pre-agreed, explicitly bounded action whose expected effect is written down in advance (for example one triage-only dispatch of a designated throwaway issue that must clone from `albiexai/synth-city`, report `triaging`, and stop). It is a real dispatch with real effects, not a no-op; scope it so its full effect list is acceptable. Only its exact expected outcome counts as passed | **Check on the day** | Deck operator runs it; observe the named outcome end-to-end |
| C4 | Third-party GitHub App installations from §7 step 6(a) are granted on `albiexai` where still wanted. Validation is per actual consumer with a bounded expected effect (for example, for the Claude Code workflow: one `@claude` comment on a designated test issue, expecting exactly one workflow run using the repository secret, `.github/workflows/claude.yml:15`, `:35`). A generic webhook "replay" is **not** a validation method (it re-delivers to live consumers); redelivery happens only for a named hook whose consumer's expected reaction is written down first | **Check on the day** (grants are per-owner) | Settings → Integrations + the one bounded trigger per consumer |
| C5 | Documentation-publishing flow rehearsed **without publishing**: in an isolated *disposable* copy of both checkouts (never the live sibling layout), with the publishing script's inputs first updated under their own approved change — today `scripts/deploy-docs.sh` still targets the old sibling directory (`:7`) and deletes/replaces that tree's `docs/` (`:19`), and the playbook names the old remotes (`DOCUMENTATION_PUBLISHING.md:41`). The local rehearsal stops after build + copy-into-the-disposable-copy + diff review; the script's printed commit/push steps and any real deploy are explicitly excluded | **Check on the day** | Disposable copies only; record the reviewed diff, discard the copies |

### 10.4 Phase D — publication checks (separately authorized, later launch gate)

Not part of transfer day. Each row stays *skipped (later launch gate)*
until the Director's separate go-live approval, and planning-time text
here grants no deployment authority:

| # | Check | Basis | How |
|---|---|---|---|
| D1 | The single reviewed cutover merge to website `master` (workflow + site source + generated docs together, per merged `website-and-docs.md` §9) deployed the **recorded** Pages project chosen in §7 step 7, and the live site serves the approved revision | **Check on the day** under separate Director approval | Actions run for that merge + open the live site; compare with the §7 step 7 known-good record |
| D2 | `albiex.org` serves the site and every-path `claudedeck.org` → `albiex.org` 301 redirects are live for representative paths | Campaign decision; **check on the day** | Spot-check `/`, one docs page, one asset on both domains |
| D3 | Rollback readiness for D1–D2 confirmed before the merge: known-good deployment (§11.2 record) identified and its restore path named | §11.2 | Record checked before the merge button is pressed |

## 11. Rollback notes — read before cutover

### 11.1 Repository-transfer failures

A transfer is **not fully reversible**, so the default response is "stop
and fix forward", in this order. Nothing below is an operator reflex:
every transfer-back is a fresh Director decision with its own short plan.

1. **Before any transfer:** cancelling is free. If a §3 gate or §7 item
   fails, nothing has moved; reschedule.
2. **Website moved, phase A fails:** stop; the product transfer does not
   start. Repair configuration in the new website home (secret presence,
   grants, protection) and re-run the failed phase A rows. A
   transfer-back is not the first tool: its effects are
   direction-specific in GitHub's documentation — a move back from an
   organisation to a personal account, for example, keeps only assignees
   that are the repository owner and drops read-only collaborators (§5
   items 5–6) — and the destination must again satisfy every transfer
   precondition, including the name-collision and possible
   name-retirement rules (§5 items 1, 9). Describe those limits in the
   fresh decision; do not assume a return trip restores the prior state.
3. **Product moved, phase A/B fails:** keep the product freeze on, repair
   the failed configuration items in the new home, and re-run exactly the
   failed rows. No repair speed is promised here; the freeze lasts as
   long as the failed rows take. Deck dispatches remain paused until
   phase C passes regardless of phase B progress.
4. **The unrecoverable error** is recreating a repository or fork at
   either old address: GitHub then permanently deletes the redirects
   (§5 item 4), and every old link, clone and bookmark in the wild breaks
   at once. If it happens: **stop and freeze. Do not delete the
   replacement** — it may already contain someone else's work, and
   deletion is neither documented to restore the redirects nor an
   authorized recovery step in this runbook. Instead: preserve the
   replacement and all evidence (who created it, when, what it contains),
   freeze further changes at both addresses, notify the Director and the
   Leader, contact GitHub Support with the timeline, and take only the
   recovery action that comes back as a **separately authorized
   decision**. Plan on the basis that recovery is **not promised**; the
   documentation establishes the loss, not a remedy.
5. **Name retirement (§5 item 9)** may make the old `owner/name`
   pair permanently unreusable (Marketplace-action, clone-volume or
   Actions-use conditions). That can also block a transfer-back under the
   identical name. Another reason any return move needs its own decision
   and plan rather than improvisation.

### 11.2 Website, Pages and redirect recovery (owned here, per merged #792)

The merged website plan (`website-and-docs.md`) assigns this runbook —
not #792 — the Pages project choice record, the verified known-good
deployment, and the infrastructure/redirect recovery steps with their
authorizers. This section supplies the planning content; executing any
step needs its named authorization. No website file is altered and
nothing is deployed by this document.

**Day-of records required before phase D (from §7 step 7):** serving
Pages project and deploy target; known-good deployment identifier/URL +
source commit; attached custom domains and DNS targets; live redirect
rules; the Director's project choice (keep `claude-deck-website` project
vs new `synth-city-website` project). Without these records, phase D does
not start.

**Recovery order if a phase D deployment is wrong** (each step stops for
its authorizer; layers recover independently — a content revert cannot
undo a project/domain change):

1. **Content layer — return to the known-good deployment.** Preferred:
   restore/redeploy the recorded known-good Cloudflare deployment
   (the mechanism named in the website build design). Alternative: a
   reviewed revert of the cutover merge on website `master` — valid only
   while the workflow and Pages project it deploys through are themselves
   unchanged and known-good, and requiring the same release-owner approval
   as a publication, because that push is itself a production deploy
   (`website:.github/workflows/deploy.yml:3`).
   *Authorizer: the named website release owner for that day.*
2. **Project layer — wrong project serving.** Point production back to
   the project recorded as serving before cutover (deploy-target/DNS
   change in Cloudflare), without touching repository content.
   *Authorizer: Director or the named Cloudflare account owner.*
3. **Domain/redirect layer.** If `albiex.org` attachment or the
   `claudedeck.org` every-path 301s misbehave: remove/fix the redirect
   rule first (old domain serves as before), then correct DNS targets.
   *Authorizer: Director or the named DNS owner.*
4. **Validate after any layer's recovery:** the live site serves the
   known-good revision, one docs path and one asset resolve on the
   serving domain, and (once re-enabled) a sample old-domain path 301s to
   the same path on the new domain. Record which deployment is now
   known-good before lifting the incident hold.

A website-layer problem is never, by itself, a reason to transfer a
repository back: the GitHub transfer does not move `claudedeck.org`
traffic, and §11.1 governs repository moves on their own merits.

## 12. Open questions for the Director

These are recorded, not decided, by this plan:

1. Cutover date, freeze lengths, and the announcement lead time in
   §7 step 2 (announcement texts and release number: #791).
2. Trademark: the campaign requires a search before launch. **Proposal**
   (undecided): require the search result, or full clearance, before the
   transfer itself (§3 item 2).
3. Cloudflare: keep the `claude-deck-website` Pages project through
   cutover, or serve production from a new `synth-city-website` project,
   switched at the separately authorized go-live (§7 step 7, §11.2).
4. Named people for cutover day: the acting operator (must be an
   `albiexai` owner, §3 item 1), the freeze owners, the §10 exception
   accepter (freeze exceptions only — §10 preamble), the website release
   owner, and the Cloudflare/DNS authorizers named in §11.2.
5. When (if ever) `adrirubio` takes other measures about the old name —
   noting §5 item 4: "protecting" the old name by recreating it would
   destroy the redirects (and, after an accidental recreation, this
   runbook authorizes no deletion either, §11.1 item 4); the safe
   protection is simply never to reuse it.

## Appendix A. Evidence: how §6 was read, and how to re-read it

### A.1 Live observations (run once per repository — never infer one from the other)

Read-only; first executed 2026-11-06. Set `REPO` for each repository in
turn (`adrirubio/claude-deck`, then `adrirubio/claude-deck-website`;
after each transfer, its new name). List endpoints paginate: always use
`--paginate` (or follow `per_page=100` pages to exhaustion) so counts are
complete, and record the observation time next to every result. Admin
rows need an admin token, for example
`gh auth refresh -h github.com -s admin:repo_hook` for hooks.

```bash
REPO=adrirubio/claude-deck        # then repeat with the website repo
gh api "repos/$REPO"              # fields cited in §6 (record field names)
gh api --paginate "repos/$REPO/subscribers"        # watchers (subscribers)
gh api --paginate "repos/$REPO/stargazers"         # stargazers (NOT watchers)
gh api --paginate "repos/$REPO/forks"
gh api --paginate "repos/$REPO/branches"
gh api --paginate "repos/$REPO/collaborators"
gh api --paginate "repos/$REPO/releases"           # Releases + asset names/sizes
gh api --paginate "repos/$REPO/actions/secrets"    # names only, never values
gh api --paginate "repos/$REPO/actions/variables"  # variables: name list for
                                  # publication; values only in protected evidence
gh api "repos/$REPO/environments"
gh api "repos/$REPO/actions/permissions"           # admin; plus the ORG policy:
gh api "orgs/<owner>/actions/permissions"          # admin, per owner
gh api "repos/$REPO/rulesets"
gh api "repos/$REPO/branches/<default>/protection" # admin
gh api "repos/$REPO/keys"                          # admin (deploy keys)
gh api --paginate "repos/$REPO/hooks"              # admin; URLs stay protected
gh api "repos/$REPO/installation"                  # App installation (Deck resolves
                                  # the same thing in github_app_auth_service.py:162)
git ls-remote --tags "https://github.com/$REPO.git"
git ls-remote "https://github.com/$REPO.wiki.git" HEAD   # observation only (§6.1)
```

Snapshot hygiene: the full output is **protected operator evidence**
(it can contain webhook targets and variable values). Publish only safe
comparisons afterwards: names, counts, and present/absent/unreadable per
line — for both repositories, side by side, never merged.

### A.2 Pinned source searches (addressed at the pins, reproducible later)

Run these with the commit spelled out, so anyone on a later checkout
reproduces this document's baselines exactly:

```bash
PIN=5e0d5d75d9091a9a6381c5540925cbef5f917e20
git grep -n 'adrirubio/claude-deck' "$PIN"        # 111 lines, 38 files at the pin
git grep -n -E 'secrets\.|vars\.' "$PIN" -- .github/workflows/
git grep -n -E 'adrirubio/claude-deck|github\.repository|claudedeck\.org' \
  "$PIN" -- .github/workflows/                   # no hits (owner-string claim, §6.1)
# website workflows were read at their own pin, e.g.:
# gh api "repos/adrirubio/claude-deck-website/contents/.github/workflows/deploy.yml?ref=0c35f391759633c774b7cc4ace5c52b96dd53d12"
```

### A.3 What was observed, and what was not

Observed 2026-11-06 (live layer): the §6 repository fields and counts,
fork lists, secret names for both repositories, **empty** product
variables list, **empty** product environments list, empty product
rulesets list, collaborators, tag refs, and the failed wiki lookup.
Observed (pinned layer): every file-and-line citation in §6–§7, including
the Deck scope model, identity guards and App auth service.
Explicitly **not** observed (token limits — recorded as unreadable, never
as absent): branch-protection settings (404), deploy keys (404),
webhooks (scope refused), repository Actions permission policy (403),
organisation Actions policy, the full GitHub App installation list, all
Deck runtime scope/auth/installation records, variables/environments of
the **website** repository, and the live Releases/assets inventories.
§7 step 3 re-takes all of these per repository with an admin token;
§10 phases A–C compare them. This Appendix distinguishing the three
layers is precisely how a later reader tells which §6 statement a future
checkout can re-verify from source and which must be re-observed live.

## Appendix B. Official sources

- GitHub Docs — *Transferring a repository*:
  https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository
  (prerequisites; what is transferred; redirects; the recreation warning;
  organisation defaults; assignee behaviour; name retirement).
- GitHub Docs — *Renaming a repository*:
  https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository
  (redirect scope; `git remote set-url` guidance; do-not-reuse-the-old-name
  warning; hosted-action exception).
- Parent and issue record: #787 (campaign), #790 (this runbook's brief),
  `README.md` and `website-and-docs.md` in this folder.

*Limits of this document, stated plainly: it is a source-reviewed plan. No
transfer was rehearsed against a throwaway repository (recommended before
cutover if the Director wants live evidence), no admin-only settings were
observed (Appendix A), and no phase of §10 has been executed yet. GitHub
documentation can change; re-fetch both pages on cutover week and diff the
claims in §5 before starting §9.*
