# Albiex Synth City rename: compatibility design for runtime identifiers

**Issue:** #789. **Source pin:** `585af8b7c0339e9e87c41d802127da2d5176b697` (master as merged through PR #796). **Scope:** this file only; it designs behaviour for a later implementation team and changes no code. **Parent:** #787. **Input:** the merged inventory in this folder (`inventory.md`, measured at its own earlier pin `94cb599a98d6`); every code line cited below was re-verified at the pin above, and line numbers refer to that pin.

## Summary for the reader

This document designs how every runtime identifier that carries the old product name is replaced when **Albiex Synth City** v4.0.0 replaces Claude Deck v3.1. Later mentions shorten the product name to Synth City; that shortening is presentation only and does not decide any identifier.

The Director's current rules, recorded in `inventory.md` section 7, shape the whole design:

- the rename release is **v4.0.0**, with no version reset;
- there is **no deprecation window and no parallel old-name support**: after the upgrade the product does not read, accept or answer to the old names alongside the new ones;
- the one exception in kind is a **one-time automatic move**: on its first start, v4.0.0 moves the existing database file and the existing backups folder to their new names, retaining every team, setting and history with no manual step by the operator.

"No parallel support" and "one-time move" are different things, and this design keeps them apart throughout. A move happens once, during the first start of the new version, and afterwards only the new name exists. Nothing in this design reads both an old and a new name as an ongoing input, aliases an old tool name to a new one, or keeps an old header working. Where data created under an old name must survive — the database, backups, installer-written agent configuration, browser storage — the design moves or rewrites that data once, as part of the standard upgrade, never by asking the operator to run a separate repair command.

Exact new spellings are **proposals for the Director**, collected in section 3. The behaviour design (ordering, conflicts, crash safety, tests) does not depend on which spelling is chosen; if the Director picks a different scheme, the names substitute mechanically. Nothing here implements, transfers or deploys anything; #791 turns the user-visible parts of this design into the migration guide and release notes.

## 1. Rules and definitions

### 1.1 Decisions already made (not reopened here)

| Rule | Source |
|---|---|
| Product is Albiex Synth City; first mention and titles use the full name; no package, command or repository is named bare `synthcity`; the repository is `albiexai/synth-city` | `website-and-docs.md` section 4.7 (merged PR #797) |
| Release is v4.0.0; old names stop working at v4.0.0; no deprecation or alias window | Director decisions 2026-11-08, `inventory.md` section 7 |
| First start of v4.0.0 automatically moves the database file and backups folder, retaining all data, no manual step | Director decision 2026-11-09, `inventory.md` section 7 |
| Old repository `adrirubio/claude-deck` is never recreated; transfer mechanics are owned by the transfer runbook | `transfer-runbook.md` |

The campaign `README.md` in this folder still describes an earlier deprecation-window plan (its lines 27–29 and 42). That text is superseded by the decisions above and is not used as design input here.

### 1.2 Terms used in the tables

- **Replacement name** — the proposed new identifier. Every replacement name in this document is a proposal (section 3), not a decided fact.
- **Old-name duration** — how long the old identifier keeps working after v4.0.0 starts. Under the decided rules this is **none** for every family; each family section states it explicitly rather than leaving it implied.
- **First-start behaviour** — what the standard upgrade does automatically the first time v4.0.0 runs: nothing (paired components simply ship together), a one-time data move, or a one-time rewrite of configuration the product itself installed.
- **Deck-owned configuration** — entries the product's own installer wrote into a user's agent configuration files and can recognise again by its own markers. Only Deck-owned configuration is rewritten automatically. Configuration the operator wrote by hand (shell exports, custom service files, hand-edited overrides) is never rewritten; section 4 states per family what breaks and what the operator must rename, which #791 must document.
- **Manual step** — any operator action beyond performing the standard upgrade (stopping the old version and starting the new one by whatever method the operator already uses). The normal upgrade path designed here needs none. Deliberately ambiguous states (both old and new database present with data) stop safely and ask for a human; that is a conflict outcome, not the normal path.

### 1.3 The compatibility surface

The surface is the inventory's runtime-identifier class (377 lines, `inventory.md` section 4.1) plus the supplemental families indexed in its section 3.4: bare-`Deck` headers and commit trailers, the joined OpenCode export and old domain, the 36 `deck_` Agent Mail tools and 46 other `deck_` tokens, systemd unit filenames, and the backend package name. Section 4 covers each family once. Pure copy (the inventory's user-facing and docs classes) and history are out of scope except where a string is both copy and a recognised marker.

## 2. Evidence at the pin

All counts below were re-run at `585af8b`; appendix A gives the commands.

- There are 16 distinct `CLAUDE_DECK_*` environment names in the runtime class (`inventory.md` section 3.3). At this pin, 15 of them have production readers or writers; `CLAUDE_DECK_MAIL_TOKEN` appears only as a synthetic refusal case in the e2e isolation test (`frontend/e2e/g0/isolation.spec.ts:147`) and in the e2e documentation's token pattern (`frontend/e2e/README.md:42`). Section 4.1 designs for all 16 but marks that one test-only.
- The 36 Agent Mail tools are ordinary Python functions registered with the MCP server in `backend/mcp_shim/agent_mail_server.py` (first definition at line 357, `deck_whoami`); the function name is the tool name presented to agents.
- The application creates its database engine from settings at import time (`backend/app/database.py:12` imports `settings`; the engine is created at `backend/app/database.py:23–28` from `settings.database_url`), and the default database URL names the old file (`backend/app/config.py:30`). Tables are created on first use by `Base.metadata.create_all` inside `init_db` (`backend/app/database.py:1156–1165`), which the web app calls from its lifespan startup (`backend/app/main.py:25`). This ordering is the central constraint on the first-start move (section 4.6).
- Two different code paths compute the backups folder from the same old home folder: `backend/app/services/backup_service.py:73` and `backend/app/services/agent_mail_install_service.py:695`. The same home folder also holds bridge attachments by default (`backend/app/config.py:33`) and is created by the installer script (`scripts/install.sh:81`).

## 3. Proposed new names (Director choices)

Two coherent spelling schemes cover almost every family. The design tables use the **recommended** spelling, but neither scheme is approved by being written here; the examples carried over from earlier issues (`synth-city`, `SYNTH_CITY`) were illustrations, not decisions.

| Scheme | Shape | Strengths | Costs |
|---|---|---|---|
| **S — short product name** | `SYNTH_CITY_*`, `synth_city_*`, `X-Synth-City-*`, `synth_city.db`, `~/.synth-city` | Readable; tool and prompt text stays short; mirrors the decided repository name `albiexai/synth-city` | The Albiex qualifier is absent from the identifier itself; "Synth City" alone carries the moderate naming risk noted in `website-and-docs.md` section 4.7 |
| **Q — fully qualified** | `ALBIEX_SYNTH_CITY_*`, `albiex_synth_city_*`, `X-Albiex-Synth-City-*`, `albiex_synth_city.db`, `~/.albiex-synth-city` | Unambiguously Albiex's in every shared namespace | Every tool name, environment line and generated prompt grows by the qualifier on every use |

