# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Background scheduler: periodic jobs and their registration.

Owns the ``_scheduler`` singleton, the per-tick job functions, and the
settings-driven auto-backup registration. The lifespan in
:mod:`backend.app` only calls :func:`start_scheduler`; settings updates
call :func:`reschedule_auto_backup`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.db.engine import SessionLocal
from backend.logger import logger
from backend.node.task import clean_stale_sessions_all_nodes, sync_all_user_limits
from backend.operations.daily_checks import check_user_used_traffic, enforce_user_limits
from backend.operations.live import POLL_SECONDS, collect_live_snapshot
from backend.operations.metrics import collect_metrics

_scheduler = None


# ── Background jobs ───────────────────────────────────────────────
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
    from backend.operations.notifier import run_daily_alerts

    # Sync job: run off the event loop so the blocking HTTPS call cannot
    # stall request handling (same pattern as the audit prune below).
    await asyncio.to_thread(run_daily_alerts)


async def auto_prune_audit_job():
    from backend.operations.audit import prune_audit_logs
    from backend.operations.usage_history import prune_daily

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


async def auto_backup_job():
    """Run the scheduled panel database backup when enabled in settings.

    Best-effort by design: every outcome is audited and logged, and nothing
    is ever raised — a failed backup must not kill the scheduler.
    """
    from backend.operations.audit import log_event
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
            return

        if backup_path is None:
            logger.warning("Scheduled auto backup skipped: database file not found")
            log_event(None, "maintenance.backup", actor="auto", detail="Scheduled backup skipped: database file not found")
            return

        logger.info("Scheduled auto backup created: %s", backup_path.name)
        log_event(None, "maintenance.backup", actor="auto", detail=f"Backup created: {backup_path.name}")

        # Optional offsite copy of the fresh backup (rsync, fallback scp).
        if offsite_target.strip():
            from backend.operations.offsite_backup import push_offsite

            pushed = await asyncio.to_thread(push_offsite, backup_path, offsite_target)
            if pushed:
                log_event(None, "maintenance.offsite_backup", actor="auto", detail=f"Offsite copy pushed: {backup_path.name}")
            else:
                log_event(None, "maintenance.offsite_backup", actor="auto", detail=f"Offsite copy failed for {backup_path.name}")

        # Telegram is a separate opt-in destination. The bundle goes as-is:
        # delivery is owner-only (bot + private chat) and the server itself
        # is the trust boundary.
        if telegram_backup_enabled:
            from backend.db import crud
            from backend.operations.telegram_backup import send_backup_document

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


def reschedule_auto_backup():
    """Re-register the daily auto-backup job from the current settings.

    Removes any existing ``auto_backup`` job, then adds it back with the
    configured time when auto backup is enabled. A no-op when the scheduler
    is not running. Called at startup and after a settings update.
    """
    scheduler = _scheduler
    if scheduler is None:
        return
    try:
        scheduler.remove_job("auto_backup")
    except Exception:
        # JobLookupError (nothing registered) is the common case; a stopped
        # scheduler is equally harmless here.
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
    from backend.bot_supervisor import _watchdog_bot

    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(
        check_user_used_traffic,
        CronTrigger(minute="*/5"),
        id="check_user_used_traffic",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        enforce_user_limits,
        CronTrigger(minute="*/10"),
        id="enforce_user_limits",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        collect_metrics,
        CronTrigger(minute="*/5"),
        id="collect_metrics",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        auto_sync_limits_job,
        CronTrigger(minute="*/30"),
        id="auto_sync_limits",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        auto_clean_stale_job,
        CronTrigger(minute="*/15"),
        id="auto_clean_stale",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        auto_prune_audit_job,
        CronTrigger(hour="*/6"),
        id="prune_audit_logs",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        auto_daily_alerts_job,
        CronTrigger(hour=9, minute=15),
        id="daily_alerts",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Live collector: single poller for all nodes. Request handlers and SSE
    # subscribers use its in-memory snapshot instead of fanning out to nodes.
    # First run is immediate so the cache is warm before the first page load.
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
    # Auto backup is OFF by default; only registered when enabled in settings.
    reschedule_auto_backup()
    return scheduler
