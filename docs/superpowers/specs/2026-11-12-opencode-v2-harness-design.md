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
- **Isolation.** OpenCode ran only in a throwaway runtime: its own `HOME` and `XDG_*` dirs and `TMPDIR`, and a private tmux socket. OpenCode stored no credential of its own: its credential and account tables are empty and there is no auth file (R). **That does not mean the runtime was credential-free.** The OpenCode processes inherited the owner's session environment, including a messaging token and Agent Mail identity variables. That covers every run before the identity variables were removed (about 22:50Z), and runs before the credential-like variables were removed (about 22:55Z) still carried the token. Those removal times are owner-reported (NR), and no process environment was retained. Which later process, if any, still carried them, and whether any variable was transmitted, is **unknown**. Mail traffic went to a local recorder, never to a live Deck. No factory config, agent user, `/opt` path or port 8011 was touched.
- **Model.** Model turns came from a local scripted OpenAI-compatible stub provider (`stub/m1`, `stub/m2`). It returns fixed text or forced tool calls. Observations marked **[stub]** show harness mechanics: flags, ids, processes, events, hooks, DB rows, tool lists and the tool results the agent receives. **They do not show how a real model behaves**, for example whether a real model tries to ask questions or copes with Code Mode. That is still unproven.
- **Incident.** One 2.2.7 test session silently ran on OpenCode's hosted free model, `opencode/iceman-free`, instead of the stub, and got a 429 free-limit error (see finding F5). It was reported to the Leader and contained with `enabled_providers`. The retained DBs hold exactly one session with a hosted model (R). That does not prove no other request reached a hosted service, because request logs were not retained. **What that request contained is not retained**, so this spike cannot prove what was sent, or that no credential was sent (see F5). After the incident, model-turn probes stopped until a loopback-only network namespace was in place (see Isolation limits).

### Version coverage and evidence retention

**R** means the observation is kept in an artifact that survives the spike (listed under "Evidence retention"), so a reviewer can check it. **NR** means it was seen during the spike, but the log that held it was cleared between probes. NR claims rest only on the owner's session record and **have not been independently verified**. They are not inferred from nearby probes.

| Item | v2.2.7 | v2.2.0 |
|---|---|---|
| `--model` / `--agent` refused | R (log) | R (log) |
| `--auto` accepted | R (DB) | R (DB) |
| `--yolo`, `--dangerously-skip-permissions` accepted | R (DB) | NR |
| `OPENCODE_CONFIG_CONTENT` model and `default_agent` on a new session | R (DB) | R (DB) |
| Custom primary agent from config: agent and model | R (DB) | not run |
| Custom agent's system prompt reaches the model | NR | not run |
| `--session` id refused without the `ses` prefix | R (log) | R (log) |
| Deck-chosen `ses…` id created | R (DB) | R (DB) |
| Relaunch resumes the same session | R (DB) | R (DB, P4) |
| Config default `model` does not change a resumed session | NR | R (stub log, P4) |
| `agents.build.model` does not change a resumed session | NR | not run |
| Plugin `switchModel` changes a resumed session | R (DB row); same-turn use NR | R (recorder and stub log, P4) |
| `--standalone` process tree, `pane_current_command`, plugin and shim process | NR | NR |
| Shim sends a registration payload (keys `cwd`, `pid`, `provider`, `session_key`, `source`) | NR | R (recorder, P4) |
| The member's `team_slot_id` reaches the registration payload | NR | NR (P4 set no slot, so its payloads have none) |
| Shared service ignores the second member's config | R (DB) | **gap** (not run, by decision) |
| Shared service reports the first member's slot for the second member | NR | **gap** (not run, by decision) |
| v1 plugin refused | R (log) | R (log) |
| v2 plugin loads; `session.created`, `session.execution.started` / `.succeeded`; `context` and `prompt` hooks fire | NR | R (recorder, P4) |
| Text pushed in the `context` hook reaches the model | NR | NR |
| `tool.execute.after`, `permission.evaluate` hooks fire | NR | NR |
| `experimental.idle` hook | fired, NR | never fired in 3 turns, R (recorder, P4) |
| A failed turn: `idle_outcome:"failed"` with the error | R (DB, F5) | **gap** |
| `question` call blocks the turn | R (DB) | R (DB) |
| `form.created` / `.replied` / `.cancelled` payloads | NR | NR |
| Question deny by config: the call fails with "No tool named" | R (DB) | R (DB) |
| Question deny by config: the tool is left out of the model's tool list | NR | NR |
| Question deny by plugin `permission.evaluate` | R (DB) | **gap** |
| `ask` rule: auto-approved with `--auto`, blocks without it | R (DB) | auto-approved, R (DB) |
| `permission.asked` / `.replied` events | NR | NR |
| Deny rules still apply under `--auto` and its aliases | R (DB) | R (DB) |
| MCP Code Mode by default ("36 tools, 11 shown") | NR | NR |
| `codemode:false` makes Agent Mail tools direct calls | R (DB) | R (DB) |
| `session_v2` has `time_busy` | R (DB) | **absent** in the 2.2.0 schema, R (DB) |
| `session_v2` has `time_idle`, `idle_outcome`, `time_suspended`, `resume_attempts` | R (DB) | R (DB) |
| A killed session's row is left looking active | R (DB): `time_busy > time_idle`, `time_suspended` set | R (DB): `time_idle` null, `time_suspended` set |
| Relaunch without a prompt leaves a stale row unchanged for 40 s | NR (that session was later deleted) | **gap** |
| Silent hosted-model fallback (F5) | R (DB, log) | not seen |
| Cold-start race (F6) | not seen | R (log) |