**Recommendation.** Use scheme S for identifiers that only ever pass between this product's own paired components (launcher-to-child environment variables, MCP tool names served by this product's own shim, headers between its own frontend, shim and backend), because those components are always installed and presented as Albiex Synth City together. Use scheme Q for names registered in namespaces shared with other software, where an unqualified name could collide or imply the wrong owner: package names, release artifacts, systemd units and install paths, the MCP server name written into third-party agent configuration, and the home data folder. This follows the existing rule that packages and commands must not be bare `synthcity` and should use `albiex` or `albiex-synth-city` (`website-and-docs.md` section 4.7). If the Director prefers one scheme everywhere, the substitution is mechanical and no behaviour in section 4 changes.

| Family | Old (evidence) | Recommended proposal | Qualified alternative |
|---|---|---|---|
| Environment prefix | `CLAUDE_DECK_` (e.g. `backend/mcp_shim/agent_mail_server.py:13`) | `SYNTH_CITY_` | `ALBIEX_SYNTH_CITY_` |
| Agent Mail tool prefix | `deck_` (`backend/mcp_shim/agent_mail_server.py:357` onward) | `synth_city_` | `albiex_synth_city_` |
| MCP server name | `claude-deck-mail` (`backend/app/services/agent_mail_install_service.py:34`; served name `backend/mcp_shim/agent_mail_server.py:22`) | `albiex-synth-city-mail` | — (already qualified) |
| Terminal header | `X-Claude-Deck-Terminal-Token` (`backend/app/api/v1/agent_bridge/router.py:384`) | `X-Synth-City-Terminal-Token` | `X-Albiex-Synth-City-Terminal-Token` |
| Operator/session headers | `X-Deck-Operator-Token`, `X-Deck-Session-Token` (`frontend/src/features/agent-mail/api.ts:22`; `backend/mcp_shim/agent_mail_server.py:125`) | `X-Synth-City-Operator-Token`, `X-Synth-City-Session-Token` | `X-Albiex-Synth-City-…` |
| Database file (default) | `claude_registry.db` (`backend/app/config.py:30`) | `synth_city.db` in the same directory | `albiex_synth_city.db` |
| Home data folder | `~/.claude-registry` (`backend/app/services/backup_service.py:73`) | `~/.albiex-synth-city` | — (already qualified) |
| GitHub labels (new defaults) | `claude-deck-ready`, `claude-deck-design` (`backend/app/models/database.py:246–247`) | `albiex-synth-city-ready`, `albiex-synth-city-design` | — (already qualified) |
| Browser storage keys | `claude-deck:selected-provider` (`frontend/src/contexts/ProviderContext.tsx:16`), `claude-deck.agent-teams.operator-token` (`frontend/src/features/agent-teams/operatorAuth.ts:1`) | `albiex-synth-city:selected-provider`, `albiex-synth-city.agent-teams.operator-token` (browser storage is a shared per-origin namespace) | — |
| Package names | `claude-code-registry-backend` (`backend/pyproject.toml:2`), `claude-deck-docs` (`docs/package.json:2`), `claude-deck-pi-agent-mail` (`integrations/pi-agent-mail/package.json:2`) | `albiex-synth-city-backend`, `albiex-synth-city-docs`, `albiex-synth-city-pi-agent-mail` | — |
| Release artifacts | `claude-deck-frontend-v<version>.zip/.tar.gz` (`.github/workflows/release.yml:102–105`) | `albiex-synth-city-frontend-v<version>.zip/.tar.gz` | — |
| Product-factory units and root | `claude-deck-product*.service/.timer`, `/opt/claude-deck-product` (`scripts/product-factory/claude-deck-product.service:3–13`) | `albiex-synth-city-product*.service/.timer`, `/opt/albiex-synth-city-product` | — |
| Generated git identity | `…@claude-deck.local`, `… (Deck agent)` (`backend/app/services/github_workspace_service.py:260`, `:264`) | `…@synth-city.local`, `… (Synth City agent)` for new workspaces only | `…@albiex-synth-city.local` |

The frontend package needs no rename: its package name is simply `frontend` (`frontend/package.json:2`). The application version fields (`backend/app/config.py:16–17`, `backend/pyproject.toml:3`, `frontend/package.json:4`, root `VERSION`) move to 4.0.0 under the existing version-bump tooling; that is release work, not compatibility design, and is noted here only so the test list can pin the starting version at 3.1.0.

## 4. Family-by-family design

### 4.1 Environment variables (`CLAUDE_DECK_*`)

**Old-name duration: none.** v4.0.0 reads and writes only the new prefix. There is no read-both fallback and no translation layer.

The 16 names fall into three behaviour groups. Who sets a variable decides what the upgrade can do about it.

| Group | Names | Set by / read by (evidence) | First-start behaviour |
|---|---|---|---|
| **A. Launcher-injected session identity** | `CLAUDE_DECK_TEAM_PRESET_ID`, `…_PRESET_NAME`, `…_TEAM_SLOT_ID`, `…_SLOT_NAME`, `…_SLOT_ROLE`, `…_SLOT_COLOR`, `CLAUDE_DECK_URL`, `CLAUDE_DECK_PROVIDER` (in session launches) | Written by the backend when it launches or discovers a session (`backend/app/services/agent_team_service.py:1001–1006`; recognised in `backend/app/services/agent_bridge/discovery.py:25–30`; spawn gate `backend/app/services/agent_bridge/spawn.py:107`); read by the shim and hooks (`backend/mcp_shim/agent_mail_server.py:13–14`, `:247–248`; `backend/mcp_shim/agent_mail_hook.py:62–73`; `backend/mcp_shim/team_question_hook.py:8`) and by the Pi client (`integrations/pi-agent-mail/client.ts:58–59`) | None needed for new sessions: launcher, shim and hooks ship together and all speak the new names from the first new launch. Sessions already running across the upgrade are the exception handled in section 5 (they must be ended or relaunched; their inherited old variables are never translated) |
| **B. Installer-written agent configuration** | `CLAUDE_DECK_URL`, `CLAUDE_DECK_PROVIDER` (in provider config), `CLAUDE_DECK_MAIL_OPT_IN`, `CLAUDE_DECK_MAIL_PYTHON`, `CLAUDE_DECK_MAIL_SHIM` | Written into users' agent configuration by the install service (`backend/app/services/agent_mail_install_service.py:546–547`, `:776`, `:924–925`, `:950–997`, `:1081–1100`; Pi readiness `backend/app/services/pi_mail_readiness.py:45–49`); read by the shim, the generated OpenCode plugin (`agent_mail_install_service.py:583–584`, `:610–611`) and the Pi extension (`integrations/pi-agent-mail/extension.ts:8`, `client.ts:153–154`) | Rewritten once, automatically, as part of the Deck-owned configuration rewrite in section 4.2. Values are carried across (for example a non-default URL); only the keys change |
| **C. Operator-set process environment** | `CLAUDE_DECK_INSTANCE_NAME`, `CLAUDE_DECK_INSTANCE_ID`, `CLAUDE_DECK_INSTANCE_ACCENT`, `CLAUDE_DECK_EXTERNAL_ACTOR_TOKEN` | Set by the operator in a shell, service file or supervisor configuration; read when identity is resolved (`backend/app/services/instance_identity.py:107`, `:110`, `:115`) and when a supervisor actor credential is presented (`backend/mcp_shim/agent_mail_server.py:182`) | Not rewritten: the product does not own those files. Under v4.0.0 the old variables are ignored — a custom instance name/id/accent falls back to the hostname-derived identity and a supervisor token supplied only under the old name is absent — until the operator renames them. #791 must list this table. To make the break discoverable rather than silent, the implementation should emit a one-time startup warning naming any old-prefixed variables present in its own process environment and their new names, **without using their values**; a warning that never consumes the value is a diagnostic, not old-name support, and it must be removed if the Director objects to even that |

