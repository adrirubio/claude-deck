# Isolated runtime kit

The isolated runtime kit starts, proves and tears down one isolated runtime for a provider live check. A harness issue uses it instead of designing its own environment. Every check runs the CLI under test against a local stub model, inside its own network namespace, with Synth City's normal team launch and Agent Mail registration.

```bash
scripts/isolated-runtime-kit.sh up     --root /tmp/kit --provider claude-code --cli /path/to/cli
scripts/isolated-runtime-kit.sh status --root /tmp/kit
scripts/isolated-runtime-kit.sh exec   --root /tmp/kit [--timeout 120] -- COMMAND...
scripts/isolated-runtime-kit.sh down   --root /tmp/kit [--keep]
```

## What `up` starts

- **Two namespace anchors.** The outer anchor runs `unshare --user --map-root-user --net`. It brings up `lo`, which must be the only network link, so nothing inside the kit can reach another host or another Synth City. The inner anchor maps back to the caller's uid and gid. Both start from an empty environment, so no token, socket or identity of the caller's session reaches the namespaces.
- **An isolated Synth City backend.** It has its own root, HOME, SQLite database and private tmux socket, a synthetic operator token, and an allowlisted environment. It doesn't build or serve the UI.
- **A stub model provider** (`scripts/runtime-kit/stub_provider.py`) on `127.0.0.1`. It answers the OpenAI-compatible chat API with a fixed reply, and its log keeps a hash of each request, never prompt text.
- **The CLI under test.** It's installed under its provider's binary name, for example `claude` for `claude-code`. Every other harness name resolves to a fake, so no host CLI can start, and `gh` is disabled. The kit then installs Agent Mail for the provider, creates a team preset with one slot and launches it through the normal launch API. That writes the real pane binding; the CLI then registers from its pane through the normal Agent Mail endpoint.

`up` prints one JSON line: the namespace, the links, the uid, the pane, the registration and binding read from the kit's database, the stub request count, and the kit's process ids. It never prints a token.

## Commands

| Command | Deadline | What it does |
|---|---|---|
| `up` | 90 s (`RUNTIME_KIT_UP_DEADLINE`) | Preflight (10 s), stub (5 s), backend health (30 s), launch and registration (30 s). A failure stops every process and keeps the root for its logs. |
| `status` | 15 s | Checks the instance, every recorded process, the backend's health and the registration before it writes anything. It then builds the evidence and the summary in a new attempt directory and publishes them; see [Evidence](#evidence) for the commit point and exit codes. |
| `exec` | 120 s by default, at most 600 s | Runs a command inside the namespaces with the kit's environment. |
| `down` | 30 s | Stops every process of the instance, including ones started later inside its namespace, proves none remains, checks the evidence manifest, and removes the root (`--keep` keeps it). If it can't prove cleanup, it fails as incomplete and keeps the root. |

**Exit codes:** 0 means success, 1 a failure, a deadline or an incomplete proof, and 2 a refusal.

## Ownership and cleanup

Each `up` creates one instance with a random id. `state/instance.json` (a private file) records that id, the root directory's identity and the kit's namespaces. `status`, `exec` and `down` refuse (exit 2) before any signal, write or deletion when:
- the record is missing or malformed, or isn't a private file of the caller;
- it was copied from another root;
- it names a host namespace.

**Ownership comes only from records.** The kit records every process it starts with its pid, start time, a SHA-256 of its command line, and its parent's pid and start time. Each process has one expected parent:
- the launcher is the parent of the outer anchor;
- the outer anchor is the parent of the inner anchor;
- the inner anchor is the parent of the tmux server, the stub and the backend (it starts them itself);
- the tmux server is the parent of the CLI pane.

A process counts as the kit's only when every recorded field matches and its parent is the recorded process of its expected parent role. It must also be in the kit's recorded namespaces. Before those are recorded, only the anchors may exist, and only in their own non-host namespaces. A process in a host namespace never counts. When a process re-executes, only its recorded command line may change.

