# OpenCode v2 harness support

Date: 2026-11-12. Status: spike result and design for review (#729). It feeds #730, #731, #732 and #733.

## Goal

Deck's `opencode-cli` provider was written for OpenCode v1 (tested on 1.17.11). OpenCode v2 is now the current major version. This spike checks v2's behaviour with live team-member sessions in tmux. It answers the seven questions in #729 and turns the answers into a design for the four follow-up issues.

## Summary

Deck's current OpenCode support does not work on v2. Three things break, and none of them reports an error to Deck:

1. **The launch command fails.** The v2 TUI rejects `--model` and `--agent` with `Unrecognized flag` and exits with status 1. Deck's spawn command passes both flags.
2. **The Agent Mail plugin never loads.** v2 uses a new plugin API, and the v1-style plugin that Deck installs fails to load with only a WARN line in OpenCode's log. Deck loses session registration, idle notices and context injection.
3. **The shared background service mixes up members.** Without `--standalone`, every TUI on the host uses one service process. That process runs the MCP shim and the plugins with the environment of whichever TUI started it. A second member's events and Mail registration then report the first member's slot, and the second member's per-launch config is ignored.

Each problem has a working fix in v2: `--standalone`, a per-launch `OPENCODE_CONFIG_CONTENT`, `--session ses_…` ids, a v2 plugin, `codemode: false` for the MCP server, a `question` deny rule and `--auto`. The design below uses these fixes.

## Method and limits

- **Versions.** **v2.2.7** (current, 2026-11-10) got the full spike. **v2.2.0**, the earliest published v2 release, was the comparison version. Both binaries are `opencode-linux-x64.tar.gz` from the official `anomalyco/opencode` GitHub releases, and both matched the release's `SHA256SUMS`. v2 is not on npm: the `opencode-ai` package ends at 1.19.5. **2.0.29**, the version in the issue, has a git tag but no published release or checksums, so it was **not reproduced**. The issue's 2.0.29 notes are kept below as reported.
- **Isolation.** OpenCode ran only in a throwaway runtime: its own `HOME` and `XDG_*` dirs and `TMPDIR`, a private tmux socket, and no credentials. Agent Mail identity variables and credential variables were removed from its environment, and Mail traffic went to a local recorder, never to a live Deck. No factory config, agent user, `/opt` path or port 8011 was touched.
- **Model.** Model turns came from a local scripted OpenAI-compatible stub provider (`stub/m1`, `stub/m2`). It returns fixed text or forced tool calls. Observations marked **[stub]** show harness mechanics: flags, ids, processes, events, hooks, DB rows, tool lists and the tool results the agent receives. **They do not show how a real model behaves**, for example whether a real model tries to ask questions or copes with Code Mode. That is still unproven.
- **Incident.** One 2.2.7 test session silently ran on OpenCode's hosted free model, `opencode/iceman-free`, instead of the stub, and got a 429 free-limit error (see finding F5). It was reported to the Leader and contained with `enabled_providers`. No other session used a hosted model. After the incident, model-turn probes stopped until a loopback-only network namespace was in place (see Isolation limits).

### Version coverage

| Item | v2.2.7 | v2.2.0 |
|---|---|---|
| TUI flags: `--model` / `--agent` refused; `--auto`, `--yolo`, `--dangerously-skip-permissions` accepted | observed | observed |
| `OPENCODE_CONFIG_CONTENT` model and `default_agent` on a new session | observed [stub] | observed [stub] |
| `--session` needs the `ses` prefix; Deck-chosen id created | observed | observed |
| Relaunch resumes the same session; resumed session keeps its model; plugin `switchModel` | observed [stub] | observed [stub] |
| `--standalone` process tree; plugin and shim in `serve --stdio`; registration pid and slot | observed [stub] | observed [stub] |
| Shared service mixes up members | observed [stub] | **gap** (not run, by decision) |
| v1 plugin refused; v2 plugin loads; `session.created`, `session.execution.started`, `session.context` injection, `permission.evaluate` | observed [stub] | observed [stub] |
| `tool.execute.after`, `session.execution.succeeded` | observed [stub] | observed [stub] |
| `experimental.idle` hook | fired [stub] | **registered without error, never fired** |
| `session.execution.failed` | observed (real hosted model, F5) | **gap** |
| Question form and `form.created` | observed [stub] | observed [stub] |
| Question deny by config rule | observed [stub] | observed [stub] |
| Question deny by plugin `permission.evaluate` | observed [stub] | **gap** |
| `--auto` with an `ask` rule; deny under `--auto` | observed [stub] | observed [stub] |
| MCP Code Mode by default; `codemode:false` gives direct tools | observed [stub] | observed [stub] |
| `session_v2` activity columns, crash staleness | observed [stub] | columns present; staleness **gap** |

### Isolation limits

- Runtime: its own `HOME`, `XDG_*` and `TMPDIR`, a private tmux server, and a scratch Python venv for Deck's MCP shim. Agent Mail identity and credential variables were removed from the environment. Mail calls went to a local recorder that answers like Deck, so the shim's later tool replies are fake (the error text in F2 is a recorder artifact).
- Network: until the incident (F5), the only network limit was the stub provider config, and that **did not stop a fallback to a hosted model**. From then on, both configs allowed only `stub` (`enabled_providers`). The four 2.2.0 probes after the incident ran in an unprivileged user and network namespace (`unshare -rn`, then mapped back to the real uid). Its only interface is `lo`, and it has no IPv4 or IPv6 routes. Each OpenCode process tree was checked to be in that namespace before its turn, and the Leader verified the namespace independently. Earlier runs, on both versions, had normal host networking: OpenCode refreshed its models.dev catalog, and one turn reached the hosted model.
- Inside the namespace, OpenCode cannot refresh its models.dev catalog and uses the cached copy. No effect on the probes was seen.
- Not tested: real-model behaviour, OpenCode's GUI and web clients, Windows and macOS, and more than one standalone member running at the same time (other than the cold-start race in F6).

## Answers

### 1. Model and agent

| | v2.2.7 | v2.2.0 |
|---|---|---|
| `opencode <dir> --model x` / `--agent x` | Rejected: `ERROR Unrecognized flag: --model in command opencode`, exit 1. The same for `--agent`. | The same. |
| Other unknown flags | Rejected, exit 1. | Not tested. |
| `opencode run` / `opencode mini` | `opencode run --help` still lists `--model provider/model#variant` and `--agent`. `mini` was not checked; the issue reports the same for 2.0.29. These are not TUI members. | Not checked. |

**How Deck selects them:** set the environment variable `OPENCODE_CONFIG_CONTENT` on the launch. It is merged on top of the user config. **[stub]** `{"model":"stub/m2","default_agent":"plan"}` started a new session with the Plan agent on `stub/m2`, on both versions. A custom primary agent works too: `{"agents":{"deckmember":{"mode":"primary","model":"stub/m2","system":"…"}},"default_agent":"deckmember"}` gave a new session that agent's model and system prompt.

**A resumed session keeps its model.** The model is stored per session (`session_v2.model`). On relaunch with `--session <id>`, the config default `model` did not change it (both versions [stub]), and neither did `agents.build.model` (2.2.7 [stub]). The plugin API can change it: calling `ctx.session.switchModel({sessionID, model:{providerID, id}})` from the plugin's `prompt` hook moved a resumed session from `m1` to `m2`. The same turn already used `m2`, and the row was updated (both versions [stub]). `switchAgent` exists too, but this spike did not test it.

### 2. Identity

- **Deck can choose the id.** `--session <id>` on the first launch creates a session with exactly that id (both versions). The only check observed is the prefix: the id must start with `ses`. `ses_abc`, `ses_deck-slot-29_issue-729` and `ses_deckslot29spike0000000001` were accepted. A UUID or `deck-slot-29` was refused with `Error: Expected a string starting with "ses" at ["sessionID"]`, exit 1. Native ids look like `ses_` followed by 26 base62 characters (for example `ses_e2e111c0dffe5XAqhRWBFFBZDf`). Deck should generate ids in that shape.
- **Relaunch resumes the exact session.** Relaunching with the same `--session` continued the same `session_v2` row, kept its history and created no new session (both versions [stub]). The first 2.2.0 attempt was invalid because its first launch failed in the cold-start race (F6). A later run inside the namespace confirmed resume over three launches of one session.
- `--continue` resumes the most recent session in the directory. Deck should not use it for members.

### 3. Process model

**With `--standalone` (both versions):**

```
tmux pane: opencode --standalone --session ses_…      pane_current_command = "opencode"
  └─ opencode serve --stdio --port 0                  private server, child of the pane process
       └─ <python> agent_mail_server.py               MCP shim
```

- The MCP shim and the plugins run in the private `serve --stdio` process. The probe plugin's `process.pid` matched that process.
- The Agent Mail shim registers `pid = os.getppid()`, which is the private server's pid: a direct child of the pane's process, not the pane's process itself. The slot environment (`SYNTH_CITY_TEAM_SLOT_ID`) reaches both the shim and the plugin.
- The private server also listens on a random `127.0.0.1` port and requires authentication (`/api/event` returns 401). Its password is in the server's environment (`OPENCODE_PASSWORD`) and is not published anywhere. Deck should not use this endpoint (see 6).
- When the TUI is killed, the private server shuts down a few seconds later (`location.shutdown`, 2.2.7).

**Without `--standalone` (2.2.7):**

- The first TUI starts `opencode serve --service` as its own child, using its own environment, and writes `~/.local/state/opencode/service.json` with the URL, pid and a password. Later TUIs connect to that service and start no server of their own. Non-TUI commands such as `opencode models` also start the service, detached.
- **The members get mixed up [stub].** Member B1 (slot 9002) started the service, and then member B2 (slot 9003) connected to it. All of B2's session events and hooks came from the service with `slot 9002`. The shim registered once, as slot 9002, with the service pid. B2's `OPENCODE_CONFIG_CONTENT` model was ignored, and its turns ran on the service's model.
- The service outlives the TUI that started it: it is reparented to pid 1 and keeps serving other TUIs with the first member's environment.

**Decision:** team members **must** run with `--standalone`. Without it, Deck cannot tie the shim, the plugin, the slot identity or the per-launch config to a member.

### 4. Plugin events and hooks

The v1 plugin API is gone. Deck's installed plugin (`plugins/albiex-synth-city-agent-mail.js`, a named async export that returns a hooks object) fails on both versions with:

> `failed to load plugin … Plugin must export a default definition with an id and an effect or setup function. (cause: SchemaError(Missing key at ["default"]))`

That error appears only as a `WARN` in OpenCode's log. Files in `~/.config/opencode/plugins/` still load automatically.

A v2 plugin is a default export `{ id, setup(ctx) }`. Its types come from **`@opencode/plugin`** (2.2.7 on npm). The v1 package `@opencode-ai/plugin` ends at 1.19.5. A plain JavaScript plugin with no imports loads without any package installed (both versions). Mapping of the hooks the Deck plugin uses (2.2.7 [stub]; the 2.2.0 coverage is in the table under "Version coverage"):

| v1 hook or event (Deck today) | v2 equivalent | Observed payload |
|---|---|---|
| `event` `session.created` | `ctx.event.subscribe()` → `session.created` | `{id, created, type, durable:{aggregateID:<session id>, seq, version}, location:{directory}, data:{sessionID, projectID, location, subpath, slug, …}}` |
| `event` `session.idle` | No event with that name. Use `session.execution.succeeded` / `.failed`. The `ctx.session.hook("experimental.idle")` hook fired on 2.2.7 but not on 2.2.0. | Execution events: `data:{sessionID}`; failures add `data.error:{type, message, status}`. Idle hook: `{sessionID, background:[]}` |
| `event` `session.deleted` | Not observed. Deleting a session from a separate CLI process produced no event in the member's private server. | — |
| `tool.execute.after` | `ctx.tool.hook("execute.after")` (also `execute.before`) | `{tool, sessionID, agent, messageID, id, input, status:"completed", result:{output, content}}` or `status:"error"` with `error` |
| `experimental.chat.system.transform` | `ctx.session.hook("context")` | `{sessionID, agent, model, system:[{type:"text", text, metadata?}], messages, tools, options}`. Pushing `{type:"text", text}` onto `system` reached the model request. |

Other events seen in a turn: `session.execution.started`, `session.inbox.enqueued` / `.delivered`, `session.step.started` / `.streamed` / `.ended` / `.failed`, `session.text.*`, `session.tool.input.started` / `.ended`, `session.tool.called` / `.success` / `.failed`, `session.usage.updated`, `session.renamed`, `session.viewed`, `form.created` / `.replied` / `.cancelled`, `permission.asked` / `.replied`, `mcp.status.changed` and `location.shutdown`. The `ctx.session.hook("prompt")` hook gets `{sessionID, messageID, prompt:{text, files, agents}, delivery:"steer"}`.

Event order in a turn varies, because handlers run asynchronously. Use `created` and `durable.seq`, not arrival order.

### 5. Questions

- **The tool:** `question` is in the default tool list. A call opens a TUI form (`Questions … ↑↓ select  enter submit  esc dismiss`) and blocks the turn (both versions [stub]).
- **Open-question signal:** a `form.created` event with `data.form.metadata.kind:"question"`, a `tool` reference and the `fields`. The form ends with `form.replied` (`answer`) or `form.cancelled`. The 2.0.29 `question.v2.asked` event did not appear in 2.2.x. Durable state: the `session_part` row for the `question` tool has `state.status:"running"`, `session_v2.time_busy` is set, and `time_idle` is null.
- **What the agent sees after an answer:** `User has answered your questions: "Pick one?"="A". You can now continue with the user's answers in mind.`
- **Denying the tool by config works.** Both the deprecated v1 form `"permission":{"question":"deny"}` and the v2 rule `"permissions":[{"action":"question","resource":"*","effect":"deny"}]` remove `question` from the tools sent to the model (12 tools become 11). When the stub forced the call anyway, the agent got `{"error":{"type":"tool.execution","message":"No tool named \"question\" is currently available. …"}}` (v2 rule: both versions [stub]; v1 form: 2.2.7 [stub]). A real model should not see the tool at all, but that is not proven with a real model.
- **Denying from the plugin hook works too, but the tool stays visible.** `ctx.permission.hook("evaluate")` gets `{sessionID, agent, action:"question", resources:["*"], source, effect}`. Setting `effect = "deny"` and `message = …` rejects the call. The agent gets `{"error":{"type":"permission.rejected","message":<our message>}}`, and the event is `session.tool.failed`. The tool is still offered to the model.
- `--auto` does **not** stop questions: the form still opens.

### 6. Activity

Observed on 2.2.7 [stub]. On 2.2.0, the execution events and `form.created` were also seen.

| Source | Working | Idle | Waiting for input | Verdict |
|---|---|---|---|---|
| Plugin events (in the member's own `--standalone` server) | `session.execution.started` | `session.execution.succeeded` (or `.failed` with `error.type`) | `form.created` (question), `permission.asked` (approval); cleared by `form.replied` / `form.cancelled` / `permission.replied` | **Primary.** Exact, immediate, and tied to the slot because the plugin runs with the member's environment. |
| `session_v2` row | `time_busy > time_idle` (or `time_idle` null) | `time_idle ≥ time_busy`, `idle_outcome` `succeeded` / `failed` | Not visible: looks like working | **Secondary**, for recovery after a Deck restart. It is stale after a crash: a TUI killed mid-turn left `time_busy > time_idle` and `time_suspended` set, and a relaunch without a prompt did not clear it in 40 s. Use it only with process liveness. A running `question` part in `session_part` marks waiting. |
| Service `/event` stream | — | — | — | **Not usable.** Members use `--standalone`, whose server is private and password-protected, and the shared service mixes up members (3). |

`session_message` also stores an `idle` row with `outcome` after each turn. The `event` table stayed empty in every run.

### 7. Skip permissions

- `--auto` ("Auto-approve permissions that are not explicitly denied") does what Deck needs. With a `shell` `ask` rule, `permission.asked` was followed by an automatic `permission.replied` `"once"`, and the command ran (both versions [stub]). Without `--auto`, the TUI stopped on `Permission required … Allow once / Always allow / Reject` (2.2.7 [stub]).
- **Deny rules still apply under `--auto`.** An `external_directory` deny gave `permission.rejected` (both versions [stub]), and the `question` deny held (2.2.7 [stub]).
- The hidden flags `--yolo` and `--dangerously-skip-permissions` are accepted by both versions and show the same "Build auto" mode as `--auto`. On 2.2.7, deny rules still applied under both flags [stub]. They are not in `--help`, so Deck should use only `--auto`.
- 2.2.7's default rules allowed everything tried without asking, including reading `/etc/hostname` through `external_directory`. Only the `question` tool interrupted a default session.

## Other findings

- **F1. Config keys renamed.** The v2 schema (`https://opencode.ai/config.json`) deprecates `agent`, `permission`, `plugin`, `provider` and the flat `mcp.<name>` map. Their replacements are `agents`, `permissions` (an ordered rule list `{action, resource, effect}`), `plugins`, `providers` and `mcp.servers.<name>`. The deprecated forms still work in 2.2.x. New Deck writes should use the v2 forms.
- **F2. MCP tools are in "Code Mode" by default.** The Agent Mail tools are not direct tool calls. The system prompt says they "only work as JavaScript inside the `execute` tool" and lists only 11 of the 36 tools (`albiex-synth-city-mail (36 tools, 11 shown)`). The model must use `search(...)` to find the rest. Setting `"codemode": false` on the server entry (`mcp.servers.<name>` or the flat form) makes them direct tools named `albiex-synth-city-mail_<tool>`, all 36 of them. `execute` is still offered for other code. **[stub]** A direct `albiex-synth-city-mail_synth_city_check_inbox` call reached the shim, which registered with the member's slot (both versions).
- **F3. The DB schema changed.** The 2.2.x tables are `session_v2`, `session_message`, `session_part`, `session_inbox` and `event`, among others. The 2.0.29 tables `session`, `message` and `part` are gone. New `session_v2` columns include `time_busy`, `time_idle`, `idle_outcome`, `time_suspended` and `resume_attempts`. 2.2.7 stores message parts in a `session_part` table. 2.2.0 has no `session_part` table, and its part storage was not examined. In 2.2.7 the assistant message's `content` is also inside `session_message.data`, so a reader should not depend on `session_part` alone.
- **F4. Config hot-reload.** Running TUIs reload `opencode.json` and the plugin files when they change. Writing the MCP entry made running members start the shim straight away. An Agent Mail install therefore affects live members.
- **F5. Silent fallback to a hosted model.** One 2.2.7 session whose default was the custom `stub/m1` ran on `opencode/iceman-free` (OpenCode's hosted free models; the turn ended in a 429 `provider.free-limit` error). The cause was not reproduced. It happened about 20 s after a models.dev catalog refresh, and the custom provider was probably not resolved yet. Without an allowlist, `opencode models` lists 12 hosted `opencode/*-free` models with no credentials needed. `"enabled_providers":[…]`, or `"disabled_providers":["opencode"]`, removes them.
- **F6. Cold-start race.** Five `--standalone` launches started at once against a fresh data dir (2.2.0). One failed with `Error: Standalone server exited before reporting readiness`, and another exited before its output was captured. Serial launches always worked.
- **F7. The first launch shows a "what's new" overlay** (2.2.7) over the session view. Keys typed during startup could be lost.
- **F8. Prompt delivery.** `--prompt` on the TUI submits immediately (both versions). `send-keys -l <text>` followed by one `Enter` submitted a prompt in an idle TUI (both versions; the 2.2.0 probes used this).
- **F9. Updates.** The `update` key (`disable` / `notify` / `auto`) replaces `autoupdate`. Members should run with `"update":"disable"` so that a campaign keeps one version.
- **F10. Environment inheritance.** The private server and its plugins inherit the TUI's whole environment. Deck must not put secrets into a member's environment that the member's plugins should not read.
- **2.0.29, reported but not reproduced:** `opencode --version` prints `opencode v2.0.29`. The same TUI flags as 2.2.x. The `service.json` service. Tables `session`, `session_v2`, `message` and `part`. A `question.v2.asked` event. The user plugin dependency `@opencode-ai/plugin` 1.17.11.

## Design

### #730: Require OpenCode 2

- Parse `opencode --version`, which prints `opencode v<semver>` on 2.x. Refuse members when the major version is below 2, with the reason `opencode_v1_unsupported`.
- **Recommended floor: 2.2.0**, the oldest version this spike observed. 2.0.x and 2.1.x have no published releases or checksums. The floor is a recommendation for the #730 scope review. It does not change #730's acceptance.
- Record the version on each observation, as for Muse, because `opencode upgrade` can change it during a campaign.

### #731: Launch contract

```
opencode <directory> --standalone --session <ses_id> [--auto] [--prompt <text>]
  env: OPENCODE_CONFIG_CONTENT=<per-member JSON>, SYNTH_CITY_TEAM_PRESET_ID, SYNTH_CITY_TEAM_SLOT_ID, …
```

- Always pass `--standalone` (answer 3). Never pass `--model`, `--agent` or `--continue`.
- **Session id:** on the first launch, Deck generates `ses_` followed by 26 base62 characters, stores it in `launch_options.session_id` and passes `--session`. Later launches pass the same id. Refuse ids that do not start with `ses` before launching.
- **Model and agent:** put them in `OPENCODE_CONFIG_CONTENT` as `{"model":"<provider>/<model>[#variant]","default_agent":"<agent>"}`. Add `"update":"disable"`, the `question` deny rule (#732) and an `enabled_providers` allowlist that contains the member's provider (F5). A model change on a resumed session needs the plugin's `switchModel` (#732), because the config only sets the default for new sessions.
- **`skip_permissions` maps to `--auto`.** Keep refusing `dangerously_bypass_approvals_and_sandbox`. `reasoning_effort` stays unsupported. Variants (`#variant`) could carry it later.
- **Process match:** argv0 `opencode`, with the shim under an `opencode serve --stdio` child. `pane_current_command` is `opencode`. Treat `opencode serve --service` as foreign: it is never a member.
- Launch team members one at a time to avoid F6.

### #732: Agent Mail install and question deny

- **Plugin:** rewrite `_opencode_plugin_content()` as a v2 plugin: `export default { id: "albiex-synth-city-agent-mail", setup(ctx) { … } }`, with no imports. Map the hooks as in answer 4: `session.created` → `session-start`; `session.execution.succeeded` / `.failed` → the idle report; `ctx.tool.hook("execute.after")` → `post-tool-use`; `ctx.session.hook("context")` → `user-prompt-submit` with the context pushed onto `system`. Optionally, `ctx.session.hook("prompt")` can apply `switchModel` when the slot's model differs from the session's.
- `installed_opencode_plugin_events()` must detect the v2 shape. An old v1 plugin file counts as **not installed**, because it never loads.
- **MCP entry:** write `mcp.servers.albiex-synth-city-mail = {type:"local", command, environment, codemode:false}`. Migrate and remove an existing flat `mcp.albiex-synth-city-mail` entry. Without `codemode:false`, members reach Mail only through `execute` and `search` (F2).
- **Question deny:** put `{"action":"question","resource":"*","effect":"deny"}` in `permissions`, both in the user config written by the install and in each member's `OPENCODE_CONFIG_CONTENT`. Add a plugin `permission.evaluate` deny as a second layer. Its message tells the agent to write to its Leader instead. Status gains `opencode_question_denied`.
- The install touches live members through hot-reload (F4). Keep the existing backup step.

### #733: Observation, guard and live check

- **Activity:** use the plugin events as the primary source (answer 6). Add a `session_v2` reader for recovery, read-only and bound by session id and directory, that reports `unknown` when the row says busy and no live `serve --stdio` child is under the pane.
- **Waiting for input:** `form.created` (question) and `permission.asked` raise the existing waiting-input notice. The matching replied or cancelled events clear it.
- **Guard:** the team supervisor's OpenCode branch reads the bound session's assistant `content` text from `session_message` instead of a transcript file. It uses `session_part` only where that table exists (F3). Tool results and user prompts never create a hold, as for the other harnesses.
- **Live check:** run one `--standalone` member on a real provider through Deck. It registers once with its own slot, Deck stores its `ses_` id, it resumes the same session after a restart, working and idle show correctly, and a forced question is denied. **The real-model behaviour this spike could not prove is checked here.**

## Out of scope

- Changing Deck code. That is #730–#733.
- OpenCode's GUI, `serve`, `acp`, `mini` and `run` as team members.
- The shared background service for members. Running one dedicated service per member could work, but it was not tested.
- 2.0.x and 2.1.x behaviour beyond the reported notes above.
