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
import hashlib, json, os, re, signal, stat, sys

ROLES_ORDER = ["cli", "stub", "backend", "tmux", "inner", "outer"]
SERVICES = {"cli", "stub", "backend", "tmux"}
# Every role has exactly one expected parent role; the launcher is a parent witness only.
PARENT = {"outer": "launcher", "inner": "outer", "tmux": "inner", "stub": "inner", "backend": "inner", "cli": "tmux"}
KNOWN_ROLES = set(PARENT) | {"launcher"}

def die(code, message):
    print(message, file=sys.stderr)
    sys.exit(code)

def proc_stat(pid):
    """(start time, ppid) from /proc/<pid>/stat, or None when the process is gone."""
    try:
        fields = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None
    return fields[19], int(fields[1])

def argv_hash(pid):
    try:
        return hashlib.sha256(open(f"/proc/{pid}/cmdline", "rb").read()).hexdigest()
    except OSError:
        return None

def link(pid, kind):
    return os.readlink(f"/proc/{pid}/ns/{kind}")

def argv_list(pid):
    try:
        return open(f"/proc/{pid}/cmdline", "rb").read().split(bytes(1))[:-1]
    except OSError:
        return None

def own_pids():
    """Pids of the processes of the caller."""
    found = []
    for name in os.listdir("/proc"):
        if name.isdigit():
            try:
                if os.stat(f"/proc/{name}").st_uid == os.getuid():
                    found.append(int(name))
            except OSError:
                pass
    return found

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
    if not isinstance(data, dict):
        die(2, "the process record is malformed")
    return data

KEYS = {"pid": int, "start": str, "argv": str, "ppid": int, "pstart": str}

def entry_of(procs, name):
    entry = procs.get(name)
    if not isinstance(entry, dict) or any(not isinstance(entry.get(key), kind) for key, kind in KEYS.items()):
        return None
    return entry

def anchor_argv_ok(inst, root, name, pid):
    args = argv_list(pid)
    if not args or len(args) < 5:
        return False
    tail = [a.decode(errors="replace") for a in args]
    if name == "outer":
        expected = ["_outer", root, str(inst["uid"]), str(os.getgid()), inst["id"]]
    else:
        expected = ["_inner", root, inst["id"]]
    return tail[-len(expected):] == expected and tail[-len(expected) - 1].endswith("/isolated-runtime-kit.sh")

def namespaces_ok(inst, procs, name, pid):
    """Role-specific namespace proof; a host-namespace anchor never qualifies."""
    try:
        net, user = link(pid, "net"), link(pid, "user")
    except OSError:
        return f"{name} pid {pid} cannot be inspected"
    if net == HOST["net"] or user == HOST["user"]:
        return f"{name} pid {pid} runs in a host namespace"
    if inst["net"] is not None:
        if net != inst["net"]:
            return f"{name} pid {pid} is outside the kit network namespace"
        if name == "inner" and user != inst["user"]:
            return f"{name} pid {pid} is outside the kit user namespace"
        return "ok"
    # Preflight: only the anchors may exist; both must share one non-host network namespace.
    if name not in ("outer", "inner"):
        return f"{name} cannot exist before the kit namespaces are recorded"
    other = entry_of(procs, "inner" if name == "outer" else "outer")
    try:
        if other is None or proc_stat(other["pid"]) is None:
            return "the other anchor is not running"
        other_net, other_user = link(other["pid"], "net"), link(other["pid"], "user")
    except OSError:
        return "the other anchor cannot be inspected"
    if other_net != net:
        return "the anchors are not in one network namespace"
    inner_user = user if name == "inner" else other_user
    outer_user = other_user if name == "inner" else user
    if inner_user in (HOST["user"], outer_user):
        return "the inner anchor is not in its own user namespace"
    return "ok"

def check(inst, procs, name, entry, root=None, argv=True):
    """The word gone, the word ok, or a reason: the full recorded identity, field by field."""
    if name not in PARENT:
        return f"{name} is not a signallable kit role"
    pid = entry["pid"]
    now = proc_stat(pid)
    if now is None:
        return "gone"
    start, ppid = now
    if start != entry["start"]:
        return "gone"  # the recorded process has exited; this pid now names another process
    if argv and argv_hash(pid) != entry["argv"]:
        return f"{name} pid {pid} has another command line"
    parent = proc_stat(entry["ppid"])
    if ppid != entry["ppid"] or parent is None or parent[0] != entry["pstart"]:
        return f"{name} pid {pid} no longer has its recorded parent"
    expected = entry_of(procs, PARENT[name])
    if expected is None or (expected["pid"], expected["start"]) != (entry["ppid"], entry["pstart"]):
        return f"{name} pid {pid} is not a child of the recorded {PARENT[name]}"
    if name in ("outer", "inner") and root is not None and not anchor_argv_ok(inst, root, name, pid):
        return f"{name} pid {pid} is not this instance anchor"
    return namespaces_ok(inst, procs, name, pid)

