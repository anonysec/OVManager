"""Debounced node restarts: edits set one flag, one consumer fans out (Task 8)."""

import asyncio
import json
import time

import pytest

from backend.operations import restart_debounce as rd


@pytest.fixture(autouse=True)
def _clean_flag():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        rd.clear_restart_flag(db)
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        rd.clear_restart_flag(db)
    finally:
        db.close()


def test_n_edits_collapse_to_one_flag():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        for i in range(5):
            rd.mark_restart_pending(db, f"edit-{i}")
        flag = rd.read_restart_flag(db)
        assert flag["flag"] == 1
        assert flag["reason"] == "edit-4", "the newest reason wins, one flag not five"
    finally:
        db.close()


def test_consumer_success_clears_flag(monkeypatch):
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        rd.mark_restart_pending(db, "protocol-change")
    finally:
        db.close()

    async def fake_all_ok(nodes, pid):
        return True

    monkeypatch.setattr(rd, "_restart_all", fake_all_ok)
    asyncio.run(rd.process_restart_debounce())

    db = SessionLocal()
    try:
        assert rd.read_restart_flag(db) is None, "all-success must clear the flag"
    finally:
        db.close()


def test_consumer_partial_failure_keeps_flag(monkeypatch):
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        rd.mark_restart_pending(db, "port-change")
    finally:
        db.close()

    async def fake_partial(nodes, pid):
        return False

    monkeypatch.setattr(rd, "_restart_all", fake_partial)
    asyncio.run(rd.process_restart_debounce())

    db = SessionLocal()
    try:
        flag = rd.read_restart_flag(db)
        assert flag is not None and flag["flag"] == 1, "a partial failure must keep the flag"
        assert flag["next_retry_at"] > time.time(), "a failed fan-out must schedule a capped retry"
    finally:
        db.close()


def test_consumer_respects_backoff(monkeypatch):
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        rd.mark_restart_pending(db, "pki-push")
        # push the next retry far into the future
        raw = json.loads(rd._read_raw(db) or "{}")
        rd._write_flag(db, 1, "pki-push", 1, time.time() + 3600)
    finally:
        db.close()

    called = []

    async def fake_all(nodes, pid):
        called.append(1)
        return True

    monkeypatch.setattr(rd, "_restart_all", fake_all)
    asyncio.run(rd.process_restart_debounce())
    assert called == [], "a pending backoff must hold the consumer off"

    assert raw is not None  # keep the intermediate read honest


def test_stale_flag_retried_at_startup():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        # a flag that has been stuck past the stale window, with a long backoff
        rd._write_flag(db, 1, "stale", 3, time.time() + 3600)
        # rewind updated_at to 10 minutes ago
        payload = json.loads(rd._read_raw(db))
        payload["updated_at"] = time.time() - rd.STALE_SECONDS - 1
        from sqlalchemy import text

        db.execute(
            text("UPDATE settings_kv SET value = :v WHERE key = :k"),
            {"v": json.dumps(payload), "k": rd.RESTART_FLAG_KEY},
        )
        db.commit()

        assert rd.retry_stale_restart_flag(db) is True, "a stale flag must be re-queued at startup"
        flag = rd.read_restart_flag(db)
        assert flag["flag"] == 1
        assert flag["next_retry_at"] == 0, "startup must clear the backoff so the next run retries now"
    finally:
        db.close()