### Acceptance questions that stay open

These parts of #729 have no retained acceptance evidence. **The spike leaves them as open gaps, and #729 is not answered with acceptance evidence on these points.** The Supervisor's incident disposition allows no further probes in #729. The implementation issues #730–#733 must close these gaps with their own tests. The restoration-run observations (E1–E5, below) bear on all four, but they are research observations with explicit provenance, not acceptance evidence. The design below treats these points as unverified and gives no guarantee:

- **Q3:** which process runs the MCP shim and the plugin, which pid the registration reports, and what `pane_current_command` shows. In the original spike only the service-mode config effect is R. See E1 and E2.
- **Q4:** the hook order and live payloads for `tool.execute.after` and `permission.evaluate`, and whether text pushed in the `context` hook reaches the model. In the original spike these are NR on both versions; only the 2.2.0 `context` and `prompt` hooks firing (P4) and the published types (A10) are retained. See E3.
- **Q5, second half:** which event shows an open question and what a row looks like while it is open. See E4.
- **Q6:** a reliable activity source after a crash, an interrupt or a relaunch. See E4 and E5.

### Evidence retention

The owner keeps these artifacts read-only in the spike's private scratch area. They are not published, because they hold local paths and runtime values.

- A1, A2: the OpenCode SQLite DBs (2.2.7, 2.2.0): sessions, messages and parts, with tool outcomes and errors.
- A3, A4: the OpenCode logs (2.2.7, 2.2.0): CLI failures, including flag and id refusals; plugin loading and v1 plugin failures; the free-limit error.
- A5: the Agent Mail recorder log, **for the last 2.2.0 run (P4) only**.
- A6: the stub model request log, **for P4 only**.
- A7: the namespace and route checks for the 2.2.0 probes.
- A8: the downloaded release archives and their `SHA256SUMS`.
- A9: the v2 config schema (`opencode.ai/config.json`).
- A10: the `@opencode/plugin` 2.2.7 type definitions. The hook and event payload shapes quoted in answers 4–7 match these types. The captured payloads themselves are NR.
- A11: the stub model, the recorder, the probe plugins and the probe scripts.

The recorder and stub request logs were cleared before each probe, so their content from every run before P4 is gone. Screen captures and process listings were never saved.

### Isolation limits

- Runtime: its own `HOME`, `XDG_*` and `TMPDIR`, a private tmux server, and a scratch Python venv for Deck's MCP shim. The environment was inherited from the owner's session. Agent Mail identity and credential-like variables were removed only partway through the spike (see Method: Isolation). **No member ever registered with a real Synth City.** Mail calls went to a local recorder that logs the request and answers with a fake member. Every "registration" in this spec is the payload the real shim sent to that recorder, and the shim's later tool replies are artifacts of the fake answer (for example, the error text in F2).
- Network: until the incident (F5), the only network limit was the stub provider config, and that **did not stop a fallback to a hosted model**. From then on, both configs allowed only `stub` (`enabled_providers`). The four 2.2.0 probes after the incident ran in an unprivileged user and network namespace (`unshare -rn`, then mapped back to the real uid). Its only interface is `lo`, and it has no IPv4 or IPv6 routes. Each OpenCode process tree was checked to be in that namespace before its turn, and the Leader verified the namespace independently. Earlier runs, on both versions, had normal host networking: OpenCode refreshed its models.dev catalog, and one turn reached the hosted model.
- Inside the namespace, OpenCode cannot refresh its models.dev catalog and uses the cached copy. No effect on the probes was seen.
- Not tested: real-model behaviour, OpenCode's GUI and web clients, Windows and macOS, and more than one standalone member running at the same time (other than the cold-start race in F6).

