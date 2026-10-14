# Muse Code harness support

Date: 2026-10-14. Status: design for review.

## Goal

Deck can run Meta's Muse Code CLI (`muse`) as a team member, on a Muse subscription, with the same supervision as the other harnesses. The first user is the researcher slot of the website planning team, with the model `muse-wonder-1.0`.

A Muse subscription works only inside Muse Code. Meta's terms say: "This credential is for use with Muse Code only." Running the Muse models in another harness needs a separate pay-as-you-go API key. So Deck must launch Muse Code itself.

## Evidence

A throwaway spike on 2026-10-14 used Muse Code 1.4.7 and `muse-wonder-1.0` on this machine. It established the following.

| Need | Muse Code behaviour |
|---|---|
| Interactive launch | `muse --yolo --trust-workspace --model <id> "<prompt>"` starts the TUI with a first prompt. `--yolo` disables approvals and the sandbox. `--trust-workspace` trusts the workspace for this run, so its skills, rules, hooks and `.mcp.json` load without a prompt. |
| Resume | `muse resume <session-uuid>`. Root options can go on either side of `resume`. |
| Session id | Session ids are time-ordered UUIDs (UUIDv7). The TUI cannot set the id; `muse exec --session-id` can. The `SessionStart` hook payload contains `session_id`. |
| Transcript | `~/.local/share/muse/sessions/YYYY/MM/DD/<uuid>/session.jsonl`, a structured event log. Each record has `record_type`, `payload_type` and `payload`. |
| Agent activity | `runtime.session` records carry `payload.event.kind`: `assistant_tool_calls_committed`, `tool_result_batch_committed`, `model_completed` (with `finish_reason` and `model`), `output`, `reasoning_committed` and `user_input_prompt_requested` (with `tool_name` and `questions`). |
| MCP | The workspace `.mcp.json` (`mcpServers`, stdio servers) loads in a trusted workspace. `-c mcpServers.<name>=<json>` adds one server for one run. The settings key is `mcpServers`; `-c` must name one server, not the whole map. |
| Hooks | The workspace `.muse/hooks.json` uses Claude Code's layout: `{"hooks": {"<Event>": [{"matcher": "...", "hooks": [{"type": "command", "command": "...", "timeout": 10}]}]}}`. `SessionStart` and `UserPromptSubmit` fire with Claude-compatible JSON on stdin: `session_id`, `cwd`, `hook_event_name`, `model`, `model_provider`, `permission_mode`, `source` and `transcript_path`. |
| Question tool | The tool is `request_user_input`. **`PreToolUse` does not fire for it** (it fires for `read_file`). A hook cannot block a question. |
| Question screen | The form ends with `Enter to select · ↑/↓ to move · Tab for an optional note · Esc to interrupt`. Deck's existing `Enter to select` pattern matches it. |
| Prompt delivery | The first `send-keys ... Enter` during startup can leave the prompt typed but not submitted. A second carriage return submits it. |
| Updates | The `muse` command is a launcher script that updates the runtime hourly (`MUSE_UPDATE_INTERVAL_SECONDS`, `MUSE_CHANNEL`). |

## Design

### 1. Provider `muse-cli`

A new `MuseCliProvider` in `backend/app/services/providers/muse_cli.py`, modelled on `pi_cli.py` and `codex_cli.py`. It is registered as `"muse-cli"` and displayed as "Muse Code", with binary `muse`.

