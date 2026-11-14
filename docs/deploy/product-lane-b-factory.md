# Product Lane B factory operation

Prepared 2026-10-02. The operator explicitly authorized completing prerequisites and enabling Lane B while absent. Lane A remains untouched. This authorization does not replace the pilot, promotion, or human merge gates.

## Destination and runtime

- Repository: `juanrubio/claude-deck`; tracker #3. Fork issues #4–#14 map to upstream #410–#417 and #364–#366.
- Implementation PR base: `feature/software-delivery-product-reposition`. Never auto-promote to master.
- Pinned controller: `ac9252242fcf436c3ea9997add5d32416cad2cd1`, `/opt/claude-deck-product/controller`.
- Local UI/API: `http://127.0.0.1:8011`. Dedicated database under `/home/deckproductctl/.local/state/claude-deck-product/`.
- Controller OS user: `deckproductctl`; agent user: `deckproduct`. Neither has general sudo. Root owns controller code and operator helpers.
- Isolated agent session server: `claude-deck-product-tmux.service`, socket under the agent home. Controller restart preserves this server and its agents.
- Four separate working directories under `/home/deckproductctl/work/`: coordination, backend, frontend, validation. Dispatch pool: dispatch-1.
- Leader/backend/frontend: Codex GPT-6.1 Sol (medium/high/high). Validator: Codex GPT-6 Astra high.
- Single scope and active dispatch; human merge; finite approval/verification rounds. Do not increase concurrency until the first complete cycle is accepted.
- Shared exclusive heavy-operation lock through `product-heavy`. Initial Codex workspace-write restrictions were replaced by the explicit temporary bypass decision below; no Tizonia credentials are copied.

The controller needs `CAP_SYS_PTRACE` and `CAP_DAC_READ_SEARCH` to resolve sockets and verify peers across the two dedicated UIDs. These permit privileged inspection; agents do not receive them. The GitHub credential is the operator-authorized existing juanrubio login, with its existing account permissions, stored privately in this factory. It is not a narrowly scoped GitHub App installation.

## Commands

```sh
sudo /opt/claude-deck-product/bin/productctl status
sudo /opt/claude-deck-product/bin/productctl plan
sudo /opt/claude-deck-product/bin/productctl pause
systemctl status claude-deck-product-supervisor.timer
```

Root state/manifest: `/opt/claude-deck-product/state/`. Shared dependency ledger: `/home/deckproductctl/work/operations/queue.json`. Original dirty packet is preserved in a private snapshot; the bootstrap packet is PR #15. Its acceptance and baseline evidence precede the ready-label queue. Absent `operations/HOLD.json` means no hold.

The scripts and unit files beside this document are the installed operational source, not an unattended installer. Never check in `.env`, auth files, capability tokens, or private logs. Controller upgrades are a separate operation.

## GitHub credential handling

`productctl configure-ambient-github --confirm` runs as root and copies the operator's own `gh` login token into two places: the controller `backend/.env` (`GITHUB_TOKEN`, read by the controller service), and `gh`'s `hosts.yml` for `deckproduct` and `deckproductctl`, so that `gh` and `git` authenticate for them.

