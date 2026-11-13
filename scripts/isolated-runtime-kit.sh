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
# Ownership. Each `up` creates one instance with a random id. The id is written
# to state/instance.json together with the root directory's identity, and it is
# carried in the argv of the anchors the kit starts. No command signals, enters
# or deletes anything unless the instance file is the caller's own, matches the
# root it sits in, and names namespaces that are not the host's; and every
# target must be one of this instance's live processes:
#   - the launcher and the outer anchor carry the instance id in their argv;
#   - the inner anchor carries it in its argv and owns the recorded user namespace;
#   - every other process is inside the recorded network namespace.
# Every recorded pid is stored with its start time (/proc/<pid>/stat field 22),
# re-checked before use. `down` stops every process inside the kit's network
# namespace and removes the root only after it proves that none remains.
#
# A root left by `down --keep` or a failed `up` is never reused: `up` refuses
# it, and `down` removes it.
#
# Exit codes: 0 ok, 1 failed or incomplete (deadline, unhealthy, unproved
# cleanup), 2 refused (unsafe input or a failed ownership proof). Tokens are
# never printed and never passed in argv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF="$REPO_ROOT/scripts/isolated-runtime-kit.sh"
MARKER=".deck-runtime-kit"

UP_DEADLINE="${RUNTIME_KIT_UP_DEADLINE:-90}"
PREFLIGHT_DEADLINE=10
HEALTH_DEADLINE=30
STUB_DEADLINE=5
REGISTRATION_DEADLINE=30
STATUS_DEADLINE=15
EXEC_DEFAULT=120
EXEC_CAP=600
DOWN_DEADLINE=30
DOWN_TERM_WAIT=10

refuse() { echo "isolated-runtime-kit: refused: $*" >&2; exit 2; }
fail() { echo "isolated-runtime-kit: failed: $*" >&2; exit 1; }
incomplete() { echo "isolated-runtime-kit: incomplete: $*" >&2; exit 1; }
note() { echo "isolated-runtime-kit: $*" >&2; }

# --- Instance and process identity (one Python helper, run isolated) ---------------

KITPY='
import json, os, re, stat, sys

def die(code, message):
    print(message, file=sys.stderr)
    sys.exit(code)

def start_time(pid):
    try:
        return open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None

def link(pid, kind):
    return os.readlink(f"/proc/{pid}/ns/{kind}")

def argv(pid):
    try:
        return open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
    except OSError:
        return []

HOST = {kind: link("self", kind) for kind in ("net", "user")}

def instance(root):
    """The validated instance record, or a refusal (exit 2) before anything destructive."""
    path = os.path.join(root, "state", "instance.json")
    try:
        info = os.lstat(path)
        data = json.load(open(path))
        here = os.stat(root)
    except (OSError, ValueError):
        die(2, "no valid instance record in this root")
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        die(2, "the instance record is not a private file of the caller")
    if not isinstance(data, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(data.get("id", ""))):
        die(2, "the instance record is malformed")
    if (data.get("root_dev"), data.get("root_ino"), data.get("uid")) != (here.st_dev, here.st_ino, os.getuid()):
        die(2, "the instance record belongs to another root or user (copied or forged state)")
    for kind in ("net", "user"):
        value = data.get(kind)
        if value is not None and (not re.fullmatch(kind + r":\[[0-9]+\]", str(value)) or value == HOST[kind]):
            die(2, f"the instance names an invalid or host {kind} namespace")
    return data

def processes(root):
    try:
        data = json.load(open(os.path.join(root, "state", "processes.json")))
    except FileNotFoundError:
        return {}
    except ValueError:
        die(2, "the process record is malformed")
    return data if isinstance(data, dict) else die(2, "the process record is malformed")