`CLAUDE_DECK_MAIL_TOKEN` has no production reader at the pin (section 2); it exists as an e2e refusal example and as the `CLAUDE_DECK_*TOKEN*` guard pattern. The e2e harness renames its guard to the new prefix (`frontend/e2e/g0/isolation.spec.ts:27`, `:141–147`; `scripts/e2e-instance.sh:50–54`, `:169`, `:201`) — test-only work with no upgrade behaviour. The same applies to the scenario and manifest generators that inject group-A names (`scripts/e2e/scenarios.py:618–623`; `scripts/generate-pi-mail-manifest.py:15–23`; `integrations/pi-agent-mail/sync_manifest.py:15`): they are regenerated from new code, never migrated.

One naming detail needs care in implementation: settings are read without an environment prefix (`backend/app/config.py:9–13` sets only an `.env` file and case-insensitive matching), so product environment variables such as the instance names are read directly via `os.getenv`, not through settings. Renaming them touches each reader; there is no single prefix constant to flip. The generated OpenCode plugin template also embeds the URL under a build-time placeholder (`__DECK_URL__`, replaced at `agent_mail_install_service.py:675`) — an internal template token that renames with the template.

### 4.2 MCP server name and the installer

**Old-name duration: none.** v4.0.0 serves and registers only the new MCP server name. The old registration in a user's agent configuration is removed once, automatically, and replaced — it is never left working in parallel.

Current state at the pin: one constant names the server everywhere (`MCP_SERVER_NAME = "claude-deck-mail"`, `backend/app/services/agent_mail_install_service.py:34`), the shim serves under the same literal (`FastMCP("claude-deck-mail")`, `backend/mcp_shim/agent_mail_server.py:22`), and per-provider apply/uninstall functions register or remove that name plus the product's hooks:

| Provider | Apply / uninstall (evidence) | What the installer wrote under the old name |
|---|---|---|
| Claude Code | `apply_claude_code_install` / `uninstall_claude_code` (`:897`, `:932`; server lookup `:858`, `:915–918`, `:936–937`) | MCP server entry + hooks in user settings, with group-B environment values |
| Codex | `apply_codex_install` / `uninstall_codex` (`:941`, `:973`; detection `:512–518`; removal `:979`) | MCP server registered by CLI + hooks file entries (`codex_hooks_path`, `:92`) |
| Copilot | `apply_copilot_install` / `uninstall_copilot` (`:986`, `:1015`; detection `:524–534`; removal `:1025`) | MCP server entry + a hooks **filename derived from the server name** (`copilot_hooks_path` returns `…/hooks/{MCP_SERVER_NAME}.json`, `:96–97`) |
| OpenCode | `apply_opencode_install` / `uninstall_opencode` (`:1033`, `:1050`; detection `:568–577`) | MCP entry in `opencode.json(c)` (`:100–107`) + a generated plugin **file** at `…/plugins/claude-deck-agent-mail.js` (`:110–111`; provider descriptor `backend/app/services/providers/opencode_cli.py:39`) recognised by its marker text (`_OPENCODE_PLUGIN_MARKER`, `:65`, written via the template at `:582` onward, tested at `:684`, `:1068`) and exporting `ClaudeDeckAgentMailPlugin` (`:599`) |
| Muse | `apply_muse_install` / `uninstall_muse` (`:1134`, `:1152`; detection `:803–805`) | MCP server entry in Muse settings with group-B environment values (`:776`) |
| Pi | readiness + generated manifest (`backend/app/services/pi_mail_readiness.py:45–49`; `integrations/pi-agent-mail/sync_manifest.py:15`, exported manifest registered by `integrations/pi-agent-mail/extension.ts:36`) | Extension environment (group B) + generated tool manifest; the Pi client also hard-codes old-name runtime artefacts (`claude-deck-pi` client name and `/tmp/claude-deck-pi-…` directory, `client.ts:88–91`, `:139`) which rename with the code and need no data move (the directory is per-run runtime state) |

**Design — one-time Deck-owned rewrite during the standard upgrade.** The implementation adds an upgrade step that runs automatically on the first start of v4.0.0 (sequencing in section 5), reusing the existing primitives rather than inventing a second installer:

1. For each provider, detect the old registration using the same checks the status code already performs (old server name present, old plugin marker present, old hooks filename present). Detection reads configuration **files the product itself installed**; it does not make the old name work.
2. Take the existing pre-mutation backup first (`_backup_before_mutation`, `:693–699`, already invoked by every apply/uninstall path, e.g. `:898`, `:933`, `:945`), so a failed rewrite is recoverable from the backups folder — noting the ordering constraint that this backup must land in the **new** backups folder, which is why section 5 sequences the data move before this step.
3. Remove the old registration with the existing uninstall behaviour for that provider, then apply the new registration with the existing apply behaviour under the new constant. Carry operator-modified **values** inside the Deck-owned entry across (a changed URL or provider value under a renamed key); do not carry across entries that no longer match the recognised Deck-owned shape.
4. For OpenCode, regenerate the plugin file under its new filename with the new marker and export, and delete the old plugin file only if it still contains the old marker (proof the product generated it). For Copilot, the hooks filename follows the new server name; remove the old-named hooks file as part of the same provider step.
5. Record the outcome per provider in the install-status surface (`get_install_status`, `:833`) so the operator sees "renamed", "was not installed", or "needs attention" without reading logs.