**Decision (issue #861).** Keep `gh`'s `hosts.yml` as the credential store and write both files safely. **Both files still contain the token in plain text.** This change does not remove plain text, and it does not by itself clear CodeQL alerts #164 (the `.env` write) or #165 (the `hosts.yml` write). Moving a write into a child process changes who writes the file, not what the analyzer sees or what the file holds. Accepting the remaining risk, the disposition of both alerts and the live verification below belong to the Supervisor and the operator, and the issue's acceptance items stay open until they have done them.

**Why the token stays in files.** Whatever credential lets `deckproduct` run `gh` and `git` is readable by `deckproduct`. `gh`'s keyring store needs a desktop secret service that these headless hosts do not run, and it falls back to the same file. A credential helper runs as the calling user and has to print the token to it. systemd credentials could protect the controller's copy but not the agents' copy. Only a root-run broker that performs the `git` and GitHub operations for the agents would keep the token away from them. That is a separate design, and it is not part of this change.

**Trust boundaries.**

- The token has the permissions of the operator's own login (the `--confirm` choice). Rotating it or using another account is out of scope here.
- Anyone who can run commands as `deckproduct` or `deckproductctl` can read the token. The harness policy below runs the agents with their sandbox bypassed, so a compromised or misled agent can take it.
- Other local accounts cannot read it. The controller `.env` is root-controlled. Each agent's `hosts.yml` is private to that agent user.

**What the script does now.**

- The agent files are written by a child that runs as the agent user (`sudo -H -u`), with the token on standard input only (never in arguments or the environment). Root no longer creates, writes or `chown`s anything inside an agent's home directory. Before this change root did, and those operations follow symlinks, so an agent could have planted a link to make root write or change ownership elsewhere.
- The child refuses a symlinked `gh` directory, sets the directory to `0700` first, writes a new `0600` file with `O_EXCL` and renames it over `hosts.yml`. An existing file, including a world-readable one, or a planted link is replaced and never receives the token.
- The controller `.env` is replaced the same way: a `0600` temporary file beside it, owned like the original before any token byte is written, then an atomic replace. A failure leaves the original untouched, and a symlinked `.env` is refused.
- The file contents, the account and the authentication behavior are unchanged.

**Operator checks after installing the script (the agents do not run these).** Run each as root, for both `deckproduct` and `deckproductctl`. None of them prints the token.

1. `sudo -H -u <user> gh auth status` reports the `juanrubio` login.
2. `sudo -H -u <user> git ls-remote <repository URL> HEAD` succeeds.
3. `stat -c '%U:%G %a %n' ~<user>/.config/gh ~<user>/.config/gh/hosts.yml` shows the user as owner, `700` and `600`. `stat -c '%U:%G %a %n' /opt/albiex-synth-city-product/controller/backend/.env` shows `600` and the owner and group that existed before.

**Proposed reasoning if the Supervisor accepts the risk (no alert has been dismissed).**

- Alert #164, `.env`: the controller service reads `GITHUB_TOKEN` from this file, so the value must be there. The file is root-controlled, replaced atomically with mode `0600` and its original owner and group, and the write refuses a symlink.
- Alert #165, `hosts.yml`: `gh` and `git` need a usable credential for the agent user, and `gh`'s own file is the supported store. The child writer creates it `0600` as that user, in a `0700` directory, without following links. The remaining exposure is that a process running as that user can read it, which the trust boundaries above record.

## Supervision

The root-owned supervisor timer reads only this factory's exact roster panes and dedicated Codex logs every 10 seconds. Recognized cybersecurity notices pause autonomy, write private and shared redacted HOLD records, and suspend the exact pane processes and descendants using SIGSTOP. PID/start-time evidence is retained; leases and approvals remain intact. Controller loss after arming and unavailable bindings also stop intake.

A hold is latched and cannot auto-resume. Await the operator's instructions; do not retry/rephrase, switch models, release leases, or replace Codex with Pi/OpenRouter automatically. Restoring execution requires explicit operator direction, reconciled authority and PID/start-time checks. This detector recognizes known notices; it cannot prove false positives or detect every silent interruption. The persistent timer provides supervision after the preparing chat ends, without claiming that a chat agent remains continuously present.

## Remaining human checkpoints

Human merge stays enabled. Autonomous workers can implement, review and open integration PRs; completed PRs can wait for the operator's return. Pilot task observations and the proceed/reduce/defer decision must be real operator evidence. Promotion and deployment remain separate decisions. Do not invent these prerequisites to keep work moving.

## Temporary harness policy — operator decision, 2026-10-02

The operator explicitly selected `--dangerously-bypass-approvals-and-sandbox` for all four Lane B Codex harnesses and deferred additional confinement. This supersedes the initial workspace-write configuration and its writable-root restrictions. The flag is limited to the dedicated product roster; it is not a global Codex default or a Tizonia roster change.

Root paused intake, obtained normal owner API release of the clean blocked workspace, preserved the conversations, retired old pane bindings, and relaunched distinct resume IDs with the explicit bypass launch option. Actual process arguments must confirm the flag and fresh authenticated wakeable bindings before intake resumes. Existing shared Git branch references remain preserved; reconcile current checkout and fresh dispatch authority instead of carrying forward approval from an earlier attempt.

The existing dedicated OS users, filesystem ownership, pinned controller, protected operator credentials and isolated tmux socket remain. No container, VM, systemd filesystem confinement or additional network boundary was introduced. Agents retain access permitted to their OS account, including the product GitHub login's existing account permissions.

Deck's distinct Leader plan approval, independent exact-head review, human merge, single dispatch and finite budgets remain in effect. The cybersecurity supervisor remains active. This flag does not disable model cybersecurity checks: a recognized notice still pauses/freeze-holds the lane and requires operator instructions. No automatic retries/rephrasing, Pi/OpenRouter switch or safety-hold clearing is authorized.