## Answers

Retention (R or NR) for each claim is in the coverage table above. Answers 4–7 quote payload shapes. The captured payloads are NR, and the shapes match the published `@opencode/plugin` types (A10).

### 1. Model and agent

| | v2.2.7 | v2.2.0 |
|---|---|---|
| `opencode <dir> --model x` / `--agent x` | Rejected: `ERROR Unrecognized flag: --model in command opencode`, exit 1. The same for `--agent`. | The same. |
| Other unknown flags | Rejected, exit 1. | Not tested. |
| `opencode run` / `opencode mini` | `opencode run --help` still lists `--model provider/model#variant` and `--agent`. `mini` was not checked; the issue reports the same for 2.0.29. These are not TUI members. | Not checked. |

**How Deck selects them:** set the environment variable `OPENCODE_CONFIG_CONTENT` on the launch. It is merged on top of the user config. **[stub]** `{"model":"stub/m2","default_agent":"plan"}` started a new session with the Plan agent on `stub/m2`, on both versions. A custom primary agent works too: `{"agents":{"deckmember":{"mode":"primary","model":"stub/m2","system":"…"}},"default_agent":"deckmember"}` gave a new session that agent's model and system prompt.

**A resumed session keeps its model.** The model is stored per session (`session_v2.model`). On relaunch with `--session <id>`, the config default `model` did not change it (both versions [stub]; R only for 2.2.0), and neither did `agents.build.model` (2.2.7 [stub], NR). The plugin API can change it: calling `ctx.session.switchModel({sessionID, model:{providerID, id}})` from the plugin's `prompt` hook moved a resumed session from `m1` to `m2`. The same turn already used `m2`, and the row was updated (both versions [stub]). `switchAgent` exists too, but this spike did not test it.

### 2. Identity

- **Deck can choose the id.** `--session <id>` on the first launch creates a session with exactly that id (both versions). The only check observed is the prefix: the id must start with `ses`. `ses_abc`, `ses_deck-slot-29_issue-729` and `ses_deckslot29spike0000000001` were accepted. A UUID or `deck-slot-29` was refused with `Error: Expected a string starting with "ses" at ["sessionID"]`, exit 1. Native ids look like `ses_` followed by 26 base62 characters (for example `ses_e2e111c0dffe5XAqhRWBFFBZDf`). Deck should generate ids in that shape.
- **Relaunch resumes the exact session.** Relaunching with the same `--session` continued the same `session_v2` row, kept its history and created no new session (both versions [stub]). The first 2.2.0 attempt was invalid because its first launch failed in the cold-start race (F6). A later run inside the namespace confirmed resume over three launches of one session.
- `--continue` resumes the most recent session in the directory. Deck should not use it for members.

### 3. Process model

**With `--standalone` (both versions; process listings NR):**

```
tmux pane: opencode --standalone --session ses_…      pane_current_command = "opencode"
  └─ opencode serve --stdio --port 0                  private server, child of the pane process
       └─ <python> agent_mail_server.py               MCP shim
```

- The MCP shim and the plugins run in the private `serve --stdio` process. The probe plugin's `process.pid` matched that process.
- The Agent Mail shim's registration payload, sent to the recorder (not accepted by any Synth City), carries `pid = os.getppid()`, which is the private server's pid: a direct child of the pane's process, not the pane's process itself (NR). The slot environment (`SYNTH_CITY_TEAM_SLOT_ID`) reached both the shim's payload and the plugin (NR on both versions). The retained P4 payloads have no `team_slot_id`, because P4 set no slot. **Q3 has no retained evidence for the process tree, the pid relation or `pane_current_command`. These are open #729 gaps (see "Acceptance questions without retained evidence").**
- The private server also listens on a random `127.0.0.1` port and requires authentication (`/api/event` returns 401). Its password is in the server's environment (`OPENCODE_PASSWORD`) and is not published anywhere. Deck should not use this endpoint (see 6).
- When the TUI is killed, the private server shuts down a few seconds later (`location.shutdown`, 2.2.7; NR).

