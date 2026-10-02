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
- Shared exclusive heavy-operation lock through `product-heavy`. Agent sandbox permits its checkout and the operations ledger; no Tizonia credentials are copied.

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

## Supervision

The root-owned supervisor timer reads only this factory's exact roster panes and dedicated Codex logs every 10 seconds. Recognized cybersecurity notices pause autonomy, write private and shared redacted HOLD records, and suspend the exact pane processes and descendants using SIGSTOP. PID/start-time evidence is retained; leases and approvals remain intact. Controller loss after arming and unavailable bindings also stop intake.

A hold is latched and cannot auto-resume. Await the operator's instructions; do not retry/rephrase, switch models, release leases, or replace Codex with Pi/OpenRouter automatically. Restoring execution requires explicit operator direction, reconciled authority and PID/start-time checks. This detector recognizes known notices; it cannot prove false positives or detect every silent interruption. The persistent timer provides supervision after the preparing chat ends, without claiming that a chat agent remains continuously present.

## Remaining human checkpoints

Human merge stays enabled. Autonomous workers can implement, review and open integration PRs; completed PRs can wait for the operator's return. Pilot task observations and the proceed/reduce/defer decision must be real operator evidence. Promotion and deployment remain separate decisions. Do not invent these prerequisites to keep work moving.