**Custom overrides and failure rules.** The rewrite touches only the recognised Deck-owned entries. A hand-edited entry that no longer matches the recognised shape, an unwritable file, or a missing provider CLI leaves that provider untouched, reports "needs attention" for it, and does not block the rest of the upgrade or the data move; the operator then re-runs the ordinary Mail setup action for that provider, which the migration guide (#791) describes. That recovery path exists for damaged configurations only — the normal upgrade proof in section 7 passes with **no** such action, because a separate repair step would not satisfy the decided no-manual-step requirement. Provider configuration the operator created entirely by hand, naming the old server without using the installer, is not Deck-owned and is not rewritten; it stops resolving at v4.0.0 and belongs in the #791 breaking-change list.

The MCP protocol test client name `claude-deck-test` (`backend/app/services/mcp_service.py:600`, `:865`) and the shim heartbeat thread name `claude-deck-agent-mail-heartbeat` (`backend/mcp_shim/agent_mail_server.py:303`) are emitted identifiers with no stored counterpart; they rename with the code.

### 4.3 Agent Mail tools (`deck_*`)

**Old-name duration: none.** The campaign README's earlier promise that old `deck_` names "stay as aliases during the deprecation window" (`README.md:42`) is withdrawn by the 2026-11-08 decisions. v4.0.0 registers only the new prefix; there are no alias registrations in the shim, the Pi manifest, or anywhere else.

The rename is a pure prefix substitution over the 36 tools actually defined in the shim (`inventory.md` section 5.3 token table). With recommended prefix `synth_city_` (section 3):

| Old tool | Proposed new tool | Old tool | Proposed new tool |
|---|---|---|---|
| `deck_ack_continuation` | `synth_city_ack_continuation` | `deck_list_work_items` | `synth_city_list_work_items` |
| `deck_ack_message` | `synth_city_ack_message` | `deck_paste_bridge_attachment` | `synth_city_paste_bridge_attachment` |
| `deck_approve_work_item` | `synth_city_approve_work_item` | `deck_plan_team_launch` | `synth_city_plan_team_launch` |
| `deck_attach_image_to_bridge_session` | `synth_city_attach_image_to_bridge_session` | `deck_prepare_operator_action_contexts` | `synth_city_prepare_operator_action_contexts` |
| `deck_check_inbox` | `synth_city_check_inbox` | `deck_prepare_work_remaining_summary` | `synth_city_prepare_work_remaining_summary` |
| `deck_create_handoff` | `synth_city_create_handoff` | `deck_render_github_summary` | `synth_city_render_github_summary` |
| `deck_create_team` | `synth_city_create_team` | `deck_reply` | `synth_city_reply` |
| `deck_decide_continuation` | `synth_city_decide_continuation` | `deck_report_backlog_assessment` | `synth_city_report_backlog_assessment` |
| `deck_get_backlog_coordination` | `synth_city_get_backlog_coordination` | `deck_report_dispatch_status` | `synth_city_report_dispatch_status` |
| `deck_get_operator_action_contexts` | `synth_city_get_operator_action_contexts` | `deck_report_owner_followup` | `synth_city_report_owner_followup` |
| `deck_get_team_summary` | `synth_city_get_team_summary` | `deck_request_context` | `synth_city_request_context` |
| `deck_get_work_item_context` | `synth_city_get_work_item_context` | `deck_request_continuation` | `synth_city_request_continuation` |
| `deck_launch_team` | `synth_city_launch_team` | `deck_request_work_item_approval` | `synth_city_request_work_item_approval` |
| `deck_list_bridge_attachments` | `synth_city_list_bridge_attachments` | `deck_retry_work_item` | `synth_city_retry_work_item` |
| `deck_list_scope_revisions` | `synth_city_list_scope_revisions` | `deck_send_message` | `synth_city_send_message` |
| `deck_list_team` | `synth_city_list_team` | `deck_supervisor_checkin` | `synth_city_supervisor_checkin` |
| `deck_list_teams` | `synth_city_list_teams` | `deck_update_team_campaign` | `synth_city_update_team_campaign` |
| `deck_update_team_parent_issue` | `synth_city_update_team_parent_issue` | `deck_whoami` | `synth_city_whoami` |

Consequences the design accepts explicitly:

- **Product-generated prompts fix themselves.** Dispatch briefs, wake prompts and policy text that name tools are generated from code at send time (examples: `backend/app/services/github_dispatch_service.py:1431` onward; `backend/app/services/team_communication_policy.py:21–22`; the hook nudge prefix in `scripts/e2e-agent-mail-same-repo-codex.sh:31` is test-side). After the rename they emit new names with no data migration.
- **Stored free text is not rewritten.** Team charters, saved prompts, skills and message history inside the moved database can contain old tool names as prose. The first-start upgrade does **not** rewrite database text: a blind substitution could corrupt quoted history, and the moved database must remain byte-identical apart from normal schema compat migrations (section 4.6). Charters the operator keeps using must be updated by their owner; #791 lists this as a breaking change. Tool *descriptions* presented to agents come from the shim docstrings and the generated Pi manifest, both regenerated from code, so an agent in a new session always sees the new names.
- **The Pi surface follows the manifest.** The Pi extension registers whatever the generated manifest contains (`integrations/pi-agent-mail/extension.ts:35–36`), and the manifest is generated from the shim's tool list (`integrations/pi-agent-mail/sync_manifest.py:21`), so renaming the Python functions and regenerating the manifest renames the Pi tools with no separate hand list. The Pi client's two hard-coded calls follow the same substitution (`deck_whoami` at `integrations/pi-agent-mail/client.ts:168`; the private close-generation call at `:207`, designed with the other tokens in section 4.4).
- **API error text that names a tool** (for example the `use_deck_approve_work_item` refusal at `backend/app/api/v1/agent_teams.py:1112`) is a machine-read string agents act on; it renames in the same substitution and its tests move with it.

### 4.4 The other `deck_` tokens

The inventory separates 46 further `deck_[a-z0-9_]+` tokens from the 36 tools (`inventory.md` section 5.3). They do not share one rule:

| Category | Tokens (evidence) | Design |
|---|---|---|
| Internal Python identifiers | `deck_base_url` (`backend/app/services/agent_mail_install_service.py:69`), `deck_url` parameters, `_deck_request` (`backend/mcp_shim/agent_mail_server.py:114`) | Ordinary code rename inside the implementation; no stored or external counterpart, no upgrade behaviour |
| FastAPI header parameter names | `x_deck_operator_token`, `x_deck_session_token` (e.g. `backend/app/api/v1/deps.py:67`, `:120`; `backend/app/api/v1/agent_mail.py:77`) | **Not merely internal:** FastAPI derives the HTTP header name from the parameter name, so these tokens *are* the `X-Deck-…` headers of section 4.5. Rename together with every client that sets them |
| Machine-readable error codes | `deck_unreachable` (`agent_mail_server.py:52`), `deck_http_error` (`:78`, recognised again at `:976` and by the Pi client at `integrations/pi-agent-mail/client.ts:185`) | Paired producer/consumer rename in one release. External scripts matching these codes break; list in #791. Do not keep emitting the old codes "for safety" — that would be parallel support of an old identifier |
| Private generation-close tool | `__deck_mail_close_generation` (defined `agent_mail_server.py:311`, registered `:332–333`, called by Pi at `client.ts:207`) | Renames with the tool prefix substitution (keeping its private double-underscore shape); shim and Pi client ship together |
| Internal database table | `deck_compat_migrations` (created `backend/app/database.py:394`, `:784`; read `:401`, `:789`; written `:801`, `:1125`; also read by `backend/app/services/factory_audit_service.py:956`) | **Preserve the table name.** It is an opaque internal bookkeeping name inside the user's database file; renaming it would orphan the applied-migration record the compat migrations themselves consult on every start. This is the opaque-constant case of section 4.8, preserved with rationale, not an input alias |
| Test and fixture names | the long tail of one-occurrence tokens (`deck_create_team_posts_to_team_api`, `deck_request_routes_by_api_prefix`, …) plus test-only references to tools that do not exist as definitions (`deck_read_inbox`, `deck_list_agents`, `deck_reserve_paths`, `deck_set_status`, `deck_check_path_conflicts`, `deck_list_path_leases`, `deck_release_paths`, `deck_join_scope`, `deck_list_scopes`, `deck_update_expertise`, `deck_down`, `deck_status`, `deck_version`, `deck_mailbox_mcp`, `deck_mailbox_hooks`, `deck_guard`, `deck_agent_mailbox_implementation_plan`, `deck_pi_manifest`, `deck_reply_context`, `deck_owned_pr_contract`) | Rename or leave per ordinary test maintenance during implementation; they pin no production contract. Where such a token is a *negative* fixture (an unknown tool name that must be refused), the fixture should use a name that stays unknown after the rename |

### 4.5 Headers, markers and trailers

**Old-name duration: none.** Every header below is set by this product's own frontend or shim and read by its own backend; all sides ship in the same release, so no cross-version reading is designed or needed.

| Identifier | Evidence (writer → reader) | Design |
|---|---|---|
| `X-Claude-Deck-Terminal-Token` | Set by the frontend bridge client (`frontend/src/features/cc-bridge/api.ts:43`); read as a FastAPI header alias (`backend/app/api/v1/agent_bridge/router.py:384`, `:407`, `:424`, `:471`) | Rename alias and client together to the proposed `X-Synth-City-Terminal-Token`. A stale browser tab running old frontend code against a new backend fails its bridge calls until reloaded; acceptable, and the standard upgrade replaces the served frontend |
| `X-Deck-Operator-Token` | Set by the frontend (`frontend/src/features/agent-mail/api.ts:22`, `:124`), the shim's campaign call (`backend/mcp_shim/agent_mail_server.py:970`) and maintenance operations (`backend/app/services/maintenance_operations.py:226`); read via the `x_deck_operator_token` parameters (section 4.4) | Rename parameter (which renames the header) and all writers together |
| `X-Deck-Session-Token` | Set by the shim (`agent_mail_server.py:125`); read via `x_deck_session_token` parameters | Same. Capability-token **values** and their stored hashes are unaffected: the hash is plain SHA-256 of the token with no name-derived seed (`backend/app/services/agent_mail_service.py:358–364`), so live sessions keep their credentials across the header rename once their shim process is the new one (section 5) |
| Commit trailers `Deck-Agent-Slot`, `Deck-Work-Item` | Requested in generated dispatch briefs (`backend/app/services/github_dispatch_service.py:1448–1450`) | New briefs request proposed `Synth-City-Agent-Slot` / `Synth-City-Work-Item`. Trailers already written into git history stay as historical record and are never rewritten; any code that *reads* trailers from history must be inventoried by the implementation team — at this pin the names are emitted instructions, and no production reader of these two trailer names was found in the searches of appendix A, so the design assumes write-only. If implementation discovers a reader, reading already-committed history is the history class, not new-name emission, and needs a Director-visible decision before it reads both |
| OpenCode plugin marker + export | `_OPENCODE_PLUGIN_MARKER = "Claude Deck Agent Mail OpenCode plugin"` (`agent_mail_install_service.py:65`); export `ClaudeDeckAgentMailPlugin` (`:599`) | The new generated file uses new marker/export (proposed: "Albiex Synth City Agent Mail OpenCode plugin", `AlbiexSynthCityAgentMailPlugin`). The old marker is recognised **once**, by the section 4.2 rewrite, solely to identify and replace the file the product generated; after the rewrite no code path recognises it |
| E2E prompt prefix (test-side marker) | `INBOX_NUDGE_PREFIX='Claude Deck Agent Mail: please call 'deck_check_inbox'…'` (`scripts/e2e-agent-mail-same-repo-codex.sh:31`, searched at `:148`, `:152`) | Renames with the generated nudge text it mirrors; test-only |

### 4.6 Database file and home data folder: the one-time automatic move

**Old-name duration: none.** After the first start of v4.0.0 completes this move, the old paths are never read again. The move is a rename of the operator's existing data, not a fallback: the new code's only configured paths are the new ones.

#### 4.6.1 What moves, and what does not

| Path today | Evidence | Proposed new path | Move scope |
|---|---|---|---|
| `./claude_registry.db` (relative to the backend working directory) + SQLite sidecars `-wal`, `-shm`, `-journal` | Default `database_url` (`backend/app/config.py:30`); WAL journal mode is set on every SQLite connection (`backend/app/database.py:38`), so sidecar files are a normal part of the database | `./synth_city.db` + corresponding sidecars, same directory | Move **only when the effective `database_url` is the shipped default**. A custom `DATABASE_URL` (any other SQLite path, `:memory:` as in `backend/tests/conftest.py:18`, or a non-SQLite URL) names a database the operator chose; the upgrade leaves it exactly where it is and the new default does not apply to them |
| `~/.claude-registry/` whole folder — `backups/` and, by default, `bridge-attachments/` | Backups: `backend/app/services/backup_service.py:73` and `backend/app/services/agent_mail_install_service.py:695` (two computations of the same folder — the implementation must move one folder and repoint both); attachments default `backend/app/config.py:33`; folder created by `scripts/install.sh:81` and mentioned in `.gitignore:61` | `~/.albiex-synth-city/` with the same subfolders | Move the whole folder, so backups **and** bridge attachments survive together. A custom bridge-attachment directory (the `bridge_attachment_dir` setting overridden away from the default, `backend/app/config.py:33`) is operator-chosen and is not moved; its contents stay valid because attachment records reference it through settings, not through the old name |

Nothing inside the database file is renamed by the move. The file is the same SQLite database afterwards: same schema, same rows (every team, setting, message and history), same applied-migration record in `deck_compat_migrations` (preserved per section 4.4). The project has no separate migration framework — schema evolution is `create_all` plus the internal compat migrations (`backend/app/database.py:1156–1165`) — so a file rename is sufficient and no data export/import is designed or needed.

#### 4.6.2 Ordering: the move must happen before first touch

At the pin the engine is created from settings when `app.database` is imported (`backend/app/database.py:12`, `:23–28`), and `init_db` would happily create a brand-new empty database at the new default path via `create_all` (`:1161–1162`) the first time the lifespan runs (`backend/app/main.py:25`). If the move ran after either of those, the upgrade would silently start empty and then find the new path "already exists". The design invariant is therefore:

> **Before settings are used to create an engine, and before any code path can create the new database file, the first-start move for the default paths has completed (or ruled itself out).**

Mechanisms are the implementation team's choice (for example a small pre-import bootstrap in the product's process entry point, before `app.main` / `app.database` import), but any mechanism must satisfy the invariant for the way the product is actually started — including the product-factory unit's `uvicorn app.main:app` command (`scripts/product-factory/claude-deck-product.service:13`) — and the test list (section 7, T-D3) proves no empty new file can appear first. Direct library imports of `app.database` by the operator's own scripts are outside the supported entry points; #791 should say the first run after upgrading must be the product itself.

