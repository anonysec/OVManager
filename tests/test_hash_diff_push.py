"""Hash-diff user push: durable skip + batched fanout chunks (Task 9)."""

import asyncio
import json

import pytest

import backend.node.sync as sync_mod


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


@pytest.fixture(autouse=True)
def _clean_cache():
    sync_mod._last_pushed_limits.clear()
    yield
    sync_mod._last_pushed_limits.clear()


def _seed(node_usage: str = "{}"):
    import datetime as dt
    import uuid as _uuid

    from backend.app import _run_migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    _run_migrations()
    db = SessionLocal()
    try:
        node = Node(
            name=f"hd_node_{_uuid.uuid4().hex[:8]}",
            address="127.0.0.1",
            protocol="udp",
            ovpn_port=1194,
            port=2083,
            key="x" * 32,
            status=True,
        )
        db.add(node)
        db.flush()
        user = User(
            uuid=str(_uuid.uuid4()),
            name=f"hd_user_{_uuid.uuid4().hex[:8]}",
            expiry_date=dt.date(2030, 1, 1),
            max_logins=1,
            is_active=True,
            node_usage=node_usage,
        )
        db.add(user)
        db.commit()
        return node.id, user.id, user.name
    finally:
        db.close()


def _cleanup(node_id, name):
    from sqlalchemy import text

    from backend.db.engine import SessionLocal
    from backend.db.models import Node, User

    db = SessionLocal()
    try:
        uid = db.execute(text("SELECT id FROM users WHERE name = :n"), {"n": name}).scalar()
        if uid is not None:
            db.execute(text("DELETE FROM traffic_ledger WHERE user_id = :uid"), {"uid": uid})
        db.query(User).filter(User.name == name).delete()
        db.query(Node).filter(Node.id == node_id).delete()
        db.commit()
    finally:
        db.close()


def _run_sync():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        return asyncio.run(sync_mod.sync_all_user_limits(db))
    finally:
        db.close()


def _only_seeded_node(monkeypatch, node_id: int) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import Node

    def _get_active(db_):
        session = SessionLocal()
        try:
            return [session.query(Node).filter(Node.id == node_id).first()]
        finally:
            session.close()

    monkeypatch.setattr(sync_mod.crud, "get_active_nodes", _get_active)


def test_unchanged_user_makes_zero_node_calls_after_restart(monkeypatch):
    """The push_hash in node_usage survives a restart — no full re-push."""
    calls: list = []
    collector_state = json.dumps({"tnode": {"total": 42}})

    class FakeRequests:
        def __init__(self, address, port, api_key, use_tls=True):
            pass

        def _request(self, method, path, **kw):
            for item in kw["json"]["users"]:
                calls.append((item["id"], item["max_logins"]))
            return {"success": True, "data": {"applied": len(kw["json"]["users"]), "failed": []}}

    monkeypatch.setattr(sync_mod, "node_client", lambda node, **kw: FakeRequests("x", 1, "k"))
    node_id, user_id, name = _seed(node_usage=collector_state)
    _only_seeded_node(monkeypatch, node_id)
    try:
        _run_sync()
        ours = [c for c in calls if c[0] == str(user_id)]
        assert ours == [(str(user_id), 1)], "first sweep must push"

        from backend.db.engine import SessionLocal
        from backend.db.models import User

        db = SessionLocal()
        try:
            stored = json.loads(db.query(User).filter(User.id == user_id).first().node_usage)
        finally:
            db.close()
        assert stored["tnode"] == {"total": 42}, "the collector's cursor must survive the merge"
        assert stored["push_hash"].get(str(node_id)), "the push hash must be stored per node"

        sync_mod._last_pushed_limits.clear()  # simulated panel restart
        calls.clear()
        quiet = _run_sync()
        assert [c for c in calls if c[0] == str(user_id)] == [], "an unchanged user must cost zero node calls after a restart"
        assert quiet["skipped"] >= 1
    finally:
        _cleanup(node_id, name)


def test_reset_preserves_push_hash_so_next_sync_pushes_nothing(monkeypatch):
    """reset-usage wipes counters but must not force a full user re-push."""
    calls: list = []

    class FakeRequests:
        def __init__(self, address, port, api_key, use_tls=True):
            pass

        def _request(self, method, path, **kw):
            for item in kw["json"]["users"]:
                calls.append((item["id"], item["max_logins"]))
            return {"success": True, "data": {"applied": len(kw["json"]["users"]), "failed": []}}

    monkeypatch.setattr(sync_mod, "node_client", lambda node, **kw: FakeRequests("x", 1, "k"))
    node_id, user_id, name = _seed(node_usage=json.dumps({"tnode": {"total": 42}}))
    _only_seeded_node(monkeypatch, node_id)
    try:
        _run_sync()
        assert [c for c in calls if c[0] == str(user_id)] == [(str(user_id), 1)], "first sweep must push"

        from backend.db import crud
        from backend.db.engine import SessionLocal
        from backend.db.models import User

        db = SessionLocal()
        try:
            row = db.query(User).filter(User.id == user_id).first()
            assert crud.reset_user_usage(db, row.uuid) is True
        finally:
            db.close()

        sync_mod._last_pushed_limits.clear()  # simulated panel restart
        calls.clear()
        _run_sync()
        assert [c for c in calls if c[0] == str(user_id)] == [], "a reset must not cost a re-push"
    finally:
        _cleanup(node_id, name)


