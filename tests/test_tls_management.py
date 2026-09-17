# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Tests for panel-managed TLS certificates (backend/routers/tls.py).

The router is not yet registered in backend/routers/__init__.py (owned by the
coordinator), so this module attaches it to the app itself unless it is
already present.
"""

import json
import os
import stat
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

import backend.routers.tls as tls_mod
from backend.app import _run_migrations, api
from backend.config import config
from backend.routers.tls import router as tls_router


def _register_tls_router() -> None:
    """Expose the router on the shared app until it is registered in __init__.

    The SPA catch-all is already the last route, so appended routes would never
    match — prepend them instead.
    """
    if any(getattr(route, "path", "").startswith("/api/tls") for route in api.routes):
        return
    before = len(api.router.routes)
    api.include_router(tls_router, prefix="/api")
    new_routes = api.router.routes[before:]
    del api.router.routes[before:]
    api.router.routes[:0] = new_routes


_register_tls_router()


@pytest.fixture(autouse=True)
def _managed_tls_dir(monkeypatch, tmp_path):
    """Point the router at a scratch TLS dir and a TLS-less environment."""
    from backend.urlpath import get_urlpath, set_urlpath

    managed = tmp_path / "tls"
    monkeypatch.setattr(tls_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SSL_KEYFILE", None)
    monkeypatch.setattr(config, "SSL_CERTFILE", None)
    previous = get_urlpath()
    set_urlpath("")
    try:
        yield managed
    finally:
        set_urlpath(previous or "")


@pytest.fixture
def client():
    return TestClient(api)


def _token(username: str, role: str) -> dict:
    from backend.auth.sessions import create_session
    from backend.db.engine import SessionLocal

    _run_migrations()
    db = SessionLocal()
    try:
        raw = create_session(db, username, role)
    finally:
        db.close()
    return {"Authorization": f"Bearer {raw}"}


def _owner_headers() -> dict:
    return _token(config.ADMIN_USERNAME, "owner")


def _ensure_admin(username: str) -> None:
    from backend.db import crud
    from backend.db.engine import SessionLocal
    from backend.schema._input import AdminCreate

    _run_migrations()
    db = SessionLocal()
    try:
        if crud.get_admin_by_username(db, username) is None:
            crud.create_admin(db, AdminCreate(username=username, password=f"pw-{username}-12345"))
    finally:
        db.close()


def _make_pair(cn: str = "panel.test", days: int = 30) -> tuple[bytes, bytes]:
    """Return (key_pem, cert_pem) for a self-signed pair."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(UTC)
    not_before = now - timedelta(days=abs(days) + 1) if days < 0 else now - timedelta(minutes=1)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return key_pem, cert.public_bytes(serialization.Encoding.PEM)


def _upload(client: TestClient, key_pem: bytes, cert_pem: bytes, headers: dict | None = None):
    return client.post(
        "/api/tls/upload",
        files={
            "key": ("privkey.pem", key_pem, "application/x-pem-file"),
            "cert": ("fullchain.pem", cert_pem, "application/x-pem-file"),
        },
        headers=headers or _owner_headers(),
    )


# ── Status ─────────────────────────────────────────────────────────────────