#### 4.6.3 Conflict matrix (database)

Decided by this design where the Director left conflict behaviour to #789. "Exists with data" means a non-empty SQLite file; a zero-byte file is treated as a failed-creation artefact, not data.

| Old default DB | New default DB | Behaviour |
|---|---|---|
| Absent | Absent | Fresh install. Create only the new file via the normal `create_all` path. No old name is ever written |
| Present | Absent | **Normal upgrade.** Move the set (main file + sidecars) to the new names per section 4.6.5, then start normally |
| Absent | Present | Already upgraded (or restored by hand). No-op; never look at the old path again |
| Present | Zero-byte only | Treat as "present / absent": remove the zero-byte artefact as part of the same journalled move, then move. This state is only reachable if something created the file without initialising it, and the move journal (4.6.5) records that it happened |
| Present with data | Present with data | **Stop.** Do not merge, do not pick a winner, do not delete either file. Abort startup before opening either database, with an operator-visible message naming both paths. Two populated databases cannot be reconciled automatically without risking teams/history, and silently choosing one would violate the data-retention decision. This is the only database outcome that needs a human, and it cannot arise from the normal upgrade sequence |

The home-folder move uses the same matrix at folder granularity, with one softening: if **both folders exist**, merge contents file-by-file without ever overwriting an existing new file, because backup archives and attachments are independent files, not one consistent database. Name collisions keep the new folder's file and leave the old file in place with a logged notice; the old folder is removed only when it ends empty. If the collision set is non-empty the upgrade still completes (backups are recoverable history, not live state), and the notice tells the operator what was left behind.