def member(inst, name, pid):
    """Whether pid is a process of this instance for the given role (start time checked by the caller)."""
    tag = inst["id"].encode()
    args = argv(pid)
    try:
        if name in ("launcher", "outer"):
            return b"_outer" in args and tag in args and (name == "launcher" or inst["net"] is None
                                                            or link(pid, "net") == inst["net"])
        if name == "inner":
            return args[:1] == [b"runtime-kit-inner-" + tag] and (inst["user"] is None or link(pid, "user") == inst["user"])
        return inst["net"] is not None and link(pid, "net") == inst["net"]
    except OSError:
        return False

def verify(root, name):
    inst = instance(root)
    entry = processes(root).get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
        die(2, f"no recorded {name} process")
    pid = entry["pid"]
    now = start_time(pid)
    if now is None:
        die(3, f"{name} (pid {pid}) is not running")
    if now != entry.get("start"):
        die(2, f"{name} pid {pid} has another start time; it is not the recorded process")
    if not member(inst, name, pid):
        die(2, f"{name} pid {pid} is not a process of this kit instance")
    print(pid)

def members(root):
    """Own processes of this instance: in its network namespace, or carrying its id in argv.

    Membership of the recorded network namespace counts only while this instance own
    outer anchor (its id and root in argv) is alive inside that namespace. Otherwise the
    recorded namespace id is unproved, and any process in it is reported, never signalled.
    """
    inst = instance(root)
    tag, me = inst["id"].encode(), {os.getpid(), os.getppid()}
    anchored = inst["net"] is None
    for entry in os.listdir("/proc"):
        if entry.isdigit() and not anchored:
            args = argv(int(entry))
            try:
                anchored = (b"_outer" in args and tag in args and root.encode() in args
                            and link(int(entry), "net") == inst["net"])
            except OSError:
                pass
    found, unproved, unreadable = [], [], []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) in me:
            continue
        pid = int(entry)
        try:
            if os.stat(f"/proc/{pid}").st_uid != os.getuid():
                continue
        except OSError:
            continue
        try:
            inside = inst["net"] is not None and link(pid, "net") == inst["net"]
        except FileNotFoundError:
            continue
        except OSError:
            unreadable.append(pid)
            continue
        start = start_time(pid)
        if start is None:
            continue
        if tag in argv(pid) or (inside and anchored):
            found.append(f"{pid}:{start}")
        elif inside:
            unproved.append(f"{pid}:{start}")
    print(" ".join(found))
    if unproved:
        print("unproved " + " ".join(unproved), file=sys.stderr)
        sys.exit(5)
    if unreadable:
        print("unreadable " + " ".join(map(str, unreadable)), file=sys.stderr)
        sys.exit(4)

def record(root, name, pid):
    start = start_time(pid)
    if start is None:
        die(2, f"{name} (pid {pid}) is gone before it could be recorded")
    path = os.path.join(root, "state", "processes.json")
    data = processes(root)
    data[name] = {"pid": int(pid), "start": start}
    tmp = path + ".tmp"
    with open(tmp, "w") as out:
        json.dump(data, out)
    os.replace(tmp, path)

def set_instance(root, ident, net, user):
    path = os.path.join(root, "state", "instance.json")
    here = os.stat(root)
    data = {"id": ident, "root_dev": here.st_dev, "root_ino": here.st_ino, "uid": os.getuid(),
            "net": net or None, "user": user or None}
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out)
    os.replace(path + ".tmp", path)

command, root, *rest = sys.argv[1:]
if command == "instance":
    data = instance(root)
    print(data["id"], data["net"] or "-", data["user"] or "-")
elif command == "verify":
    verify(root, rest[0])
elif command == "members":
    members(root)
elif command == "record":
    record(root, rest[0], int(rest[1]))
elif command == "set-instance":
    set_instance(root, *rest)
else:
    die(2, "unknown helper command")
'
kitpy() { python3 -I -c "$KITPY" "$@"; }

