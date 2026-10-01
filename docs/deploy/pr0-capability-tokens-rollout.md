# PR0 rollout — Agent Mail capability tokens

Four ordered steps. **Steps 1 and 2 provision the operator credential; steps 3
and 4 provision the agents'.** They are different credentials with different
lifetimes, and each needs its own restart — the backend loads the operator token
at import, while agents obtain session tokens by registering. Doing 4 before 3
locks every agent out of mail.

Autonomy stays **off** for the whole sequence. Nothing here needs a dispatch to
verify, and a dispatch mid-rollout would register against a half-configured
backend.

## Step 1 — write the operator token

```bash
openssl rand -hex 32                     # 32 bytes is a floor, not a suggestion
```

Put it in `backend/.env` as `operator_token`:

```
operator_token=<the value>
```

Then:

```bash
chmod 600 backend/.env
```

`backend/.env` is already gitignored (`.gitignore:27` is a bare `.env`, which git
matches at any depth) — do not add another rule. The `chmod` is the part that is
not automatic.

**Never `export` this value.** `spawn_session` runs `subprocess.run(["tmux",
"new-session", ...])` with **no `env=` argument** (`app/services/agent_bridge/spawn.py:89-101`),
so the tmux server inherits the backend process's environment, and any pane can
read it with `tmux show-environment -g`.
A secret exported into the shell that launched the backend is a secret every
agent can read, which defeats the entire point of a credential agents are not
given.

`hmac.compare_digest` protects the comparison against timing attacks. Nothing
protects a short secret from being guessed at loopback speed, which is why the
floor is 32 bytes.

## Step 2 — restart the backend

```bash
# whatever you use to run it; the point is a NEW process
```

`settings = Settings()` runs at import (`backend/app/config.py:61`), so the value
is read once per process. Until this restart, every operator-gated route answers
`503 operator_token_unconfigured` — which is the intended fail-closed posture,
not a bug.

**Verify before continuing:**

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST http://127.0.0.1:8000/api/v1/agent-teams/github-scopes/1/workspaces/1/force-release \
  -H 'Content-Type: application/json' -d '{}'
# expect 401 -- the route exists and demands a credential

curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8000/api/v1/agent-teams/github-scopes/1/workspaces \
  -H "X-Deck-Operator-Token: $(grep '^operator_token=' backend/.env | cut -d= -f2-)"
# expect 200 or 404 -- authenticated; 404 only means scope 1 does not exist
```

A `503` on the second call means the restart did not pick up the file. A `401`
means the value does not match — check for a trailing newline or a quoted value.

**Do not put the token in shell history.** The `grep | cut` form above reads it
from the file rather than typing it. If you type it once, clear the line.

## Step 3 — restart the agent panes

Each agent registers on its next MCP call and receives a capability token, once,
in the registration response. The shim stores it and sends it as
`X-Deck-Session-Token` from then on (Task 6).

Until a pane restarts it holds no token. That is exactly why step 4 comes last:
with `mail_capability_tokens_required = False`, tokenless writes still work and
log `capability_token_missing` once per member — so this step's progress is
observable in the backend log.

**Verify before continuing:** the log should show no new
`capability_token_missing` lines for members whose panes you restarted. A member
that still logs it has a pane running pre-upgrade shim code.

## Step 4 — enforce

Add to `backend/.env`:

```
mail_capability_tokens_required=true
```

Restart the backend again. From this point:

- A mail write with no credential is `401 session_token_required`.
- A write with a token matching no session is `401 session_token_invalid` — an
  invalid token is never treated as an absent one.
- A token for an explicitly offline session, or for a slot-bound session whose
  recorded pane is gone, reused, or unobservable, is `401 session_token_stale`.
  Start a fresh agent session; do not copy the old bearer token into a new pane.
- Re-registering an existing hashed session row requires that row's current
  token. A slot-bound row can only re-register from its original live pane.
- Agent registration on a host where the pane cannot be derived from the kernel
  refuses with `bind_unverifiable`. On Linux this means the peer process is
  gone; on macOS it means always, which is why the README lists Linux as a
  prerequisite for this feature.
- The Agent Mail **UI** does not receive either credential above. It provisions
  a per-tab external-actor credential automatically, keeps the actor key in
  `sessionStorage`, and re-provisions once on `401` without changing that key.

**Rollback** is this step in reverse: set `mail_capability_tokens_required=false`,
restart the backend. Grace mode returns and tokenless writes work again. The
operator token stays configured and the operator routes stay gated — that half
took effect at step 2 and is not covered by the flag.

## What changes immediately at step 2, before enforcement

Two behaviours do not wait for the flag, and both are intentional:

- **Force-release and the workspace listing require the operator token.** An
  unconfigured install has no working operator route at all. A destructive route
  with no credential should be closed rather than open.
- **The force-release mismatch message no longer contains a lease token.**
  It previously interpolated the live token into an HTTP 409 body, making two
  unauthenticated calls enough to force-release any agent's workspace: guess,
  read the real token from the refusal, replay. The message now names the
  operator's `expected_leased_at` and the freshly observed lease state, never a
  lease token or the operator-supplied reason.

## Rotating the operator token

Replace it in `backend/.env` and restart the backend. There is no overlap
window: the old value dies with the old process. Acceptable here because the
population holding it is one operator, not 150 panes. No browser update is
needed: PR0 has no frontend caller for the operator-gated workspace routes, and
the Agent Mail UI uses its separate per-tab external-actor credential.
