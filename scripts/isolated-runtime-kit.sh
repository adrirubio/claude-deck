#!/usr/bin/env bash
# The isolated runtime kit (#902): start, prove and tear down one isolated
# runtime for a provider live check.
#
#   isolated-runtime-kit.sh up     --root DIR --provider P --cli PATH
#   isolated-runtime-kit.sh status --root DIR
#   isolated-runtime-kit.sh exec   --root DIR [--timeout S] -- COMMAND...
#   isolated-runtime-kit.sh down   --root DIR [--keep]
#
# Everything runs inside the kit's own user and network namespaces:
#   - an outer anchor (`unshare --user --map-root-user --net`) brings up `lo`,
#     which must be the only link;
#   - an inner anchor (`unshare --user --map-user/--map-group`) maps back to the
#     caller's uid and gid;
#   - entry is two-step, through the outer anchor (it owns the network namespace)
#     and then the inner one: `nsenter -U -n -t OUTER`, then `nsenter -U -t INNER`.
# Inside run an isolated Synth City backend (own root, HOME, SQLite, private tmux
# socket, synthetic operator token, allowlisted environment), a stub model
# provider, and the CLI under test, launched through Synth City's normal team
# launch so the real pane binding and Agent Mail registration are exercised.
#
# Every pid the kit records is stored with its start time (/proc/<pid>/stat
# field 22). The kit re-checks both before it enters a namespace or sends a
# signal, and refuses on any mismatch. Each command has a finite deadline.
#
# Exit codes: 0 ok, 1 failed (deadline, unhealthy), 2 refused (unsafe input or
# a failed proof). Tokens are never printed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$REPO_ROOT/scripts/isolated-runtime-kit.sh"
MARKER=".deck-runtime-kit"
OPERATOR_TOKEN="runtime-kit-operator-$(od -An -N4 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')"

UP_DEADLINE="${RUNTIME_KIT_UP_DEADLINE:-90}"
PREFLIGHT_DEADLINE=10
HEALTH_DEADLINE=30
STUB_DEADLINE=5
REGISTRATION_DEADLINE=30
STATUS_DEADLINE=15
EXEC_DEFAULT=120
EXEC_CAP=600
DOWN_TERM_WAIT=10

refuse() { echo "isolated-runtime-kit: refused: $*" >&2; exit 2; }
fail() { echo "isolated-runtime-kit: failed: $*" >&2; exit 1; }
note() { echo "isolated-runtime-kit: $*" >&2; }

# --- Process identity --------------------------------------------------------------

start_time() { # pid -> /proc/<pid>/stat field 22, or nothing
  local stat
  stat="$(cat "/proc/$1/stat" 2>/dev/null)" || return 1
  stat="${stat##*) }"            # drop "pid (comm) "; comm may contain spaces
  # shellcheck disable=SC2086
  set -- $stat
  echo "${20}"                   # field 22 overall is field 20 after pid and comm
}

proc_json() { echo "$ROOT/state/processes.json"; }

record() { # name pid
  local start
  start="$(start_time "$2")" || refuse "$1 (pid $2) is gone before it could be recorded"
  python3 -I - "$(proc_json)" "$1" "$2" "$start" <<'PY'
import json, os, sys
path, name, pid, start = sys.argv[1:5]
data = json.load(open(path)) if os.path.exists(path) else {}
data[name] = {"pid": int(pid), "start": start}
tmp = path + ".tmp"
json.dump(data, open(tmp, "w"))
os.replace(tmp, path)
PY
  python3 -I - "$ROOT/state/started.json" "$1" <<'PY'
import json, os, sys
path, name = sys.argv[1:3]
data = json.load(open(path)) if os.path.exists(path) else {}
data[name] = True
json.dump(data, open(path, "w"))
PY
}

recorded() { # name -> "pid start" or nothing
  python3 -I - "$(proc_json)" "$1" <<'PY'
import json, os, sys
path, name = sys.argv[1:3]
if os.path.exists(path):
    entry = json.load(open(path)).get(name)
    if entry:
        print(entry["pid"], entry["start"])
PY
}