def test_tls_status_without_config_is_disabled(client):
    resp = client.get("/api/tls/status", headers=_owner_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["mode"] in ("disabled", "misconfigured")
    assert data["source"] in (None, "environment")
    if data["mode"] == "disabled":
        assert data["cert_path"] is None
        assert data["expires_days"] is None
        assert data["subject"] is None
        assert data["issued_by"] is None
        assert data["restart_required"] is False


# ── Upload ─────────────────────────────────────────────────────────────────


def test_tls_upload_rejects_mismatched_pair(client, _managed_tls_dir):
    key_pem, _ = _make_pair("first.test")
    _, cert_pem = _make_pair("second.test")
    resp = _upload(client, key_pem, cert_pem)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "match" in body["msg"].lower()
    assert not (_managed_tls_dir / "privkey.pem").exists()
    assert not (_managed_tls_dir / "fullchain.pem").exists()


def test_tls_upload_rejects_expired_certificate(client, _managed_tls_dir):
    key_pem, cert_pem = _make_pair("expired.test", days=-1)
    resp = _upload(client, key_pem, cert_pem)
    body = resp.json()
    assert body["success"] is False
    assert "expired" in body["msg"].lower()
    assert not (_managed_tls_dir / "privkey.pem").exists()


def test_tls_upload_accepts_valid_pair_and_secures_files(client, _managed_tls_dir):
    key_pem, cert_pem = _make_pair("upload.test", days=30)
    resp = _upload(client, key_pem, cert_pem)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True, body["msg"]
    assert body["data"]["restart_required"] is True
    assert "restart" in body["msg"].lower()
    assert "systemctl restart ovmanager" in body["msg"]
    assert "docker restart ovmanager" in body["msg"]

    assert (_managed_tls_dir / "privkey.pem").read_bytes() == key_pem
    assert (_managed_tls_dir / "fullchain.pem").read_bytes() == cert_pem
    assert stat.S_IMODE(os.stat(_managed_tls_dir / "privkey.pem").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(_managed_tls_dir / "fullchain.pem").st_mode) == 0o644
    assert json.loads((_managed_tls_dir / "meta.json").read_text())["mode"] == "custom"

    status = client.get("/api/tls/status", headers=_owner_headers()).json()["data"]
    assert status["mode"] == "managed"
    assert status["source"] == "panel-managed"
    assert status["cert_path"] == str(_managed_tls_dir / "fullchain.pem")
    assert status["issued_by"] == "self-signed"
    assert status["subject"] and "upload.test" in status["subject"]
    assert status["expires_days"] is not None and status["expires_days"] >= 29
    assert status["restart_required"] is True


# ── Self-signed ────────────────────────────────────────────────────────────


def test_tls_self_signed_generates_readable_certificate(client, _managed_tls_dir):
    resp = client.post("/api/tls/self-signed", headers=_owner_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True, body["msg"]
    assert body["data"]["restart_required"] is True

    cert = x509.load_pem_x509_certificate((_managed_tls_dir / "fullchain.pem").read_bytes())
    assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    remaining = (cert.not_valid_after_utc - datetime.now(UTC)).days
    assert remaining > 3600  # ~10 years
    private_key = serialization.load_pem_private_key((_managed_tls_dir / "privkey.pem").read_bytes(), password=None)
    assert private_key.key_size == 2048
    assert stat.S_IMODE(os.stat(_managed_tls_dir / "privkey.pem").st_mode) == 0o600
    assert json.loads((_managed_tls_dir / "meta.json").read_text())["mode"] == "self-signed"

    status = client.get("/api/tls/status", headers=_owner_headers()).json()["data"]
    assert status["mode"] == "managed"
    assert status["issued_by"] == "self-signed"


# ── Renew (no acme.sh) ─────────────────────────────────────────────────────


def test_tls_renew_without_acme_returns_guidance(client, monkeypatch, tmp_path, _managed_tls_dir):
    monkeypatch.setattr(tls_mod, "ACME_SH", tmp_path / "missing-acme" / "acme.sh")

    def _no_port_probe():
        raise AssertionError("port 80 must not be probed when acme.sh is absent")

    monkeypatch.setattr(tls_mod, "_port_80_busy", _no_port_probe)

    resp = client.post(
        "/api/tls/renew",
        json={"domain": "panel.example.com", "email": "ops@example.com"},
        headers=_owner_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "acme.sh" in body["msg"]
    assert "get.acme.sh" in body["msg"]
    assert not (_managed_tls_dir / "privkey.pem").exists()

    # The IP option hits the same guidance instead of failing hard.
    resp = client.post("/api/tls/renew", json={"use_ip": True}, headers=_owner_headers())
    assert resp.json()["success"] is False
    assert "acme.sh" in resp.json()["msg"]


def test_tls_renew_rejects_invalid_domain(client, monkeypatch, tmp_path, _managed_tls_dir):
    monkeypatch.setattr(tls_mod, "ACME_SH", tmp_path / "missing-acme" / "acme.sh")
    resp = client.post("/api/tls/renew", json={"domain": "--standalone"}, headers=_owner_headers())
    assert resp.json()["success"] is False
    assert "not valid" in resp.json()["msg"]
    resp = client.post("/api/tls/renew", json={}, headers=_owner_headers())
    assert resp.json()["success"] is False


# ── Owner-only access ──────────────────────────────────────────────────────


def test_tls_endpoints_require_owner(client, tmp_path):
    _ensure_admin("tls_admin_gate")
    admin = _token("tls_admin_gate", "admin")
    key_pem, cert_pem = _make_pair("gate.test")
    calls = [
        ("get", "/api/tls/status", {}),
        ("post", "/api/tls/upload", {"files": {"key": ("k.pem", key_pem), "cert": ("c.pem", cert_pem)}}),
        ("post", "/api/tls/self-signed", {}),
        ("post", "/api/tls/renew", {"json": {"domain": "panel.example.com"}}),
        ("post", "/api/tls/restart", {}),
    ]
    for method, path, kwargs in calls:
        # The CSRF middleware rejects bearer-less POSTs before auth runs, so
        # send the header real browser clients would send to reach 401.
        anon_headers = {"X-Requested-With": "XMLHttpRequest"}
        anon = getattr(client, method)(path, headers=anon_headers, **kwargs)
        assert anon.status_code == 401, f"{path} anonymous got {anon.status_code}"
        as_admin = getattr(client, method)(path, headers=admin, **kwargs)
        assert as_admin.status_code == 403, f"{path} admin got {as_admin.status_code}"
    assert not (tmp_path / "tls").exists()
