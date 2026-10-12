#!/usr/bin/env bash
# Start one isolated Deck instance for the E2E journeys.
#
# The instance has its own temporary root: HOME, database, tmux server and
# fake harness binaries. It never reads the checkout's .env, never contacts
# GitHub and never signals processes outside its own tmux server.
#
# Environment:
#   E2E_PORT        Port for the API and the built UI (default 18765).
#   E2E_ROOT        Use this directory as the temporary root (default: mktemp).
#   E2E_SKIP_BUILD  Set to 1 to reuse an existing frontend/dist.
#   E2E_KEEP_ROOT   Set to 1 to keep the temporary root after exit.
#   PYTHON          Python with the backend requirements (default: backend/venv).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${E2E_PORT:-18765}"
if [[ -n "${PYTHON:-}" ]]; then
  :
elif [[ -x "$REPO_ROOT/backend/venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/backend/venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

if [[ -n "${E2E_ROOT:-}" ]]; then
  ROOT="$E2E_ROOT"
  mkdir -p "$ROOT"
else
  ROOT="$(mktemp -d "${TMPDIR:-/tmp}/deck-e2e.XXXXXX")"
fi
# Absolute paths only: the backend runs from $ROOT/run.
ROOT="$(cd "$ROOT" && pwd)"

export HOME="$ROOT/home"
export TMUX_TMPDIR="$ROOT/tmux"
unset TMUX TMUX_PANE
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export XDG_CACHE_HOME="$HOME/.cache"
export XDG_STATE_HOME="$HOME/.local/state"
FAKE_BIN="$ROOT/bin"
RUN_DIR="$ROOT/run"
DB_PATH="$ROOT/deck-e2e.db"
mkdir -p "$HOME" "$TMUX_TMPDIR" "$FAKE_BIN" "$RUN_DIR"
chmod 700 "$TMUX_TMPDIR"

backend_pid=""
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
  # Stop only the instance's own tmux server. TMUX_TMPDIR selects its socket.
  if command -v tmux >/dev/null 2>&1; then
    tmux kill-server 2>/dev/null || true
  fi
  if [[ "${E2E_KEEP_ROOT:-0}" != 1 ]]; then
    rm -rf "$ROOT"
  else
    echo "e2e-instance: kept $ROOT" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

# Fake harness binaries. Each one answers --version and echoes its input, so
# Deck sees installed providers and live members without real agents.
write_fake_harness() {
  local name="$1" version="$2"
  cat >"$FAKE_BIN/$name" <<EOF
#!/usr/bin/env bash
# Fake $name for the Deck E2E instance. No network, no credentials.
case "\${1:-}" in
  --version|-v|-V|version) echo "$version"; exit 0 ;;
  --help|-h|help) echo "usage: $name [--version]"; exit 0 ;;
esac
exec -a "$name" "\$BASH" -c 'echo "$name e2e fake ready"; while IFS= read -r line; do printf "%s\n" "\$line"; done; exit 0'
EOF
  chmod 755 "$FAKE_BIN/$name"
}
write_fake_harness claude "2.1.0 (Claude Code)"
write_fake_harness codex "codex-cli 0.50.0"
write_fake_harness copilot "1.0.0"
write_fake_harness opencode "1.0.0"
write_fake_harness pi "1.0.0"
# Deck must not reach GitHub through the gh CLI either.
cat >"$FAKE_BIN/gh" <<'EOF'
#!/usr/bin/env bash
echo "gh is disabled on the Deck E2E instance" >&2
exit 1
EOF
chmod 755 "$FAKE_BIN/gh"
export PATH="$FAKE_BIN:$PATH"

if [[ "${E2E_SKIP_BUILD:-0}" != 1 ]]; then
  (cd "$REPO_ROOT/frontend" && npm run build >&2)
fi
if [[ ! -f "$REPO_ROOT/frontend/dist/index.html" ]]; then
  echo "e2e-instance: frontend/dist is missing; unset E2E_SKIP_BUILD" >&2
  exit 1
fi

# Settings come from this environment only. The backend runs from $RUN_DIR,
# so a .env file in the checkout is never read.
export DATABASE_URL="sqlite+aiosqlite:///$DB_PATH"
export TEST_INSTANCE=1
export OPERATOR_TOKEN="e2e-director-key-0000000000000000"
export GITHUB_TOKEN=""
export GITHUB_APP_ID=""
export GITHUB_APP_PRIVATE_KEY_PATH=""
export GITHUB_COORDINATION_HOLD_PATHS="[]"
export BRIDGE_ATTACHMENT_DIR="$HOME/.claude-registry/bridge-attachments"
export HOST=127.0.0.1
export PORT
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$REPO_ROOT/backend"

cd "$RUN_DIR"
"$PYTHON" "$REPO_ROOT/scripts/e2e/seed.py" --database "$DB_PATH" --root "$ROOT" >&2

"$PYTHON" -m uvicorn app.main:app --app-dir "$REPO_ROOT/backend" \
  --host 127.0.0.1 --port "$PORT" --log-level warning &
backend_pid=$!
echo "e2e-instance: root=$ROOT port=$PORT pid=$backend_pid" >&2
wait "$backend_pid"
