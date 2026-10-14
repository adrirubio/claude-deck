#!/usr/bin/env bash
# Start one isolated Deck instance for the E2E journeys.
#
# The instance has its own temporary root: HOME, database, a private tmux
# server and fake harness binaries. The seed, the backend and tmux run with an
# allowlisted environment (env -i). The instance never reads the checkout's
# .env, never starts a real agent CLI, never contacts GitHub or another Deck,
# and never signals processes outside its own tmux server.
#
# It refuses to start (exit 2) when:
#   - the tmux binary is not a real tmux executable (for example a launcher
#     script that forces a shared team socket);
#   - the private tmux socket is not inside the instance root, or the server
#     is not new, or the server does not use the instance HOME;
#   - CLAUDE_DECK_URL, or a Deck Mail token variable, names another Deck;
#   - the instance HOME holds an Agent Mail MCP configuration;
#   - a harness name (claude, codex, copilot, opencode, pi, muse), gh or tmux does
#     not resolve to the instance's fake binaries.
#
# Environment:
#   E2E_PORT        Port for the API and the built UI. playwright.config.ts
#                   chooses a free port; 18765 is only the manual-start default.
#   E2E_RUN_TOKEN   Per-run token that /health reports (default: random).
#   E2E_ROOT        Temporary root (default: mktemp). It must be new, empty, or
#                   marked with a .deck-e2e-root file. It is removed on exit.
#   E2E_SKIP_BUILD  Set to 1 to reuse an existing frontend/dist.
#   E2E_KEEP_ROOT   Set to 1 to keep the temporary root after exit.
#   E2E_TMUX        The tmux executable (default: the first tmux on PATH).
#   E2E_NO_TMUX     Set to 1 to run without a tmux server. Deck then sees no
#                   live sessions; journeys that need them skip. CI never sets it.
#   E2E_SEED_NOW    ISO UTC time the seed counts from (default: this hour).
#   PYTHON          Python with the backend requirements (default: backend/venv).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${E2E_PORT:-18765}"
INSTANCE_URL="http://127.0.0.1:$PORT"
NO_TMUX="${E2E_NO_TMUX:-0}"
ROOT_MARKER=".deck-e2e-root"

refuse() {
  echo "e2e-instance: refused: $*" >&2
  exit 2
}

# --- Refusals that need no process -------------------------------------------

# Another Deck (for example production Agent Mail) must not be reachable
# through the caller's environment.
if [[ -n "${CLAUDE_DECK_URL:-}" && "$CLAUDE_DECK_URL" != "$INSTANCE_URL" ]]; then
  refuse "CLAUDE_DECK_URL names another Deck; unset it to run the E2E instance"
fi
for var in $(compgen -e); do
  if [[ "$var" == CLAUDE_DECK_* && "$var" == *TOKEN* ]]; then
    refuse "$var is set; a Deck Mail credential must not reach the E2E instance"
  fi
done

if [[ -n "${PYTHON:-}" ]]; then
  :
