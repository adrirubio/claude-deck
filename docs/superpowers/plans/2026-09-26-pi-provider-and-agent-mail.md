# Pi Provider, Agent Mail and OpenRouter Kimi K3 — Implementation Plan

**Issue:** https://github.com/adrirubio/claude-deck/issues/357
**Status:** Implemented in the isolated feature worktree; independent Astra findings resolved and targeted re-review cleared. See `docs/deploy/pi-provider-validation.md` for execution evidence. PR review, merge and every live rollout checkpoint remain separate.
**Review:** `/tmp/pi-provider-plan-astra-review.md`; final disposition closes F1–F9 and lifecycle corrections A1/A2. This approves the plan, not deployment or live migration.
**Implementation amendment:** Early closure review required a durable `MailPaneLifecycle` admission/retirement gate keyed by pane PID/start time, atomic registration-plus-binding publication, and a strict liveness helper for destructive retirement. These strengthen the reviewed terminal-close contract; they do not change work-item/approval authority or live policy. Existing unobservable-liveness behavior for unrelated discovery callers is preserved.
**Baseline:** `origin/feature/autonomous-github-dispatch` at `2a51da44b634319644b4147b65764bdb7311936a`.
**Working branch:** `feature/pi-provider`, isolated worktree `/home/juan/work/repos/juanrubio/claude-deck-pi-provider`.
**Delivery:** One implementation PR into `feature/autonomous-github-dispatch`, never master. Deployment and live migration are separate operator checkpoints after review and merge.

## Goal and Scope

Make Pi a first-class provider that can participate in Deck Teams using Kimi K3 on OpenRouter, including authenticated mailbox tools, distinct approval authority, heartbeat, bound wakes and the existing continuation protocol. Do not modify the recovery protocol to accommodate the client. A provider change is not a guarantee that every client/model interruption disappears.

The Tizonia scheduler fix is already merged in PR #878. This work does not apply it to draft PR #875, submit a continuation, spend a revision, change policy or declare a soak pass. The live attempt remains escalated, autonomy off, continuation on and merge policy human. The independently launched Pi/Kimi investigation session is unrelated and must remain unaffected.

## Measured Inputs and Decisions

| Input | Measured fact / decision |
| --- | --- |
| Pi installation | `@earendil-works/pi-coding-agent` 0.87.1; executable `pi` |
| Model | Installed catalog and OpenRouter API list `moonshotai/kimi-k3`, including tool calling |
| Pi launch | Native `--provider openrouter --model moonshotai/kimi-k3`; explicit extension path |
| Pi resume | `--continue` or `--session <validated project-local exact path>`; resolve full IDs to that path, never pass prefixes or cross-project IDs through to Pi |
| Thinking | Native `--thinking`: off, minimal, low, medium, high, xhigh, max; Deck maps its `reasoning_effort` field, no new generic field needed |
| Extension API | `pi.registerTool`, `session_start`, `session_shutdown`; current SDK uses `typebox`, not `@sinclair/typebox` |
| MCP | No assumed native MCP configuration integration; connect the existing Python stdio shim with a Deck-owned Pi extension |
| MCP client | NPM `@modelcontextprotocol/sdk` currently 1.30.1; lock compatible versions and test against the Python server |
| Existing provider contract | Registry, capability matrix, launch descriptor, Team install readiness and wake allowlist all need explicit Pi support |
| UI defaults | Currently biased toward Anthropic/Bedrock; Pi must show OpenRouter, not silently inherit Anthropic |
| Credentials | Pi's existing auth storage or provider-specific inherited configuration; no new credential field or copied key |
| Permissions | Pi's built-in file/bash tools are not a Deck sandbox. No invented approval mode or `--yolo` flag; unsupported controls must be rejected |
| Participation | Only explicit Deck launches attach the mail extension. No global extension/config/hook installation |

