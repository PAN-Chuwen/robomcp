"""Sim worker: reap stale episodes, claim one, run it on the main thread, heartbeat, record the result.

One process runs one episode at a time (MuJoCo renders on the main thread); scale by running more
processes. Heartbeats go from a background thread with their own DB transactions.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import signal
import socket
import threading
import time
import traceback
import uuid

from sqlalchemy.orm import Session, sessionmaker

from robomcp_platform import queue
from robomcp_platform.config import Settings, get_settings
from robomcp_platform.db import make_engine, make_sessionmaker
from robomcp_platform.runner import EpisodeRunner, EpisodeSpec

log = logging.getLogger("robomcp_platform.worker")


def load_runner(path: str) -> EpisodeRunner:
    """Instantiate a runner from 'module:factory' (a class or zero-argument callable)."""
    module_name, _, attr = path.partition(":")
    if not attr:
        raise ValueError(f"runner must look like 'module:factory', got {path!r}")
    runner = getattr(importlib.import_module(module_name), attr)()
    if not isinstance(runner, EpisodeRunner):
        raise TypeError(f"{path} did not produce an EpisodeRunner (needs a run(spec) method)")
    return runner


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class _Heartbeat(threading.Thread):
    def __init__(self, sm: sessionmaker[Session], episode_id: uuid.UUID, worker_id: str, interval_s: float):
        super().__init__(name=f"heartbeat-{episode_id}", daemon=True)
        self._sm, self._episode_id, self._worker_id, self._interval = sm, episode_id, worker_id, interval_s
        self._halt = threading.Event()
        self.lost_claim = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(self._interval):
            try:
                with self._sm.begin() as s:
                    alive = queue.heartbeat(s, self._episode_id, self._worker_id)
            except Exception:  # a DB blip must not kill the episode; the next beat retries
                log.exception("heartbeat failed for episode %s", self._episode_id)
                continue
            if not alive:
                log.warning("lost claim on episode %s (reaped?)", self._episode_id)
                self.lost_claim.set()
                return

    def stop(self) -> None:
        self._halt.set()
        self.join()


class Worker:
    def __init__(
        self,
        sm: sessionmaker[Session],
        runner: EpisodeRunner,
        settings: Settings,
        worker_id: str | None = None,
    ):
        self.sm, self.runner, self.settings = sm, runner, settings
        self.worker_id = worker_id or default_worker_id()
        self._last_reap = float("-inf")

    def reap(self) -> list[queue.Reaped]:
        with self.sm.begin() as s:
            reaped = queue.reap_stale(s, self.settings.heartbeat_timeout_s, self.settings.max_attempts)
        for r in reaped:
            log.warning("reaped stale episode %s -> %s", r.episode_id, r.status)
        return reaped

    def run_once(self) -> bool:
        """Reap if due, then claim and run at most one episode. Returns True if an episode was run."""
        now = time.monotonic()
        if now - self._last_reap >= self.settings.heartbeat_interval_s:
            self.reap()
            self._last_reap = now
        with self.sm.begin() as s:
            spec = queue.claim_next(s, self.worker_id, self.settings.max_running_per_org)
        if spec is None:
            return False
        self._run(spec)
        return True

    def _run(self, spec: EpisodeSpec) -> None:
        log.info("episode %s: task=%s seed=%s repeat=%s attempt=%s",
                 spec.episode_id, spec.task_key, spec.seed, spec.repeat_index, spec.attempt)
        beat = _Heartbeat(self.sm, spec.episode_id, self.worker_id, self.settings.heartbeat_interval_s)
        beat.start()
        try:
            result = self.runner.run(spec)
        except Exception as exc:
            beat.stop()
            detail = f"{type(exc).__name__}: {exc}"
            log.error("episode %s raised %s\n%s", spec.episode_id, detail, traceback.format_exc())
            with self.sm.begin() as s:
                status = queue.fail(s, spec.episode_id, self.worker_id, detail, self.settings.max_attempts)
            log.info("episode %s -> %s", spec.episode_id, status or "claim lost, result dropped")
            return
        beat.stop()
        with self.sm.begin() as s:
            recorded = queue.complete(s, spec.episode_id, self.worker_id, result)
        if recorded:
            log.info("episode %s -> %s", spec.episode_id, "succeeded" if result.success else "failed")
        else:
            log.warning("episode %s finished after its claim was lost; result dropped", spec.episode_id)

    def run_forever(self, stop: threading.Event, max_episodes: int | None = None) -> int:
        done = 0
        while not stop.is_set() and (max_episodes is None or done < max_episodes):
            try:
                ran = self.run_once()
            except Exception:
                log.exception("worker loop error; backing off")
                ran = False
            if ran:
                done += 1
            else:
                stop.wait(self.settings.poll_interval_s)
        return done


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="robomcp-worker", description="Run RoboMCP sim episodes from the queue.")
    p.add_argument("--runner", help="'module:factory' for the EpisodeRunner (default: ROBOMCP_WORKER_RUNNER)")
    p.add_argument("--worker-id", help="identifier stored in episodes.claimed_by (default: host:pid:random)")
    p.add_argument("--max-episodes", type=int, help="exit after running this many episodes")
    p.add_argument("--once", action="store_true", help="run at most one episode, then exit")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    engine = make_engine(settings.database_url)
    worker = Worker(make_sessionmaker(engine), load_runner(args.runner or settings.worker_runner), settings,
                    args.worker_id)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # finish the current episode, then exit

    log.info("worker %s started", worker.worker_id)
    if args.once:
        worker.run_once()
    else:
        worker.run_forever(stop, args.max_episodes)
    engine.dispose()
