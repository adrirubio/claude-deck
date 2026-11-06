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
this runbook except where the website deploy depends on the repository (§6.2, §10 row 12).

Plain words for non-specialists: a *transfer* hands the existing repository —
code, issues, stars, old releases — to the new organisation in one move,
like changing the owner of a house instead of demolishing and rebuilding it.
GitHub then forwards every old address to the new one automatically.

## 2. Pinned sources for every fact in this document

All repository facts below were read at these exact commits. If either
repository moves before cutover day, re-run the checks in Appendix A and
update this table before following the runbook.

| Source | Pin |
|---|---|
| Product repo `adrirubio/claude-deck`, branch `master` | `5e0d5d75d9091a9a6381c5540925cbef5f917e20` (merge of PR #793, 2026-11-06) |
| Website repo `adrirubio/claude-deck-website`, branch `master` | `0c35f391759633c774b7cc4ace5c52b96dd53d12` (2026-10-09) |
| GitHub behaviour claims | Official GitHub Docs, fetched 2026-11-06 (§5, Appendix B) |

File-and-line citations without a repository prefix refer to the product
repository at the product pin. Website citations are prefixed `website:` and
refer to the website pin.

## 3. Gates that must be green before cutover day

None of these is satisfied by this document. Each needs a named human owner.

1. **Organisation ready.** `albiexai` exists, has Juan and Adrian as owners,
   and Adrian can create repositories in it (Director phase 0, `README.md`
   in this folder). GitHub requires create-repository permission in the
   target organisation before a transfer can start (§5).
2. **Trademark clearance.** The search for "Albiex" and "Synth City" is a
   Director open item. Do not transfer into a name that is not cleared.
3. **Announcement published** on the old repository before the move (§8).
   The exact texts are drafted in the release and announcement plan (#791);
   this runbook only fixes *when* they go out.
4. **Rename plans reconciled.** The inventory (#788) and compatibility
   (#789) plans are merged, so the team transferring knows which old names
   inside the product are handled by the code rename and which are handled
   by GitHub redirects. The website plan (#792) is already merged.
5. **Freeze window agreed.** A named person declares a short freeze: no
   merges, no releases, no Deck-dispatched work against either repository
   between the last check in §6 and the final check in §10.
6. **No name collisions in `albiexai`.** The organisation must not already
   contain `synth-city`, `synth-city-website`, or a fork of either project
   in the same fork network. GitHub refuses a transfer when the target
   already has a repository with the same name or a fork in the same
   network (§5). Check on the day (§6, step 4).

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
   part of the same transfer.
2. **What travels (verified).** Issues, pull requests, wiki, stars and
   watchers move with the repository. Webhooks, services, secrets and
   deploy keys stay associated. Commit history and contributions are
   preserved. Forks stay connected to the transferred repository.
3. **Redirects (verified).** All web links to the old location redirect to
   the new one, and `git clone`, `git fetch` and `git push` against the old
   address keep working through the redirect. GitHub still recommends
   updating local clones with `git remote set-url origin NEW_URL`.
4. **The one destructive mistake (verified).** Creating a new repository
   (or fork) at the old location `adrirubio/claude-deck` **permanently
   deletes the redirects**. This is why §6 forbids recreating either old
   repository, forever, including as a placeholder or a mirror.
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
9. **Name retirement (verified).** If a repository had more than 100 clones
   or more than 100 GitHub Actions uses in the week before transfer,
   GitHub permanently retires the old `owner/name` pair so it cannot be
   reused at all. Whether we cross that threshold is a check-on-the-day
   item; the §9 step 4 rule (never recreate) protects us either way.

## 6. Current state at the pins (what the transfer must preserve)

Read-only inventory taken 2026-11-06 with the commands in Appendix A.
Anything an admin-only API refused to show is marked **check on the day**
rather than guessed.

### 6.1 Product repository `adrirubio/claude-deck`

- Public, default branch `master`, MIT licence, not archived. Discussions
  **on**, issues on, projects on, GitHub Pages **off**.
- Stars **32**, forks **8**, open issues **73** at the pin. Forks:
  `bclenneybev`, `hassanayoub1985`, `MinTALI`, `feelpass`, `yosiwizman`,
  `RubenAlonso-code`, `iflow-mcp/adrirubio-claude-deck`, and
  **`juanrubio/claude-deck`** (§9 covers what changes for them).
- Wiki setting is on, but no wiki repository exists:
  `git ls-remote https://github.com/adrirubio/claude-deck.wiki.git` returns
  "Repository not found". There is no wiki content to lose; re-check on the
  day in case pages are added meanwhile.
- Tags that must survive the move (10 release tags): `v1.0.0`, `v1.1.0`,
  `v1.2.0`, `v1.3.0`, `v1.3.1`, `v2.0.0`, `v2.0.1`, `v3.0.0`, `v3.1.0`, plus
  `archive/release-v3.0.0`. The release workflow refuses to reuse an
  existing tag at a different commit (`.github/workflows/release.yml:66`),
  which is why the release-number question belongs to #791, not here.
- Collaborators visible by API: `adrirubio` and `juanrubio`.
- Actions secrets present (names only, by API): `CLAUDE_CODE_OAUTH_TOKEN`,
  `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`. Actions variables: none
  returned. Environments: none returned.
- Rulesets: the API returns an empty list. Classic branch protection on
  `master`: the API returns 404 to this token — that can mean "none" or
  "not visible without admin", so it is **check on the day** with an admin
  account, not assumed absent.
- Deploy keys and webhooks: not readable with this token
  (`admin:repo_hook` scope required for hooks; keys returned 404).
  **Check on the day** before the transfer and again after (§10).
- Workflows (`.github/workflows/`): `backend-tests.yml`, `claude.yml`,
  `codeql.yml`, `e2e.yml`, `factory-checks.yml`, `product-ci.yml`,
  `release.yml`. A whole-folder `git grep` finds **no** hardcoded
  `adrirubio/claude-deck`, `github.repository`, or `claudedeck.org` inside
  `.github/workflows/`, so no workflow source edit is required by the
  transfer itself. The two secret consumers are the Claude Code workflow
  (`.github/workflows/claude.yml:37`, `secrets.CLAUDE_CODE_OAUTH_TOKEN`,
  action `anthropics/claude-code-action@v1` at
  `.github/workflows/claude.yml:35`) and the release workflow's built-in
  token (`.github/workflows/release.yml:151`, `secrets.GITHUB_TOKEN`).
- The release workflow creates the GitHub Release in whichever repository
  it runs in (`softprops/action-gh-release`,
  `.github/workflows/release.yml:138`, tag at `:140`) and names artifacts
  `claude-deck-frontend-v<version>` (`:102`, `:147`). Artifact *names* are
  a product-rename item (#788/#789), not a transfer blocker; the workflow
  keeps working after the move because it never hardcodes the owner.
- CodeQL runs on pushes and pull requests to `master` and `release/v3.1`,
  plus a weekly schedule (`.github/workflows/codeql.yml:4`). A transfer
  does not edit workflow files, so the triggers survive; §10 re-checks
  that security events can still upload (its job needs
  `security-events: write`).
- Dependabot is configured for npm, pip and github-actions
  (`.github/dependabot.yml:1`), and many `dependabot/*` and `deck/*`
  remote branches exist. Nothing moves branches except the transfer
  itself; stale Deck dispatch branches are housekeeping for another day.
- Hardcoded old-address links inside the tracked tree: 111 lines in 38
  files mention `adrirubio/claude-deck` (for example clone instructions at
  `README.md:168` and `DOCUMENTATION_PUBLISHING.md:41`, issue links at
  `CONTRIBUTING.md:38`, changelog compare links at `CHANGELOG.md:224`).
  GitHub redirects keep these working after the move (§5.3); rewriting
  them is inventory work (#788), not a cutover-day edit.

### 6.2 Website repository `adrirubio/claude-deck-website`

At website pin `0c35f39…`:

- Public, default branch `master`, issues on, Discussions **off**, GitHub
  Pages **off**, wiki setting on, 1 star, 1 fork.
- Deploy is GitHub Actions → Cloudflare Pages: `website:.github/workflows/deploy.yml`
  runs `cloudflare/wrangler-action@v3` with
  `pages deploy . --project-name=claude-deck-website`, using repository
  secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (both present
  by API). A push to `master` deploys production — this is why the freeze
  in §3.5 covers this repository too, and why the website plan (#792)
  lands its changes in one reviewed revision.
- `website:.github/workflows/check-pages.yml` only reads files on pull
  requests; it has no secrets and no owner references.
- Branches include `release/v3.0.0`, `preview/website-v2` and Deck
  dispatch branches. The Cloudflare *project name* `claude-deck-website`
  is a Cloudflare-side identifier, not a GitHub name; renaming the GitHub
  repository does not rename the Cloudflare project. Whether to create a
  `synth-city-website` Pages project is a #792/Director decision — the
  runbook only requires that whatever project serves production is the
  one the transferred repository deploys to (§10).

### 6.3 Deck itself (this factory) points at the old names

This transfer moves the factory's own workplace. Before cutover, someone
with Deck admin access must list, and after cutover update:

- the team's GitHub scope/repo bindings for `adrirubio/claude-deck` and
  `adrirubio/claude-deck-website` (the dispatch that produced this very
  document was bound to `adrirubio/claude-deck`);
- every agent charter, skill and workspace whose `origin` remote or
  recorded repository is the old address (local clones keep working via
  redirect, §9, but new dispatches should use the new address);
- branch/label conventions that embed the repository (labels travel with
  the repository, but Deck-side filters keyed by `owner/name` strings do
  not update themselves).

**Check on the day:** the exact Deck configuration records cannot be
inventoried from this repository checkout; §10 requires a post-transfer
smoke dispatch (one no-op triage) to prove the factory still binds, clones
and reports against `albiexai/synth-city` before real work resumes.

## 7. Before cutover day (checklist, in order)

Owner for every line: a named human. Tick nothing on trust — record the
command output or settings screenshot next to each item.

1. Confirm the §3 gates, especially organisation ownership, trademark
   clearance, and the freeze window with a start and end time.
2. Publish the pre-transfer announcement on the **old** product
   repository (§8). Wait long enough for watchers to see it — the exact
   lead time is a Director decision recorded in #791.
3. Take a pre-transfer snapshot of both repositories with the Appendix A
   commands: stars, forks, open issues, tags, branches, secret *names*,
   variables, environments, rulesets, and — with an admin token — branch
   protection, deploy keys, webhooks, and installed GitHub Apps
   (Settings → Integrations). Store it outside the repositories (the
   snapshot is the yardstick for §10; do not commit admin output that
   could contain sensitive URLs without reviewing it first).
4. In `albiexai`, confirm the names `synth-city` and `synth-city-website`
   are free and no same-network fork already sits there (§3.6).
5. Confirm both future owners can sign in, pass 2FA, and see the
   organisation. A transfer to an organisation needs no email acceptance
   dance, but the person clicking needs admin on the source repository
   and create-repository permission in `albiexai` (§5.1).
6. List GitHub App installations that target either repository
   (Settings → Integrations → GitHub Apps). The only app-style consumer
   visible in source is the Claude Code action
   (`.github/workflows/claude.yml:35`), which runs as a workflow with the
   `CLAUDE_CODE_OAUTH_TOKEN` repository secret (`:37`), not as a separate
   App installation — still **check on the day**, because installations
   are granted per account/organisation and an app installed only on
   `adrirubio` may need a fresh grant on `albiexai`.
7. Decide the Cloudflare question in advance (§6.2): keep deploying to
   the existing `claude-deck-website` Pages project through cutover, or
   pre-create the new project per #792 and only flip DNS at go-live. Do
   not improvise this on the day; a `master` push deploys production.
8. Warn the Deck operators: pause dispatches for the freeze window. A
   dispatch mid-transfer could clone through a redirect, push to a branch
   whose binding still names the old owner, or hold a lease on a
   workspace whose recorded repository is about to change.
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
   and installs keep working (redirects §5.3; product fallbacks are #789).
2. Add the README banner linking to that Discussion. Banner copy comes
   from #791; it is a normal reviewed PR into `master` **before** the
   freeze, not an edit during cutover.
3. Only after both are live on the old repository does the freeze start.
   After the transfer, the Discussion and banner travel with the
   repository (§5.2) — §10 verifies the pin survived and the banner link
   still resolves, and the banner is then updated to past tense by a
   normal PR.

## 9. Cutover day: the transfer, step by step

Do the website repository first (smaller blast radius, proves the
mechanics), run the §10 quick checks on it, then the product repository.
If anything in §10 fails on the website move, stop (§11) — do not proceed
to the product repository "to save the day".

For **each** repository, in this order:

1. Start the freeze. Confirm no Actions runs are in progress
   (`gh run list`) and no Deck dispatch is active against the repository.
2. Re-run the §7.3 snapshot if anything merged since it was taken.
3. Repository → Settings → General → Danger Zone → **Transfer
   ownership**. Target organisation: `albiexai`. New name in the same
   step: `synth-city-website` first, later `synth-city`.
4. Confirm the transfer dialogs exactly (type the repository name when
   asked). Do not create anything at the old address afterwards — ever
   (§5.4). This includes forks *into* `adrirubio` from the new home: a
   fork at the previous location deletes the redirects just the same.
5. Immediately open the old URL in a private browser window and confirm
   it redirects to the new home. Then `git ls-remote` the **old** clone
   URL and confirm it answers (redirect working for git, §5.3).
6. Update your own working clones:
   `git remote set-url origin https://github.com/albiexai/synth-city.git`
   (and the `-website` twin). Existing clones would keep working without
   this; doing it now removes a whole class of later confusion.
7. Run §10 in full for this repository, record pass/fail per row, and
   only then lift its part of the freeze.

**What changes for forks and clones (tell people this):**

- Forks stay connected to the transferred repository automatically
  (§5.2). `juanrubio/claude-deck` remains a fork of what is now
  `albiexai/synth-city`; its "upstream" is the new address. Fork owners do
  not have to re-fork, and must **not** delete-and-refork as a "cleanup":
  nothing is gained, and a fork created at the *old* location is the one
  destructive case (§5.4).
- Pull requests from forks keep their history with the repository
  (§5.2). Open PRs should be re-checked in §10 (head/base still resolve).
- Existing clones keep fetching and pushing through the redirect, but
  everyone should run the `git remote set-url` line above once. CI
  systems, scripts and bookmarks that embed
  `github.com/adrirubio/claude-deck` keep working through web redirects;
  anything that compares the repository *string* (Deck bindings, §6.3)
  needs the new string, redirects do not rewrite configuration.

## 10. After each transfer: verification checklist

Compare every row against the §7.3 snapshot. "Basis" says why we expect it
to hold; a row is only done when someone has *seen* it hold.

| # | Check | Basis | How |
|---|---|---|---|
| 1 | Old web URL redirects to new home; an old issue URL and an old PR URL redirect too | Verified §5.3 | Private browser window on three old links |
| 2 | `git clone`/`fetch`/`push` via the **old** URL still work; then update remotes to the new URL | Verified §5.3 | Scratch clone by old URL; push test on a scratch branch, then delete it |
| 3 | Star count and watcher count match the snapshot (32 stars at the pin; use the day's snapshot number) | Verified §5.2 | Repository home + `gh api` (Appendix A) |
| 4 | All 8 forks still list the repository as upstream, incl. `juanrubio/claude-deck` | Verified §5.2 | Forks page / `gh api …/forks` |
| 5 | Tags and releases complete: the 10 tags of §6.1, release assets downloadable | Transfer preserves git data §5.2 | `git ls-remote --tags`; download one old release asset |
| 6 | Issues/PRs intact (count, one open PR head/base, assignees tidy-up list) | Verified §5.2, §5.5 | Compare snapshot; note cleared assignees for non-`albiexai` members |
| 7 | Discussions intact and the §8 announcement is still pinned | Verified §5.2 | Open Discussions on the new home |
| 8 | Wiki: still no content expected; if pages appeared since the pin, they open | Verified §5.2 | `git ls-remote …wiki.git` + click-through |
| 9 | Actions secrets present by name (`CLAUDE_CODE_OAUTH_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` product; the two Cloudflare names website) | Verified §5.2 (names only — values are never visible) | Settings → Secrets and variables, or `gh api …/actions/secrets` |
| 10 | A no-op workflow run succeeds end-to-end on the new home (product: `factory-checks` or a docs-only PR; website: **not** a `master` push until §10 row 12 is decided) | Secrets travel §5.2; runner behaviour **check on the day** | `gh run watch` on the new address |
| 11 | CodeQL still analyses and uploads (security tab shows a fresh run) | Triggers live in source (`.github/workflows/codeql.yml:4`); upload permission **check on the day** (org policy may differ, §5.6) | Push a trivial PR or wait for schedule; inspect Security → Code scanning |
| 12 | Website deploy path: the next *intentional* website `master` merge deploys the expected Cloudflare Pages project and the live site changes | `website:.github/workflows/deploy.yml` (project name is Cloudflare-side, §6.2) — **check on the day** | Coordinate with #792 go-live; verify the Actions run and open the site |
| 13 | Release workflow dry run passes on the new home (`dry_run=true`, `.github/workflows/release.yml:14`) — publishes nothing | Workflow is owner-agnostic §6.1; **check on the day** | Actions → Release → Run workflow with dry run on |
| 14 | Branch protection / rulesets: whatever the admin snapshot found is present again on `master` | **Check on the day** (not visible at the pin, §6.1) | Settings → Branches / Rules, compare snapshot |
| 15 | Deploy keys and webhooks: whatever the admin snapshot found still exists with the same targets; one webhook delivery replays green | Verified §5.2; inventory **check on the day** | Settings → Deploy keys / Webhooks → Recent deliveries |
| 16 | GitHub Apps from the §7.6 list are installed/granted on `albiexai` and respond | **Check on the day** (grants are per-owner) | Settings → Integrations; trigger one app action (e.g. an `@claude` comment, `.github/workflows/claude.yml:13`) |
| 17 | Organisation defaults did not silently widen or narrow access: collaborators `adrirubio` + `juanrubio` still have the intended roles | Verified §5.6 (defaults apply) | Settings → Collaborators and teams |
| 18 | Deck smoke test: one no-op triage dispatch binds to `albiexai/synth-city`, clones, and reports status | **Check on the day** (§6.3) | Deck operator runs it; only then unpause real dispatches |
| 19 | Nothing exists at the old addresses, and nobody's to-do list says "recreate" | Verified §5.4 (destructive) | Open `github.com/adrirubio/claude-deck` — it must redirect, not 404 and not show a fresh repo |
| 20 | Documentation-publishing flow works with new remotes (build docs from product, publish via website repo) | Flow names both repos (`DOCUMENTATION_PUBLISHING.md:41`) | Dry-run the playbook steps that do not publish |

Rows 1–9 and 19 are quick checks and gate any further step. Rows 10–18
and 20 can complete within the freeze day; the freeze lifts per
repository only when its rows pass or a named human accepts a written
exception.

## 11. Rollback note — read before cutover

A transfer is **not fully reversible**, so rollback means "stop and fix
forward", in this order:

1. **Before any transfer:** cancelling is free. If a §3 gate or §7 item
   fails, nothing has moved; reschedule.
2. **Website moved, checks fail:** stop. Do not move the product
   repository. Fix forward on the website repository (secrets, grants and
   Cloudflare settings are all re-creatable). Transferring it *back* is
   possible in principle (same Danger Zone flow, needs create-repo rights
   on the way back), but each hop re-runs §5.5/§5.6 side effects
   (assignees, org defaults) and burns redirect history — treat
   transfer-back as a Director decision, not an operator reflex.
3. **Product moved, checks fail:** same rule. The repository, its history
   and its redirects are safe by construction (§5.2–5.3); almost every
   failure in §10 is configuration (grants, secrets, protection, Deck
   bindings) that can be repaired in the new home faster than a return
   trip. Keep the freeze on, fix, re-run the failed §10 rows.
4. **The unrecoverable error** is recreating a repository or fork at
   either old address: GitHub then permanently deletes the redirects
   (§5.4), and every old link, clone and bookmark in the wild breaks at
   once. There is no undo. If it happens by accident: delete the new
   repository at the old address immediately and contact GitHub Support —
   but plan as if it cannot be undone, because the documentation promises
   no recovery.
5. **Name-retirement side effect:** if the >100-clone/Actions-use
   threshold (§5.9) was crossed, GitHub may refuse to ever reuse
   `adrirubio/claude-deck` again. That also constrains a transfer-*back*
   under the identical name — another reason rollback-by-return is a last
   resort requiring a Director decision and a fresh plan.
6. **DNS/website rollback is separate** and belongs to #792: the GitHub
   transfer does not move `claudedeck.org` traffic by itself, so a website
   problem is never a reason to transfer a repository back.

## 12. Open questions for the Director

These are recorded, not decided, by this plan:

1. Cutover date, freeze length, and the announcement lead time in §7.2
   (announcement texts and release number: #791).
2. Trademark clearance for "Albiex" and "Synth City" (§3.2).
3. Cloudflare: keep the `claude-deck-website` Pages project through
   cutover, or serve production from a new project (with #792, §7.7).
4. Who holds admin on cutover day, and who is the named exception-accepter
   for §10 rows.
5. When (if ever) `adrirubio` takes other measures against name reuse —
   noting §5.4: "protecting" the old name by recreating it would destroy
   the redirects, so the safe protection is simply never to reuse it.

## Appendix A. Evidence: how the §6 facts were read

Read-only commands, run 2026-11-06 from a clean checkout at the product
pin. Re-run them for the §7.3 snapshot and the §10 comparisons (swap in
`albiexai/synth-city` after the move). Admin-only rows need an admin token,
for example `gh auth refresh -h github.com -s admin:repo_hook` for hooks.

```bash
gh api repos/adrirubio/claude-deck            # visibility, features, counts
gh api repos/adrirubio/claude-deck-website
gh api repos/adrirubio/claude-deck/forks?per_page=100
gh api repos/adrirubio/claude-deck/actions/secrets      # names only
gh api repos/adrirubio/claude-deck/actions/variables
gh api repos/adrirubio/claude-deck/environments
gh api repos/adrirubio/claude-deck/rulesets
gh api repos/adrirubio/claude-deck/branches/master/protection   # admin
gh api repos/adrirubio/claude-deck/keys                         # admin
gh api repos/adrirubio/claude-deck/hooks                        # admin
gh api repos/adrirubio/claude-deck/collaborators
git ls-remote --tags origin
git ls-remote https://github.com/adrirubio/claude-deck.wiki.git HEAD
git grep -n 'secrets\.\|vars\.' -- .github/workflows/
git grep -n 'adrirubio/claude-deck'   # 111 lines, 38 files at the pin
```

Observed at the pin (not guessed): the §6 counts, secret names, empty
rulesets list, empty variables/environments, and the missing wiki.
Explicitly **not** observed (token limits, recorded honestly rather than
filled in): branch-protection settings (404), deploy keys (404), webhooks
(scope refused), Actions permission policy (403), and the GitHub App
installation list. §7.3 and §10 rows 14–16 exist because of these gaps.

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
observed (Appendix A), and no row of §10 has been executed yet. GitHub
documentation can change; re-fetch both pages on cutover week and diff the
claims in §5 before starting §9.*
