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
    from types import SimpleNamespace

    from backend.db import crud
    from backend.db.engine import SessionLocal

    monkeypatch.setattr(crud, "get_active_nodes", lambda db: [SimpleNamespace(name="ok1"), SimpleNamespace(name="ok2")])

    db = SessionLocal()
    try:
        rd.mark_restart_pending(db, "protocol-change")
    finally:
        db.close()

    async def fake_all_ok(nodes, pid):
        return [n.name for n in nodes]

    monkeypatch.setattr(rd, "_restart_all", fake_all_ok)
    asyncio.run(rd.process_restart_debounce())

    db = SessionLocal()
    try:
        assert rd.read_restart_flag(db) is None, "all-success must clear the flag"
    finally:
        db.close()


def test_consumer_partial_failure_keeps_flag(monkeypatch):
    from types import SimpleNamespace

    from backend.db import crud
    from backend.db.engine import SessionLocal

    monkeypatch.setattr(crud, "get_active_nodes", lambda db: [SimpleNamespace(name="ok1"), SimpleNamespace(name="down1")])

    db = SessionLocal()
    try:
        rd.mark_restart_pending(db, "port-change")
    finally:
        db.close()

    async def fake_partial(nodes, pid):
        return ["ok1"]  # only one of the two succeeded

    monkeypatch.setattr(rd, "_restart_all", fake_partial)
    asyncio.run(rd.process_restart_debounce())

    db = SessionLocal()
    try:
        flag = rd.read_restart_flag(db)
        assert flag is not None and flag["flag"] == 1, "a partial failure must keep the flag"
        assert flag["next_retry_at"] > time.time(), "a failed fan-out must schedule a capped retry"
        assert flag["done"] == ["ok1"], "the succeeded node must not be retried"
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
        return [n.name for n in nodes]

    monkeypatch.setattr(rd, "_restart_all", fake_all)
    asyncio.run(rd.process_restart_debounce())
    assert called == [], "a pending backoff must hold the consumer off"

    assert raw is not None  # keep the intermediate read honest


def test_retry_hits_only_the_nodes_that_failed(monkeypatch):
    """1 down + 2 healthy: the retry must reach only the down node (Gate 2 #2)."""
    from types import SimpleNamespace

    from backend.db import crud
    from backend.db.engine import SessionLocal

    names = ["hb_ok1", "hb_down", "hb_ok2"]
    monkeypatch.setattr(crud, "get_active_nodes", lambda db: [SimpleNamespace(name=n) for n in names])

    calls: dict[str, int] = dict.fromkeys(names, 0)
    down = {"hb_down"}

    class FakeClient:
        def __init__(self, node, panel_id=None):
            self.node = node

        async def restart_vpn(self):
            calls[self.node.name] += 1
            return {"success": self.node.name not in down}

    monkeypatch.setattr(rd, "node_client", FakeClient)

    db = SessionLocal()
    try:
        rd.mark_restart_pending(db, "tunnel-change")
    finally:
        db.close()

    asyncio.run(rd.process_restart_debounce())
    assert calls == {"hb_ok1": 1, "hb_down": 1, "hb_ok2": 1}

    db = SessionLocal()
    try:
        flag = rd.read_restart_flag(db)
        assert flag is not None
        assert set(flag["done"]) == {"hb_ok1", "hb_ok2"}, "the healthy nodes must be remembered"
        # backoff elapsed: force the retry due, keeping the done list
        rd._write_flag(db, 1, "tunnel-change", 1, 0, done=flag["done"])
    finally:
        db.close()

    asyncio.run(rd.process_restart_debounce())
    assert calls == {"hb_ok1": 1, "hb_down": 2, "hb_ok2": 1}, "only the down node is retried"

    # the down node recovers → the retry clears the flag
    down.clear()
    db = SessionLocal()
    try:
        flag = rd.read_restart_flag(db)
        rd._write_flag(db, 1, "tunnel-change", 2, 0, done=flag["done"])
    finally:
        db.close()

    asyncio.run(rd.process_restart_debounce())
    assert calls == {"hb_ok1": 1, "hb_down": 3, "hb_ok2": 1}
    db = SessionLocal()
    try:
        assert rd.read_restart_flag(db) is None, "full success must clear the flag"
    finally:
        db.close()


def test_max_backoff_survives_a_worker_restart():
    """A flag inside its capped backoff window must keep backing off (Gate 2 #5).

    Restart is simulated by rewinding updated_at far past any stale age while
    next_retry_at is still in the future.
    """
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        rd._write_flag(db, 1, "stuck", 5, time.time() + rd.MAX_BACKOFF_SECONDS, done=["ok1"])
        payload = json.loads(rd._read_raw(db))
        payload["updated_at"] = time.time() - 400  # written long ago
        from sqlalchemy import text

        db.execute(
            text("UPDATE settings_kv SET value = :v WHERE key = :k"),
            {"v": json.dumps(payload), "k": rd.RESTART_FLAG_KEY},
        )
        db.commit()

        assert rd.retry_stale_restart_flag(db) is False, "a pending backoff must survive a restart"
        flag = rd.read_restart_flag(db)
        assert flag["next_retry_at"] > time.time(), "the backoff must stay scheduled"
        assert flag["done"] == ["ok1"], "the done list must survive the restart"
    finally:
        db.close()


def test_due_flag_requeued_at_startup():
    """A flag whose retry is already owed gets its backoff cleared."""
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        rd._write_flag(db, 1, "due", 3, time.time() - 1, done=["ok1"])

        assert rd.retry_stale_restart_flag(db) is True, "a due flag must be re-queued at startup"
        flag = rd.read_restart_flag(db)
        assert flag["next_retry_at"] == 0, "startup must clear the backoff so the next run retries now"
        assert flag["done"] == ["ok1"], "re-queue must not forget the succeeded nodes"
    finally:
        db.close()
