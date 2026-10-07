"""Manual cleanup routes (backend/routers/maintenance.py).

The daily ``ovmanager-cleanup.timer`` sweeps expired-and-disabled users on its
own; these tests cover the owner-only on-demand lever: dry-run preview,
confirmed run, reset-all-usage, and the usage-history purge.

Seeds use a ``cln_`` prefix and an expiry far older than any other test file
leaves behind, so a ``run`` here cannot sweep another test's users.
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app import _run_migrations, api
from backend.config import config

_ADMIN = "cleanup_admin_d6"


def _owner_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    _run_migrations()
    db = SessionLocal()
    try:
        raw = create_session(db, config.ADMIN_USERNAME, "owner")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


def _admin_headers() -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal
    from conftest import create_admin

    create_admin(_ADMIN)
    db = SessionLocal()
    try:
        raw = create_session(db, _ADMIN, "admin")
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}", "X-Requested-With": "XMLHttpRequest"}


def _seed(name: str, *, expiry: date, active: bool = True, used: int = 0, last_online=None) -> int:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        row = User(
            name=name,
            expiry_date=expiry,
            is_active=active,
            owner=config.ADMIN_USERNAME,
            total=1024,
            used=used,
            last_online=last_online,
            node_usage="{}",
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def _purge_seeds(*names: str) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        for name in names:
            row = db.query(User).filter(User.name == name).first()
            if row is None:
                continue
            db.execute(text("DELETE FROM user_traffic_daily WHERE user_id = :uid"), {"uid": row.id})
            db.delete(row)
        db.commit()
    finally:
        db.close()


def _exists(name: str) -> bool:
    from backend.db.engine import SessionLocal
    from backend.db.models import User

    db = SessionLocal()
    try:
        return db.query(User).filter(User.name == name).first() is not None
    finally:
        db.close()


def _audit_count(action: str) -> int:
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        try:
            return int(db.execute(text("SELECT COUNT(*) FROM audit_logs WHERE action = :a"), {"a": action}).scalar() or 0)
        except Exception:
            return 0  # audit table not created yet: no rows can predate it
    finally:
        db.close()


def test_preview_counts_without_deleting():
    seeds = ("cln_pv_old", "cln_pv_old_off", "cln_pv_keep")
    _seed("cln_pv_old", expiry=date(2000, 1, 1))
    _seed("cln_pv_old_off", expiry=date(2000, 1, 1), active=False)
    _seed("cln_pv_keep", expiry=date.today() + timedelta(days=30))
    try:
        with TestClient(api) as client:
            r = client.post(
                "/api/maintenance/cleanup/preview",
                json={"status": "expired", "older_than_days": 3650},
                headers=_owner_headers(),
            )
        assert r.status_code == 200 and r.json()["success"] is True, r.text
        data = r.json()["data"]
        assert data["matched"] >= 2
        assert {"cln_pv_old", "cln_pv_old_off"} <= set(data["sample"])
        assert "cln_pv_keep" not in data["sample"]
        assert 0 < len(data["sample"]) <= 20
        # dry run: every seeded user is still here
        assert all(_exists(n) for n in seeds)
    finally:
        _purge_seeds(*seeds)


def test_preview_disabled_filter_ignores_active_users():
    seeds = ("cln_dis_off", "cln_dis_on")
    _seed("cln_dis_off", expiry=date.today() + timedelta(days=30), active=False)
    _seed("cln_dis_on", expiry=date.today() + timedelta(days=30), active=True)
    try:
        with TestClient(api) as client:
            r = client.post(
                "/api/maintenance/cleanup/preview",
                json={"status": "disabled", "older_than_days": 0},
                headers=_owner_headers(),
            )
        assert r.status_code == 200 and r.json()["success"] is True, r.text
        data = r.json()["data"]
        assert "cln_dis_off" in data["sample"]
        assert "cln_dis_on" not in data["sample"]
        assert _exists("cln_dis_off") and _exists("cln_dis_on")
    finally:
        _purge_seeds(*seeds)


def test_run_deletes_only_matching_set():
    seeds = ("cln_run_old", "cln_run_old_off", "cln_run_recent", "cln_run_future")
    old_id = _seed("cln_run_old", expiry=date(2000, 1, 1))
    _seed("cln_run_old_off", expiry=date(2000, 1, 1), active=False)
    _seed("cln_run_recent", expiry=date.today() - timedelta(days=1))
    _seed("cln_run_future", expiry=date.today() + timedelta(days=30))
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        db.execute(
            text("INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (:u, :d, :b)"),
            {"u": old_id, "d": "2000-01-01", "b": 4096},
        )
        db.commit()
    finally:
        db.close()

    audit_before = _audit_count("maintenance.cleanup_run")
    try:
        with TestClient(api) as client:
            r = client.post(
                "/api/maintenance/cleanup/run",
                json={"status": "expired", "older_than_days": 3650, "confirm": True},
                headers=_owner_headers(),
            )
        assert r.status_code == 200 and r.json()["success"] is True, r.text
        body = r.json()["data"]
        assert body["deleted"] >= 2
        assert {"cln_run_old", "cln_run_old_off"} <= set(body["names"])

        assert not _exists("cln_run_old") and not _exists("cln_run_old_off")
        # the date filter keeps recently-expired and active users
        assert _exists("cln_run_recent") and _exists("cln_run_future")

        # usage history went with the deleted user
        db = SessionLocal()
        try:
            left = db.execute(
                text("SELECT COUNT(*) FROM user_traffic_daily WHERE user_id = :u"), {"u": old_id}
            ).scalar()
        finally:
            db.close()
        assert int(left or 0) == 0

        assert _audit_count("maintenance.cleanup_run") == audit_before + 1
    finally:
        _purge_seeds(*seeds)


def test_run_refuses_without_confirm():
    seed = "cln_confirm"
    _seed(seed, expiry=date(2000, 1, 1))
    try:
        with TestClient(api) as client:
            h = _owner_headers()
            for payload in (
                {"status": "expired", "older_than_days": 3650},
                {"status": "expired", "older_than_days": 3650, "confirm": False},
            ):
                r = client.post("/api/maintenance/cleanup/run", json=payload, headers=h)
                assert r.status_code == 200 and r.json()["success"] is False, r.text
                assert _exists(seed), "a refused run must delete nothing"
    finally:
        _purge_seeds(seed)


def test_reset_all_zeroes_usage():
    seed = "cln_reset"
    _seed(seed, expiry=date.today() + timedelta(days=30), used=123456)
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        db.execute(
            text("UPDATE users SET last_node_usage = 7, node_usage = :nu WHERE name = :n"),
            {"nu": '{"n1": {"total": 9}}', "n": seed},
        )
        db.commit()
    finally:
        db.close()

    audit_before = _audit_count("maintenance.usage_reset_all")
    try:
        with TestClient(api) as client:
            h = _owner_headers()
            r = client.post("/api/maintenance/usage/reset-all", json={}, headers=h)
            assert r.status_code == 200 and r.json()["success"] is False, r.text

            db = SessionLocal()
            try:
                used = db.execute(text("SELECT used FROM users WHERE name = :n"), {"n": seed}).scalar()
            finally:
                db.close()
            assert int(used) == 123456, "a refused reset must change nothing"

            r = client.post("/api/maintenance/usage/reset-all", json={"confirm": True}, headers=h)
            assert r.status_code == 200 and r.json()["success"] is True, r.text
            assert r.json()["data"]["reset"] >= 1

        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT used, last_node_usage, node_usage FROM users WHERE name = :n"), {"n": seed}
            ).fetchone()
        finally:
            db.close()
        assert int(row[0]) == 0 and int(row[1]) == 0 and row[2] == "{}"
        assert _audit_count("maintenance.usage_reset_all") == audit_before + 1
    finally:
        _purge_seeds(seed)


def test_purge_drops_only_old_daily_rows():
    seed = "cln_purge"
    uid = _seed(seed, expiry=date.today() + timedelta(days=30))
    old_day = (date.today() - timedelta(days=400)).isoformat()
    new_day = date.today().isoformat()
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        for day in (old_day, new_day):
            db.execute(
                text("INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (:u, :d, 1000)"),
                {"u": uid, "d": day},
            )
        db.commit()
    finally:
        db.close()

    def _rows() -> list[str]:
        from backend.db.engine import SessionLocal as SL

        s = SL()
        try:
            return [r[0] for r in s.execute(
                text("SELECT day FROM user_traffic_daily WHERE user_id = :u"), {"u": uid}
            ).fetchall()]
        finally:
            s.close()

    try:
        with TestClient(api) as client:
            h = _owner_headers()
            r = client.post("/api/maintenance/usage/purge", json={"older_than_days": 30}, headers=h)
            assert r.status_code == 200 and r.json()["success"] is False, r.text
            assert sorted(_rows()) == sorted([old_day, new_day]), "a refused purge must change nothing"

            r = client.post(
                "/api/maintenance/usage/purge",
                json={"older_than_days": 30, "confirm": True},
                headers=h,
            )
            assert r.status_code == 200 and r.json()["success"] is True, r.text
            assert r.json()["data"]["removed"] >= 1
            assert _rows() == [new_day], "only rows older than the cutoff may go"
    finally:
        _purge_seeds(seed)


def test_non_owner_forbidden():
    from conftest import cleanup_admin

    try:
        h = _admin_headers()
        with TestClient(api) as client:
            cases = (
                ("/api/maintenance/cleanup/preview", {"status": "expired"}),
                ("/api/maintenance/cleanup/run", {"status": "expired", "confirm": True}),
                ("/api/maintenance/usage/reset-all", {"confirm": True}),
                ("/api/maintenance/usage/purge", {"older_than_days": 30, "confirm": True}),
            )
            for path, payload in cases:
                r = client.post(path, json=payload, headers=h)
                assert r.status_code == 403, f"{path} allowed for admin: {r.status_code}"
    finally:
        cleanup_admin(_ADMIN)
