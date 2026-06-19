#!/usr/bin/env bash
# Launches the Grove backend and frontend inside a detached tmux session
# so both keep running continuously, independent of any terminal closing.
#
# Usage:
#   ./run_grove.sh start    -> creates/attaches the tmux session
#   ./run_grove.sh stop     -> kills the tmux session (stops both servers)
#   ./run_grove.sh status   -> shows whether it's running
#
# After it's running, open http://localhost:8080 in your browser.

set -e

SESSION="grove"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

ensure_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is not installed. Install it first, e.g.:"
    echo "  sudo apt-get install -y tmux     (Debian/Ubuntu)"
    echo "  brew install tmux                (macOS)"
    exit 1
  fi
}

ensure_deps() {
  if ! python3 -c "import aiohttp" >/dev/null 2>&1; then
    echo "Installing backend dependency (aiohttp)..."
    pip3 install --break-system-packages -q aiohttp || pip3 install -q aiohttp
  fi
}

start() {
  ensure_tmux
  ensure_deps

  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Grove session already running. Attach with: tmux attach -t $SESSION"
    exit 0
  fi

  tmux new-session -d -s "$SESSION" -n backend -c "$BACKEND_DIR" "python3 server.py"
  tmux new-window  -t "$SESSION" -n frontend  -c "$FRONTEND_DIR" "python3 serve.py"

  echo "Grove is running inside tmux session '$SESSION'."
  echo "  Backend (WebSocket + state):  ws://localhost:8765/ws"
  echo "  Frontend (open in browser):   http://localhost:8080"
  echo ""
  echo "Useful commands:"
  echo "  tmux attach -t $SESSION       # view logs / both windows"
  echo "  tmux ls                        # list sessions"
  echo "  ./run_grove.sh stop            # stop everything"
}

stop() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    echo "Grove session stopped."
  else
    echo "No running Grove session found."
  fi
}

status() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Grove is running."
    tmux list-windows -t "$SESSION"
  else
    echo "Grove is not running."
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "Usage: $0 {start|stop|status}"; exit 1 ;;
esac
