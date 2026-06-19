"""
Grove — Bio-Break Guardian backend.

Owns the timer state so the schedule survives page reloads, browser
crashes, or laptop sleep. The frontend is just a renderer + voice.

State machine per cycle:
  ACTIVE        -> counting down the 30 min work interval
  BREAK_DUE     -> 30 min elapsed, waiting for the user to press "I accept"
  ON_BREAK      -> user accepted, counting down the 10 min break
  WELCOME_BACK  -> 10 min elapsed, voice line fires, auto-returns to ACTIVE

Extra features beyond the base timer:
  - Idle pause: while ACTIVE, the frontend can tell the backend the user
    has stepped away (no mouse/keyboard activity) so the focus countdown
    freezes instead of silently ticking down time nobody worked through.
  - Snooze with a cost: while BREAK_DUE, the user can ask for a couple
    more minutes, but each snooze is counted and reported back so the
    UI can visibly "wilt" the tree further the more it's used — postponing
    isn't free.
  - Daily stats: every completed cycle is appended to grove_stats.jsonl
    so the frontend can show "breaks taken today" / "snoozes today" /
    "idle-paused time today" without re-deriving it from logs.

Run with: python3 server.py
Listens on 0.0.0.0:8765 (HTTP + WebSocket on the same port).
"""

import asyncio
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s [grove] %(message)s")
log = logging.getLogger("grove")

STATE_FILE = Path(__file__).parent / "grove_state.json"
STATS_FILE = Path(__file__).parent / "grove_stats.jsonl"

WORK_SECONDS = 30 * 60
BREAK_SECONDS = 10 * 60
SNOOZE_SECONDS = 120          # cost of one snooze: pushes break-due window 2 min later
MAX_SNOOZES_PER_BREAK = 3     # after this, the button disables — no infinite postponing

LEVEL_THRESHOLDS = {
    1: 0,
    2: 50,
    3: 120,
    4: 250,
    5: 500,
    6: 800,
    7: 1200,
    8: 1700,
    9: 2300,
    10: 3000
}

@dataclass
class GroveState:
    phase: str = "STOPPED"
    cycle_start_ts: float = 0.0
    phase_duration: float = WORK_SECONDS
    cycles_completed: int = 0
    started_at_clock: str = ""

    paused: bool = False
    snooze_count: int = 0
    idle_paused_seconds_cycle: float = 0.0

    # NEW
    tree_level: int = 1
    tree_xp: int = 0
    streak_days: int = 0
    health_score: int = 100

    achievements: list = None

    def __post_init__(self):
        if self.achievements is None:
            self.achievements = []

    def to_public_dict(self):
        now = time.time()

        elapsed = (
            now - self.cycle_start_ts
            if self.phase != "STOPPED"
            else 0
        )

        remaining = max(
            0,
            self.phase_duration - elapsed
        )

        overdue = (
            max(0, elapsed - self.phase_duration)
            if self.phase == "BREAK_DUE"
            else 0
        )

        d = asdict(self)
        d["remaining_seconds"] = remaining
        d["overdue_seconds"] = overdue
        d["server_time"] = now

        return d

