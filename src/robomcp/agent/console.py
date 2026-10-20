"""Web console: type a task, watch the arm move and the agent's plan / tool calls / verification live.

    uv run robomcp-agent console        # then open http://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from robomcp.agent.harness import LIVE_DIR, Harness

PAGE = Path(__file__).with_name("console.html")


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.running = False

    def push(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)

    def start(self, goal: str, mode: str, seed: int | None) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.events = True, []
        threading.Thread(target=self._run, args=(goal, mode, seed), daemon=True).start()
        return True

    def _run(self, goal: str, mode: str, seed: int | None) -> None:
        try:
            harness = Harness(mode=mode, on_event=self.push, live=True)
            asyncio.run(harness.run(goal, seed=seed))
        except Exception as e:  # surface failures in the page instead of a silent stop
            self.push({"kind": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            with self.lock:
                self.running = False


STATE = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path.startswith("/frame.jpg"):
            frame = LIVE_DIR / "frame.jpg"
            self._send(200, frame.read_bytes(), "image/jpeg") if frame.exists() else self._send(404, b"", "text/plain")
        elif self.path.startswith("/events"):
            since = int(self.path.split("since=")[-1]) if "since=" in self.path else 0
            with STATE.lock:
                body = {"running": STATE.running, "events": STATE.events[since:], "total": len(STATE.events)}
            self._send(200, json.dumps(body, ensure_ascii=False).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        if self.path != "/run":
            return self._send(404, b"not found", "text/plain")
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        seed = req.get("seed")
        ok = STATE.start(req.get("goal", "").strip() or "把红色方块放进托盘", req.get("mode", "plan"),
                         int(seed) if seed not in (None, "") else None)
        self._send(200 if ok else 409, json.dumps({"started": ok}).encode(), "application/json")


def serve(port: int = 8765) -> None:
    from robomcp.sim import TabletopSim

    # Render one still frame so the page shows the scene before the first run.
    sim = TabletopSim()
    sim._live_dir = LIVE_DIR
    sim.write_live_frame()
    print(f"RoboMCP console: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