def verify(root, name):
    inst, procs = instance(root), processes(root)
    entry = entry_of(procs, name)
    if entry is None:
        die(2, f"no recorded {name} process")
    result = check(inst, procs, name, entry, root)
    if result == "gone":
        die(3, f"{name} (pid {entry.get(chr(112) + chr(105) + chr(100))}) is not running")
    if result != "ok":
        die(2, result)
    print(entry["pid"])

def unrecorded(inst, procs, root):
    """Own processes inside the kit network namespace that are not currently proved roles."""
    if inst["net"] is None:
        return [], []
    proved = set()
    for name in ROLES_ORDER:
        entry = entry_of(procs, name)
        if entry is not None and check(inst, procs, name, entry, root) == "ok":
            proved.add(entry["pid"])
    # The launcher (unshare --kill-child) joins the new network namespace before it forks the
    # outer anchor. It is excluded only while its own start and command line still match and
    # it is still the proved parent of the outer anchor; it is never a signal target.
    launcher, outer = entry_of(procs, "launcher"), entry_of(procs, "outer")
    if (launcher is not None and outer is not None and "outer" in procs
            and proc_stat(launcher["pid"]) is not None and proc_stat(launcher["pid"])[0] == launcher["start"]
            and argv_hash(launcher["pid"]) == launcher["argv"]
            and (launcher["pid"], launcher["start"]) == (outer["ppid"], outer["pstart"])
            and outer["pid"] in proved):
        proved.add(launcher["pid"])
    found, unreadable = [], []
    for pid in own_pids():
        if pid in proved or pid in (os.getpid(), os.getppid()):
            continue
        try:
            if link(pid, "net") == inst["net"]:
                found.append(pid)
        except FileNotFoundError:
            continue
        except OSError:
            unreadable.append(pid)
    return found, unreadable

def plan(root):
    """Read-only teardown plan: every proof first, then the ordered targets; never signals."""
    inst, procs = instance(root), processes(root)
    targets, problems = [], []
    for name in procs:
        if name not in KNOWN_ROLES:
            problems.append(f"unknown role record: {name}")
    for name in ROLES_ORDER:
        if name not in procs:
            continue
        entry = entry_of(procs, name)
        if entry is None:
            problems.append(f"{name} record is malformed")
            continue
        result = check(inst, procs, name, entry, root)
        if result == "ok":
            targets.append(name)
        elif result != "gone":
            problems.append(result)
    found, unreadable = unrecorded(inst, procs, root)
    if found:
        problems.append("unrecorded processes in the kit namespace: " + " ".join(map(str, found)))
    if unreadable:
        problems.append("processes that cannot be inspected: " + " ".join(map(str, unreadable)))
    return {"targets": targets, "problems": problems}

def send(root, name, signame, dry):
    """Open a pidfd first, then prove the full recorded identity, then signal through that pidfd."""
    inst, procs = instance(root), processes(root)
    if name not in PARENT:
        die(2, f"{name} is never a signal target")
    entry = entry_of(procs, name)
    if entry is None:
        die(2, f"no recorded {name} process")
    if os.environ.get("RUNTIME_KIT_TEST_NO_PIDFD") or not hasattr(os, "pidfd_open") \
            or not hasattr(signal, "pidfd_send_signal"):
        die(4, "pidfd support is unavailable; nothing was signalled")
    try:
        fd = os.pidfd_open(entry["pid"])
    except ProcessLookupError:
        die(3, f"{name} is gone")
    except OSError as exc:
        die(4, f"cannot open a pidfd for {name}: {exc}")
    try:
        result = check(inst, procs, name, entry, root)
        if result == "gone":
            die(3, f"{name} is gone")
        if result != "ok":
            die(2, result + "; nothing was signalled")
        if not dry:
            signal.pidfd_send_signal(fd, getattr(signal, "SIG" + signame))
        print("checked" if dry else "signalled")
    finally:
        os.close(fd)