**Without `--standalone` (2.2.7):**

- The first TUI starts `opencode serve --service` as its own child, using its own environment, and writes `~/.local/state/opencode/service.json` with the URL, pid and a password. Later TUIs connect to that service and start no server of their own. Non-TUI commands such as `opencode models` also start the service, detached.
- **The members get mixed up [stub].** Member B1 (slot 9002) started the service, and then member B2 (slot 9003) connected to it. All of B2's session events and hooks came from the service with `slot 9002`, and the shim sent one registration payload, as slot 9002, with the service pid (NR). B2's `OPENCODE_CONFIG_CONTENT` asked for `stub/m2`, but B2's session row has `stub/m1`, the service's model (R).
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
| `experimental.chat.system.transform` | `ctx.session.hook("context")` | `{sessionID, agent, model, system:[{type:"text", text, metadata?}], messages, tools, options}`. Pushing `{type:"text", text}` onto `system` reached the model request (NR). |

Other events seen in a turn: `session.execution.started`, `session.inbox.enqueued` / `.delivered`, `session.step.started` / `.streamed` / `.ended` / `.failed`, `session.text.*`, `session.tool.input.started` / `.ended`, `session.tool.called` / `.success` / `.failed`, `session.usage.updated`, `session.renamed`, `session.viewed`, `form.created` / `.replied` / `.cancelled`, `permission.asked` / `.replied`, `mcp.status.changed` and `location.shutdown`. The `ctx.session.hook("prompt")` hook gets `{sessionID, messageID, prompt:{text, files, agents}, delivery:"steer"}`.

Event order in a turn varies, because handlers run asynchronously. Use `created` and `durable.seq`, not arrival order.

### 5. Questions

- **The tool:** `question` is in the default tool list. A call opens a TUI form (`Questions … ↑↓ select  enter submit  esc dismiss`) and blocks the turn (both versions [stub]).
- **Open-question signal:** a `form.created` event with `data.form.metadata.kind:"question"`, a `tool` reference and the `fields`. The form ends with `form.replied` (`answer`) or `form.cancelled`. The 2.0.29 `question.v2.asked` event did not appear in 2.2.x. Durable state while the question is open: the `question` tool part has `state.status:"running"`, `session_v2.time_busy` is set, and `time_idle` is null (NR while open; the R rows of sessions killed during a question still show busy).
- **What the agent sees after an answer (NR):** `User has answered your questions: "Pick one?"="A". You can now continue with the user's answers in mind.`
- **Denying the tool by config works.** Both the deprecated v1 form `"permission":{"question":"deny"}` and the v2 rule `"permissions":[{"action":"question","resource":"*","effect":"deny"}]` remove `question` from the tools sent to the model (12 tools become 11; NR). When the stub forced the call anyway, the agent got `{"error":{"type":"tool.execution","message":"No tool named \"question\" is currently available. …"}}` (v2 rule: both versions [stub]; v1 form: 2.2.7 [stub]). A real model should not see the tool at all, but that is not proven with a real model.
- **Denying from the plugin hook works too, but the tool stays visible.** `ctx.permission.hook("evaluate")` gets `{sessionID, agent, action:"question", resources:["*"], source, effect}`. Setting `effect = "deny"` and `message = …` rejects the call. The agent gets `{"error":{"type":"permission.rejected","message":<our message>}}`, and the event is `session.tool.failed`. The tool is still offered to the model.
- `--auto` does **not** stop questions: the form still opens.

### 6. Activity

Observed on 2.2.7 [stub]. On 2.2.0, the execution events and `form.created` were also seen.

