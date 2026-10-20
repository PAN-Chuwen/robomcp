"""Web console: type a task, watch the arm move and the agent's plan / tool calls / verification live.

    uv run robomcp-agent console        # then open http://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
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

    def start(self, goal: str, mode: str, seed: int | None, slip: float = 0.0) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running, self.events = True, []
        threading.Thread(target=self._run, args=(goal, mode, seed, slip), daemon=True).start()
        return True

    def _run(self, goal: str, mode: str, seed: int | None, slip: float) -> None:
        try:
            harness = Harness(mode=mode, on_event=self.push, live=True, slip=slip)
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
        elif self.path.startswith("/stream.mjpg"):
            self._stream()
        elif self.path.startswith("/events"):
            since = int(self.path.split("since=")[-1]) if "since=" in self.path else 0
            with STATE.lock:
                body = {"running": STATE.running, "events": STATE.events[since:], "total": len(STATE.events)}
            self._send(200, json.dumps(body, ensure_ascii=False).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def _stream(self) -> None:
        """MJPEG: push each new frame as soon as the simulator writes it (about 25 fps while moving)."""
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        frame, last = LIVE_DIR / "frame.jpg", 0.0
        try:
            while True:
                mtime = frame.stat().st_mtime if frame.exists() else 0.0
                if mtime != last:
                    last, data = mtime, frame.read_bytes()
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                    self.wfile.flush()
                time.sleep(0.02)
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser closed the tab

    def do_POST(self) -> None:
        if self.path != "/run":
            return self._send(404, b"not found", "text/plain")
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        seed = req.get("seed")
        ok = STATE.start(req.get("goal", "").strip() or "把红色方块放进托盘", req.get("mode", "plan"),
                         int(seed) if seed not in (None, "") else None, float(req.get("slip") or 0))
        self._send(200 if ok else 409, json.dumps({"started": ok}).encode(), "application/json")


def serve(port: int = 8765) -> None:
    from robomcp.sim import TabletopSim

    # Render one still frame so the page shows the scene before the first run.
    sim = TabletopSim()
    sim._live_dir = LIVE_DIR
    sim.write_live_frame()
    print(f"RoboMCP console: http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
