#!/bin/bash
# Development server startup script
# Starts both backend and frontend in development mode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
BACKEND_PORT=8000
FRONTEND_PORT=5173

ACTION="start"
HOST=""

usage() {
    cat <<EOF
Usage: $0 [start|stop|restart] [--host <host>]

Commands:
  start           Start backend and frontend dev servers (default)
  stop            Stop Claude Deck dev servers for this checkout
  restart         Stop then start the dev servers

Options:
  --host <host>   Bind both backend and frontend to the given host (e.g. 0.0.0.0)
  -h, --help      Show this help message
EOF
}

if [[ $# -gt 0 && "$1" != -* ]]; then
    ACTION="$1"
    shift
fi

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

case "$ACTION" in
    start|stop|restart)
        ;;
    *)
        echo "Unknown command: $ACTION"
        usage
        exit 1
        ;;
esac

BACKEND_PID=""
FRONTEND_PID=""
CLEANED_UP=0

is_project_process() {
    local pid="$1"
    local command cwd
    command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"

    case "$command" in
        *"$BACKEND_DIR/venv/"*|*"$FRONTEND_DIR/node_modules/"*|*"$PROJECT_ROOT"*)
            return 0
            ;;
    esac

    case "$cwd" in
        "$PROJECT_ROOT"|"$PROJECT_ROOT"/*)
            return 0
            ;;
    esac

    return 1
}

listeners_on_port() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$port" -sTCP:LISTEN -n -P 2>/dev/null || true
    fi
}

collect_dev_server_pids() {
    {
        pgrep -f "$BACKEND_DIR/venv/bin/uvicorn app.main:app" 2>/dev/null || true
        pgrep -f "npm run dev" 2>/dev/null || true
        pgrep -f "$FRONTEND_DIR/node_modules/.bin/vite" 2>/dev/null || true
        listeners_on_port "$BACKEND_PORT"
        listeners_on_port "$FRONTEND_PORT"
    } | while read -r pid; do
        [ -n "$pid" ] || continue
        if is_project_process "$pid"; then
            echo "$pid"
        fi
    done | sort -u
}

collect_process_tree() {
    local pid="$1"
    local child
    [ -n "$pid" ] || return 0
    ps -p "$pid" >/dev/null 2>&1 || return 0
    echo "$pid"
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        collect_process_tree "$child"
    done
}

# Kill a process and its entire descendant tree
kill_tree() {
    local pid="$1"
    local pids
    [ -z "$pid" ] && return 0
    pids="$(collect_process_tree "$pid" | sort -rn | tr '\n' ' ')"
    [ -n "$pids" ] || return 0
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

stop_servers() {
    local quiet="${1:-}"
    local pids
    pids="$(collect_dev_server_pids)"

    if [ -z "$pids" ]; then
        [ "$quiet" = "quiet" ] || echo "No Claude Deck dev servers found for this checkout."
        return 0
    fi

    [ "$quiet" = "quiet" ] || echo "Stopping Claude Deck dev servers..."
    for pid in $pids; do
        kill_tree "$pid"
    done
    [ "$quiet" = "quiet" ] || echo "Stopped Claude Deck dev servers."
}

ensure_port_available() {
    local port="$1"
    local label="$2"
    local pid

    for pid in $(listeners_on_port "$port"); do
        if ! is_project_process "$pid"; then
            echo "Error: $label port $port is already in use by another process:"
            ps -p "$pid" -o pid=,command= 2>/dev/null || true
            exit 1
        fi
    done
}

check_dependencies() {
    # Check if backend venv exists
    if [ ! -d "$BACKEND_DIR/venv" ]; then
        echo "Error: Backend virtual environment not found."
        echo "Run ./scripts/install.sh first."
        exit 1
    fi

    # Check if frontend node_modules exists
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        echo "Error: Frontend dependencies not installed."
        echo "Run ./scripts/install.sh first."
        exit 1
    fi
}

start_servers() {
    echo "Starting Claude Deck development servers..."
    check_dependencies
    stop_servers quiet
    ensure_port_available "$BACKEND_PORT" "Backend"
    ensure_port_available "$FRONTEND_PORT" "Frontend"

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
    echo "Starting backend server on http://${BACKEND_DISPLAY_HOST}:${BACKEND_PORT}..."
    cd "$BACKEND_DIR"
    source venv/bin/activate
    uvicorn app.main:app --reload --port "$BACKEND_PORT" "${BACKEND_HOST_ARGS[@]}" &
    BACKEND_PID=$!

    # Start frontend
    echo "Starting frontend server on http://${BACKEND_DISPLAY_HOST}:${FRONTEND_PORT}..."
    cd "$FRONTEND_DIR"
    npm run dev "${FRONTEND_HOST_ARGS[@]}" &
    FRONTEND_PID=$!

    echo ""
    echo "Development servers started!"
    echo "  - Backend:  http://${BACKEND_DISPLAY_HOST}:${BACKEND_PORT}"
    echo "  - Frontend: http://${BACKEND_DISPLAY_HOST}:${FRONTEND_PORT}"
    echo "  - API Docs: http://${BACKEND_DISPLAY_HOST}:${BACKEND_PORT}/docs"
    echo ""
    echo "Press Ctrl+C to stop all servers."

    # Wait for either process to exit, then clean up the other
    wait -n 2>/dev/null || true
    cleanup
}

case "$ACTION" in
    start)
        start_servers
        ;;
    stop)
        stop_servers
        ;;
    restart)
        stop_servers
        start_servers
        ;;
esac
