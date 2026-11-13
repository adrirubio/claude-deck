# Agent Bridge

Agent Bridge discovers and manages local agent CLIs running inside tmux. It supports mixed Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode CLI, and Pi sessions in the same view.

## Overview

The bridge performs a provider-aware tmux discovery pass and classifies each matching pane as `claude-code`, `codex-cli`, `copilot-cli`, `opencode-cli`, or `pi-cli`. The UI can show all sessions together or filter to one provider.

Session cards include:

- Provider badge
- tmux target
- Current working directory
- Live preview
- Attach, fullscreen, and kill controls

Agent Bridge also projects redacted Agent Mail state for each discovered pane: its matched member and repository, whether wake participation is enabled, and a wake state/reason. The state distinguishes wakeable, opted-out, stale, ambiguous, and unbound panes. A wake target is shown only after Agent Mail confirms that the pane has one fresh authenticated MCP binding and is actually wakeable. This projection is read-only; listing sessions does not synchronize observations or trigger a wake. Manual sessions are opted out by default, and only an operator can change participation through the Agent Mail API.

The terminal grid is shared across providers. Read-only and interactive modes work the same way whether the pane is Claude Code, Codex, or Copilot.

Provider filters are explicit:

- **All agents** — mixed Claude Code, Codex, Copilot, OpenCode, and Pi sessions
- **Claude Code** — Claude Code panes only
- **Codex** — Codex panes only
- **Copilot** — GitHub Copilot CLI panes only
- **OpenCode** — OpenCode CLI panes only
- **Pi** — Pi panes only

When Agent Team sessions are running, Agent Bridge also shows a team filter row. Team filters compose with provider filters, so selecting a team and a provider shows only matching session cards. Selecting a specific team also detaches any open terminal panes that do not belong to that team; it does not auto-attach that team's sessions or kill any tmux sessions. New sessions launched from Agent Bridge remain standalone and are not attached while a specific team filter is active.

With a specific team selected, the **Team lanes** action opens a fullscreen vertical-lane layout for that team. Lane mode shows up to four live team sessions side by side, ordered by configured team slot position, without changing the normal grid attachments. Press `Esc` or the exit button to return to the previous grid; if more than four members are live, Agent Bridge shows how many are not displayed.

## Live sessions in Work context

Work can open read-only session context. A terminal is selected only after a unique current team/slot/member/MCP-session match; ambiguous, offline or failed observations show filtered candidates without selecting a terminal. Navigation sends no input, launches nothing and claims no work. The contextual terminal is locked read-only.

Open manual Live sessions separately for standalone launch and explicit interactive controls. An offline actor's Teams link requires a current authenticated slot launch-plan review; it is not an automatic restart. Session controls, operator protection and provider-specific constraints are separate from factory observation. Native activity is not proof of progress on a particular issue.

See [Work](/features/work) and [Teams](/features/agent-teams).

## Keyboard Controls

Each terminal bar includes a keyboard shortcut chip. Click it to open the in-app shortcut reference; the dialog is available in the normal grid, single fullscreen, and team-lanes layouts.

When a bridge terminal is focused, press `Ctrl+Space` to arm the Agent Bridge leader. The hint overlay lists the available follow-up keys:

- `←` / `→` — focus the previous or next displayed pane, wrapping in on-screen order.
- `1`-`4` — jump to displayed pane 1-4; out-of-range numbers do nothing.
- `r` — toggle the focused pane between read-only and interactive mode.
- `Esc` — cancel the leader.

The displayed order is the grid attachment order, the team-lane slot order, or the single fullscreen pane. If the next key is not a shortcut, Agent Bridge forwards the `Ctrl+Space` terminal input and the following key in interactive mode; read-only panes intentionally drop input. Some OS or input-method configurations reserve `Ctrl+Space` before it reaches the browser.

## New Sessions

The new session dialog starts with a provider choice.

Claude Code keeps the existing session modes:

- Plain session
- Worktree session
- Resume session

Codex CLI supports:

- New session with `codex --cd <directory>`
- Resume by session id or `--last`
- Fork by session id or `--last`
- Model and profile selectors with custom-value fallback
- Optional sandbox, approval policy, web search, and prompt seed

Dangerous Codex bypass mode is exposed as an explicit advanced option because it disables approval and sandbox protections.

GitHub Copilot CLI supports:

- New sessions with `copilot -C <directory>`
- Resume by session id or `--continue`
- Optional model, custom agent, context tier, reasoning effort, plan mode, remote control, prompt seed, and explicit permissive launch flags

Claude Code and Codex support a launch-time platform choice:

- Claude Code: Anthropic or Amazon Bedrock
- Codex CLI: OpenAI or Amazon Bedrock

For Codex Bedrock sessions, Albiex Synth City passes a per-session Codex config override for `model_provider = "amazon-bedrock"`. Optional AWS region and profile values are passed as process environment variables. Synth City does not collect AWS secret keys or Bedrock bearer tokens; Codex resolves credentials from the existing shell environment or AWS SDK credential chain.

## Terminals when agents run as another user

Albiex Synth City can run its controller and the agents as different OS users. Then `tmux` is a wrapper that starts tmux as the agent user, for example with `sudo`. Terminal lanes in Team lanes and Live sessions attach through that wrapper.