verify() { # name -> pid, after proving the recorded start time; refuses otherwise
  local entry pid start now
  entry="$(recorded "$1")"
  [[ -n "$entry" ]] || refuse "no recorded $1 process"
  read -r pid start <<<"$entry"
  now="$(start_time "$pid")" || refuse "$1 (pid $pid) is not running"
  [[ "$now" == "$start" ]] || refuse "$1 pid $pid has another start time; it is not the recorded process"
  echo "$pid"
}

# --- Namespace entry -----------------------------------------------------------------

in_ns() { # run a command inside the kit namespaces, with the allowlisted environment
  local outer inner
  outer="$(verify outer)"
  inner="$(verify inner)"
  nsenter --preserve-credentials -U -n -t "$outer" \
    nsenter --preserve-credentials -U -t "$inner" \
    env -i "${CLEAN_ENV[@]}" "$@"
}

spawn() { # name log command... : start a long-running process inside the namespaces and record it.
  # nsenter, the nested nsenter and env all exec, so $! is the process itself.
  local name="$1" log="$2" outer inner
  shift 2
  outer="$(verify outer)"
  inner="$(verify inner)"
  setsid nsenter --preserve-credentials -U -n -t "$outer" \
    nsenter --preserve-credentials -U -t "$inner" \
    env -i "${CLEAN_ENV[@]}" "$@" </dev/null >"$log" 2>&1 &
  record "$name" "$!"
}

load_env() {
  [[ -f "$ROOT/state/env" ]] || refuse "$ROOT is not a running kit"
  mapfile -t CLEAN_ENV <"$ROOT/state/env"
}

# --- Arguments -----------------------------------------------------------------------

COMMAND="${1:-}"
[[ -n "$COMMAND" ]] && shift
# --- Internal anchors (run inside the namespaces) -------------------------------------

if [[ "$COMMAND" == _outer ]]; then
  # Root of the outer user namespace: own the network namespace, bring up lo only.
  ROOT="$1" CALLER_UID="$2" CALLER_GID="$3"
  ip link set lo up
  links="$(ip -o link | awk -F': ' '{print $2}' | tr '\n' ' ')"
  [[ "$links" == "lo " ]] || { echo "links: $links" >"$ROOT/state/outer.refused"; exit 2; }
  echo "$$" >"$ROOT/state/outer.pid"
  unshare --user --map-user="$CALLER_UID" --map-group="$CALLER_GID" "$SELF" _inner "$ROOT" &
  inner=$!
  trap 'kill -TERM "$inner" 2>/dev/null; exit 0' TERM INT
  wait "$inner"
  exit 0
fi
if [[ "$COMMAND" == _inner ]]; then
  ROOT="$1"
  echo "$$ $(id -u) $(id -g) $(readlink /proc/self/ns/net) $(readlink /proc/self/ns/user)" >"$ROOT/state/inner.id"
  exec sleep infinity
fi

ROOT_ARG="" PROVIDER="" CLI="" KEEP=0 EXEC_TIMEOUT="$EXEC_DEFAULT"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT_ARG="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --cli) CLI="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --timeout) EXEC_TIMEOUT="$2"; shift 2 ;;
    --) shift; break ;;
    *) refuse "unknown argument $1" ;;
  esac
done

[[ -n "$ROOT_ARG" ]] || refuse "--root is required"
mkdir -p "$(dirname "$ROOT_ARG")"
ROOT="$(cd "$(dirname "$ROOT_ARG")" && pwd)/$(basename "$ROOT_ARG")"

# --- up ------------------------------------------------------------------------------

provider_binary() {
  case "$1" in
    claude-code) echo claude ;;
    codex-cli) echo codex ;;
    copilot-cli) echo copilot ;;
    opencode-cli) echo opencode ;;
    pi-cli) echo pi ;;
    muse-cli) echo muse ;;
    *) return 1 ;;
  esac
}