#### 4.6.4 Custom-path exclusions

The move is defined over the **shipped defaults only**. Concretely, the implementation must compare the effective locations against the old defaults rather than pattern-matching filenames: an operator whose `DATABASE_URL` already points at `…/my.db`, or whose backups live elsewhere through their own tooling, is untouched — including an operator who coincidentally named a *custom* file `claude_registry.db` in a different directory. The e2e instance (the `test_instance` settings, `backend/app/config.py:75–79`) and in-memory test databases must never trigger a move.

#### 4.6.5 Crash safety, partial moves and idempotence

The move runs while the old version is stopped (the standard upgrade; section 5 makes quiescence a prerequisite, since an open WAL database must not be renamed under a live writer). Requirements, in order:

1. **Journal first.** Write a small move-intent record beside the target (intended source, target, and file set) and flush it, before renaming anything. On every later start, a leftover journal means a previous move was interrupted: resume from the recorded state, never improvise.
2. **Rename sidecars, main file last.** On the same filesystem each rename is atomic; renaming `-wal`/`-shm`/`-journal` first and the main `.db` last makes the main file's arrival the commit point. Flush the containing directory after the set lands. Permissions and ownership are preserved because rename keeps the inode.
3. **Interruption states are all recoverable.** Crash before any rename → old set intact, redo the move. Crash mid-set → journal + which files already carry the new name define exactly what remains; finish the renames. In no state is a file deleted before its replacement exists under the new name.
4. **Cross-filesystem fallback.** If rename fails because source and target are somehow on different filesystems, copy to a temporary name in the target directory, verify size (and checksum where the implementation provides one), rename into place, and only then remove the source. A failed verification removes the temporary copy and aborts startup with the old data untouched.
5. **Idempotence.** After a successful move the journal is removed and the "old absent / new present" cell of the matrix makes every subsequent start a no-op. Running the move twice must be indistinguishable from running it once.
6. **Failure is loud and early.** Any unrecoverable move failure aborts startup **before** the engine opens a database — starting empty is always worse than not starting. The backups-folder move is sequenced before the section 4.2 rewrite so its pre-mutation backup lands in the new folder, but a backups-move failure must not strand an already-moved database: the two moves are journalled independently, and the database move never rolls back because the folder move failed.

