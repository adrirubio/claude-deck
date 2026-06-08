#!/bin/bash
# Documentation development server
# Starts the VitePress docs site in development mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

HOST=""
PORT="5174"

usage() {
    cat <<EOF
Usage: $0 [--host <host>] [--port <port>]

Options:
  --host <host>   Bind the docs server to the given host (e.g. 0.0.0.0)
  --port <port>   Port for the docs server (default: 5174)
  -h, --help      Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)
            if [ -z "${2:-}" ]; then
                echo "Error: --host requires a value."
                usage
                exit 1
            fi
            HOST="$2"
            shift 2
            ;;
        --host=*)
            HOST="${1#*=}"
            shift
            ;;
        --port)
            if [ -z "${2:-}" ]; then
                echo "Error: --port requires a value."
                usage
                exit 1
            fi
            PORT="$2"
            shift 2
            ;;
        --port=*)
            PORT="${1#*=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

if [ ! -d "$PROJECT_ROOT/docs/node_modules" ]; then
    echo "Error: Documentation dependencies are not installed."
    echo "Run ./scripts/install.sh first."
    exit 1
fi

DOCS_HOST_ARGS=()
DOCS_DISPLAY_HOST="${HOST:-localhost}"
if [ -n "$HOST" ]; then
    DOCS_HOST_ARGS+=(--host "$HOST")
    echo "Binding docs server to host: $HOST"
fi

echo "Starting documentation server on http://${DOCS_DISPLAY_HOST}:${PORT}/docs/..."
cd "$PROJECT_ROOT/docs"
npm run dev -- --port "$PORT" "${DOCS_HOST_ARGS[@]}"