verify() { # name -> pid of this instance's live process for that role; refuses otherwise
  local out code=0
  out="$(kitpy verify "$ROOT" "$1" 2>&1)" || code=$?
  if ((code)); then
    ((code == 3)) && incomplete "$out"
    refuse "$out"
  fi
  echo "$out"
}
record() { kitpy record "$ROOT" "$1" "$2" || refuse "could not record $1"; }

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
  ROOT="$1" CALLER_UID="$2" CALLER_GID="$3" INSTANCE="$4"
  ready="$ROOT/state/run-$INSTANCE"
  ip link set lo up
  links="$(ip -o link | awk -F': ' '{print $2}' | tr '\n' ' ')"
  [[ "$links" == "lo " ]] || { echo "links: $links" >"$ready/outer.refused"; exit 2; }
  echo "$$" >"$ready/outer.pid"
  unshare --user --map-user="$CALLER_UID" --map-group="$CALLER_GID" "$SELF" _inner "$ROOT" "$INSTANCE" &
  inner=$!
  trap 'kill -TERM "$inner" 2>/dev/null; exit 0' TERM INT
  wait "$inner"
  exit 0
fi
if [[ "$COMMAND" == _inner ]]; then
  ROOT="$1" INSTANCE="$2"
  echo "$$ $(id -u) $(id -g) $(readlink /proc/self/ns/net) $(readlink /proc/self/ns/user)" >"$ROOT/state/run-$INSTANCE/inner.id"
  exec -a "runtime-kit-inner-$INSTANCE" sleep infinity
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
  # A root kept by `down --keep` or a failed `up` is never reused: its records and
  # readiness files belong to another instance.
  if [[ -d "$ROOT/state" && -n "$(ls -A "$ROOT/state")" ]]; then
    refuse "$ROOT holds a retained instance; run down to remove it first"
  fi
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
  chmod 700 "$ROOT/t" "$ROOT/state"
  local instance
  instance="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  kitpy set-instance "$ROOT" "$instance" "" ""
  local ready="$ROOT/state/run-$instance"
  mkdir -p "$ready"
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

  # --- Preflight: anchors, uid mapping, two-step entry (before any backend) -----------
  local preflight=$((SECONDS + PREFLIGHT_DEADLINE))
  # The anchors start from an empty environment too: nothing of the caller's session
  # (tokens, sockets, identities) may live inside the namespaces. The launcher is
  # recorded at once, so a failure at any later point can still stop it.
  setsid env -i "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "HOME=$ROOT/home" "LANG=C.UTF-8" \
    unshare --user --map-root-user --net --kill-child "$SELF" _outer "$ROOT" "$(id -u)" "$(id -g)" "$instance" \
    </dev/null >"$ROOT/logs/anchor.log" 2>&1 &
  record launcher "$!"
  [[ "${RUNTIME_KIT_TEST_FAULT:-}" != after_anchor_spawn ]] || { sleep 0.3; fail "injected fault after the anchor spawn"; }
  until [[ -s "$ready/inner.id" || -f "$ready/outer.refused" ]]; do
    ((SECONDS < preflight)) || fail "preflight deadline: the namespace anchors did not start"
    sleep 0.1
  done
  [[ ! -f "$ready/outer.refused" ]] || refuse "the network namespace is not loopback-only ($(cat "$ready/outer.refused"))"
  record outer "$(cat "$ready/outer.pid")"
  local inner_pid inner_uid inner_gid inner_net inner_user
  read -r inner_pid inner_uid inner_gid inner_net inner_user <"$ready/inner.id"
  record inner "$inner_pid"
  if [[ "${RUNTIME_KIT_TEST_FAULT:-}" == uid_mismatch ]]; then inner_uid=$((inner_uid + 1)); fi
  [[ "$inner_uid" == "$(id -u)" && "$inner_gid" == "$(id -g)" ]] \
    || refuse "the inner namespace maps uid/gid $inner_uid/$inner_gid, not the caller's $(id -u)/$(id -g)"
  [[ "$inner_net" != "$(readlink /proc/self/ns/net)" && "$inner_user" != "$(readlink /proc/self/ns/user)" ]] \
    || refuse "the kit shares a host namespace"
  local joined
  joined="$(in_ns sh -c 'echo "$(id -u) $(id -g) $(readlink /proc/self/ns/net) $(readlink /proc/self/ns/user) $(ip -o link | wc -l)"')" \
    || refuse "entering the kit namespaces failed"
  if [[ "${RUNTIME_KIT_TEST_FAULT:-}" == join_mismatch ]]; then joined="$joined mismatch"; fi
  [[ "$joined" == "$(id -u) $(id -g) $inner_net $inner_user 1" ]] \
    || refuse "the namespace join check failed (got: $joined)"
  kitpy set-instance "$ROOT" "$instance" "$inner_net" "$inner_user"
  kitpy instance "$ROOT" >/dev/null || refuse "the instance record did not validate"
  printf '%s\n' "${CLEAN_ENV[@]}" >"$ROOT/state/env"

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
  # Tokens live only in 0600 files. Every reader opens the file itself: no token is
  # ever an argument, since argv is visible to every process listing.
  (umask 077
   od -An -N16 -tx1 /dev/urandom | tr -d ' \n' >"$ROOT/state/run-token"
   printf 'runtime-kit-operator-%s' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" >"$ROOT/state/operator-token"
   {
     printf 'export %q\n' "DATABASE_URL=sqlite+aiosqlite:///$ROOT/kit.db" "TEST_INSTANCE=1" "TEST_INSTANCE_ROOT=$ROOT" \
       "GITHUB_TOKEN=" "GITHUB_APP_ID=" "GITHUB_APP_PRIVATE_KEY_PATH=" "GITHUB_COORDINATION_HOLD_PATHS=[]" \
       "HOST=127.0.0.1" "PORT=$port" "PYTHONDONTWRITEBYTECODE=1" "PYTHONPATH=$REPO_ROOT/backend"
     printf 'TEST_INSTANCE_TOKEN="$(cat "%s")"; export TEST_INSTANCE_TOKEN\n' "$ROOT/state/run-token"
     printf 'OPERATOR_TOKEN="$(cat "%s")"; export OPERATOR_TOKEN\n' "$ROOT/state/operator-token"
   } >"$ROOT/state/backend.env")
  printf '#!/bin/sh\n. "%s"\ncd "%s"\nexec "%s" -m uvicorn app.main:app --app-dir "%s" --host 127.0.0.1 --port %s --log-level warning\n' \
    "$ROOT/state/backend.env" "$ROOT/run" "$python" "$REPO_ROOT/backend" "$port" >"$ROOT/run/backend.sh"
  chmod 700 "$ROOT/run/backend.sh"
  spawn backend "$ROOT/logs/backend.log" "$ROOT/run/backend.sh"
  local health=$((SECONDS + HEALTH_DEADLINE))
  until backend_healthy "$python"; do
    ((SECONDS < health && SECONDS < deadline)) || fail "deadline: the isolated backend did not report healthy"
    sleep 0.5
  done

  # --- Team slot, real launch, Agent Mail registration --------------------------------
  git -C "$ROOT/home/work" init -q 2>/dev/null || true
  local launch
  launch="$(in_ns "$python" -I - "$port" "$ROOT/state/operator-token" "$PROVIDER" "$ROOT/home/work" <<'PY'