**Signals.** Every signal opens a pidfd first, proves the full recorded identity, and then signals through that pidfd. Without pidfd support, or on any mismatch, nothing is signalled. The launcher is never signalled; it exits with the outer anchor.

**`down`** first computes a read-only plan. It refuses before any signal, keeping the root and the anchors, if any recorded process fails its proof, or if any unrecorded or unreadable process is in the kit's network namespace. Otherwise it stops the CLI, the stub, the backend, the tmux server, the inner anchor and the outer anchor, in that order.

**A root is never reused.** A root left by `down --keep` or by a failed `up` is refused by the next `up`; run `down` to remove it.

## Evidence

`status` publishes these files in `ROOT/evidence/` (a link to the latest complete attempt in `ROOT/evidence.d/`), with `MANIFEST.sha256`:
- `namespaces.json`
- `links.txt`
- `processes.txt`
- `pane.json`
- `registration.json`
- `environment-names.json`, holding variable names only, never values
- `stub-requests.jsonl`
- `summary.json`

`down` refuses to finish if the manifest no longer matches.

**Publication.** `status` builds each attempt in a new `evidence.d/<16 hex>` directory and then replaces the `ROOT/evidence` link with one atomic rename. That rename is the commit point.
- **Before the commit point,** a failure removes only this run's own attempt directory and temporary link, after checking that each is its own direct, non-symlink entry. The published link and every earlier attempt stay unchanged; `status` exits 1 ("incomplete … the published evidence is unchanged").
- **After the commit point,** the new evidence is published and stays published. `status` then prints the summary. If printing fails, it exits 1 with "published, but the summary could not be printed". Exit 0 means published and printed.
- **Earlier attempts are kept.** `status` never deletes them and never follows a link to delete anything; `down` removes them with the whole root.
- `status` refuses (exit 2), writing nothing, if `evidence.d` or an attempt is a symlink or isn't a direct child of the root.

## Safety rules

The kit refuses, with exit 2, when:
- `SYNTH_CITY_URL` or a Synth City Mail credential variable is set;
- the root is not empty and has no `.deck-runtime-kit` marker;
- the root path is longer than 96 bytes, because the tmux socket path must fit in 108;
- no real tmux executable is found (a launcher script is not accepted);
- the network namespace has any link other than `lo`;
- the inner namespace doesn't map to the caller's uid and gid;
- the two-step namespace entry doesn't land in the anchors' namespaces;
- a recorded process id now has another start time, so it may belong to another process.

