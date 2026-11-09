# Albiex Synth City rename: inventory of every old-name occurrence

**Issue:** #788. **Source pin:** `94cb599a98d60281db824fc8e726d841acdb46a0` (master as merged through PR #794). **Scope:** this file only; it plans no code change.
**Parent:** #787. **Next consumer:** #789 (compatibility design) reads the runtime-identifier class (section 4.1) plus the supplemental compatibility index (section 3.4), which cross-references the runtime families listed in sections 5.1, 5.2, 5.3, 5.4 and the package name excluded in 5.6. Director decisions recorded after measurement (section 7) remove parallel old-name support from that design and separately require a one-time automatic first-start move of the database and backups, which #789 designs.

## Summary for the reader

This inventory supports the rename to **Albiex Synth City**. Naming presentation in this document follows the Director rule recorded later in merged PR #797 (`website-and-docs.md` section 4.7 at merge `9895f49b5074e621dadd0d62390fb974647be40b`): first current mention uses the full name, page titles use the full name, later "Synth City" is allowed, and no package, command or repository is named bare `synthcity` (`albiexai/synth-city` remains decided). That rule post-dates the measurement pin below; quoted excerpts and titles in the tables are preserved exactly as measured at the pin and are not rewritten to manufacture compliance.
A case-insensitive search for the six old-name strings in tracked text files finds **1,596 matching lines** (1,728 non-overlapping occurrences) in **255 distinct files** at the pin. Every one of those lines is listed exactly once, in exactly one of four classes, in the tables in section 4. Separate searches in section 5 cover the short name `Deck`, joined spellings such as `claudedeck.org`, the `deck_` names, filenames, one binary archive, and the Claude Code references that stay. Nothing in section 5 is added into the headline total.
The one-sentence version: most old-name text is documentation and dated planning records that either rename as ordinary docs or stay untouched as history; the compatibility risk is concentrated in the much smaller runtime-identifier class (environment variables, the MCP server name, headers and markers, database and backup paths, package names, storage keys).
This inventory file itself did not exist at the pin, so its own old-name mentions are not counted. The approved re-pin condition applied before the inventory run: had master moved before that run, measurement would have stopped and re-pinned instead of mixing commits. Master later moved for PR #797, and the Director recorded further decisions on 2026-11-08 and a completing data-movement decision on 2026-11-09 (comments on #787, summarised in section 7); those later policies are cited separately and no count in this document mixes commits. Every number below is a measurement of `94cb599a98d6`, not a constant.

## 1. Method

### 1.1 The primary search

```bash
git grep -I -n -i -E 'Claude Deck|claude-deck|claude_deck|CLAUDE_DECK|claude_registry|\.claude-registry' \
  94cb599a98d60281db824fc8e726d841acdb46a0 -- .
```

- `-I` restricts the primary sweep to text files; the one binary match is handled as a supplemental set (section 5.5). `-i` makes the search case-insensitive, so `Claude-Deck`, `CLAUDE-DECK`, `Claude_Deck` and similar spellings of the six terms are primary matches, not a separate variant list. The escaped dot in `\.claude-registry` matches only the literal dot. `CLAUDE_DECK_*` names are counted once per full name through the `CLAUDE_DECK` term.
- The tracked universe at the pin is 1,270 files (`git ls-tree -r --name-only`).
- Three units are used throughout, always labelled: a **matching line** (a text line with at least one match), a **non-overlapping occurrence** (left-to-right regex matches on the line; one line can hold several), and **distinct files** (a set union — a file appearing in two classes or under two terms is still one file in any total that spans them).
### 1.2 Classification: one class per line

The classified atom is the matching **line**, not the file. A mixed file appears in several class tables, once per (file, class) pair, and the line-number lists in those rows never overlap. All occurrences on one line inherit that line's class. Tests are applied in this fixed precedence order:

1. **History to keep** — dated planning records (`docs/plans/**`, `docs/superpowers/**`, including this rename campaign's own dated folder, which is a record of the rename and is not mechanically rewritten), released-version changelog entries (section 4.4 lists the current-pointer lines that stay in docs instead), and the one-off rollout, validation, soak and handoff records under `docs/deploy/` (the current Lane B operating note, `docs/deploy/product-lane-b-factory.md`, stays in docs). A historical line is history even when its wording is user-facing.
2. **Runtime identifier** — the matched string itself functions, in an executable, configuration, data or test-contract context, as a name current installs or agents depend on: environment variables, the MCP server name, HTTP headers and content markers, database and backup paths, package names, browser storage keys, stored label values, release artifact filenames, unit names and paths. It also includes machine-recognized strings that code or tests search or match against, even when their shape is prose (searched markers and test prompt prefixes/predicates). A prose mention of such a name (a sentence in a manual, a comment, an internal docstring) is **not** runtime; it falls through to the tests below. A match that occurs only inside a displayed web link is likewise copy, or test-fixture data, not a runtime dependency. That is why the same environment variable can be runtime in `backend/app/config.py` and docs in a guide — section 3's term-by-class matrix keeps those mentions findable for #789.
3. **User-facing copy** — the old product name presented as current copy to a person or an agent: interface text and titles, generated prompts, log and error messages, confirmation-dialog text, emitted agent-facing tool descriptions, the root `README.md` product prose, `launch-posts.md`, and the documentation home page (`docs/index.md`). A function docstring counts here, not in docs, when the product exports it as a public tool description presented to agents.
4. **Docs** — everything else: manuals and guides, code comments and internal docstrings that are not emitted as tool descriptions, test descriptions, and changelog pointer lines that are maintained with the current tree.

Judgement calls are recorded so a reviewer can disagree precisely. (1) Machine-recognized prose-shaped strings are runtime: the OpenCode plugin marker (defined at `backend/app/services/agent_mail_install_service.py:65`, written at `:582`, asserted at `backend/tests/agent_mail/test_install.py:381`) and the e2e prompt prefix/predicate (`scripts/e2e-agent-mail-same-repo-codex.sh:31`, searched with `rg -qF` at `:148` and `:152`; the permission-prompt predicate at `:88` triggering `:89`). (2) Displayed or emitted copy is user-facing even when it embeds identifiers: the warning at `backend/app/services/instance_identity.py:95` (the lookup is `:115`), the `mailConfirm` confirmation strings at `frontend/src/features/agent-mail/mailSetup.ts:193`, `:220`, `:239` (rendered at `frontend/src/features/agent-mail/HarnessMailSetup.tsx:132`), and the public MCP tool descriptions at `backend/mcp_shim/agent_mail_server.py:358`, `:386`, `:885`, `:1182` and in the generated `integrations/pi-agent-mail/manifest.ts` (exported by `integrations/pi-agent-mail/sync_manifest.py:21` and registered at `integrations/pi-agent-mail/extension.ts:36`). (3) `launch-posts.md` is outward marketing copy rather than a release record, so it is user-facing even though the posts are old.

## 2. Reconciling the earlier counts

| Search | Matching lines | Occurrences | Distinct files |
|---|---:|---:|---:|
| Case-insensitive text (this inventory) at `94cb599a98d6` | 1,596 | 1,728 | 255 |
| Case-sensitive text probe at `94cb599a98d6` | 1,542 | 1,673 | 249 |
| Case-insensitive incl. binary at `94cb599a98d6` | 1,597 reported matches | not counted (binary) | 256 |
| Case-insensitive text at older pin `c4daece7b300` | 1,537 | 1,660 | 253 |
| Case-sensitive text at older pin `c4daece7b300` | 1,483 | 1,605 | 247 |
| Issue brief ("about 1,470 occurrences in 248 files") | — | ~1,470 | 248 |

No mode/unit pair reproduces the brief exactly; it is closest to case-sensitive matching lines and files at the older pin, and it used the word "occurrences" loosely. The growth from the older pin to this pin is mostly the merged rename-planning documents themselves, which necessarily discuss the old name. Case-insensitive matching adds 54 lines over the case-sensitive probe at this pin, chiefly the `X-Claude-Deck-Terminal-Token` header (for example `backend/app/api/v1/agent_bridge/router.py:384`).

## 3. Totals

### 3.1 By class

| Class | Matching lines | Occurrences | Distinct files |
|---|---:|---:|---:|
| runtime | 377 | 400 | 93 |
| user-facing | 170 | 174 | 53 |
| docs | 156 | 171 | 46 |
| history | 893 | 983 | 95 |
| **Primary total (files as union)** | **1,596** | **1,728** | **255** |

The per-class file counts sum to more than the union because mixed files appear in several classes; the line and occurrence columns do sum, because lines partition disjointly.

### 3.2 By search term (occurrences; lines and files can overlap between terms)

| Term | Occurrences | Lines | Files | Runtime | User-facing | Docs | History |
|---|---:|---:|---:|---:|---:|---:|---:|
| Claude Deck (spaced, any case) | 527 | 506 | 124 | 4 | 125 | 62 | 336 |
| claude-deck (hyphen, any case) | 808 | 755 | 163 | 236 | 42 | 78 | 452 |
| claude_deck (snake, other cases) | 10 | 10 | 4 | 0 | 0 | 0 | 10 |
| CLAUDE_DECK (uppercase) | 296 | 274 | 59 | 153 | 7 | 12 | 124 |
| claude_registry | 66 | 55 | 20 | 1 | 0 | 14 | 51 |
| .claude-registry | 21 | 21 | 12 | 6 | 0 | 5 | 10 |

Term rows overlap: one line can carry two terms, so term line counts need not sum to the primary line total. Occurrence columns in this table do sum to the primary occurrence total.

### 3.3 Runtime identifiers at a glance (for #789)

The runtime class contains 16 distinct `CLAUDE_DECK_*` environment names: `CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN`, `CLAUDE_DECK_INSTANCE_ACCENT`, `CLAUDE_DECK_INSTANCE_ID`, `CLAUDE_DECK_INSTANCE_NAME`, `CLAUDE_DECK_MAIL_OPT_IN`, `CLAUDE_DECK_MAIL_PYTHON`, `CLAUDE_DECK_MAIL_SHIM`, `CLAUDE_DECK_MAIL_TOKEN`, `CLAUDE_DECK_PROVIDER`, `CLAUDE_DECK_TEAM_PRESET_ID`, `CLAUDE_DECK_TEAM_PRESET_NAME`, `CLAUDE_DECK_TEAM_SLOT_COLOR`, `CLAUDE_DECK_TEAM_SLOT_ID`, `CLAUDE_DECK_TEAM_SLOT_NAME`, `CLAUDE_DECK_TEAM_SLOT_ROLE`, `CLAUDE_DECK_URL`.
Other runtime groups, each traceable through the section 4.1 line lists: the MCP server name `claude-deck-mail` (defined at `backend/app/services/agent_mail_install_service.py:34`); the `X-Claude-Deck-Terminal-Token` header (for example `backend/app/api/v1/agent_bridge/router.py:384`); the stored labels `claude-deck-ready` and `claude-deck-design` (for example `backend/app/models/database.py:246`); the database file in `database_url` (`backend/app/config.py:30`) and the `~/.claude-registry` paths (for example `backend/app/config.py:33`); package names (`docs/package.json:2`, `integrations/pi-agent-mail/package.json:2`); browser storage keys (for example `frontend/src/contexts/ProviderContext.tsx:16`); release artifact filenames (`.github/workflows/release.yml:102`); and the product-factory unit names and install paths under `scripts/product-factory/`. Prose mentions of these same names in manuals are in docs by the precedence rule; section 3.2 shows how many there are per term. The Director decided on 2026-11-09 (section 7) that the first start of v4.0.0 automatically moves the existing database file and backups folder to their new names, retaining every team, setting and history without a manual step; that is a requirement for #789 to design — including both-old-and-new-path conflicts and a no-manual-step v3.1 upgrade test — not an implemented result recorded here, and it is not parallel old-name support. This inventory identifies only the old paths; #791 describes the move in migration guidance and release notes.

### 3.4 Supplemental compatibility index (for #789)

These families are runtime evidence outside the six primary terms. They stay in section 5 with their own totals; this index only prevents #789 from reading section 4.1 as the whole compatibility surface. #789 assesses rename, compatibility and migration needs per family under the Director decision recorded on 2026-11-08 that there is **no deprecation window and no parallel old-name support**, completed on 2026-11-09 by the decided one-time automatic first-start move of the database and backups (section 7); that move is separate from, and creates no exception to, the no-parallel-support rule, and its conflict behaviour and tests belong to #789.

| Supplemental family | Representative evidence | Listed in | What #789 assesses |
|---|---|---|---|
| Bare-Deck headers and trailers (`X-Deck-Operator-Token`, `X-Deck-Session-Token`, `Deck-Agent-Slot`, `Deck-Work-Item`) | `frontend/src/features/agent-mail/api.ts:22`; `backend/mcp_shim/agent_mail_server.py:125`; `backend/app/services/github_dispatch_service.py:1448` | 5.1 | Replacement header names with no parallel reading of the old headers, and how new commit trailers coexist with trailers already in history |
| Joined export and old domain (`ClaudeDeckAgentMailPlugin`, `claudedeck.org`) | `backend/app/services/agent_mail_install_service.py:599`; `README.md:3` | 5.2 | Generated plugin export replacement or regeneration for installed plugins, with no alias window; domain redirects to the decided new `synth-city-website` Pages project (with #790/#792) |
| `deck_` Agent Mail tools and other `deck_` tokens | definitions from `backend/mcp_shim/agent_mail_server.py:357` onward | 5.3 | A new tool prefix (exact prefix still open) as replacement names for the 36 tools, with no old-name alias window; the 46 other tokens individually |
| systemd unit filenames | `scripts/product-factory/claude-deck-product.service` and siblings | 5.4 | Unit rename and enable/state handling, with no parallel old unit names, and references between units |
| Product package name excluded from the keep-list (`claude-code-registry-backend`) | `backend/pyproject.toml:2`; `backend/uv.lock:188` | 5.6 exclusion | Package rename and lockfile regeneration; never bare `synthcity` (the `website-and-docs.md` section 4.7 rule noted above) |

## 4. The classified primary lines

Each table below has one row per (file, class). "Line numbers" lists every counted line for that row, compressed into ranges; expanding a class's ranges reproduces exactly that class's share of the raw search output (section 6).

### 4.1 Runtime identifiers — 377 lines, 400 occurrences, 93 files

These are the six-term lines whose exact strings current consumers read. Runtime families that sit outside the six primary terms are indexed in section 3.4 and listed in section 5; they are not in this table and not in its counts. #789 assesses replacement names for each family here and there under the decided rule of no deprecation window and no parallel old-name support; the sole decided data movement is the automatic first-start database/backups move in section 7, whose new names, both-path conflict behaviour and tests #789 designs, and not every test-only name necessarily needs any data movement. Lines that merely mention these names in prose are not in this table.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `.github/workflows/release.yml` | 7 | 8 | 102, 104-105, 133-134, 147-148 | zip -r "../../claude-deck-frontend-v${RELEASE_VERSION}.zip" . |
| `.gitignore` | 1 | 1 | 61 | ~/.claude-registry/ |
| `backend/app/api/v1/agent_bridge/router.py` | 4 | 4 | 384, 407, 424, 471 | token: str = Header(default="", alias="X-Claude-Deck-Terminal-Token"), |
| `backend/app/config.py` | 2 | 2 | 30, 33 | database_url: str = Field(default="sqlite+aiosqlite:///./claude_registry.db", repr=False) |
| `backend/app/models/database.py` | 2 | 2 | 246-247 | dispatch_label: Mapped[str] = mapped_column(String, default="claude-deck-ready", nullable=False) |
| `backend/app/models/schemas.py` | 2 | 2 | 2544-2545 | dispatch_label: str = "claude-deck-ready" |
| `backend/app/services/agent_bridge/discovery.py` | 6 | 6 | 25-30 | "CLAUDE_DECK_TEAM_PRESET_ID": "team_preset_id", |
| `backend/app/services/agent_bridge/spawn.py` | 1 | 1 | 107 | if extra_env and extra_env.get("CLAUDE_DECK_TEAM_SLOT_ID"): |
| `backend/app/services/agent_mail_install_service.py` | 23 | 26 | 34, 65, 111, 546-547, 563-564, 582-584, 610-611, 695, 776, 924-925, 950, 952, 995, 997, 1081, 1098, 1100 | MCP_SERVER_NAME = "claude-deck-mail" |
| `backend/app/services/agent_team_service.py` | 6 | 6 | 1001-1006 | "CLAUDE_DECK_TEAM_PRESET_ID": str(preset.id), |
| `backend/app/services/backup_service.py` | 1 | 1 | 73 | backup_dir = get_user_home() / ".claude-registry" / "backups" |
| `backend/app/services/github_approval_service.py` | 1 | 1 | 69 | _LEASE_HASH_DOMAIN = b"claude-deck:github-workspace-lease:v1\x00" |
| `backend/app/services/github_workspace_service.py` | 1 | 1 | 260 | return f"{slug}{suffix}@claude-deck.local" |
| `backend/app/services/instance_identity.py` | 4 | 4 | 79, 107, 110, 115 | return hashlib.sha256(f"claude-deck:{hostname}".encode("utf-8")).hexdigest()[:12] |
| `backend/app/services/mcp_service.py` | 2 | 2 | 600, 865 | "clientInfo": {"name": "claude-deck-test", "version": "1.0.0"}, |
| `backend/app/services/pi_mail_readiness.py` | 5 | 5 | 45-49 | "CLAUDE_DECK_MAIL_OPT_IN": "1", |
| `backend/app/services/providers/opencode_cli.py` | 1 | 1 | 39 | "agent_mail_plugin": str(home / "plugins" / "claude-deck-agent-mail.js"), |
| `backend/mcp_shim/agent_mail_hook.py` | 4 | 4 | 62, 64, 72-73 | parser.add_argument("--deck-url", default=os.environ.get("CLAUDE_DECK_URL", "http://127.0.0.1:8000")) |
| `backend/mcp_shim/agent_mail_server.py` | 8 | 8 | 13-14, 22, 182, 228, 247-248, 303 | DECK_URL = os.environ.get("CLAUDE_DECK_URL", "http://127.0.0.1:8000").rstrip("/") |
| `backend/mcp_shim/team_question_hook.py` | 1 | 1 | 8 | marker = os.environ.get("CLAUDE_DECK_TEAM_SLOT_ID", "") |
| `backend/tests/agent_mail/test_install.py` | 12 | 12 | 85, 125, 291, 293, 327, 349, 351, 365, 379, 381, 388, 527 | hooks_path = tmp_path / "claude-deck-mail.json" |
| `backend/tests/agent_mail/test_mcp_shim.py` | 9 | 9 | 78-79, 153, 357, 359, 925, 968, 1048-1049 | monkeypatch.setenv("CLAUDE_DECK_TEAM_PRESET_ID", "1") |
| `backend/tests/agent_mail/test_muse_install.py` | 2 | 2 | 30, 38 | assert doc["mcpServers"]["claude-deck-mail"]["transport"] == "stdio" |
| `backend/tests/agent_mail/test_pi_manifest.py` | 1 | 1 | 24 | monkeypatch.setenv("CLAUDE_DECK_PROVIDER", "pi-cli") |
| `backend/tests/agent_mail/test_pi_shim.py` | 1 | 1 | 93 | monkeypatch.setenv("CLAUDE_DECK_PROVIDER", provider) |
| `backend/tests/agent_mail/test_supervisor_shim.py` | 3 | 3 | 10, 19, 37 | monkeypatch.delenv("CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN", raising=False) |
| `backend/tests/agent_teams/test_agent_team_service.py` | 3 | 3 | 1533-1535 | assert calls[0][2]["CLAUDE_DECK_TEAM_PRESET_ID"] == str(preset.id) |
| `backend/tests/agent_teams/test_github_dispatch_scheduler.py` | 2 | 2 | 127, 663 | {"name": "claude-deck-ready"}, |
| `backend/tests/agent_teams/test_github_scope_models.py` | 2 | 2 | 46-47 | assert scope.dispatch_label == "claude-deck-ready" |
| `backend/tests/agent_teams/test_github_watcher_service.py` | 21 | 23 | 120, 130, 134, 290, 306, 316, 325, 352, 435, 480, 622, 657, 709, 742, 771, 835, 867, 901-902, 974-975 | "labels": [{"name": "claude-deck-ready"}], |
| `backend/tests/agent_teams/test_github_workspace_service.py` | 4 | 4 | 941, 943-944, 1175 | "backend-sme+slot12@claude-deck.local" |
| `backend/tests/factory/fixtures/v1-p04/manifest.json` | 1 | 1 | 28 | "source_repository": "juanrubio/claude-deck" |
| `backend/tests/factory/fixtures/v1/manifest.json` | 1 | 1 | 563 | "source_repository": "juanrubio/claude-deck", |
| `backend/tests/test_agent_bridge_attachments.py` | 19 | 19 | 78, 103, 107, 121, 127, 138, 149, 179, 189, 199, 208, 220, 233, 245, 264, 282, 300, 315, 325 | headers={"X-Claude-Deck-Terminal-Token": await _token(client)}, |
| `backend/tests/test_agent_bridge_discovery.py` | 6 | 6 | 57-62 | "CLAUDE_DECK_TEAM_PRESET_ID=10", |
| `backend/tests/test_agent_bridge_spawn.py` | 14 | 14 | 50, 52, 66, 80, 86, 108-109, 505, 508, 529, 532, 566, 582, 604 | project_dir = tmp_path / "claude-deck" |
| `backend/tests/test_instance_identity.py` | 15 | 15 | 13-15, 30-32, 49-50, 64, 74, 93, 106-107, 120, 128 | monkeypatch.setenv("CLAUDE_DECK_INSTANCE_NAME", "Studio Mac") |
| `backend/tests/test_pi_mail_ancestry.py` | 4 | 5 | 73-76 | "CLAUDE_DECK_MAIL_OPT_IN": "1", "CLAUDE_DECK_PROVIDER": "pi-cli", |
| `backend/tests/test_pi_provider.py` | 2 | 2 | 132-133 | assert "CLAUDE_DECK_MAIL_OPT_IN=1" in captured[0] |
| `docs/package-lock.json` | 2 | 2 | 2, 8 | "name": "claude-deck-docs", |
| `docs/package.json` | 1 | 1 | 2 | "name": "claude-deck-docs", |
| `frontend/e2e/g0/isolation.spec.ts` | 4 | 4 | 27, 141, 147, 158 | if (!key.startsWith('CLAUDE_DECK_')) env[key] = value |
| `frontend/e2e/lane-c/support.ts` | 1 | 1 | 7 | const KEY_STORAGE = 'claude-deck.agent-teams.operator-token' |
| `frontend/e2e/lane-c/unlock.spec.ts` | 1 | 1 | 9 | const KEY_STORAGE = 'claude-deck.agent-teams.operator-token' |
| `frontend/e2e/lane-d/harness-mail-setup.spec.ts` | 1 | 1 | 34 | \|\| !await page.evaluate(() => sessionStorage.getItem('claude-deck.agent-teams.operator-token'))) { |
| `frontend/src/contexts/ProviderContext.tsx` | 1 | 1 | 16 | const STORAGE_KEY = 'claude-deck:selected-provider' |
| `frontend/src/features/agent-teams/ScopeSettingsDialogs.tsx` | 4 | 4 | 104-105, 194-195 | dispatch_label: 'claude-deck-ready', |
| `frontend/src/features/agent-teams/operatorAuth.ts` | 1 | 1 | 1 | const OPERATOR_TOKEN_KEY = 'claude-deck.agent-teams.operator-token' |
| `frontend/src/features/cc-bridge/api.ts` | 1 | 1 | 43 | headers.set('X-Claude-Deck-Terminal-Token', token) |
| `frontend/src/features/factory/RepositorySetupPage.tsx` | 1 | 2 | 43 | owner: "", repo: "", path: "", dispatch: "claude-deck-ready", design: "claude-deck-design", baseRef: "origin/HEAD", |
| `frontend/src/features/native-settings/surfaceRegistry.tsx` | 1 | 1 | 195 | : (window.localStorage.getItem("claude-deck:selected-provider") ?? |
| `frontend/tests/activity-feed.test.tsx` | 5 | 5 | 18, 31, 60-61, 64 | context_snapshot: { team_display_name: "Release crew", repo_owner: "adrirubio", repo_name: "claude-deck", issue_number: 101 }, |
| `frontend/tests/agent-mail-roster.test.tsx` | 3 | 3 | 42, 109, 112 | member(4, 'claude-deck', null, { participant_kind: 'repo', role: null, charter: null, sessions: [session(4, { provider: 'codex-cli' })] }), |
| `frontend/tests/audit-feed.test.ts` | 3 | 3 | 22, 33, 64 | context_snapshot: { team_display_name: "Release crew", repo_owner: "adrirubio", repo_name: "claude-deck", issue_number: 101 }, |
| `frontend/tests/audit-refusals.test.ts` | 2 | 2 | 27, 69 | context_snapshot: { repo_name: "claude-deck-website", issue_number: 2 }, |
| `frontend/tests/autonomy-browser.mjs` | 1 | 1 | 180 | await send('Page.addScriptToEvaluateOnNewDocument',{source:'localStorage.setItem('theme',${JSON.stringify(theme)});sessionStorage.setItem('claude-deck… |
| `frontend/tests/autonomy-panel.test.tsx` | 2 | 2 | 51-52 | dispatch_label: 'claude-deck-ready', |
| `frontend/tests/factory.test.tsx` | 2 | 2 | 90-91 | localStorage.setItem("claude-deck:selected-provider", "pi-cli"); |
| `frontend/tests/fixture-browser.mjs` | 3 | 3 | 413, 443, 546 | if (name === "legacy-mismatch") await evaluate('localStorage.setItem("claude-deck:selected-provider", "codex-cli")'); |
| `frontend/tests/fixtures/factory/v1-p04/manifest.json` | 1 | 1 | 28 | "source_repository": "juanrubio/claude-deck" |
| `frontend/tests/fixtures/factory/v1/manifest.json` | 1 | 1 | 563 | "source_repository": "juanrubio/claude-deck", |
| `frontend/tests/native-context.test.tsx` | 6 | 6 | 101, 111, 145, 162, 167, 181 | localStorage.setItem('claude-deck:selected-provider','codex-cli') |
| `frontend/tests/navigation-affordances.test.tsx` | 4 | 4 | 33, 43, 87, 101 | localStorage.setItem('claude-deck:selected-provider', 'pi-cli') |
| `frontend/tests/needs-a-look.test.tsx` | 7 | 7 | 17, 28, 30, 50-51, 130-131 | context_snapshot: { repo_name: "claude-deck-website", issue_number: 2 }, |
| `frontend/tests/provider-operations.test.tsx` | 6 | 6 | 58, 68, 98, 105, 119, 139 | localStorage.setItem('claude-deck:selected-provider','pi-cli') |
| `frontend/tests/repository-pages.test.tsx` | 1 | 2 | 25 | dispatch_label: "claude-deck-ready", design_label: "claude-deck-design", merge_policy: "human", |
| `frontend/tests/repository-settings.test.tsx` | 2 | 2 | 43-44 | dispatch_label: 'claude-deck-ready', |
| `frontend/tests/repository-setup.test.tsx` | 30 | 35 | 224, 309, 369, 391, 425, 450, 492, 516, 555, 636, 658, 678, 743, 768-769, 790, 899, 1095, 1189, 1322, 1381, 1448, 1486, 1501, 1528, 1553, 1629, 1718-1719, 1734 | dispatch_label: "claude-deck-ready", design_label: "claude-deck-design", base_ref: "origin/HEAD", |
| `frontend/tests/terminal-authority.test.ts` | 1 | 1 | 47 | expect(request.mock.calls[1][1].headers.get('X-Claude-Deck-Terminal-Token')).toBe('attachment-grant') |
| `integrations/pi-agent-mail/client.ts` | 7 | 9 | 58-59, 88, 91, 139, 153-154 | 'CLAUDE_DECK_URL', 'CLAUDE_DECK_TEAM_PRESET_ID', 'CLAUDE_DECK_TEAM_SLOT_ID'] |
| `integrations/pi-agent-mail/extension.ts` | 1 | 1 | 8 | if (process.env.CLAUDE_DECK_MAIL_OPT_IN !== '1') return |
| `integrations/pi-agent-mail/package-lock.json` | 2 | 2 | 2, 7 | "name": "claude-deck-pi-agent-mail", |
| `integrations/pi-agent-mail/package.json` | 1 | 1 | 2 | "name": "claude-deck-pi-agent-mail", |
| `integrations/pi-agent-mail/readiness.mjs` | 1 | 1 | 14 | delete process.env.CLAUDE_DECK_MAIL_OPT_IN |
| `integrations/pi-agent-mail/sync_manifest.py` | 1 | 1 | 15 | os.environ["CLAUDE_DECK_PROVIDER"] = "pi-cli" |
| `integrations/pi-agent-mail/tests/client.test.ts` | 5 | 5 | 16-17, 24-25, 27 | CLAUDE_DECK_MAIL_PYTHON: process.execPath, |
| `integrations/pi-agent-mail/tests/extension-activity.test.ts` | 4 | 4 | 19-21, 82 | DECK_TEST_PANE_PID: String(process.pid), CLAUDE_DECK_MAIL_OPT_IN: '1', |
| `integrations/pi-agent-mail/tests/pi-runtime.test.ts` | 8 | 8 | 16-17, 51-52, 57-58, 79-80 | const previous = process.env.CLAUDE_DECK_MAIL_OPT_IN |
| `scripts/deploy-docs.sh` | 1 | 1 | 7 | WEBSITE_DIR="$REPO_ROOT/../claude-deck-website" |
| `scripts/e2e-agent-mail-same-repo-codex.sh` | 3 | 3 | 31-32, 88 | INBOX_NUDGE_PREFIX='Claude Deck Agent Mail: please call 'deck_check_inbox' |
| `scripts/e2e-instance.sh` | 6 | 8 | 50, 54, 130, 169, 201, 229 | if [[ -n "${CLAUDE_DECK_URL:-}" && "$CLAUDE_DECK_URL" != "$INSTANCE_URL" ]]; then |
| `scripts/e2e/scenarios.py` | 6 | 6 | 618-623 | "CLAUDE_DECK_TEAM_PRESET_ID": str(RELEASE_TEAM), |
| `scripts/generate-pi-mail-manifest.py` | 4 | 4 | 15-16, 21, 23 | previous = os.environ.get("CLAUDE_DECK_PROVIDER") |
| `scripts/install.sh` | 1 | 1 | 81 | mkdir -p ~/.claude-registry/backups |
| `scripts/product-factory/agent-tmux` | 2 | 5 | 4-5 | env={'HOME':u.pw_dir,'USER':u.pw_name,'LOGNAME':u.pw_name,'PATH':'/opt/claude-deck-product/agent-bin:/opt/claude-deck-product/tools:/usr/bin:/bin','LA… |
| `scripts/product-factory/claude-deck-product-supervisor-failure.service` | 1 | 1 | 5 | ExecStart=/usr/bin/python3 -c "import runpy; m=runpy.run_path('/opt/claude-deck-product/libexec/product-supervisor'); m['pause']('supervisor_failure')… |
| `scripts/product-factory/claude-deck-product-supervisor.service` | 3 | 3 | 3-4, 7 | After=claude-deck-product.service |
| `scripts/product-factory/claude-deck-product-supervisor.timer` | 1 | 1 | 7 | Unit=claude-deck-product-supervisor.service |
| `scripts/product-factory/claude-deck-product-tmux.service` | 2 | 3 | 10-11 | Environment=PATH=/opt/claude-deck-product/agent-bin:/opt/claude-deck-product/tools:/usr/bin:/bin |
| `scripts/product-factory/claude-deck-product.service` | 6 | 7 | 3-4, 10-13 | After=network.target claude-deck-product-tmux.service |
| `scripts/product-factory/controller-tmux` | 1 | 1 | 2 | exec /usr/bin/sudo -n -u deckproduct /opt/claude-deck-product/libexec/agent-tmux "$@" |
| `scripts/product-factory/product-supervisor` | 3 | 3 | 4, 49, 118 | BASE=pathlib.Path('/opt/claude-deck-product'); OPS=pathlib.Path('/home/deckproductctl/work/operations'); STATE=BASE/'state'; API='http://127.0.0.1:801… |
| `scripts/product-factory/productctl` | 4 | 4 | 4, 32, 46, 61 | BASE=pathlib.Path('/opt/claude-deck-product');STATE=BASE/'state';WORK=pathlib.Path('/home/deckproductctl/work');URL='http://127.0.0.1:8011';ENV=BASE/'… |

### 4.2 User-facing copy — 170 lines, 174 occurrences, 53 files

Current copy a person or an agent reads as the product speaking. These lines take the new product name directly; none of them is a compatibility surface by itself, although tests that assert the visible title appear here because they pin this copy.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `.github/workflows/release.yml` | 1 | 1 | 142 | name: Claude Deck v${{ inputs.version }} |
| `README.md` | 13 | 13 | 1, 9, 23, 89, 101, 110, 156, 174, 203, 205, 207, 231, 278 | # Claude Deck |
| `backend/app/config.py` | 1 | 1 | 16 | app_name: str = "Claude Deck" |
| `backend/app/services/agent_mail_install_service.py` | 2 | 2 | 1084-1085 | "## Claude Deck Agent Mail\n" |
| `backend/app/services/agent_mail_service.py` | 2 | 2 | 87, 2635 | "Claude Deck Agent Mail: call 'deck_check_inbox(unread_only=False)' now. " |
| `backend/app/services/agent_team_service.py` | 1 | 1 | 1696 | f'You are being started by Claude Deck as part of Agent Team "{preset.name}".', |
| `backend/app/services/codex_history_service.py` | 1 | 1 | 42 | "Claude Deck summarizes structure only until stable non-sensitive history " |
| `backend/app/services/github_approval_service.py` | 2 | 2 | 884, 900 | "Claude Deck approved continuation: call " |
| `backend/app/services/github_dispatch_service.py` | 7 | 7 | 1377, 1380, 1401, 1446, 1508, 1883, 3289 | body = f"{body[:12000]}\n\n[Issue body truncated by Claude Deck.]" |
| `backend/app/services/github_verification_service.py` | 1 | 1 | 571 | "Claude Deck provenance\n" |
| `backend/app/services/instance_identity.py` | 1 | 1 | 95 | "Unsupported CLAUDE_DECK_INSTANCE_ACCENT=%r; using hostname-derived accent", |
| `backend/app/services/oauth_service.py` | 1 | 1 | 128 | "client_name": f"Claude Deck - {server_name}", |
| `backend/app/services/runtime_environment.py` | 1 | 1 | 10 | "No agent CLIs detected. Claude Deck must run in the same environment where " |
| `backend/mcp_shim/agent_mail_server.py` | 7 | 7 | 53, 119, 224, 358, 386, 885, 1182 | "suggestion": "Continue without mailbox coordination, or ask the user to start Claude Deck.", |
| `backend/mcp_shim/git_credential_helper.py` | 3 | 3 | 45, 50, 66 | raise RuntimeError(f"Claude Deck refused credential request ({response.status})") |
| `backend/pyproject.toml` | 1 | 1 | 4 | description = "Backend API for Claude Deck" |
| `backend/tests/agent_teams/test_github_verification_service.py` | 1 | 1 | 1493 | "Claude Deck provenance\n" |
| `docs/.vitepress/config.ts` | 7 | 7 | 4-5, 19, 27, 111, 119, 125 | title: 'Claude Deck', |
| `docs/index.md` | 2 | 2 | 4, 13 | name: Claude Deck |
| `frontend/e2e/g0/isolation.spec.ts` | 3 | 3 | 143, 177, 189 | expect(stderr).toContain('CLAUDE_DECK_URL names another Deck') |
| `frontend/e2e/g1/identity.spec.ts` | 1 | 1 | 35 | await expect(page).toHaveTitle('Claude Deck') |
| `frontend/e2e/lane-f/navigation.spec.ts` | 1 | 1 | 61 | expect(titles.filter(title => title === 'Claude Deck'), 'no page keeps the bare app title').toEqual([]) |
| `frontend/index.html` | 1 | 1 | 9 | <title>Claude Deck</title> |
| `frontend/src/components/layout/Footer.tsx` | 2 | 2 | 5, 7 | <span>Claude Deck v{APP_VERSION}</span> |
| `frontend/src/components/layout/Header.tsx` | 3 | 3 | 27, 43, 47 | 'Claude Deck instance: ${instance.name}', |
| `frontend/src/features/agent-mail/AgentMailHelpDialog.tsx` | 3 | 3 | 43, 65, 82 | Agent Mail only works after each agent type has the Claude Deck mail MCP server. |
| `frontend/src/features/agent-mail/AgentMailPage.tsx` | 1 | 1 | 340 | : 'Start or resume an agent in a repository, then have it call deck_whoami once so Claude Deck can attach it to a participant.'} |
| `frontend/src/features/agent-mail/ComposeDialog.tsx` | 2 | 2 | 86, 91 | : '${member.display_name} is offline. This message will be stored for later; Claude Deck cannot wake a live session.' |
| `frontend/src/features/agent-mail/actorAuth.ts` | 1 | 1 | 43 | description: 'Claude Deck browser session', |
| `frontend/src/features/agent-mail/mailSetup.ts` | 19 | 23 | 193, 218, 220, 228, 230, 237, 239-240, 247, 249-250, 256, 258, 266, 268, 274, 277, 284, 287 | const server = 'claude-deck-mail' |
| `frontend/src/features/agent-teams/AgentTeamsHelpDialog.tsx` | 1 | 1 | 100 | <p><a href="https://github.com/adrirubio/claude-deck/blob/master/docs/autonomy.md" target="_blank" rel="noreferrer" className="text-primary underline"… |
| `frontend/src/features/agent-teams/OperatorTokenDialog.tsx` | 1 | 1 | 13 | const INSTALLATION_GUIDE_URL = 'https://github.com/adrirubio/claude-deck/blob/master/docs/guide/installation.md' |
| `frontend/src/features/cc-bridge/CCBridgePage.tsx` | 1 | 1 | 430 | {agentCliWarning} Run Claude Deck natively on the host where Claude Code, Codex, Copilot, or OpenCode are installed. |
| `frontend/src/features/cc-bridge/ImageAttachmentDialog.tsx` | 1 | 1 | 61 | Uploads the image to this Claude Deck host. Pasting its file-path prompt into {targetLabel} requires interactive mode and the Deck operator token. |
| `frontend/src/features/factory/auditSummary.ts` | 1 | 1 | 8 | export const GUIDE_URL = "https://github.com/adrirubio/claude-deck/blob/master/docs/guide/factory-audit-and-metrics.md"; |
| `frontend/src/features/harnesses/HarnessesPage.tsx` | 2 | 2 | 154, 252 | useDocumentTitle('${harnesses[id]} · Claude Deck'); |
| `frontend/src/features/native-settings/NativeRoute.tsx` | 1 | 1 | 71 | useDocumentTitle(pageName && metadata ? '${pageName} · ${harnessName} · Claude Deck' : null); |
| `frontend/src/hooks/useInstanceDocumentTitle.ts` | 1 | 1 | 5 | const BASE_TITLE = 'Claude Deck' |
| `frontend/tests/agent-mail-setup.test.tsx` | 1 | 1 | 122 | expect(mailConfirm('codex-cli', 'remove', status()).mutations[0]).toBe('Codex CLI: run 'codex mcp remove claude-deck-mail'') |
| `frontend/tests/audit-feed.test.ts` | 3 | 3 | 39-41 | ["Deck", "delivered", "adrirubio/claude-deck #101"], |
| `frontend/tests/audit-refusals.test.ts` | 2 | 2 | 73, 75 | expect(newest.itemLabel).toBe("claude-deck #492"); |
| `frontend/tests/instance-document-title.test.tsx` | 5 | 5 | 23, 28, 37, 39, 46 | expect(document.title).toBe("Claude Deck"); |
| `frontend/tests/needs-a-look.test.tsx` | 1 | 1 | 66 | expect(screen.getByRole("link", { name: "Open claude-deck-website #2" })).toHaveAttribute("href", "/work/7"); |
| `frontend/tests/provider-operations.test.tsx` | 2 | 2 | 163, 170 | expect(document.title).toBe('Configuration · Codex CLI · Claude Deck') |
| `integrations/pi-agent-mail/manifest.ts` | 4 | 4 | 430, 439, 739, 1301 | "description": "List all local Agent Mail participants Claude Deck knows about, including member\n ids, display names, roles, repos, team slots, chart… |
| `launch-posts.md` | 38 | 38 | 1, 9, 58, 61, 72, 94, 107, 111, 130, 139-141, 144, 148, 166, 180, 183, 210, 219, 223, 236, 242, 245, 261, 271, 274, 278, 285, 300, 323, 334, 344, 350, 353, 368, 372, 379, 389 | # Claude Deck Launch Posts |
| `scripts/build.sh` | 1 | 1 | 10 | echo "Building Claude Deck for production..." |
| `scripts/deploy-docs.sh` | 1 | 1 | 10 | echo "Error: claude-deck-website not found at $WEBSITE_DIR" |
| `scripts/dev.sh` | 5 | 5 | 24, 162, 166, 170, 232 | stop Stop Claude Deck dev servers for this checkout |
| `scripts/e2e-agent-mail-same-repo-codex.sh` | 3 | 3 | 230, 237, 252 | "You are the planner in an automated Claude Deck Agent Mail E2E test. " + |
| `scripts/e2e-instance.sh` | 1 | 1 | 51 | refuse "CLAUDE_DECK_URL names another Deck; unset it to run the E2E instance" |
| `scripts/install.sh` | 1 | 1 | 10 | echo "Setting up Claude Deck..." |
| `scripts/product-factory/claude-deck-product.service` | 1 | 1 | 2 | Description=Isolated Claude Deck product factory |

### 4.3 Docs — 156 lines, 171 occurrences, 46 files

Manuals, guides, comments, internal docstrings and test descriptions. These rename as ordinary documentation once #789 fixes the identifier vocabulary they describe; examples that must keep old-install instructions usable are a #792/#789 wording decision, not an inventory question.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `.gitignore` | 1 | 1 | 60 | # Claude Deck specific |
| `CHANGELOG.md` | 2 | 2 | 3, 224 | All notable changes to Claude Deck will be documented in this file. |
| `CLAUDE.md` | 4 | 4 | 1, 68, 94, 98 | # Claude Deck |
| `CONTRIBUTING.md` | 4 | 4 | 1, 9-10, 38 | # Contributing to Claude Deck |
| `DOCUMENTATION_PUBLISHING.md` | 34 | 39 | 9-10, 17, 19-20, 27, 30-31, 41-42, 48, 52, 56, 61, 72-73, 79, 83, 88-90, 95, 102, 110, 114-116, 119, 126-127, 134, 138-139, 142 | \| 'claude-deck' \| Markdown content in 'docs/', VitePress configuration and assets, and the build/copy scripts \| |
| `README.md` | 5 | 5 | 37, 168-169, 210-211 | Green boxes are planned for v3.1 ([#506](https://github.com/adrirubio/claude-deck/issues/506)). See the [Factory operating model](docs/guide/operating… |
| `backend/app/api/v1/plugins.py` | 1 | 1 | 2 | Plugin API endpoints for Claude Deck |
| `backend/app/models/schemas.py` | 1 | 1 | 1796 | """Runtime identity for the Claude Deck backend instance.""" |
| `backend/app/services/instance_identity.py` | 1 | 1 | 1 | """Runtime identity metadata for this Claude Deck backend instance.""" |
| `backend/app/services/plugin_service.py` | 1 | 1 | 2 | Plugin Service for Claude Deck |
| `backend/app/services/runtime_environment.py` | 1 | 1 | 16 | """Return True when Claude Deck appears to be running in a container.""" |
| `backend/mcp_shim/agent_mail_hook.py` | 1 | 1 | 1 | """Claude Deck Agent Mail lifecycle hook shim.""" |
| `backend/mcp_shim/agent_mail_server.py` | 1 | 1 | 1 | """Claude Deck Agent Mail MCP server over stdio.""" |
| `backend/mcp_shim/git_credential_helper.py` | 1 | 1 | 1 | """Git credential helper that requests a short-lived token from Claude Deck.""" |
| `docs/api/agent-bridge.md` | 7 | 8 | 80, 82, 87, 103-104, 110, 129 | Use image attachments to upload a screenshot or mockup to the Claude Deck host, then paste a file-path prompt into a live tmux session. |
| `docs/api/agent-mail.md` | 1 | 1 | 179 | Actor creation is loopback-only. External endpoints require a bearer token and are intended for Claude Deck's local trust boundary, not internet-facin… |
| `docs/api/index.md` | 1 | 1 | 3 | Claude Deck exposes a RESTful API under '/api/v1/'. The frontend communicates with the backend entirely through this API. |
| `docs/changelog.md` | 3 | 3 | 3, 21, 176 | All notable changes to Claude Deck are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). |
| `docs/deploy/product-lane-b-factory.md` | 9 | 9 | 7, 9-10, 12, 23-26, 29 | - Repository: 'juanrubio/claude-deck'; tracker #3. Fork issues #4–#14 map to upstream #410–#417 and #364–#366. |
| `docs/features/agent-mail.md` | 9 | 9 | 3, 57, 85, 87, 93, 103, 115-116, 121 | Agent Mail lets local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions coordinate as a user-directed team. Claude Deck keeps … |
| `docs/features/agent-teams.md` | 2 | 2 | 173, 177 | 'From Bridge' uses live Agent Bridge tmux sessions. If multiple sessions are visible for the same repo, Claude Deck keeps each session as a separate s… |
| `docs/features/backup.md` | 2 | 2 | 38, 49 | Codex backups are export-only. The restore plan can show archive contents and explain why automatic restore is refused, but Claude Deck does not extra… |
| `docs/features/commands.md` | 1 | 1 | 7 | Slash commands are markdown files that Claude Code executes when you type '/command-name'. Claude Deck lets you browse all available commands across u… |
| `docs/features/config.md` | 3 | 3 | 63, 78, 95 | The Config page reads and writes to the standard Claude Code configuration files. No additional Claude Deck configuration is needed. |
| `docs/features/external-agent-orchestration.md` | 3 | 3 | 3, 42-43 | Claude Deck exposes a local Agent Mail API for tools such as OpenClaw to coordinate installed agents without pretending to be a repo agent or a UI use… |
| `docs/features/harnesses.md` | 1 | 1 | 25 | - **Agent Mail:** **Set up** on the Muse Code page writes the user-wide settings file '~/.config/muse/settings.json' (or '$MUSE_CONFIG_DIR/settings.js… |
| `docs/features/memory.md` | 1 | 1 | 68 | Memory files are standard markdown. No special Claude Deck configuration needed — the Memory page reads and writes directly to the filesystem. |
| `docs/features/sessions.md` | 1 | 1 | 40 | Claude Deck caches parsed sessions in its database with a 5-minute TTL and file hash validation for fast page loads. |
| `docs/features/usage.md` | 1 | 1 | 51 | Claude Deck caches parsed usage data in localStorage with a 5-minute TTL for instant page loads on return visits. |
| `docs/guide/architecture.md` | 3 | 3 | 3, 53, 59 | Claude Deck is a full-stack application with a Python backend and React frontend. |
| `docs/guide/contributing.md` | 4 | 4 | 3, 10-11, 62 | Thanks for your interest in contributing to Claude Deck! We welcome pull requests and issues from everyone. |
| `docs/guide/installation.md` | 17 | 23 | 3, 5, 33-34, 51, 57, 71, 75, 79, 82, 93, 101, 103-104, 110, 114, 118 | Claude Deck must run in the same environment where your agent CLIs and credentials are installed. Docker is not supported because containers cannot se… |
| `docs/guide/multi-provider-codex-v2.md` | 2 | 2 | 3, 66 | Claude Deck supports mixed local harness workflows with separate factory observations, native adapters and provider APIs. Codex includes sessions, saf… |
| `docs/guide/operating-model.md` | 4 | 5 | 5, 8, 75, 123 | Select a figure to open it at full size. Parts marked **Planned (v3.1)** come from proposal [#506](https://github.com/adrirubio/claude-deck/issues/506… |
| `docs/guide/quick-start.md` | 4 | 4 | 44, 47-49 | When you run Claude Deck on more than one machine, or expose it over a LAN or tailnet, set an instance name so each browser window clearly shows the b… |
| `docs/guide/supervised-factory-playbook.md` | 5 | 6 | 236, 329, 463, 510, 521 | The installed Claude 'PreToolUse' hook refuses 'AskUserQuestion' only in Deck team sessions. It checks 'CLAUDE_DECK_TEAM_SLOT_ID'. |
| `frontend/e2e/README.md` | 2 | 3 | 21, 42 | 3. It runs the seed, the backend and tmux with an allowlisted environment ('env -i'). 'PATH' is the fake binaries and the system directories only. 'CL… |
| `frontend/e2e/g1/identity.spec.ts` | 3 | 3 | 4-5, 32 | // is "Claude Deck" unless a name is configured. The E2E instance sets no |
| `frontend/src/features/config/settings/cards/ManagedPolicyCard.tsx` | 1 | 1 | 8 | * read-only. Claude Deck is not a policy authoring tool; this card exists so |
| `frontend/src/types/status.ts` | 1 | 1 | 16 | // True only when the operator set CLAUDE_DECK_INSTANCE_NAME. |
| `frontend/tests/agent-teams-help-dialog.test.tsx` | 1 | 1 | 17 | 'https://github.com/adrirubio/claude-deck/blob/master/docs/autonomy.md', |
| `frontend/tests/instance-document-title.test.tsx` | 2 | 2 | 21, 26 | it("stays Claude Deck when no name is configured", () => { |
| `frontend/tests/repository-setup.test.tsx` | 1 | 1 | 1749 | fireEvent.change(screen.getByLabelText("GitHub repository"), { target: { value: "https://github.com/adrirubio/claude-deck-docs" } }); |
| `frontend/tests/team-summary-card.test.tsx` | 1 | 1 | 28 | const ISSUE = 'https://github.com/adrirubio/claude-deck/issues/490' |
| `scripts/e2e-agent-mail-same-repo-codex.sh` | 1 | 1 | 7 | # - Claude Deck backend running on DECK_URL, default http://127.0.0.1:8000 |
| `scripts/e2e-instance.sh` | 1 | 1 | 15 | # - CLAUDE_DECK_URL, or a Deck Mail token variable, names another Deck; |

### 4.4 History to keep — 893 lines, 983 occurrences, 95 files

Dated plans and released changelog entries: kept as written. The rename does not rewrite these records; at most, campaign-level pointers may be added outside them by a separate decision. The changelog preamble and the `[Unreleased]`/full-changelog pointer lines are maintained with the current tree, so they sit in docs (`CHANGELOG.md:3`, `CHANGELOG.md:224`, `docs/changelog.md:3`, `docs/changelog.md:21`, `docs/changelog.md:176`) rather than here.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `CHANGELOG.md` | 11 | 11 | 58, 61, 125, 206, 225-231 | - **Product positioning**: Claude Deck is a self-hosted workspace to observe and intervene in bounded coding-agent attempts on GitHub issues, with mix… |
| `docs/changelog.md` | 1 | 1 | 157 | - Initial release of Claude Deck |
| `docs/deploy/attempt-recovery-pr1-rollout.md` | 8 | 9 | 12, 18-19, 28, 53, 80, 134-135 | 'sqlite+aiosqlite:///./claude_registry.db'. |
| `docs/deploy/attempt-recovery-pr2-rollout.md` | 1 | 1 | 29 | sqlite3 -header -column claude_registry.db <<'SQL' |
| `docs/deploy/attempt-recovery-pr3-rollout.md` | 5 | 6 | 25-27, 158-159 | sqlite3 claude_registry.db ".backup 'claude_registry.pre-attempt-recovery-pr3.db'" |
| `docs/deploy/attempt-recovery-soak-log-2026-09-29.md` | 1 | 1 | 136 | Follow-up: [Deck issue #359](https://github.com/adrirubio/claude-deck/issues/359). |
| `docs/deploy/codex-soak-handoff.md` | 4 | 5 | 1, 6, 52, 92 | You are taking over execution of the claude-deck soak deployment schedule from the |
| `docs/deploy/pi-provider-rollout.md` | 2 | 4 | 34, 46 | Without 'CLAUDE_DECK_MAIL_OPT_IN=1', the extension registers no tools/listeners or transport. Deck launches supply non-secret opt-in, Python/shim path… |
| `docs/deploy/pi-provider-validation.md` | 1 | 1 | 3 | Issue #357. Baseline: '2a51da44b634319644b4147b65764bdb7311936a'. Implementation branch: 'feature/pi-provider'; target: 'feature/autonomous-github-dis… |
| `docs/deploy/soak-resume-runbook.md` | 8 | 9 | 3, 80, 108, 181, 222, 227-228, 421 | **Status: G0 through G6 passed. G5 resolved the Tizonia scope to GitHub App mode, pushed with a repository-scoped installation credential, created PR … |
| `docs/plans/2026-02-07-mcp-page-enhancements-design.md` | 2 | 2 | 69, 182 | **Note**: Delete 'backend/claude_registry.db' after schema changes (no migration system). |
| `docs/plans/2026-03-05-http-hooks-integration-design.md` | 5 | 7 | 1, 5, 7, 48, 86 | # HTTP Hooks Integration for Claude Deck |
| `docs/plans/2026-03-06-agent-orchestration-design.md` | 3 | 4 | 11, 42, 300 | Claude Deck today is a monitoring dashboard for Claude Code sessions. This document proposes evolving it into a **full agent orchestration platform** … |
| `docs/plans/2026-03-08-presence-status-accuracy.md` | 2 | 2 | 10, 88 | - **5 of 8 cards are nearly empty** — openclaw, both nano-banana-pipelines, claude-deck, and linode-migration show only a tiny activity sparkline with… |
| `docs/plans/2026-03-20-new-settings-surface.md` | 1 | 1 | 1 | # New Claude Code Settings — Surface in Claude Deck |
| `docs/plans/2026-04-10-settings-gap-update-plan.md` | 1 | 1 | 5 | Claude-deck's settings editor (last updated 2026-03-20) is missing settings that Claude Code has added since: Auto Mode, Plugins/Marketplaces, Sandbox… |
| `docs/plans/2026-05-25-codex-cli-support.html` | 7 | 10 | 6, 14, 17, 24, 79, 560, 564 | <title>Codex CLI Support Across Claude Deck</title> |
| `docs/plans/2026-05-25-codex-cli-support.md` | 6 | 8 | 1, 9, 16, 81, 603, 607 | # Codex CLI Support Across Claude Deck |
| `docs/plans/2026-05-26-codex-backup-restore-policy.md` | 2 | 2 | 8, 42 | Codex backups are export-only. Claude Deck may create and download a redacted |
| `docs/plans/2026-05-26-codex-cli-v2-plan.md` | 3 | 3 | 12, 294, 351 | v1 proved the architecture: Claude Deck can detect, configure, launch, diagnose, and back up Codex CLI alongside Claude Code. v2 should close the deli… |
| `docs/plans/2026-10-11-v3.1-director-ui/director-ui-mockup.html` | 48 | 58 | 5, 344, 371, 399, 518, 520, 522, 524, 531, 533, 535, 573, 586, 590, 601, 651, 656, 660, 675, 682, 689, 703, 705, 709, 743-750, 754, 759, 766, 814, 822-824, 828, 830, 834, 845, 874, 883, 888, 917, 927 | <title>Claude Deck — Overview mockup (#507–#513)</title> |
| `docs/plans/2026-10-11-v3.1-director-ui/factory-operation-explainer.html` | 2 | 2 | 5, 119 | <title>How a Claude Deck factory is operated (#506, simplified)</title> |
| `docs/plans/2026-10-15-director-website/01-audit.md` | 13 | 15 | 29, 59, 69, 75, 115, 174, 184, 236-241 | - Instance evidence: 'GET http://127.0.0.1:18765/health' returns '{"name":"Claude Deck","version":"3.1.0","status":"running"}'. It shows the tested so… |
| `docs/plans/2026-11-06-rename-synth-city/README.md` | 12 | 15 | 1, 7, 16-17, 25-26, 36-39, 61, 78 | # Rename: Claude Deck → Albiex Synth City |
| `docs/plans/2026-11-06-rename-synth-city/transfer-runbook.md` | 30 | 31 | 1, 16-17, 46-47, 173, 212, 214, 224-225, 227, 265, 281, 298, 304, 306, 321, 334, 475, 512, 605, 614, 677, 785, 837, 855, 863, 912, 914, 917 | # Repository transfer runbook: Claude Deck → Synth City |
| `docs/plans/2026-11-06-rename-synth-city/website-and-docs.md` | 29 | 37 | 57-58, 98, 126, 374-375, 384, 386-387, 395, 403, 432, 434, 473, 551, 577, 627, 631-632, 677, 793, 861, 866-867, 871, 882, 885-887 | \| **[product]** \| 'adrirubio/claude-deck' (becomes 'albiexai/synth-city') \| 'c4daece7b300e2d07b884a75adf6ef8f99950389' \| |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-implementation-plan.md` | 26 | 27 | 7, 1288, 1918, 1936, 1941-1942, 1977, 2052-2053, 2073, 2076-2077, 2204, 2208, 2218-2219, 2222, 2241, 2287, 2302, 2464, 3206-3207, 3476-3477, 3481 | **Architecture:** Claude Deck's backend owns all coordination state in SQLite (4 new tables). Agents interact through (a) a standalone MCP stdio shim … |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-review-for-patching.md` | 2 | 2 | 145, 201 | - Codex MCP install uses 'CLAUDE_DECK_PROVIDER=codex-cli'. |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v3-implementation-plan.md` | 36 | 37 | 7, 1374, 2011, 2033, 2052-2053, 2060-2061, 2103, 2224-2225, 2252-2253, 2276, 2279-2280, 2439, 2443, 2453-2454, 2457, 2476, 2522, 2537, 2700, 3550-3551, 3573, 3591, 3632, 3649, 3922-3923, 3927, 3929, 3938 | **Architecture:** Claude Deck's backend owns all coordination state in SQLite (4 new tables). Agents interact through (a) a standalone MCP stdio shim … |
| `docs/plans/agent-mail/2026-06-13-presence-feature-usability-review.md` | 3 | 3 | 21, 25, 81 | **Decision:** Demote Presence from the primary Claude Deck sidebar now and remove the Presence-derived active-session badge from the top header. Initi… |
| `docs/plans/agent-mail/2026-06-14-codex-app-server-wakeups-implementation-plan.md` | 13 | 14 | 3, 5, 12, 16, 79, 98, 154, 180, 236, 256, 478, 698, 729 | **Issue:** [#185](https://github.com/adrirubio/claude-deck/issues/185) |
| `docs/plans/agent-mail/2026-06-15-agent-team-presets-implementation-plan.md` | 16 | 16 | 4, 9, 80-81, 83, 152, 517, 519, 556-559, 565, 577-578, 598 | Issue: https://github.com/adrirubio/claude-deck/issues/189 |
| `docs/plans/agent-mail/agent_mailbox_alternate_direction_evaluation.md` | 15 | 16 | 3-4, 12, 29, 51, 53, 61, 70, 108, 200, 353, 466, 490, 497, 500 | **Companion document to:** 'claude_deck_agent_mailbox_implementation_plan.md' |
| `docs/plans/agent-mail/claude_deck_agent_mailbox_implementation_plan.md` | 126 | 138 | 1, 3, 5-6, 12, 15, 17, 19, 37, 41, 45, 47, 63, 68, 70, 80-81, 90, 96, 99, 103, 105, 120, 123, 151, 174, 215, 251, 259, 487, 757, 927, 1012, 1020, 1028, 1040, 1088-1089, 1097, 1155, 1162, 1165, 1182, 1185, 1187-1188, 1213, 1221, 1249, 1255, 1261, 1267, 1295-1303, 1338, 1375, 1394, 1413, 1609, 1611, 1623, 1625-1627, 1634, 1636, 1644, 1650, 1662, 1719, 1731, 1760, 1774, 1786, 1821, 1876, 1892, 1899, 1903, 1905-1906, 1917, 1920, 1922-1923, 1960, 1968, 1971, 1988, 1991-1992, 2247, 2379, 2388, 2407, 2417, 2583, 2830, 2917, 2928, 2936, 3070-3071, 3118, 3140, 3180, 3183, 3200, 3254, 3256, 3324, 3360, 3377, 3389-3394 | # Claude Deck Agent Mailbox — Codex CLI Implementation Plan |
| `docs/plans/instance-identity/claude-deck-instance-identity-implementation-plan.md` | 87 | 93 | 1, 4, 6, 12, 18, 74, 108, 128, 135-136, 228, 239-241, 247-248, 253-254, 259-260, 307, 334, 395, 410, 418, 422, 425, 429, 466, 482-484, 655, 693, 697, 724, 999, 1001, 1004-1005, 1017-1020, 1053-1055, 1072, 1118, 1124, 1155, 1160, 1201, 1296-1298, 1307-1309, 1312, 1325, 1384-1386, 1449, 1462, 1468, 1517, 1580, 1594-1597, 1602, 1617-1618, 1659, 1677, 1704, 1764, 1779, 1789, 1792, 1796, 1944, 1966, 1970 | # Claude Deck Instance Identity & Accent Implementation Plan |
| `docs/plans/presence/claude-deck-cost-mockup.html` | 6 | 6 | 6, 166, 222, 248, 369, 374 | <title>Claude Deck — Cost</title> |
| `docs/plans/presence/claude-deck-files-mockup.html` | 6 | 6 | 6, 224, 239, 315, 325, 377 | <title>Claude Deck — Files</title> |
| `docs/plans/presence/claude-deck-presence-mockup.html` | 4 | 4 | 6, 354, 520, 525 | <title>Claude Deck — Presence</title> |
| `docs/plans/presence/claude-deck-timeline-mockup.html` | 8 | 8 | 6, 470, 489, 575, 579, 701, 711, 729 | <title>Claude Deck — Timeline</title> |
| `docs/plans/product-reposition/README.md` | 5 | 5 | 1, 3, 5, 7, 15 | # Claude Deck product repositioning implementation packet |
| `docs/plans/product-reposition/agent-deployment-plan.md` | 19 | 19 | 7, 14-17, 21, 23, 51-56, 58-59, 63, 131-132, 134 | Deploy four product harness sessions first, coordinated through a dedicated Claude Deck instance, authenticated Agent Mail and GitHub. Preserve the Ti… |
| `docs/plans/product-reposition/architecture-contracts.md` | 2 | 2 | 1, 3 | # Claude Deck delivery architecture and contracts |
| `docs/plans/product-reposition/evidence/baseline-ac92522.json` | 1 | 1 | 3 | "repository": "juanrubio/claude-deck", |
| `docs/plans/product-reposition/evidence/baseline-ac92522.md` | 1 | 1 | 6 | 'feature/software-delivery-product-reposition' on 'juanrubio/claude-deck'. |
| `docs/plans/product-reposition/evidence/review-pr15-3df0cfd.md` | 1 | 1 | 4 | Repository: 'juanrubio/claude-deck'; issue #4, PR #15. |
| `docs/plans/product-reposition/evidence/review-pr15-ce8b729.md` | 1 | 1 | 5 | 'juanrubio/claude-deck', targeting 'feature/software-delivery-product-reposition'. |
| `docs/plans/product-reposition/evidence/review-pr16-54f3c0b.md` | 1 | 1 | 5 | 'juanrubio/claude-deck', target 'feature/software-delivery-product-reposition'. |
| `docs/plans/product-reposition/evidence/review-pr16-faa2efb.md` | 1 | 1 | 4 | Repository: 'juanrubio/claude-deck'; PR #16, 'product/factory-operations'. |
| `docs/plans/product-reposition/experience-spec.md` | 3 | 3 | 1, 3, 45 | # Claude Deck delivery experience specification |
| `docs/plans/product-reposition/handoffs/audit-and-metrics.md` | 1 | 1 | 3 | **Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / 'ac9252242fcf436c3ea9997add5d32416cad2cd1'. Product work starts first in the… |
| `docs/plans/product-reposition/handoffs/delivery-backend.md` | 1 | 1 | 3 | **Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / 'ac9252242fcf436c3ea9997add5d32416cad2cd1'. Product work starts first in the… |
| `docs/plans/product-reposition/handoffs/delivery-interface.md` | 1 | 1 | 3 | **Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / 'ac9252242fcf436c3ea9997add5d32416cad2cd1'. Product work starts first in the… |
| `docs/plans/product-reposition/handoffs/harness-operations.md` | 1 | 1 | 3 | **Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / 'ac9252242fcf436c3ea9997add5d32416cad2cd1'. Product work starts first in the… |
| `docs/plans/product-reposition/handoffs/onboarding-and-roles.md` | 1 | 1 | 3 | **Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / 'ac9252242fcf436c3ea9997add5d32416cad2cd1'. Product work starts first in the… |
| `docs/plans/product-reposition/handoffs/validation-and-release.md` | 2 | 2 | 3, 191 | **Execution baseline, 2026-10-02:** G00 passed through upstream PR #399 / 'ac9252242fcf436c3ea9997add5d32416cad2cd1'. Product work starts first in the… |
| `docs/plans/product-reposition/implementation-plan.md` | 3 | 3 | 1, 3, 35 | # Claude Deck product repositioning implementation plan |
| `docs/plans/product-reposition/product-brief.md` | 5 | 5 | 1, 3, 5, 13, 24 | # Claude Deck software delivery product brief |
| `docs/plans/product-reposition/reconciliation-ledger.md` | 1 | 1 | 12 | \| Product integration / controller pin \| 'ac9252242fcf436c3ea9997add5d32416cad2cd1'; product PRs target 'feature/software-delivery-product-repositio… |
| `docs/superpowers/plans/2026-07-04-autonomous-github-dispatch-phase-a.md` | 12 | 13 | 103-104, 195-196, 550, 555, 559, 752, 764, 773, 917, 1649 | assert scope.dispatch_label == "claude-deck-ready" |
| `docs/superpowers/plans/2026-07-06-autonomous-dispatch-hardening-and-soak.md` | 3 | 3 | 330, 959, 961 | """Report progress on a Claude-Deck-dispatched GitHub issue back to the brain. |
| `docs/superpowers/plans/2026-07-23-leader-owned-dependency-unblocking.md` | 1 | 1 | 556 | f'You are being started by Claude Deck as part of Agent Team "{preset.name}".', |
| `docs/superpowers/plans/2026-07-23-leader-unblock-coldstart-followup.md` | 1 | 2 | 35 | Note on preset resolution: the endpoint is keyed by 'preset_id'. The registered member carries its 'team_preset_id' (set at registration via 'CLAUDE_D… |
| `docs/superpowers/plans/2026-07-29-dispatch-workspace-provisioning.md` | 2 | 3 | 552, 1014 | "- Do NOT create, move or remove git worktrees yourself. Claude Deck " |
| `docs/superpowers/plans/2026-08-02-phase-g2-session-lifecycle.md` | 9 | 13 | 31-32, 34, 38, 44, 46, 67-69 | - Work **only** in '/home/juan/work/repos/juanrubio/claude-deck-g1'. |
| `docs/superpowers/plans/2026-08-04-phase-g3-observed-session-durability.md` | 15 | 17 | 106-107, 109-110, 117, 137, 336, 503-507, 728, 763, 851 | - Work **only** in '/home/juan/work/repos/juanrubio/claude-deck-g1'. |
| `docs/superpowers/plans/2026-08-09-pr0-agent-mail-capability-tokens.md` | 69 | 70 | 27-28, 33, 276, 380, 388, 434, 442, 519, 587, 595, 682, 790, 800, 870, 973, 983, 1005, 1013, 1248, 1322, 1629, 1637, 1725, 1798, 1838, 1955, 1963, 2261, 2269, 2277, 2320, 2386, 2454, 2462, 2696, 2821, 2827, 3363, 3371, 3392, 3426, 3505, 3507, 3545, 3586, 3591, 3599, 3607, 3982, 4190, 4206, 4216, 4687, 4827, 4866, 4878, 5540, 5589, 5764, 5803, 5937, 5969, 5977, 5985, 6968, 7047, 7363, 7427 | - Work only in '/home/juan/work/repos/juanrubio/claude-deck-g1'. |
| `docs/superpowers/plans/2026-08-11-pr1-approval-attribution-and-gate.md` | 2 | 2 | 29-30 | - Work only in '/home/juan/work/repos/juanrubio/claude-deck-g1'. |
| `docs/superpowers/plans/2026-08-12-pr2-distinct-commit-and-pr-identity.md` | 4 | 4 | 49, 51, 209, 396 | - Work only in '/home/juan/work/repos/juanrubio/claude-deck-g1'. |
| `docs/superpowers/plans/2026-08-29-autonomous-attempt-recovery.md` | 2 | 2 | 6, 106 | **Issue:** 'https://github.com/adrirubio/claude-deck/issues/325' |
| `docs/superpowers/plans/2026-08-29-pr1-approval-request-authority.md` | 4 | 4 | 20, 47, 67, 69 | **Issue:** 'https://github.com/adrirubio/claude-deck/issues/325' |
| `docs/superpowers/plans/2026-09-26-pi-provider-and-agent-mail.md` | 6 | 6 | 3, 8, 104, 175-177 | **Issue:** https://github.com/adrirubio/claude-deck/issues/357 |
| `docs/superpowers/plans/2026-10-14-muse-code-harness.md` | 4 | 5 | 22, 275, 283, 336 | - **Settings file:** '$MUSE_CONFIG_DIR' or '~/.config/muse', then 'settings.json'. It must keep 'schema_version'. The install edits only 'mcpServers.c… |
| `docs/superpowers/plans/2026-10-16-website-foundation-and-first-scene.md` | 10 | 12 | 5, 11, 15, 51-52, 286, 425, 488, 496, 672 | **Goal:** a new Astro site on the branch 'preview/website-v2' of 'adrirubio/claude-deck-website', live on an unlisted Cloudflare Pages preview URL, wi… |
| `docs/superpowers/specs/2026-04-10-settings-gap-update-design.md` | 1 | 1 | 5 | **Context:** Claude-deck's settings editor was last updated on 2026-03-20 (commit 565de27). Since then, Claude Code has added Auto Mode, Plugins/Marke… |
| `docs/superpowers/specs/2026-05-29-agent-bridge-bedrock-platform-design.md` | 3 | 3 | 15, 41, 96 | - **Credential source: inherit from the server.** Claude Deck never collects or stores AWS secrets. Selecting Bedrock sets non-secret env vars ('CLAUD… |
| `docs/superpowers/specs/2026-06-29-agent-bridge-image-paste-design.md` | 22 | 24 | 18-19, 22, 68, 86, 192-193, 196, 207, 218, 226, 229, 288, 308-309, 318, 353, 362, 372, 562, 570, 686 | 3. Claude Deck stores the image somewhere the tmux agent process can read, |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-design.md` | 5 | 6 | 6, 12, 62, 200, 246 | **Scope:** Can the Claude Deck Agent Teams API faithfully express, and can an external agent generate, a roster where each slot pins a specific CLI to… |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-e2e-tests.md` | 11 | 11 | 6, 16, 22, 27, 168, 179, 190, 199, 208, 290-291 | **Purpose:** verify that an agent can set up, validate, and launch Agent Teams through the Claude Deck agentic surface (MCP tools, with REST equivalen… |
| `docs/superpowers/specs/2026-07-02-autonomous-github-dispatch-design.md` | 12 | 16 | 5, 13, 28, 93-94, 107-108, 198, 234, 282, 316, 402 | **Scope:** Give Claude Deck an optional "brain" that watches labeled GitHub issues on one or more repos per Agent Team, routes each issue to the team'… |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-ui-mockups.html` | 12 | 12 | 265, 306, 328, 349, 362, 377-378, 393-394, 452, 457, 557 | <p>Screens are annotated with which use case(s) from the use-case doc they exist to satisfy, and rendered against Claude Deck's actual color palette (… |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-use-cases.html` | 3 | 4 | 252, 328, 499 | <p class="trigger">Trigger: issue labeled <code>claude-deck-ready</code> + <code>area:backend</code>, scope's <code>merge_policy=human</code>.</p> |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-workflows.html` | 2 | 2 | 184, 186 | Human->>GH: label issue #42 "claude-deck-ready" + "area:backend" |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-workflows.md` | 3 | 3 | 23, 25, 264 | Human->>GH: label issue #42 "claude-deck-ready" + "area:backend" |
| `docs/superpowers/specs/2026-07-04-autonomous-github-dispatch-conversational-setup-mockups.html` | 5 | 5 | 223, 237, 449, 451, 566 | <div class="app-titlebar"><span class="dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span> Claude Deck — Agent Te… |
| `docs/superpowers/specs/2026-07-04-conversational-team-and-autonomy-setup-design.md` | 1 | 1 | 8 | **Scope:** Give Claude Deck a conversational entry point that lets a human describe a project and have the brain propose *both* an 'AgentTeamPreset' r… |
| `docs/superpowers/specs/2026-07-05-autonomous-github-dispatch-e2e-verification-plan.md` | 6 | 8 | 22, 25, 47, 68, 73, 94 | 1. **A throwaway target repo** you own with write access — NOT a production repo, NOT SnazzyEmail or Claude Deck itself. Create 'e2e-dispatch-sandbox'… |
| `docs/superpowers/specs/2026-07-05-tizonia-e2e-testbed-plan.md` | 10 | 11 | 1, 13, 15-16, 31, 55, 68-69, 76, 79 | # Tizonia as Claude Deck E2E Testbed — Adapted Verification Plan |
| `docs/superpowers/specs/2026-07-06-dispatch-open-finding-leader-ack-timeout.md` | 1 | 1 | 38 | This should be resolved before Claude Deck runs genuinely unattended against a live roadmap at scale, since leader latency will be common there. Tackl… |
| `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-run-log.md` | 24 | 29 | 137, 352, 658-661, 688, 691-693, 695-697, 719, 721, 733, 736, 931, 1034, 1731, 1747, 1779, 1790, 1795 | While #820 (SoundCloud removal, real code) was dispatched, the **standing Specialist session (member 17)** detected a **separate dispatched-owner proc… |
| `docs/superpowers/specs/2026-07-29-dispatch-workspace-provisioning-design.md` | 1 | 1 | 381 | - Do NOT create, move or remove git worktrees yourself. Claude Deck provisions |
| `docs/superpowers/specs/2026-08-02-phase-g2-session-lifecycle-design.md` | 1 | 1 | 993 | - every other checkout (including 'claude-deck-g1') migrates itself, instead of silently |
| `docs/superpowers/specs/2026-08-05-distinct-approver-identity-design.md` | 15 | 15 | 274, 535, 545, 2240, 2586, 3083, 3086, 3098, 3111, 3117, 3177, 3192, 3248, 3775, 4489 | Three conclusions: the defect is real and total on the path it affects; enforcing a distinct approver would reject a **rare** case (3/81 requests), no… |
| `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md` | 1 | 1 | 6 | **Issue:** [#325 — Resume active escalated attempts with leader-authorized scope extensions](https://github.com/adrirubio/claude-deck/issues/325) |
| `docs/superpowers/specs/2026-10-14-muse-code-harness-design.md` | 1 | 1 | 68 | - **MCP:** set 'mcpServers.claude-deck-mail' to a stdio entry that runs Deck's 'agent_mail_server.py' shim. Keep all other servers and settings, and r… |
| `docs/superpowers/specs/2026-10-16-website-build-design.md` | 2 | 3 | 13, 31 | - **Repository:** 'adrirubio/claude-deck-website', the repository of the live site. |

## 5. Supplemental searches (separate totals, never added to section 3)

Each set below was searched on its own terms at the same pin. Where a supplemental line is already a primary line, that overlap is stated and the table lists only the non-primary remainder, so nothing is double-counted across sections 4 and 5.

### 5.1 Bare `Deck` (the short product name)

Search: `git grep -I -n -w -E 'Deck' <pin> -- .` (case-sensitive capital `Deck` as a word; hyphenated forms such as `X-Deck-Operator-Token` and the `Deck-Agent-Slot`/`Deck-Work-Item` trailers match as word components and are included).
Whole set: 2,254 lines, 2,424 occurrences, 348 distinct files. Of these, 585 lines are already primary lines in section 4. The table lists the **1,669 non-primary lines** (1,796 occurrences, 279 distinct files). An ordinary-language screen for collocations such as "slide Deck", "Deck of cards" or "tape Deck" over the non-primary lines found **0** candidates, so no line is held back as ambiguous; capital `Deck` in this repository is the product short name throughout the listed lines. Lowercase bare `deck` as an English word is outside this search by design. These lines matter for the rename because the short name is product copy and, in the hyphenated tokens, identifier material for #789 — but they are not occurrences of the six primary strings.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `CHANGELOG.md` | 1 | 1 | 23 | - **Agent Mail:** "Waiting on someone" first, conversations grouped by team, a compact roster, the sender shown as Deck, Director or agent, and Mail s… |
| `CLAUDE.md` | 1 | 1 | 89 | - Docs-only pull requests (every changed file under 'docs/' or root Markdown) skip the expensive steps of the backend, frontend and e2e jobs. The jobs… |
| `README.md` | 8 | 8 | 17-18, 27, 29, 35, 163, 165, 201 | - Local control plane and real agent/repository files; no Deck cloud account. |
| `backend/app/api/v1/agent_mail.py` | 1 | 1 | 1231 | return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "Check your Deck inbox."}} |
| `backend/app/models/database.py` | 1 | 1 | 715 | # New ORM notices come from Deck. The migration leaves historical rows null. |
| `backend/app/models/schemas.py` | 1 | 1 | 2737 | "Deck will poll again. Unreadable checks do not grant verification or consume a retry.", |
| `backend/app/services/agent_activity_service.py` | 2 | 2 | 532, 701 | # reject UUID reuse anywhere in Deck, including other presets/disabled slots, |
| `backend/app/services/agent_mail_install_service.py` | 1 | 1 | 821 | # Deck's Muse groups carry no matcher, so they run for every session source. |
| `backend/app/services/agent_mail_service.py` | 2 | 2 | 1728, 1731 | return "Deck", "system", None |
| `backend/app/services/agent_team_service.py` | 1 | 1 | 1021 | "Resume the saved rollout ID through Deck after capture" |
| `backend/app/services/cc_bridge/spawn.py` | 1 | 1 | 91 | """Return all sessions spawned by Deck.""" |
| `backend/app/services/codex_process_identity.py` | 2 | 2 | 1, 31 | """Recognize only the explicit resume command forms emitted by Deck.""" |
| `backend/app/services/github_client.py` | 1 | 1 | 31 | """GitHub returned a response Deck cannot safely interpret.""" |
| `backend/app/services/github_dispatch_service.py` | 5 | 5 | 1409-1410, 1448, 1450, 1455 | "- This is a shared human checkout, not a Deck-managed worktree. Its " |
| `backend/app/services/github_verification_service.py` | 6 | 6 | 69, 659, 1715, 1883, 2513, 2523 | # Escalations a late PR legitimately resolves: the agent said it was stuck, or Deck |
| `backend/app/services/github_workspace_service.py` | 1 | 1 | 264 | return f"{display_name} (Deck agent)" |
| `backend/app/services/maintenance_operations.py` | 1 | 1 | 226 | headers={"Content-Type":"application/json", "X-Deck-Operator-Token":token}) |
| `backend/app/services/pi_mail_readiness.py` | 1 | 1 | 26 | return False, "Deck Pi extension assets are missing" |
| `backend/app/services/provider_operations_service.py` | 3 | 3 | 214-215, 233 | "launch": ("Deck has a validated native launch contract.", ["Binary and Mail prerequisites", "Validated provider launch options", "Existing launch act… |
| `backend/app/services/providers/capabilities.py` | 6 | 6 | 43, 51, 106, 109, 129, 132 | "spawn": capability("write_capable", "Spawn Sessions", "Deck can launch Muse Code on a Muse subscription or API key."), |
| `backend/app/services/providers/launch_contract.py` | 1 | 1 | 168 | """Return whether a provider exposes a Deck Bedrock launch path.""" |
| `backend/app/services/providers/launch_options.py` | 1 | 2 | 66 | descriptor["warnings"] = ["Agent Mail requires the Deck Pi extension. Pi tools are not a Deck sandbox."] |
| `backend/app/services/team_communication_policy.py` | 4 | 4 | 13, 16-17, 59 | These instructions guide your output. Deck does not check the full controlled dictionary.""" |
| `backend/mcp_shim/agent_mail_server.py` | 4 | 4 | 108, 125, 970, 1377 | raise TimeoutError("Deck request total deadline expired") |
| `backend/mcp_shim/github_summary_protocol.py` | 1 | 1 | 96 | # Another Deck section inside this block belongs to another writer. |
| `backend/mcp_shim/team_question_hook.py` | 2 | 2 | 1, 21 | """Refuse interactive questions in unattended Deck team sessions.""" |
| `backend/tests/agent_mail/test_actor_thread_capability.py` | 6 | 6 | 57-58, 335, 384-385, 553 | headers={"X-Deck-Operator-Token": "test-director-key"}, |
| `backend/tests/agent_mail/test_api.py` | 132 | 134 | 96, 105, 122, 193, 204, 209, 214, 250, 253, 261, 322, 327, 332, 344, 418, 437, 442, 445, 462, 665, 670, 699, 714, 720, 725, 754, 763, 779, 786, 795, 847, 850, 855, 857, 866, 896, 905, 934, 956, 962, 968, 977, 997, 1010, 1020, 1031, 1057, 1087, 1116, 1146, 1181, 1203, 1213, 1240, 1256, 1287, 1296, 1301, 1306, 1332, 1348, 1401, 1431, 1462, 1469, 1483, 1494, 1533, 1540, 1562, 1746, 1820, 1867, 1903, 1941, 2006, 2060, 2083, 2109, 2123, 2140, 2169, 2178, 2191, 2200, 2227, 2245, 2267, 2312, 2338, 2366, 2384, 2389, 2394, 2420, 2463, 2494, 2566, 2607, 2618, 2670, 2692, 2709, 2731, 2742, 2773, 2783, 2798, 2822, 2832, 2847, 2956, 2964, 2970, 3004, 3030-3031, 3067, 3102, 3176-3177, 3210, 3234, 3240, 3255, 3259, 3338-3339, 3402, 3420, 3429-3430 | return {"X-Deck-Session-Token": token} |
| `backend/tests/agent_mail/test_capability_tokens.py` | 18 | 18 | 328, 356, 401, 644, 655, 714, 738, 753, 780, 815, 847, 868, 920, 958, 1004, 1091, 1098, 1105 | headers={"X-Deck-Session-Token": token}, |
| `backend/tests/agent_mail/test_dispatch_status_tool.py` | 3 | 3 | 94, 118, 349 | headers={"X-Deck-Session-Token": DEFAULT_TOKEN}, |
| `backend/tests/agent_mail/test_external_api.py` | 3 | 3 | 55, 175, 406 | headers={"X-Deck-Operator-Token": "test-director-key"}, |
| `backend/tests/agent_mail/test_hooks_api.py` | 2 | 2 | 31, 178 | return {"X-Deck-Session-Token": response.json()["capability_token"]} |
| `backend/tests/agent_mail/test_lease_token_redaction.py` | 4 | 4 | 62, 82, 105, 128 | response = await client.get("/api/v1/agent-mail/messages", headers={"X-Deck-Operator-Token": "test-director-key"}) |
| `backend/tests/agent_mail/test_mcp_shim.py` | 7 | 7 | 329, 360, 385, 447, 858, 873, 998 | assert captured["headers"]["X-Deck-Session-Token"] == "tok-abc" |
| `backend/tests/agent_mail/test_messaging.py` | 17 | 17 | 113, 117, 137-138, 144-154, 169, 193 | assert (system.sender_name, system.sender_type) == ("Deck", "system") |
| `backend/tests/agent_mail/test_session_closure.py` | 6 | 6 | 48, 50, 56, 63, 87, 157 | close = await client.post("/api/v1/agent-mail/agent/close", headers={"X-Deck-Session-Token": token}) |
| `backend/tests/agent_teams/test_active_continuation_cancellation.py` | 1 | 1 | 39 | OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN} |
| `backend/tests/agent_teams/test_agent_team_api.py` | 7 | 7 | 141, 180, 1007, 1020-1021, 1070, 1073 | json=body, headers={"X-Deck-Operator-Token": "invalid"}) |
| `backend/tests/agent_teams/test_agent_team_service.py` | 1 | 1 | 2191 | """Without this row every Deck-launched pane gets bind_pending forever.""" |
| `backend/tests/agent_teams/test_agent_team_supervisor.py` | 5 | 5 | 49, 100, 106, 187, 251 | headers={"X-Deck-Operator-Token": "synthetic-director-token"}, json={"actor_id": actor_id}) |
| `backend/tests/agent_teams/test_factory_delivery_policy.py` | 2 | 2 | 837, 868 | headers={'X-Deck-Operator-Token':'fixture-operator'} |
| `backend/tests/agent_teams/test_force_release_concurrency.py` | 1 | 1 | 29 | OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN} |
| `backend/tests/agent_teams/test_github_coordination.py` | 3 | 4 | 414, 425, 926 | leader_headers = {"X-Deck-Session-Token": "fixture-session-token"} |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | 4 | 4 | 2177-2178, 2183, 3545 | assert f"Deck-Agent-Slot: {owner.id} ({owner.display_name})" in brief |
| `backend/tests/agent_teams/test_github_recovery_gate.py` | 3 | 3 | 518, 521, 526 | await client.get(endpoint, headers={"X-Deck-Operator-Token": "wrong"}) |
| `backend/tests/agent_teams/test_github_work_progress.py` | 3 | 3 | 620-621, 632 | assert (await http.get(path, headers={"X-Deck-Session-Token": "other-token"})).status_code == 403 |
| `backend/tests/agent_teams/test_github_workspace_api.py` | 1 | 1 | 63 | OPERATOR_HEADERS = {"X-Deck-Operator-Token": OPERATOR_TOKEN} |
| `backend/tests/agent_teams/test_github_workspace_service.py` | 1 | 1 | 1172 | "Backend SME (Deck agent)" |
| `backend/tests/agent_teams/test_initial_approval_cancellation.py` | 2 | 2 | 163, 166 | operator = {"X-Deck-Operator-Token": "review-operator"} |
| `backend/tests/agent_teams/test_initial_approval_diagnostics.py` | 2 | 2 | 135-136 | operator = {"X-Deck-Operator-Token": "review-operator"} |
| `backend/tests/agent_teams/test_operator_auth.py` | 28 | 28 | 130, 220-221, 312, 315, 319, 322, 324, 328, 334, 351, 355, 373-374, 430, 433, 463, 480, 508, 515, 533, 554, 577, 590, 606, 635, 650, 703 | headers={"X-Deck-Operator-Token": director_key}, |
| `backend/tests/agent_teams/test_owner_followup.py` | 2 | 2 | 722-723 | assert (await client.post(path, json=body, headers={"X-Deck-Operator-Token":"fixture-operator"})).status_code == 401 |
| `backend/tests/agent_teams/test_pi_team.py` | 5 | 5 | 153, 155, 162, 168, 170 | retired = await client.post("/api/v1/agent-mail/sessions/retire-dead-pane", headers={"X-Deck-Operator-Token": "migration-operator"}, json={"pane_pid":… |
| `backend/tests/agent_teams/test_team_deletion_guard.py` | 1 | 1 | 208 | headers={"X-Deck-Operator-Token": token} if token else {}) as client: |
| `backend/tests/agent_teams/test_terminal_revision_reconciliation.py` | 1 | 1 | 302 | headers = {"X-Deck-Operator-Token": header} if header else {} |
| `backend/tests/factory/test_factory_api.py` | 1 | 1 | 99 | # A status that Deck does not know yet is not finished, so it is open. |
| `backend/tests/factory/test_factory_audit_metrics.py` | 2 | 2 | 1142, 1150 | _OPERATOR_HEADERS = {"X-Deck-Operator-Token": _OPERATOR} |
| `backend/tests/factory/test_factory_context_keys.py` | 2 | 2 | 20, 102 | HEADERS = {"X-Deck-Operator-Token": OPERATOR} |
| `backend/tests/factory/test_factory_fixtures.py` | 1 | 1 | 146 | headers={"X-Deck-Operator-Token": "synthetic-factory-operator"}) |
| `backend/tests/factory/test_setup_preflight.py` | 2 | 2 | 42, 379 | headers={"X-Deck-Operator-Token": OPERATOR}, |
| `backend/tests/fixtures/native_screens/claude-question-form-two-questions.txt` | 1 | 1 | 16 | The sessions only run a fake echo loop. Deck can |
| `backend/tests/fixtures/provider-operations/v1/catalog.json` | 33 | 33 | 12, 26, 502, 516, 944, 958, 1114, 1129, 1366, 1380, 1536, 1551, 1788, 1805, 1925, 1939, 2211, 2225, 2361, 2635, 2649, 3077, 3091, 3519, 3533, 3961, 3975, 4403, 4417, 4845, 4859, 5287, 5301 | "reason": "Deck has a validated native launch contract.", |
| `backend/tests/test_agent_bridge_attachments.py` | 2 | 2 | 265, 301 | "X-Deck-Operator-Token": "test-operator-secret", |
| `backend/tests/test_bridge_terminal_authority.py` | 4 | 5 | 48, 56, 74, 87 | for headers in (None, {"X-Deck-Session-Token": "agent-token"}, {"X-Deck-Operator-Token": "wrong"}): |
| `backend/tests/test_cors.py` | 1 | 1 | 1 | """Cross-origin access to the local Deck API is explicit, not wildcard.""" |
| `backend/tests/test_pi_mail_ancestry.py` | 1 | 1 | 55 | closures.append(self.headers.get("X-Deck-Session-Token") == "synthetic-capability") |
| `backend/tests/test_settings_write_guard.py` | 2 | 2 | 81, 93 | wrong = await client.request(method, path, headers={"X-Deck-Operator-Token": "wrong"}) |
| `docs/api/agent-bridge.md` | 1 | 1 | 68 | Returns a 30-second, single-use token bound to one exact tmux target and purpose. 'purpose=readonly' is available for terminal viewing; 'purpose=attac… |
| `docs/api/agent-mail.md` | 2 | 2 | 57, 114 | X-Deck-Operator-Token: <operator token> |
| `docs/api/agent-teams.md` | 2 | 3 | 12, 320 | "Operator token" means the 'X-Deck-Operator-Token' header. "Mail session" means an authenticated 'X-Deck-Session-Token'. |
| `docs/api/cc-bridge.md` | 1 | 1 | 33 | Returns a 30-second, single-use token for one exact tmux target and purpose. 'purpose=interactive' requires 'X-Deck-Operator-Token'; agent session tok… |
| `docs/api/factory.md` | 4 | 5 | 7, 169, 182, 209 | The classes below describe behavior and access, not the HTTP method. "Operator token" means the 'X-Deck-Operator-Token' header. "Mail session" means a… |
| `docs/autonomy.md` | 9 | 9 | 3, 7, 9-10, 13, 18, 21, 34, 68 | This guide is for the operator of a Deck team. Autonomy is off until you enable it for the team, and a watched repo can also be paused separately. |
| `docs/deploy/attempt-recovery-pr1-rollout.md` | 3 | 3 | 43, 109, 154 | index has the expected name but the wrong uniqueness, columns, or predicate, Deck repairs |
| `docs/deploy/attempt-recovery-pr2-rollout.md` | 2 | 2 | 105, 109 | No live Deck database was migrated, no autonomy or continuation flag was enabled, and no |
| `docs/deploy/attempt-recovery-pr3-rollout.md` | 4 | 4 | 97-98, 121, 178 | Do not install hosted-only diagnostic tools on the Deck host. A missing hosted tool is not |
| `docs/deploy/attempt-recovery-rollout.md` | 3 | 3 | 31, 35, 107 | isolated so unrelated sessions cannot receive Deck prompts. |
| `docs/deploy/attempt-recovery-soak-log-2026-09-29.md` | 7 | 8 | 10, 25-26, 51-52, 112, 138 | records the final revision and terminal cleanup from live Deck DB/API, Agent Mail, |
| `docs/deploy/attempt-recovery-soak-log-template.md` | 2 | 2 | 9, 11 | - Deployed Deck SHA: |
| `docs/deploy/attempt-recovery-soak-runbook.md` | 7 | 7 | 30, 47, 150, 154, 208, 233, 239 | - Do not install diagnostic tools on the Deck host. |
| `docs/deploy/factory-delivery-practices.md` | 1 | 1 | 43 | Projects choose their own check names. Deck does not assume a language, team name, harness, or model. |
| `docs/deploy/factory-maintenance-operations.md` | 3 | 3 | 30, 34, 113 | Both owner monitors use the usual idle nudge and grace first. Unknown native evidence does not renew contact. A bound, live owner with actual approval… |
| `docs/deploy/leader-backlog-coordination.md` | 4 | 4 | 61, 63, 73, 156 | Delayed queue and refusal writes cannot undo an operator cancellation. Deck |
| `docs/deploy/pi-provider-rollout.md` | 4 | 4 | 16, 36, 52, 116 | Development validation uses full 'npm ci', 'npm run typecheck', 'npm test', and the backend interpreter to run 'scripts/generate-pi-mail-manifest.py -… |
| `docs/deploy/pi-provider-validation.md` | 1 | 2 | 21 | The actual Pi CLI fixture ran '--mode rpc --no-session --no-extensions --no-skills' with the explicit Deck extension, isolated HOME/runtime storage an… |
| `docs/deploy/pr0-capability-tokens-rollout.md` | 2 | 2 | 68, 82 | -H "X-Deck-Operator-Token: $(grep '^operator_token=' backend/.env \| cut -d= -f2-)" |
| `docs/deploy/pr2-github-app-rollout.md` | 5 | 5 | 3, 15, 36, 58, 66 | PR2 adds per-agent commit identity, repository-scoped push credentials, and Deck-owned pull-request creation. Roll it out one repository at a time. |
| `docs/deploy/product-lane-b-factory.md` | 1 | 1 | 51 | Deck's distinct Leader plan approval, independent exact-head review, human merge, single dispatch and finite budgets remain in effect. The cybersecuri… |
| `docs/deploy/soak-resume-runbook.md` | 8 | 9 | 35, 39, 43, 50, 281, 379, 414, 428 | Deck's autonomous dispatch loop is not verified against fixtures. It is verified by pointing |
| `docs/features/agent-bridge.md` | 1 | 2 | 86 | For Codex Bedrock sessions, Deck passes a per-session Codex config override for 'model_provider = "amazon-bedrock"'. Optional AWS region and profile v… |
| `docs/features/agent-mail.md` | 5 | 6 | 5, 46, 73, 81, 104 | Broadcasts require an explicit audience: an Agent Team preset, repository, or GitHub work item. Deck stores that audience with the message and creates… |
| `docs/features/agent-teams.md` | 12 | 12 | 17, 60, 69, 86, 107, 116, 121, 129, 139, 150, 212, 224 | Build directory, command and parallelism fields are hints in the owner's brief; Deck does not run those build commands. Editable numeric drafts valida… |
| `docs/features/external-agent-orchestration.md` | 4 | 5 | 132, 137, 146, 167 | External tools should use the existing Agent Teams API to launch or reuse a saved roster. Listing presets needs no credential. Planning and launching … |
| `docs/features/harnesses.md` | 5 | 5 | 21, 23-24, 26-27 | Muse Code is Meta's CLI ('muse'). Deck runs it as a team member with the provider 'muse-cli', for example with the model 'muse-wonder-1.0'. |
| `docs/guide/installation.md` | 3 | 3 | 24, 76, 95 | - The dependencies of the repository-local Agent Mail extension in 'integrations/pi-agent-mail', prepared before you launch Pi from Deck |
| `docs/guide/operating-model.md` | 17 | 17 | 3, 19, 25, 31, 36, 38, 45-46, 63, 65, 67, 69, 73, 83, 88, 99, 110 | This page shows who does what when a Deck team works on a GitHub backlog. Use it with the [Supervised factory playbook](./supervised-factory-playbook.… |
| `docs/guide/quick-start.md` | 2 | 2 | 3, 53 | Start Deck, inspect existing work, or launch a manual session before deciding whether to connect a repository. |
| `docs/guide/supervised-factory-playbook.md` | 26 | 28 | 3, 5, 44, 66, 110, 144, 154, 170, 177, 191, 220, 222, 224, 226-228, 279, 401, 403, 414, 424, 432, 531, 601, 603, 609 | Use this playbook when an operator delegates a GitHub backlog to a supervising agent and a Deck team. It covers preparation, autonomous delivery, inde… |
| `docs/plans/2026-03-01-cc-bridge-stage1.md` | 1 | 1 | 1457 | **Step 2: Start the Deck dev servers** |
| `docs/plans/2026-03-05-http-hooks-integration-design.md` | 5 | 5 | 135, 139, 179, 197, 227 | #### 2.5 Frontend: Connect to Deck Dialog |
| `docs/plans/2026-03-06-agent-orchestration-design.md` | 30 | 31 | 13, 64-66, 82, 92, 96, 109, 132, 146, 187, 194, 200, 206, 212-213, 222, 224, 235, 237, 240, 243, 250, 256, 267, 278, 290, 292, 303-304 | The killer feature: **Deck becomes the nervous system connecting OpenClaw and CC instances**, enabling end-to-end execution of large tasks (PRDs, migr… |
| `docs/plans/2026-10-11-v3.1-director-ui/README.md` | 2 | 2 | 1, 3 | # Deck v3.1 Director UI — design reference |
| `docs/plans/2026-10-11-v3.1-director-ui/director-ui-mockup.html` | 20 | 21 | 390, 412, 429, 482, 499, 679, 686, 713, 771, 793, 795, 811, 837, 899, 901-902, 907, 912, 915-916 | <div><div class="what">Approve publication of Deck v3.0.1</div> |
| `docs/plans/2026-10-11-v3.1-director-ui/factory-operation-explainer.html` | 17 | 18 | 120, 125, 203, 251, 354-355, 375, 386, 411, 467, 471, 500, 586, 632, 641, 659, 664 | <p class="lede">This page shows the simplified #506 proposal. The Director owns the GitHub backlog. The factory is the supervisor, the controller and … |
| `docs/plans/2026-10-15-director-website/01-audit.md` | 12 | 15 | 5, 16, 19, 26, 47, 65, 109, 138, 162, 172, 190, 194 | Purpose. This document audits claudedeck.org and the Deck documentation for a non-technical director. |
| `docs/plans/2026-10-15-director-website/02-factory-story.md` | 10 | 13 | 11, 17, 31, 39, 41, 43, 74, 88, 140, 142 | You shape the feature backlog, Deck's AI team builds and checks the work, and the key decisions stay with you. |
| `docs/plans/2026-10-15-director-website/03-website-plan.md` | 28 | 33 | 1, 14, 24, 26-27, 37, 39, 47, 69, 79, 86, 92, 100, 102, 104, 108, 110, 125, 134, 148, 156, 158, 166, 180, 207, 239, 242, 267 | # Website plan for the Deck website |
| `docs/plans/2026-10-15-director-website/04-docs-and-video.md` | 20 | 22 | 29-30, 41, 47, 50, 61, 91, 95, 97, 107, 117, 119, 138, 142, 147-148, 157, 208, 215, 231 | \| Start here \| Director \| What Deck is \| No install step, no shell command, no undefined word. \| |
| `docs/plans/2026-10-15-director-website/README.md` | 3 | 4 | 29, 43, 72 | 4. **Add Share Deck.** The link, the one-page summary, and later the video. Source: '03-website-plan.md', Share Deck; '01-audit.md', top problem 4. Di… |
| `docs/plans/2026-10-15-director-website/mockup/how-it-works.html` | 6 | 6 | 6, 42-43, 55, 94-95 | <title>Deck — How it works</title> |
| `docs/plans/2026-10-15-director-website/mockup/index.html` | 15 | 15 | 6, 120, 123, 130, 188, 192, 194, 271, 296, 305, 307, 347, 384, 395, 409 | <title>Deck — Your backlog. Your AI team. Finished work.</title> |
| `docs/plans/2026-10-15-director-website/pages/home.md` | 8 | 8 | 22, 28, 32, 50, 68, 102, 106, 111 | > Deck — Your features. Your AI teams. Finished products. |
| `docs/plans/2026-10-15-director-website/pages/how-it-works.md` | 16 | 17 | 15, 21, 25, 55, 185, 189, 197, 205, 209, 211, 215, 221, 235, 258, 262, 267 | > Deck — How it works |
| `docs/plans/2026-10-15-director-website/pages/quick-tour.md` | 13 | 14 | 9, 15, 21, 25, 33, 35, 37, 49, 159, 161, 185, 189, 194 | Every stop shows one seeded Deck screenshot carrying this label on the image: "Example data — seeded screens. Not live records." Crop every capture to… |
| `docs/plans/2026-10-15-director-website/pages/technical-information.md` | 21 | 22 | 15, 21, 25, 33, 41, 53, 55, 59, 63-65, 74, 82, 84, 86, 92, 102, 104, 116, 146, 150 | > Deck — Technical information |
| `docs/plans/2026-10-15-director-website/style/README.md` | 1 | 1 | 13 | - **Two pictures:** the hero shows the factory from outside (the Director, an AI helper, GitHub, Deck and several AI teams); the second scene shows th… |
| `docs/plans/2026-10-15-director-website/style/index.html` | 8 | 8 | 6, 48, 53, 56, 67, 147, 149, 163 | <title>Deck — style option C, revised</title> |
| `docs/plans/2026-10-15-director-website/style/source.html` | 8 | 8 | 6, 44, 49, 52, 63, 143, 145, 159 | <title>Deck — style option C, revised</title> |
| `docs/plans/2026-11-06-rename-synth-city/README.md` | 3 | 3 | 56, 62, 64 | ### Phase 1: the rename planning team (a Deck team, plan documents only) |
| `docs/plans/2026-11-06-rename-synth-city/transfer-runbook.md` | 33 | 34 | 91, 114, 296, 333, 344, 346, 355, 398-399, 405, 407, 446-447, 453, 481, 484, 497, 543-544, 569, 581-582, 620, 683, 685, 689, 691, 733, 891, 894-895, 927, 932 | During a freeze: no merges, no releases, and no Deck-dispatched work |
| `docs/plans/2026-11-06-rename-synth-city/website-and-docs.md` | 6 | 6 | 407, 486, 488, 490, 494, 870 | "Deck" labels ('factory.svg' 1, 'hierarchy.svg' 1, 'modes.svg' 3 visible labels at |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-implementation-plan.md` | 3 | 3 | 19, 3440, 3443 | 5. **No path leases, no PreToolUse guard, no Notification hook, no events audit table, no token auth in MVP.** Leases are Phase 2. Token rationale: De… |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v3-implementation-plan.md` | 3 | 3 | 21, 3884, 3889 | 5. **No path leases, no PreToolUse guard, no Notification hook, no events audit table, no token auth in MVP.** Leases are Phase 2. Token rationale: De… |
| `docs/plans/agent-mail/2026-06-14-codex-app-server-wakeups-implementation-plan.md` | 9 | 9 | 66, 122, 158, 176, 178, 228, 469, 536, 658 | Spike result: the installed Codex CLI on this machine supports 'codex app-server --stdio' directly, but 'codex remote-control start --json' fails beca… |
| `docs/plans/agent-mail/2026-06-15-agent-team-presets-implementation-plan.md` | 5 | 5 | 22, 39, 65, 201, 206 | 2. **Prefer reconciliation over blind spawning.** Deck should inspect live sessions and reuse matching agents before creating new tmux sessions. |
| `docs/plans/agent-mail/claude_deck_agent_mailbox_implementation_plan.md` | 1 | 1 | 4 | **Feature name:** Agent Mailbox, also called Agent Mesh / Deck Bus in this plan |
| `docs/plans/cc-bridge-design.md` | 17 | 18 | 3, 13, 18-19, 25, 59, 67, 91, 203, 205, 283, 287, 292, 299, 310-312 | > Deck ↔ Claude Code integration: observe, launch, orchestrate, and configure CC sessions from the browser. |
| `docs/plans/instance-identity/claude-deck-instance-identity-implementation-plan.md` | 7 | 7 | 282, 1176, 1190-1191, 1196, 1198, 1619 | - If missing, show no instance chip or show 'This Deck' fallback. |
| `docs/plans/product-reposition/agent-deployment-plan.md` | 5 | 5 | 65, 91, 95, 100, 169 | Use a dedicated product Deck instance on a recorded reviewed release SHA, initially the PR #399 release candidate subject to setup review. Do not run … |
| `docs/plans/product-reposition/architecture-contracts.md` | 4 | 4 | 270, 294, 298, 405 | \| 'launch' \| Launch a provider through Deck's validated launch contract \| |
| `docs/plans/product-reposition/experience-spec.md` | 1 | 1 | 84 | \| Updated \| Deck record update timestamp labelled as an observation \| |
| `docs/plans/product-reposition/handoffs/audit-and-metrics.md` | 1 | 1 | 65 | Team/repository renames and slot-provider changes do not rewrite past facts. Keep configured-at-event and observed-runtime providers distinct. Aggrega… |
| `docs/plans/product-reposition/handoffs/harness-operations.md` | 1 | 1 | 59 | \| Pi \| Preserve explicit extension opt-in, runtime requirements, exact project-local resume, authenticated lifecycle handling, and the absence of a … |
| `docs/plans/product-reposition/handoffs/validation-and-release.md` | 1 | 1 | 17 | Use a disposable Deck database, temporary repository/config directories, mocked GitHub and provider operations, and isolated tmux processes where a re… |
| `docs/plans/product-reposition/product-brief.md` | 4 | 4 | 52, 55, 69, 110 | \| Choosing a harness \| Understand operational readiness and the native features Deck actually supports \| |
| `docs/public/images/operating-model/factory.svg` | 1 | 1 | 42 | <text x="294" y="173" font-size="16" font-weight="700" fill="#1e293b">Deck controller</text> |
| `docs/public/images/operating-model/hierarchy.svg` | 1 | 1 | 72 | <text x="82" y="492" font-size="14" font-weight="700" fill="#1e293b">Deck controller</text> |
| `docs/public/images/operating-model/modes.svg` | 3 | 3 | 12, 23, 48 | <text x="186" y="28" font-size="12.5" fill="#57534e">Deck UI available · supervisor optional</text> |
| `docs/superpowers/plans/2026-07-06-autonomous-dispatch-hardening-and-soak.md` | 3 | 3 | 973, 1001-1002 | **Finish line:** loop reliability across every 'roadmap:v1' issue Deck picks up — NOT solving every issue. Easy issues merge; hard/blocked ones escala… |
| `docs/superpowers/plans/2026-07-23-leader-owned-dependency-unblocking.md` | 2 | 6 | 7, 15 | **Architecture:** Two generic Deck primitives + a leader-prompt addition. (1) A shared async notify helper on 'github_dispatch_service' fires a leader… |
| `docs/superpowers/plans/2026-07-26-soak-defect-triad-hardening.md` | 1 | 1 | 5 | **Goal:** Fix the three confirmed soak defects blocking unattended operation: (12) retry bypasses the leader-ack gate, (10) Deck can spawn a duplicate… |
| `docs/superpowers/plans/2026-07-27-closed-issue-reconciliation.md` | 1 | 1 | 77 | # A closed issue is ground truth from GitHub and outranks Deck's stale inference |
| `docs/superpowers/plans/2026-07-27-escalation-inflight-safety.md` | 1 | 1 | 49 | # Escalations a late PR legitimately resolves: the agent said it was stuck, or Deck |
| `docs/superpowers/plans/2026-07-29-dispatch-workspace-provisioning.md` | 19 | 23 | 5, 11, 363, 365, 367, 387, 502, 560-561, 605, 733, 738, 745, 808, 816, 972, 1004, 1039, 1043 | **This is the fifth version, and it has been through three reviews plus one design pass.** The first judged it unsafe ('/tmp/dispatch-workspace-provis… |
| `docs/superpowers/plans/2026-08-02-phase-g2-session-lifecycle.md` | 7 | 7 | 958, 1072, 1145, 1859, 2043, 2559, 3211 | Deck must not discard uncommitted work its own sweep can see. |
| `docs/superpowers/plans/2026-08-09-pr0-agent-mail-capability-tokens.md` | 52 | 55 | 116, 123, 1621, 1718, 1726, 1729, 2053, 2062, 2208, 2250, 2291, 2474, 2830, 2923, 2961, 3008, 3116, 3125, 3133, 3395, 3419-3420, 3479, 3508, 3535, 3582, 3720, 4505, 4526, 4548, 4567, 4588, 4618, 4639, 4679, 4804, 4885, 5058, 6215, 6501, 6550, 6724, 6728, 7045, 7184, 7367, 7429, 7443, 7454, 7528, 7542, 7636 | \| 'backend/app/services/agent_team_service.py' \| Modify \| Write and commit the 'agent_pane_bindings' row on both launch paths (':569' reuse, ':637'… |
| `docs/superpowers/plans/2026-08-12-pr2-distinct-commit-and-pr-identity.md` | 13 | 16 | 5, 7, 29, 33, 52, 68, 77, 398, 406, 690, 728, 782, 788 | **Goal:** Give each dispatched slot a distinct commit identity, create App-authored pull requests through Deck, deliver short-lived repository-scoped … |
| `docs/superpowers/plans/2026-08-29-autonomous-attempt-recovery.md` | 5 | 5 | 110, 133, 135, 137, 140 | - No Deck/tmux restarts until the deployment runbook explicitly authorizes them. |
| `docs/superpowers/plans/2026-08-29-pr1-approval-request-authority.md` | 2 | 2 | 48-49 | - Do not touch '/home/juan/work/repos/tizonia/', Tizonia PR #875, or Deck work item 23. |
| `docs/superpowers/plans/2026-08-29-pr2-non-destructive-attempt-continuation.md` | 1 | 1 | 59 | - Do not touch the live Deck checkout, live DB, Tizonia checkout, work item 23, or PR #875. |
| `docs/superpowers/plans/2026-08-29-pr3-diagnostic-recovery-orchestration.md` | 4 | 4 | 41, 242, 246, 396 | - Diagnostic tools are installed only by approved hosted CI changes; never on the Deck host. |
| `docs/superpowers/plans/2026-08-29-pr4-agent-bridge-visibility-and-soak-replay.md` | 8 | 8 | 38, 142, 300, 324, 327, 370, 377, 432 | - Do not use the live Deck database while implementing or testing UI. |
| `docs/superpowers/plans/2026-09-26-pi-provider-and-agent-mail.md` | 17 | 19 | 13, 25, 27, 32-33, 39, 46, 92, 95, 105, 110, 124, 133, 138, 197, 211, 216 | Make Pi a first-class provider that can participate in Deck Teams using Kimi K3 on OpenRouter, including authenticated mailbox tools, distinct approva… |
| `docs/superpowers/plans/2026-10-14-muse-code-harness.md` | 3 | 3 | 5, 32, 640 | **Goal:** Deck launches, identifies, observes, supervises and connects Agent Mail for Meta's Muse Code CLI as the provider 'muse-cli'. |
| `docs/superpowers/plans/2026-10-16-website-foundation-and-first-scene.md` | 6 | 7 | 19, 155, 587-588, 600, 639 | - The product is called only "Deck". No "Claude" anywhere in the new pages and scenes (the generated docs under 'docs/' are excluded from this check u… |
| `docs/superpowers/specs/2026-06-29-agent-bridge-image-paste-design.md` | 13 | 15 | 70, 84, 127-128, 493, 506, 512, 558, 577, 582, 676, 700, 706 | For this feature, attachments should be stored in a Deck-managed path on the same machine/filesystem namespace as the tmux process. |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-e2e-tests.md` | 2 | 2 | 140, 336 | > Substitute the concrete account-specific model IDs you actually use; the example IDs come from 'GET /providers/{id}/launch-options' → 'model_example… |
| `docs/superpowers/specs/2026-07-02-autonomous-github-dispatch-design.md` | 7 | 10 | 71, 237, 337, 360, 370-371, 384 | - External actors ('MailExternalActor', 'external_agent_mail_service.py') already authenticate via bearer token and are loopback-only to create ('exte… |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-ui-mockups.html` | 6 | 6 | 5, 263-264, 285, 290, 648 | <title>Autonomous GitHub Dispatch — Deck UI Mockups</title> |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-use-cases.html` | 2 | 2 | 233, 484 | <tr><td><code>dispatch_label</code></td><td><code>TeamGithubScope</code></td><td>Which issues Deck is allowed to touch at all (relevance filter).</td>… |
| `docs/superpowers/specs/2026-07-04-conversational-team-and-autonomy-setup-design.md` | 7 | 7 | 105, 110, 146, 208, 236-237, 240 | - Reading existing Deck state (a preset's slots, a repo's config) before speaking. |
| `docs/superpowers/specs/2026-07-05-autonomous-github-dispatch-e2e-verification-plan.md` | 1 | 1 | 54 | 3. **Pass criteria:** the PR is auto-merged by Deck, once, and the daily-auto-merge counter increments. Open a second auto issue and confirm it also m… |
| `docs/superpowers/specs/2026-07-05-dispatch-open-finding-stale-ready-state.md` | 3 | 4 | 7, 13, 19 | When a code-pipeline PR goes green → is promoted to 'dispatch_status="ready_for_review"' → and then a **new commit is pushed to the PR branch that tur… |
| `docs/superpowers/specs/2026-07-05-tizonia-e2e-testbed-plan.md` | 1 | 1 | 57 | - **T-S7 — branch protection → human fallback:** enable branch protection on tizonia 'master' (it should probably have this anyway) → auto-merge attem… |
| `docs/superpowers/specs/2026-07-06-autonomous-dispatch-hardening-and-soak-design.md` | 5 | 6 | 108, 139, 167, 175, 204 | In 'GithubVerificationService._process_review_item', under 'merge_policy=auto', Deck calls 'client.merge_pull' trusting the earlier 'ready_for_review'… |
| `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-run-log.md` | 53 | 62 | 5, 33, 125, 139, 149, 153, 157, 159, 161, 167, 169, 201, 205, 207, 232, 255, 271, 279, 303, 305, 318, 327, 340, 344, 348, 350, 356, 374, 390, 440, 450, 452, 458, 597, 635-636, 889, 901, 1320, 1322, 1356, 1422, 1572, 1672, 1743, 1758, 1774, 1778, 1793, 1796, 1812, 1831, 1835 | **Deck build:** integration branch 'feature/autonomous-github-dispatch' @ '5fb4d02' (Phase D merged) |
| `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-runbook.md` | 3 | 3 | 5, 33-34 | **Finish line:** loop reliability across every 'roadmap:v1' issue Deck picks up — NOT solving every issue. Easy issues merge; hard/blocked ones escala… |
| `docs/superpowers/specs/2026-07-23-leader-owned-dependency-unblocking-design.md` | 13 | 16 | 13, 20, 22, 30, 36, 69, 80, 90, 92, 109, 118-120 | - Deck has **no dependency model** — blocked detection is 100% agent triage (owner reads the issue body). |
| `docs/superpowers/specs/2026-07-26-soak-defect-triad-hardening-design.md` | 7 | 7 | 11, 78, 86, 88, 112, 140, 161 | Deck models **logical work**, not **physical resources**. Each existing guard is correct about its own abstraction and blind to the physical thing tha… |
| `docs/superpowers/specs/2026-07-27-closed-issue-reconciliation-design.md` | 4 | 5 | 22, 30, 58, 74 | The two sets are disjoint in exactly the wrong way: **the path that notices "the issue is done" excludes escalated items, and the path that handles es… |
| `docs/superpowers/specs/2026-07-27-escalation-inflight-safety-design.md` | 6 | 8 | 23, 32, 46-47, 53, 69 | So the owner's eventual 'deck_report_dispatch_status(status="pr_opened", pr_number=N)' would have failed **HTTP 409**. The work existed, the PR existe… |
| `docs/superpowers/specs/2026-07-29-dispatch-workspace-provisioning-design.md` | 34 | 44 | 13, 39, 51, 67, 142, 227, 276, 332, 338, 340-341, 367, 386, 390, 410, 474, 476, 482, 510, 525, 569, 596, 598, 623, 651, 672, 719, 783-784, 800, 804, 811, 893, 957 | Deck has **no workspace provisioning of any kind**. 'grep -rn worktree app/services/github_*' returns nothing. |
| `docs/superpowers/specs/2026-08-02-phase-g2-session-lifecycle-design.md` | 4 | 4 | 128, 447, 472, 595 | 1. **Deck cannot identify the owner session by asking "which pane sits in the leased |
| `docs/superpowers/specs/2026-08-05-distinct-approver-identity-design.md` | 134 | 162 | 49, 95-96, 108, 112-113, 117, 128, 131, 142-143, 193, 352, 386, 388, 403-404, 452, 464, 467, 527-528, 539, 543, 619, 639, 700, 737, 741, 747, 759, 812, 899, 931, 1054-1055, 1058, 2086, 2135, 2201, 2210, 2376, 2496, 3028, 3087-3088, 3145, 3171, 3176, 3197, 3238, 3240, 3247, 3253-3254, 3264, 3266, 3269, 3272, 3276, 3278, 3284, 3288-3289, 3291, 3306, 3322, 3326, 3328, 3341, 3378, 3380, 3386, 3438, 3440, 3455, 3474, 3478, 3492, 3524, 3528, 3582, 3584, 3586, 3591, 3596, 3604, 3659, 3663, 3670, 3683, 3687, 3705, 3707, 3712, 3752, 3762, 3764, 3770, 3818, 3841, 3876, 3881, 3889, 3928, 3940, 3958, 4023, 4031, 4037, 4104, 4120, 4152, 4154, 4166, 4184, 4212, 4244, 4246, 4406-4407, 4490, 4492, 4494-4495, 4503, 4507, 4527, 4536, 4540, 4544, 4569, 4575, 4583 | **What revision 15 changed** — revised after a fourteenth implementer review of '2932ec9' returned two sequencing blockers and one correction, all in … |
| `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md` | 27 | 27 | 14, 19, 21, 27-28, 43, 57, 114, 124, 128, 143, 194, 212, 249, 389, 406, 642, 687, 748, 781, 884, 1074, 1101, 1319, 1327, 1335, 1337 | Deck can stop unsafe work, but it cannot autonomously resume a stopped attempt when the |
| `docs/superpowers/specs/2026-10-14-muse-code-harness-design.md` | 12 | 13 | 7, 9, 25, 35, 43, 45-46, 69-70, 75, 102, 118 | Deck can run Meta's Muse Code CLI ('muse') as a team member, on a Muse subscription, with the same supervision as the other harnesses. The first user … |
| `docs/superpowers/specs/2026-10-16-website-build-design.md` | 9 | 10 | 7, 45, 50, 65, 78, 80, 84, 86, 90 | Build the new Deck website described in the approved plan ('docs/plans/2026-10-15-director-website/', #745) in the chosen style ('style/', option C "F… |
| `frontend/e2e/README.md` | 5 | 6 | 1, 3, 53, 57, 74 | # Deck E2E journeys |
| `frontend/e2e/g0/isolation.spec.ts` | 6 | 6 | 23, 140, 146, 149, 176, 181 | /** The caller environment without any Deck endpoint or credential. */ |
| `frontend/e2e/g1/project-selector.spec.ts` | 2 | 2 | 56, 58 | test('@active Folders Deck knows about explains what the folders do', async ({ page }) => { |
| `frontend/e2e/lane-b/team-url.spec.ts` | 1 | 1 | 53 | await expect(dialog).toContainText('Deck needs the key to plan a launch.') |
| `frontend/e2e/lane-c/feed.spec.ts` | 1 | 1 | 27 | expect(text, 'an actor in plain words').toMatch(/Director\|Deck\|scheduler\|B1 Backend\|B2 Backend\|Leader\|Backend\|Frontend/i) |
| `frontend/e2e/lane-d/conversations.spec.ts` | 3 | 3 | 9, 51, 56 | // Deck notices with the same subject and recipient collapse into one row. |
| `frontend/e2e/lane-g/mail-auth-flow.spec.ts` | 7 | 7 | 5-6, 48-49, 54, 57, 91 | const OWNER = { 'X-Deck-Session-Token': 'e2e-seed-idle-agent' } |
| `frontend/e2e/support/instance-identity.ts` | 2 | 2 | 16, 21 | throw new ForeignInstanceError('E2E refused: no Deck test instance answers ${baseURL}/health') |
| `frontend/e2e/support/time.ts` | 2 | 2 | 31, 45 | /** Assert that a locator shows the moment's local clock time (any of Deck's formats). */ |
| `frontend/playwright.config.ts` | 1 | 1 | 8 | // One isolated Deck instance serves the built UI and the API on one origin. |
| `frontend/src/components/shared/AgentStatusBadges.tsx` | 2 | 3 | 43, 66 | title={view.current ? 'Whether the agent session is alive.' : expired ? 'This status has expired.' : 'Deck has no status for this agent.'} |
| `frontend/src/features/agent-mail/ConversationsTab.tsx` | 1 | 1 | 150 | Deck loads the newest {CONVERSATION_LIMIT} threads. Older threads are not listed here. |
| `frontend/src/features/agent-mail/RosterRow.tsx` | 1 | 1 | 55 | <p className="text-xs text-muted-foreground" title="How Deck wakes this agent.">Wake method: {wakeMethods}</p> |
| `frontend/src/features/agent-mail/SenderLabel.tsx` | 1 | 1 | 9 | deck: { Icon: Cog, title: 'Sent by Deck, not by an agent', className: 'text-muted-foreground' }, |
| `frontend/src/features/agent-mail/actorAuth.ts` | 2 | 2 | 37, 41 | ...(directorKey ? { 'X-Deck-Operator-Token': directorKey } : {}), |
| `frontend/src/features/agent-mail/api.ts` | 3 | 3 | 22, 78, 124 | return token ? { 'X-Deck-Operator-Token': token } : {} |
| `frontend/src/features/agent-mail/conversations.ts` | 3 | 3 | 16, 36, 70 | { id: 'notices', label: 'Deck notices' }, |
| `frontend/src/features/agent-mail/mailSetup.ts` | 3 | 3 | 77, 115, 178 | case 'automatic_ready': return '✓ Ready · Deck adds it when it launches Pi' |
| `frontend/src/features/agent-mail/utils.ts` | 3 | 4 | 37, 40, 45 | export const LEGACY_SENDER_LABEL = 'Deck or Director (recorded before v3.1)' |
| `frontend/src/features/agent-teams/AgentActivityBadge.tsx` | 2 | 2 | 17, 25 | duplicate_native_identity: 'More than one Deck slot is configured to resume this native conversation. Per-agent activity cannot be distinguished.', |
| `frontend/src/features/agent-teams/AgentTeamsHelpDialog.tsx` | 3 | 3 | 92, 95, 99 | <li>Put <code>github_token</code> in <code>backend/.env</code> for polling private repos and restart Deck. App-backed dispatch also needs GitHub App s… |
| `frontend/src/features/agent-teams/AgentTeamsPage.tsx` | 1 | 1 | 656 | The new setting applies when the member receives new Deck instructions. |
| `frontend/src/features/agent-teams/AutonomyPanel.tsx` | 4 | 5 | 225, 235, 239, 282 | {gateStatus === 'active' && <p role="status" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm">Recovery-only mode is activ… |
| `frontend/src/features/agent-teams/BacklogCoordination.tsx` | 2 | 2 | 83, 213 | awaiting_assessment: 'Waiting for the Leader’s backlog assessment', unknown: 'Deck has not read the backlog yet', |
| `frontend/src/features/agent-teams/OperatorTokenDialog.tsx` | 3 | 4 | 38, 41, 44 | Paste the Director key for this Deck installation. It is the value of <code>OPERATOR_TOKEN</code> on the server. Deck keeps it in this browser tab onl… |
| `frontend/src/features/agent-teams/RepositorySettings.tsx` | 1 | 1 | 93 | <Row label="Who merges">{scope.merge_policy === 'auto' ? 'Deck merges after checks pass' : 'You (human merge)'}</Row> |
| `frontend/src/features/agent-teams/ScopeSettingsDialogs.tsx` | 4 | 4 | 257, 307, 356, 391 | Existing clone under your home directory. Deck creates one worktree per issue next to it, in the same parent folder, and launches the owner there. Nor… |
| `frontend/src/features/agent-teams/TeamSummaryCard.tsx` | 7 | 7 | 17-19, 26, 30, 32, 204 | hold: 'This team is on HOLD. Deck admits no new work.', |
| `frontend/src/features/agent-teams/WorkItemActions.tsx` | 4 | 4 | 109, 314, 498, 540 | return 'Recovery revision ${item.active_scope_revision} was submitted; Deck is checking the PR.' |
| `frontend/src/features/agent-teams/WorkPublicationPanel.tsx` | 2 | 2 | 172, 217 | const actors = { owner: ownerName ?? 'Assigned owner', leader: 'Team Leader', operator: 'Director', controller: 'Deck', none: 'None' } |
| `frontend/src/features/agent-teams/api.ts` | 2 | 2 | 220, 336 | return { 'X-Deck-Operator-Token': operatorToken } |
| `frontend/src/features/agent-teams/scopeAuthStatus.ts` | 4 | 6 | 6, 11, 16, 21 | help: 'Set github_token in backend/.env and restart Deck. The watcher uses this host token to poll GitHub; private repos cannot be polled through App … |
| `frontend/src/features/agent-teams/useWorkItemOperations.tsx` | 1 | 1 | 91 | Deck defers re-dispatch until the current owner releases it. Review the work item before continuing. |
| `frontend/src/features/agent-teams/workItemAttention.ts` | 1 | 1 | 33 | return { label: 'Your intervention is needed', reason: 'Deck stopped this attempt. Open the details to inspect the reason and available recovery actio… |
| `frontend/src/features/cc-bridge/ImageAttachmentDialog.tsx` | 1 | 1 | 100 | This terminal is read-only. Enter the Deck operator token to switch to interactive mode before pasting into tmux. |
| `frontend/src/features/cc-bridge/KillSessionDialog.tsx` | 2 | 2 | 47, 65 | setError('Enter the Deck operator token to terminate a session.') |
| `frontend/src/features/cc-bridge/api.ts` | 6 | 6 | 70, 83, 99, 113, 126, 168 | headers: { 'X-Deck-Operator-Token': operatorToken }, |
| `frontend/src/features/factory/NeedsALookPanel.tsx` | 1 | 1 | 93 | Deck read only the newest request events. Older refusals in this window are not counted. |
| `frontend/src/features/factory/RepositorySetupPage.tsx` | 7 | 7 | 238, 373, 688, 791, 887, 891, 905 | headers: { "X-Deck-Operator-Token": operatorToken }, |
| `frontend/src/features/factory/auditFeed.ts` | 3 | 3 | 182, 257, 309 | return "Deck"; |
| `frontend/src/features/factory/auditRefusals.ts` | 2 | 2 | 35, 38 | active_continuation_cancel_conflict: "The active plan changed, so Deck could not cancel it.", |
| `frontend/src/features/factory/auditSummary.ts` | 1 | 1 | 155 | help: "Deck has no measured usage attribution, so it reports no cost.", |
| `frontend/src/features/factory/components/ProtectedRemedies.tsx` | 4 | 4 | 102-103, 137, 175 | ? "Retry reset this work item to pending. Deck has not yet seen a new dispatch." |
| `frontend/src/features/factory/components/RepositoryTable.tsx` | 1 | 1 | 18 | <caption className="sr-only">Repositories that Deck watches</caption> |
| `frontend/src/features/factory/components/RequiredCiNotice.tsx` | 1 | 1 | 23 | Deck cannot read the required checks |
| `frontend/src/features/factory/components/overview/CampaignBar.tsx` | 1 | 1 | 5 | // shows the whole campaign. Without one it shows only the work that Deck has |
| `frontend/src/features/factory/components/overview/CampaignProgress.tsx` | 1 | 1 | 70 | The backlog cannot be read, so Deck shows only the work it has seen. |
| `frontend/src/features/factory/components/overview/statusSentence.ts` | 2 | 2 | 13, 15 | return { tone: "warn", text: "Recovery-only mode. Deck blocks normal intake." }; |
| `frontend/src/features/factory/components/requiredCiReason.ts` | 1 | 1 | 9 | unknown: "Deck does not know why the checks cannot be read.", |
| `frontend/src/features/factory/filterHelpers.ts` | 1 | 1 | 47 | // reason is the one line that Deck gives for the intake state. |
| `frontend/src/features/factory/pages/WorkDetailPage.tsx` | 1 | 1 | 94 | <Time value={w.item.updated_at} label="Deck record updated" /> |
| `frontend/src/features/harnesses/HarnessesPage.tsx` | 2 | 2 | 113, 190 | {harnesses[id]} has no settings pages in Deck. <Link className="text-primary underline" to="/teams">Open Teams</Link> or <Link className="text-primary… |
| `frontend/src/features/native-settings/LegacyNativeRedirect.tsx` | 1 | 1 | 22 | <p>Deck found no harness for <code>{pathname}</code>. Open Harnesses to see what is installed.</p> |
| `frontend/src/features/projects/ProjectSelector.tsx` | 3 | 3 | 43, 66, 87 | setError(err instanceof Error ? err.message : 'Deck could not add this folder.'); |
| `frontend/src/features/projects/ProjectsPage.tsx` | 2 | 2 | 2, 24 | * "Folders Deck knows about": the folders that a project-scoped Harness page can use. |
| `frontend/src/features/providers/ProviderLaunchOptionsFields.tsx` | 1 | 2 | 119 | <p className="text-sm text-muted-foreground">OpenRouter · default moonshotai/kimi-k3. Agent Mail requires the Deck extension; Pi tools are not sandbox… |
| `frontend/src/lib/agentStatus.ts` | 6 | 7 | 17, 20, 32, 37-38, 70 | wake_target_stale: 'The wake target is out of date. Deck cannot confirm it.', |
| `frontend/src/lib/api.ts` | 1 | 1 | 14 | return token ? { 'X-Deck-Operator-Token': token } : {} |
| `frontend/src/types/agentTeams.ts` | 1 | 1 | 194 | // Missing on an older server. Null means Deck could not read it. |
| `frontend/tests/agent-activity-badge.test.tsx` | 1 | 1 | 6 | it('explains that a session needs a restart before Deck can observe it', () => { |
| `frontend/tests/agent-mail-authentication.test.tsx` | 4 | 4 | 128, 140-141, 143 | expect(options.headers['X-Deck-Operator-Token']).toBe('test-director-key') |
| `frontend/tests/agent-mail-conversations.test.tsx` | 7 | 7 | 68, 223-224, 243, 245, 258, 290 | it('collapses Deck notices with the same subject and recipient and counts them', () => { |
| `frontend/tests/agent-mail-sender.test.tsx` | 7 | 9 | 28, 38, 47-48, 84, 102, 115 | deck: message(1, { sender_type: "system", sender_name: "Deck" }), |
| `frontend/tests/agent-mail-setup.test.tsx` | 1 | 1 | 163 | expect(screen.getByText(/✓ Ready · Deck adds it when it launches Pi/)).toBeInTheDocument() |
| `frontend/tests/audit-client-boundary.test.ts` | 3 | 3 | 40, 45, 62 | expect(metricHeaders["X-Deck-Operator-Token"]).toBeUndefined(); |
| `frontend/tests/audit-feed.test.ts` | 1 | 1 | 51 | expect(rows[0].action).toBe("did something that Deck does not describe on"); |
| `frontend/tests/audit-metrics.test.tsx` | 4 | 4 | 165, 170, 274, 386 | expect(stub.metrics()[0].headers["X-Deck-Operator-Token"]).toBeUndefined(); |
| `frontend/tests/autonomy-panel.test.tsx` | 2 | 2 | 204, 212 | expect(within(dialog).getByText('Deck needs the key to read audit events.')).toBeInTheDocument() |
| `frontend/tests/backlog-coordination.test.tsx` | 2 | 2 | 185, 197 | method: 'PUT', headers: { 'X-Deck-Operator-Token': 'fixture-token' }, |
| `frontend/tests/creation-client-authz.test.ts` | 2 | 2 | 35, 69 | expect(headers['X-Deck-Operator-Token']).toBe('client-operator-token') |
| `frontend/tests/factory.test.tsx` | 5 | 5 | 454, 524, 538, 551, 892 | new Headers(options.headers).get("X-Deck-Operator-Token") === |
| `frontend/tests/fixtures/provider-operations/v1/catalog.json` | 33 | 33 | 12, 26, 502, 516, 944, 958, 1114, 1129, 1366, 1380, 1536, 1551, 1788, 1805, 1925, 1939, 2211, 2225, 2361, 2635, 2649, 3077, 3091, 3519, 3533, 3961, 3975, 4403, 4417, 4845, 4859, 5287, 5301 | "reason": "Deck has a validated native launch contract.", |
| `frontend/tests/harness-list.test.tsx` | 1 | 1 | 63 | expect(within(card('Pi')).getByText(/No settings pages in Deck/)).toBeInTheDocument() |
| `frontend/tests/harness-page.test.tsx` | 1 | 1 | 93 | expect(screen.getByText(/has no settings pages in Deck/)).toBeInTheDocument() |
| `frontend/tests/new-session-dialog.test.tsx` | 1 | 1 | 124 | expect(within(dialog).getByText(/Deck needs the key to start a session\./)).toBeInTheDocument() |
| `frontend/tests/operator-write-headers.test.ts` | 1 | 1 | 11 | expect(operatorWriteHeaders(method)).toEqual({ 'X-Deck-Operator-Token': 'director-key' }) |
| `frontend/tests/overview.test.tsx` | 2 | 2 | 29, 261 | preset_id: 1, description: 'Release Deck v3.0.1.', parent_issue_url: 'https://github.com/o/r/issues/490', |
| `frontend/tests/provider-operations.test.tsx` | 1 | 1 | 63 | expect(screen.getAllByText('No settings pages in Deck')).toHaveLength(4) |
| `frontend/tests/repository-pages.test.tsx` | 1 | 1 | 51 | const table = await screen.findByRole("table", { name: "Repositories that Deck watches" }); |
| `frontend/tests/repository-settings.test.tsx` | 1 | 1 | 103 | expect(screen.getByText(/Deck does not run a build/)).toBeInTheDocument() |
| `frontend/tests/repository-setup.test.tsx` | 4 | 4 | 95, 1736, 1787, 1829 | expect(within(dialog).getByText("Deck needs the key to check access to this repository.")).toBeInTheDocument(); |
| `frontend/tests/required-ci-unreadable.test.tsx` | 4 | 4 | 33, 84, 126-127 | 'Deck will poll again. Unreadable checks do not grant verification or consume a retry.', |
| `frontend/tests/team-page.test.tsx` | 5 | 5 | 48, 59, 106, 165, 188 | id: 1, name: 'major-release-v3', description: 'Release Deck v3.0.0 and its website.', created_at: stamp, updated_at: stamp, |
| `frontend/tests/team-summary-card.test.tsx` | 2 | 2 | 33, 80 | description: 'Release Deck v3.0.1 and its website.', |
| `frontend/tests/team-url.test.tsx` | 1 | 1 | 174 | expect(within(dialog).getByText('Deck needs the key to plan a launch.')).toBeInTheDocument() |
| `frontend/tests/terminal-authority.test.ts` | 3 | 3 | 17, 29, 48 | expect.objectContaining({ headers: expect.not.objectContaining({ 'X-Deck-Operator-Token': expect.anything() }) }), |
| `frontend/tests/work-item-actions.test.tsx` | 4 | 4 | 222, 238, 264, 300 | expect(resume.headers.get('X-Deck-Operator-Token')).toBe('test-token') |
| `integrations/pi-agent-mail/README.md` | 3 | 3 | 12, 23, 26 | The command reads tool definitions. It does not register an agent or call the Deck API. |
| `integrations/pi-agent-mail/extension.ts` | 1 | 1 | 30 | ctx.ui.notify('Deck Agent Mail is unavailable or fenced. Tools remain disabled; operator recovery may be required.', 'error') |
| `integrations/pi-agent-mail/manifest.ts` | 1 | 1 | 298 | "description": "Read current requests and issue instruction templates. This grants no authority.\n\n The Leader must publish completed templates near … |
| `integrations/pi-agent-mail/tests/client.test.ts` | 1 | 1 | 130 | test('mapping failure preserves a definitive Deck outcome rather than replacing it', () => { |
| `scripts/ci/docs_only.py` | 1 | 1 | 8 | 'success' either way, because Deck accepts a required check only with that |
| `scripts/e2e-agent-mail-same-repo-codex.sh` | 1 | 1 | 3 | # The planner intentionally stops after requesting review, so success requires Deck |
| `scripts/e2e-instance.sh` | 10 | 10 | 2, 7, 29, 48, 55, 129, 141, 147, 151, 202 | # Start one isolated Deck instance for the E2E journeys. |
| `scripts/e2e/fake-harness.sh` | 2 | 2 | 2, 7 | # Fake harness binary for the Deck E2E instance. No network, no credentials. |
| `scripts/e2e/scenarios.py` | 2 | 2 | 1, 269 | """Synthetic E2E scenarios for the Deck v3.1 design reference. |
| `scripts/e2e/seed.py` | 3 | 3 | 2, 30, 39 | """Seed the Deck E2E database with deterministic, synthetic state. |
| `scripts/product-factory/product-supervisor` | 1 | 1 | 9 | req=urllib.request.Request(API+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'Content-Type':'application/json',… |
| `scripts/product-factory/productctl` | 1 | 1 | 7 | req=urllib.request.Request(URL+'/api/v1'+path,data=None if body is None else json.dumps(body).encode(),method=method,headers={'Content-Type':'applicat… |
| `scripts/product-factory/team-supervisor` | 1 | 1 | 134 | request = urllib.request.Request(self.config['api'] + path, data=None if body is None else json.dumps(body).encode(), method=method, headers={'Content… |
| `skills/deck-factory-supervisor/SKILL.md` | 7 | 7 | 3, 6, 32, 45, 52, 54, 60 | description: Prepare, supervise, maintain and finish a Deck team working on a GitHub backlog when the operator delegates factory execution. Use for te… |
| `skills/deck-factory-supervisor/agents/openai.yaml` | 3 | 3 | 2-4 | display_name: "Deck Factory Supervisor" |

### 5.2 Joined and camel-case spellings (`claudedeck`, domain, `ClaudeDeck`)

Search: `git grep -I -n -i -E 'claudedeck' <pin> -- .`, which catches `claudedeck.org` and every camel-case joining. Case variants of the six primary terms are **not** here: the primary search is case-insensitive, so they are already in section 4.
Whole set: 27 lines, 28 occurrences, 9 distinct files. Of these, 10 lines are already primary lines in section 4. The table lists the **17 non-primary lines** (18 occurrences, 8 distinct files). The one code identifier in this set is the generated OpenCode plugin export at `backend/app/services/agent_mail_install_service.py:599`; the rest are the old domain in current docs and in the rename campaign's own records.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `DOCUMENTATION_PUBLISHING.md` | 1 | 1 | 3 | This playbook rebuilds the public documentation at <https://claudedeck.org/docs/> from the maintained documentation in this repository, copies the gen… |
| `README.md` | 1 | 2 | 3 | **Website**: [claudedeck.org](https://claudedeck.org) |
| `backend/app/services/agent_mail_install_service.py` | 1 | 1 | 599 | export const ClaudeDeckAgentMailPlugin = async (ctx) => { |
| `docs/.vitepress/theme/custom.css` | 1 | 1 | 9 | /* Backgrounds — match claudedeck.org */ |
| `docs/plans/2026-10-15-director-website/01-audit.md` | 1 | 1 | 5 | Purpose. This document audits claudedeck.org and the Deck documentation for a non-technical director. |
| `docs/plans/2026-11-06-rename-synth-city/README.md` | 3 | 3 | 30, 52, 71 | - **'claudedeck.org' redirects every path** to 'albiex.org' (301 redirects). |
| `docs/plans/2026-11-06-rename-synth-city/transfer-runbook.md` | 4 | 4 | 22, 266, 706, 825 | (§5). The public domain moves separately: 'claudedeck.org' will redirect |
| `docs/plans/2026-11-06-rename-synth-city/website-and-docs.md` | 5 | 5 | 43, 87, 626, 684, 707 | \| Old domain \| 'claudedeck.org' redirects every path to 'albiex.org' with 301 redirects \| campaign 'README.md:30' \| |

### 5.3 `deck_` names

Search: `git grep -I -n -E 'deck_[a-z0-9_]+' <pin> -- .` (case-sensitive, as the names are).
Whole set: 1,027 lines, 1,155 occurrences of 82 distinct tokens, 106 distinct files; 40 of those lines are already primary. The file table lists the **987 non-primary lines** (1,104 occurrences, 103 distinct files). Not every `deck_` token is an Agent Mail tool: the token table after the file table separates the 36 tools actually defined in `backend/mcp_shim/agent_mail_server.py` (the surface #789 renames under a new prefix still to be chosen, with no old-name alias window after the 2026-11-08 Director decision) from other tokens such as storage keys and test names, which follow ordinary identifier rules in #789.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `backend/app/api/v1/agent_bridge/router.py` | 2 | 2 | 319, 322 | x_deck_operator_token: str \| None = Header(default=None), |
| `backend/app/api/v1/agent_mail.py` | 28 | 29 | 77, 81, 90-91, 95-99, 102, 107, 110-111, 936-937, 944, 948, 951, 960, 963, 1029, 1043, 1045, 1091, 1237, 1241, 1266, 1270 | x_deck_operator_token: Optional[str] = Header(default=None), |
| `backend/app/api/v1/agent_teams.py` | 1 | 1 | 1112 | raise HTTPException(status_code=409, detail="use_deck_approve_work_item") |
| `backend/app/api/v1/cc_bridge/router.py` | 2 | 2 | 55, 58 | x_deck_operator_token: str \| None = Header(default=None), |
| `backend/app/api/v1/deps.py` | 16 | 16 | 67, 71, 76, 97, 100, 102, 120, 159, 162, 172, 187, 191-192, 196-198 | x_deck_session_token: Optional[str] = Header(default=None), |
| `backend/app/database.py` | 6 | 6 | 394, 401, 784, 789, 801, 1125 | "CREATE TABLE IF NOT EXISTS deck_compat_migrations (" |
| `backend/app/models/schemas.py` | 1 | 1 | 2260 | deck_url: str |
| `backend/app/services/agent_mail_install_service.py` | 9 | 10 | 69, 87, 120, 675, 887, 1086-1089 | def deck_base_url() -> str: |
| `backend/app/services/agent_mail_service.py` | 3 | 5 | 2662-2663, 2680 | "Coordinate via MCP tools: deck_check_inbox, deck_request_context, " |
| `backend/app/services/agent_team_service.py` | 1 | 2 | 1698 | "Call 'deck_whoami' when the session starts, then check your inbox with 'deck_check_inbox(unread_only=False)'.", |
| `backend/app/services/factory_audit_service.py` | 4 | 4 | 956, 960, 976, 983 | " AND name = 'deck_compat_migrations'"))).first() |
| `backend/app/services/github_approval_service.py` | 4 | 4 | 885, 887, 901, 904 | "'deck_check_inbox(unread_only=False)' now, find delivery message " |
| `backend/app/services/github_coordination_service.py` | 5 | 5 | 569, 572, 575, 580, 596 | f"deck_get_backlog_coordination(scope_id={scope_id}) for the current request, " |
| `backend/app/services/github_dispatch_service.py` | 31 | 31 | 1431, 1440, 1453, 1460, 1466, 1469, 1500, 1782, 1784, 1786, 1794, 1801, 1806, 1817, 1820, 1828, 1842, 1844, 1848, 1884, 2231, 2233, 3261, 3290, 3294, 3499-3500, 3582, 3607, 3839, 3947 | "- Use deck_send_message with to_supervisor_actor_id for the current bound Supervisor.", |
| `backend/app/services/github_owner_followup_service.py` | 2 | 2 | 589, 591 | f"Call deck_get_backlog_coordination(scope_id={watch.scope_id}). Inspect owner_followups " |
| `backend/app/services/github_workspace_service.py` | 2 | 2 | 23, 274 | from app.services.agent_mail_install_service import deck_base_url |
| `backend/app/services/pi_mail_readiness.py` | 1 | 1 | 42 | from app.services.agent_mail_install_service import deck_base_url, shim_path |
| `backend/app/services/team_communication_policy.py` | 4 | 4 | 21-22, 41, 57 | Before requesting human input, call deck_prepare_operator_action_contexts for the intended requests. |
| `backend/mcp_shim/agent_mail_hook.py` | 1 | 1 | 81 | f"{args.deck_url.rstrip('/')}/api/v1/agent-mail/hooks/{args.event}", |
| `backend/mcp_shim/agent_mail_server.py` | 63 | 64 | 52, 78, 114, 159, 163, 178, 205, 209, 311, 332-333, 357, 385, 416, 434, 437-438, 467, 503, 512, 542, 551, 587, 628, 669, 693, 708, 725, 736, 769, 807, 854, 865, 884, 894, 925, 941, 953, 976, 989, 1001, 1008, 1030, 1039, 1042, 1059, 1076, 1114, 1168, 1192, 1217, 1234, 1238, 1305, 1320, 1336, 1342, 1367, 1386, 1410, 1436, 1438, 1440 | "error": {"code": "deck_unreachable", "message": message}, |
| `backend/mcp_shim/git_credential_helper.py` | 3 | 3 | 25, 38, 64 | deck_url: str, |
| `backend/tests/agent_mail/test_api.py` | 2 | 2 | 3228, 3391 | curl_available=False, shim_path="test-shim", python_path="test-python", deck_url="http://test") |
| `backend/tests/agent_mail/test_context.py` | 2 | 2 | 57, 83 | assert "deck_check_inbox" in ctx |
| `backend/tests/agent_mail/test_dispatch_status_tool.py` | 10 | 10 | 459, 1202-1204, 1226, 1274-1275, 1296, 1364, 1469 | assert resp.json()["detail"] == "use_deck_approve_work_item" |
| `backend/tests/agent_mail/test_install.py` | 1 | 1 | 501 | deck_url="http://127.0.0.1:8000", |
| `backend/tests/agent_mail/test_lease_token_redaction.py` | 1 | 1 | 23 | "deck_report_dispatch_status(\n" |
| `backend/tests/agent_mail/test_mcp_shim.py` | 61 | 61 | 12, 27, 32, 35, 37, 56-57, 69, 125, 157, 185, 191, 227, 234, 245, 248, 307, 328, 332, 353, 363, 384, 388, 529, 575, 630, 644, 651, 657, 701, 732, 759, 819, 827, 838, 864, 866, 868, 880, 882, 893, 905-906, 910-911, 914, 938, 950, 953, 959, 973, 979, 989, 1001-1004, 1007, 1019, 1026, 1037 | assert callable(shim.deck_whoami) |
| `backend/tests/agent_mail/test_pi_manifest.py` | 8 | 12 | 29-34, 38-39 | "deck_get_backlog_coordination", "deck_report_backlog_assessment", |
| `backend/tests/agent_mail/test_pi_shim.py` | 12 | 14 | 68-69, 78, 99-100, 102-106, 162, 164 | assert shim.__deck_mail_close_generation() == {"ok": True, "closed": True} |
| `backend/tests/agent_mail/test_registry.py` | 1 | 1 | 44 | "deck_check_inbox(unread_only=False)", |
| `backend/tests/agent_mail/test_supervisor_shim.py` | 5 | 5 | 13, 29, 43, 57, 60 | assert shim.deck_supervisor_checkin(7, "2026-10-13T02:00:00Z") == { |
| `backend/tests/agent_teams/test_agent_team_campaign.py` | 1 | 1 | 95 | async def test_unreadable_backlog_keeps_deck_counts_and_unknown_not_started(db, monkeypatch): |
| `backend/tests/agent_teams/test_agent_team_service.py` | 1 | 1 | 1576 | assert "deck_retry_work_item" in calls[0][1].prompt |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | 20 | 20 | 573, 576, 590, 592, 607, 2067-2068, 2075, 2134, 2142, 4002, 4603-4604, 4796, 4802, 4806, 5072, 5217-5218, 5775 | assert "deck_retry_work_item" in text |
| `backend/tests/agent_teams/test_review_rework_guidance.py` | 1 | 1 | 51 | assert "deck_approve_work_item" in owner |
| `backend/tests/factory/test_factory_audit_metrics.py` | 1 | 1 | 5338 | "SELECT COUNT(*) FROM deck_compat_migrations WHERE name = :name"), |
| `docs/api/agent-bridge.md` | 3 | 3 | 141-143 | - 'deck_attach_image_to_bridge_session(target, file_path, submit, prompt)' |
| `docs/api/agent-mail.md` | 1 | 1 | 16 | External member reads and 'deck_list_team' include this object. |
| `docs/api/agent-teams.md` | 7 | 7 | 166, 221-222, 251-253, 264 | The current authenticated Leader publishes assessments through 'deck_report_backlog_assessment'. |
| `docs/autonomy.md` | 1 | 1 | 55 | context returned by 'deck_get_work_item_context' includes 'review_rework_guidance'; |
| `docs/deploy/attempt-recovery-pr1-rollout.md` | 5 | 5 | 59, 91, 98, 108-109 | FROM deck_compat_migrations |
| `docs/deploy/factory-maintenance-operations.md` | 2 | 2 | 7, 58 | Use 'deck_render_github_summary' with the latest body and public summary fields. The renderer updates only 'deck:current-summary'. It preserves human … |
| `docs/deploy/leader-backlog-coordination.md` | 6 | 6 | 86, 89, 120, 124, 266, 268 | On receipt, the Leader calls 'deck_get_backlog_coordination(scope_id)', reconciles |
| `docs/deploy/pi-provider-rollout.md` | 3 | 3 | 44, 60, 98 | Normal shutdown stops tools and heartbeat, privately requests '__deck_mail_close_generation', waits for a backend-committed close ACK, then closes its… |
| `docs/features/agent-mail.md` | 3 | 10 | 71, 106-107 | - The MCP server exposes 'deck_whoami', 'deck_list_team', 'deck_check_inbox', 'deck_send_message', 'deck_reply', 'deck_ack_message', 'deck_request_con… |
| `docs/features/agent-teams.md` | 1 | 1 | 97 | The owner supplies the estimate. The Leader calls 'deck_prepare_work_remaining_summary' after a safe published checkpoint or review handoff. |
| `docs/guide/supervised-factory-playbook.md` | 6 | 6 | 39-40, 269, 281, 313, 416 | Members find 'supervisor_address' in 'deck_whoami' and the dispatch brief. |
| `docs/plans/2026-10-11-v3.1-director-ui/director-ui-mockup.html` | 4 | 4 | 605, 611, 870, 876 | {n:'Leader', m:'Sonnet 5.5', s:'Working', lines:['<span class="d">› deck_report_backlog_assessment</span>',' assessed 5 items · 1 human action','<span… |
| `docs/plans/2026-11-06-rename-synth-city/README.md` | 1 | 2 | 42 | - **Also renamed (the Director's decision):** the Agent Mail tool names ('deck_check_inbox', 'deck_launch_team', …). They get a new prefix, and the ol… |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-implementation-plan.md` | 41 | 55 | 21, 454, 1248, 1267, 1304-1305, 1322, 1943, 1991, 2002, 2026, 2078-2081, 2163-2170, 2187, 2191, 2238, 2286, 2301, 2319, 2337-2340, 2357, 2385, 2399, 2404, 2425, 2558, 2989, 3479 | 7. **MCP shim is standalone** ('backend/mcp_shim/agent_mail_server.py'): imports only 'mcp' + 'httpx', never 'app.*', so it runs from any cwd via the … |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-review-for-patching.md` | 2 | 2 | 74-75 | - MCP 'deck_create_handoff' |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v3-implementation-plan.md` | 42 | 56 | 23, 495, 1334, 1353, 1390-1391, 1408, 2062, 2117, 2128, 2196, 2281-2284, 2398-2405, 2422, 2426, 2473, 2521, 2536, 2554, 2572-2575, 2592, 2620, 2623, 2635, 2640, 2661, 2796, 3303, 3925 | 7. **MCP shim is standalone** ('backend/mcp_shim/agent_mail_server.py'): imports only 'mcp' + 'httpx', never 'app.*', so it runs from any cwd via the … |
| `docs/plans/agent-mail/2026-06-14-codex-app-server-wakeups-implementation-plan.md` | 2 | 2 | 75, 100 | - Do not add user-facing chat transcripts for app-server wake turns in Agent Mail MVP follow-up. The wake turn's job is to get the agent to call 'deck… |
| `docs/plans/agent-mail/agent_mailbox_alternate_direction_evaluation.md` | 25 | 26 | 112, 116-118, 133, 153, 156, 173, 261-273, 279-281, 284 | The original plan relies heavily on inbox polling through 'deck_read_inbox'. That is technically simple but behaviorally weak. Agents may never notice… |
| `docs/plans/agent-mail/claude_deck_agent_mailbox_implementation_plan.md` | 42 | 43 | 153-164, 848, 1334, 1371, 1390, 1409, 1439, 1458, 1479, 1497, 1521, 1544, 1563, 1581, 1608, 1677, 1734-1738, 1880, 2399-2400, 2911, 3061-3062, 3149, 3151, 3157-3158 | - 'deck_whoami' |
| `docs/plans/product-reposition/experience-spec.md` | 1 | 1 | 111 | Loading a work page is an observational read. The page must not call agent tools such as 'deck_get_work_item_context', which can perform an owner cont… |
| `docs/plans/product-reposition/reconciliation-ledger.md` | 1 | 1 | 21 | Leader 'deck_list_work_items(status="")' and 'status="escalated"' both returned no items at startup. No cold-start retry applies. No dispatch workspac… |
| `docs/superpowers/plans/2026-07-04-autonomous-github-dispatch-phase-a.md` | 12 | 13 | 7, 40, 1476, 1484, 1487, 1635, 1638, 1642, 1668, 1678, 1689, 1840 | **Architecture:** New SQLAlchemy tables ('TeamGithubScope', 'GithubWorkItem') plus additive columns on the existing 'AgentTeamSlot'/'AgentTeamPreset' … |
| `docs/superpowers/plans/2026-07-06-autonomous-dispatch-hardening-and-soak.md` | 6 | 6 | 30, 291, 298, 300, 306, 327 | - 'backend/mcp_shim/agent_mail_server.py' — add 'ack_received' to the 'deck_report_dispatch_status' docstring's valid-status list. |
| `docs/superpowers/plans/2026-07-23-leader-owned-dependency-unblocking.md` | 17 | 18 | 7, 28, 167, 337, 344, 349, 422, 426, 442, 450, 479, 496, 498, 511, 537, 558, 641 | **Architecture:** Two generic Deck primitives + a leader-prompt addition. (1) A shared async notify helper on 'github_dispatch_service' fires a leader… |
| `docs/superpowers/plans/2026-07-23-leader-unblock-coldstart-followup.md` | 23 | 25 | 5, 16, 22, 33, 43, 60, 69, 73, 77, 119, 126, 134, 145, 148, 155, 168, 171, 179, 190, 217, 221, 226-227 | **Goal:** Close the Phase E cold-start seam (soak Finding 9): the leader knows an escalated dependent is unblocked at start-up but can't act because (… |
| `docs/superpowers/plans/2026-07-29-dispatch-workspace-provisioning.md` | 3 | 11 | 816, 1043, 1049 | Read design §2.10c before writing this. The short version: Deck has two classes of operator, and everything written above about "the operator" assumed… |
| `docs/superpowers/plans/2026-08-02-phase-g2-session-lifecycle.md` | 9 | 9 | 1708, 1954, 1959, 1961, 1963, 1973, 2010, 2341, 3153 | - Modify: 'backend/mcp_shim/agent_mail_server.py' (the 'deck_report_dispatch_status' docstring/params) |
| `docs/superpowers/plans/2026-08-09-pr0-agent-mail-capability-tokens.md` | 29 | 30 | 165, 1119, 1623, 2875, 3194, 3204, 3209, 3269, 3415, 3424, 3457, 3478, 3482, 3504, 3511, 3534, 3538, 3574, 3576, 3609, 3654, 4286, 4698, 4737, 4740, 4841, 4844, 4849, 4853 | \| **§3.5a's 'revision_requested' → '409 use_deck_approve_work_item'** \| The replacement tool 'deck_approve_work_item' is §4.3a, a PR1 artifact. Refu… |
| `docs/superpowers/plans/2026-08-11-pr1-approval-attribution-and-gate.md` | 14 | 18 | 218, 244, 603, 615, 617, 621, 777, 779, 781, 882, 997, 1009, 1013, 1015 | def deck_request_context( |
| `docs/superpowers/plans/2026-08-12-pr2-distinct-commit-and-pr-identity.md` | 3 | 3 | 89, 410, 736 | - Helper commands use 'http://127.0.0.1:{settings.port}' (the same value as 'deck_base_url()'), never a hard-coded port or '0.0.0.0'. |
| `docs/superpowers/plans/2026-08-29-pr1-approval-request-authority.md` | 5 | 5 | 40-41, 373-375 | **Planning correction — explicit initial approval:** Generic 'deck_request_context' remains |
| `docs/superpowers/plans/2026-08-29-pr2-non-destructive-attempt-continuation.md` | 6 | 6 | 340-341, 344-347 | - 'deck_request_continuation'; |
| `docs/superpowers/plans/2026-09-26-pi-provider-and-agent-mail.md` | 6 | 7 | 95, 106, 110, 112, 119, 205 | 6. Preserve exact names so Deck's existing 'deck_check_inbox' wake prompt remains valid. Expose the existing shim's full mail/team/approval/continuati… |
| `docs/superpowers/plans/2026-10-14-muse-code-harness.md` | 7 | 7 | 118, 222, 310, 430, 541, 567, 639 | Run: 'cd backend && venv/bin/python -m pytest tests/test_muse_provider.py -p deck_guard -q' |
| `docs/superpowers/specs/2026-06-29-agent-bridge-image-paste-design.md` | 3 | 3 | 498, 517, 523 | deck_attach_image_to_bridge_session( |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-design.md` | 5 | 7 | 164, 168-171 | **Prerequisite — generalize the shim's request helper.** '_request()' is hardwired to the Agent-Mail prefix ('API = .../api/v1/agent-mail', 'agent_mai… |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-e2e-tests.md` | 16 | 16 | 77, 98, 149, 151, 166, 177, 241, 243, 254, 260, 262, 269, 276-277, 294, 310 | deck_create_team( |
| `docs/superpowers/specs/2026-07-02-autonomous-github-dispatch-design.md` | 13 | 16 | 35, 64, 242, 246-247, 252, 254, 257, 274, 288, 311, 333, 394 | \| B1 — ownership doesn't travel with an internal handoff \| §5c/§5d (new 'deck_report_dispatch_status' tool with 'reassign_to_slot_id') \| |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-ui-mockups.html` | 2 | 2 | 264, 290 | <p>Companion to <code>2026-07-02-autonomous-github-dispatch-design.md</code>, <code>2026-07-03-autonomous-github-dispatch-workflows.md</code>, and <co… |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-workflows.html` | 6 | 6 | 197, 242, 250, 259, 348, 356 | Owner->>Brain: deck_report_dispatch_status(pr_opened, pr=101) |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-workflows.md` | 8 | 8 | 36, 75, 83, 92, 103, 172, 180, 256 | Owner->>Brain: deck_report_dispatch_status(pr_opened, pr=101) |
| `docs/superpowers/specs/2026-07-06-autonomous-dispatch-hardening-and-soak-design.md` | 1 | 1 | 72 | The monitor must know the owner's ack arrived, **without parsing mail bodies**. The owner already reports lifecycle via 'deck_report_dispatch_status' … |
| `docs/superpowers/specs/2026-07-06-dispatch-open-finding-leader-ack-timeout.md` | 1 | 1 | 7 | - Owner (Generalist, member 14) dispatched correctly, received its brief, and sent the leader (member 16) two 'deck_request_context' approval requests… |
| `docs/superpowers/specs/2026-07-06-tizonia-roadmap-v1-soak-run-log.md` | 17 | 22 | 102, 104, 106, 110, 113-114, 232, 299, 452, 458, 1018, 1368, 1432, 1483, 1487, 1550, 1814 | On start-up the Leader correctly built its dep map and reported (mail 222): "#817 -> #816[CLOSED] ... so #817 is logically clear ... Inbox contains no… |
| `docs/superpowers/specs/2026-07-23-leader-owned-dependency-unblocking-design.md` | 11 | 12 | 65, 73, 75, 84-85, 87, 98-99, 105, 113, 132 | The 'escalated_items' array is the scope's current 'escalated' work items (the candidate dependents). Each carries the 'issue_number' ↔ 'work_item_id'… |
| `docs/superpowers/specs/2026-07-27-closed-issue-reconciliation-design.md` | 1 | 1 | 64 | Of the 12 escalated items, exactly **one** changes: item 26 (#818) → 'completed', firing 'notify_blocker_merged' to the Leader, whose body already lis… |
| `docs/superpowers/specs/2026-07-27-escalation-inflight-safety-design.md` | 2 | 2 | 23, 25 | So the owner's eventual 'deck_report_dispatch_status(status="pr_opened", pr_number=N)' would have failed **HTTP 409**. The work existed, the PR existe… |
| `docs/superpowers/specs/2026-07-29-dispatch-workspace-provisioning-design.md` | 3 | 7 | 598, 621, 623 | Deck already treats non-human operators as first-class, and not incidentally — 'mcp_shim/agent_mail_server.py' exposes 18 'deck_*' tools, and the Agen… |
| `docs/superpowers/specs/2026-08-02-phase-g2-session-lifecycle-design.md` | 4 | 4 | 210, 319, 648, 926 | 'deck_report_dispatch_status'. |
| `docs/superpowers/specs/2026-08-05-distinct-approver-identity-design.md` | 75 | 99 | 53, 89, 126, 142, 154, 172, 196, 205, 398, 402, 582, 663, 728, 737, 767, 769, 939, 1130, 1140, 1215, 1348, 1415, 1417, 1453, 1456, 1649, 1729, 1868, 1872, 1886, 1903, 1914, 1933, 1939, 1996, 2002, 2006, 2008, 2017, 2022, 2069, 2074, 2084, 2088, 2096, 2107, 2191, 2502, 2506, 2525, 2527, 2668-2669, 2672, 2679-2681, 2692, 2699-2700, 2705, 2709, 2984, 3246, 3384, 3386, 3433, 3478, 3510, 3512, 4309, 4523, 4535, 4544, 4553 | **What revision 13 changed** — revised after a twelfth implementer review of '7c850a9' returned three blockers and three corrections. All six confirme… |
| `docs/superpowers/specs/2026-08-29-autonomous-attempt-recovery-design.md` | 18 | 18 | 480, 545, 591, 639, 645, 879, 966-970, 972, 982, 985, 987, 993, 1188, 1333 | deck_request_continuation(...) |
| `frontend/src/features/agent-mail/AgentMailHelpDialog.tsx` | 4 | 6 | 57-58, 74-75 | <li>Have each agent call <code>deck_whoami</code> once from its repo.</li> |
| `frontend/src/features/agent-mail/AgentMailPage.tsx` | 1 | 1 | 364 | Agent Bridge can see the Codex tmux session. Ask that agent to run <code>deck_whoami</code> once from its repository so Agent Mail can mark it connect… |
| `frontend/src/features/agent-mail/mailSetup.ts` | 1 | 1 | 115 | { label: 'Deck URL', value: status.deck_url }, |
| `frontend/src/features/agent-teams/AgentTeamsHelpDialog.tsx` | 3 | 3 | 84-86 | Use Agent Mail for the actual coordination. Agents should call <code>deck_whoami</code> |
| `frontend/src/types/agentMail.ts` | 1 | 1 | 140 | deck_url: string |
| `frontend/tests/agent-mail-setup.test.tsx` | 1 | 1 | 63 | deck_url: 'http://localhost:8000', |
| `integrations/pi-agent-mail/client.ts` | 3 | 3 | 168, 185, 207 | const identity = adaptResult(await this.client.callTool({ name: 'deck_whoami', arguments: {} }, undefined, { timeout: 20000 })) |
| `integrations/pi-agent-mail/manifest.ts` | 84 | 88 | 3, 30, 35, 47, 52-53, 84, 89, 116, 121, 136, 141, 188, 193-194, 238, 243, 275, 280, 292, 297, 309, 314, 326, 331, 343, 348-349, 390, 395, 407, 412, 424, 429, 433, 438, 442, 447-448, 462, 467, 489, 494-495, 531, 536, 557, 562, 628, 633, 663, 668, 685, 690-691, 733, 738, 876, 881-882, 918, 923-924, 984, 989, 1069, 1074-1075, 1109, 1114, 1131, 1136-1137, 1175, 1180, 1209, 1214, 1266, 1271, 1295, 1300, 1304, 1312, 1316 | "name": "deck_ack_continuation", |
| `integrations/pi-agent-mail/sync_manifest.py` | 1 | 1 | 32 | elif tool.name == "__deck_mail_close_generation": |
| `integrations/pi-agent-mail/tests/client.test.ts` | 11 | 12 | 31, 33, 35, 44, 93, 103, 111, 122, 135, 143, 146 | assert(manifest.some(tool => tool.name === 'deck_decide_continuation' && tool.inputSchema.required.includes('approval_request_id' as never))) |
| `integrations/pi-agent-mail/tests/fake-server.mjs` | 3 | 3 | 22, 25, 28 | const result = request.params.name === '__deck_mail_close_generation' |
| `integrations/pi-agent-mail/tests/pi-runtime.test.ts` | 12 | 12 | 28-29, 32-39, 41, 73 | assert.deepEqual(validate('deck_check_inbox', { unread_only: false, limit: 10 }), { unread_only: false, limit: 10 }) |
| `scripts/attempt-recovery-preflight.sh` | 10 | 11 | 9, 31-36, 190-191, 217 | deck_base_url=${1%/} |
| `scripts/e2e-agent-mail-same-repo-codex.sh` | 5 | 7 | 231-232, 235, 253, 255 | "First call deck_whoami and deck_list_team. Find the teammate named \"" + $reviewer + "\". " + |
| `scripts/generate-pi-mail-manifest.py` | 2 | 2 | 13, 30 | spec = importlib.util.spec_from_file_location("deck_pi_manifest", root / "backend/mcp_shim/agent_mail_server.py") |
| `skills/deck-factory-supervisor/SKILL.md` | 4 | 4 | 14, 29, 39-40 | Use 'deck_get_team_summary' to read existing attention, human actions, HOLD, pauses, effort totals, and next actors. |

Token totals over the **whole** `deck_` set (primary-overlap lines included), so each tool's full footprint is visible:

| Token | Kind | Occurrences | Lines | Files |
|---|---|---:|---:|---:|
| `deck_check_inbox` | MCP tool (defined `agent_mail_server.py:416`) | 80 | 77 | 30 |
| `deck_report_dispatch_status` | MCP tool (defined `agent_mail_server.py:1168`) | 79 | 79 | 24 |
| `deck_retry_work_item` | MCP tool (defined `agent_mail_server.py:1305`) | 74 | 74 | 17 |
| `deck_request_context` | MCP tool (defined `agent_mail_server.py:725`) | 62 | 61 | 20 |
| `deck_list_work_items` | MCP tool (defined `agent_mail_server.py:1234`) | 54 | 53 | 16 |
| `deck_whoami` | MCP tool (defined `agent_mail_server.py:357`) | 48 | 48 | 25 |
| `deck_approve_work_item` | MCP tool (defined `agent_mail_server.py:542`) | 46 | 44 | 14 |
| `deck_base_url` | other `deck_` token | 39 | 39 | 9 |
| `deck_send_message` | MCP tool (defined `agent_mail_server.py:434`) | 39 | 39 | 19 |
| `deck_operator_token` | other `deck_` token | 36 | 36 | 6 |
| `deck_create_handoff` | MCP tool (defined `agent_mail_server.py:769`) | 32 | 32 | 14 |
| `deck_session_token` | other `deck_` token | 31 | 31 | 4 |
| `deck_reply` | MCP tool (defined `agent_mail_server.py:467`) | 29 | 28 | 14 |
| `deck_request` | other `deck_` token | 27 | 25 | 8 |
| `deck_launch_team` | MCP tool (defined `agent_mail_server.py:1030`) | 25 | 24 | 11 |
| `deck_get_work_item_context` | MCP tool (defined `agent_mail_server.py:1217`) | 22 | 22 | 12 |
| `deck_plan_team_launch` | MCP tool (defined `agent_mail_server.py:1001`) | 21 | 21 | 8 |
| `deck_request_work_item_approval` | MCP tool (defined `agent_mail_server.py:503`) | 21 | 21 | 9 |
| `deck_list_team` | MCP tool (defined `agent_mail_server.py:385`) | 20 | 19 | 11 |
| `deck_url` | other `deck_` token | 20 | 20 | 12 |
| `deck_ack_message` | MCP tool (defined `agent_mail_server.py:708`) | 19 | 19 | 11 |
| `deck_mail_close_generation` | other `deck_` token | 19 | 19 | 11 |
| `deck_create_team` | MCP tool (defined `agent_mail_server.py:894`) | 18 | 18 | 10 |
| `deck_get_backlog_coordination` | MCP tool (defined `agent_mail_server.py:1320`) | 16 | 16 | 9 |
| `deck_decide_continuation` | MCP tool (defined `agent_mail_server.py:628`) | 15 | 15 | 10 |
| `deck_prepare_work_remaining_summary` | MCP tool (defined `agent_mail_server.py:1114`) | 14 | 14 | 10 |
| `deck_compat_migrations` | other `deck_` token | 13 | 13 | 5 |
| `deck_prepare_operator_action_contexts` | MCP tool (defined `agent_mail_server.py:1386`) | 13 | 13 | 9 |
| `deck_report_backlog_assessment` | MCP tool (defined `agent_mail_server.py:1410`) | 13 | 13 | 10 |
| `deck_report_owner_followup` | MCP tool (defined `agent_mail_server.py:1336`) | 13 | 13 | 10 |
| `deck_request_continuation` | MCP tool (defined `agent_mail_server.py:587`) | 13 | 13 | 7 |
| `deck_unreachable` | other `deck_` token | 13 | 13 | 9 |
| `deck_ack_continuation` | MCP tool (defined `agent_mail_server.py:669`) | 12 | 12 | 7 |
| `deck_get_operator_action_contexts` | MCP tool (defined `agent_mail_server.py:1367`) | 12 | 12 | 9 |
| `deck_supervisor_checkin` | MCP tool (defined `agent_mail_server.py:178`) | 10 | 10 | 7 |
| `deck_get_team_summary` | MCP tool (defined `agent_mail_server.py:989`) | 9 | 9 | 7 |
| `deck_update_team_campaign` | MCP tool (defined `agent_mail_server.py:953`) | 8 | 8 | 3 |
| `deck_attach_image_to_bridge_session` | MCP tool (defined `agent_mail_server.py:807`) | 7 | 7 | 5 |
| `deck_guard` | other `deck_` token | 7 | 7 | 1 |
| `deck_read_inbox` | other `deck_` token | 7 | 7 | 2 |
| `deck_update_team_parent_issue` | MCP tool (defined `agent_mail_server.py:941`) | 7 | 7 | 5 |
| `deck_list_agents` | other `deck_` token | 6 | 6 | 2 |
| `deck_list_bridge_attachments` | MCP tool (defined `agent_mail_server.py:854`) | 6 | 6 | 5 |
| `deck_list_scope_revisions` | MCP tool (defined `agent_mail_server.py:693`) | 6 | 6 | 5 |
| `deck_render_github_summary` | MCP tool (defined `agent_mail_server.py:1076`) | 6 | 6 | 5 |
| `deck_list_teams` | MCP tool (defined `agent_mail_server.py:884`) | 5 | 5 | 4 |
| `deck_paste_bridge_attachment` | MCP tool (defined `agent_mail_server.py:865`) | 5 | 5 | 4 |
| `deck_reserve_paths` | other `deck_` token | 4 | 4 | 2 |
| `deck_set_status` | other `deck_` token | 4 | 4 | 2 |
| `deck_check_path_conflicts` | other `deck_` token | 3 | 3 | 2 |
| `deck_http_error` | other `deck_` token | 3 | 3 | 2 |
| `deck_list_path_leases` | other `deck_` token | 3 | 3 | 2 |
| `deck_mailbox_mcp` | other `deck_` token | 3 | 3 | 1 |
| `deck_release_paths` | other `deck_` token | 3 | 3 | 2 |
| `deck_down` | other `deck_` token | 2 | 2 | 2 |
| `deck_mailbox_hooks` | other `deck_` token | 2 | 2 | 1 |
| `deck_request_preserves_a_callers_headers` | other `deck_` token | 2 | 2 | 2 |
| `deck_request_sends_no_header_without_a_token` | other `deck_` token | 2 | 2 | 2 |
| `deck_request_sends_the_session_token` | other `deck_` token | 2 | 2 | 2 |
| `deck_status` | other `deck_` token | 2 | 2 | 1 |
| `deck_version` | other `deck_` token | 2 | 2 | 1 |
| `deck_agent_mailbox_implementation_plan` | other `deck_` token | 1 | 1 | 1 |
| `deck_attach_image_to_bridge_session_rejects_missing_file` | other `deck_` token | 1 | 1 | 1 |
| `deck_attach_image_to_bridge_session_uploads_and_pastes` | other `deck_` token | 1 | 1 | 1 |
| `deck_check_inbox_returns_deck_unreachable_on_http_error` | other `deck_` token | 1 | 1 | 1 |
| `deck_counts_and_unknown_not_started` | other `deck_` token | 1 | 1 | 1 |
| `deck_create_team_posts_to_team_api` | other `deck_` token | 1 | 1 | 1 |
| `deck_join_scope` | other `deck_` token | 1 | 1 | 1 |
| `deck_launch_team_forwards_confirm_hash` | other `deck_` token | 1 | 1 | 1 |
| `deck_launch_team_requires_plan_hash` | other `deck_` token | 1 | 1 | 1 |
| `deck_list_bridge_attachments_uses_bridge_api` | other `deck_` token | 1 | 1 | 1 |
| `deck_list_scopes` | other `deck_` token | 1 | 1 | 1 |
| `deck_list_team_uses_cached_roster` | other `deck_` token | 1 | 1 | 1 |
| `deck_list_work_items_returns_escalated_with_ids` | other `deck_` token | 1 | 1 | 1 |
| `deck_owned_pr_contract` | other `deck_` token | 1 | 1 | 1 |
| `deck_pi_manifest` | other `deck_` token | 1 | 1 | 1 |
| `deck_plan_team_launch_returns_plan_hash` | other `deck_` token | 1 | 1 | 1 |
| `deck_reply_context` | other `deck_` token | 1 | 1 | 1 |
| `deck_reply_only_uses_answer_for_context_requests` | other `deck_` token | 1 | 1 | 1 |
| `deck_request_routes_by_api_prefix` | other `deck_` token | 1 | 1 | 1 |
| `deck_unavailable` | other `deck_` token | 1 | 1 | 1 |
| `deck_update_expertise` | other `deck_` token | 1 | 1 | 1 |

### 5.4 Filenames containing an old-name token

Search: `git ls-tree -r --name-only <pin>` filtered case-insensitively for `claude[-_ ]deck|claude_registry|claude-registry|claudedeck`. There is no line unit for a filename; the content of these files, where it matched, is already classified in section 4.

| Tracked path | Note |
|---|---|
| `docs/plans/agent-mail/claude_deck_agent_mailbox_implementation_plan.md` | Dated planning record; filename kept with its history. |
| `docs/plans/instance-identity/claude-deck-instance-identity-implementation-plan.md` | Dated planning record; filename kept with its history. |
| `docs/plans/instance-identity/claude-deck-instance-identity-plan.zip` | Dated planning record; filename kept with its history. |
| `docs/plans/presence/claude-deck-cost-mockup.html` | Dated planning record; filename kept with its history. |
| `docs/plans/presence/claude-deck-files-mockup.html` | Dated planning record; filename kept with its history. |
| `docs/plans/presence/claude-deck-presence-mockup.html` | Dated planning record; filename kept with its history. |
| `docs/plans/presence/claude-deck-timeline-mockup.html` | Dated planning record; filename kept with its history. |
| `scripts/product-factory/claude-deck-product-supervisor-failure.service` | systemd unit name: an identifier other unit files reference (`After=`, `Requires=`, `OnFailure=`); #789 treats the filename itself as a runtime identifier. |
| `scripts/product-factory/claude-deck-product-supervisor.service` | systemd unit name: an identifier other unit files reference (`After=`, `Requires=`, `OnFailure=`); #789 treats the filename itself as a runtime identifier. |
| `scripts/product-factory/claude-deck-product-supervisor.timer` | systemd unit name: an identifier other unit files reference (`After=`, `Requires=`, `OnFailure=`); #789 treats the filename itself as a runtime identifier. |
| `scripts/product-factory/claude-deck-product-tmux.service` | systemd unit name: an identifier other unit files reference (`After=`, `Requires=`, `OnFailure=`); #789 treats the filename itself as a runtime identifier. |
| `scripts/product-factory/claude-deck-product.service` | systemd unit name: an identifier other unit files reference (`After=`, `Requires=`, `OnFailure=`); #789 treats the filename itself as a runtime identifier. |

12 tracked paths in total.

### 5.5 Binary assets

Search: the primary pattern without `-I`, minus the text sweep's file set. Exactly one tracked binary file matches:

| Tracked path | What was checked |
|---|---|
| `docs/plans/instance-identity/claude-deck-instance-identity-plan.zip` | `file(1)` reports Zip archive data. File-level listing only: the archive was not extracted for this inventory, so no line or occurrence count is claimed for its contents. |

This file is the whole difference between the 1,597-match/256-file binary-inclusive probe and the 1,596-line/255-file text sweep in section 2.

### 5.6 Claude Code keep-list (references that stay)

Search: `git grep -I -n -E 'Claude Code|claude-code' <pin> -- .`, then one exclusion: lines whose only hit is the product package name `claude-code-registry-backend` are **not** keep-list lines, because that package name identifies this product, not the harness. Path conventions that do not spell the name (`.claude/` directories, `CLAUDE.md` files) are outside this name search by design.
Keep-list: 1,129 lines, 1,188 occurrences, 262 distinct files; 68 of those lines also carry a primary old-name match and are classified in section 4. Excluded package-name lines: 23 in 6 files (`backend/pyproject.toml:2`, `backend/uv.lock:188`, 17 generated-comment lines in `backend/requirements.txt` (:4, :6, :19, :39, :42, :55, :70, :79, :87, :93, :98, :101, :106, :112, :123, :132, :157), `scripts/bump-version.sh:100` and `:130`, campaign `README.md:40`, and `docs/superpowers/plans/2026-08-12-pr2-distinct-commit-and-pr-identity.md:247`) — #789 owns that package rename. The table lists the **1,061 non-primary keep-list lines** (1,115 occurrences, 260 distinct files). The keep rule is occurrence-specific, not a whole-line exemption: the `Claude Code`/`claude-code` harness occurrences on the listed lines stay, because they name the Anthropic product or its CLI/provider identifier. Any other product occurrence on the same line still follows its own classification: `docs/features/agent-mail.md:104` and `docs/guide/supervised-factory-playbook.md:222` and `:603`, for example, are also bare-Deck supplemental lines whose `Deck` product copy renames (or is kept as history) under sections 4 and 5.1, while their harness names stay.

| File | Lines | Occurrences | Line numbers | Example (first listed line) |
|---|---:|---:|---|---|
| `.github/workflows/claude.yml` | 4 | 4 | 1, 33, 35, 47 | name: Claude Code |
| `CHANGELOG.md` | 19 | 21 | 50, 76, 80, 82, 86, 93, 97, 119, 121, 139, 141, 157, 168, 173, 187, 192, 207, 210-211 | - **Harnesses**: Show the versioned operations and readiness catalog for Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI and Pi, with guarded… |
| `CLAUDE.md` | 2 | 2 | 3, 86 | Web app for managing Claude Code configurations, MCP servers, commands, plugins, hooks, and permissions. |
| `PYTHON_CODE_REVIEW.md` | 1 | 1 | 9 | The session transcripts integration feature adds the ability to read and display Claude Code conversation history from JSONL files stored in '~/.claud… |
| `README.md` | 16 | 17 | 67, 75, 77-80, 83-84, 103, 105-106, 112, 162, 264, 268, 272 | - **Config Editor** — Browse, inspect, and edit Claude Code JSON settings or Codex TOML settings, including Codex profiles, runtime options, and featu… |
| `backend/app/api/v1/agent_bridge/router.py` | 1 | 1 | 54 | provider: str = "claude-code" |
| `backend/app/api/v1/agent_mail.py` | 5 | 5 | 1171-1172, 1181, 1344, 1357 | provider = str(payload.get("provider") or "claude-code") |
| `backend/app/api/v1/agent_teams.py` | 1 | 1 | 3356 | "claude-code": "claude", |
| `backend/app/api/v1/cc_bridge/router.py` | 2 | 2 | 36, 115 | """List all discovered Claude Code sessions in tmux.""" |
| `backend/app/api/v1/config.py` | 1 | 1 | 113 | for patterns that Claude Code would reject. |
| `backend/app/api/v1/memory.py` | 1 | 1 | 159 | Cannot modify the managed policy file (/etc/claude-code/CLAUDE.md). |
| `backend/app/api/v1/plans.py` | 6 | 6 | 17, 38, 58, 78, 99, 113 | PLAN_PROVIDERS = {"claude-code", "codex-cli"} |
| `backend/app/api/v1/status.py` | 1 | 1 | 33 | version = await asyncio.to_thread(get_provider("claude-code").get_version) |
| `backend/app/models/database.py` | 1 | 1 | 23 | """Project model for tracking Claude Code project directories.""" |
| `backend/app/models/schemas.py` | 9 | 9 | 120, 1668-1669, 1704-1705, 1725-1726, 1757-1758 | provider: str = "claude-code" |
| `backend/app/services/agent_activity_service.py` | 7 | 7 | 50, 59, 99, 425, 453, 507, 721 | if provider not in {"claude-code", "codex-cli", "muse-cli"} or len(screen) > 65536: |
| `backend/app/services/agent_bridge/attachments.py` | 1 | 1 | 29 | "claude-code": "Please inspect this image: {path}", |
| `backend/app/services/agent_bridge/spawn.py` | 3 | 3 | 82, 158, 174 | if provider.id == "claude-code" and options.mode == "worktree" and not options.worktree_name: |
| `backend/app/services/agent_mail_service.py` | 1 | 1 | 62 | TMUX_WAKE_PROVIDERS = {"claude-code", "codex-cli", "copilot-cli", "opencode-cli", "pi-cli", "muse-cli"} |
| `backend/app/services/agent_status_service.py` | 1 | 1 | 51 | AgentTeamSlot.provider.in_(["codex-cli", "claude-code"])))).all() |
| `backend/app/services/agent_team_service.py` | 4 | 4 | 995, 1009, 1341-1342 | if slot.provider == "claude-code" and options.mode != "resume": |
| `backend/app/services/backup_service.py` | 1 | 1 | 89 | """Try to get Claude Code version.""" |
| `backend/app/services/cc_bridge/discovery.py` | 5 | 5 | 10-11, 17-18, 33 | """Check if a tmux pane is running Claude Code.""" |
| `backend/app/services/cc_bridge/spawn.py` | 4 | 4 | 1, 65, 70, 84 | """Spawn and kill Claude Code sessions in tmux.""" |
| `backend/app/services/claude_activity_service.py` | 1 | 1 | 1 | """Read bounded Claude Code turn evidence for an explicitly identified process.""" |
| `backend/app/services/cli_executor.py` | 4 | 4 | 16, 25, 132, 135 | DEFAULT_PROVIDER = "claude-code" |
| `backend/app/services/config_service.py` | 2 | 2 | 1, 24 | """Configuration service for reading and merging Claude Code configurations.""" |
| `backend/app/services/context_service.py` | 1 | 1 | 1 | """Service for context window analysis of Claude Code sessions.""" |
| `backend/app/services/credentials_service.py` | 1 | 1 | 1 | """Service for managing Claude Code OAuth credentials.""" |
| `backend/app/services/factory_audit_service.py` | 1 | 1 | 435 | "claude": "claude-code", |
| `backend/app/services/hook_service.py` | 3 | 3 | 1, 49, 208 | """Service for managing Claude Code hooks.""" |
| `backend/app/services/mcp_registry_service.py` | 1 | 1 | 149 | # Map registry transport types to Claude Code types |
| `backend/app/services/mcp_service.py` | 1 | 1 | 197 | # Prefix with plugin identifier to match Claude Code's format |
| `backend/app/services/memory_service.py` | 4 | 4 | 1, 17, 21, 36 | """Service for managing Claude Code memory files (CLAUDE.md, rules, etc.).""" |
| `backend/app/services/owner_observation_pause.py` | 2 | 2 | 51, 53 | if slot.provider in {"claude-code", "codex-cli", "muse-cli"} and not activity._canonical_session_id(options.get("session_id")): |
| `backend/app/services/plan_service.py` | 2 | 2 | 1, 13 | """Service for browsing Claude Code plan files.""" |
| `backend/app/services/plugin_descriptions.py` | 3 | 3 | 2, 52, 134 | Hardcoded descriptions for official Claude Code plugins. |
| `backend/app/services/plugin_service.py` | 1 | 1 | 52 | """Service for managing Claude Code plugins.""" |
| `backend/app/services/project_service.py` | 1 | 1 | 107 | Claude Code metadata is preserved when present: |
| `backend/app/services/provider_operations_service.py` | 2 | 2 | 190, 211 | implemented = set(SURFACES) if provider.id == "claude-code" else {"summary", "config", "mcp", "plugins", "plans"} if provider.id == "codex-cli" else s… |
| `backend/app/services/provider_readiness_service.py` | 4 | 4 | 12, 14, 16, 58 | if provider == "claude-code": |
| `backend/app/services/providers/__init__.py` | 1 | 1 | 14 | "claude-code": ClaudeCodeProvider(), |
| `backend/app/services/providers/capabilities.py` | 27 | 27 | 55-76, 87-88, 90, 92-93 | "claude-code": { |
| `backend/app/services/providers/claude_code.py` | 6 | 6 | 1, 17-18, 62, 66, 69 | """Claude Code provider implementation.""" |
| `backend/app/services/providers/platform_env.py` | 1 | 1 | 11 | PROVIDER_CLAUDE_CODE = "claude-code" |
| `backend/app/services/session_service.py` | 3 | 3 | 1, 3-4 | """Service for managing Claude Code session transcripts. |
| `backend/app/services/statusline_service.py` | 1 | 1 | 1 | """Service for managing Claude Code status line configuration.""" |
| `backend/app/services/team_workspace_trust.py` | 3 | 3 | 126, 133, 147 | if provider not in {"claude-code", "codex-cli"}: |
| `backend/app/utils/path_utils.py` | 9 | 9 | 1, 13, 20, 25, 37, 44, 49, 53, 248 | """Path utilities for Claude Code configuration file locations.""" |
| `backend/app/utils/pattern_utils.py` | 2 | 2 | 3, 30 | Validates permission patterns against Claude Code's current rules and |
| `backend/mcp_shim/agent_mail_server.py` | 2 | 2 | 904, 908 | Valid providers: claude-code, codex-cli, copilot-cli, opencode-cli. |
| `backend/tests/agent_mail/test_api.py` | 2 | 2 | 3375-3376 | ("claude-code", "apply", "apply_claude_code_install"), |
| `backend/tests/agent_mail/test_external_api.py` | 2 | 3 | 234, 277 | @pytest.mark.parametrize("provider", ["codex-cli", "claude-code"]) |
| `backend/tests/agent_mail/test_hooks_api.py` | 1 | 1 | 29 | "source": "mcp", "provider": "claude-code", "session_key": "mcp:s1", "cwd": str(cwd)}) |
| `backend/tests/agent_mail/test_install.py` | 3 | 3 | 1, 506, 510 | """Install service: status, confirmed endpoints, Claude Code and Codex mutation paths.""" |
| `backend/tests/agent_mail/test_pi_shim.py` | 1 | 1 | 91 | @pytest.mark.parametrize("provider", ["pi-cli", "codex-cli", "claude-code", "unknown"]) |
| `backend/tests/agent_mail/test_registry.py` | 7 | 9 | 56, 677-678, 947, 1103, 1486, 1944 | def _register(cwd, session_key="cc:s1", source="hook", provider="claude-code", pid=None): |
| `backend/tests/agent_teams/test_agent_bridge_session_metadata.py` | 2 | 2 | 24, 41 | provider="claude-code", |
| `backend/tests/agent_teams/test_agent_status.py` | 1 | 1 | 181 | mcp.provider = "claude-code" |
| `backend/tests/agent_teams/test_agent_team_api.py` | 1 | 1 | 2642 | ("claude-code", ["claude"]), |
| `backend/tests/agent_teams/test_agent_team_service.py` | 7 | 7 | 857, 876, 898, 913, 2170, 2787, 2810 | provider="claude-code", |
| `backend/tests/agent_teams/test_claude_activity.py` | 1 | 1 | 42 | return activity._observe(2, "claude-code", identity, |
| `backend/tests/agent_teams/test_factory_delivery_policy.py` | 1 | 1 | 169 | provider="claude-code", repo_id="fixture", repo_path=str(tmp_path), |
| `backend/tests/agent_teams/test_github_dispatch_service.py` | 1 | 1 | 7426 | provider="claude-code", repo_id="website", repo_path="/tmp/website", repo_name="website", |
| `backend/tests/agent_teams/test_native_activity.py` | 2 | 2 | 301, 629 | assert native["observe"](provider="claude-code").reason == "session_identity_unavailable" |
| `backend/tests/agent_teams/test_native_input_wait.py` | 15 | 15 | 10-15, 18, 37, 63, 79, 87, 99, 195, 201, 203 | ("claude-code", "claude-question-form.txt", "question"), |
| `backend/tests/agent_teams/test_operator_auth.py` | 1 | 1 | 472 | {"provider": "claude-code"}, |
| `backend/tests/agent_teams/test_repo_path_override.py` | 2 | 2 | 44, 58 | preset_id=preset.id, position=0, display_name="Dev", provider="claude-code", |
| `backend/tests/agent_teams/test_team_workspace_trust.py` | 13 | 13 | 21, 24, 36, 61, 66, 69, 85, 109, 113-114, 120, 128, 162 | @pytest.mark.parametrize("provider", ["claude-code", "codex-cli"]) |
| `backend/tests/factory/conftest.py` | 1 | 1 | 77 | provider="claude-code" if position == 0 else "codex-cli", |
| `backend/tests/factory/test_factory_api.py` | 2 | 2 | 108, 112 | assert (await get_ok(factory_client, "work-items", provider="claude-code"))["total"] == 0 |
| `backend/tests/factory/test_factory_audit_metrics.py` | 5 | 6 | 3675, 3699, 3752, 3866, 4963 | async def _bind_native(store, who: dict, pid: int, start: str, *, claimed: str = "claude-code", |
| `backend/tests/fixtures/native_screens/README.md` | 5 | 5 | 7-10, 12 | \| 'claude-question-form.txt' / '.ansi' \| Claude Code 2.1.292 \| waiting: question form (one question, "↑/↓ to navigate") \| |
| `backend/tests/fixtures/native_screens/claude-idle-after-declined-question.txt` | 2 | 2 | 2, 6 | ▐▛███▛█ Claude Code v2.1.292 |
| `backend/tests/fixtures/native_screens/claude-question-form.ansi` | 1 | 1 | 2 | [38;5;174m ▐[48;5;16m▛███▛█[39m[49m [1mClaude Code[0m [38;5;246mv2.1.292[39m |
| `backend/tests/fixtures/native_screens/claude-question-form.txt` | 1 | 1 | 2 | ▐▛███▛█ Claude Code v2.1.292 |
| `backend/tests/fixtures/native_screens/claude-trust-prompt-with-permissions.txt` | 1 | 1 | 7 | Claude Code'll be able to read, edit, and execute files here. |
| `backend/tests/fixtures/native_screens/claude-trust-prompt.ansi` | 1 | 1 | 10 | Claude Code'll be able to read, edit, and execute files here. |
| `backend/tests/fixtures/native_screens/claude-trust-prompt.txt` | 1 | 1 | 10 | Claude Code'll be able to read, edit, and execute files here. |
| `backend/tests/fixtures/provider-operations/v1/catalog.json` | 81 | 81 | 5, 7-8, 162, 167, 172, 177, 182, 187, 192, 197, 202, 207, 212, 217, 222, 227, 232, 237, 242, 247, 252, 257, 262, 268, 279, 290, 301, 312, 323, 334, 345, 356, 367, 378, 389, 400, 411, 422, 433, 444, 692, 697, 707, 717, 722, 2825, 2830, 2840, 2850, 2855, 3267, 3272, 3282, 3292, 3297, 3709, 3714, 3724, 3734, 3739, 4151, 4156, 4166, 4176, 4181, 4593, 4598, 4608, 4618, 4623, 5035, 5040, 5050, 5060, 5065, 5477, 5482, 5492, 5502, 5507 | "claude-code": { |
| `backend/tests/fixtures/provider-operations/v1/manifest.json` | 1 | 1 | 17 | "claude-code", |
| `backend/tests/test_agent_bridge_attachments.py` | 2 | 2 | 59, 86 | "provider": "claude-code", |
| `backend/tests/test_agent_bridge_discovery.py` | 2 | 2 | 22, 27 | "claude-code", |
| `backend/tests/test_agent_bridge_spawn.py` | 9 | 9 | 24, 71, 196, 427, 462, 481, 527, 565, 567 | "claude-code", |
| `backend/tests/test_codex_history_service.py` | 2 | 2 | 129, 133 | providers_api.get_provider_history_diagnostics("claude-code") |
| `backend/tests/test_codex_usage_context_service.py` | 1 | 1 | 165 | providers_api.get_provider_usage_context_diagnostics("claude-code") |
| `backend/tests/test_multi_provider_smoke.py` | 5 | 5 | 12, 14, 47, 123, 127 | assert provider_ids == {"claude-code", "codex-cli", "copilot-cli", "opencode-cli", "pi-cli", "muse-cli"} |
| `backend/tests/test_provider_cli_executor.py` | 1 | 1 | 79 | assert executor.provider_id == "claude-code" |
| `backend/tests/test_provider_contract_api.py` | 7 | 7 | 22, 27-28, 38, 42, 50, 52 | providers_api.get_provider_doctor("claude-code") |
| `backend/tests/test_provider_readiness.py` | 3 | 3 | 40, 130, 243 | ("claude-code", "claude_code_mcp_installed"), ("codex-cli", "codex_mcp_installed"), |
| `backend/tests/test_providers.py` | 6 | 7 | 11-12, 21, 61, 67, 179 | assert provider_ids == {"claude-code", "codex-cli", "copilot-cli", "opencode-cli", "pi-cli", "muse-cli"} |
| `backend/tests/test_settings_write_guard.py` | 1 | 1 | 54 | for harness in ("claude-code", "codex", "copilot", "opencode", "muse") |
| `backend/tests/test_team_supervisor.py` | 4 | 4 | 1, 3, 132, 176 | """The team-supervisor guard reads Claude Code and Codex transcripts. |
| `backend/tests/test_usage_service.py` | 1 | 1 | 91 | """Test current Claude Code model aliases have non-zero pricing.""" |
| `docs/api/agent-bridge.md` | 4 | 4 | 3, 13, 153, 157 | Provider-aware live terminal monitoring for Claude Code, Codex CLI, GitHub Copilot CLI, and OpenCode CLI tmux sessions. |
| `docs/api/agent-mail.md` | 3 | 3 | 3, 151-152 | Durable local mailbox coordination for Claude Code, Codex CLI, GitHub Copilot CLI, and trusted same-machine orchestration tools. |
| `docs/api/agent-teams.md` | 1 | 1 | 3 | Saved rosters for launching or reusing local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions. |
| `docs/api/backup.md` | 1 | 1 | 80 | Claude Code backups can be restored according to the restore plan. Codex backups refuse automatic restore and return an explicit failure because the a… |
| `docs/api/cc-bridge.md` | 4 | 4 | 4, 7, 17, 52 | Use '/api/v1/agent-bridge/*' for new provider-aware clients. '/api/v1/cc-bridge/*' remains for compatibility with Claude Code-only integrations. |
| `docs/api/config.md` | 2 | 3 | 3, 21 | Manage Claude Code configuration across all scopes. Codex CLI uses a separate TOML-backed config API because its file format and safety rules differ f… |
| `docs/api/factory.md` | 1 | 1 | 41 | Overview and both lists accept optional 'team_id', 'scope_id' and 'provider'. IDs must be positive integers no larger than 2^63−1. A scope selected wi… |
| `docs/api/index.md` | 1 | 1 | 95 | \| [CC Bridge](/api/cc-bridge) \| '/cc-bridge' \| Legacy Claude Code terminal monitoring route \| |
| `docs/api/providers.md` | 1 | 1 | 13 | Returns registered providers such as 'claude-code', 'codex-cli', and 'copilot-cli', including install status, version, capabilities, and config paths. |
| `docs/changelog.md` | 10 | 10 | 38, 48, 50, 54, 56, 62, 90, 107, 140, 162 | - Claude Code Config now covers current high-impact settings: |
| `docs/features/agent-bridge.md` | 8 | 9 | 3, 7, 19, 23-24, 59, 81, 83 | Agent Bridge discovers and manages local agent CLIs running inside tmux. It supports mixed Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, a… |
| `docs/features/agent-mail.md` | 3 | 3 | 69, 104, 123 | Claude Code gets both MCP tools and command hooks: |
| `docs/features/agent-teams.md` | 1 | 1 | 3 | Agent Teams are saved rosters of local Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions. Use them when the same group of repo… |
| `docs/features/agents-skills.md` | 1 | 1 | 3 | Create custom agents and discover reusable skills for Claude Code. |
| `docs/features/backup.md` | 1 | 2 | 7 | The Backup page lets you create ZIP archives of your Claude Code configuration, restore from Claude Code backups, create redacted Codex exports, and m… |
| `docs/features/cc-bridge.md` | 5 | 6 | 4, 7, 11, 17, 29 | The provider-aware feature is now Agent Bridge. This page describes the original Claude Code-only bridge naming; use [Agent Bridge](/features/agent-br… |
| `docs/features/commands.md` | 1 | 1 | 3 | Create, manage, and organize custom slash commands for Claude Code. |
| `docs/features/config.md` | 7 | 8 | 3, 7, 17, 22, 29, 37, 119 | The Config page lets you view, edit, and understand provider configuration. Claude Code uses JSON settings across multiple scopes; Codex CLI uses TOML… |
| `docs/features/dashboard.md` | 1 | 1 | 17 | The former provider/project dashboard is available as Configuration summary under [Harnesses](/features/harnesses) for implemented providers. Claude C… |
| `docs/features/external-agent-orchestration.md` | 1 | 1 | 172 | - Non-tmux Claude Code, Codex, and Copilot sessions return 'delivered_waiting'; they are not falsely reported as woken. |
| `docs/features/hooks.md` | 2 | 2 | 3, 7 | Configure event-triggered actions that run during the Claude Code lifecycle. |
| `docs/features/memory.md` | 3 | 3 | 3, 7, 47 | View and edit Claude Code's memory hierarchy — CLAUDE.md files, rules, auto-memory, and imports. |
| `docs/features/permissions.md` | 1 | 1 | 3 | Visual rule builder for controlling which operations Claude Code can perform. |
| `docs/features/plugins.md` | 4 | 4 | 3, 7, 58, 69 | Browse, install, enable/disable, and update Claude Code plugins. |
| `docs/features/sessions.md` | 3 | 3 | 3, 7, 34 | Browse Claude Code conversation transcripts with full message details and tool use. |
| `docs/features/statusline.md` | 2 | 2 | 3, 7 | Customize the bottom status bar in Claude Code with presets, powerline themes, or custom scripts. |
| `docs/features/usage.md` | 2 | 2 | 7, 45 | The Usage page aggregates token usage data from Claude Code sessions and displays costs, trends, and billing block analysis. |
| `docs/guide/installation.md` | 1 | 1 | 14 | - Claude Code |
| `docs/guide/multi-provider-codex-v2.md` | 3 | 4 | 30, 106-107 | \| Surface \| Claude Code \| Codex CLI \| |
| `docs/guide/supervised-factory-playbook.md` | 3 | 3 | 168, 222, 603 | The product work used several harness and model combinations. The v3 team used Claude Code Sonnet implementers and a Leader, with an Opus verifier. Ea… |
| `docs/plans/2026-02-07-mcp-page-enhancements-design.md` | 1 | 1 | 8 | Bring the MCP Servers page to feature parity with Claude Code's '/mcp' capabilities. Three priority areas: per-server approval overrides, server healt… |
| `docs/plans/2026-03-01-cc-bridge-stage1.md` | 8 | 8 | 5, 195, 204, 222, 586, 1183, 1372, 1493 | **Goal:** Discover running Claude Code sessions in tmux and view them live in the browser via xterm.js. |
| `docs/plans/2026-03-05-http-hooks-integration-design.md` | 1 | 1 | 108 | - 'POST /api/v1/webhook-receiver' — Receives hook payloads from Claude Code. Stores in DB. Returns 200 with empty JSON (no decision, pure logging) |
| `docs/plans/2026-03-06-agent-orchestration-design.md` | 1 | 1 | 19 | Large engineering tasks exceed what a single Claude Code session can do reliably: |
| `docs/plans/2026-03-08-presence-status-accuracy.md` | 4 | 4 | 80, 84, 89, 109 | ### Approach B: Poll Claude Code Status Directly |
| `docs/plans/2026-03-20-new-settings-surface.md` | 1 | 1 | 205 | feat(config): surface new Claude Code settings in SettingsEditor |
| `docs/plans/2026-05-25-codex-cli-support.html` | 21 | 21 | 20, 22, 59, 73-74, 78, 80, 88, 96, 129, 203, 213, 309, 351, 394, 414, 419, 462, 489, 534, 577 | <li>View and edit Codex configuration with parity to the existing Claude Code configuration experience.</li> |
| `docs/plans/2026-05-25-codex-cli-support.md` | 21 | 21 | 12, 14, 55, 71, 73, 80, 82, 92, 102, 139, 223, 233, 335, 381, 426, 448, 454, 498, 528, 577, 620 | - View and edit Codex configuration with parity to the existing Claude Code configuration experience. |
| `docs/plans/2026-05-26-codex-cli-v2-plan.md` | 9 | 9 | 20, 37, 58, 66, 77, 79, 208, 225, 299 | - Provider registry for Claude Code and Codex CLI. |
| `docs/plans/2026-05-26-codex-history-investigation.md` | 1 | 1 | 11 | Local inspection shows 'history.jsonl' rows with 'session_id', 'ts', and 'text'. The session id and timestamp are useful, but 'text' is prompt content… |
| `docs/plans/2026-05-26-codex-usage-context-investigation.md` | 2 | 2 | 10, 37 | context-window metric surface that is safe to treat like Claude Code usage and |
| `docs/plans/2026-10-11-v3.1-director-ui/director-ui-mockup.html` | 9 | 18 | 346, 653-654, 770, 794, 796, 862, 882, 916 | <span class="harness">Claude Code 2.1 · Codex 0.159 · Pi 0.87</span> |
| `docs/plans/2026-10-11-v3.1-director-ui/factory-operation-explainer.html` | 1 | 1 | 241 | <text x="42" y="254" font-size="11.5" fill="#4c1d95">Claude Code, OpenClaw,</text> |
| `docs/plans/2026-10-15-director-website/01-audit.md` | 2 | 2 | 121, 182 | Agent Teams page. Evidence: 'docs/features/agent-teams.md' opens with 'Agent Teams are saved rosters of local Claude Code, Codex CLI, GitHub Copilot C… |
| `docs/plans/2026-11-06-rename-synth-city/README.md` | 1 | 1 | 44 | - names of the Claude Code harness, which is a real third-party product the agents run; |
| `docs/plans/2026-11-06-rename-synth-city/transfer-runbook.md` | 5 | 5 | 271, 273, 396, 460, 692 | the Claude Code workflow ('.github/workflows/claude.yml:37', |
| `docs/plans/2026-11-06-rename-synth-city/website-and-docs.md` | 3 | 5 | 388, 800, 868 | \| 'Claude Code' / 'claude-code' (third-party harness) \| 90 / 30 \| **Keep.** These name a real external product the agents run, not this product; ne… |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-implementation-plan.md` | 20 | 21 | 5, 20, 22, 506, 1622, 1734, 1736, 1753, 1858, 1955, 2100, 2105, 2618, 2622, 2678, 3195, 3437, 3450, 3475, 3480 | **Goal:** Let local Claude Code / Codex CLI sessions coordinate as a user-directed team — durable per-repo team identities, structured context request… |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v2-review-for-patching.md` | 5 | 5 | 115, 128, 177, 209, 237 | The v2 goal says local Claude Code and Codex CLI sessions should coordinate with one-click install. But Task 8 says Codex only gets copy-paste 'config… |
| `docs/plans/agent-mail/2026-06-12-agent-mail-v3-implementation-plan.md` | 26 | 27 | 5, 22, 24, 192, 213, 221, 547, 1708, 1820, 1822, 1839, 1944, 2074, 2308, 2316, 2858, 2862, 2946, 3539, 3570, 3588, 3880, 3896, 3921, 3926, 3928 | **Goal:** Let local Claude Code / Codex CLI sessions coordinate as a user-directed team — durable per-repo team identities, structured context request… |
| `docs/plans/agent-mail/2026-06-13-presence-feature-usability-review.md` | 11 | 11 | 41, 47, 49, 53, 69, 243-244, 294, 296, 301, 347 | Presence was originally trying to answer a different question: "What Claude Code sessions exist and what are they doing right now?" |
| `docs/plans/agent-mail/2026-06-14-codex-app-server-wakeups-implementation-plan.md` | 1 | 1 | 73 | - Do not make Agent Mail depend on Codex app-server for Claude Code. |
| `docs/plans/agent-mail/2026-06-15-agent-team-presets-implementation-plan.md` | 8 | 9 | 25, 36, 329, 536, 570, 724, 787, 882 | 5. **Stay provider-aware.** Claude Code and Codex launch options differ. The preset model should store common slot intent plus provider-specific launc… |
| `docs/plans/agent-mail/agent_mailbox_alternate_direction_evaluation.md` | 5 | 5 | 118, 185, 288, 408, 460 | - Claude Code 'SessionStart' hook nudges the model to call 'deck_read_inbox'. |
| `docs/plans/agent-mail/claude_deck_agent_mailbox_implementation_plan.md` | 31 | 34 | 26, 53, 66, 117, 124, 168, 211, 273, 281, 306, 1270, 1362, 1619, 1680, 1707, 1869, 1983, 2149, 2577, 2594, 2638, 2971, 2982, 3130, 3148, 3173, 3181-3182, 3206, 3395-3396 | 5. Claude Code hook integration for SessionStart, SessionEnd, Notification, PostToolUse, and optional PreToolUse lease checks. |
| `docs/plans/cc-bridge-design.md` | 9 | 9 | 1, 3, 13, 54-56, 122, 128, 283 | # Claude Code Bridge — Design Document |
| `docs/plans/instance-identity/claude-deck-instance-identity-implementation-plan.md` | 5 | 5 | 36, 111, 205-207 | - Existing '/status' endpoint currently computes Claude Code version, active Agent Bridge session count, provider statuses, and returns 'SystemStatusR… |
| `docs/plans/product-reposition/experience-spec.md` | 2 | 2 | 36, 172 | The harness filter means the owner slot's current configured harness. Label historical runtime evidence separately when it exists. Unassigned work app… |
| `docs/plans/product-reposition/handoffs/harness-operations.md` | 2 | 2 | 5, 55 | Implement **P03 in M1b**: extend the accepted thin Harnesses index with a common operating contract and readiness for Claude Code, Codex CLI, Copilot … |
| `docs/plans/product-reposition/product-brief.md` | 1 | 1 | 87 | Native settings remain provider specific. A harness can participate effectively in delivery without having every Claude Code configuration surface. Eq… |
| `docs/public/images/operating-model/factory.svg` | 1 | 1 | 32 | <text x="42" y="254" font-size="11.5" fill="#4c1d95">Claude Code, OpenClaw,</text> |
| `docs/superpowers/plans/2026-05-29-agent-bridge-bedrock-platform.md` | 6 | 6 | 7, 243, 279, 543, 626, 651 | **Architecture:** A 'platform' enum plus a provider-side env builder. The new-session dialog gains a Platform selector (Claude Code provider only); se… |
| `docs/superpowers/plans/2026-07-04-autonomous-github-dispatch-phase-a.md` | 1 | 1 | 404 | preset_id=preset.id, position=0, display_name="Dev", provider="claude-code", |
| `docs/superpowers/plans/2026-08-02-phase-g2-session-lifecycle.md` | 2 | 3 | 2072, 2112 | 1. 'provider="claude"' is **not** a wake provider. 'TMUX_WAKE_PROVIDERS = {"claude-code", "codex-cli", "copilot-cli", "opencode-cli"}' ('agent_mail_se… |
| `docs/superpowers/plans/2026-08-04-phase-g3-observed-session-durability.md` | 2 | 2 | 639-640 | "provider": "claude-code", |
| `docs/superpowers/plans/2026-08-09-pr0-agent-mail-capability-tokens.md` | 2 | 2 | 2356, 2375 | "claude-code", |
| `docs/superpowers/specs/2026-04-10-settings-gap-update-design.md` | 2 | 2 | 11, 136 | The SettingsEditor currently covers ~35 settings across 10 cards. The official Claude Code settings docs at 'code.claude.com/docs/en/settings' now doc… |
| `docs/superpowers/specs/2026-05-29-agent-bridge-bedrock-platform-design.md` | 7 | 7 | 5, 9, 24, 40, 57, 69, 81 | **Scope:** Add a per-session platform picker (Anthropic default / Amazon Bedrock) to the Agent Bridge "New Session" dialog for the Claude Code provide… |
| `docs/superpowers/specs/2026-06-29-agent-bridge-image-paste-design.md` | 4 | 4 | 6, 304, 407, 669 | **Scope:** Add image paste / drag-drop support to Agent Bridge terminal sessions so a browser user can provide screenshots, mockups, diagrams, and oth… |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-design.md` | 5 | 5 | 72, 155, 181, 223-224 | \| Field \| claude-code \| codex-cli \| copilot-cli \| opencode-cli \| |
| `docs/superpowers/specs/2026-06-29-agentic-agent-teams-e2e-tests.md` | 6 | 7 | 42, 59, 66, 292, 298, 334 | \| 'claude-code' \| plain, worktree, resume \| — (none) \| yes \| platform, aws_region, aws_profile, bedrock_model \| |
| `docs/superpowers/specs/2026-07-03-autonomous-github-dispatch-ui-mockups.html` | 1 | 1 | 309 | <p class="app-sub">Saved rosters for launching or reusing local Claude Code, Codex CLI, and GitHub Copilot CLI sessions.</p> |
| `docs/superpowers/specs/2026-07-04-autonomous-github-dispatch-conversational-setup-mockups.html` | 1 | 1 | 232 | <p class="app-sub" style="margin-top:-6px;">Saved rosters for launching or reusing local Claude Code, Codex CLI, and GitHub Copilot CLI sessions.</p> |
| `docs/superpowers/specs/2026-07-05-autonomous-github-dispatch-e2e-verification-plan.md` | 1 | 1 | 32 | 4. **An agent provider that actually runs** on this machine — codex-cli or claude-code, whichever you have working creds for. The spawned team member … |
| `docs/superpowers/specs/2026-07-05-tizonia-e2e-testbed-plan.md` | 1 | 1 | 36 | Per decision: **1 leader + 1 code-capable generalist slot** (no 'area_labels' → leader-fallback routing). This keeps the first e2e run about proving *… |
| `docs/superpowers/specs/2026-10-14-muse-code-harness-design.md` | 3 | 3 | 23, 45, 69 | \| Hooks \| The workspace '.muse/hooks.json' uses Claude Code's layout: '{"hooks": {"<Event>": [{"matcher": "...", "hooks": [{"type": "command", "comm… |
| `frontend/e2e/g0/routes.spec.ts` | 4 | 4 | 104, 108-109, 113 | await expect(page.getByText('Claude Code').first()).toBeVisible() |
| `frontend/e2e/g1/project-selector.spec.ts` | 3 | 3 | 16, 36, 51 | await page.goto('/harnesses/claude-code/config') |
| `frontend/e2e/lane-d/harness-mail-setup.spec.ts` | 7 | 7 | 18, 64, 72, 75, 84, 101, 110 | const MANAGED = ['claude-code', 'codex-cli', 'copilot-cli', 'opencode-cli', 'muse-cli'] |
| `frontend/e2e/lane-d/mail-page.ts` | 1 | 1 | 11 | * Show Agent Mail as set up for Claude Code. The instance HOME has no Agent |
| `frontend/e2e/lane-f/controls.spec.ts` | 1 | 1 | 8 | await page.goto('/harnesses/claude-code/mcp') |
| `frontend/e2e/lane-f/harness-list.spec.ts` | 3 | 3 | 11, 59, 61 | const HARNESSES = ['claude-code', 'codex-cli', 'copilot-cli', 'opencode-cli', 'pi-cli', 'muse-cli'] |
| `frontend/e2e/lane-f/harness-page.spec.ts` | 4 | 4 | 29, 54, 67-68 | for (const harness of ['claude-code', 'codex-cli']) { |
| `frontend/e2e/lane-f/loading.spec.ts` | 1 | 1 | 11 | for (const route of ['/harnesses', '/harnesses/claude-code']) { |
| `frontend/e2e/lane-f/navigation.spec.ts` | 2 | 2 | 11, 66 | const HARNESSES = ['claude-code', 'codex-cli'] |
| `frontend/e2e/lane-f/projects-a11y.spec.ts` | 1 | 1 | 13 | await page.goto('/harnesses/claude-code/config') |
| `frontend/e2e/lane-g/no-active-project.spec.ts` | 1 | 2 | 10 | '/harnesses', '/harnesses/claude-code', '/harnesses/claude-code/config', '/projects', |
| `frontend/src/contexts/DashboardContext.tsx` | 2 | 2 | 139, 143 | : 'Claude Code' |
| `frontend/src/contexts/ProviderContext.tsx` | 2 | 2 | 15, 23 | const DEFAULT_PROVIDER: AgentProviderId = 'claude-code' |
| `frontend/src/features/agent-mail/AgentMailHelpDialog.tsx` | 3 | 3 | 48, 55, 64 | <Badge variant="outline">Claude Code: MCP + hooks</Badge> |
| `frontend/src/features/agent-mail/AgentMailPage.tsx` | 1 | 1 | 339 | ? 'Install the Agent Mail MCP server for Claude Code, Codex, GitHub Copilot CLI, or OpenCode CLI before agents can send, receive, or answer mailbox re… |
| `frontend/src/features/agent-mail/HarnessMailSetup.tsx` | 1 | 1 | 157 | const needsSnippets = hasMailAction(providerId) && providerId !== 'claude-code' |
| `frontend/src/features/agent-mail/api.ts` | 2 | 2 | 153, 160 | return apiClient<AgentMailInstallStatus>('agent-mail/install/claude-code/apply', { |
| `frontend/src/features/agent-mail/mailSetup.ts` | 11 | 12 | 20, 22, 25, 40, 91, 100, 119, 197, 199, 206, 208 | export type MailActionHarness = 'claude-code' \| 'codex-cli' \| 'copilot-cli' \| 'opencode-cli' \| 'muse-cli' |
| `frontend/src/features/agent-mail/roster.ts` | 1 | 2 | 9 | 'claude-code': 'Claude Code', |
| `frontend/src/features/agent-mail/useAgentMailSetup.ts` | 3 | 3 | 26-28 | 'claude-code': { |
| `frontend/src/features/agent-teams/AgentTeamsPage.tsx` | 1 | 2 | 500 | <SelectItem value="claude-code">Claude Code</SelectItem> |
| `frontend/src/features/agent-teams/teamSources.ts` | 1 | 1 | 7 | export const PROVIDER_IDS: AgentProviderId[] = ['codex-cli', 'claude-code', 'copilot-cli', 'opencode-cli', 'pi-cli', 'muse-cli'] |
| `frontend/src/features/backup/BackupWizard.tsx` | 1 | 1 | 61 | providerId = "claude-code", |
| `frontend/src/features/cc-bridge/CCBridgePage.tsx` | 2 | 4 | 36, 169 | { value: 'claude-code', label: 'Claude Code' }, |
| `frontend/src/features/cc-bridge/NewSessionDialog.tsx` | 4 | 4 | 143, 321-322, 326 | const isClaude = provider === 'claude-code' |
| `frontend/src/features/cc-bridge/SessionList.tsx` | 1 | 1 | 65 | : 'Claude Code' |
| `frontend/src/features/commands/CommandWizard.tsx` | 1 | 1 | 165 | Available in all your Claude Code projects. Commands saved here |
| `frontend/src/features/commands/CommandsPage.tsx` | 1 | 1 | 146 | Manage custom Claude Code commands |
| `frontend/src/features/config/ConfigViewerPage.tsx` | 2 | 2 | 259, 318 | {selectedProviderId === "claude-code" && ( |
| `frontend/src/features/config/settings/SettingsEditor.tsx` | 1 | 1 | 262 | be rejected by Claude Code. Fix them before saving? |
| `frontend/src/features/config/settings/cards/AdvancedCard.tsx` | 1 | 1 | 99 | description="Refuse to run if the Claude Code binary is older than this semver." |
| `frontend/src/features/config/settings/cards/GeneralCard.tsx` | 2 | 2 | 36, 64 | Ordered models to try when the primary model is overloaded or unavailable. Claude Code uses up to three. |
| `frontend/src/features/config/settings/cards/IdeCard.tsx` | 2 | 2 | 26, 33 | description="Automatically connect to a running IDE when Claude Code starts" |
| `frontend/src/features/config/settings/cards/RemoteControlCard.tsx` | 3 | 3 | 11, 16, 45 | <CardDescription>Claude Code remote session access and terminal notification behavior</CardDescription> |
| `frontend/src/features/config/settings/cards/UiCard.tsx` | 1 | 1 | 28 | description="Claude Code terminal color theme." |
| `frontend/src/features/config/settings/cards/WorktreeCard.tsx` | 2 | 2 | 12, 28 | <CardDescription>Behavior when creating git worktrees from Claude Code</CardDescription> |
| `frontend/src/features/context/ActiveSessionsList.tsx` | 1 | 1 | 33 | Sessions appear here when a Claude Code instance has been active within the last hour. |
| `frontend/src/features/factory/RepositorySetupPage.tsx` | 1 | 1 | 911 | {draft.teamMode === "existing" ? <label className={labelClass}>Team<select className={inputClass} value={draft.teamId} onChange={(e) => update({ teamI… |
| `frontend/src/features/factory/filterHelpers.ts` | 1 | 2 | 20 | "claude-code": "Claude Code", |
| `frontend/src/features/harnesses/HarnessNav.tsx` | 1 | 1 | 9 | /** Harnesses › Claude Code › MCP servers. Every part except the current one is a link. */ |
| `frontend/src/features/hooks/HookWizard.tsx` | 1 | 1 | 177 | Step {step} of 4 - Configure your Claude Code hook |
| `frontend/src/features/hooks/HooksPage.tsx` | 1 | 1 | 147 | Customize Claude Code behavior with hooks triggered by events |
| `frontend/src/features/mcp/MCPRegistryInstallDialog.tsx` | 1 | 1 | 317 | This name identifies the server in your Claude Code config |
| `frontend/src/features/mcp/MCPServersPage.tsx` | 2 | 2 | 121, 516 | description="List, add, and remove MCP servers using codex mcp. Claude Code approval settings and registry installs are not part of the Codex CLI MCP … |
| `frontend/src/features/mcp/mcpStatus.ts` | 1 | 1 | 32 | * matching the Claude Code '/mcp' interface states: |
| `frontend/src/features/native-settings/surfaceRegistry.tsx` | 3 | 3 | 73, 184, 196 | "claude-code": claude, |
| `frontend/src/features/output-styles/OutputStyleEditor.tsx` | 1 | 1 | 93 | When enabled, Claude Code will retain its default coding-related |
| `frontend/src/features/output-styles/OutputStyleList.tsx` | 1 | 1 | 127 | No output styles configured. Create your first output style to customize Claude Code responses. |
| `frontend/src/features/output-styles/OutputStyleWizard.tsx` | 1 | 1 | 181 | When enabled, Claude Code will retain its default coding-related |
| `frontend/src/features/output-styles/OutputStylesPage.tsx` | 1 | 1 | 164 | Custom output formatting instructions for Claude Code responses |
| `frontend/src/features/permissions/PermissionsPage.tsx` | 3 | 3 | 200, 384, 464 | Control which operations Claude Code can perform |
| `frontend/src/features/plans/PlansPage.tsx` | 2 | 2 | 88, 108 | () => plans.filter((plan) => (plan.source ?? 'claude-code') === selectedProviderId), |
| `frontend/src/features/plugins/PluginsPage.tsx` | 1 | 1 | 369 | Manage Claude Code plugins and browse marketplace |
| `frontend/src/features/providers/ProviderLaunchOptionsFields.tsx` | 2 | 2 | 30, 81 | if (provider === 'claude-code') return 'Anthropic' |
| `frontend/src/features/sessions/SessionCard.tsx` | 3 | 3 | 20, 32, 40 | const url = '/harnesses/claude-code/sessions/${encodeURIComponent(session.project_folder)}/${encodeURIComponent(session.id)}' |
| `frontend/src/features/sessions/SessionViewPage.tsx` | 1 | 1 | 83 | navigate('/harnesses/claude-code/sessions') |
| `frontend/src/features/sessions/SessionViewer.tsx` | 1 | 1 | 57 | const url = '/harnesses/claude-code/sessions/${encodeURIComponent(projectFolder)}/${encodeURIComponent(sessionId)}?page=${currentPage}' |
| `frontend/src/features/sessions/SessionsPage.tsx` | 1 | 1 | 54 | View your Claude Code conversation history |
| `frontend/src/features/statusline/StatusLinePage.tsx` | 1 | 1 | 233 | Customize the status bar displayed at the bottom of Claude Code |
| `frontend/src/features/usage/UsagePage.tsx` | 1 | 1 | 151 | Monitor your Claude Code token usage and costs |
| `frontend/src/lib/pattern-utils.ts` | 2 | 2 | 4, 28 | * Validates permission patterns against Claude Code's current rules |
| `frontend/src/types/agentTeams.ts` | 1 | 1 | 3 | export type AgentTeamProvider = 'claude-code' \| 'codex-cli' \| 'copilot-cli' \| 'opencode-cli' \| 'pi-cli' \| 'muse-cli' |
| `frontend/src/types/providers.ts` | 1 | 1 | 1 | export type AgentProviderId = 'claude-code' \| 'codex-cli' \| 'copilot-cli' \| 'opencode-cli' \| 'pi-cli' \| 'muse-cli' |
| `frontend/tests/agent-mail-roster.test.tsx` | 3 | 3 | 20, 65, 78 | id, provider: 'claude-code', source: 'mcp', session_key: 'key-${id}', cwd: '/work/repo-${id}', |
| `frontend/tests/agent-mail-setup.test.tsx` | 15 | 16 | 80-82, 102, 104, 109, 118-119, 135, 189, 192, 194, 217, 219, 240 | expect(mailSetupState('claude-code', status())).toBe('connected') |
| `frontend/tests/agent-status.test.tsx` | 2 | 3 | 140, 154 | provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: 'deck-e2e-5:0.0', session_name: AGENT, |
| `frontend/tests/fixture-browser.mjs` | 2 | 2 | 29, 473 | "claude-code", |
| `frontend/tests/fixtures/factory/native-adapters.json` | 1 | 1 | 5 | "claude-code": { |
| `frontend/tests/fixtures/provider-operations/v1/catalog.json` | 81 | 81 | 5, 7-8, 162, 167, 172, 177, 182, 187, 192, 197, 202, 207, 212, 217, 222, 227, 232, 237, 242, 247, 252, 257, 262, 268, 279, 290, 301, 312, 323, 334, 345, 356, 367, 378, 389, 400, 411, 422, 433, 444, 692, 697, 707, 717, 722, 2825, 2830, 2840, 2850, 2855, 3267, 3272, 3282, 3292, 3297, 3709, 3714, 3724, 3734, 3739, 4151, 4156, 4166, 4176, 4181, 4593, 4598, 4608, 4618, 4623, 5035, 5040, 5050, 5060, 5065, 5477, 5482, 5492, 5502, 5507 | "claude-code": { |
| `frontend/tests/fixtures/provider-operations/v1/manifest.json` | 1 | 1 | 17 | "claude-code", |
| `frontend/tests/harness-list.test.tsx` | 6 | 7 | 47-48, 58, 70, 106-107 | { id: 1, slots: [{ provider: 'claude-code' }, { provider: 'claude-code' }, { provider: 'codex-cli' }] }, |
| `frontend/tests/harness-page.test.tsx` | 7 | 7 | 14, 46, 60, 64, 73, 75, 82 | useDashboard: () => ({ stats: { providerId: 'claude-code', warnings: [], unsupportedFeatures: [], sessionMetricKind: 'live', settingsKeys: 3, mcpServe… |
| `frontend/tests/header-harness-summary.test.ts` | 5 | 5 | 9, 13, 17, 24, 26 | const summary = harnessSummary([harness('Claude Code', true, '2.1.0'), harness('Codex', true, '0.50.0'), harness('Pi', true, '1.0.0'), |
| `frontend/tests/legacy-native-redirect.test.tsx` | 4 | 4 | 16, 72, 76, 82 | { id: 'claude-code', installed: false }, |
| `frontend/tests/live-sessions-page.test.tsx` | 2 | 5 | 26, 31 | useProviderContext: () => ({ selectedProviderId: 'claude-code', providers: [{ id: 'claude-code', display_name: 'Claude Code', installed: true, capabil… |
| `frontend/tests/native-context.test.tsx` | 3 | 4 | 70, 104, 106 | "claude-code", |
| `frontend/tests/navigation-affordances.test.tsx` | 2 | 2 | 36, 42 | expect(screen.getAllByRole('link', { name: /^Open/ })[0]).toHaveAttribute('href', '/harnesses/claude-code') |
| `frontend/tests/new-session-dialog.test.tsx` | 4 | 5 | 23, 27-28, 84 | fetchProviderLaunchOptions: vi.fn().mockResolvedValue({ provider: 'claude-code', bedrock_supported: false, fields: [] }), |
| `frontend/tests/project-selection.test.tsx` | 7 | 7 | 56, 62, 70, 88, 103, 107, 114 | renderAt('/harnesses/claude-code/mcp?project=${encodeURIComponent(TEAM_FOLDER)}') |
| `frontend/tests/provider-operations.test.tsx` | 4 | 5 | 109, 290, 293, 295 | const value:unknown=failure==='missing'?{}:failure==='wrong_provider'?catalogs['claude-code']:failure==='wrong_schema'?{...broken,schema_version:2}:br… |
| `frontend/tests/session-list.test.tsx` | 2 | 3 | 8, 55 | provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: 'coordinator-9d91:0.${over.pane_id}', |
| `frontend/tests/team-lanes-view.test.tsx` | 1 | 2 | 29 | provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: 't:0.${index}', session_name: 's${index}', |
| `frontend/tests/team-page.test.tsx` | 2 | 2 | 43, 234 | id, preset_id: 1, position: id, display_name: name, provider: 'claude-code', repo_id: 'repo', |
| `frontend/tests/team-sources.test.tsx` | 5 | 6 | 55, 135-136, 242, 244 | provider: 'claude-code', provider_display_name: 'Claude Code', tmux_target: '${name}:0.0', session_name: name, |
| `frontend/tests/team-url.test.tsx` | 1 | 1 | 40 | id, preset_id: 1, position: id, display_name: name, provider: 'claude-code', repo_id: 'repo', |
| `integrations/pi-agent-mail/manifest.ts` | 1 | 2 | 194 | "description": "Create an Agent Team preset.\n\n parent_issue_url is an HTTPS GitHub issue URL.\n\n Valid providers: claude-code, codex-cli, copilot-c… |
| `launch-posts.md` | 29 | 30 | 56, 66, 82, 88, 104, 109, 118, 124, 132, 146, 155, 163, 168, 185, 193, 207, 221, 231, 252, 258, 263, 309, 320, 331, 355, 366, 377, 386, 395 | We built a self-hosted web dashboard for Claude Code. |
| `scripts/e2e/fake-harness.sh` | 1 | 1 | 15 | claude) echo "2.1.0 (Claude Code)" ;; |
| `scripts/e2e/scenarios.py` | 13 | 13 | 59-61, 63-66, 69-70, 73, 443-444, 446 | {"id": 1, "name": "L1 Leader", "role": "leader", "provider": "claude-code", "color": "purple"}, |
| `scripts/product-factory/team-supervisor` | 2 | 2 | 208, 269 | paths.add(self.transcript(binding.get('provider') or 'claude-code', binding['repo_path'], native_id)) |

## 6. Validation performed

- Partition check: the four class line-number sets in section 4 were expanded and compared with the raw primary search output at the pin: pairwise disjoint, union equal, zero unmatched and zero double-counted lines.
- Arithmetic check: class line and occurrence sums equal the re-derived primary totals; every distinct-file figure was recomputed as a set union (per-class, per-term and per supplemental set), never by adding row counts.
- Range check: every "Line numbers" cell expands to exactly the counted lines of its row, and the example in each row is the text of that row's first listed line at the pin.
- Supplemental check: each section 5 table was regenerated from its own stated search at the pin, with primary-overlap lines removed and the overlap counted, as stated per set.
- Two independent counters (the shell searches in the appendix and the generation script's regex counter) agree on the section 2 figures, and the Leader independently reproduced the 1,596-line/255-file text total before approval.
- Local hygiene: `git diff --check` clean; the diff touches only this file. Hosted CI and independent review apply to the pull request head and are reported there, not claimed here.

Limits: this is a source-text inventory at one commit. It does not inventory the website repository (#792 did), generated outputs outside the tracked tree or untracked files, GitHub-side text (issue and release bodies), or the contents of the one binary archive. Classification follows the precedence rules in section 1.2; a line a reviewer would place differently is a one-line move between tables, never a change to the totals, because the partition is over the same searched lines.

## 7. Director decisions recorded after measurement, and what remains open

This inventory makes no decisions itself. After the measurement pin, the Director recorded decisions on 2026-11-08 in a [comment on #787](https://github.com/adrirubio/claude-deck/issues/787#issuecomment-6719501255), completed on 2026-11-09 by a [data-movement decision on #787](https://github.com/adrirubio/claude-deck/issues/787#issuecomment-6738481205). They change the guidance #789 and later items work to; they change no count, classification, or excerpt in this document:

| Question | Director decision (2026-11-08) |
|---|---|
| Release number | **v4.0.0.** No version reset, so the existing tags v1.0.0 to v3.1.0 are not broken. |
| Deprecation window | **None.** Old names are not kept working alongside the new ones; there is no parallel old-name support and no alias window. |
| First-start data movement (2026-11-09) | **Automatic one-time move.** On its first start, v4.0.0 moves the existing database file and backups folder to their new names, retaining every team, setting and history without any manual step. This is a requirement for #789 to design — including both-old-and-new-path conflicts and a no-manual-step v3.1 upgrade test — not a compatibility layer and not parallel old-name support; #791 describes it in migration guidance and release notes. The new path names themselves are left to #789. |
| Cloudflare project | **A new `synth-city-website` Pages project**, switched at go-live, with a redirect from the old site. |
| Preview access | **`noindex`** until the preview is shut down. |
| Trademark filing | **Later**, when the project gets traction; the screening is enough for now. |
| Cutover date | **No fixed date.** The cutover happens when the team is ready. |
| Named people | **Adrian (`adrirubio`) performs the transfers.** The Director owns every other role: freeze, exceptions, website release, Cloudflare and DNS. |
| The old repository name | **`adrirubio/claude-deck` is never recreated.** |

Still open, unchanged by this document: the exact new `deck_` tool prefix, the new database and backups path names, and announcement content and go-live approvals beyond the no-fixed-date decision above. #789 assesses replacement names per family for section 4.1 and for the supplemental families indexed in section 3.4 (listed in sections 5.1-5.4 and the 5.6 package exclusion) under the no-deprecation rule, and designs the decided first-start move above; not every test-only name necessarily needs any data movement. Nothing here authorizes a rename, a transfer or a code change.

## Appendix: reproducing every number

```bash
PIN=94cb599a98d60281db824fc8e726d841acdb46a0
OLD=c4daece7b300e2d07b884a75adf6ef8f99950389
PAT='Claude Deck|claude-deck|claude_deck|CLAUDE_DECK|claude_registry|\.claude-registry'
# primary (section 4) and probes (section 2)
git grep -I -n -i -E "$PAT" $PIN -- . | wc -l
git grep -I -l -i -E "$PAT" $PIN -- . | wc -l
git grep -I -n    -E "$PAT" $PIN -- . | wc -l
git grep    -l -i -E "$PAT" $PIN -- . | wc -l   # binary-inclusive file count
git grep -I -n -i -E "$PAT" $OLD -- . | wc -l
# supplemental sets (section 5)
git grep -I -n -w -E 'Deck'            $PIN -- .
git grep -I -n -i -E 'claudedeck'      $PIN -- .
git grep -I -n    -E 'deck_[a-z0-9_]+' $PIN -- .
git grep -I -n    -E 'Claude Code|claude-code' $PIN -- .   # then drop claude-code-registry-backend-only lines
git ls-tree -r --name-only $PIN | grep -i -E 'claude[-_ ]deck|claude_registry|claude-registry|claudedeck'
```

Occurrence counts are the number of non-overlapping left-to-right matches of the same pattern on the matched lines; `git grep` itself reports lines, so occurrences need a counter (any regex `findall` over the matched line text with the same case flag).
