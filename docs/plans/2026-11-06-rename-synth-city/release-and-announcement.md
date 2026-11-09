# Albiex Synth City: release and announcement plan

**Issue:** #791. **Source pin:** `56b6b40c78cd170dd60698128c7956f17bdbdc25` (master including the merged, C1-accepted `compatibility.md` from PR #798). **Scope:** this file only; it plans the release and drafts the announcement texts. It performs no transfer, release, deployment, DNS or publication action. **Parent:** #787.

## Summary for the reader

This document plans how **Albiex Synth City** v4.0.0 is released and announced, and drafts every user-facing text in plain words: the migration guide, the release notes, the pre-transfer pinned Discussion, the pre-transfer README banner, and the go-live announcement. Later mentions may shorten the name to Synth City; each drafted text below nevertheless gets its own full-name first mention, as the naming rule requires.

Everything substantive is already decided elsewhere and is not reopened here: the version is **v4.0.0** with no reset and no deprecation window; the first start of v4.0.0 automatically moves the database and backups with no manual step; old names stop working at v4.0.0; every new identifier spelling is now decided. What remains for the Director is execution, not design: approving the announcement texts, performing/approving the transfers, and choosing when to publish. This plan sequences those approvals and says exactly what must be true before each one. The drafts in sections 6–9 are **drafts for Director approval** — merging this document publishes none of them.

## 1. Decisions already made (and where)