**Namespace entry is two-step.** The kit enters through the outer anchor, which owns the network namespace, and then the inner one. A single `nsenter` into the inner anchor is refused by the kernel. Before it enters a namespace, the kit proves both anchors as described in [Ownership and cleanup](#ownership-and-cleanup).

## OpenCode members

For `--provider opencode-cli`, `up` pins the member to the kit's stub model before any pane starts:
- **Stub-only config.** After the Agent Mail install has written the kit HOME's `opencode.json`, `up` adds exactly one provider, `kitstub` (OpenAI-compatible, `baseURL` `http://127.0.0.1:18781/v1`, one model `stub`). It sets `enabled_providers` to `["kitstub"]`, `model` to `kitstub/stub`, and turns autoupdate and sharing off. The install's Agent Mail entry (`mcp.servers.albiex-synth-city-mail`) and its question-deny rule are kept.
- **The slot model.** The kit's team slot launches with the model `kitstub/stub`, so the product's own per-member config (`OPENCODE_CONFIG_CONTENT`) also limits `enabled_providers` to `kitstub`.
- **Proof before launch.** `up` reads the config back and refuses (exit 2) before the launch unless all of these hold:
  - the only provider is `kitstub`, with the adapter `@ai-sdk/openai-compatible` and its `baseURL` on `127.0.0.1`;
  - `enabled_providers` is exactly `["kitstub"]` and the model is `kitstub/stub`;
  - autoupdate is off and sharing is disabled;
  - the install's Mail entry is usable: local, enabled, `codemode` off, provider `opencode-cli` and the kit's own backend URL. Its command must be exactly two items: an absolute path that resolves to the kit backend's own Python interpreter (an alias of it is accepted; a different program named `python3` is not), then this checkout's `backend/mcp_shim/agent_mail_server.py`;
  - the deny rule is present.

  It also refuses an `opencode.jsonc` (comments can't be merged safely), a missing or non-object config, a config that already names another provider, and any symlinked or non-directory component of `home/.config/opencode`. A refusal changes nothing, inside or outside the kit.
- **Any later change is refused.** `up` records the SHA-256 of the config it wrote in `state/opencode-config.sha256`. A config with any other bytes no longer counts as proved. `state/` must be a plain directory of the root and the proof a plain file. `up` stages the new config and proof completely and commits each by an atomic rename, proof first, so a hard-linked proof is replaced, never written through. If the config can't be committed, the earlier proof is restored and the config is left unchanged (exit 2). A failed or partial write removes its own temporary file. If the earlier proof can't be restored, or a temporary file can't be removed, `up` stops as incomplete (exit 1) and names what is not as it was, including every temporary file it kept; it never reports that as an unchanged refusal.
- **The provider is proved from records.** `status` uses the OpenCode proof when the provider recorded by `up`, the launched slot's provider and the registered session's provider all agree. If the marker is missing or any of them disagree, `status` refuses before writing anything.
- **Evidence.** `status` proves the config again and publishes `opencode-config.json` in the manifest. It holds the provider ids, `enabled_providers`, the model, the stub's host and port, and whether the Mail entry is usable and the deny rule present; nothing else. At the end of capture, `status` proves the provider and the config once more. A change during capture fails `status`, and the published evidence stays unchanged.

**Limits.** The fake CLI is not OpenCode, so the product's OpenCode 2 gate refuses its Agent Mail registration and `up` with the fake stops at registration. That the stub-only config holds for a real OpenCode member, and that no hosted fallback happens, is proved only by a run of the real OpenCode CLI inside the kit; that run is a separate, approved phase.

## Using it for a live check

1. Write the check as commands run with `exec`, or let the CLI under test act from its pane.
2. Run `up`, then `status`, and keep the printed summary and the evidence manifest as the check's evidence.
3. Run `down` and keep its result as proof of cleanup.

The end-to-end test `backend/tests/test_isolated_runtime_kit.py` runs a fake provider CLI (`scripts/runtime-kit/fake_cli.sh`) through these steps. Its tests that start a namespace, backend or CLI are **opt-in**: they run only with `SYNTH_CITY_KIT_RUNTIME=1` and otherwise skip with "kit runtime tests are opt-in", so a broad `-k` filter or a full local run never starts a runtime by accident. Without the flag, every kit command in the tests also runs with a `PATH` whose `setsid`, `unshare` and `nsenter` refuse, so even a regressed refusal can't start an anchor. The model and refusal tests run everywhere.

## Limits

- **Linux only.** The kit needs unprivileged user and network namespaces, plus `tmux`, `unshare`, `nsenter`, `ip`, `timeout` and `setsid`. The kit's own checks without namespaces (the model, refusal, fake-CLI and stub tests) run on every host.
- **Not on the hosted `ubuntu-latest` runner as configured.** The runner denies the namespace setup (`unshare: write failed /proc/self/uid_map: Operation not permitted`). The log shows the denial, not its cause. There, each namespace-dependent test skips with `capability unavailable: uid_map`, and the namespace path is proved by one local run in the owner's leased workspace, with evidence on the PR for review.
- **One OS user.** Factory members share one OS user, so ownership is proved by the instance id and namespace, never by the user id alone.
- **Local checks only.** The stub model doesn't model a real provider; a real-provider check is a separate decision with its own approval.
- **One kit per root.** The ports (18780 for the backend, 18781 for the stub) belong to the kit's own network namespace, so separate kits don't collide.