def record(root, name, pid):
    pid = int(pid)
    now = proc_stat(pid)
    if now is None:
        die(2, f"{name} (pid {pid}) is gone before it could be recorded")
    parent = proc_stat(now[1])
    digest = argv_hash(pid)
    if parent is None or digest is None:
        die(2, f"{name} (pid {pid}) cannot be recorded")
    path = os.path.join(root, "state", "processes.json")
    data = processes(root)
    data[name] = {"pid": pid, "start": now[0], "argv": digest, "ppid": now[1], "pstart": parent[0]}
    tmp = path + ".tmp"
    with open(tmp, "w") as out:
        json.dump(data, out)
    os.replace(tmp, path)
    print(now[1])

def refresh(root, name):
    """After an exec: only the argv may change; pid, start, parent and role proof must hold first."""
    inst, procs = instance(root), processes(root)
    entry = entry_of(procs, name)
    if entry is None:
        die(2, f"no recorded {name} process")
    result = check(inst, procs, name, entry, root, argv=False)
    if result != "ok":
        die(2, f"{name} cannot be refreshed: {result}")
    digest = argv_hash(entry["pid"])
    if digest is None or proc_stat(entry["pid"]) != (entry["start"], entry["ppid"]):
        die(2, f"{name} changed while it was refreshed")
    entry["argv"] = digest
    path = os.path.join(root, "state", "processes.json")
    with open(path + ".tmp", "w") as out:
        json.dump(procs, out)
    os.replace(path + ".tmp", path)

def set_instance(root, ident, net, user):
    path = os.path.join(root, "state", "instance.json")
    here = os.stat(root)
    data = {"id": ident, "root_dev": here.st_dev, "root_ino": here.st_ino, "uid": os.getuid(),
            "net": net or None, "user": user or None}
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(data, out)
    os.replace(path + ".tmp", path)

def main():
    command, root, *rest = sys.argv[1:]
    if command == "instance":
        data = instance(root)
        print(data["id"], data["net"] or "-", data["user"] or "-")
    elif command == "verify":
        verify(root, rest[0])
    elif command == "plan-teardown":
        result = plan(root)
        print(json.dumps(result))
        sys.exit(0 if not result["problems"] else 5)
    elif command == "check-signal":
        send(root, rest[0], rest[1] if len(rest) > 1 else "TERM", dry=True)
    elif command == "signal":
        send(root, rest[0], rest[1], dry=False)
    elif command == "gone":
        entry = entry_of(processes(root), rest[0])
        now = None if entry is None else proc_stat(entry["pid"])
        sys.exit(0 if entry is not None and (now is None or now[0] != entry["start"]) else 1)
    elif command == "refresh":
        refresh(root, rest[0])
    elif command == "record":
        record(root, rest[0], rest[1])
    elif command == "set-instance":
        set_instance(root, *rest)
    else:
        die(2, "unknown helper command")

if __name__ == "__main__":
    main()
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
record() { kitpy record "$ROOT" "$1" "$2" >/dev/null || refuse "could not record $1"; }

# --- Namespace entry -----------------------------------------------------------------

in_ns() { # run a command inside the kit namespaces, with the allowlisted environment
  local outer inner
  outer="$(verify outer)"
  inner="$(verify inner)"
  nsenter --preserve-credentials -U -n -t "$outer" \
    nsenter --preserve-credentials -U -t "$inner" \
    env -i "${CLEAN_ENV[@]}" "$@"
}

