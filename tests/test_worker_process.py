"""The scheduled-jobs worker process.

The split is the safety property, so it is asserted directly: the jobs that
can block for a long time must not be registered in the web process, and the
two that genuinely need in-process state must be.
"""

import asyncio
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _job_ids(scheduler) -> set[str]:
    return {j.id for j in scheduler.get_jobs()}


# ── the split ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_web_process_registers_only_the_jobs_that_need_its_own_state():
    """A blocking job in the web process is a job that can take the panel down.

    collect_live_snapshot publishes to the in-process live bus that
    routers/telemetry.py subscribes to for SSE, and _watchdog_bot holds the
    Popen for the bot child this process starts. Neither can move.

    Asserts the *absences*, not an exact set. start_scheduler() also registers
    auto_backup, driven by whatever the shared test database happens to have
    enabled — so an exact set only held when this ran before any other test
    touched those settings, which is how a five-runs-one-failure flake came
    from a test that had been green for a week.
    """
    import backend.scheduler as sched
    from backend.scheduler import start_scheduler

    sched._scheduler = None
    scheduler = start_scheduler()
    try:
        ids = _job_ids(scheduler)
        assert {"live_snapshot", "watchdog_bot"} <= ids, f"missing the in-process jobs: {ids}"
        for worker_only in (
            "check_user_used_traffic",
            "enforce_user_limits",
            "collect_metrics",
            "auto_sync_limits_job",
            "auto_clean_stale_job",
            "auto_prune_audit_job",
            "auto_daily_alerts_job",
        ):
            assert worker_only not in ids, f"{worker_only} must not run in the web process"
    finally:
        scheduler.shutdown(wait=False)
        import backend.scheduler as sched

        sched._scheduler = None


@pytest.mark.asyncio
async def test_the_heavy_periodic_jobs_are_registered_in_the_worker():
    """These are the jobs that fan out to nodes and touch the database."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from backend.worker import register_worker_jobs

    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    register_worker_jobs(scheduler)
    scheduler.start()  # get_jobs() on an unstarted scheduler raises
    ids = _job_ids(scheduler)

    for expected in (
        "check_user_used_traffic",
        "enforce_user_limits",
        "collect_metrics",
        "auto_sync_limits_job",
        "auto_clean_stale_job",
        "auto_prune_audit_job",
        "auto_daily_alerts_job",
    ):
        assert expected in ids, f"{expected} is not registered in the worker"

    # The two in-process jobs must NOT be here, or they would publish into a
    # bus with no subscribers and watchdog a process this one never started.
    assert "live_snapshot" not in ids
    assert "watchdog_bot" not in ids
    scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_no_job_is_registered_in_both_places():
    """A job in both processes would run twice — two backups a night."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    import backend.scheduler as sched
    from backend.scheduler import start_scheduler
    from backend.worker import register_worker_jobs

    sched._scheduler = None
    web = start_scheduler()
    worker = AsyncIOScheduler()
    register_worker_jobs(worker)
    worker.start()
    try:
        overlap = _job_ids(web) & _job_ids(worker)
        assert not overlap, f"registered in both processes: {overlap}"
    finally:
        web.shutdown(wait=False)
        worker.shutdown(wait=False)
        import backend.scheduler as sched

        sched._scheduler = None


# ── the single-instance lock ──────────────────────────────────────────────


def test_a_second_worker_refuses_to_run():
    """Two workers would double every schedule.

    This project has already been bitten by double-scheduling (auto-backup
    exists in both bash and the panel), so the guard is explicit rather than
    left to the supervisor.
    """
    from backend.worker import acquire_single_instance_lock

    first = acquire_single_instance_lock()
    try:
        assert first is not None, "the first worker must get the lock"
        assert acquire_single_instance_lock() is None, "a second worker must be refused"
    finally:
        if first is not None:
            first.close()

    # Released on close, so a replacement worker can start immediately.
    replacement = acquire_single_instance_lock()
    assert replacement is not None
    replacement.close()


def test_the_lock_is_released_when_the_process_dies(tmp_path):
    """flock, not a pidfile: a crashed worker must not block the next start."""

    # Exits non-zero without closing the handle, which is what a crash looks
    # like to the kernel.
    script = (
        f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from backend.worker import acquire_single_instance_lock;"
        "h = acquire_single_instance_lock();"
        "print('got' if h else 'refused');"
        "sys.exit(9 if h else 0)"
    )
    env = {**os.environ, "DATA_DIR": str(tmp_path)}
    crashed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60)
    assert "got" in crashed.stdout, crashed.stderr[-400:]

    # The crashed process is gone, so the lock must be free.
    probe = (
        f"import sys; sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from backend.worker import acquire_single_instance_lock;"
        "print('got' if acquire_single_instance_lock() else 'refused')"
    )
    after = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=60)
    assert "got" in after.stdout, "the lock outlived the crashed worker"


# ── the real child ────────────────────────────────────────────────────────


