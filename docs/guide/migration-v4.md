# Moving to Albiex Synth City v4.0.0

**Albiex Synth City** is the new name of Claude Deck. Version 4.0.0 is the rename release. For most installations the whole move is: **stop the old version, start the new one.** Your teams, settings, Agent Mail history, backups and attachments come with you automatically — there is no migration command to run and nothing to rename by hand for a standard installation. Read “If you customised…” below only if you changed defaults or wrote your own integrations.

### Before you upgrade

1. Let running teams finish, or stop them. Running agent sessions do not carry over live — their work and history are kept, and you relaunch the teams afterwards.
2. **Stop Claude Deck v3.1 completely** — the product itself, not just its teams. Do not update the checkout or dependencies while it is running: the development launcher auto-reloads on file changes, so new code could start against un-migrated data mid-upgrade. (Downloading v4.0.0 into a *separate* staging location beforehand is fine; changing the live checkout or its dependencies is not.)
3. **While it is stopped**, keep a complete pre-upgrade backup: the database file set copied as one quiescent set (main file plus `-wal`/`-shm` sidecars together, or the SQLite backup command, as the installation guide describes), the whole `~/.claude-registry` data folder, your agent (provider) configuration, **and your browser state for this app** — the actual stored values for the app's address, in both `localStorage` (for example your selected provider and settings) and `sessionStorage` (the operator token lives there and dies with the tab, so capture it from the still-open tab before closing it, or accept re-entering it). Version 4.0.0 cannot be “renamed back”: the only way back is restoring that complete set (see “Going back”). Copying just the database and data folder is not a complete backup.
4. Get v4.0.0 the normal way — now update your checkout/source to the `v4.0.0` tag and install dependencies as the installation guide describes (the downloadable frontend archives alone cannot upgrade the backend) — then start Albiex Synth City v4.0.0 normally. Do not run both versions against the same data. “Stop old, start new” below is shorthand for this stop → back up → update → start order; there is still no separate migration command. (That this backup/restore procedure works end-to-end is itself part of what the pre-release upgrade tests must prove; until v4.0.0 ships, treat it as the documented contract, not as already-demonstrated behaviour.)

### What happens on first start

- Your database moves from `claude_registry.db` to **`synth_city.db`** (same folder), including its SQLite sidecar files. It is the same database — every team, setting and message is still there.
- Your data folder moves from `~/.claude-registry` to **`~/.albiex-synth-city`**, including `backups/` and `bridge-attachments/`. Existing backups stay downloadable and restorable; existing attachments keep working.
- If you used Mail setup to connect your coding agents, connections the app can positively recognise as its own are re-registered under the new server name **`albiex-synth-city-mail`** automatically (with a safety backup taken first). An entry the app cannot positively recognise is left untouched and reported as needing attention rather than guessed at. If a connection step cannot finish (for example an agent's command-line tool is missing or a file cannot be written), it is reported as an incomplete step and retried on later starts — it is never silently reported as done, and ordinary temporary failures finish on a later start without a repair command. Agent Mail tools are renamed from `deck_…` to **`synth_city_…`** (for example `synth_city_check_inbox`); newly launched agents see the new names.
- The app runs under a major version **4.0.0**. The browser keeps your saved settings, such as your selected provider. The operator token is kept only in a browser tab that stays open across the upgrade, because it lives in that tab's session storage; if you closed the tab, enter the operator token again — it is unchanged on the server.

If a first start is interrupted (power loss, killed process), simply start again: an interrupted move that the app can verify — including one where both old and new copies temporarily exist — resumes and finishes automatically. Only a conflict the app cannot explain (for example, old and new databases with data and no valid record of an interrupted move) stops startup safely, tells you both paths, and deletes nothing; that unexplained state does not result from a normal upgrade, so ask for help rather than deleting either file.

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
- **You set a custom database location or attachment folder:** a genuinely custom location stays where it is; only the shipped default locations move, each independently. If you explicitly configured a value that is exactly the shipped default, it is treated as the default and migrates automatically — you do not need to edit your launch files. If custom locations are nested inside, or overlap, a folder that would move (for example a custom database inside the old data folder), startup may stop safely instead of moving the whole folder, and will say so rather than guess. Scripts that referenced the *default* filenames above need the new names.
- **You added the Mail MCP server to an agent by hand** (not via Mail setup), or heavily edited what setup installed: that entry stops working and is reported as needing attention. Re-add it under `albiex-synth-city-mail`, or run Mail setup for that agent.
- **Your prompts, charters, skills or scripts name `deck_*` tools, the error codes `deck_unreachable`/`deck_http_error`, or the headers `X-Deck-Operator-Token` / `X-Deck-Session-Token` / `X-Claude-Deck-Terminal-Token`:** update them to `synth_city_*`, `synth_city_unreachable` / `synth_city_http_error`, and `X-Synth-City-…`. Your operator token is unchanged on the server (re-enter it if your browser tab was closed), but session credentials are not: stopped sessions must be relaunched and receive fresh session keys and capabilities through normal registration, with the usual session lifecycle checks unchanged; old session credentials are not revived.
- **You download releases by script:** use the new `albiex-synth-city-frontend-v4.0.0` file names.

### Going back

There is no supported downgrade by renaming files back: after first start, data files, stored file references, agent connections and browser state have all moved. To return to v3.1 you must restore the complete pre-upgrade set — database file set, data folder, agent (provider) configuration, and browser state, kept with the operator settings the restored environment needs — and accept losing anything created after the upgrade. Restoring only some of those pieces (for example, files but not browser state) is not a supported downgrade and can leave you with a mixture of old and new state. If that trade-off is not acceptable, do not upgrade until you are ready to stay.
