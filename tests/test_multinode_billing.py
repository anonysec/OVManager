"""A user's traffic must accumulate across EVERY node, not just the first.

check_user_used_traffic() loads all_users ONCE and reuses that dict for each
node. The write is a conditional UPDATE the session never sees, so without a
refresh the second node's WHERE clause expects the pre-first-node value and is
rejected — a two-node panel silently billed 1000 bytes for 6000 real ones.
"""
from datetime import date

import pytest
from sqlalchemy import text

from backend.db.engine import SessionLocal
from backend.db.models import User
from backend.operations.billing import daily


class _FakeNode:
    def __init__(self, name):
        self.name = name


@pytest.fixture
def user_row():
    db = SessionLocal()
    db.add(User(name="multinode-test", used=0, total=0,
                expiry_date=date(2030, 1, 1), owner="n",
                node_usage='{"n1": {"total": 100}, "n2": {"total": 200}}'))
    db.commit()
    uid = db.query(User).filter(User.name == "multinode-test").one().id
    yield db
    # The daily history rows too: this test bills real deltas, and a leftover
    # row for a reused id fails an unrelated test's "no traffic may be billed".
    db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :u"), {"u": uid})
    db.execute(text("DELETE FROM users WHERE name = :n"), {"n": "multinode-test"})
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_traffic_accumulates_across_two_nodes(user_row, monkeypatch):
    db = user_row
    all_users = {u.name: u for u in db.query(User).all()}
    user = all_users["multinode-test"]
    uid = user.id

    async def fake_get_users_used_traffic(node, db=None):
        total = {"n1": 1100, "n2": 5200}[node.name]
        return {"users": {"multinode-test": total}, "totals": {"multinode-test": total},
                "sessions": {}}

    monkeypatch.setattr(daily, "get_users_used_traffic", fake_get_users_used_traffic)

    # exactly check_user_used_traffic's loop: one loaded dict, every node
    stale: set = set()
    for name in ("n1", "n2"):
        await daily._collect_node_traffic(_FakeNode(name), all_users, db, {}, stale)
        db.commit()

    billed = db.execute(text("SELECT used FROM users WHERE id = :i"), {"i": uid}).fetchone()[0]
    assert billed == 6000, f"expected 1000 + 5000 across two nodes, billed {billed}"