import json, sys, urllib.error, urllib.request
port, token_file, provider, work = sys.argv[1:5]
token = open(token_file).read().strip()
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
  verify cli >/dev/null

  trap - EXIT
  summary
}

backend_healthy() { # python: /health must report this run's token (read from its file, not argv)
  in_ns "$1" -I - "$ROOT/state/run-token" <<'PY' 2>/dev/null
import json, sys, urllib.request
token = open(sys.argv[1]).read().strip()
body = json.load(urllib.request.urlopen("http://127.0.0.1:18780/health", timeout=2))
sys.exit(0 if token and body.get("test_instance", {}).get("token") == token else 1)
PY
}

registration_row() { # the registered session and its pane binding, read from the kit's own database
  python3 -I - "$ROOT/kit.db" "$ROOT/state/launch.json" <<'PY'
import json, sqlite3, sys
slot = int(json.load(open(sys.argv[2]))["slot_id"])
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
row = db.execute(
    "SELECT s.provider, s.source, s.team_slot_id, s.bound_pane_pid, s.mailbox_status, b.pane_pid, b.slot_id "
    "FROM mail_agent_sessions s JOIN agent_pane_bindings b ON b.pane_pid = s.bound_pane_pid "
    "AND b.pane_proc_start = s.bound_pane_proc_start WHERE s.team_slot_id = ? AND s.closed_at IS NULL "
    "ORDER BY s.id DESC LIMIT 1", (slot,)).fetchone()
if row is None:
    sys.exit(1)
keys = ["provider", "source", "team_slot_id", "bound_pane_pid", "mailbox_status", "binding_pane_pid", "binding_slot_id"]
print(json.dumps(dict(zip(keys, row))))
PY
}

