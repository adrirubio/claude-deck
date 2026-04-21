#!/bin/bash
# Development server startup script
# Starts both backend and frontend in development mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

HOST=""

usage() {
    cat <<EOF
Usage: $0 [--host <host>]

Options:
  --host <host>   Bind both backend and frontend to the given host (e.g. 0.0.0.0)
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

echo "Starting Claude Deck development servers..."

# Check if backend venv exists
if [ ! -d "$PROJECT_ROOT/backend/venv" ]; then
    echo "Error: Backend virtual environment not found."
    echo "Run ./scripts/install.sh first."
    exit 1
fi

# Check if frontend node_modules exists
if [ ! -d "$PROJECT_ROOT/frontend/node_modules" ]; then
    echo "Error: Frontend dependencies not installed."
    echo "Run ./scripts/install.sh first."
    exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=0

# Kill a process and its entire descendant tree
kill_tree() {
    local pid="$1"
    [ -z "$pid" ] && return 0
    # Collect descendants (children, grandchildren, ...)
    local pids="$pid"
    local frontier="$pid"
    while [ -n "$frontier" ]; do
        local next
        next="$(pgrep -P $frontier 2>/dev/null | tr '\n' ' ')"
        [ -z "$next" ] && break
        pids="$pids $next"
        frontier="$next"
    done
    kill -TERM $pids 2>/dev/null || true
    # Give them a moment, then force-kill anything left
    sleep 1
    kill -KILL $pids 2>/dev/null || true
}

cleanup() {
    [ "$CLEANED_UP" -eq 1 ] && return
    CLEANED_UP=1
    echo ""
    echo "Shutting down servers..."
    kill_tree "$BACKEND_PID"
    kill_tree "$FRONTEND_PID"
    wait 2>/dev/null || true
}

trap 'cleanup; exit 130' SIGINT
trap 'cleanup; exit 143' SIGTERM
trap cleanup EXIT

BACKEND_HOST_ARGS=()
FRONTEND_HOST_ARGS=()
if [ -n "$HOST" ]; then
    BACKEND_HOST_ARGS=(--host "$HOST")
    FRONTEND_HOST_ARGS=(-- --host "$HOST")
    echo "Binding servers to host: $HOST"
fi

# Start backend
BACKEND_DISPLAY_HOST="${HOST:-localhost}"
echo "Starting backend server on http://${BACKEND_DISPLAY_HOST}:8000..."
cd "$PROJECT_ROOT/backend"
source venv/bin/activate
uvicorn app.main:app --reload --port 8000 "${BACKEND_HOST_ARGS[@]}" &
BACKEND_PID=$!

# Start frontend
echo "Starting frontend server on http://${BACKEND_DISPLAY_HOST}:5173..."
cd "$PROJECT_ROOT/frontend"
npm run dev "${FRONTEND_HOST_ARGS[@]}" &
FRONTEND_PID=$!

echo ""
echo "Development servers started!"
echo "  - Backend:  http://${BACKEND_DISPLAY_HOST}:8000"
echo "  - Frontend: http://${BACKEND_DISPLAY_HOST}:5173"
echo "  - API Docs: http://${BACKEND_DISPLAY_HOST}:8000/docs"
echo ""
echo "Press Ctrl+C to stop all servers."

# Wait for either process to exit, then clean up the other
wait -n 2>/dev/null || true
cleanup