class Grove:
    def __init__(self):
        self.state = GroveState()
        self.clients: set[web.WebSocketResponse] = set()
        self._load()

    def add_xp(self, amount: int):
        self.state.tree_xp += amount

        new_level = self.state.tree_level

        for level, required in LEVEL_THRESHOLDS.items():
            if self.state.tree_xp >= required:
                new_level = level

        if new_level > self.state.tree_level:
            self.state.tree_level = new_level

            self.unlock_achievement(
                f"Reached Tree Level {new_level}"
            )

        self._save()
    
    def unlock_achievement(self, achievement_name: str):

        if achievement_name in self.state.achievements:
            return

        self.state.achievements.append(
            achievement_name
        )

        self._log_stat(
            "achievement_unlocked",
            {
                "achievement": achievement_name
            }
        )

    def _load(self):
        if STATE_FILE.exists():
            try:
                raw = json.loads(STATE_FILE.read_text())
                self.state = GroveState(**{k: raw[k] for k in raw if k in GroveState.__dataclass_fields__})
                log.info("restored state: %s", self.state.phase)
            except Exception as e:
                log.warning("could not restore state (%s), starting fresh", e)

    def _save(self):
        STATE_FILE.write_text(json.dumps(asdict(self.state)))

    def _log_stat(self, event: str, extra: Optional[dict] = None):
        record = {
            "ts": time.time(),
            "date": datetime.now(timezone.utc).astimezone().date().isoformat(),
            "event": event,
        }
        if extra:
            record.update(extra)
        try:
            with STATS_FILE.open("a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            log.warning("could not write stats (%s)", e)

    async def broadcast(self, event: dict):
        dead = set()
        for ws in self.clients:
            try:
                await ws.send_json(event)
            except Exception:
                dead.add(ws)
        self.clients -= dead

    async def push_state(self, extra_event: Optional[str] = None):
        payload = {"type": "state", "data": self.state.to_public_dict()}
        if extra_event:
            payload["event"] = extra_event
        await self.broadcast(payload)

    def start(self, clock_label: str):
        self.state = GroveState(
            phase="ACTIVE",
            cycle_start_ts=time.time(),
            phase_duration=WORK_SECONDS,
            cycles_completed=0,
            started_at_clock=clock_label,
        )
        self._save()
        log.info("grove started at %s", clock_label)

    def stop(self):
        self.state = GroveState()
        self._save()
        log.info("grove stopped")

    def accept_break(self) -> bool:
        if self.state.phase != "BREAK_DUE":
            log.info("accept_break ignored, phase is %s not BREAK_DUE", self.state.phase)
            return False
        self.state.phase = "ON_BREAK"
        self.state.cycle_start_ts = time.time()
        self.state.phase_duration = BREAK_SECONDS
        self._save()
        log.info("break accepted, 10 min countdown started")
        return True

    def pause_idle(self) -> bool:
        if self.state.phase != "ACTIVE" or self.state.paused:
            return False
        self.state.paused = True
        self._save()
        log.info("idle pause engaged")
        return True

    def resume_idle(self) -> bool:
        if not self.state.paused:
            return False
        self.state.paused = False
        self._save()
        log.info("idle pause released, %.0fs idle this cycle so far", self.state.idle_paused_seconds_cycle)
        return True

    def snooze(self) -> bool:
        if self.state.phase != "BREAK_DUE":
            log.info("snooze ignored, phase is %s not BREAK_DUE", self.state.phase)
            return False
        if self.state.snooze_count >= MAX_SNOOZES_PER_BREAK:
            log.info("snooze ignored, max snoozes (%d) already used", MAX_SNOOZES_PER_BREAK)
            return False
        self.state.cycle_start_ts += SNOOZE_SECONDS
        self.state.snooze_count += 1
        self.state.health_score = max(
            0,
            self.state.health_score - 3
        )

        self.add_xp(-2)
        self._save()
        self._log_stat("snooze", {"snooze_count": self.state.snooze_count})
        log.info("snooze #%d used, break-due window pushed %ds", self.state.snooze_count, SNOOZE_SECONDS)
        return True

    async def tick(self):
        """Background loop, checked every second, drives automatic phase transitions."""
        while True:
            await asyncio.sleep(1)
            if self.state.phase == "STOPPED":
                continue

            if self.state.paused:
                # Freeze the countdown: shift the phase start forward so elapsed
                # time doesn't include time the user was away. No phase
                # transitions happen while paused.
                self.state.cycle_start_ts += 1
                self.state.idle_paused_seconds_cycle += 1
                continue

            elapsed = time.time() - self.state.cycle_start_ts
            if self.state.phase == "ACTIVE" and elapsed >= self.state.phase_duration:
                self.state.phase = "BREAK_DUE"
                self.state.snooze_count = 0
                self._save()
                await self.push_state(extra_event="BREAK_DUE")
                log.info("30 min reached -> BREAK_DUE")
            elif self.state.phase == "ON_BREAK" and elapsed >= self.state.phase_duration:
                idle_secs = self.state.idle_paused_seconds_cycle
                snoozes = self.state.snooze_count
                self.add_xp(10)

                self.state.health_score = min(
                    100,
                    self.state.health_score + 2
                )

                if self.state.cycles_completed == 0:
                    self.unlock_achievement("First Break")

                if self.state.cycles_completed == 4:
                    self.unlock_achievement("5 Breaks Completed")

                if self.state.cycles_completed == 24:
                    self.unlock_achievement("25 Breaks Completed")
                self.state.cycle_start_ts = time.time()
                self.state.phase_duration = WORK_SECONDS
                self.state.cycles_completed += 1
                self.state.idle_paused_seconds_cycle = 0.0
                self.state.snooze_count = 0
                self._save()
                self._log_stat("cycle_complete", {
                    "cycles_completed": self.state.cycles_completed,
                    "idle_paused_seconds": idle_secs,
                    "snoozes_used": snoozes,
                })
                await self.push_state(extra_event="WELCOME_BACK")
                log.info("10 min break finished -> WELCOME_BACK, new ACTIVE cycle")
            else:
                await self.push_state()

    def stats_today(self) -> dict:
        today = datetime.now(timezone.utc).astimezone().date().isoformat()
        completed = 0
        snoozes = 0
        idle_seconds = 0.0
        if STATS_FILE.exists():
            try:
                for line in STATS_FILE.read_text().splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    if rec.get("date") != today:
                        continue
                    if rec.get("event") == "cycle_complete":
                        completed += 1
                        snoozes += rec.get("snoozes_used", 0)
                        idle_seconds += rec.get("idle_paused_seconds", 0)
                    elif rec.get("event") == "snooze":
                        pass  # already counted via cycle_complete's snoozes_used
            except Exception as e:
                log.warning("could not read stats (%s)", e)
        return {
            "date": today,
            "cycles_completed_today": completed,
            "snoozes_used_today": snoozes,
            "idle_paused_minutes_today": round(idle_seconds / 60, 1),

            "tree_level": self.state.tree_level,
            "tree_xp": self.state.tree_xp,
            "health_score": self.state.health_score,
            "achievements": self.state.achievements
        }


grove = Grove()


async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    grove.clients.add(ws)
    log.info("client connected (%d total)", len(grove.clients))
    await ws.send_json({"type": "state", "data": grove.state.to_public_dict()})

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                cmd = json.loads(msg.data)
            except Exception:
                continue

            action = cmd.get("action")
            if action == "start":
                grove.start(cmd.get("clock_label", ""))
                await grove.push_state(extra_event="STARTED")
            elif action == "accept_break":
                accepted = grove.accept_break()
                await grove.push_state(extra_event="BREAK_ACCEPTED" if accepted else None)
            elif action == "stop":
                grove.stop()
                await grove.push_state(extra_event="STOPPED")
            elif action == "pause_idle":
                grove.pause_idle()
                await grove.push_state(extra_event="IDLE_PAUSED")
            elif action == "resume_idle":
                grove.resume_idle()
                await grove.push_state(extra_event="IDLE_RESUMED")
            elif action == "snooze":
                snoozed = grove.snooze()
                await grove.push_state(extra_event="SNOOZED" if snoozed else "SNOOZE_DENIED")
            elif action == "get_state":
                await ws.send_json({"type": "state", "data": grove.state.to_public_dict()})
    finally:
        grove.clients.discard(ws)
        log.info("client disconnected (%d total)", len(grove.clients))
    return ws


async def handle_health(request):
    return web.json_response({"ok": True, "phase": grove.state.phase})


async def handle_stats(request):
    return web.json_response(grove.stats_today())


def cors_middleware_factory():
    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            resp = await handler(request)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        return resp
    return cors_middleware


async def on_startup(app):
    app["tick_task"] = asyncio.create_task(grove.tick())


async def on_cleanup(app):
    app["tick_task"].cancel()


def build_app():
    app = web.Application(middlewares=[cors_middleware_factory()])
    app.router.add_get("/ws", handle_ws)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/stats", handle_stats)
    app.router.add_route("OPTIONS", "/stats", handle_stats)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    app = build_app()
    log.info("Grove backend listening on http://0.0.0.0:8765 (ws at /ws, stats at /stats)")
    web.run_app(app, host="0.0.0.0", port=8765)