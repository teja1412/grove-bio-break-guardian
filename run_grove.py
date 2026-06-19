"""
Cross-platform launcher for Grove — runs the backend and frontend as two
child processes from a single Python script, with no dependency on tmux.

Works the same way on Windows, macOS, and Linux.

Usage:
    python3 run_grove.py start     starts both servers, keeps running in
                                    this terminal (Ctrl+C to stop both)
    python3 run_grove.py start --background
                                    starts both, detaches, returns immediately
                                    (Windows: uses pythonw-style detach;
                                     macOS/Linux: forks to background)
    python3 run_grove.py stop      stops a --background run (uses a pidfile)
    python3 run_grove.py status    shows whether it's running
"""

import sys
import os
import time
import signal
import subprocess
import json
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
PIDFILE = ROOT / ".grove_pids.json"

IS_WINDOWS = os.name == "nt"


def ensure_deps():
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        print("Installing backend dependency (aiohttp)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "aiohttp"], check=True)


def spawn(cmd, cwd, log_path):
    """Start a child process, detached enough to survive this script exiting
    when running in background mode, but always killable later. Output is
    redirected to a log file so the child never holds open this script's
    own stdout/stderr pipes (important when this script itself is launched
    in the background / from a terminal that gets closed)."""
    kwargs = {"cwd": str(cwd)}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["preexec_fn"] = os.setsid
    log_file = open(log_path, "a")
    kwargs["stdout"] = log_file
    kwargs["stderr"] = log_file
    kwargs["stdin"] = subprocess.DEVNULL
    return subprocess.Popen(cmd, **kwargs)


def write_pidfile(backend_pid, frontend_pid):
    PIDFILE.write_text(json.dumps({"backend": backend_pid, "frontend": frontend_pid}))


def read_pidfile():
    if not PIDFILE.exists():
        return None
    try:
        return json.loads(PIDFILE.read_text())
    except Exception:
        return None


def pid_alive(pid):
    if IS_WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def kill_pid(pid):
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


def print_log_tail(log_path, lines=20):
    try:
        content = Path(log_path).read_text(errors="replace").splitlines()
        tail = content[-lines:]
        if tail:
            print(f"--- last {len(tail)} lines of {Path(log_path).name} ---")
            for line in tail:
                print(line)
            print("--- end of log ---")
        else:
            print(f"({Path(log_path).name} is empty — the process likely failed before printing anything)")
    except Exception as e:
        print(f"(could not read {log_path}: {e})")


def start(background=False):
    ensure_deps()

    existing = read_pidfile()
    if existing and pid_alive(existing.get("backend", -1)):
        print("Grove already appears to be running (backend pid "
              f"{existing['backend']}). Use 'stop' first if you want to restart.")
        return

    backend_proc = spawn([sys.executable, "server.py"], BACKEND_DIR, ROOT / "backend.log")
    time.sleep(0.5)
    frontend_proc = spawn([sys.executable, "serve.py"], FRONTEND_DIR, ROOT / "frontend.log")
    time.sleep(0.5)

    backend_log = ROOT / "backend.log"
    frontend_log = ROOT / "frontend.log"

    # Quick sanity check right after launch: if either process already died
    # in this first half-second, surface why immediately instead of leaving
    # the person to go hunting for a log file.
    startup_failed = False
    if backend_proc.poll() is not None:
        print(f"Backend failed to start (exit code {backend_proc.returncode}).")
        print_log_tail(backend_log)
        startup_failed = True
    if frontend_proc.poll() is not None:
        print(f"Frontend failed to start (exit code {frontend_proc.returncode}).")
        print_log_tail(frontend_log)
        startup_failed = True
    if startup_failed:
        kill_pid(backend_proc.pid)
        kill_pid(frontend_proc.pid)
        return

    write_pidfile(backend_proc.pid, frontend_proc.pid)

    frontend_url = "http://localhost:8080"
    try:
        log_text = frontend_log.read_text(errors="replace")
        for line in log_text.splitlines():
            if line.startswith("Grove frontend serving at"):
                frontend_url = line.split("at", 1)[1].strip().replace("0.0.0.0", "localhost")
    except Exception:
        pass

    print("Grove is running.")
    print("  Backend (WebSocket + state):  ws://localhost:8765/ws")
    print(f"  Frontend (open in browser):   {frontend_url}")
    print()

    if background:
        print("Running in the background. Use 'python3 run_grove.py stop' to stop it.")
        return

    print("Press Ctrl+C to stop both servers.")

    stop_requested = {"flag": False}

    def handle_term(signum, frame):
        stop_requested["flag"] = True

    if not IS_WINDOWS:
        signal.signal(signal.SIGTERM, handle_term)

    try:
        while True:
            time.sleep(1)
            if stop_requested["flag"]:
                print("\nReceived stop signal, stopping Grove...")
                break
            if backend_proc.poll() is not None:
                print(f"Backend process exited unexpectedly (exit code {backend_proc.returncode}), stopping.")
                print_log_tail(backend_log)
                break
            if frontend_proc.poll() is not None:
                print(f"Frontend process exited unexpectedly (exit code {frontend_proc.returncode}), stopping.")
                print_log_tail(frontend_log)
                break
    except KeyboardInterrupt:
        print("\nStopping Grove...")
    finally:
        kill_pid(backend_proc.pid)
        kill_pid(frontend_proc.pid)
        if PIDFILE.exists():
            PIDFILE.unlink()
        print("Stopped.")


def stop():
    existing = read_pidfile()
    if not existing:
        print("No running Grove found (no pidfile). If you started it in the "
              "foreground, just press Ctrl+C in that terminal instead.")
        return
    for name in ("backend", "frontend"):
        pid = existing.get(name)
        if pid and pid_alive(pid):
            kill_pid(pid)
            print(f"Stopped {name} (pid {pid}).")
        else:
            print(f"{name} was not running.")
    if PIDFILE.exists():
        PIDFILE.unlink()


def status():
    existing = read_pidfile()
    if not existing:
        print("Grove is not running.")
        return
    backend_ok = pid_alive(existing.get("backend", -1))
    frontend_ok = pid_alive(existing.get("frontend", -1))
    print(f"Backend running: {backend_ok}")
    print(f"Frontend running: {frontend_ok}")
    if not backend_ok and not frontend_ok and PIDFILE.exists():
        PIDFILE.unlink()


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "start"
    background = "--background" in args

    if cmd == "start":
        start(background=background)
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    else:
        print("Usage: python3 run_grove.py {start [--background]|stop|status}")
        sys.exit(1)