summary() { # one JSON line on stdout; no tokens
  in_ns sh -c 'echo "$(readlink /proc/self/ns/net)"; ip -o link | awk -F": " "{print \$2}"' >"$ROOT/run/ns.txt"
  local pane reg
  pane="$(in_ns "$ROOT/bin/tmux" list-panes -a -F '#{pane_pid} #{pane_current_command}' | head -1)"
  reg="$(registration_row)" || incomplete "no registered session with a pane binding"
  python3 -I - "$ROOT" "$pane" "$reg" <<'PY'
import json, os, sys
root, pane, reg = sys.argv[1:4]
lines = open(os.path.join(root, "run/ns.txt")).read().split()
launch = json.load(open(os.path.join(root, "state/launch.json")))
procs = json.load(open(os.path.join(root, "state/processes.json")))
log = os.path.join(root, "run/stub-requests.jsonl")
pane_pid, _, pane_command = pane.partition(" ")
print(json.dumps({
    "root": root, "net_namespace": lines[0], "links": lines[1:], "uid": os.getuid(), "gid": os.getgid(),
    "preset_id": launch["preset_id"], "slot_id": launch["slot_id"],
    "pane_pid": int(pane_pid) if pane_pid else None, "pane_command": pane_command,
    "registration": json.loads(reg), "stub_requests": sum(1 for _ in open(log)) if os.path.exists(log) else 0,
    "pids": {name: entry["pid"] for name, entry in procs.items() if name != "launcher"},
}))
PY
}

# --- status ----------------------------------------------------------------------------