- **Plain launch:** `muse --trust-workspace --model <model> [--reasoning-effort <tier>] [--yolo] [<prompt>]`. `skip_permissions` maps to `--yolo`. Team slots always use `--trust-workspace`, because Deck pre-trusts team workspaces for every harness.
- **Resume launch:** `muse --trust-workspace --model <model> [--yolo] resume <session_id>`. The id must be a UUID; otherwise the launch is refused with a block code.
- **Options:** `model`, `reasoning_effort` (Muse's tiers: none, minimal, low, medium, high, xhigh, max and ultra), `skip_permissions`, `prompt`, `session_id` and `mode`. Other `SpawnCommandOptions` fields are reported as unsupported, as `pi_cli.py` does. That includes the Bedrock fields: Muse runs only on Meta.
- **Process match:** argv0 `muse` (the launcher script) or `muse-bin-<version>` (the binary that the launcher `exec`s, for example `muse-bin-1.4.8-R6256.1`).
- **Capability matrix:** an entry for `muse-cli`. Mark capabilities `supported` only when this design implements them; everything else is `unsupported` or `unknown`.

### 2. Session identity

The TUI cannot be given a session id, so Deck discovers it, as it does for Codex.

- **Primary source:** the `SessionStart` hook that the Agent Mail install adds (section 4). It sends `session_id` and `cwd` to Deck's existing hook route. That route already records Claude Code sessions, and its provider allowlist and session-key prefix gain `muse-cli`.
- **Process-bound discovery:** the `muse-bin-<version>` process holds its session's `.session.lock` open, at `~/.local/share/muse/sessions/YYYY/MM/DD/<uuid>/.session.lock`. Deck reads `/proc/<pid>/fd`, takes the session folder's name as the id, and accepts it only if that folder's `session.jsonl` has `session.opened.observed` with the same `session_id` and `runtime.session.metadata` with `workspace_root` equal to the pane's cwd. That is as strict as the Codex rollout discovery.

After the first launch, the slot stores the id in `launch_options.session_id` and relaunches in resume mode. This avoids the session-mismatch failure from v3.1.

### 3. Native observation

A new `muse_activity_service.py`, modelled on `pi_activity_service.py`. It reads the bound session's `session.jsonl` incrementally, with a bounded read size, and derives the same states as the other harnesses.

- **working:** a `runtime.session` event of kind `started` that carries a `prompt` (a turn start), with no later `terminal`.
- **idle:** the turn's `terminal` event with `terminal: "completed"`. Any other `terminal` value is `unknown`.
- **waiting for input:** a `user_input_prompt_requested` whose `prompt_id` has no later `user_input_prompt_settled`. This is the exact signal, and it feeds the existing waiting-input notice for the bound Supervisor.
- **Binding:** the file must contain `session.opened.observed` with the slot's session id, and `runtime.session.metadata` with `workspace_root` equal to the pane's cwd. Timestamps (`recorded_at`) are epoch microseconds.
- **unknown:** an unreadable, ambiguous or missing transcript. Unknown grants no authority, as for every harness.

`recognize_native_input_wait()` also accepts `muse-cli`, with the spike's question form as a fixture. A `NUL`-padded or partial last line is treated like the guard does: it is not parsed until it is complete.

### 4. Agent Mail install

New install and uninstall functions in `agent_mail_install_service.py`, with `POST /agent-mail/install/muse/apply` and `.../uninstall`. Both routes need the Director key when one is configured, like the other install routes, and `test_settings_write_guard.py` lists them.

The install is **user-wide**, like every other harness's install, in Muse's user settings file `~/.config/muse/settings.json`. The directory comes from `$MUSE_CONFIG_DIR` when it is set. A per-workspace install would write `.mcp.json` and `.muse/hooks.json` into dispatch workspaces, which are git clones. Those files would be untracked changes, and the maintenance and publication checks require a clean tree. The spike confirmed that the settings file accepts a `hooks` block, and that user-level hooks fire even in an untrusted directory.

- **MCP:** set `mcpServers.claude-deck-mail` to a stdio entry that runs Deck's `agent_mail_server.py` shim. Keep all other servers and settings, and refuse to overwrite a malformed file.
- **Hooks:** add `SessionStart` and `UserPromptSubmit` groups in Claude Code's layout. They run `agent_mail_hook.py --provider muse-cli`, as Codex does, and Deck's hook route accepts `muse-cli` with the session-key prefix `muse`.
- **Uninstall:** remove only Deck's entries, recognised by the shim markers. Keep the rest of the file.
- **Status:** `muse_cli_available`, `muse_mcp_installed`, `muse_hooks` and `muse_hooks_missing` in `AgentMailInstallStatus`.

### 5. Unattended safety: questions

A hook cannot block `request_user_input`. Deck uses three layers instead:

1. **Deny the tool by permission profile, if Muse supports it.** The settings area `permissions` exists, with named profiles and a `schema_version`. Implementation first checks with a live session whether a profile can deny `request_user_input`. If it can, team launches select that profile, and the capability is `supported`.
2. **Detect and escalate.** Whether or not layer 1 works, `user_input_prompt_requested` marks the slot as waiting for input, and the bound Supervisor gets the existing notice. A question cannot stall unseen.
3. **Charter rule.** The team charter tells Muse members never to use the question tool, and to write to the Supervisor instead.

If layer 1 is not possible, the capability matrix says so, and the Harnesses page shows that questions are detected, not blocked.

### 6. The guard

`scripts/product-factory/team-supervisor` gains a `muse-cli` branch:

- **`transcript()`:** the session's `session.jsonl` under `~/.local/share/muse/sessions/*/*/*/<uuid>/`. As for Codex, there must be exactly one match on every scan; a missing or ambiguous match fails closed.
- **`notice()`:** checks the agent's own output only: `output` chunks and final results, and assistant text in `reasoning_committed`. Tool results and user prompts never create a hold, as for the other harnesses. Error events are mapped to the existing safety codes.

### 7. Frontend

Add `muse-cli` with the label "Muse Code" to:
- the provider union in `types/providers.ts`;
- the harness names in `filterHelpers.ts`;
- the surface registry, empty at first;
- the team slot provider select;
- the repository setup provider list;
- the launch-options fields: a model field with an example `muse-wonder-1.0`, a reasoning effort field, and no platform field.

### 8. Version visibility

The launcher updates itself; the spike saw 1.4.7 become 1.4.8 within one hour. Each Muse observation records the session's version, from the `muse-bin-<version>` process name and the transcript's `runtime.session.metadata.build`, so a change during a campaign is visible. Pinning is out of scope: Deck does not change the user's launcher.

## Out of scope

- A Muse native-settings editor on the Harnesses page.
- API-key launches (`META_API_KEY`). The design does not block them, but they are not tested.
- Muse subagents, worktrees and session messaging.

## Testing

- **Provider unit tests:** the plain and resume commands, option validation, refusal of a non-UUID resume id, and unsupported options.
- **Activity tests:** recorded `session.jsonl` fixtures from the spike, sanitised, for the working, idle, waiting-for-input and unknown states, plus a partial last line.
- **Agent Mail install tests:** merging into existing `.mcp.json` and `hooks.json` files, refusing malformed files, uninstall keeping other entries, and the Director-key guard on both routes.
- **Guard tests:** Muse transcript discovery (missing and ambiguous both fail closed), a notice in agent output, and no hold for a notice in tool output.
- **Waiting-screen fixture:** the spike's question form.
- **Frontend:** the provider appears in the slot select and the launch-options fields, and the harness list e2e includes Muse Code.
- **Manual check:** one real team slot on Muse Wonder, launched by Deck. It registers in Mail, Deck records its session id, it resumes after a restart, the activity view shows working and idle, and a question shows as waiting for input.

## Delivery

One feature branch, `feat/muse-code-harness`, as one PR into `master` with the four required CI jobs. The Supervisor implements it, by the Director's decision. The website team starts after it merges and is deployed to the local instance.