| Decision | What was decided | Source |
|---|---|---|
| Version | **v4.0.0**, no reset | Parent issue decision record 2026-11-08 ([#787 comment 6719501255](https://github.com/adrirubio/claude-deck/issues/787#issuecomment-6719501255)); issue #791 record. Superseded reset/window questions are handled as rejected history in section 2 |
| Old names | No deprecation window, no parallel support, no aliases; old names stop at v4.0.0 | Same 2026-11-08 record; implemented as design in merged `compatibility.md` sections 1 and 6 |
| Data movement | First start automatically moves the database file set and home data folder, retaining all data, no manual step | Director decision 2026-11-09 ([#787 comment 6738481205](https://github.com/adrirubio/claude-deck/issues/787#issuecomment-6738481205)); designed (and its conflict/recovery limits specified) in `compatibility.md` sections 4.6, 5, 7 |
| Exact new spellings | Short `SYNTH_CITY_*` environment names, `synth_city_*` tools, `X-Synth-City-*` headers, `synth_city.db`; qualified `albiex-synth-city` names in shared places (MCP server `albiex-synth-city-mail`, packages, release files, service units, labels, browser storage); home `~/.albiex-synth-city`; labels `albiex-synth-city-ready` / `albiex-synth-city-design`; startup warning naming still-set old `CLAUDE_DECK_*` variables **kept**, never showing values | Director decision on `compatibility.md` Appendix B ([#787 comment 6748130887](https://github.com/adrirubio/claude-deck/issues/787#issuecomment-6748130887)) — Appendix B in the merged document predates it, so read those items as now-decided, not open |
| Naming presentation | Full name **Albiex Synth City** at first mention and in titles; no bare `synthcity` package/command; repository `albiexai/synth-city` | `website-and-docs.md` section 4.7 (merged PR #797) |
| Transfer | Both repositories transferred (never recreated) to `albiexai/synth-city` / `albiexai/synth-city-website`; Adrian performs transfers; Director owns freeze, exceptions, website release, Cloudflare, DNS and every other role; no fixed cutover date | 2026-11-08 record; mechanics in `transfer-runbook.md` |
| Website | New `synth-city-website` Pages project; `noindex` preview; publish only after org and transfers; every-path 301 from `claudedeck.org` to `albiex.org` | 2026-11-08 record; `website-and-docs.md` sections 7–9 |
| Pre-transfer announcement | Pinned Discussion and README banner on the old repository go live **before** the transfer/freeze | Campaign `README.md:26`; owned in order by `transfer-runbook.md` section 8 and `website-and-docs.md` section 9.2 step 3; texts drafted here (sections 8–9) |

## 2. Superseded history: version reset and deprecation window

The original #791 issue asked this document to compare (a) continuing at v4.0.0 with (b) resetting to v1, to recommend a deprecation window of two minor releases, and to assume `deck_` aliases. All three premises were superseded by the 2026-11-08 decisions before this plan was written, so they are recorded here once as rejected history rather than re-argued as live options:

- **Version reset to v1 — rejected.** The decided release is v4.0.0. Separately from that decision, two pinned facts would have made a reset costly: transferred repositories keep their existing tags, and this repository already carries `v1.0.0`…`v3.1.0` (`git tag -l 'v*'` at the pin), so fresh `v1.x` tags would collide outright; and the release workflow refuses to create a tag that already points at a different commit (`.github/workflows/release.yml:66–76`). Those facts prove *collision*; they do not by themselves prove anything about sorting. Sorting is a separate mechanism: the codebase's own version comparison splits on dots and compares numerically part by part (`backend/app/services/plugin_service.py:1330–1352`), under which `1.0.0 < 3.1.0 < 4.0.0` — so a reset release would sort *below* the current release for any tool or operator using ordinary numeric/semantic ordering, looking like a downgrade. No product self-update comparator was found at the pin, so this is stated as an operator/tooling consequence of numeric ordering, not as a claim about an in-product updater.
- **Deprecation window / aliases — rejected.** There is no window in which old names keep working, and the renamed tools register no `deck_` aliases (`compatibility.md` sections 4.1, 4.3). The migration guide in section 6 therefore describes one clean break plus automatic data movement, never a grace period.

## 3. Release preconditions (all must be true before tagging)

The release described here is the rename implementation shipped as v4.0.0. Tagging is blocked until every row holds; this document can merge long before any of them do.

| # | Precondition | Evidence owner |
|---|---|---|
| P1 | The compatibility design is **implemented** and its section-7 test list passes — in particular the standard-upgrade proof (stop v3.1 → start v4.0.0, nothing else) retaining data through current readers, and the power-loss boundary. Acceptance of `compatibility.md` was source/design review only; it proved no behaviour | Implementation team; `compatibility.md` section 7 |
| P2 | Decided spellings (section 1) are the ones implemented everywhere — environment, tools, headers, database file, home folder, MCP server, packages, artifacts, units, labels, storage keys — and the no-old-name guard (T-G1) passes with only its named exceptions | Implementation team |
| P3 | Version fields are synced to `4.0.0` by the existing tooling (`scripts/bump-version.sh` writes `VERSION`, `frontend/package.json`, `backend/pyproject.toml`, lockfiles and `backend/app/config.py`; at the pin they read `3.1.0`, e.g. `backend/app/config.py:17`) | Release operator |
| P4 | The release commit is a single accepted full SHA on `master`, and a **dry run** of the manual release workflow passes against it (`.github/workflows/release.yml:3–17` — `workflow_dispatch` with explicit version + 40-character commit + `dry_run` defaulting to true) | Release operator |
| P5 | Transfer runbook gates that the release depends on are green and sequenced with section 4 (pre-transfer announcement live before freeze; transfers verified before anything is published as the new home) | `transfer-runbook.md` sections 3, 7–10 |
| P6 | The Director has approved the final announcement texts (sections 6–9 as amended by the Director) and the publication moment; no fixed cutover date exists in advance | Director |

## 4. Release sequence

Ordering only; every step's mechanics belong to the owner named. Steps 4–7 interleave with `website-and-docs.md` section 9.2, and where orders could conflict the transfer runbook wins (its sections 7–10), exactly as that document requires.

1. **Pre-transfer announcement goes live** (Director-approved texts, sections 8–9): pinned Discussion posted, README banner merged by normal reviewed PR into `master` *before* the freeze (`transfer-runbook.md` section 8).
2. **Freeze, transfers, verification** under the runbook (Adrian performs; Director owns freeze/exceptions). Nothing in this document authorizes any of it.
3. **Rename implementation lands** on the transferred repository's `master` under its own reviewed process, including P1–P3. (Whether implementation work starts earlier on branches is an implementation-team choice; it must not be *released* before this sequence completes.)
4. **Website cutover merge** as one reviewed revision, then live checks (`website-and-docs.md` section 9.2 steps 6–7); `claudedeck.org` redirect switched on only after those checks pass.
5. **Release run (dry run first, P4):** invoke the manual workflow with version `4.0.0` and the accepted full commit SHA. The workflow validates that all version fields equal the input (`.github/workflows/release.yml:54–64`), refuses a pre-existing `v4.0.0` tag pointing elsewhere (`:66–76`), builds the frontend archives under the decided release-file names (`albiex-synth-city-frontend-v4.0.0.zip` / `.tar.gz`, replacing today's `claude-deck-frontend-…` at `:102–105`), and — only with `dry_run` explicitly off — creates tag `v4.0.0` and the GitHub release. Paste the approved release notes (section 7) as the release body; do not improvise release text in the workflow UI.
6. **Post-release verification:** fresh install from the release artifacts starts as Albiex Synth City v4.0.0; a staged v3.1 fixture performs the standard upgrade and passes the same reader-level checks as T-D1 (backups download/restore, attachments list/paste/delete); old-domain and old-repository addresses land on the new ones. Any failure stops at step 7's recovery rules — no hot-fix by editing the release after the fact.
7. **Go-live announcement** (section 10) is published **after** steps 4–6 pass, when the Director says so. The pre-transfer banner is then updated to past tense by a normal reviewed PR outside the freeze (`transfer-runbook.md` section 8).

**Abort and rollback, stated honestly.** Before tagging, aborting is free: nothing has been promised publicly beyond the pre-transfer announcement, whose correction is a Director-approved follow-up post. After a user has started v4.0.0, there is no rename-back downgrade (section 6): the only recovery is restoring the complete pre-upgrade state from a pre-upgrade backup. The release must therefore never be announced as “try it and switch back”, and a defective v4.0.0 is fixed forward (v4.0.1) or the release is withdrawn with the full-restoration instructions — never by telling users to rename files back.

## 5. Redirect map (summary; mechanics owned elsewhere)

This section is the announcement-facing summary only. Implementation and verification belong to `website-and-docs.md` section 8 and `transfer-runbook.md` sections 7–10; if this summary and those documents ever disagree, they win.

| From | To | Kind | Owner |
|---|---|---|---|
| `claudedeck.org/<any path>` | `albiex.org/<same path>` (including `/docs/…` and assets) | 301 permanent, every path, new Cloudflare configuration at DNS move | Director (Cloudflare/DNS); `website-and-docs.md` section 8 |
| `github.com/adrirubio/claude-deck` (web, git, API) | `github.com/albiexai/synth-city` | Automatic GitHub redirect, **because transfer, not recreation** — which is also why the old repository must never be recreated | Transfer runbook |
| `github.com/adrirubio/claude-deck-website` | `github.com/albiexai/synth-city-website` | Same | Transfer runbook |
| Links inside our own pages/docs/README | New addresses directly (never relying on the redirects above); personal profile links stay personal attribution | Content edits in the rename work | `website-and-docs.md` section 8 |

Two announcement consequences: public text may promise that old *web and repository links* keep landing in the right place, and must never extend that promise to old *runtime names* (environment variables, tool names, headers, file paths), which stop working at v4.0.0 by decision. Conflating the two is the single most likely announcement error; every draft below keeps them in separate sentences.

## 6. Draft: migration guide for existing users

> Draft for Director approval. Publish target: docs site + linked from the release notes. Wording describes the *accepted compatibility design* (`compatibility.md` sections 4–6); it may only be published once that design is implemented and its tests pass (P1).

---

# Moving to Albiex Synth City v4.0.0

**Albiex Synth City** is the new name of Claude Deck. Version 4.0.0 is the rename release. For most installations the whole move is: **stop the old version, start the new one.** Your teams, settings, Agent Mail history, backups and attachments come with you automatically — there is no migration command to run and nothing to rename by hand for a standard installation. Read “If you customised…” below only if you changed defaults or wrote your own integrations.

### Before you upgrade

1. Let running teams finish, or stop them. Running agent sessions do not carry over live — their work and history are kept, and you relaunch the teams afterwards.
2. Keep a backup of your installation as you normally would before a major upgrade. Version 4.0.0 cannot be “renamed back”: the only way back is restoring that pre-upgrade backup in full (see “Going back”).
3. Stop Claude Deck v3.1 completely before starting Albiex Synth City v4.0.0. Do not run both against the same data.

### What happens on first start

- Your database moves from `claude_registry.db` to **`synth_city.db`** (same folder), including its SQLite sidecar files. It is the same database — every team, setting and message is still there.
- Your data folder moves from `~/.claude-registry` to **`~/.albiex-synth-city`**, including `backups/` and `bridge-attachments/`. Existing backups stay downloadable and restorable; existing attachments keep working.
- If you used Mail setup to connect your coding agents, those connections are re-registered under the new server name **`albiex-synth-city-mail`** automatically (with a safety backup taken first). Agent Mail tools are renamed from `deck_…` to **`synth_city_…`** (for example `synth_city_check_inbox`); newly launched agents see the new names.
- The app runs under a major version **4.0.0**; the browser keeps your selected provider and stored operator token.

If both an old and a new database with data are found, startup stops safely and tells you both paths instead of guessing — nothing is deleted. That state cannot result from a normal upgrade; ask for help rather than deleting either file. If a first start is interrupted (power loss, killed process), simply start again: the move resumes where it stopped.

### What changed name (the short list)

| Was (v3.1) | Now (v4.0.0) |
|---|---|
| `CLAUDE_DECK_*` environment variables | `SYNTH_CITY_*` |
| `deck_*` Agent Mail tools | `synth_city_*` (no aliases) |
| MCP server `claude-deck-mail` | `albiex-synth-city-mail` |
| `claude_registry.db` | `synth_city.db` |
| `~/.claude-registry/` | `~/.albiex-synth-city/` |
| Labels `claude-deck-ready` / `claude-deck-design` (defaults for new scopes) | `albiex-synth-city-ready` / `albiex-synth-city-design` — existing scopes keep matching their existing labels; nothing to rename |
| Release files `claude-deck-frontend-v…` | `albiex-synth-city-frontend-v…` |
| `claudedeck.org`, `adrirubio/claude-deck` links | `albiex.org`, `albiexai/synth-city` (old links redirect) |

Old runtime names stop working at v4.0.0. There is no period where both sets work.

### If you customised…

- **You set `CLAUDE_DECK_INSTANCE_NAME`, `…_INSTANCE_ID`, `…_INSTANCE_ACCENT` or `…_EXTERNAL_ACTOR_TOKEN` yourself:** rename them to the `SYNTH_CITY_…` spellings. Until you do, they are ignored (a custom instance label falls back to the default). At startup the app warns once, naming any old variables still set — it never displays their values.
- **You set a custom database location or attachment folder:** it stays exactly where it is. Only the shipped default locations move, each independently. Scripts that referenced the *default* filenames above need the new names.
- **You added the Mail MCP server to an agent by hand** (not via Mail setup), or heavily edited what setup installed: that entry stops working and is reported as needing attention. Re-add it under `albiex-synth-city-mail`, or run Mail setup for that agent.
- **Your prompts, charters, skills or scripts name `deck_*` tools, the error codes `deck_unreachable`/`deck_http_error`, or the headers `X-Deck-Operator-Token` / `X-Deck-Session-Token` / `X-Claude-Deck-Terminal-Token`:** update them to `synth_city_*`, the new codes, and `X-Synth-City-…`. Token *values* did not change, but stopped sessions must be relaunched — they register fresh sessions; old session credentials are not revived.
- **You download releases by script:** use the new `albiex-synth-city-frontend-v4.0.0` file names.

### Going back

There is no supported downgrade by renaming files back: after first start, data files, stored file references, agent connections and browser state have all moved. To return to v3.1 you must restore your complete pre-upgrade backup (database, data folder and agent configuration) and accept losing anything created after the upgrade. If that trade-off is not acceptable, do not upgrade until you are ready to stay.

---

## 7. Draft: v4.0.0 release notes

> Draft for Director approval. Publish target: the GitHub release body for tag `v4.0.0` (section 4, step 5). Keep the first line exactly in this shape — it is the one place “formerly” belongs.

---

# Albiex Synth City v4.0.0 — formerly Claude Deck

**Albiex Synth City** is the new name of Claude Deck. Same project, same data, new name — now developed as `albiexai/synth-city` and documented at `albiex.org`. Old links redirect.

**Upgrading from v3.1:** stop the old version completely, then start v4.0.0. Your database (`claude_registry.db` → `synth_city.db`), backups and attachments (`~/.claude-registry` → `~/.albiex-synth-city`), teams, settings and Agent Mail history move automatically on first start — no migration command, no manual renaming for a standard install. Read the [migration guide](LINK) before upgrading if you customised paths, environment variables, agent connections, or scripts.

**Breaking changes (complete list):**

- Old runtime names stop working; there are no aliases and no grace period.
- `CLAUDE_DECK_*` → `SYNTH_CITY_*` environment variables. Hand-set instance/supervisor variables must be renamed; startup warns (names only, never values) if old ones remain set.
- Agent Mail tools `deck_*` → `synth_city_*`; MCP server `claude-deck-mail` → `albiex-synth-city-mail`. Connections made through Mail setup are rewritten automatically; hand-written ones must be re-added.
- API headers `X-Deck-*` / `X-Claude-Deck-Terminal-Token` → `X-Synth-City-*`; error codes renamed to match. Running sessions must be relaunched; they register as new sessions.
- Default database and data-folder paths renamed (above). Custom locations are untouched.
- New queues/scopes default to labels `albiex-synth-city-ready` / `albiex-synth-city-design`; existing scopes keep working with their current labels.
- Downgrade is restore-from-backup only — see the migration guide.

**Not changed:** your data model and history, backup file contents, token values, and the internal identifiers that existing databases depend on.

Full rename design and upgrade contract: [compatibility design](LINK). Report upgrade problems with your startup log — never post tokens or credentials.

---

## 8. Draft: pinned Discussion (pre-transfer, old repository)

> Draft for Director approval. Publish target: a pinned Discussion on `adrirubio/claude-deck`, posted and pinned **before** the transfer/freeze (section 4 step 1; `transfer-runbook.md` section 8). Square-bracketed fields are filled by the Director at posting time — no cutover date exists in advance (2026-11-08 decision), so the draft deliberately promises an update instead of inventing one. Discussion preservation across transfer is verified after the move (runbook section 10 phase B), not assumed.

---

**Title:** Albiex Synth City: Claude Deck is changing its name and moving

**Albiex Synth City** will be the new name of this project.

**What is happening.** This repository will be transferred — not copied, not recreated — to its new home at `albiexai/synth-city`, and the website will move to `albiex.org`. The next major release after the move is **v4.0.0**. [Director to add: planned move window, or “We will update this post with the date before anything moves.”]

**What will not break.** Existing links to this repository and to `claudedeck.org` will redirect to the new addresses. Your clone, bookmarks and installed copy keep working; you do not need to re-clone. Your local data is not touched by the repository move at all.

**What will change at v4.0.0.** Release 4.0.0 renames the runtime identifiers (environment variables, Agent Mail tool names, default database and data-folder paths). For a standard installation the upgrade is still just *stop the old version, start the new one*: your database, backups, settings and history move automatically on first start, with no manual step. If you customised those names or wrote scripts against them, read the migration guide when v4.0.0 lands — it lists every rename. Old runtime names will not keep working alongside the new ones; this post is the advance notice.

**What you need to do now.** Nothing. We will update this Discussion when the move is scheduled and again when v4.0.0 is released. Please use this thread for questions about the rename so answers stay in one place.

---

## 9. Draft: README banner (pre-transfer, old repository)

> Draft for Director approval. Publish target: top-of-README banner on `adrirubio/claude-deck`, merged by a normal reviewed PR before the freeze, linking to the section-8 Discussion. After the transfer it is updated to past tense by a normal reviewed PR outside the freeze (`transfer-runbook.md` section 8). The past-tense replacement is drafted alongside so the swap needs no new copy decision.

**Before the move (banner text):**

> **Albiex Synth City** is the future name of this project. This repository will move to [`albiexai/synth-city`](https://github.com/albiexai/synth-city) and the website to [albiex.org](https://albiex.org); old links will redirect. Details and questions: [the pinned announcement](LINK-TO-DISCUSSION).

**After the move (replacement text, for the transferred repository's README):**

> **Albiex Synth City** — formerly Claude Deck. This repository moved here from `adrirubio/claude-deck`; old links redirect. Upgrading from v3.1? Read the [migration guide](LINK) first.

Placement rules: exactly one banner, above the existing title/introduction, removed (not stacked) when replaced. The banner is file content and travels with git history through the transfer, so no separate migration of the banner itself is needed; what must be verified after transfer is that its Discussion link still resolves and the Discussion is still pinned.

## 10. Draft: go-live announcement

> Draft for Director approval. Publish target: new repository Discussion/announcement + website news slot if one exists at publication time. Publish **only after** section 4 steps 4–6 pass (website live checks, redirect switched on, release verified). This is deliberately separate from the section-8 pre-transfer post.

---

# Albiex Synth City v4.0.0 is live

**Albiex Synth City** v4.0.0 is released. This is Claude Deck under its new name: project home [`albiexai/synth-city`](https://github.com/albiexai/synth-city), website and docs at [albiex.org](https://albiex.org). Links to the old repository and to `claudedeck.org` redirect here.

**Upgrading from v3.1** is a normal major upgrade: stop the old version completely, start v4.0.0, and your teams, settings, history, backups and attachments move automatically — no migration command and no manual renaming for a standard install. The [migration guide](LINK) covers the renamed environment variables (`SYNTH_CITY_*`), Agent Mail tools (`synth_city_*`), MCP server (`albiex-synth-city-mail`), database (`synth_city.db`) and data folder (`~/.albiex-synth-city`), and the cases that need your attention if you customised any of them. Please read its “Going back” section before upgrading: downgrade means restoring a pre-upgrade backup in full.

Release notes: [v4.0.0](LINK). Questions and upgrade reports: [Discussions](LINK) — include your startup log, never tokens or credentials. Thank you to everyone who reported issues under the old name; history, issues and credit all carried over with the transfer.

---

## 11. Acceptance checklist for whoever executes this plan

Document/pipeline checks (necessary, not sufficient):

1. Every published text matches its Director-approved final wording byte-for-byte apart from filled LINK/date fields; each text's first product mention is **Albiex Synth City**; no text promises a deprecation window, aliases, a rename-back downgrade, or old runtime names continuing to work.
2. Every decided spelling in sections 6–10 matches section 1 of this plan and the shipped build (one grep pass for `CLAUDE_DECK_`, `deck_`, `claude-deck`, `claude_registry`, `.claude-registry` over the *published* texts returns only intentional “was” references).
3. Release run used `dry_run` first against the accepted full SHA, then the real run with identical inputs; tag `v4.0.0` points at that SHA; artifacts carry the `albiex-synth-city-frontend-v4.0.0` names.

Behavioural/operational proofs (owned elsewhere, required before section 10 may be published):

4. P1 evidence exists: the compatibility implementation's test list passes, including the standard-upgrade and power-loss boundaries — announcement text must not run ahead of this.
5. Transfer and website live checks pass under their owning documents; `claudedeck.org` spot checks (`/`, one docs page, one asset) return the same paths on `albiex.org`; old GitHub web/git/API addresses redirect; the pinned Discussion is present, still pinned, and its banner link resolves on the new home.
6. A fresh install and a staged v3.1 standard upgrade both succeed from the published release artifacts (section 4 step 6).

## 12. What remains Director-owned

Nothing in sections 1–11 needs a new *design* decision. The following are execution approvals only, and this document must not be read as granting them:

- approval of the final announcement/release-note/migration-guide wording (sections 6–10) and of any fill-in dates or links;
- the freeze, both repository transfers, website/DNS/Cloudflare changes, and their timing (“when ready”, per the 2026-11-08 record);
- the real (non-dry-run) release invocation and the go-live publication moment;
- any exception to the sequences above, and any reopening of a decided name.

## Appendix: reproducing the pin evidence

```bash
PIN=56b6b40c78cd170dd60698128c7956f17bdbdc25
# merged planning documents this plan builds on
git ls-tree $PIN docs/plans/2026-11-06-rename-synth-city/
git rev-parse $PIN:docs/plans/2026-11-06-rename-synth-city/compatibility.md
# existing version tags (collision fact only - sorting is argued from
# plugin_service's numeric comparison, not from this list)
git tag -l 'v*' | sort -V
# version fields and bump tooling at the pin
grep -n 'app_version' backend/app/config.py
sed -n '1,20p' scripts/bump-version.sh
# release workflow gates: input validation + dry run, tag-collision refusal
sed -n '1,80p' .github/workflows/release.yml
```
