"""Live demo runner: generates a batch every N seconds, writes it to data/inbox/ as CSV (ready for
NiFi) AND POSTs it to /ingest/batch (direct path). If the HTTP call fails it falls back to the
in-process ingest so the demo never stops."""
import asyncio
import logging
import os
import random
import time

import httpx
from fastapi.concurrency import run_in_threadpool

from app import db as dbmod
from app.config import settings
from app.security import create_access_token
from app.services import events, stats
from app.services.ingest import ingest_rows
from app.utils import utcnow
from simulator.generator import generate_batch, write_csv

log = logging.getLogger("simulator")


class DemoRunner:
    def __init__(self):
        self.task: asyncio.Task | None = None
        self.state = "idle"  # idle | running | finished | stopped
        self.speed = 1
        self.batch_no = 0
        self.total_batches = 0
        self.interval_seconds = 30.0
        self.duration_minutes = 10.0
        self.next_batch_in = 0.0
        self.started_at: float | None = None
        self.start_hour: int | None = None
        self.direct_ok = 0
        self.fallbacks = 0
        self.last_file: str | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> dict:
        return {
            "state": self.state, "running": self.running, "speed": self.speed, "batch_no": self.batch_no,
            "total_batches": self.total_batches, "interval_seconds": self.interval_seconds,
            "duration_minutes": self.duration_minutes, "next_batch_in": round(self.next_batch_in, 1),
            "elapsed_s": round(time.time() - self.started_at) if self.started_at and self.running else 0,
            "direct_ingest": settings.sim_direct_ingest, "direct_ok": self.direct_ok, "fallbacks": self.fallbacks,
            "last_file": self.last_file,
        }

    async def start(self, duration_minutes: float, interval_seconds: float, speed: int, reset: bool,
                    start_hour: int | None) -> None:
        if reset:
            await run_in_threadpool(self._reset)
        self.duration_minutes, self.interval_seconds, self.speed = duration_minutes, interval_seconds, speed
        self.total_batches = max(1, round(duration_minutes * 60 / interval_seconds))
        self.batch_no, self.direct_ok, self.fallbacks, self.next_batch_in = 0, 0, 0, 0.0
        self.start_hour, self.started_at, self.state = start_hour, time.time(), "running"
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self.running:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.state = "stopped"
            await run_in_threadpool(self._log, "sim", "Live demo stopped by admin")

    # ---- internals ----
    @staticmethod
    def _reset():
        with dbmod.SessionLocal() as db:
            stats.reset_data(db)

    @staticmethod
    def _log(kind: str, message: str, data: dict | None = None):
        with dbmod.SessionLocal() as db:
            events.log_event(db, kind, message, data)

    async def _loop(self):
        rng = random.Random()
        await run_in_threadpool(self._log, "sim", f"Live demo started: {self.total_batches} batches, one every "
                                f"{self.interval_seconds:g}s at {self.speed}x")
        try:
            for n in range(1, self.total_batches + 1):
                self.batch_no = n
                await self._run_batch(n, rng)
                if n == self.total_batches:
                    break
                progress = 0.0
                while progress < 1.0:  # speed can change mid-wait
                    await asyncio.sleep(0.25)
                    progress += 0.25 * self.speed / self.interval_seconds
                    self.next_batch_in = max(0.0, (1 - progress) * self.interval_seconds / self.speed)
            self.state, self.next_batch_in = "finished", 0.0
            await run_in_threadpool(self._log, "sim", f"Live demo finished: {self.total_batches} batches sent")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never die silently
            log.exception("simulator loop crashed")
            self.state = "stopped"
            await run_in_threadpool(self._log, "warning", f"Simulator crashed: {exc}")

    async def _run_batch(self, n: int, rng: random.Random):
        now = utcnow()
        hour = float(self.start_hour) if self.start_hour is not None else None
        rows, meta = generate_batch(now, rng, hour)
        path = await run_in_threadpool(write_csv, rows, settings.inbox_dir, n, now)
        self.last_file = os.path.basename(path)
        await run_in_threadpool(
            self._log, "sim", f"Batch {n}/{self.total_batches}: generated {meta['donations']} donations + "
            f"{meta['requests']} requests (~{meta['dirty']} dirty) -> inbox/{self.last_file}", meta)
        if not settings.sim_direct_ingest:
            return
        try:
            token = create_access_token("admin@foodrescue.demo", "admin", minutes=15)
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{settings.api_internal_url}/ingest/batch",
                                         json={"source": "sim", "rows": rows},
                                         headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            self.direct_ok += 1
        except Exception as exc:
            self.fallbacks += 1
            log.warning("direct ingest failed (%s); using in-process fallback", exc)
            await run_in_threadpool(self._log, "warning",
                                    f"Direct /ingest/batch failed for batch {n} ({type(exc).__name__}); "
                                    "falling back to in-process ingest")
            await run_in_threadpool(self._ingest_fallback, rows)

    @staticmethod
    def _ingest_fallback(rows: list[dict]):
        with dbmod.SessionLocal() as db:
            ingest_rows(db, rows, source="sim")


runner = DemoRunner()