def _create_schema(data_dir: Path) -> None:
    """Create the panel's tables in `data_dir`, as an install would have.

    In a subprocess, deliberately: backend.data_paths resolves DATA_DIR at
    import time and this process imported it against conftest's throwaway
    directory long before tmp_path existed, so building the schema here would
    put it in the wrong place and leave the child looking at an empty one.
    """
    script = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "from backend.db.engine import SessionLocal;"
        "from backend.db.migrations import _create_extra_tables, _create_mapped_tables;"
        "db = SessionLocal();"
        "_create_mapped_tables(db); _create_extra_tables(db); db.commit(); db.close()"
    )
    env = {**os.environ, "DATA_DIR": str(data_dir), "OVM_APP_DIR": str(data_dir)}
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, f"schema creation failed: {r.stderr[-600:]}"


def test_the_worker_child_registers_the_jobs(tmp_path):
    """End to end: a real interpreter, importing the app, taking the lock.

    This is the only test that turns OVM_WORKER back on, because it is the
    only one that should pay for a second interpreter.
    """
    # The worker reads the settings table on startup, so it needs the same
    # schema the panel would have created — an empty directory makes the child
    # die on a missing table, which is a test-fixture problem, not a worker one.
    _create_schema(tmp_path)
    env = {**os.environ, "DATA_DIR": str(tmp_path), "OVM_APP_DIR": str(tmp_path), "OVM_WORKER": "1"}
    log = tmp_path / "worker.log"
    with log.open("w") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "backend.worker"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            # Evidence it is the live instance: it took the single-instance
            # lock, and it is still running. Deliberately not asserting on a log
            # line — the panel's effective level is WARNING, so the worker's
            # INFO lines are suppressed and would never appear at all.
            lock = tmp_path / "scheduler.lock"
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline and not lock.exists():
                assert proc.poll() is None, f"worker exited early:\n{log.read_text(errors='replace')[-800:]}"
                time.sleep(0.2)
            assert lock.exists(), f"worker never took the lock:\n{log.read_text(errors='replace')[-800:]}"
            assert proc.poll() is None, "the worker is a daemon; it should still be running"
            time.sleep(1.0)  # and still running a moment later
            assert proc.poll() is None
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
                proc.wait(timeout=5)

    # Clean SIGTERM shutdown, not a kill.
    assert proc.returncode == 0, f"worker exited {proc.returncode}\n{log.read_text(errors='replace')[-600:]}"


@pytest.mark.asyncio
async def test_start_worker_is_a_noop_when_disabled(monkeypatch):
    """The test suite's opt-out must actually prevent the spawn."""
    import backend.worker as worker_mod

    monkeypatch.setenv("OVM_WORKER", "0")
    worker_mod._worker = None
    worker_mod.start_worker()
    assert worker_mod._worker is None


@pytest.mark.asyncio
async def test_worker_alive_tracks_the_child(monkeypatch):
    import backend.worker as worker_mod

    monkeypatch.setenv("OVM_WORKER", "1")
    worker_mod._worker = None
    worker_mod._monitor = None
    try:
        assert worker_mod.worker_alive() is False
        worker_mod.start_worker()
        assert worker_mod._worker is not None
        # Give the child a moment to be running, not just spawned.
        for _ in range(50):
            if worker_mod.worker_alive():
                break
            await asyncio.sleep(0.1)
        assert worker_mod.worker_alive() is True
    finally:
        worker_mod.stop_worker()
    assert worker_mod.worker_alive() is False


# ── the doctor check ──────────────────────────────────────────────────────


def _install_with_data_dir(data_dir: Path):
    from cli.env import Install

    return Install.detect(install_dir=str(data_dir / "opt"), data_dir=str(data_dir))


def test_doctor_reports_a_running_worker(tmp_path):
    from cli.doctor import check_worker

    lock = tmp_path / "scheduler.lock"
    handle = lock.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write("4242\n")
        handle.flush()
        result = check_worker(_install_with_data_dir(tmp_path))
        assert result.ok is True
        assert "4242" in result.detail
    finally:
        handle.close()


def test_doctor_flags_a_stale_lock_file(tmp_path):
    """A lock file nobody holds means the worker died and left it behind.

    The important half of this check: the panel looks healthy while the daily
    backup and limit enforcement have silently stopped.
    """
    from cli.doctor import check_worker

    (tmp_path / "scheduler.lock").write_text("4242\n")
    result = check_worker(_install_with_data_dir(tmp_path))
    assert result.ok is False
    assert "not running" in result.detail
    assert result.fix, "a failing check must say what to run"


def test_doctor_flags_a_missing_lock(tmp_path):
    from cli.doctor import check_worker

    result = check_worker(_install_with_data_dir(tmp_path))
    assert result.ok is False
    assert "no lock file" in result.detail


def test_doctor_check_is_in_the_reported_set(tmp_path):
    """It has to be in collect(), or operators never see it."""
    from cli.doctor import collect

    names = [c.name for c in collect(_install_with_data_dir(tmp_path))]
    assert "Worker" in names
    assert len(names) == 13, f"expected thirteen checks, got {len(names)}: {names}"
