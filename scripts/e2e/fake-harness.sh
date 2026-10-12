#!/usr/bin/env bash
# Fake harness binary for the Deck E2E instance. No network, no credentials.
#
# scripts/e2e-instance.sh copies this file to <tmp>/bin/<name> for each
# provider (claude, codex, copilot, opencode, pi). The name comes from $0.
# - Probes (--version, --help, any --json call) return at once.
# - Without a terminal on stdin it exits 0, so a Deck subprocess never hangs.
# - In a terminal (a tmux pane) it echoes its input with argv[0] set to the
#   harness name, so tmux and /proc report "claude", "codex" and so on.
name="$(basename "$0")"

case "${1:-}" in
  --version | -v | -V | version)
    case "$name" in
      claude) echo "2.1.0 (Claude Code)" ;;
      codex) echo "codex-cli 0.50.0" ;;
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

export FAKE_HARNESS_NAME="$name"
# shellcheck disable=SC2016 # expanded by the inner shell
exec -a "$name" "$BASH" -c 'echo "$FAKE_HARNESS_NAME e2e fake ready"; while IFS= read -r line; do printf "%s\n" "$line"; done'