| Source | Working | Idle | Waiting for input | Verdict |
|---|---|---|---|---|
| Plugin events (in the member's own `--standalone` server) | `session.execution.started` | `session.execution.succeeded` (or `.failed` with `error.type`) | `form.created` (question), `permission.asked` (approval); cleared by `form.replied` / `form.cancelled` / `permission.replied` | **Primary.** Exact, immediate, and tied to the slot because the plugin runs with the member's environment. |
| `session_v2` row | 2.2.7: `time_busy > time_idle`. 2.2.0 has no `time_busy`; `time_idle` null or older than the last prompt is the only hint | `time_idle` set, `idle_outcome` `succeeded` / `failed` | Not visible: looks like working | **Secondary**, and only a hint. It goes stale when a TUI dies, and process liveness alone does not detect that. Retained killed sessions still look active: two on 2.2.7 (`time_busy > time_idle`, `time_suspended` set) and one on 2.2.0 (`time_idle` null, `time_suspended` set). A session killed mid-turn was not cleared by a relaunch without a prompt within 40 s (NR), so even a live relaunched process can leave a stale row. No retained evidence shows what clears `time_suspended`. |
| Service `/event` stream | — | — | — | **Not usable.** Members use `--standalone`, whose server is private and password-protected, and the shared service mixes up members (3). |

`session_message` also stores an `idle` row with `outcome` after each turn. The `event` table stayed empty in every run.

### 7. Skip permissions

- `--auto` ("Auto-approve permissions that are not explicitly denied") does what Deck needs. With a `shell` `ask` rule, `permission.asked` was followed by an automatic `permission.replied` `"once"` (events NR), and the command ran (both versions [stub], R). Without `--auto`, the TUI stopped on `Permission required … Allow once / Always allow / Reject` (2.2.7 [stub]).
- **Deny rules still apply under `--auto`.** An `external_directory` deny gave `permission.rejected` (both versions [stub]), and the `question` deny held (2.2.7 [stub]).
- The hidden flags `--yolo` and `--dangerously-skip-permissions` are accepted by both versions and show the same "Build auto" mode as `--auto` (footer NR; 2.2.7 sessions under both flags R). On 2.2.7, deny rules still applied under both flags [stub]. They are not in `--help`, so Deck should use only `--auto`.
- 2.2.7's default rules allowed everything tried without asking, including reading `/etc/hostname` through `external_directory`. Only the `question` tool interrupted a default session.

## Restoration-run observations (E1–E5)

**Provenance.** After review, the owner ran a bounded evidence-restoration run on v2.2.7 only (2026-11-12, 23:28–23:35 UTC).
- **Network and model:** it ran in a loopback-only network namespace that the Leader verified, with the stub provider only (`enabled_providers:["stub"]`).
- **Retention:** every artifact was kept, and a hash manifest covers 50 files. The owner holds the artifacts privately; V1 verified the hashes.
- **Authorization:** E1 ran within the Leader's authorization. **E2–E5 are a post-stop, unauthorized run.** The Leader had issued a stop, and the owner did not check Mail between probes, so E2–E5 ran after it.
- **Status:** the Supervisor's incident disposition allows all five to be cited here as research observations. **They are not acceptance evidence for #729 or any later issue.**
- **Limits:** the namespace helper processes carried the owner's inherited token and identity variable names. The OpenCode processes' environment-name checks were printed only to the owner's session (NR). The Mail recorder is local, not Synth City. The recorder log kept the synthetic test prompts in one field and local paths.

| Run | Question | Observation (v2.2.7, stub) |
|---|---|---|
| E1 (authorized) | Q3 | With `--standalone`, the ancestry is TUI → `opencode serve --stdio --port 0` → MCP shim. The probe plugin's init record and the shim's registration payload both report the `serve --stdio` pid, a child of the pane process, with the fake slot (`team_slot_id` 9601). `pane_current_command` is `opencode`. The TUI footer shows "1 plugin failed", which is Deck's v1 plugin. No `session_v2` row exists until the first prompt. |
| E2 (post-stop, unauthorized) | Q3 | Without `--standalone`: member A starts `opencode serve --service` as its own child, and that service runs the only MCP shim. Member B's pane has no server child. One registration payload is sent, carrying A's slot (9602). Member B's (slot 9603) `session.created` and `session.execution.*` events come from the service process labelled with A's slot. B's `OPENCODE_CONFIG_CONTENT` asked for `stub/m2`, but B's session runs and is stored with `stub/m1`. |
| E3 (post-stop, unauthorized) | Q4 | Arrival order for one turn with one tool call: `session.created`, then the `prompt` hook, `context` hook, `session.execution.started`, `tool.execute.before`, `permission.evaluate`, the `session.tool.*` events, `tool.execute.after` (`status:"completed"`), a second `context`, the `experimental.idle` hook, and `session.execution.succeeded`. Durable `seq` values are kept. A marker pushed onto `system` in the `context` hook was present in both agent-loop model requests (`marker_present=true`; the prompt text was not logged). After `opencode session delete` from a separate CLI, the member's plugin received no `session.deleted` or any other record within 60 s, and the CLI produced no plugin records. |
| E4 (post-stop, unauthorized) | Q5 | **Answered:** `form.created` (`data.form.metadata.kind:"question"`, linked to the tool call). While open, the tool part is `running`, `time_busy` is set, `time_idle` is null and `time_suspended` is set. Then `form.replied` (`answer`), the part becomes `completed`, and the row goes idle and `succeeded`. **Cancelled with Esc:** `form.cancelled`, the tool part ends `aborted`, and a `session.execution.interrupted` event fires. The row then still looks busy (`time_idle` null, `time_suspended` set) while the TUI is alive and shows "interrupted". **Denied by the config rule:** `question` is absent from the offered tools (11 instead of 12), and the forced call fails with "No tool named". |
| E5 (post-stop, unauthorized) | Q6 | `time_suspended` is set during every live execution and cleared at idle, so it is **not** a crash marker. After a kill mid-turn, the row keeps `time_busy > time_idle` with `time_suspended` set. A relaunch with the same `--session` and no prompt left the row unchanged for 40 s, and the new server sent only its plugin init and registration, with no execution event. The first new prompt produced `session.execution.started` and `.succeeded` from the new server process and cleared the row. |

**Consequences for the design** (still unverified for acceptance):
- A `session_v2` row can look busy both after a crash and after an interrupt with a live process (E4, E5), and `time_suspended` does not tell these cases apart. The recovery reader in #733 must never report `working` from the row alone.
- The plugin's `session.execution.started`, `.succeeded`, `.failed` and `.interrupted` events, seen from the current server process, are the candidate activity source.

## Other findings

- **F1. Config keys renamed.** The v2 schema (`https://opencode.ai/config.json`) deprecates `agent`, `permission`, `plugin`, `provider` and the flat `mcp.<name>` map. Their replacements are `agents`, `permissions` (an ordered rule list `{action, resource, effect}`), `plugins`, `providers` and `mcp.servers.<name>`. The deprecated forms still work in 2.2.x. New Deck writes should use the v2 forms.
- **F2. MCP tools are in "Code Mode" by default.** The Agent Mail tools are not direct tool calls. The system prompt says they "only work as JavaScript inside the `execute` tool" and lists only 11 of the 36 tools (`albiex-synth-city-mail (36 tools, 11 shown)`, NR). The model must use `search(...)` to find the rest. Setting `"codemode": false` on the server entry (`mcp.servers.<name>` or the flat form) makes them direct tools named `albiex-synth-city-mail_<tool>`, all 36 of them (NR). `execute` is still offered for other code (NR). **[stub]** A direct `albiex-synth-city-mail_synth_city_check_inbox` call was executed by the shim on both versions (R). The recorder's fake reply produced the tool error, and the slot in the registration payload is NR.
- **F3. The DB schema changed.** The 2.2.x tables are `session_v2`, `session_message`, `session_part`, `session_inbox` and `event`, among others. The 2.0.29 tables `session`, `message` and `part` are gone. The schema also differs between 2.2.x versions. `session_v2` has `time_idle`, `idle_outcome`, `time_suspended` and `resume_attempts` in both, but **`time_busy` only in 2.2.7**. 2.2.7 has a `session_part` table and 2.2.0 does not. In both versions the assistant message's `content`, including tool parts with their status and errors, is inside `session_message.data` (R). Readers must check the schema per version and must not depend on `time_busy` or `session_part`.
- **F4. Config hot-reload.** Running TUIs reload `opencode.json` and the plugin files when they change. Writing the MCP entry made running members start the shim straight away. An Agent Mail install therefore affects live members.
- **F5. Silent fallback to a hosted model.** One 2.2.7 session whose default was the custom `stub/m1` ran on `opencode/iceman-free` (OpenCode's hosted free models; the turn ended in a 429 `provider.free-limit` error). The cause was not reproduced. It happened about 20 s after a models.dev catalog refresh, and the custom provider was probably not resolved yet. Without an allowlist, `opencode models` lists 12 hosted `opencode/*-free` models with no credentials needed. `"enabled_providers":[…]`, or `"disabled_providers":["opencode"]`, removes them. **The request sent to the hosted model is not retained**, so this spike cannot show what it contained, or that it carried no credential. The retained facts are only these: OpenCode's `credential`, `account`, `account_state` and `control_account` tables are empty; the runtime has no auth file; and its config holds no API key except the stub's placeholder. Removing credential variables from the environment before that turn is NR.
- **F6. Cold-start race.** Five `--standalone` launches started at once against a fresh 2.2.0 data dir. The retained 2.2.0 log shows two `Standalone server exited before reporting readiness` failures, one `SQLiteError: database is locked`, and one failed `CREATE TABLE` migration query (R). Serial launches always worked.
- **F7. The first launch shows a "what's new" overlay** (2.2.7) over the session view. Keys typed during startup could be lost.
- **F8. Prompt delivery.** `--prompt` on the TUI submits immediately (both versions). `send-keys -l <text>` followed by one `Enter` submitted a prompt in an idle TUI (both versions; the 2.2.0 probes used this).
- **F9. Updates.** The `update` key (`disable` / `notify` / `auto`) replaces `autoupdate`. Members should run with `"update":"disable"` so that a campaign keeps one version.
- **F10. Environment inheritance.** The private server and its plugins inherit the TUI's whole environment. Deck must not put secrets into a member's environment that the member's plugins should not read.
- **2.0.29, reported but not reproduced:** `opencode --version` prints `opencode v2.0.29`. The same TUI flags as 2.2.x. The `service.json` service. Tables `session`, `session_v2`, `message` and `part`. A `question.v2.asked` event. The user plugin dependency `@opencode-ai/plugin` 1.17.11.

## Design

### #730: Require OpenCode 2

- Parse `opencode --version`, which prints `opencode v<semver>` on 2.x. Refuse members when the major version is below 2, with the reason `opencode_v1_unsupported`.
- **Recommended floor: 2.2.7**, the version with the most evidence. 2.2.0 differs in ways that matter to #733: it has no `session_v2.time_busy`, and the `experimental.idle` hook never fired. It also has open gaps in the coverage table. Lowering the floor to 2.2.0 is possible only after #733's live check covers it. 2.0.x and 2.1.x have no published releases or checksums. The floor is a recommendation for the #730 scope review. It does not change #730's acceptance.
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

- **Activity:** use the plugin events as the primary source (answer 6). A `session_v2` reader for recovery, read-only, bound by session id and directory and schema-aware per version (F3), may only report `idle` or `unknown`. Proposed rule, **unverified** (an open #729 gap, Q6): report `working` only after the plugin has seen `session.execution.started` from the current server process. Report `unknown` for any busy-looking row with no such event, after a `session.execution.interrupted`, and while no live `serve --stdio` child is under the pane. `time_suspended` is set during every live execution, so it is not a crash marker (E5), and process liveness alone is not enough (E4). This spike does not guarantee the rule.
- **Waiting for input:** `form.created` (question) and `permission.asked` raise the existing waiting-input notice, and the matching replied or cancelled events clear it (observed in E4, not acceptance evidence). #732 and #733 must prove these signals with their own tests before Deck relies on them.
- **Guard:** the team supervisor's OpenCode branch reads the bound session's assistant `content` text from `session_message` instead of a transcript file. It uses `session_part` only where that table exists (F3). Tool results and user prompts never create a hold, as for the other harnesses.
- **Live check:** run one `--standalone` member on a real provider through Deck. It registers once with its own slot, Deck stores its `ses_` id, it resumes the same session after a restart, working and idle show correctly, and a forced question is denied. **The real-model behaviour this spike could not prove is checked here.**

## Rules for later harness probes (#730–#738)

From the Supervisor's #729 incident disposition:

1. Start each third-party CLI with an empty environment and an explicit allowlist (for example `env -i HOME=… PATH=…`). Never inherit the agent session's environment.
2. Configure only the local stub provider, and confirm that no hosted-provider fallback exists before the first turn.
3. Check Mail before each probe, and stop at once on a stop message.

## Out of scope

- Changing Deck code. That is #730–#733.
- OpenCode's GUI, `serve`, `acp`, `mini` and `run` as team members.
- The shared background service for members. Running one dedicated service per member could work, but it was not tested.
- 2.0.x and 2.1.x behaviour beyond the reported notes above.
