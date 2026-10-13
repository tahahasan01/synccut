"""Background jobs on a thread pool, with state kept in the project document.

v0 stand-in for Celery + Redis. The UI polls the project to see progress.
"""

from __future__ import annotations

import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .store import Store, new_id

log = logging.getLogger("synccut.jobs")
MAX_JOBS_KEPT = 30


class JobContext:
    def __init__(self, store: Store, pid: str, job_id: str):
        self.store, self.pid, self.job_id = store, pid, job_id
        self._last = 0.0

    def progress(self, fraction: float, message: str = "", *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < 0.5:
            return
        self._last = now
        self._set(progress=round(max(0.0, min(1.0, fraction)), 3), message=message)

    def _set(self, **fields) -> None:
        def apply(project: dict) -> None:
            for job in project["jobs"]:
                if job["id"] == self.job_id:
                    job.update(fields)

        self.store.update(self.pid, apply)


class Jobs:
    def __init__(self, store: Store, workers: int = 2):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")

    def recover(self) -> None:
        """Jobs that were running when the server stopped can't resume; mark them failed."""
        for project in self.store.list():
            if any(j["status"] in ("queued", "running") for j in project["jobs"]):
                def apply(p: dict) -> None:
                    for job in p["jobs"]:
                        if job["status"] in ("queued", "running"):
                            job.update(status="failed", error="Server restarted while this job was running. Start it again.")
                self.store.update(project["id"], apply)

    def start(self, pid: str, job_type: str, fn: Callable[[JobContext], None], label: str = "") -> dict:
        job = {
            "id": new_id("j"),
            "type": job_type,
            "label": label or job_type,
            "status": "queued",
            "progress": 0.0,
            "message": "Waiting to start",
            "error": None,
            "created_at": time.time(),
            "finished_at": None,
        }

        def add(project: dict) -> None:
            project["jobs"] = [job] + project["jobs"][: MAX_JOBS_KEPT - 1]

        self.store.update(pid, add)
        self.pool.submit(self._run, pid, job["id"], fn)
        return job

    def _run(self, pid: str, job_id: str, fn: Callable[[JobContext], None]) -> None:
        ctx = JobContext(self.store, pid, job_id)
        ctx._set(status="running", message="Starting")
        try:
            fn(ctx)
        except Exception as exc:
            log.error("job %s failed:\n%s", job_id, traceback.format_exc())
            try:
                ctx._set(status="failed", error=str(exc) or exc.__class__.__name__, finished_at=time.time())
            except Exception:
                log.exception("could not record failure for job %s", job_id)
            return
        ctx._set(status="succeeded", progress=1.0, message="Done", finished_at=time.time())
