"""A deleted user must not cost every other user their traffic for the tick.

The multi-node fix refreshes a stale session object before reading its counters.
An unguarded db.refresh() on a row another session deleted mid-tick raises
InvalidRequestError, which escaped the per-user loop and discarded the whole
node's batch — so a bystander who node 1 never touched was billed 0 instead of
their real delta. Measured deterministically: 3200 bytes before the refresh,
0 after.
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
def two_users():
    db = SessionLocal()
    names = ("bystander", "doomed")
    for n in names:
        db.add(
            User(
                name=n,
                used=0,
                total=0,
                expiry_date=date(2030, 1, 1),
                owner="n",
                node_usage='{"n1": {"total": 0}, "n2": {"total": 0}}',
            )
        )
    db.commit()
    ids = {u.name: u.id for u in db.query(User).filter(User.name.in_(names)).all()}
    yield db, ids
    db.query(User).filter(User.name.in_(names)).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_deleted_user_does_not_zero_out_the_whole_node(two_users, monkeypatch):
    db, ids = two_users
    bystander, doomed = ids["bystander"], ids["doomed"]

    async def fake_fetch(node, db=None):
        # node 1 bills BOTH users, so both land in `stale`. `doomed` is then
        # deleted by another session before node 2 — which is the only way to
        # reach the refresh for a row that no longer exists. Without that, the
        # doomed user is never refreshed and the unguarded code passes.
        if node.name == "n1":
            return {"users": {"bystander": 3200, "doomed": 900}, "totals": {"bystander": 3200, "doomed": 900}, "sessions": {}}
        return {"users": {"bystander": 6400, "doomed": 1800}, "totals": {"bystander": 6400, "doomed": 1800}, "sessions": {}}

    monkeypatch.setattr(daily, "get_users_used_traffic", fake_fetch)

    # node 1: the bystander gets billed normally.
    all_users = {u.name: u for u in db.query(User).all()}
    stale: set = set()
    await daily._collect_node_traffic(_FakeNode("n1"), all_users, db, {}, stale)
    db.commit()

    # another session deletes `doomed` before node 2 runs
    other = SessionLocal()
    other.query(User).filter(User.id == doomed).delete()
    other.commit()
    other.close()

    # node 2 must still bill the bystander.
    await daily._collect_node_traffic(_FakeNode("n2"), all_users, db, {}, stale)
    db.commit()

    # Raw read: db.get() would hand back the session's own stale object
    # (expire_on_commit is False), which is the very thing the fix works around.
    billed = db.execute(text("SELECT used FROM users WHERE id = :i"), {"i": bystander}).scalar()
    # Node 1 billed 3200 for n1. Node 2 reports a lifetime total of 6400 for a
    # DIFFERENT node (n2), which node 1 never billed, so its whole 6400 is new
    # growth. The correct bill is therefore 3200 + 6400.
    assert billed == 9600, (
        f"the bystander was billed {billed} instead of 9600 — one deleted user discarded the whole node's batch"
    )