### What the relay does

- **Resize.** The relay makes its terminal the controlling terminal of the attach process. When the browser terminal changes size, including full screen and back, the kernel tells the attach process the new size. The relay sends no signal to the attach process.
- **Errors.** What the attach process or the wrapper writes to stderr goes to the backend log, up to a fixed size. It does not go into the terminal and it does not go to the browser. A failed resize is logged once for each terminal connection.
- **A failed attach.** If the attach process ends with a failure before it showed anything, the lane shows one fixed message and the connection closes. The cause is in the backend log. When `sudo` reported that it could not allocate its own pty, the message names the setup rule: "Could not attach to the terminal: sudo needs `!use_pty` for the agent tmux command. See the setup docs and the backend log." Every other failure, and an attach program that cannot be started, shows "Could not attach to the terminal. See the backend log." Neither message contains text from `sudo`.

### What you must set up: a command-scoped `!use_pty`

The attach command must run without a second pty. In the `sudoers` file, turn `use_pty` off for the agent `tmux` command only, and leave it on for everything else:

```
Defaults!<the agent tmux command> !use_pty
```

Use the full path of the command that the controller runs through `sudo`. Do not turn `use_pty` off for all commands. Albiex Synth City does not change `sudoers`. The operator does.

Why. The relay terminal is the controlling terminal of the attach process. With `use_pty`, `sudo` then allocates its own pty and must hand it to the agent user, which needs the `CAP_CHOWN` capability. A service that runs with a limited capability set, as the product factory does (no `CAP_CHOWN` and no `CAP_KILL`), cannot do that. `sudo` stops with `unable to allocate pty: Operation not permitted`, and the lane shows the message that names `!use_pty`. Without `use_pty` there is no second pty. The command runs on the relay terminal directly, and the kernel resize reaches it without a signal that `sudo` would have to relay.

### What is verified and what is not

| Check | State |
|---|---|
| Real cross-user trial of the first version of this change under the production capability limits, with `use_pty` left on | **Failed.** The lane did not attach: `sudo: unable to allocate pty: Operation not permitted`. The original bug (no resize, and a `sudo: kill(...): Operation not permitted` error in the lane) reproduced on the version before the change. Without the limits, or with `CAP_CHOWN` added, the change resized correctly. |
| The relay code of this change with `!use_pty` for the attach command, under the production capability limits | **Verified** by the Supervisor's production-capability trial 2 on the parent head `3e15ff09`, in an isolated run with the production capability limits (`setpriv`), a copied wrapper and a temporary command-scoped `!use_pty` rule. The lane resized 83x31, 157x45, 83x31 twice, with no `sudo` text in the lane. In the same run, with `use_pty` left on, the lane did not attach (`sudo` could not allocate its pty), and the version before the change with `!use_pty` failed (`SIGWINCH` not permitted, shown in the lane). So production needs the code change and the `!use_pty` rule. The trial ran on the parent head; the relay code of this change differs from it only by the message text above. |
| Same user: a real child on a real pty gets every size change, including full screen and back | Verified by automated tests. |
| A failed attach shows a fixed message (the one that names `!use_pty` when `sudo` could not allocate its pty, the generic one otherwise), with no raw `sudo` or exception text in the lane or the browser | Verified by automated tests with a stand-in attach program. |
| An automated test with real `sudo`, a disposable agent user and the production capability limits, on a GitHub-hosted runner | **Not part of this change, and not passing.** It was moved to follow-up issue #880. On the hosted runner (`sudo-rs`, not the `sudo` of production) it failed in its first phase for a reason that is not yet explained. It never reached the `!use_pty` phase there. It does not replace the real cross-user trial. |

The production behavior rests on that trial. The operator deploys the `sudoers` rule.

### Checking a setup

Run this only in an isolated environment that you can throw away, never on a live installation. It starts a command with the same capability limits as the product factory service:

```
setpriv --bounding-set=-all,+dac_override,+dac_read_search,+setgid,+setuid,+sys_ptrace \
  --reuid=<controller uid> --regid=<controller gid> --init-groups <command>
```

Attach through the wrapper with a private `tmux` socket, change the size of the terminal (full screen and back), and check two things: the size follows, and no `sudo:` text appears in the lane. A failed attach shows the fixed message, and the cause is in the backend log.

## Compatibility

The frontend route `/agent-bridge` is the primary route. `/cc-bridge` remains as a compatibility alias.

The backend keeps `/api/v1/cc-bridge/*` for existing callers and adds `/api/v1/agent-bridge/*` for provider-aware clients.

## Smoke Coverage

Multi-provider smoke checks should cover mixed discovery, provider filters, attach/read-only/interactive terminal behavior, Codex spawn/resume/fork options, and the legacy `/cc-bridge` compatibility route. Native pages mount only for a checked-in adapter whose catalog access permits them; see [Harnesses](/features/harnesses). Codex has configuration, MCP, plugin and read-only Plans adapters; Claude-only transcript, usage, context, permission, hook, agent, skill, and memory pages stay unavailable for Codex. The saved native harness preference does not filter factory work.