Sources: [Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md), [Pi models/authentication](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md), [OpenRouter Kimi K3](https://openrouter.ai/moonshotai/kimi-k3). Recheck installed API declarations and CLI help when implementing; report drift instead of silently changing the contract.

## Safety and Delivery Constraints

- Never run a backend server or pytest from the live Deck checkout: its database URL is CWD-relative. Do not copy its `.env` or database into the implementation worktree.
- Tests use fixture databases, fake model/MCP transports and disposable tmux sockets. No real model calls, GitHub writes or public-repo builds during unit validation.
- Do not edit the Tizonia worktree, stop existing agents, change slots, alter a lease, enable autonomy, release a hold, or act as owner/Leader during this PR.
- Never use capability/operator/GitHub/OpenRouter credentials as command-line arguments, tmux metadata, launch JSON, manifest entries or diagnostic output.
- Preserve existing owner-only lease projections. The extension must not add debug logging or persisted custom entries containing lease material. Pi's ordinary owner tool transcripts remain sensitive; deployment must verify private permissions, not pretend every owner tool result is public-safe.
- Linux pane-derived authentication and existing parent-walk budgets remain unchanged. A process match is discovery, not proof of authority.
- Pi integration code must not send synthetic approvals/statuses, automatically answer mail, or act on another participant's behalf.
- Supported capability flags must describe implemented Deck surfaces, not everything Pi can theoretically do.

## File Map

| Files | Responsibility |
| --- | --- |
| `backend/app/services/providers/pi_cli.py` (new), `providers/__init__.py` | Provider and process recognition |
| `backend/app/services/providers/{base,capabilities,launch_contract,launch_options,platform_env}.py` | Launch options and honest provider capabilities |
| `backend/app/services/agent_bridge/spawn.py`, `backend/app/api/v1/agent_bridge/router.py` | Explicit opt-in extension launch and provider defaults |
| `backend/app/services/agent_mail_install_service.py`, `backend/app/models/schemas.py` | Readiness diagnostics without global installation |
| `backend/app/services/agent_team_service.py` | Team validation, readiness and Pi default propagation |
| `backend/app/services/agent_mail_service.py`, `backend/app/api/v1/agent_mail.py`, `backend/app/api/v1/deps.py` | Terminal self-close, closed-session authentication/registration guards, dead-pane operator retirement and explicit wake-provider support |
| `backend/app/models/database.py`, `backend/app/database.py` | Nullable terminal session-close timestamp and guarded compatibility migration |
| `backend/mcp_shim/agent_mail_server.py` | Registration readiness handshake, stoppable heartbeat, authenticated closure and mutation-outcome uncertainty; existing approval authorization unchanged |
| `integrations/pi-agent-mail/{extension,client,manifest}.ts` (new) | Explicit extension, MCP adapter and tool schemas |
| `integrations/pi-agent-mail/{package.json,package-lock.json,tsconfig.json}` (new) | Reproducible local dependencies and typecheck |
| `integrations/pi-agent-mail/tests/` (new) | Node built-in runner tests; no frontend test framework |
| `scripts/generate-pi-mail-manifest.py` (new) | Generate/check schemas from imported MCP definitions, without running the server heartbeat |
| `frontend/src/types/{providers,agentTeams}.ts`, `frontend/src/contexts/ProviderContext.tsx` | Provider/platform types and selection persistence |
| `frontend/src/features/providers/ProviderLaunchOptionsFields.tsx`, `frontend/src/features/cc-bridge/NewSessionDialog.tsx`, provider selectors in Teams/Bridge | Pi fields, serialized requests and provider-switch/default persistence |
| `frontend/src/types/agentMail.ts`, Agent Mail install-status UI | Optional backward-compatible Pi readiness fields |
| Backend provider/spawn/Teams/mail tests | Positive/negative integration contracts |
| `docs/deploy/pi-provider-rollout.md` (new) | Deployment, migration gates and rollback |

Search all provider allowlists/selectors before editing; update necessary consumers rather than adding another disconnected list. Do not add Pi to hook-provider handling merely to claim hooks exist: this implementation uses the MCP extension, not an unauthenticated hook as authority.

## Task 1 — Provider Identity, Discovery and CLI Contract

**Files:** provider registry/base/capabilities/launch contract; `backend/tests/test_providers.py`, `test_multi_provider_smoke.py`, `test_provider_contract_api.py`.

1. Add `PiCliProvider`: id `pi-cli`, display name Pi, executable/version `pi --version`. Expose config/session locations as paths only; do not read or inventory auth-file contents.
2. Recognize direct `pi` panes and the installed Pi Node bundle entry point `dist/bundle/cli.js`, including a shell parent with the actual Pi descendant. Inspect executable/cmdline identity; do not classify arbitrary Node processes, filenames containing `pi`, or background MCP children as Pi panes. Keep discovery's depth 4, mail association's eight iterations and kernel peer resolution's 32-parent bound distinct and unchanged.
3. Plain and resume only. Build argv, never a shell string; directory is handled by the tmux bridge. A prompt is a positional message after `--` so leading hyphens cannot become flags. Pi still interprets a leading `@` as a file attachment after `--`: reject such prompts with stable `pi_literal_prompt_required`, without opening the file. Spaces, quotes and multiline prompts remain literal argv values.
4. Default model is explicitly Kimi K3 for this OpenRouter-first integration. Permit other nonempty OpenRouter model IDs through the model field. Normalize an optional `openrouter/` prefix without changing the Moonshot model namespace.
5. Resume requires a validated exact project-local session path or full session ID resolved to that path, or `use_last`; reject ambiguous/both selectors. Reject prefix/malformed IDs and foreign-project paths/IDs rather than invoking Pi's fork confirmation. Resolve using the installed Pi session-directory/project mapping without exposing transcript contents; do not guess its encoding. Include Pi in the Team unsafe-resume-last provider allowlist and test two slots in the same repository.
6. Map `reasoning_effort` to native `--thinking`; reject invalid values and unsupported fork/worktree, profiles, sandbox/approval/bypass, remote, agent, plan and Bedrock options with stable launch errors.
7. Declare spawn/resume capabilities supported; mail extension support is described explicitly. Leave generic config writes, plugin administration, session export/backup, arbitrary MCP configuration UI and permission control unsupported unless actually implemented here.

**Tests:** exact argv and quoting inputs; nonexistent executable; installed-version parse; plain/resume defaults; leading-hyphen prompt; impostor Node command; wrong descendant/depth; unsupported modes/options; old provider descriptor/argv snapshots unchanged.

## Task 2 — Package and Tool-Schema Contract

**Files:** new integration package/manifest generator and tests.

1. Use a local TypeScript extension loaded explicitly with `--extension <absolute extension.ts>`. Pi loads TypeScript with jiti; no global install or separate production compilation is required.
2. Pin the MCP SDK, current compatible `typebox`, TypeScript and Pi development/type dependencies in this package and commit the lockfile. Dependencies resolve from the package directory, not a presumed global npm layout. Define `npm test` using Node's built-in runner and a `typecheck` script.
3. Generate a checked-in manifest of exact public `deck_*` tool names/descriptions/input schemas from imported Python FastMCP definitions. Keep the fixed private lifecycle tool set separate and never model-visible. Generator and live `tools/list` checks assert public plus explicitly declared private tools, rejecting unexpected omissions/additions. Importing/generating must not start heartbeat, register an agent, contact Deck or invoke a tool. Generator `--check` fails on drift.
4. Check opt-in before factory tool registration or side-effecting listeners. Without opt-in, register nothing. When opted in, register manifest tools during factory evaluation but do not spawn a long-lived client/process there: transport starts at `session_start`; tools refuse until readiness completes.
5. Use a lossless JSON-schema adapter/type boundary accepted by installed Pi validation rather than reconstructing every schema in a bespoke TypeBox converter. All 25 current FastMCP schemas compiled in the first review. Test actual Pi validation, local `$defs`/references, required approval IDs, nullability, arrays and dictionaries; unsupported forms fail readiness rather than being dropped. Keep generated tool parity authoritative instead of hard-coding a tool count.
6. Preserve exact names so Deck's existing `deck_check_inbox` wake prompt remains valid. Expose the existing shim's full mail/team/approval/continuation surface, not a two-tool demo. Never expose a caller-selected MCP executable, server URL, operator token or identity override as a model tool.

**Tests:** schema/name parity against FastMCP; tool omission/addition/type mutation; required approval ID; null/record/list parameters; registration does not spawn; model tools cannot supply identity transport configuration.

## Task 3 — Session-Scoped MCP Transport and Tool Results

**Files:** extension/client modules, test fixtures; existing shim only where essential.

1. Use official SDK `Client` + `StdioClientTransport` to run the existing shim via a configured absolute backend Python executable and shim path, with `cwd=ctx.cwd`. Do not use a shell, intermediary detached process, or independent HTTP identity client.
2. Backend-managed launch provides non-secret `CLAUDE_DECK_MAIL_OPT_IN=1`, Deck URL, Python/shim paths, and team metadata when applicable. If opt-in is absent, return without connecting, registering tools into active model state, starting timers or injecting mail prompts—even when the file is loaded accidentally.
3. Pass a bounded environment to the child: required runtime variables, provider `pi-cli`, Deck URL and verified launch metadata. Audit the SDK's effective environment, including its default-variable merge, not only the supplied map. Exclude OpenRouter/operator/GitHub credentials from this shim child; Pi itself resolves its OpenRouter key. Explicitly suppress or safely drain child stderr, whose SDK default is inheritance; never expose raw transport payloads as debug logs.
4. On session start, create one transport and perform a harmless `deck_whoami` readiness handshake so the shim obtains its own server-derived capability token. Registration may initially return `409 bind_pending`, because Team spawn precedes the binding commit. In Pi mode, serialize registration/heartbeat startup and retry only `bind_pending` with a 250ms-to-1s bounded backoff and a 15s total startup deadline, one shim and one session key. Authority tools remain unavailable until successful authenticated registration. Other refusals fail immediately; timeout closes/fences the generation rather than waiting the existing 300s heartbeat backoff or spawning another child. Existing providers retain their current startup behavior. Test delayed commit, early refusal, commit failure, eventual success and deadline expiry. The shim owns heartbeat; do not create a second extension heartbeat/registration authority.
5. A transport generation belongs to one Pi session/cwd. On session switch/new/fork, close the old transport before creating a new one; never re-use a token/client from another project session. Automatic fork launch is unsupported, but interactive session navigation must still be safe.
6. Implement the mandatory terminal close and failed-close fence protocol below; an offline flag or child exit is not a terminal close. On reload/shutdown, stop new tools, stop/drain the shim heartbeat, authenticate self-close, then close/kill only the owned child with a bounded timeout. A replacement generation cannot activate on an unresolved close.
7. Backend outage does not restart the child in a loop or duplicate mail. Reuse the shim's retry/backoff; return the structured offline error. Reject malformed protocol results and unavailable transport safely.
8. Preserve Deck's semantic envelope/status/conflict code in model-facing text and structured data in Pi `details`; map supported text/image blocks and explicitly reject unsupported MCP content. Pi's returned `AgentToolResult` has no `isError` field: use a manifest-tool-scoped supported `tool_result` handler to set the final Pi error flag without losing content/details. Distinguish protocol `isError`, Deck `ok:false`, malformed results and outcome uncertainty. Test the final Pi event/message, not just the adapter object. Wire abort signals with bounded timeouts; cancellation does not roll back an already dispatched HTTP transaction. Conservatively mark transport failures, including shim `deck_unreachable`, from a dispatched mutating tool as `mutation_outcome_unknown`; preserve original conflict information when a definitive HTTP response exists. Reconcile with existing read-only tools or operator handling, never blind resubmission. Classify pre-send cancellation as not dispatched only when proven. Add an additive shim uncertainty indicator if needed; do not change continuation authorization. Cover commit-then-lost-response, read/write timeout and abort before/after dispatch, including shutdown during a pending call.
9. Do not put capability keys into Pi custom session entries. Verify Pi session-file privacy in rollout and document that ordinary owner-only tool transcripts may contain sensitive context.
10. Classify mutating tools by actual backend effects, never their names: `deck_get_work_item_context` claims continuation and `deck_check_inbox` changes receipts. Audit and explicitly declare read-only exceptions; unknown/new tools conservatively count as mutating for uncertain-outcome handling. Test these two misleadingly named writes and cancellation's final model-visible result.

**Tests:** actual fake stdio MCP server; call/result/error/timeout/abort; representative 403/409 conflicts; concurrent calls use one transport; navigation/reload/shutdown and forced-close cleanup; outage/backoff; no secret-bearing child env; no auto-retry of proposal/decision/ack after ambiguous transport outcome.

### Mandatory terminal close and failed-close fence

- Add nullable `MailAgentSession.closed_at` with an idempotent SQLite migration. An authenticated self-close endpoint derives the session from its own capability and atomically sets `closed_at`/offline. It closes only that row; retain the token hash solely to authenticate idempotent close replay. Use a dedicated close-only hash-auth dependency, not normal `require_mail_session`, whose freshness/offline rejection would prevent close replay. All other token consumers, registration/heartbeat, roster, reuse and wake selectors refuse/exclude closed rows. Registration cannot clear `closed_at`; every heartbeat writer uses a conditional write with `closed_at IS NULL`, not a check followed by an unconditional update. Closed session keys remain tombstones: refuse before member reassignment, pane rebinding, token minting or success, even with capability enforcement off. Do not delete/recreate closed keys to bypass this. Existing unclosed rows remain compatible.
- Add private MCP lifecycle tool `__deck_mail_close_generation` with an empty object schema and `additionalProperties:false`. The extension calls it directly on its owned MCP client; it never enters Pi tools/model descriptions. No target/session/PID/identity/token argument is accepted. The shim uses only its private state, latches closing, refuses new public calls/registration, bounds heartbeat drainage, then calls its own HTTP self-close. Only a backend-acknowledged committed close yields `{ok:true, closed:true}` over MCP. Repeated calls may replay that acknowledged result; no capability leaves the shim. Check public/private `tools/list` separation and manifest parity explicitly.
- Bound shutdown to 10s. Reject new tool dispatch, stop/drain heartbeat, request self-close, then stop the owned transport. Treat a lost close response as unresolved even if the server may have committed; never claim process exit proves closure. An in-flight authority call may complete remotely: mark its outcome unknown, do not replay it and do not block shutdown indefinitely waiting for it.
- Distinguish owned Pi/shim process identity from authoritative tmux pane identity; a surviving shell may be the pane while Pi is its child. Before registration, resolve the actual pane PID/start time using bounded local ancestry/tmux checks and exclusively create a pane-scoped private non-secret fence. Inability to resolve fails closed. The key is the pane PID/start time, not the replaceable Pi child's PID; record Pi PID/start time and generation inside it for owned-process handling. Use a validated user-owned runtime directory (0700 directory, 0600 file, no symlink following), never tokens or contents. Persistence spans reload/session/cwd changes and a new Pi child in the same shell pane. Local resolution/fence metadata is not backend authority: the server still derives binding independently from the kernel.
- Remove a fence only for the matching owned generation after the private close request's definitive `{ok:true, closed:true}` ACK, or proof that no registration request was dispatched. Correlate the ACK to the client/request/generation and compare generation before unlink: late callbacks must not remove a replacement fence. EOF, generic success, malformed ACK, timeout or a lost reply leaves it intact. An existing fence blocks tools and new registration; do not overwrite it, reuse its client or relax duplicate-row checks. Backend failure/forced kill blocks reload instead of admitting two bindings. Same-uid malicious fence tampering is outside this persistence mechanism's security claim.
- Recovery from an unresolved fence requires explicit authorization to stop the exact bound pane/process tree, not merely its Pi child when a shell survives. Add a narrow `require_operator` retirement endpoint: server must verify the snapshotted pane PID/start time is dead/replaced, fail closed on unobservable liveness, and conditionally terminal-close only matching rows. A still-live shell pane is refused even when its old Pi child died. Confirm retirement and pane death before explicit local cleanup removes only that exact fence. A new process in the same unresolved live pane cannot bypass the gate; a replacement pane identity is distinct. Lost acknowledgments intentionally require this recovery, not automatic takeover. Never stop unrelated panes or expose the operator secret to Pi/shim.
- Old already-running Claude/Codex shims do not gain new shutdown code when Deck is deployed. During migration, coordinate their quiescence, stop only explicitly authorized exact panes, positively verify death, then use the narrow retirement endpoint before replacement. Do not extract their capabilities or pretend an offline status is sufficient.
- Test real DB row counts and token behavior: delayed heartbeat versus close, repeated/lost close replies, outage, forced kill, old-token calls/re-registration, two rapid reloads, persisted fence after runtime replacement, operator retirement of dead versus live/unobservable panes and exact-row isolation. Test enforcement on/off with absent/wrong/old-correct tokens against closed keys, and every heartbeat writer. Cover direct Pi-as-pane, shell -> Pi -> shim, Pi-only restart under a surviving shell, numeric PID reuse with a different start time and unresolved ancestry. Test normal private close end-to-end, malformed/unknown ACK, late stale callback, public/private parity and capability confinement. At most one fresh authoritative binding can activate; an unresolved generation stays blocked.

## Task 4 — Launch Opt-In, Defaults and Team Readiness

**Files:** Bridge spawn/router, launch descriptors, Teams service, install service/schemas; relevant provider/spawn/Teams/install tests.

1. Pi descriptor advertises only platform `openrouter`, default OpenRouter, Kimi K3 example, verified thinking options, plain/resume and the honest capability matrix.
2. Keep existing generic `SpawnCommandOptions.platform` default behavior for old providers. At Bridge request and Team dictionary boundaries, explicitly supply Pi's `openrouter` default for omitted/empty/whitespace values; explicit JSON null is rejected with 422 at both boundaries, not converted to a default. Use request field-presence information so explicit `anthropic`/`bedrock` is rejected. In `_validate_slot_options`, separate generic platform validation from AWS-only presence: today's `_BEDROCK_LAUNCH_OPTION_KEYS` includes `platform` and wrongly rejects OpenRouter. Pi stays `supports_bedrock=False` and rejects all AWS-specific keys, even empty ones. Preserve other providers' existing behavior. Test create/update/plan/spawn across every presence/value case; direct builders receive the normalized platform.
3. Configure the extension and non-secret opt-in environment for Deck-managed Pi launches, including manually created Bridge sessions. A manual `pi` invocation outside Deck does not automatically opt in. Preserve Team env flags and server-written bindings; accommodate early `bind_pending` using Task 3's handshake rather than claiming an existing commit-before-registration ordering. Manual Bridge participation remains repo-level unless explicitly launched as a Team slot.
4. Add backward-compatible Pi readiness diagnostics: executable/version, local extension/shim/Python assets and dependencies. Initially support tested Pi 0.87.1 with Node >=22.19.0; other Pi versions fail readiness until separately validated, not silently accepted by a loose semver range. Verify actual no-session/no-network extension loading and dependency resolution against the launched CLI's jiti aliases, production install mode, and Python `mcp`/`httpx` imports; local dev typings are not proof of the global runtime's compatibility. Team readiness explicitly rejects missing integration instead of falling through `_agent_mail_ready_reason`; explicit Bridge creation uses the same gate. No Claude/Codex hooks or global MCP config required.
5. Missing/incompatible assets produce Team plan `block_code=agent_mail_not_configured` and launch `status=blocked_agent_mail_not_configured`, with equivalent safe Bridge validation. No automatic npm install or global config edits inside launch/GET status APIs; provide explicit deployment preparation commands.
6. Do not broaden allowed provider CLI commands to `pi auth print-api-key`, `print-bearer-token`, or `--credentials`. Any optional credential readiness check uses only `pi auth check --provider openrouter --model moonshotai/kimi-k3 --no-refresh` without credential output; never executes a model request.
7. Preserve old provider defaults and outputs; model/platform/thinking and extension readiness must agree across descriptor, API validation and Team plan-launch.
8. Pi automatic Team reuse is restricted to an already explicitly enrolled pane with a fresh authenticated registration and exact server-verified preset/slot/provider/PID binding. Disable name/repo fallback adoption for Pi. If no eligible enrolled pane exists, spawn a new Deck-owned pane or return a safe block; do not attach or mutate an unrelated session. Preserve existing providers' reuse behavior. Test manual same-repo Pi, matching display names, unbound Bridge Pi, stale/closed registrations and foreign-slot bindings: no member reassignment, binding insert, prompt or process termination. Explicit manual adoption is deferred.

**Tests:** provider-default presence matrix at all boundaries; Bridge and Team same argv/env; production runtime/version/load readiness; old providers unchanged; CLI secret-print rejection; no install in GET/launch; early refused registration followed by binding commit; Pi-only reuse isolation.

## Task 5 — Authenticated Identity, Wake Isolation and Lifecycle

**Files:** Agent Mail wake allowlist; auth/registry/peer/Teams/MCP tests.

1. Add `pi-cli` to eligible tmux providers only after the extension registration path exists. Do not weaken exactly-one observed pane + fresh authenticated MCP binding checks or use hook rows as wake authority.
2. Exercise real Pi -> shim -> loopback backend ancestry in disposable Linux fixtures. Assert the actual applicable resolver's bounds, separately from discovery and mail association; do not conflate the 4/8/32 limits or raise one based on an assumed process tree. Include at/over-bound and impostor cases.
3. Reuse `AgentPaneBinding` and authenticated server-derived slot identity. Negative cases include wrong provider/slot/preset/cwd, stale/PID-reused pane, no opt-in, unrelated manual Pi in another repo, multiple physical panes and duplicate fresh registrations.
4. Preserve empty-inbox refusal and the read-but-unacked continuation obligation exception. Test a properly bound Pi owner re-nudge and a distinct Pi Leader's pending request nudge, with exact pane-target auditing.
5. Isolated two-slot flow: owner creates approval/continuation request, distinct Leader decides, owner acknowledges, and cross-slot/old-session calls fail. Use synthetic workspaces/PR snapshots and fake GitHub clients, never Tizonia item23 or real GitHub.
6. The old shim from a Pi reload must no longer be fresh/wake-authoritative before a replacement becomes eligible. Test live row counts, not just a mocked `close()` callback.
7. Add synthetic provider-migration and rollback fixtures. Preserve preset/slot/member IDs and creation identity, owner slot, workspace path/token/acquisition, nonce/head/ref, revision/failed-head history, policy/holds and continuation state. Provider edits detach old sessions to repo membership: terminally retire their authority first and prove old tokens cannot act afterward. Permit only new session/binding rows and the documented owner claim's PID/start/contact/updated-at writes. Assert no release/reacquire, handoff, proposal, approval/ack, redispatch, retry or budget increment. Compare sensitive values privately; never emit them in snapshots or assertion messages.

**Mutation checks:** remove provider/PID/slot guard; count hook as MCP; bind arbitrary Node; duplicate close lost; global extension load; wrong-session transport reuse; collapse structured 409; suppress owner ack re-nudge.

## Task 6 — Bridge and Teams UI

**Files:** provider context/types, Team types/selectors, shared launch fields, install-status UI.

1. Add Pi to provider selection, persistence and Team slot editors; retain custom-model text input and show OpenRouter/Kimi K3 explicitly. Update `NewSessionDialog.tsx`'s request construction, not just rendered fields: send Pi prompt/model/thinking/resume and explicit OpenRouter. On a user provider switch, clear remembered Bedrock/AWS controls; preserve rejection of explicit invalid API payloads. Handle delayed descriptor loading without falling back to Anthropic. Shared launch-field defaults and remembered-platform logic must agree.
2. Shared launch fields must render model/thinking fields based on Pi's descriptor, not Claude/Codex-only conditionals. Display platform OpenRouter without Bedrock/AWS fields or API-key inputs.
3. Show extension readiness/unsupported surfaces clearly; do not label Pi as sandboxed or hide missing Agent Mail behind a green CLI-installed badge.
4. Session cards retain role/team identity and wake status. An unrelated manually launched Pi session may appear in Bridge but must remain unbound, not auto-enrolled into a team.
5. Preserve keyboard/accessibility patterns and use the installed React guidelines when implementing. Do not add a frontend test framework; build/typecheck and targeted manual UI checks are the existing validation contract.

**Verify:** frontend build; lint affected files against baseline; manual Pi selection, Bedrock-to-Pi switch, delayed descriptors, custom model, exact resume, invalid platform, unsupported controls, missing extension and unrelated-session wake refusal. Inspect outgoing request and resulting argv, not just visible fields. Do not claim manual checks completed without execution.

## Task 7 — Validation and Review Gate

Run commands from the isolated worktree. Use the existing live venv executable only as an interpreter, never its CWD/database or copied settings. Set test-local database/config explicitly; record environment-sensitive existing failures separately. Record measured counts, not estimates.

Authoring baseline: isolated `--collect-only` on the Agent Mail, Teams and SQLite migration suites collected **1,098 tests** at the pinned baseline, with `DATABASE_URL` directed to a disposable `/tmp` path. This is collection evidence, not a test-pass claim. Implementation must remeasure pass/fail counts after changes.

```text
cd /home/juan/work/repos/juanrubio/claude-deck-pi-provider/backend
/home/juan/work/repos/juanrubio/claude-deck/backend/venv/bin/pytest -q tests/test_providers.py tests/test_provider_contract_api.py tests/test_agent_bridge_spawn.py tests/agent_mail/test_install.py tests/agent_mail/test_peer_process.py tests/agent_mail/test_mcp_shim.py tests/agent_teams/test_agent_team_service.py
/home/juan/work/repos/juanrubio/claude-deck/backend/venv/bin/pytest -q tests/agent_mail tests/agent_teams tests/test_sqlite_compat_migrations.py
cd ../integrations/pi-agent-mail
npm ci
npm run typecheck
npm test
cd ../../frontend
npm ci
npm run build
cd ..
git diff --check
```

Also run terminal-close/auth/registry tests, new Pi backend tests, migration/rollback invariant fixtures, manifest `--check`, fixture tmux ancestry/cleanup tests and the broader suite when practical. Exercise final Pi tool-result events and installed-runtime extension load, including production dependency installation. The pre-existing #312 Agent Bridge smoke failure is report-don't-fix unless this PR actually changes its cause. No model-account credentials are needed for automated tests. The real authentication/model probe is separately operator-authorized deployment work, not a substitute for unit tests.

Commit focused implementation changes, push the feature branch and open one PR into the integration branch. Require an independent review of backend identity, extension lifecycle/tool semantics and UI before merge. Do not deploy or migrate automatically after the PR opens.

## Task 8 — Rollout and Migration Runbook (Write Only)

Create `docs/deploy/pi-provider-rollout.md`; do not execute it during implementation.

**Checkpoint P0:** Reviewed integration merge; autonomy off; backup DB via SQLite backup API, snapshot redacted attempt/lease identity and current launch config. Prepare local package dependencies and verify executable/shim paths, Pi version, OpenRouter credential readiness and sensitive file permissions without printing credentials. Define rollback to the previous deployed Deck SHA and slot configuration; no workspace reset/release.

**Checkpoint P1:** Disposable Pi fixture with explicit extension: harmless identity/mail tools, heartbeat, bound wake, structured errors, reload/resume/shutdown and no unrelated-session prompts. A separately approved minimal paid model/tool probe verifies actual Kimi tool calls. Stop for confirmation before any live team replacement.

**Checkpoint P2:** Operator-authorized live migration, autonomy off. Coordinate pauses, inspect work state and obtain explicit permission to replace both exact old panes; never kill an owner merely for being slow. Old running shims lack the new lifecycle: stop the authorized panes, verify death, then terminally retire their exact registrations with the operator dead-pane endpoint. Do not copy old capabilities. Update existing slots 4 and 6 to Pi/OpenRouter/Kimi K3, retaining preset/slot/member IDs and creation identity/charter/labels. Provider edits detach old sessions; prove retired tokens cannot act afterward. No new team, owner reassignment or handoff.

Use separate plan/launch API calls for the two slots, with `reuse_existing=false` and a freshly reviewed plan hash for each. Leader slot 4 launches in its ordinary repository checkout. Owner slot 6 launches using `repo_path_override` equal to the preserved leased worktree path. That override applies to an entire launch request, so never combine these launches or give the Leader the owner's override. The runbook must spell out both payloads against the implemented API schema, expected paths and before/after identity assertions; placeholders must be resolved from read-only state before operator confirmation. No retry/redispatch shortcut. Preserve checkout/lease/acquisition/item/nonce/head/ref/budgets; only new session/binding rows are expected so far.

**Checkpoint P2a:** Separately authorized owner re-entry: the new Specialist calls `deck_get_work_item_context` for the preserved work item. This is an authenticated claim-continuation write, not read-only preflight or an extension/coordinator startup action. Verify only the documented leased-owner PID/start-time, contact and updated-at evidence changed; preserve acquisition/token and all attempt authority. Stop if any other field changes.

**Checkpoint P3:** Re-entry preflight with continuation already on: exact one observed pane and fresh bound MCP registration per slot, unique wakeable Bridge targets, stable lease/attempt identity, no pending proposal, human merge, recovery-only selector matched and autonomy off. Treat the standard fresh-rollout script's continuation-off requirement as inapplicable; perform equivalent read-only re-entry checks, not a policy toggle. Stop and report identity matrix before any proposal or autonomy change.

**Checkpoint P4:** Resume the existing soak runbook at the next implementation proposal. The owner independently creates a held proposal for merged Tizonia commit `1e384079799775189565fb888bb13e89664738bf`, exactly the two authorized scheduler/test-component paths. Revision cap 11 has ten persisted revisions and six failed heads of eight; do not silently increase it. Distinct Leader review/decision and separate operator decision/ack hold releases remain mandatory. No coordinator cherry-pick or status report on behalf of the owner. Hosted product CI must pass before human merge of PR #875; no local Tizonia build or diagnostic rewrite. Stop at every existing checkpoint.

**Rollback:** Keep autonomy off. Stop only the new Pi sessions under explicit authorization, close their registrations, restore old provider configuration/deployment and start new authenticated old-provider sessions through Deck. Never reuse capability tokens, reset the preserved workspace, alter revision history or claim that rollback authorizes another proposal. Record any live revision/pending approval and stop for its separate disposition.

## Completion Criteria

1. First-class Pi launch/API/UI selection is consistent and has no credential-bearing argv/options.
2. Opted-in Pi exposes the actual Deck approval/continuation tools; unrelated Pi sessions receive no mail prompts.
3. Authenticated pane/slot identity and distinct Leader/owner actions work in disposable fixtures without broader trust.
4. Idle heartbeat, session navigation/reload/shutdown, transport outages and ambiguous authority outcomes are bounded and tested.
5. Install/readiness checks block incomplete integration without modifying global Pi configuration.
6. Existing provider contracts and frontend build pass; independent review is complete.
7. Live migration and soak are explicitly separate, operator-gated work, not asserted as implementation validation.