up_cleanup_on_failure() {
  local status=$?
  if [[ $status -ne 0 && -f "$ROOT/$MARKER" ]]; then
    # Stop everything, but keep the root (logs and state) so the failure can be read.
    note "tearing down after a failed up; keeping $ROOT for its logs (run down to remove it)"
    "$SELF" down --root "$ROOT" --keep >&2 || true
  fi
  exit "$status"
}

up() {
  local deadline=$((SECONDS + UP_DEADLINE))
  # Refusals that need no process (as in scripts/e2e-instance.sh).
  [[ -z "${SYNTH_CITY_URL:-}" ]] || refuse "SYNTH_CITY_URL is set; unset it so no other Synth City is reachable"
  local var
  for var in $(compgen -e); do
    if [[ "$var" == SYNTH_CITY_* && ( "$var" == *TOKEN* || "$var" == *SESSION* ) ]]; then
      refuse "$var is set; a Synth City Mail credential must not reach the kit"
    fi
  done
  local binary
  binary="$(provider_binary "$PROVIDER")" || refuse "unknown provider '$PROVIDER'"
  [[ -n "$CLI" && -x "$CLI" ]] || refuse "--cli must be an executable"
  if [[ -e "$ROOT" && -n "$(ls -A "$ROOT")" && ! -f "$ROOT/$MARKER" ]]; then
    refuse "$ROOT is not empty and has no $MARKER file"
  fi
  [[ ! -f "$ROOT/state/env" ]] || refuse "a kit is already running in $ROOT; run down first"
  ((${#ROOT} <= 96)) || refuse "the kit root path is longer than 96 bytes; the tmux socket path would exceed the 108-byte limit"
  local python="${PYTHON:-}"
  if [[ -z "$python" ]]; then
    if [[ -x "$REPO_ROOT/backend/venv/bin/python" ]]; then python="$REPO_ROOT/backend/venv/bin/python"; else python="$(command -v python3)"; fi
  fi
  # The real tmux executable, never a launcher script (a launcher can force a shared
  # team socket). RUNTIME_KIT_TMUX overrides; otherwise the first ELF tmux on PATH.
  local tmux_bin="" candidate
  for candidate in ${RUNTIME_KIT_TMUX:-$(type -aP tmux)}; do
    candidate="$(readlink -f "$candidate")"
    if [[ "$(head -c 4 "$candidate" 2>/dev/null | od -An -c | tr -d ' ')" == '177ELF' ]]; then tmux_bin="$candidate"; break; fi
  done
  [[ -n "$tmux_bin" ]] || refuse "no tmux executable found (a launcher script is not accepted); set RUNTIME_KIT_TMUX"

  mkdir -p "$ROOT"
  touch "$ROOT/$MARKER"
  mkdir -p "$ROOT/state" "$ROOT/home/work" "$ROOT/bin" "$ROOT/run" "$ROOT/t" "$ROOT/evidence" "$ROOT/logs"
  chmod 700 "$ROOT/t"
  echo '{}' >"$ROOT/state/started.json"
  trap up_cleanup_on_failure EXIT

  # Binaries: the CLI under test under its provider name; every other harness name
  # resolves to a fake, so no host CLI can start; gh is disabled; tmux is pinned.
  local name
  for name in claude codex copilot opencode pi muse; do
    install -m 755 "$REPO_ROOT/scripts/e2e/fake-harness.sh" "$ROOT/bin/$name"
  done
  install -m 755 "$CLI" "$ROOT/bin/$binary"
  printf '#!/bin/sh\necho "gh is disabled in the isolated runtime kit" >&2\nexit 1\n' >"$ROOT/bin/gh"
  printf '#!/bin/sh\nexec "%s" -S "%s" "$@"\n' "$tmux_bin" "$ROOT/t/s" >"$ROOT/bin/tmux"
  chmod 755 "$ROOT/bin/gh" "$ROOT/bin/tmux"

  local port=18780 stub_port=18781
  CLEAN_ENV=(
    "PATH=$ROOT/bin:/usr/local/bin:/usr/bin:/bin"
    "HOME=$ROOT/home" "USER=${USER:-kit}" "LOGNAME=${USER:-kit}"
    "LANG=C.UTF-8" "TERM=xterm-256color"
    "TMPDIR=$ROOT/run" "TMUX_TMPDIR=$ROOT/t"
    "XDG_CONFIG_HOME=$ROOT/home/.config" "XDG_DATA_HOME=$ROOT/home/.local/share"
    "XDG_CACHE_HOME=$ROOT/home/.cache" "XDG_STATE_HOME=$ROOT/home/.local/state"
    "SYNTH_CITY_URL=http://127.0.0.1:$port"
    "RUNTIME_KIT_ROOT=$ROOT" "RUNTIME_KIT_PROVIDER=$PROVIDER"
    "RUNTIME_KIT_STUB_URL=http://127.0.0.1:$stub_port"
  )
  [[ -z "${RUNTIME_KIT_TEST_FAULT:-}" ]] || CLEAN_ENV+=("RUNTIME_KIT_TEST_FAULT=$RUNTIME_KIT_TEST_FAULT")
  printf '%s\n' "${CLEAN_ENV[@]}" >"$ROOT/state/env.pending"

  # --- Preflight: anchors, uid mapping, two-step entry (before any backend) -----------
  local preflight=$((SECONDS + PREFLIGHT_DEADLINE))
  # The anchors start from an empty environment too: nothing of the caller's session
  # (tokens, sockets, identities) may live inside the namespaces.
  setsid env -i "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "HOME=$ROOT/home" "LANG=C.UTF-8" \
    unshare --user --map-root-user --net --kill-child "$SELF" _outer "$ROOT" "$(id -u)" "$(id -g)" \
    </dev/null >"$ROOT/logs/anchor.log" 2>&1 &
  until [[ -s "$ROOT/state/inner.id" || -f "$ROOT/state/outer.refused" ]]; do
    ((SECONDS < preflight)) || fail "preflight deadline: the namespace anchors did not start"
    sleep 0.1
  done
  [[ ! -f "$ROOT/state/outer.refused" ]] || refuse "the network namespace is not loopback-only ($(cat "$ROOT/state/outer.refused"))"
  record outer "$(cat "$ROOT/state/outer.pid")"
  local inner_pid inner_uid inner_gid inner_net inner_user
  read -r inner_pid inner_uid inner_gid inner_net inner_user <"$ROOT/state/inner.id"
  record inner "$inner_pid"
  if [[ "${RUNTIME_KIT_TEST_FAULT:-}" == uid_mismatch ]]; then inner_uid=$((inner_uid + 1)); fi
  [[ "$inner_uid" == "$(id -u)" && "$inner_gid" == "$(id -g)" ]] \
    || refuse "the inner namespace maps uid/gid $inner_uid/$inner_gid, not the caller's $(id -u)/$(id -g)"
  [[ "$inner_net" != "$(readlink /proc/self/ns/net)" ]] || refuse "the kit shares the host network namespace"
  mapfile -t CLEAN_ENV <"$ROOT/state/env.pending"
  local joined
  joined="$(in_ns sh -c 'echo "$(id -u) $(id -g) $(readlink /proc/self/ns/net) $(readlink /proc/self/ns/user) $(ip -o link | wc -l)"')" \
    || refuse "entering the kit namespaces failed"
  if [[ "${RUNTIME_KIT_TEST_FAULT:-}" == join_mismatch ]]; then joined="$joined mismatch"; fi
  [[ "$joined" == "$(id -u) $(id -g) $inner_net $inner_user 1" ]] \
    || refuse "the namespace join check failed (got: $joined)"
  mv "$ROOT/state/env.pending" "$ROOT/state/env"

  # --- Private tmux server, proved inside the root ------------------------------------
  in_ns "$ROOT/bin/tmux" -f /dev/null new-session -d -s kit-probe "sleep 600" </dev/null >/dev/null 2>&1
  [[ "$(in_ns "$ROOT/bin/tmux" display-message -p -t '=kit-probe' '#{socket_path}')" == "$ROOT/t/s" ]] \
    || refuse "tmux used a socket outside the kit root"
  [[ "$(in_ns "$ROOT/bin/tmux" list-sessions -F '#{session_name}')" == kit-probe ]] || refuse "the tmux server is not private"
  record tmux "$(in_ns "$ROOT/bin/tmux" display-message -p '#{pid}')"
  in_ns "$ROOT/bin/tmux" set-option -g exit-empty off \; kill-session -t '=kit-probe'

  # --- Stub model provider -------------------------------------------------------------
  spawn stub "$ROOT/logs/stub.log" \
    python3 "$REPO_ROOT/scripts/runtime-kit/stub_provider.py" --port "$stub_port" --log "$ROOT/run/stub-requests.jsonl"
  local stub_ready=$((SECONDS + STUB_DEADLINE))
  until in_ns python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$stub_port/health', timeout=1)" 2>/dev/null; do
    ((SECONDS < stub_ready && SECONDS < deadline)) || fail "deadline: the stub provider did not start"
    sleep 0.2
  done

  # --- Isolated backend ----------------------------------------------------------------
  local run_token
  run_token="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  printf '%s\n' "$run_token" >"$ROOT/state/run-token"
  printf '%s\n' "$OPERATOR_TOKEN" >"$ROOT/state/operator-token"
  chmod 600 "$ROOT/state/run-token" "$ROOT/state/operator-token"
  local backend_env=(
    "DATABASE_URL=sqlite+aiosqlite:///$ROOT/kit.db" "TEST_INSTANCE=1" "TEST_INSTANCE_ROOT=$ROOT"
    "TEST_INSTANCE_TOKEN=$run_token" "OPERATOR_TOKEN=$OPERATOR_TOKEN"
    "GITHUB_TOKEN=" "GITHUB_APP_ID=" "GITHUB_APP_PRIVATE_KEY_PATH=" "GITHUB_COORDINATION_HOLD_PATHS=[]"
    "HOST=127.0.0.1" "PORT=$port" "PYTHONDONTWRITEBYTECODE=1" "PYTHONPATH=$REPO_ROOT/backend"
  )
  # Secrets go through a 0600 file read by a small launcher, never through argv
  # (argv is visible in process listings and in the evidence).
  (umask 077; printf 'export %q\n' "${backend_env[@]}" >"$ROOT/state/backend.env")
  printf '#!/bin/sh\n. "%s"\ncd "%s"\nexec "%s" -m uvicorn app.main:app --app-dir "%s" --host 127.0.0.1 --port %s --log-level warning\n' \
    "$ROOT/state/backend.env" "$ROOT/run" "$python" "$REPO_ROOT/backend" "$port" >"$ROOT/run/backend.sh"
  chmod 700 "$ROOT/run/backend.sh"
  spawn backend "$ROOT/logs/backend.log" "$ROOT/run/backend.sh"
  local health=$((SECONDS + HEALTH_DEADLINE))
  until in_ns "$python" -I - "$port" "$run_token" <<'PY' 2>/dev/null
import json, sys, urllib.request
body = json.load(urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=1))
sys.exit(0 if body.get("test_instance", {}).get("token") == sys.argv[2] else 1)
PY
  do
    ((SECONDS < health && SECONDS < deadline)) || fail "deadline: the isolated backend did not report healthy"
    sleep 0.5
  done

  # --- Team slot, real launch, Agent Mail registration --------------------------------
  git -C "$ROOT/home/work" init -q 2>/dev/null || true
  local launch
  launch="$(in_ns "$python" -I - "$port" "$OPERATOR_TOKEN" "$PROVIDER" "$ROOT/home/work" <<'PY'
import json, sys, urllib.error, urllib.request
port, token, provider, work = sys.argv[1:5]
def call(method, path, body=None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-Synth-City-Operator-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path}: HTTP {exc.code}: {exc.read()[:400].decode(errors='replace')}")
install = {"claude-code": "claude-code", "codex-cli": "codex", "copilot-cli": "copilot",
           "opencode-cli": "opencode", "muse-cli": "muse"}.get(provider)
if install:  # the provider's normal Agent Mail install, written into the kit HOME
    call("POST", f"/agent-mail/install/{install}/apply", {"confirmed": True})
preset = call("POST", "/agent-teams/presets", {"name": "runtime-kit", "slots": [
    {"display_name": "kit member", "provider": provider, "repo_path": work}]})
slot_id = preset["slots"][0]["id"]
plan = call("POST", f"/agent-teams/presets/{preset['id']}/plan-launch", {"skip_plan_confirmation": True})
blocked = [item for item in plan.get("items", []) if item.get("blocked") or item.get("block_code")]
if blocked:
    sys.exit("launch plan blocked: " + json.dumps([{k: item.get(k) for k in ("block_code", "blocked_reason", "reason", "warnings")}
                                                    for item in blocked])[:800])
result = call("POST", f"/agent-teams/presets/{preset['id']}/launch", {"skip_plan_confirmation": True})
print(json.dumps({"preset_id": preset["id"], "slot_id": slot_id, "launch": result.get("status")}))
PY
  )" || fail "the team launch through the isolated backend failed (see $ROOT/logs/backend.log)"
  echo "$launch" >"$ROOT/state/launch.json"

  local registered=$((SECONDS + REGISTRATION_DEADLINE))
  until registration_row >/dev/null 2>&1; do
    ((SECONDS < registered && SECONDS < deadline)) || fail "deadline: the CLI did not register through Agent Mail"
    sleep 0.5
  done
  record cli "$(registration_row | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["bound_pane_pid"])')"

  trap - EXIT
  summary
}

registration_row() { # the registered session and its pane binding, read from the kit's own database
  python3 -I - "$ROOT/kit.db" "$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["slot_id"])' "$ROOT/state/launch.json")" <<'PY'
import json, sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
row = db.execute(
    "SELECT s.provider, s.source, s.team_slot_id, s.bound_pane_pid, s.mailbox_status, b.pane_pid, b.slot_id "
    "FROM mail_agent_sessions s JOIN agent_pane_bindings b ON b.pane_pid = s.bound_pane_pid "
    "AND b.pane_proc_start = s.bound_pane_proc_start WHERE s.team_slot_id = ? AND s.closed_at IS NULL "
    "ORDER BY s.id DESC LIMIT 1", (int(sys.argv[2]),)).fetchone()
if row is None:
    sys.exit(1)
keys = ["provider", "source", "team_slot_id", "bound_pane_pid", "mailbox_status", "binding_pane_pid", "binding_slot_id"]
print(json.dumps(dict(zip(keys, row))))
PY
}

summary() { # one JSON line on stdout; no tokens
  local outer inner
  outer="$(verify outer)"; inner="$(verify inner)"
  in_ns sh -c 'echo "$(readlink /proc/self/ns/net)"; ip -o link | awk -F": " "{print \$2}"' >"$ROOT/run/ns.txt"
  local pane
  pane="$(in_ns "$ROOT/bin/tmux" list-panes -a -F '#{pane_pid} #{pane_current_command}' | head -1)"
  local reg
  reg="$(registration_row 2>/dev/null || echo '{}')"
  python3 -I - "$ROOT" "$pane" "$reg" <<'PY'
import json, os, sys
root, pane, reg = sys.argv[1:4]
reg = json.loads(reg)
lines = open(os.path.join(root, "run/ns.txt")).read().split()
launch = json.load(open(os.path.join(root, "state/launch.json")))
procs = json.load(open(os.path.join(root, "state/processes.json")))
log = os.path.join(root, "run/stub-requests.jsonl")
pane_pid, _, pane_command = pane.partition(" ")
print(json.dumps({
    "root": root, "net_namespace": lines[0], "links": lines[1:], "uid": os.getuid(), "gid": os.getgid(),
    "preset_id": launch["preset_id"], "slot_id": launch["slot_id"],
    "pane_pid": int(pane_pid) if pane_pid else None, "pane_command": pane_command,
    "registration": reg, "stub_requests": sum(1 for _ in open(log)) if os.path.exists(log) else 0,
    "pids": {name: entry["pid"] for name, entry in procs.items()},
}))
PY
}

# --- status ----------------------------------------------------------------------------

status() {
  load_env
  local outer inner
  outer="$(verify outer)"; inner="$(verify inner)"
  local ev="$ROOT/evidence"
  in_ns sh -c 'printf "{\"net\": \"%s\", \"user\": \"%s\"}\n" "$(readlink /proc/self/ns/net)" "$(readlink /proc/self/ns/user)"' \
    | python3 -I -c 'import json,sys,os; d=json.load(sys.stdin); d["host_net"]=os.readlink("/proc/self/ns/net"); d["host_user"]=os.readlink("/proc/self/ns/user"); print(json.dumps(d))' >"$ev/namespaces.json"
  in_ns ip -o link | awk -F': ' '{print $2}' >"$ev/links.txt"
  python3 -I - "$(proc_json)" >"$ev/processes.txt" <<'PY'
import json, sys
for name, entry in json.load(open(sys.argv[1])).items():
    try:
        cmd = open(f"/proc/{entry['pid']}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmd = "(gone)"
    print(f"{name}\t{entry['pid']}\t{entry['start']}\t{cmd[:200]}")
PY
  in_ns "$ROOT/bin/tmux" list-panes -a -F '{"pane_pid": #{pane_pid}, "pane_current_command": "#{pane_current_command}", "target": "#{session_name}:#{window_index}.#{pane_index}"}' >"$ev/pane.json"
  registration_row >"$ev/registration.json" || echo '{}' >"$ev/registration.json"
  python3 -I - "$(proc_json)" >"$ev/environment-names.json" <<'PY'
import json, sys
names = {}
for name, entry in json.load(open(sys.argv[1])).items():
    try:
        raw = open(f"/proc/{entry['pid']}/environ", "rb").read()
    except OSError:
        continue
    names[name] = sorted({item.split(b"=", 1)[0].decode(errors="replace") for item in raw.split(b"\0") if item})
print(json.dumps(names, indent=1))
PY
  cp "$ROOT/run/stub-requests.jsonl" "$ev/stub-requests.jsonl" 2>/dev/null || : >"$ev/stub-requests.jsonl"
  (cd "$ev" && sha256sum namespaces.json links.txt processes.txt pane.json registration.json \
    environment-names.json stub-requests.jsonl >MANIFEST.sha256)
  note "evidence written to $ev"
  summary
}

# --- exec --------------------------------------------------------------------------------

run_exec() {
  load_env
  [[ "$EXEC_TIMEOUT" =~ ^[0-9]+$ && "$EXEC_TIMEOUT" -ge 1 && "$EXEC_TIMEOUT" -le "$EXEC_CAP" ]] \
    || refuse "--timeout must be 1..$EXEC_CAP seconds"
  [[ $# -gt 0 ]] || refuse "exec needs a command after --"
  local outer inner
  outer="$(verify outer)"; inner="$(verify inner)"
  timeout -k 5 "$EXEC_TIMEOUT" nsenter --preserve-credentials -U -n -t "$outer" \
    nsenter --preserve-credentials -U -t "$inner" env -i "${CLEAN_ENV[@]}" "$@"
}

# --- down ------------------------------------------------------------------------------

down() {
  [[ -f "$ROOT/$MARKER" ]] || refuse "$ROOT is not a kit root (no $MARKER)"
  local names=(cli backend stub tmux inner outer) name entry pid start
  local -a live=()
  for name in "${names[@]}"; do
    entry="$(recorded "$name")"
    [[ -n "$entry" ]] || continue
    read -r pid start <<<"$entry"
    if [[ "$(start_time "$pid" 2>/dev/null || true)" == "$start" ]]; then
      if [[ "$name" == tmux && -f "$ROOT/state/env" ]]; then
        load_env; in_ns "$ROOT/bin/tmux" kill-server 2>/dev/null || true
      fi
      kill -TERM "$pid" 2>/dev/null || true
      live+=("$pid:$start")
    fi
  done
  # Processes the backend started (panes) belong to the private tmux server, stopped above.
  local wait_until=$((SECONDS + DOWN_TERM_WAIT)) item still
  while ((SECONDS < wait_until)); do
    still=0
    for item in "${live[@]}"; do
      [[ "$(start_time "${item%%:*}" 2>/dev/null || true)" == "${item#*:}" ]] && still=1
    done
    ((still)) || break
    sleep 0.2
  done
  for item in "${live[@]}"; do
    if [[ "$(start_time "${item%%:*}" 2>/dev/null || true)" == "${item#*:}" ]]; then
      kill -KILL "${item%%:*}" 2>/dev/null || true
    fi
  done
  sleep 0.3
  # Prove that nothing still runs from the kit root.
  local left
  left="$(python3 -I - "$ROOT" "$$" <<'PY'
import os, sys
root = sys.argv[1].encode()
# The callers of down (this script and its wrappers) name the root in their argv; skip them.
me, pid = set(), str(os.getpid())
while pid not in ("0", "1") and pid not in me:
    me.add(pid)
    try:
        pid = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1]
    except OSError:
        break
found = []
for pid in os.listdir("/proc"):
    if not pid.isdigit() or pid in me:
        continue
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd").encode()
        blob = open(f"/proc/{pid}/cmdline", "rb").read() + open(f"/proc/{pid}/environ", "rb").read()
    except OSError:
        continue
    if cwd.startswith(root) or root in blob:
        found.append(pid)
print(" ".join(found))
PY
)"
  [[ -z "$left" ]] || fail "processes still use the kit root: $left"
  if [[ -f "$ROOT/evidence/MANIFEST.sha256" ]]; then
    (cd "$ROOT/evidence" && sha256sum -c --quiet MANIFEST.sha256) || fail "the evidence manifest does not match"
  fi
  if ((KEEP)); then
    rm -f "$ROOT/state/env"
    note "stopped; kept $ROOT"
  else
    rm -rf "$ROOT"
    note "stopped and removed $ROOT"
  fi
}

# Every command runs under a finite deadline: the public command re-runs itself
# as an internal one under timeout(1). The exec deadline is enforced inside run_exec.
deadline_for() {
  case "$1" in
    up) echo $((UP_DEADLINE + 15)) ;;
    status) echo "$STATUS_DEADLINE" ;;
    down) echo 30 ;;
  esac
}
case "$COMMAND" in
  up | status | down)
    set +e
    timeout -k 5 "$(deadline_for "$COMMAND")" "$SELF" "_$COMMAND" --root "$ROOT" --provider "$PROVIDER" --cli "$CLI" \
      $( ((KEEP)) && echo --keep )
    status=$?
    if [[ $status -eq 124 || $status -eq 137 ]]; then
      echo "isolated-runtime-kit: failed: deadline: $COMMAND did not finish in $(deadline_for "$COMMAND") s" >&2
      [[ "$COMMAND" == up ]] && timeout -k 5 30 "$SELF" _down --root "$ROOT" --keep >&2
      exit 1
    fi
    exit "$status"
    ;;
  _up) up ;;
  _status) status ;;
  _down) down ;;
  exec) run_exec "$@" ;;
  *) refuse "usage: isolated-runtime-kit.sh up|status|exec|down --root DIR ..." ;;
esac
