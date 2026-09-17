# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Scale guard for the expiry sweep.

300 expired users on 8 nodes is small for production but large enough to
expose the two regressions this suite protects against: an N+1 active-node
query per disabled user, and an unbounded per-node threadpool fan-out. The
node client is faked (no network) while the real fan-out code runs, so the
in-flight counter observes the actual semaphore behavior.
"""

import asyncio
import datetime as dt
import threading
import time
import uuid as _uuid

from sqlalchemy import text

from backend.app import _run_migrations
from backend.node import ops as node_ops
from backend.operations import daily_checks as dc

PREFIX = "sc_"
USER_COUNT = 300
NODE_COUNT = 8
TIME_CEILING_SECONDS = 30.0


def _seed(seed_id: str) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    _run_migrations()
    db = SessionLocal()
    try:
        for i in range(NODE_COUNT):
            db.add(
                Node(
                    name=f"{PREFIX}node_{seed_id}_{i}",
                    address="127.0.0.1",
                    protocol="udp",
                    ovpn_port=1194,
                    port=2083,
                    key="k" * 32,
                    status=True,
                    use_tls=False,
                )
            )
        expired = dt.date.today() - dt.timedelta(days=1)
        # Bulk insert: 300 individual flushes would dominate the runtime.
        db.add_all(
            [
                User(
                    uuid=str(_uuid.uuid4()),
                    name=f"{PREFIX}user_{seed_id}_{i:03d}",
                    owner="owner",
                    expiry_date=expired,
                    total=10**12,
                    used=0,
                    max_logins=1,
                    is_active=True,
                )
                for i in range(USER_COUNT)
            ]
        )
        db.commit()
    finally:
        db.close()


def _cleanup(seed_id: str) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    pattern = f"{PREFIX}user_{seed_id}_%"
    db = SessionLocal()
    try:
        db.execute(
            text("DELETE FROM user_traffic_daily WHERE user_id IN (SELECT id FROM users WHERE name LIKE :p)"),
            {"p": pattern},
        )
        db.query(User).filter(User.name.like(pattern)).delete(synchronize_session=False)
        db.query(Node).filter(Node.name.like(f"{PREFIX}node_{seed_id}_%")).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_enforce_scale_is_bounded_and_queries_nodes_once(monkeypatch):
    import backend.db.crud as crud_mod

    seed_id = _uuid.uuid4().hex[:8]
    _seed(seed_id)

    # The fake node call runs in the AnyIO threadpool, so all bookkeeping
    # must assume concurrent access.
    lock = threading.Lock()
    state = {"in_flight": 0, "max_in_flight": 0, "calls": 0}
    pushed: set[str] = set()

    class FakeRequests:
        def __init__(self, *args, **kwargs):
            pass

        def change_user_status(self, name, status, max_logins=None, uid=None):
            with lock:
                state["in_flight"] += 1
                state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
                state["calls"] += 1
                pushed.add(name)
            time.sleep(0.002)
            with lock:
                state["in_flight"] -= 1
            return True

    real_get_active = crud_mod.get_active_nodes
    queries = {"n": 0}

    def counting_get_active(db):
        queries["n"] += 1
        prefix = f"{PREFIX}node_{seed_id}_"
        return [n for n in real_get_active(db) if n.name.startswith(prefix)]

    monkeypatch.setattr(crud_mod, "get_active_nodes", counting_get_active)
    monkeypatch.setattr(node_ops, "node_client", lambda node, **kw: FakeRequests())

    started = time.perf_counter()
    try:
        asyncio.run(dc.enforce_user_limits())
        elapsed = time.perf_counter() - started

        from backend.db.engine import SessionLocal
        from backend.db.models import User

        db = SessionLocal()
        try:
            rows = db.query(User).filter(User.name.like(f"{PREFIX}user_{seed_id}_%")).all()
            assert len(rows) == USER_COUNT
            assert all(row.is_active is False for row in rows), "every expired user must be disabled"
        finally:
            db.close()

        expected_names = {f"{PREFIX}user_{seed_id}_{i:03d}" for i in range(USER_COUNT)}
        assert expected_names <= pushed, "every user must be pushed to the nodes"
        assert queries["n"] == 1, f"active-node list queried {queries['n']} times, expected once"
        assert state["max_in_flight"] <= node_ops.NODE_FANOUT_LIMIT, (
            f"fan-out hit {state['max_in_flight']} concurrent node calls, cap is {node_ops.NODE_FANOUT_LIMIT}"
        )
        assert state["max_in_flight"] > 1, "test must actually exercise concurrent fan-out"
        assert state["calls"] >= USER_COUNT * NODE_COUNT
        assert elapsed < TIME_CEILING_SECONDS, f"enforce took {elapsed:.1f}s (ceiling {TIME_CEILING_SECONDS}s)"
    finally:
        _cleanup(seed_id)
