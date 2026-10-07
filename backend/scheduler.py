"""Background scheduler: periodic jobs and their registration.

Owns the ``_scheduler`` singleton, the per-tick job functions, and the
settings-driven auto-backup registration. The lifespan in
:mod:`backend.app` only calls :func:`start_scheduler`; settings updates
call :func:`reschedule_auto_backup`.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.db.engine import SessionLocal
from backend.logger import logger
from backend.node.sync import clean_stale_sessions_all_nodes, sync_all_user_limits
from backend.operations.observability.live import POLL_SECONDS, collect_live_snapshot

_scheduler = None
_in_worker = False  # True once this process's scheduler is the jobs worker's


async def auto_sync_limits_job():
    db = SessionLocal()
    try:
        await sync_all_user_limits(db)
    finally:
        db.close()


async def auto_clean_stale_job():
    db = SessionLocal()
    try:
        await clean_stale_sessions_all_nodes(db)
    finally:
        db.close()


async def auto_daily_alerts_job():
    """Push the daily expiring/out-of-traffic summary to the owner once a day."""
    from backend.operations.observability.notifier import run_daily_alerts

    await asyncio.to_thread(run_daily_alerts)


async def auto_prune_audit_job():
    from backend.operations.billing.usage import prune_daily
    from backend.operations.observability.audit import prune_audit_logs

    db = SessionLocal()
    try:
        removed = await asyncio.to_thread(prune_audit_logs, db)
        if removed:
            logger.info("Pruned %s audit log row(s) older than 90 days", removed)
        removed_daily = await asyncio.to_thread(prune_daily, db)
        if removed_daily:
            logger.info("Pruned %s daily usage row(s) older than 90 days", removed_daily)
    finally:
        db.close()


async def _notify_backup_failure(detail: str, *, enabled: bool) -> None:
    """Tell the owner when the scheduled backup did not happen.

    Audit rows alone are invisible until someone looks; a silent missing
    backup is the failure this notice exists for. Best-effort like the job
    itself: never raises.
    """
    if not enabled:
        return
    try:
        from backend.operations.observability.notifier import send_telegram

        await asyncio.to_thread(send_telegram, f"OVManager scheduled backup failed: {detail}")
    except Exception:
        logger.exception("Backup failure notice could not be sent")


async def auto_backup_job():
    """Run the scheduled panel database backup when enabled in settings.

    Best-effort by design: a failed backup must not kill the scheduler, so every
    outcome is logged and audited instead of raised.
    """
    from backend.operations.observability.audit import log_event
    from backend.routers.maintenance import create_panel_backup

    try:
        from backend.db.models import Settings

        db = SessionLocal()
        try:
            settings = db.query(Settings).first()
            enabled = bool(getattr(settings, "auto_backup_enabled", False))
            keep = int(getattr(settings, "auto_backup_keep", 50) or 50)
            offsite_target = getattr(settings, "offsite_backup_target", None) or ""
            telegram_backup_enabled = bool(getattr(settings, "telegram_backup_enabled", False))
        finally:
            db.close()

        if not enabled:
            return

        try:
            backup_path = await asyncio.to_thread(create_panel_backup, keep)
        except Exception as exc:
            logger.exception("Scheduled auto backup failed")
            log_event(None, "maintenance.backup", actor="auto", detail=f"Scheduled backup failed: {exc}")
            await _notify_backup_failure(str(exc), enabled=telegram_backup_enabled)
            return

        if backup_path is None:
            logger.warning("Scheduled auto backup skipped: database file not found")
            log_event(None, "maintenance.backup", actor="auto", detail="Scheduled backup skipped: database file not found")
            await _notify_backup_failure("database file not found", enabled=telegram_backup_enabled)
            return

        logger.info("Scheduled auto backup created: %s", backup_path.name)
        log_event(None, "maintenance.backup", actor="auto", detail=f"Backup created: {backup_path.name}")

        if offsite_target.strip():
            from backend.operations.backup.offsite import push_offsite

            pushed = await asyncio.to_thread(push_offsite, backup_path, offsite_target)
            if pushed:
                log_event(None, "maintenance.offsite_backup", actor="auto", detail=f"Offsite copy pushed: {backup_path.name}")
            else:
                log_event(None, "maintenance.offsite_backup", actor="auto", detail=f"Offsite copy failed for {backup_path.name}")

        if telegram_backup_enabled:
            from backend.db import crud
            from backend.operations.backup.telegram import send_backup_document

            db = SessionLocal()
            try:
                settings = crud.get_settings(db)
                result = await asyncio.to_thread(send_backup_document, backup_path, settings)
            finally:
                db.close()
            if result.ok:
                log_event(
                    None,
                    "maintenance.telegram_backup",
                    actor="auto",
                    detail=f"Telegram copy delivered: {backup_path.name} message={result.message_id}",
                )
            else:
                log_event(
                    None,
                    "maintenance.telegram_backup",
                    actor="auto",
                    detail=f"Telegram copy failed for {backup_path.name}: {result.error}",
                )
    except Exception:
        logger.exception("Scheduled auto backup job crashed")


def set_scheduler_instance(scheduler) -> None:
    """Publish the scheduler instance for the helpers that re-register jobs.

    The worker process runs this in its own interpreter, so it has to set the
    module global itself; without it reschedule_auto_backup() would find None
    and silently never register the daily backup. Setting it also marks this
    process as the jobs worker, which owns the daily backup.
    """
    global _scheduler, _in_worker
    _scheduler = scheduler
    _in_worker = True


def reschedule_auto_backup():
    """Re-register the daily auto-backup job from the current settings.

    A no-op when the scheduler is not running. Called at startup and after a
    settings update.
    """
    scheduler = _scheduler
    if scheduler is None:
        return
    if not _in_worker and os.environ.get("OVM_WORKER") != "0":
        # The worker process owns the daily backup (see backend.worker): the
        # web scheduler registering it too would fire it twice a night — two
        # bundles, two Telegram copies. The worker re-reads settings every
        # minute, so a settings save reaches it within 60s. Without a worker
        # (OVM_WORKER=0) this process is the only scheduler, so it owns it.
        return
    try:
        scheduler.remove_job("auto_backup")
    except Exception:
        pass

    try:
        from backend.db.models import Settings

        db = SessionLocal()
        try:
            settings = db.query(Settings).first()
            enabled = bool(getattr(settings, "auto_backup_enabled", False))
            raw_time = str(getattr(settings, "auto_backup_time", "") or "")
        finally:
            db.close()
    except Exception:
        logger.exception("Could not read auto backup settings")
        return

    if not enabled:
        return

    try:
        hour, minute = (int(part) for part in raw_time.split(":"))
    except (TypeError, ValueError):
        logger.warning("Auto backup not scheduled: invalid auto_backup_time %r", raw_time)
        return

    try:
        scheduler.add_job(
            auto_backup_job,
            CronTrigger(hour=hour, minute=minute),
            id="auto_backup",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception:
        logger.exception("Could not register the auto backup job for %r", raw_time)
        return
    logger.info("Automatic backup scheduled daily at %02d:%02d", hour, minute)


def start_scheduler():
    """Register only the jobs that need this process's own state.

    The periodic database and node jobs live in the worker process
    (:mod:`backend.worker`). The two jobs below must not move: the live snapshot
    publishes to an in-process bus, and ``_watchdog_bot`` holds the bot child's
    Popen — both are process-local.
    """
    from backend.bot_supervisor import _watchdog_bot

    global _scheduler, _in_worker
    if _scheduler and _scheduler.running:
        return _scheduler
    _in_worker = False
    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(
        collect_live_snapshot,
        IntervalTrigger(seconds=POLL_SECONDS),
        id="live_snapshot",
        replace_existing=True,
        next_run_time=datetime.now(tz=UTC),
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _watchdog_bot,
        CronTrigger(minute="*/1"),
        id="watchdog_bot",
        replace_existing=True,
        misfire_grace_time=30,
    )
    scheduler.start()
    _scheduler = scheduler
    reschedule_auto_backup()
    return scheduler