def test_pki_repin_path_is_unaffected_by_hash_skip(monkeypatch):
    """The hash skip gates limits sweeps only — PKI pushes always go out.

    After a sweep stored the push hash (user pushes now silent), the repin
    endpoint must still reach the node and store the certificate pin.
    """
    import backend.routers.node as node_router

    class FakeRequests:
        def __init__(self, address, port, api_key, use_tls=True):
            pass

        def _request(self, method, path, **kw):
            return {"success": True, "data": {"applied": len(kw["json"]["users"]), "failed": []}}

    monkeypatch.setattr(sync_mod, "node_client", lambda node, **kw: FakeRequests("x", 1, "k"))
    node_id, user_id, name = _seed(node_usage=json.dumps({"tnode": {"total": 1}}))
    _only_seeded_node(monkeypatch, node_id)
    try:
        _run_sync()  # stores the push hash; the user sweep is now silent

        fetched = []

        async def fake_cert(address, port):
            fetched.append((address, port))
            return "-----BEGIN CERTIFICATE-----"

        monkeypatch.setattr(node_router, "_fetch_node_cert", fake_cert)

        from backend.db.engine import SessionLocal

        db = SessionLocal()
        try:
            out = asyncio.run(node_router.repin_node_cert(node_id, db=db, user={"username": "tester"}))
        finally:
            db.close()

        assert fetched == [("127.0.0.1", 2083)], "the PKI path must still reach the node"
        assert out.data == {"repinned": True}

        db = SessionLocal()
        try:
            from backend.db.models import Node, User

            node = db.query(Node).filter(Node.id == node_id).first()
            assert node.server_ca == "-----BEGIN CERTIFICATE-----", "the pin must be stored"
            row = db.query(User).filter(User.id == user_id).first()
            assert json.loads(row.node_usage)["push_hash"], "the hash must still be intact"
        finally:
            db.close()
    finally:
        _cleanup(node_id, name)


def test_bulk_push_chunks_at_batch_size_under_1mb(monkeypatch):
    """5000 users with sync.batch_size=100 → 50 chunks, each payload <1MB."""
    from backend.app import _run_migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import Node

    _run_migrations()

    db = SessionLocal()
    try:
        sync_mod.crud.set_kv(db, "sync.batch_size", "100")
        db.commit()
        seed_node = Node(
            name="hd_chunk_node",
            address="127.0.0.1",
            protocol="udp",
            ovpn_port=1194,
            port=2083,
            key="x" * 32,
            status=True,
        )
        db.add(seed_node)
        db.commit()
        node_id = seed_node.id
    finally:
        db.close()

    class _U:
        def __init__(self, i):
            # ids far above the autoincrement range so the hash-merge guard
            # finds no real row to touch
            self.id = 900_000_000 + i
            self.name = f"chunku{i}"
            self.max_logins = 1
            self.node_usage = "{}"

    def _get_users(db_):
        return [_U(i) for i in range(5000)]

    def _get_active(db_):
        session = SessionLocal()
        try:
            return [session.query(Node).filter(Node.id == node_id).first()]
        finally:
            session.close()

    monkeypatch.setattr(sync_mod.crud, "get_all_users", _get_users)
    monkeypatch.setattr(sync_mod.crud, "get_active_nodes", _get_active)

    chunks: list[list] = []

    def fake_push(node, pairs, panel_id=None):
        chunks.append(list(pairs))
        return {"node": node.name, "applied": len(pairs), "failed": 0, "success": True, "failed_items": []}

    monkeypatch.setattr(sync_mod, "_push_limits_batch", fake_push)
    sync_mod._last_pushed_limits.clear()

    try:
        result = _run_sync()
        assert result["applied"] == 5000
        assert len(chunks) == 50, f"5000 users at batch_size=100 must be 50 chunks, got {len(chunks)}"
        for chunk in chunks:
            assert len(chunk) <= 100
            payload = {"users": [{"id": str(u.id), "max_logins": int(u.max_logins or 0)} for _, u, _want in chunk]}
            assert len(json.dumps(payload).encode()) < 1_048_576, "every chunk must stay under 1MB"
    finally:
        from sqlalchemy import text

        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM nodes WHERE id = :nid"), {"nid": node_id})
            db.execute(text("DELETE FROM settings_kv WHERE key = 'sync.batch_size'"))
            db.commit()
        finally:
            db.close()