status() {
  local ev="$ROOT/evidence"
  # A stale manifest must never pass for current evidence.
  rm -f "$ev/MANIFEST.sha256"
  kitpy instance "$ROOT" >/dev/null || refuse "this root has no valid kit instance"
  load_env
  local name python="${PYTHON:-}"
  for name in outer inner tmux stub backend cli; do
    verify "$name" >/dev/null
  done
  if [[ -z "$python" ]]; then
    if [[ -x "$REPO_ROOT/backend/venv/bin/python" ]]; then python="$REPO_ROOT/backend/venv/bin/python"; else python="$(command -v python3)"; fi
  fi
  backend_healthy "$python" || incomplete "the isolated backend does not report this run as healthy"
  registration_row >/dev/null || incomplete "no registered session with a pane binding"

  in_ns sh -c 'printf "{\"net\": \"%s\", \"user\": \"%s\"}\n" "$(readlink /proc/self/ns/net)" "$(readlink /proc/self/ns/user)"' \
    | python3 -I -c 'import json,sys,os; d=json.load(sys.stdin); d["host_net"]=os.readlink("/proc/self/ns/net"); d["host_user"]=os.readlink("/proc/self/ns/user"); print(json.dumps(d))' >"$ev/namespaces.json"
  in_ns ip -o link | awk -F': ' '{print $2}' >"$ev/links.txt"
  python3 -I - "$ROOT/state/processes.json" >"$ev/processes.txt" <<'PY'
import json, sys
for name, entry in json.load(open(sys.argv[1])).items():
    try:
        cmd = open(f"/proc/{entry['pid']}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmd = "(gone)"
    print(f"{name}\t{entry['pid']}\t{entry['start']}\t{cmd[:200]}")
PY
  in_ns "$ROOT/bin/tmux" list-panes -a -F '{"pane_pid": #{pane_pid}, "pane_current_command": "#{pane_current_command}", "target": "#{session_name}:#{window_index}.#{pane_index}"}' >"$ev/pane.json"
  registration_row >"$ev/registration.json"
  python3 -I - "$ROOT/state/processes.json" >"$ev/environment-names.json" <<'PY'
import json, sys
names = {}
for name, entry in json.load(open(sys.argv[1])).items():
    if name == "launcher":
        continue
    try:
        raw = open(f"/proc/{entry['pid']}/environ", "rb").read()
    except OSError:
        continue
    names[name] = sorted({item.split(b"=", 1)[0].decode(errors="replace") for item in raw.split(b"\0") if item})
print(json.dumps(names, indent=1))
PY
  cp "$ROOT/run/stub-requests.jsonl" "$ev/stub-requests.jsonl" 2>/dev/null || : >"$ev/stub-requests.jsonl"
  # The identities are checked again after capture: evidence of a process that
  # changed while it was read is not published.
  for name in outer inner tmux stub backend cli; do
    verify "$name" >/dev/null
  done
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
  # Ownership first: nothing is signalled or deleted unless this root holds a valid
  # instance of the caller's own (not copied, not forged, no host namespace).
  local inst
  inst="$(kitpy instance "$ROOT")" || refuse "this root has no valid kit instance; nothing was signalled or removed"
  # Stop the private tmux server through the namespaces while the anchors live.
  if [[ -f "$ROOT/state/env" ]] && kitpy verify "$ROOT" outer >/dev/null 2>&1 && kitpy verify "$ROOT" inner >/dev/null 2>&1; then
    load_env
    in_ns "$ROOT/bin/tmux" kill-server 2>/dev/null || true
  fi
  # Every process of this instance: inside its network namespace, or carrying its
  # id in argv (the launcher and anchors, also before the namespace was recorded).
  local targets code=0 until=$((SECONDS + DOWN_TERM_WAIT)) item
  targets="$(kitpy members "$ROOT")" || code=$?
  ((code != 5)) || incomplete "processes run in the recorded namespace, but no live anchor of this instance proves it is the kit's; nothing was signalled and the root is kept"
  ((code == 0)) || incomplete "some processes of the caller could not be inspected; the root is kept"
  for item in $targets; do kill -TERM "${item%%:*}" 2>/dev/null || true; done
  while ((SECONDS < until)); do
    targets="$(kitpy members "$ROOT" 2>/dev/null)" || true
    [[ -n "$targets" ]] || break
    sleep 0.2
  done
  for item in $targets; do
    # KILL only a process that is still the same one (pid and start time).
    [[ "$(kitpy members "$ROOT" 2>/dev/null)" == *"$item"* ]] && kill -KILL "${item%%:*}" 2>/dev/null || true
  done
  sleep 0.3
  # Prove containment: no process of this instance remains, and none could not be read.
  code=0
  targets="$(kitpy members "$ROOT")" || code=$?
  ((code == 0)) || incomplete "containment could not be proved (unreadable or unproved processes); the root is kept"
  [[ -z "$targets" ]] || incomplete "processes of this kit instance are still running: $targets; the root is kept"
  if [[ -f "$ROOT/evidence/MANIFEST.sha256" ]]; then
    (cd "$ROOT/evidence" && sha256sum -c --quiet MANIFEST.sha256) || fail "the evidence manifest does not match; the root is kept"
  fi
  if ((KEEP)); then
    rm -f "$ROOT/state/env"
    note "stopped; kept $ROOT (it can only be removed with down, not reused)"
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
    down) echo "$DOWN_DEADLINE" ;;
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
      [[ "$COMMAND" == up ]] && timeout -k 5 "$DOWN_DEADLINE" "$SELF" _down --root "$ROOT" --keep >&2
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
