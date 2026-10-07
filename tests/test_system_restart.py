"""Owner-only panel restart route (POST /api/maintenance/restart).

The route must return immediately: the restart itself is spawned detached by
``backend.routers.tls._spawn_detached``. The spawn is recorded instead of run,
so no test process is ever restarted.
"""

import pytest
from fastapi.testclient import TestClient

import backend.routers.maintenance as m
from backend.app import _run_migrations, api
from backend.config import config
from backend.routers import tls


@pytest.fixture(autouse=True)
def _no_urlpath_prefix():
    from backend.urlpath import get_urlpath, set_urlpath

    previous = get_urlpath()
    set_urlpath("")
    try:
        yield
    finally:
        set_urlpath(previous or "")


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


def test_restart_owner_returns_immediately_and_spawns_detached(monkeypatch):
    records = []

    def fake_popen(argv, **kwargs):
        records.append((argv, kwargs))
        return object()

    with TestClient(api) as client:
        # Force a restart target (CI has neither systemd unit nor container)
        # and record the detach instead of running it.
        monkeypatch.setattr(m, "_systemd_unit_exists", lambda unit="ovmanager": True)
        monkeypatch.setattr(m, "_docker_container_running", lambda name="ovmanager": False)
        monkeypatch.setattr(tls.subprocess, "Popen", fake_popen)
        resp = client.post("/api/maintenance/restart", headers=_owner_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["msg"] == "Restarting panel…"
    assert body["data"]["restarted"] is True

    assert len(records) == 1
    argv, kwargs = records[0]
    assert argv[:4] == ["sh", "-c", 'sleep 1; exec "$@"', "ovmanager-restart"]
    assert argv[4:] == ["systemctl", "restart", "ovmanager"]
    assert kwargs["start_new_session"] is True
