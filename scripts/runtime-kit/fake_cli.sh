#!/usr/bin/env bash
# A fake provider CLI for the isolated runtime kit (#902). No real model, no credentials.
#
# The kit installs it under the provider's binary name (for example `codex`), so
# Synth City's normal team launch starts it in a tmux pane. In the pane it does
# what a real member does first, through the same endpoints:
#   1. registers with Agent Mail from its own pane (POST /api/v1/agent-mail/agent/register;
#      the backend derives the pane and slot from the kernel peer, not from this payload);
#   2. sends one chat request to the kit's stub model provider;
# then it waits on its terminal like an idle agent.
#
# Probes (--version, --help, --json calls) and runs without a terminal return at once.
# The kit's environment supplies SYNTH_CITY_URL, RUNTIME_KIT_PROVIDER and RUNTIME_KIT_STUB_URL.
name="$(basename "$0")"

case "${1:-}" in
  --version | -v | -V | version)
    case "$name" in
      claude) echo "2.1.0 (Claude Code)" ;;
      codex) echo "codex-cli 0.50.0" ;;
      opencode) echo "opencode v2.2.7" ;;
      *) echo "$name 1.0.0" ;;
    esac
    exit 0
    ;;
  --help | -h | help)
    echo "usage: $name [--version]"
    exit 0
    ;;
esac
for arg in "$@"; do
  if [[ "$arg" == --json ]]; then
    if [[ " $* " == *" list "* ]]; then echo "[]"; else echo "{}"; fi
    exit 0
  fi
done
if [[ ! -t 0 ]]; then
  exit 0
fi

state="${RUNTIME_KIT_ROOT:?}/run/fake-cli"
mkdir -p "$state"
if [[ "${RUNTIME_KIT_TEST_FAULT:-}" != no_registration ]]; then
  python3 - "$state" <<'PY' || echo "fake cli: registration failed" >&2
import json, os, sys, urllib.request
state = sys.argv[1]
base = os.environ["SYNTH_CITY_URL"]
body = {"source": "mcp", "provider": os.environ["RUNTIME_KIT_PROVIDER"], "cwd": os.getcwd(),
        "session_key": f"runtime-kit:{os.getppid()}", "pid": os.getppid()}
request = urllib.request.Request(base + "/api/v1/agent-mail/agent/register", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=10) as response:
    reply = json.loads(response.read())
# The capability token stays in memory; only identifiers are kept.
with open(os.path.join(state, "registered.json"), "w") as out:
    json.dump({"member_id": reply["member"]["id"], "session_key": reply["session"]["session_key"]}, out)
chat = {"model": "stub-model", "messages": [{"role": "user", "content": "isolated runtime kit check"}]}
request = urllib.request.Request(os.environ["RUNTIME_KIT_STUB_URL"] + "/v1/chat/completions",
                                 data=json.dumps(chat).encode(), headers={"Content-Type": "application/json"},
                                 method="POST")
with urllib.request.urlopen(request, timeout=10) as response:
    json.loads(response.read())
PY
fi

export FAKE_CLI_NAME="$name"
# shellcheck disable=SC2016 # expanded by the inner shell
exec -a "$name" "$BASH" -c 'echo "$FAKE_CLI_NAME runtime-kit fake ready"; while IFS= read -r line; do printf "%s\n" "$line"; done'
