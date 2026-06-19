# Grove — Bio-Break Guardian

A 30-minute focus / 10-minute break reminder, themed as a living forest grove
that mirrors your wellbeing. Built with a Python backend (owns the timer, so
it survives reloads/crashes) and a single-page nature-clock frontend with a
soothing female voice for alerts.

## How it works

1. Pick (or "use current time" for) the time you started working.
2. Tap **Start the grove**. A wooden-ring clock with a living tree in the
   center begins counting down 30 minutes. The tree sways gently and stays green.
3. At 30 minutes, the tree dims, an amber/red overlay appears, and a calm
   female voice warns that "the grove is wilting" — like your body, it needs
   rest. You tap **I accept** to begin your break.
4. A 10-minute countdown begins (tree shown in a recovering/amber tone).
5. At 10 minutes, the grove turns vibrant green again, a voice says it's
   "safe to come back," and the 30-minute focus cycle restarts automatically.
6. This repeats indefinitely as long as the backend is running.

## Project layout

```
bio-break-guardian/
  backend/
    server.py        Python (aiohttp) WebSocket server, owns all timer state
    grove_state.json  auto-created, persists state across restarts
  frontend/
    index.html        the nature clock UI, voice, and WebSocket client
    serve.py           tiny static file server for index.html
  run_grove.sh         tmux launcher (macOS/Linux): start / stop / status
  run_grove.py         cross-platform launcher (Windows/macOS/Linux), no tmux needed
  run_grove.bat        double-click launcher for Windows
  requirements.txt     Python dependencies (just aiohttp)
```

## Running it

Requirements: Python 3.9+ and `pip install -r requirements.txt` (just `aiohttp`).

### Windows (no tmux, no admin rights needed)

tmux doesn't run natively on Windows and isn't a pip package — if you saw an
error trying to `pip install tmux`, that's expected, it's not a real Python
dependency. Use one of these instead:

**Option A — double-click `run_grove.bat`**
Opens two console windows (backend + frontend). Closing either window stops
that server. Closing both stops Grove entirely.

**Option B — `python run_grove.py` (works in Git Bash / MINGW64 too)**
```bash
python run_grove.py start              # runs in this terminal, Ctrl+C to stop both
python run_grove.py start --background # starts both, returns control to your terminal
python run_grove.py status             # check if it's running
python run_grove.py stop               # stop a --background run
```

Then open **http://localhost:8080** in your browser.

### macOS / Linux (with tmux)

```bash
cd bio-break-guardian
./run_grove.sh start     # launches backend (port 8765) + frontend (port 8080) in tmux
./run_grove.sh status    # check it's running
./run_grove.sh stop      # stop both servers
tmux attach -t grove     # watch live logs from both processes
```

If you're on macOS/Linux but don't have or want tmux, `run_grove.py` (Option
B above) works there too — it's fully cross-platform.

Because the timer state lives in the backend (and is written to
`grove_state.json` after every change), you can close your browser tab,
reopen it, or even restart your laptop's browser — as long as the tmux
session keeps running, the countdown keeps going and picks up exactly where
it left off when you reconnect.

## Why a backend at all (not just a browser timer)

A pure browser `setTimeout` resets if the tab is closed, the laptop sleeps,
or the page is refreshed — easy to lose your place in a long-running 24/7
reminder. Running the actual countdown in a small always-on Python service
under tmux means the *schedule* is durable; the browser tab is just the
display + the thing that can speak out loud (speech synthesis is a
browser-only API, so that part has to stay in the frontend).

## Notes on the voice

Voice selection depends on what your OS/browser exposes to the Web Speech
API. The app tries to auto-pick a soft, natural-sounding female voice (e.g.
Samantha, Google US English, Victoria) and falls back gracefully. Use the
"Test voice" button and the dropdown in the Voice & sound card to switch if
the auto-pick doesn't sound right to you. If your browser doesn't support
speech synthesis at all, the alerts still appear visually as overlays.

## Suggested improvements (your call on which to add)

- **Browser tab title / favicon countdown** — show "12:48 to break" in the
  tab title so you can see status without switching tabs.
- **Desktop notifications** — use the Notifications API to alert you even if
  the Grove tab isn't focused or is in a background window.
- **Sound fallback** — play a gentle chime alongside/instead of speech, in
  case speech synthesis isn't available or you're in a meeting and want
  silent-but-visible alerts.
- **Configurable durations** — right now 30/10 minutes are hardcoded in
  `server.py` (`WORK_SECONDS`, `BREAK_SECONDS`); easy to expose as fields in
  the UI if you want to tune the rhythm.
- **Daily/weekly stats page** — the backend already counts
  `cycles_completed`; persisting a timestamped log would let you build a
  simple "breaks taken today" view, reinforcing the health habit.
- **Auto-launch on login** — wrap `run_grove.sh start` in a systemd user
  service or a login script so the grove is always running without you
  remembering to start it manually.
- **Snooze with a cost** — if you want to gently discourage skipping
  breaks, a "snooze 2 min" option that visually wilts the tree a little
  further each time it's used (rather than letting you postpone for free).
