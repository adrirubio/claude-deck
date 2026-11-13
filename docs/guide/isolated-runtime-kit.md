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
| `status` | 15 s | Checks every recorded process, the backend's health and the registration, then writes the evidence and prints the summary. If any proof is missing it fails as incomplete and writes no manifest. |
| `exec` | 120 s by default, at most 600 s | Runs a command inside the namespaces with the kit's environment. |
| `down` | 30 s | Stops every process of the instance, including ones started later inside its namespace, proves none remains, checks the evidence manifest, and removes the root (`--keep` keeps it). If it can't prove cleanup, it fails as incomplete and keeps the root. |

**Exit codes:** 0 means success, 1 a failure, a deadline or an incomplete proof, and 2 a refusal.

## Ownership and cleanup

Each `up` creates one instance with a random id. `state/instance.json` (a private file) records that id, the root directory's identity and the kit's namespaces. The anchors carry the id in their arguments. `status`, `exec` and `down` refuse (exit 2), before any signal or deletion, when:
- the record is missing or malformed, or isn't a private file of the caller;
- it was copied from another root;
- it names a host namespace.

`down` stops the processes of the instance: those carrying its id, and those inside its network namespace, but the namespace counts only while the instance's own anchor is alive in it. If processes run in a namespace that no live anchor proves, or a process can't be inspected, `down` signals nothing, reports the cleanup as incomplete and keeps the root.

**A root is never reused.** A root left by `down --keep` or by a failed `up` is refused by the next `up`; run `down` to remove it.

## Evidence

`status` writes these files to `ROOT/evidence/`, with `MANIFEST.sha256`:
- `namespaces.json`
- `links.txt`
- `processes.txt`
- `pane.json`
- `registration.json`
- `environment-names.json`, holding variable names only, never values
- `stub-requests.jsonl`

`down` refuses to finish if the manifest no longer matches.

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

**Namespace entry is two-step.** The kit enters through the outer anchor, which owns the network namespace, and then the inner one. A single `nsenter` into the inner anchor is refused by the kernel. Before it enters a namespace or sends a signal, the kit checks the recorded pid and its start time (`/proc/<pid>/stat` field 22).

## Using it for a live check

1. Write the check as commands run with `exec`, or let the CLI under test act from its pane.
2. Run `up`, then `status`, and keep the printed summary and the evidence manifest as the check's evidence.
3. Run `down` and keep its result as proof of cleanup.

The end-to-end test `backend/tests/test_isolated_runtime_kit.py` runs a fake provider CLI (`scripts/runtime-kit/fake_cli.sh`) through these steps.

## Limits

- **Linux only.** The kit needs unprivileged user and network namespaces, plus `tmux`, `unshare`, `nsenter`, `ip`, `timeout` and `setsid`. The test fails, and doesn't skip, on a host without them.
- **Not on the hosted `ubuntu-latest` runner as configured.** Its AppArmor policy refuses unprivileged user namespaces (`unshare: write failed /proc/self/uid_map: Operation not permitted`), so the kit can't run there.
- **One OS user.** Factory members share one OS user, so ownership is proved by the instance id and namespace, never by the user id alone.
- **Local checks only.** The stub model doesn't model a real provider; a real-provider check is a separate decision with its own approval.
- **One kit per root.** The ports (18780 for the backend, 18781 for the stub) belong to the kit's own network namespace, so separate kits don't collide.
