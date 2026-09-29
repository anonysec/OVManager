"""The scheduled-jobs worker: the periodic jobs, in their own process.

Why a separate process at all. These jobs share a process with the HTTP
server, so a job that wedges takes the panel down with it: a backup that
fills the disk, a traffic-enforcement pass that fans out to nodes the
moment a lot of them are unreachable. The panel then stops answering
/health and stops serving the login page, which is indistinguishable from
a hung install. Measured cost of the isolation is ~45 MB of resident
memory for the second interpreter.

What stays in the web process, deliberately, because it cannot move:

- ``collect_live_snapshot`` publishes to the in-process live bus that
  ``routers/telemetry.py`` subscribes to for SSE. A collector in another
  process would publish to a bus with no subscribers, and the live view
  would silently stop updating.
- ``_watchdog_bot`` holds the ``Popen`` for the bot child, which the web
  process starts in its lifespan. In another process that handle is
  None and the watchdog would do nothing.

So this process runs the periodic database and node work, and the web
process keeps the two jobs that are tied to in-process state.

Exactly one worker may run. A second one would double every schedule --
two backups a night, two enforcement passes -- so the entrypoint takes an
exclusive lock on the data dir and exits if it cannot. The web process
supervises and restarts this child, which is also why the lock rather
than a pidfile: a pidfile cannot tell a live worker from a stale one
after a crash.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import subprocess
import sys
from pathlib import Path

from backend.data_paths import DATA_DIR
from backend.logger import logger

LOCK_NAME = "scheduler.lock"
RESTART_BACKOFF_SECONDS = 30.0


def _lock_path() -> Path:
    return Path(DATA_DIR) / LOCK_NAME


def acquire_single_instance_lock():
    """Take the exclusive worker lock, or return None if a worker holds it.

    The file handle is deliberately returned and kept open: flock is
    released by the kernel when the process dies, however it dies, so a
    crashed worker never leaves a lock behind that blocks the next start.
    """
    path = _lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+")
    except OSError as exc:
        # A read-only data dir must not stop the panel starting; without the
        # lock the worst case is a duplicate worker, which is recoverable,
        # whereas refusing to start the jobs at all is not.
        logger.warning("worker: cannot open %s (%s) — continuing without the single-instance lock", path, exc)
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def register_worker_jobs(scheduler) -> None:
    """Register every job that does not need the web process's own state.

    Kept in one place so the split is reviewable: anything added here runs
    out of process, and anything needing in-process state belongs in
    ``backend.scheduler.start_scheduler`` instead.
    """
    from apscheduler.triggers.cron import CronTrigger

    from backend.operations.billing.daily import check_user_used_traffic, enforce_user_limits
    from backend.operations.observability.metrics import collect_metrics
    from backend.scheduler import (
        auto_clean_stale_job,
        auto_daily_alerts_job,
        auto_prune_audit_job,
        auto_sync_limits_job,
        reschedule_auto_backup,
    )

    jobs = (
        (check_user_used_traffic, CronTrigger(minute="*/5"), 60),
        (enforce_user_limits, CronTrigger(minute="*/10"), 60),
        (collect_metrics, CronTrigger(minute="*/5"), 60),
        (auto_sync_limits_job, CronTrigger(minute="*/30"), 60),
        (auto_clean_stale_job, CronTrigger(minute="*/15"), 60),
        (auto_prune_audit_job, CronTrigger(hour="*/6"), 300),
        (auto_daily_alerts_job, CronTrigger(hour=9, minute=15), 3600),
    )
    for fn, trigger, grace in jobs:
        scheduler.add_job(fn, trigger, id=fn.__name__, replace_existing=True, misfire_grace_time=grace)

    # The web process can no longer re-register this when an operator changes
    # the backup time, because the job lives here. So the worker re-reads the
    # settings itself, every minute: the cost is that a change takes up to a
    # minute to apply, and the alternative is a control channel between two
    # processes for one cron trigger.
    scheduler.add_job(
        reschedule_auto_backup,
        CronTrigger(minute="*"),
        id="reschedule_auto_backup",
        replace_existing=True,
        misfire_grace_time=60,
    )


async def _run() -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from backend.scheduler import set_scheduler_instance

    lock = acquire_single_instance_lock()
    if lock is None:
        logger.warning("worker: another scheduler worker already holds %s — this one exits", _lock_path())
        return

    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    register_worker_jobs(scheduler)
    set_scheduler_instance(scheduler)
    scheduler.start()
    logger.info("worker: started with %d jobs", len(scheduler.get_jobs()))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - non-POSIX
            pass

    await stop.wait()
    logger.info("worker: stopping")
    scheduler.shutdown(wait=False)
    if lock is not None:
        lock.close()


def main() -> int:
    # Importing backend.logger is what configures logging — it installs its
    # handlers at module import, so the child's lines land in the same
    # app.log and on the same stderr as the panel's.
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:  # pragma: no cover
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ── Parent side: the web process supervises this child ────────────────────

_worker: subprocess.Popen | None = None
_monitor: asyncio.Task | None = None


def start_worker() -> None:
    """Start the jobs worker and watch it.

    A fresh interpreter rather than a fork: forking from a process with a
    running event loop and live threads is how you inherit a locked lock.
    The child gets this process's environment, so DATA_DIR and the rest
    point where the panel's do.
    """
    global _worker, _monitor
    if _worker is not None and _worker.poll() is None:
        return
    if os.environ.get("OVM_WORKER") == "0":
        # Escape hatch, and how the test suite keeps from spawning a real
        # second interpreter for every test that exercises the lifespan. The
        # worker itself is covered by tests/s/test_worker_process.py, which
        # turns this back on deliberately.
        return
    _worker = subprocess.Popen(  # noqa: S603 - fixed argv, this interpreter
        [sys.executable, "-m", "backend.worker"],
        env=os.environ.copy(),
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    logger.info("worker: started as pid %s", _worker.pid)
    _monitor = asyncio.get_running_loop().create_task(_watch_worker())


async def _watch_worker() -> None:
    """Restart the worker if it dies; the panel does not go down with it."""
    global _worker
    while True:
        try:
            await asyncio.to_thread(_worker.wait)  # type: ignore[union-attr]
        except asyncio.CancelledError:
            raise
        rc = _worker.returncode  # type: ignore[union-attr]
        if rc == 0:
            logger.info("worker: exited cleanly (rc=0) — not restarting")
            return
        logger.warning("worker: died (rc=%s) — restarting in %.0fs", rc, RESTART_BACKOFF_SECONDS)
        await asyncio.sleep(RESTART_BACKOFF_SECONDS)
        try:
            _worker = subprocess.Popen(  # noqa: S603
                [sys.executable, "-m", "backend.worker"],
                env=os.environ.copy(),
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            logger.info("worker: restarted as pid %s", _worker.pid)
        except OSError as exc:  # pragma: no cover - interpreter vanished
            logger.error("worker: cannot restart: %s", exc)
            return


def stop_worker(timeout: float = 10.0) -> None:
    """Terminate the worker on panel shutdown."""
    global _worker, _monitor
    if _monitor is not None:
        _monitor.cancel()
        _monitor = None
    proc = _worker
    _worker = None
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
        proc.wait(timeout=5)


def worker_alive() -> bool:
    """Whether the jobs worker is currently running."""
    return _worker is not None and _worker.poll() is None
