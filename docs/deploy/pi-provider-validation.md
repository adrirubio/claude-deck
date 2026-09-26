# Pi Provider Implementation Validation

Issue #357. Baseline: `2a51da44b634319644b4147b65764bdb7311936a`. Implementation branch: `feature/pi-provider`; target: `feature/autonomous-github-dispatch`, never master. Executed on 2026-09-26 in `/home/juan/work/repos/juanrubio/claude-deck-pi-provider`.

## Automated Results

| Check | Result |
| --- | --- |
| Agent Mail, Teams, SQLite compatibility, Pi provider and actual Pi ancestry suites | 1,178 passed in 112.71s |
| Full backend suite | 1,347 passed; one pre-existing #312 failure in `test_agent_bridge_session_filter_smoke` |
| Integration TypeScript typecheck | Passed |
| Integration Node/SDK/Pi runtime suite | 21 passed |
| Generated public/private MCP manifest `--check` | Passed |
| Frontend `tsc -b && vite build` | Passed; existing bundle-size warning |
| Affected TSX lint, baseline versus implementation | Both one error and six warnings; no count increase |
| Production-only `npm ci --omit=dev --ignore-scripts` and installed Pi loader readiness | Passed; runtime dependency audit reports zero vulnerabilities |
| `git diff --check` | Passed |

Backend execution used the existing venv executable with the isolated worktree as CWD and explicit disposable database URLs. No live database/settings were copied. The provider-registry smoke test's expected count was updated from four to five; the unrelated async Bridge smoke failure was not changed.

The actual Pi CLI fixture ran `--mode rpc --no-session --no-extensions --no-skills` with the explicit Deck extension, isolated HOME/runtime storage and its own disposable tmux socket. It used a fixture HTTP backend, not Deck's live server. Kernel socket ancestry resolved the same pane across close-and-new-session replacement; close was authenticated and each generation registered a different key. No model request or account credential was used.

Additional fixtures exercise terminal close/replay, old-token rejection, retirement-versus-admission serialization on separate file-backed SQLite connections, custom/shared session directories, unrelated manual Pi refusal, a distinct Pi Leader's approval decision, owner acknowledgement, exact audited pane wakes after a delivery was read but not acknowledged, and migration/rollback with pending holds and failed-head history. Sensitive preserved-state snapshots are compared as hashes. Owner claim changes only permitted workspace liveness/contact fields; ordinary provider edits also update preset/slot modification timestamps.

Pi's pinned loader and TypeBox validator compile all public schemas. Tests exercise required authority IDs, null/dictionary/list values and nested definitions. The actual Pi `ExtensionRunner` and `AgentSession` tool hook preserve native error semantics. SDK fixtures cover definitive conflicts, cancellation, malformed/protocol results, uncertain mutations without replay, and lost/errored close ACKs that retain the pane fence.

## Browser Fixture

Used a separate browser session against a static production frontend and a fixture-only HTTP server on an ephemeral loopback port. Every API request stayed on that fixture; spawn POSTs were recorded and refused deliberately. The fixture server and browser were stopped afterward.

Verified Bridge Pi selection after entering a synthetic Claude Bedrock profile, delayed launch descriptors, disappearance of AWS/permission/fork controls, the OpenRouter/Kimi/extension warning, model and thinking inputs, and plain/resume request serialization. Recorded requests contained `provider=pi-cli`, `platform=openrouter`, literal model/prompt/thinking values and the exact resume ID; no AWS fields survived. Backend fixtures independently verify invalid-platform and missing-readiness refusal. Team slot editing has API regression coverage and source review; a live Team editor/paid-model smoke remains a rollout check, not a claimed implementation test.

## Independent Review

GPT-6 Astra inspected the implementation read-only. Its initial report identified four implementation findings: private lifecycle tool exposure to other providers, missing protocol-result uncertainty, an incomplete total startup deadline, and custom Pi session-directory mismatch. All were corrected, along with errored-close-ACK and generation-swap checks. The targeted re-review identified no remaining blocker. Review artifacts are `/tmp/pi-provider-implementation-astra-review.md` and `/tmp/pi-provider-implementation-astra-rereview.md`; this document preserves the disposition and execution evidence without implying that the reviewer independently ran the suites.

The HTTP deadline cannot revoke a server transaction already admitted. Timeout means unknown outcome, not non-commit; the client does not replay it and retains its fence without a committed close ACK.

## Not Executed or Authorized

No live deployment, database migration, team replacement, Agent Mail reply/approval/claim, Tizonia write/build, policy change, autonomy enablement or soak resumption occurred. The coordinator's existing inbox was checked; no pending request or handoff required a reply. No OpenRouter authentication/paid model probe was performed. Follow the separately gated rollout runbook only after PR review/merge and explicit operator authorization.