Downgrade note: after the move, v3.1 would look for the old filenames and not find them; rolling back the release is therefore "stop, rename back by hand" — an operator recovery action for the release plan (#791) to document, not a behaviour v4.0.0 implements.

### 4.7 Stored labels, browser storage, packages, artifacts and units

**GitHub dispatch/design labels — defaults rename, stored values do not.** The label names are column *defaults* (`backend/app/models/database.py:246–247`; API default `backend/app/models/schemas.py:2544–2545`; frontend defaults `frontend/src/features/agent-teams/ScopeSettingsDialogs.tsx:104–105` and `frontend/src/features/factory/RepositorySetupPage.tsx:43`), but each scope's effective label is a stored value the watcher and dispatcher compare against live GitHub issue labels (`backend/app/services/github_watcher_service.py:172`, `:283`; `backend/app/services/github_dispatch_service.py:1079`). Design: v4.0.0 changes the defaults for **new** scopes to the proposed names (section 3) and leaves every existing scope's stored label untouched, so upgraded installations keep matching the labels already on their GitHub issues with no manual step. Renaming the actual GitHub labels (which, on GitHub, preserves issue associations) plus the stored values is a possible coordinated clean-up, but it is an operational choice for the implementation/release work — never an automatic database rewrite during first start, because the database half alone would break matching until the GitHub half happened. Old-name duration for *code defaults*: none. For *stored label data*: the strings survive as operator data, exactly like a team whose name mentions the old product; that is data retention, not code support.

**Browser storage keys — one-time copy-then-delete on first load.** Two keys hold user state: the selected provider (`frontend/src/contexts/ProviderContext.tsx:16`, read `:21`, written `:44`; also read directly at `frontend/src/features/native-settings/surfaceRegistry.tsx:195`) and the operator token (`frontend/src/features/agent-teams/operatorAuth.ts:1`, read `:13`, written `:26`, removed `:34`). Losing the provider choice is a nuisance; losing the stored operator token forces re-entry. Design: on first load of the v4.0.0 frontend, if a new key is absent and its old key is present, copy the value to the new key and delete the old key — the browser-storage analogue of the file move. This is a one-time migration inside the standard upgrade, not an ongoing read-both: after the copy, only new keys are read. The e2e and test references to the old keys (`frontend/e2e/lane-c/support.ts:7`; `frontend/tests/factory.test.tsx:90–91`, among others in `inventory.md` section 4.1) rename with the constants.

**Package names and lockfiles.** Rename per section 3 (`backend/pyproject.toml:2`; `docs/package.json:2`; `integrations/pi-agent-mail/package.json:2`) and regenerate the affected lockfiles (`backend/uv.lock` records the backend project name; `docs/package-lock.json:2`, `integrations/pi-agent-mail/package-lock.json:2` record theirs). No installed-state migration beyond a normal reinstall of the new release; old-name duration: none. The docs deploy script's sibling-website path (`scripts/deploy-docs.sh:7`) follows the website repository rename owned by the transfer runbook and #792.

**Release artifacts.** The release workflow builds and uploads old-named archives (`.github/workflows/release.yml:102–105`, uploaded `:133–134`, `:147–148`). From v4.0.0 the archives carry the proposed new names; previously published release assets keep their historical filenames. Any operator script that downloads a hard-coded asset name breaks — list in #791. Old-name duration: none for new releases.

**Product-factory systemd units and install root.** The five unit files `claude-deck-product.service`, `-tmux.service`, `-supervisor.service`, `-supervisor.timer`, `-supervisor-failure.service` reference each other by name (`After=`/`Requires=` at `scripts/product-factory/claude-deck-product.service:3–4`; supervisor unit `:3–4`, timer `:7`) and point into `/opt/claude-deck-product` (`claude-deck-product.service:10–13`; the same root is embedded in `scripts/product-factory/productctl:4`, `product-supervisor:4`, `agent-tmux:4–5`, `controller-tmux:2`). Design: rename units and root together per section 3 as a **factory operations change, sequenced with the transfer**, not as part of an end-user first start (these files operate this project's own factory; ordinary installations never install them). systemd has no rename: the operational sequence is disable/stop old units, move the install root, install/enable new units, start — with no period where both unit sets are enabled against the same state directory. Old unit names are not kept as aliases. The factory's own local state paths under the same stem (for example its state database and tmux socket, `scripts/product-factory/product-supervisor:49`, `scripts/product-factory/agent-tmux:5`) move in the same operations change. The exact cutover steps belong to operations planning under the transfer runbook's "the factory points at the old names" section, not to the v4.0.0 first-start code.

**Generated git identities.** New dispatch workspaces get the proposed new bot email/display shape (section 3; today `backend/app/services/github_workspace_service.py:260`, `:264`). Existing commits and workspace configs keep the identity they were created with — git history is the history class and is never rewritten for a rename.

### 4.8 Opaque constants: preserve, do not "rename"

**Rule:** a string nobody types, reads or matches from outside — whose only job is to be mixed into a hash or to name an internal bookkeeping object — is preserved byte-for-byte, with the reason recorded next to it in code during implementation. Preserving such a constant is **not** old-name support: it accepts no old-name input, presents no old name to any user, and changing it would silently invalidate existing data. This class must stay narrow; anything a user, agent, script or another program can observe or supply belongs to sections 4.1–4.7.

| Constant | Evidence | Why changing it breaks data | Verdict |
|---|---|---|---|
| Instance-ID derivation seed `f"claude-deck:{hostname}"` | `backend/app/services/instance_identity.py:75–79` (`_stable_id`, used when no explicit instance ID is set, `:110`) | The derived instance ID is the installation's stable identity; changing the seed changes the ID of every default installation at upgrade, orphaning anything keyed to the old ID. (The accent digest beside it hashes the hostname alone, `:83`, and needs nothing) | **Preserve the exact v1 seed bytes.** The variable/comment may be renamed to record that it is a frozen version-1 domain string. A future re-key would need its own stored-ID migration design; it is not part of the rename |
| Workspace-lease hash domain `b"claude-deck:github-workspace-lease:v1\x00"` | `backend/app/services/github_approval_service.py:69`, mixed into lease-token hashing at `:212` | Stored lease hashes in the moved database were computed with this domain; changing it makes every previously issued lease token unverifiable | **Preserve.** It already carries an explicit `v1` version marker — exactly the mechanism a future change should use, with a migration, outside this rename |
| Internal table `deck_compat_migrations` | `backend/app/database.py:394`, `:784`, `:801`, `:1125` | Holds the applied compat-migration record inside every existing database (section 4.4) | **Preserve the table name** |
| Capability-token hash | `backend/app/services/agent_mail_service.py:358–364` | No name-derived seed exists (plain SHA-256 of the token), so nothing needs preserving or changing | **No action** — listed so the absence of a seed is verified fact, not an oversight |

A "rename the seed and migrate" alternative was considered for the first two rows and rejected for this release: it adds stored-data rewriting to a release whose decided data behaviour is a pure file move, for strings no person ever sees. If the Director wants even these gone, that is a separate versioned re-key project (new `v2` domain + one-time rehash where the plaintext is even available — for lease tokens it generally is not), and it should be decided as such.

## 5. The first start of v4.0.0, end to end

**Prerequisite (operational, not a code path):** the standard upgrade stops the old version first. No v3.1 process, dispatch scheduler or agent session may be mid-flight while the data files are renamed. Sessions are long-lived children carrying group-A environment variables, the old headers and a running old shim process (`backend/mcp_shim/agent_mail_server.py:13–14`, `:125`, `:247–248`); after the upgrade only new sessions — launched by the new backend with new variables, new headers and the new shim — are supported. Work belonging to sessions that were running is preserved in the moved database and in their git workspaces (their *credentials* even stay valid, section 4.5), but the sessions themselves must be relaunched by the new version; the upgrade never translates a live old session. #791 states "stop the old version, let running teams finish or be stopped, then start the new version" as the upgrade instruction; that is part of performing a normal major upgrade, not an extra migration step.

The first start then performs, in this order:

1. **Data move (before settings/engine first touch).** Apply section 4.6 to the default database set and the home data folder: resume or start the journalled move, apply the conflict matrix, abort before opening any database on the both-populated cell or an unrecoverable failure. Custom paths and test instances rule themselves out here.
2. **Normal database open.** Create settings/engine against the new default (or the operator's custom URL) and run the existing `create_all` + compat-migration sequence (`backend/app/database.py:1156–1165`) from the lifespan (`backend/app/main.py:25`). Against the moved file this is the same no-op-plus-compat behaviour as any v3.1 restart; only a genuinely fresh install creates tables.
3. **Deck-owned agent-configuration rewrite.** Run section 4.2 once: per provider, back up (into the new backups folder), remove the old MCP registration and hooks/plugin files the product installed, apply the new registration carrying values across, and record per-provider outcome in install status. A provider that needs attention does not block startup, dispatch, or the already-completed data move.
4. **Ordinary startup continues.** Attachment cleanup, scheduler start and relay cleanup follow their existing order (`backend/app/main.py:26–43`) — now reading attachment records from the moved folder under its new default. New sessions launched from here carry only new identifiers.
5. **First frontend load.** The served v4.0.0 frontend performs the one-time browser-storage copy-then-delete (section 4.7) and uses only new headers thereafter.
6. **Operator-visible record.** Startup logging (and the install-status surface for step 3) states plainly: what was moved (old path → new path), what was rewritten per provider, anything left needing attention, and — for group-C environment variables (section 4.1) — the value-free warning if old-prefixed names were present in the process environment. No tokens, lease values or other credentials are logged.

Every later start repeats steps 1–3 as cheap no-ops via the conflict matrix and the detectors (old paths absent, old registrations absent). There is no "migration mode" flag to clear and no second phase to run.

## 6. What deliberately breaks at v4.0.0 (input to #791)

This design implements the decided clean break. The release notes and migration guide (#791) must name at least:

1. `CLAUDE_DECK_*` variables set by hand (instance name/id/accent, external-actor token) are ignored until renamed (section 4.1, group C).
2. Agent configuration that names the old MCP server but was **not** installed by the product's installer stops resolving; installer-written configuration is rewritten automatically (section 4.2).
3. Prompts, charters, skills and scripts that call `deck_*` tools must use the new tool names; no aliases exist (section 4.3). External scripts matching `deck_unreachable` / `deck_http_error` error codes must match the new codes (section 4.4).
4. Scripts calling the HTTP API with `X-Deck-Operator-Token`, `X-Deck-Session-Token` or `X-Claude-Deck-Terminal-Token` must send the new header names; token values are unchanged (section 4.5).
5. Custom `DATABASE_URL` installations keep their chosen path — and operators who scripted against the **default filenames** (`claude_registry.db`, `~/.claude-registry`) must update those scripts to the new paths (section 4.6).
6. Release-download scripts must use the new artifact names (section 4.7). Existing GitHub label names keep working for existing scopes; only new scopes default to new labels (section 4.7).
7. Rolling back to v3.1 after the first v4.0.0 start requires renaming the moved data back by hand (section 4.6.5).

## 7. Test list: proving a v3.1 install upgrades with no manual step

These are **requirements for the implementation team's tests**, not results. Nothing here has been run; the design is accepted only when tests at least this strong pass against the implementation. "Standard upgrade" in every test means: stop the v3.1 fixture, replace the code with v4.0.0, start it once by its normal entry point — and nothing else. Any test that needs a repair command, a manual file rename or a configuration edit between stop and start is a failing test of this design.

**Fixture (shared):** build a realistic v3.1 installation with the *old* code: default database file populated through the API with teams/presets/slots, settings, Agent Mail members and message history, dispatch scopes with default labels, backups and a bridge attachment in the home folder, Deck-owned MCP registrations for each supported provider in a throwaway home directory, and browser storage seeded with both old keys. Record row counts per table and a checksum manifest of the backup/attachment files before upgrading.

### Data move (section 4.6)

- **T-D1 Normal upgrade retains everything.** Standard upgrade of the fixture. Assert: only the new database path and new home folder exist afterwards; the old paths are absent; every recorded table row count is unchanged and spot-checked rows (a team, a setting, the mail history, a scope's stored label) read back identical through the API; the backups and attachment checksums are unchanged; no manual step occurred.
- **T-D2 Files are moved, not recreated.** Assert the new database file is the same inode as the old file on a same-filesystem setup (or byte-identical where the harness cannot assert inodes), including a pre-existing non-empty `-wal` sidecar whose contents remain readable after the move.
- **T-D3 No empty-database race.** Start the new version against the fixture with every supported entry point and assert no zero-byte or freshly-initialised database is ever created at the new path before the move; the first health response already serves fixture data.
- **T-D4 Conflict matrix.** Each cell of section 4.6.3: fresh install creates only new files; already-upgraded is a no-op; zero-byte-new is consumed by the journalled move; both-populated aborts startup before opening either database, leaves both files byte-identical, and reports both paths.
- **T-D5 Crash and resume.** Interrupt the move at each journal stage (before renames, mid-sidecars, after main-file commit, during folder merge) and restart: the upgrade completes exactly once, no file is lost or duplicated, and a third start is a clean no-op.
- **T-D6 Custom paths untouched.** Repeat the standard upgrade with a custom SQLite `DATABASE_URL`, with `:memory:`, and with a custom bridge-attachment directory: no file is renamed, the application uses the custom locations, and the default locations are neither created nor required.
- **T-D7 Folder merge collisions.** Both home folders pre-exist with an overlapping backup filename and distinct other files: distinct files merge, the collision keeps the new file, the old colliding file remains with a logged notice, and startup completes.

### Installer and environment (sections 4.1–4.2)

- **T-I1 Deck-owned rewrite, per provider.** For each provider in the section 4.2 table, standard upgrade leaves: no registration under the old server name, a working registration under the new name (an MCP `tools/list` through that provider's configuration succeeds and lists only new-prefix tools), group-B environment keys renamed with a customised value (non-default URL) carried across, and a pre-mutation backup created **in the new backups folder**.
- **T-I2 Generated files replaced safely.** The OpenCode plugin: old-marked file is replaced by the new filename/marker/export; a plugin file whose marker was hand-removed (no longer Deck-owned) is left untouched and reported as needing attention. The Copilot hooks file follows the new server-name filename.
- **T-I3 Damaged configuration does not block the upgrade.** Corrupt one provider's config so it no longer matches the recognised shape: startup and the data move still succeed, that provider reports "needs attention", the others rewrite normally.
- **T-I4 Hand-written configuration untouched.** A by-hand MCP entry naming the old server, never created by the installer, is byte-identical after the upgrade (documented breakage, not silent editing of user files).
- **T-E1 New-prefix only.** New code started with only old group-C variables set behaves as if they are absent (default identity; the value-free warning is emitted if implemented) and never falls back to reading them; with new variables set, identity/provider/URL take effect everywhere the old ones did, including session launches and the Pi extension opt-in.

### Tools, headers, storage, labels (sections 4.3–4.5, 4.7)

- **T-T1 Tool surface.** The shim's registered tool list is exactly the 36 new names of section 4.3 — no `deck_`-prefixed tool and no alias is callable; a call to an old tool name fails as unknown. The generated Pi manifest, regenerated from the shim, lists the same 36.
- **T-H1 Headers.** The backend accepts the new operator/session/terminal headers and refuses the old ones; the frontend and shim send only the new ones; a session capability token issued by the v3.1 fixture still authenticates after the upgrade (hash continuity, section 4.5) once presented under the new header by the new shim.
- **T-S1 Browser storage.** First load with only old keys present copies both values to the new keys and deletes the old ones (stored operator token keeps working without re-entry; selected provider is kept); a second load performs no copy; pre-existing new keys are never overwritten by stale old ones.
- **T-L1 Labels.** After the standard upgrade, existing scopes still dispatch against issues carrying their stored (old) label; a scope created after the upgrade defaults to the new label names.

### Opaque constants and global guards (section 4.8)

- **T-O1 Golden values.** For a fixed hostname and a fixed lease token, the v4.0.0 build derives the *same* instance ID and the *same* lease hash as the v3.1 fixture code; a lease issued pre-upgrade still validates post-upgrade, and the moved database's `deck_compat_migrations` rows are still honoured (no compat migration re-runs destructively).
- **T-G1 No-old-name guard.** On the implementation branch, the inventory's primary search over executable/configuration paths returns only: history and dated records, the frozen constants of section 4.8 (each carrying its rationale comment), negative test fixtures, and this campaign's planning documents. Any other hit fails the check. This guard is what stops "just one small fallback" from creeping back in.
- **T-G2 Second-start and downgrade honesty.** A second v4.0.0 start changes nothing (file listing and config bytes stable); the documented manual rename-back procedure from #791, followed literally, makes the fixture start under v3.1 again with its data intact.

## Appendix A: reproducing the evidence

```bash
PIN=585af8b7c0339e9e87c41d802127da2d5176b697
# environment names with production readers/writers, and the test-only one
git grep -I -h -o -E 'CLAUDE_DECK_[A-Z0-9_]+' $PIN -- backend/app backend/mcp_shim integrations scripts frontend/src | sort -u
git grep -I -n -E 'CLAUDE_DECK_MAIL_TOKEN' $PIN -- .
# tool definitions (the 36) and other deck_ tokens
git grep -I -n -E '^def deck_' $PIN -- backend/mcp_shim/agent_mail_server.py
git grep -I -n    -E 'deck_[a-z0-9_]+' $PIN -- .
# database first-touch ordering and paths
git grep -I -n -E 'database_url|create_async_engine|create_all|init_db' $PIN -- backend/app/config.py backend/app/database.py backend/app/main.py
git grep -I -n -E '\.claude-registry' $PIN -- backend scripts .gitignore
# trailers: emitted, not read in production at this pin
git grep -I -n -E 'Deck-Agent-Slot|Deck-Work-Item' $PIN -- backend frontend/src scripts
```

Checkout-wide counts of every old-name occurrence, including classes outside this design, remain the merged inventory's job (`inventory.md` sections 3–5, measured at its own pin); this document cites lines, not new totals, so the two pins are never mixed into one number.

## Appendix B: decisions still open for the Director

1. **Spelling scheme** (section 3): recommended split (S for paired-component identifiers, Q for shared namespaces), or S everywhere, or Q everywhere. Settles the environment prefix, tool prefix, default database filename and headers in one choice.
2. **Exact home folder and label names** if the recommended qualified spellings (`~/.albiex-synth-city`, `albiex-synth-city-ready` / `-design`) are not wanted.
3. **The value-free startup warning** for old-prefixed group-C environment variables (section 4.1): keep as a discoverability aid, or omit so that no code path even looks at old names.
4. Nothing else in this document needs a Director decision to implement: conflict behaviour, the no-rewrite rule for stored labels and free text, opaque-constant preservation, and the factory-units-as-operations boundary are designed within the decisions already made — but any of them can be reopened explicitly.