elif [[ -x "$REPO_ROOT/backend/venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/backend/venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

TMUX_BIN=""
if [[ "$NO_TMUX" != 1 ]]; then
  TMUX_BIN="${E2E_TMUX:-$(command -v tmux || true)}"
  [[ -n "$TMUX_BIN" && -x "$TMUX_BIN" ]] || refuse "tmux is required; set E2E_TMUX"
  tmux_real="$(readlink -f "$TMUX_BIN")"
  if [[ "$(head -c 4 "$tmux_real" | od -An -c | tr -d ' ')" != '177ELF' ]]; then
    refuse "$TMUX_BIN is not a tmux executable (a launcher script can force a shared socket)"
  fi
  TMUX_BIN="$tmux_real"
fi

# --- The temporary root --------------------------------------------------------

if [[ -n "${E2E_ROOT:-}" ]]; then
  mkdir -p "$E2E_ROOT"
  ROOT="$(cd "$E2E_ROOT" && pwd)"
  if [[ -n "$(ls -A "$ROOT")" && ! -f "$ROOT/$ROOT_MARKER" ]]; then
    refuse "E2E_ROOT $ROOT is not empty and has no $ROOT_MARKER file"
  fi
else
  ROOT="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/deck-e2e.XXXXXX")" && pwd)"
fi
touch "$ROOT/$ROOT_MARKER"

E2E_HOME="$ROOT/home"
TMUX_DIR="$ROOT/tmux"
TMUX_SOCKET="$TMUX_DIR/deck-e2e.sock"
FAKE_BIN="$ROOT/bin"
RUN_DIR="$ROOT/run"
DB_PATH="$ROOT/deck-e2e.db"
mkdir -p "$E2E_HOME" "$TMUX_DIR" "$FAKE_BIN" "$RUN_DIR"
chmod 700 "$TMUX_DIR"

backend_pid=""
tmux_owned=0
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill -TERM "$backend_pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$backend_pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL "$backend_pid" 2>/dev/null || true
  fi
  # Stop only the private tmux server, and only after the proof below showed
  # that the socket belongs to this instance.
  if [[ "$tmux_owned" == 1 ]]; then
    "$TMUX_BIN" -S "$TMUX_SOCKET" kill-server 2>/dev/null || true
  fi
  if [[ "${E2E_KEEP_ROOT:-0}" == 1 ]]; then
    echo "e2e-instance: kept $ROOT" >&2
  elif [[ -f "$ROOT/$ROOT_MARKER" ]]; then
    rm -rf "$ROOT"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# An Agent Mail MCP configuration in HOME would connect fake agents to a Deck.
if grep -rqsE 'claude-deck-mail|deck_check_inbox|/api/v1/agent-mail' "$E2E_HOME"; then
  refuse "the instance HOME holds an Agent Mail MCP configuration"
fi

# --- Fake binaries and the allowlisted environment ---------------------------

for name in claude codex copilot opencode pi muse; do
  install -m 755 "$REPO_ROOT/scripts/e2e/fake-harness.sh" "$FAKE_BIN/$name"
done
cat >"$FAKE_BIN/gh" <<'EOF'
#!/bin/sh
echo "gh is disabled on the Deck E2E instance" >&2
exit 1
EOF
if [[ "$NO_TMUX" == 1 ]]; then
  cat >"$FAKE_BIN/tmux" <<'EOF'
#!/bin/sh
echo "tmux is disabled on this Deck E2E instance (E2E_NO_TMUX=1)" >&2
exit 1
EOF
else
  # Every tmux call (Deck and the seed) goes to the private socket.
  cat >"$FAKE_BIN/tmux" <<EOF
#!/bin/sh
exec "$TMUX_BIN" -S "$TMUX_SOCKET" "\$@"
EOF
fi
chmod 755 "$FAKE_BIN/gh" "$FAKE_BIN/tmux"

# System directories only after the fakes. Host agent launchers are not on it.
CLEAN_PATH="$FAKE_BIN:/usr/local/bin:/usr/bin:/bin"
CLEAN_ENV=(
  "PATH=$CLEAN_PATH"
  "HOME=$E2E_HOME"
  "USER=${USER:-e2e}" "LOGNAME=${USER:-e2e}"
  "LANG=C.UTF-8" "TERM=xterm-256color"
  "TMPDIR=$ROOT" "TMUX_TMPDIR=$TMUX_DIR"
  "XDG_CONFIG_HOME=$E2E_HOME/.config" "XDG_DATA_HOME=$E2E_HOME/.local/share"
  "XDG_CACHE_HOME=$E2E_HOME/.cache" "XDG_STATE_HOME=$E2E_HOME/.local/state"
  "CLAUDE_DECK_URL=$INSTANCE_URL"
  "E2E_NO_TMUX=$NO_TMUX"
)
if [[ -n "${E2E_SEED_NOW:-}" ]]; then
  CLEAN_ENV+=("E2E_SEED_NOW=$E2E_SEED_NOW")
fi
run_clean() { env -i "${CLEAN_ENV[@]}" "$@"; }

for name in claude codex copilot opencode pi muse gh tmux; do
  resolved="$(run_clean sh -c "command -v $name" || true)"
  [[ "$resolved" == "$FAKE_BIN/$name" ]] || refuse "$name resolves to ${resolved:-nothing}, not the fake binary"
done

# --- Private tmux server --------------------------------------------------------

if [[ "$NO_TMUX" == 1 ]]; then
  CLEAN_ENV+=("E2E_NO_PANES=1")
else
  [[ ! -e "$TMUX_SOCKET" ]] || refuse "$TMUX_SOCKET exists already; use a new E2E_ROOT"
  case "$TMUX_SOCKET" in
    "$ROOT"/*) ;;
    *) refuse "the tmux socket is outside the instance root" ;;
  esac
  # A probe session proves the socket, a new server and the environment.
  run_clean "$FAKE_BIN/tmux" -f /dev/null new-session -d -s deck-e2e-probe "sleep 600"
  probe_socket="$(run_clean "$FAKE_BIN/tmux" display-message -p -t '=deck-e2e-probe' '#{socket_path}' 2>/dev/null || true)"
  [[ "$probe_socket" == "$TMUX_SOCKET" ]] || refuse "tmux used a socket outside the instance root"
  tmux_owned=1
  [[ "$(run_clean "$FAKE_BIN/tmux" list-sessions -F '#{session_name}')" == deck-e2e-probe ]] \
    || refuse "the tmux server has other sessions; it is not private"
  [[ "$(run_clean "$FAKE_BIN/tmux" show-environment -g HOME 2>/dev/null || true)" == "HOME=$E2E_HOME" ]] \
    || refuse "the tmux server HOME is outside the instance root"
  [[ "$(run_clean "$FAKE_BIN/tmux" show-environment -g CLAUDE_DECK_URL 2>/dev/null || true)" == "CLAUDE_DECK_URL=$INSTANCE_URL" ]] \
    || refuse "the tmux server names another Deck"
  run_clean "$FAKE_BIN/tmux" set-option -g exit-empty off \; kill-session -t '=deck-e2e-probe'
  CLEAN_ENV+=("E2E_TMUX_PROVEN_SOCKET=$TMUX_SOCKET")
fi

# --- Build, seed and serve ------------------------------------------------------

if [[ "${E2E_SKIP_BUILD:-0}" != 1 ]]; then
  (cd "$REPO_ROOT/frontend" && npm run build >&2)
fi
[[ -f "$REPO_ROOT/frontend/dist/index.html" ]] || refuse "frontend/dist is missing; unset E2E_SKIP_BUILD"

# The run token identifies this instance on /health; journeys refuse a server
# that reports another token. Never print it.
RUN_TOKEN="${E2E_RUN_TOKEN:-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')}"
[[ "$RUN_TOKEN" =~ ^[A-Za-z0-9_-]{16,}$ ]] || refuse "E2E_RUN_TOKEN must be at least 16 letters, digits, - or _"

# Settings come from this environment only. The backend runs from $RUN_DIR,
# so a .env file in the checkout is never read.
CLEAN_ENV+=(
  "DATABASE_URL=sqlite+aiosqlite:///$DB_PATH"
  "TEST_INSTANCE=1"
  "TEST_INSTANCE_ROOT=$ROOT"
  "TEST_INSTANCE_TOKEN=$RUN_TOKEN"
  "OPERATOR_TOKEN=e2e-director-key-0000000000000000"
  "GITHUB_TOKEN=" "GITHUB_APP_ID=" "GITHUB_APP_PRIVATE_KEY_PATH="
  "GITHUB_COORDINATION_HOLD_PATHS=[]"
  "BRIDGE_ATTACHMENT_DIR=$E2E_HOME/.claude-registry/bridge-attachments"
  "HOST=127.0.0.1" "PORT=$PORT"
  "PYTHONDONTWRITEBYTECODE=1" "PYTHONPATH=$REPO_ROOT/backend"
)

cd "$RUN_DIR"
run_clean "$PYTHON" "$REPO_ROOT/scripts/e2e/seed.py" --database "$DB_PATH" --root "$ROOT" >&2

# Not through run_clean: a backgrounded function is a subshell, and its PID
# would not be the server's. env execs Python, so $! is the server itself.
env -i "${CLEAN_ENV[@]}" "$PYTHON" -m uvicorn app.main:app --app-dir "$REPO_ROOT/backend" \
  --host 127.0.0.1 --port "$PORT" --log-level warning &
backend_pid=$!
echo "e2e-instance: root=$ROOT port=$PORT pid=$backend_pid" >&2
wait "$backend_pid"