spawn() { # name log argv... : the inner anchor starts it as its own child; it is recorded with that parent.
  local name="$1" log="$2" ready="$ROOT/state/run-$INSTANCE_ID" req pid inner i
  shift 2
  inner="$(verify inner)"
  req="$(mktemp -d "$ready/req-XXXXXX")"
  printf '%s\0' "$@" >"$req/argv"
  printf '%s' "$log" >"$req/log"
  printf '%s\n' "$req" >"$ready/spawn.fifo"
  for i in $(seq 1 50); do [[ -s "$req/pid" ]] && break; sleep 0.1; done
  [[ -s "$req/pid" ]] || fail "the inner anchor did not start $name"
  pid="$(cat "$req/pid")"
  # Record only after exec: until then the child still shows the anchor's command line.
  for i in $(seq 1 50); do
    cmp -s "/proc/$pid/cmdline" "/proc/$inner/cmdline" || break
    sleep 0.05
  done
  record "$name" "$pid"
  [[ "$(kitpy verify "$ROOT" "$name" 2>/dev/null)" == "$pid" ]] || refuse "$name was not started by the recorded inner anchor"
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
  trap 'exit 0' TERM INT  # no forwarding: down stops the inner anchor first, by pidfd
  wait "$inner"
  exit 0
fi
if [[ "$COMMAND" == _inner ]]; then
  # The inner anchor maps back to the caller and starts every kit service as its own
  # child (requests arrive on a private FIFO), so no recorded process is ever reparented.
  ROOT="$1" INSTANCE="$2"
  ready="$ROOT/state/run-$INSTANCE"
  mkfifo -m 600 "$ready/spawn.fifo"
  trap 'exit 0' TERM INT
  exec 3<>"$ready/spawn.fifo"
  echo "$$ $(id -u) $(id -g) $(readlink /proc/self/ns/net) $(readlink /proc/self/ns/user)" >"$ready/inner.id"
  while read -r req <&3; do
    [[ "$req" == "$ready"/req-* && -f "$req/argv" && -f "$ROOT/state/env" ]] || continue
    mapfile -d '' -t argv <"$req/argv"
    mapfile -t envl <"$ROOT/state/env"
    env -i "${envl[@]}" "${argv[@]}" </dev/null >"$(cat "$req/log")" 2>&1 &
    echo "$!" >"$req/pid.tmp"
    mv "$req/pid.tmp" "$req/pid"
  done
  exit 0
fi
if [[ "$COMMAND" == _kitpy ]]; then  # the helper, for the kit's own tests
  kitpy "$@"
  exit $?
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
  mkdir -p "$ROOT/state" "$ROOT/home/work" "$ROOT/bin" "$ROOT/run" "$ROOT/t" "$ROOT/evidence.d" "$ROOT/logs"
  chmod 700 "$ROOT/t" "$ROOT/state"
  local instance
  instance="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  INSTANCE_ID="$instance"
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
  until [[ -s "$ready/inner.id" || -f "$ready/outer.refused" ]]; do
    ((SECONDS < preflight)) || fail "preflight deadline: the namespace anchors did not start"
    sleep 0.1
  done
  [[ ! -f "$ready/outer.refused" ]] || refuse "the network namespace is not loopback-only ($(cat "$ready/outer.refused"))"
  record outer "$(cat "$ready/outer.pid")"
  local inner_pid inner_uid inner_gid inner_net inner_user
  read -r inner_pid inner_uid inner_gid inner_net inner_user <"$ready/inner.id"
  record inner "$inner_pid"
  [[ "${RUNTIME_KIT_TEST_FAULT:-}" != after_anchor_spawn ]] || fail "injected fault after the anchor spawn"
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

  # --- Private tmux server: a foreground child of the inner anchor, on the kit's socket --
  spawn tmux "$ROOT/logs/tmux.log" "$tmux_bin" -D -f /dev/null -S "$ROOT/t/s"
  local i
  for i in $(seq 1 50); do [[ -S "$ROOT/t/s" ]] && break; sleep 0.1; done
  in_ns "$ROOT/bin/tmux" new-session -d -s kit-probe "sleep 600" </dev/null >/dev/null 2>&1
  [[ "$(in_ns "$ROOT/bin/tmux" display-message -p -t '=kit-probe' '#{socket_path}')" == "$ROOT/t/s" ]] \
    || refuse "tmux used a socket outside the kit root"
  [[ "$(in_ns "$ROOT/bin/tmux" list-sessions -F '#{session_name}')" == kit-probe ]] || refuse "the tmux server is not private"
  [[ "$(in_ns "$ROOT/bin/tmux" display-message -p '#{pid}')" == "$(verify tmux)" ]] \
    || refuse "the tmux server is not the recorded one"
  in_ns "$ROOT/bin/tmux" kill-session -t '=kit-probe'

  # --- Stub model provider -------------------------------------------------------------
  if [[ "${RUNTIME_KIT_TEST_FAULT:-}" == stub_ignores_term ]]; then  # a recorded child that ignores TERM
    spawn stub "$ROOT/logs/stub.log" python3 -c \
      "import runpy, signal, sys; signal.signal(signal.SIGTERM, signal.SIG_IGN); sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name=chr(95) * 2 + chr(109) + chr(97) + chr(105) + chr(110) + chr(95) * 2)" \
      "$REPO_ROOT/scripts/runtime-kit/stub_provider.py" --port "$stub_port" --log "$ROOT/run/stub-requests.jsonl"
  else
    spawn stub "$ROOT/logs/stub.log" \
      python3 "$REPO_ROOT/scripts/runtime-kit/stub_provider.py" --port "$stub_port" --log "$ROOT/run/stub-requests.jsonl"
  fi
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
  # The launcher script has exec'd into the server by now: record its final command line.
  kitpy refresh "$ROOT" backend || refuse "the backend could not be refreshed with an unchanged identity"
  verify backend >/dev/null

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

  # The launched pane is the CLI: record it at once (parent = the recorded tmux server),
  # so any later failure can still stop it with a proved identity.
  local pane_pid="" i
  for i in $(seq 1 50); do
    pane_pid="$(in_ns "$ROOT/bin/tmux" list-panes -a -F '#{pane_pid}' 2>/dev/null | head -1)"
    [[ -n "$pane_pid" ]] && break
    sleep 0.1
  done
  [[ "$pane_pid" =~ ^[0-9]+$ ]] || fail "the launch started no pane"
  # Wait until the pane's command line is stable (a CLI may exec once at start).
  local last="" now stable=0
  for i in $(seq 1 50); do
    now="$(sha256sum "/proc/$pane_pid/cmdline" 2>/dev/null | cut -c1-64)"
    if [[ -n "$now" && "$now" == "$last" ]]; then stable=$((stable + 1)); else stable=0; fi
    last="$now"
    ((stable >= 5)) && break
    sleep 0.1
  done
  record cli "$pane_pid"
  verify cli >/dev/null
  python3 -I - "$ROOT/state/processes.json" <<'PY' || refuse "the CLI pane is not a child of the recorded tmux server"
import json, sys
procs = json.load(open(sys.argv[1]))
sys.exit(0 if procs["cli"]["ppid"] == procs["tmux"]["pid"] and procs["cli"]["pstart"] == procs["tmux"]["start"] else 1)
PY

  local registered=$((SECONDS + REGISTRATION_DEADLINE))
  until registration_row >/dev/null 2>&1; do
    ((SECONDS < registered && SECONDS < deadline)) || fail "deadline: the CLI did not register through Agent Mail"
    sleep 0.5
  done
  [[ "$(registration_row | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["bound_pane_pid"])')" == "$pane_pid" ]] \
    || refuse "the registration is bound to another pane than the recorded CLI"
  # The fake CLI exec'd into its idle loop after registering: refresh only its command line.
  kitpy refresh "$ROOT" cli || refuse "the CLI could not be refreshed with an unchanged identity"
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
  # Ownership and every proof before any write: an invalid root is never modified.
  kitpy instance "$ROOT" >/dev/null || refuse "this root has no valid kit instance; nothing was written"
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

  # Build the whole attempt, summary included, beside the published evidence; publish it
  # only when everything succeeded, by atomically swapping the evidence link.
  local id att
  id="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
  mkdir -p "$ROOT/evidence.d"
  att="$ROOT/evidence.d/$id"
  mkdir "$att"
  if ! capture_evidence "$att"; then
    rm -rf "$att"
    incomplete "the evidence could not be captured; the published evidence is unchanged"
  fi
  local old=""
  [[ -L "$ROOT/evidence" ]] && old="$(readlink "$ROOT/evidence")"
  ln -s "evidence.d/$id" "$ROOT/.evidence-$id"
  mv -T "$ROOT/.evidence-$id" "$ROOT/evidence"
  [[ -n "$old" && "$old" == evidence.d/* && "$old" != "evidence.d/$id" ]] && rm -rf "${ROOT:?}/$old"
  note "evidence written to $ROOT/evidence"
  cat "$att/summary.json"
}

capture_evidence() { # dir: every evidence file and the summary; fails without publishing anything
  local ev="$1" name
  in_ns sh -c 'printf "{\"net\": \"%s\", \"user\": \"%s\"}\n" "$(readlink /proc/self/ns/net)" "$(readlink /proc/self/ns/user)"' \
    | python3 -I -c 'import json,sys,os; d=json.load(sys.stdin); d["host_net"]=os.readlink("/proc/self/ns/net"); d["host_user"]=os.readlink("/proc/self/ns/user"); print(json.dumps(d))' >"$ev/namespaces.json" || return 1
  in_ns ip -o link | awk -F': ' '{print $2}' >"$ev/links.txt" || return 1
  python3 -I - "$ROOT/state/processes.json" >"$ev/processes.txt" <<'PY' || return 1
import json, sys
for name, entry in json.load(open(sys.argv[1])).items():
    try:
        cmd = open(f"/proc/{entry['pid']}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        cmd = "(gone)"
    print(f"{name}\t{entry['pid']}\t{entry['start']}\t{entry['argv'][:16]}\t{entry['ppid']}:{entry['pstart']}\t{cmd[:200]}")
PY
  in_ns "$ROOT/bin/tmux" list-panes -a -F '{"pane_pid": #{pane_pid}, "pane_current_command": "#{pane_current_command}", "target": "#{session_name}:#{window_index}.#{pane_index}"}' >"$ev/pane.json" || return 1
  registration_row >"$ev/registration.json" || return 1
  python3 -I - "$ROOT/state/processes.json" >"$ev/environment-names.json" <<'PY' || return 1
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
  if [[ -f "$ROOT/run/stub-requests.jsonl" ]]; then cp "$ROOT/run/stub-requests.jsonl" "$ev/stub-requests.jsonl" || return 1; else : >"$ev/stub-requests.jsonl"; fi
  [[ "${RUNTIME_KIT_TEST_FAULT:-}" != summary_fails ]] || return 1
  summary >"$ev/summary.json" || return 1
  # Identities are checked again after capture: evidence of a changed process is not published.
  for name in outer inner tmux stub backend cli; do
    kitpy verify "$ROOT" "$name" >/dev/null 2>&1 || return 1
  done
  (cd "$ev" && sha256sum namespaces.json links.txt processes.txt pane.json registration.json \
    environment-names.json stub-requests.jsonl summary.json >MANIFEST.sha256) || return 1
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
  kitpy instance "$ROOT" >/dev/null || refuse "this root has no valid kit instance; nothing was signalled or removed"
  # Every proof before any signal: recorded identities with their parents, and no
  # unrecorded or unreadable process in the kit namespace.
  local plan code=0 name
  plan="$(kitpy plan-teardown "$ROOT")" || code=$?
  ((code == 0 || code == 5)) || refuse "the teardown plan could not be computed; nothing was signalled"
  if ((code == 5)); then
    incomplete "teardown refused before any signal: $(python3 -I -c 'import json,sys; print("; ".join(json.loads(sys.argv[1])["problems"]))' "$plan"); the root and anchors are kept"
  fi
  # Children before parents: cli, stub, backend, tmux, then inner and outer last.
  for name in $(python3 -I -c 'import json,sys; print(" ".join(json.loads(sys.argv[1])["targets"]))' "$plan"); do
    stop_role "$name" || incomplete "$name could not be stopped with a proved identity; teardown stopped and the root is kept"
  done
  # The launcher (host side of the anchors) is never signalled: it exits with its child.
  local i
  for i in $(seq 1 30); do
    kitpy gone "$ROOT" launcher && break
    sleep 0.1
  done
  code=0
  plan="$(kitpy plan-teardown "$ROOT")" || code=$?
  [[ $code -eq 0 && "$plan" == *'"targets": []'* ]] || incomplete "processes of this kit instance are still running; the root is kept"
  kitpy gone "$ROOT" launcher || incomplete "the anchor launcher has not exited; the root is kept"
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

stop_role() { # name: TERM through a proved pidfd, a bounded wait, then KILL after a fresh proof
  local code=0 i
  kitpy signal "$ROOT" "$1" TERM >/dev/null 2>&1 || code=$?
  ((code == 3)) && return 0
  ((code == 0)) || return 1
  for i in $(seq 1 30); do
    [[ "$(kitpy verify "$ROOT" "$1" >/dev/null 2>&1; echo $?)" == 3 ]] && return 0
    sleep 0.1
  done
  code=0
  kitpy signal "$ROOT" "$1" KILL >/dev/null 2>&1 || code=$?
  ((code == 3)) && return 0
  ((code == 0)) || return 1
  for i in $(seq 1 20); do
    [[ "$(kitpy verify "$ROOT" "$1" >/dev/null 2>&1; echo $?)" == 3 ]] && return 0
    sleep 0.1
  done
  return 1
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
