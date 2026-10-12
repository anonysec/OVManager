"""TLS writers must refresh the process-local settings cache (Gate 1 #2)."""

import pytest
from sqlalchemy import text

import backend.routers.tls as tls_mod
from backend.config import config, settings_cache
from backend.db.crud.settings import get_cached_settings
from backend.db.engine import SessionLocal
from backend.routers.tls import TlsSettingsUpdate, generate_self_signed, put_tls_settings


@pytest.fixture(autouse=True)
def _clean_cache():
    settings_cache.clear()
    yield
    settings_cache.clear()


@pytest.fixture()
def _managed_tls_dir(monkeypatch, tmp_path):
    """Scratch certificate paths, the way test_tls_management declares them."""
    managed = tmp_path / "tls"
    monkeypatch.setattr(tls_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SSL_KEYFILE", str(managed / "privkey.pem"))
    monkeypatch.setattr(config, "SSL_CERTFILE", str(managed / "fullchain.pem"))
    return managed


def _restore(db, column: str, value) -> None:
    db.execute(text(f"UPDATE settings SET {column} = :v"), {"v": value})
    db.commit()
    settings_cache.clear()


def test_put_tls_settings_refreshes_cache():
    cache_db = SessionLocal()
    try:
        previous = get_cached_settings(cache_db).acme_domain
    finally:
        cache_db.close()  # cache now holds a row detached from a closed session

    db = SessionLocal()
    try:
        resp = put_tls_settings(TlsSettingsUpdate(acme_domain="gate.example.com"), db, {"username": "tester"})
        assert resp.success is True, resp.msg
        assert get_cached_settings(db).acme_domain == "gate.example.com", "cache must not serve a pre-write row"
    finally:
        _restore(db, "acme_domain", previous)
        db.close()


def test_generate_self_signed_refreshes_cache(_managed_tls_dir):
    db = SessionLocal()
    previous = db.execute(text("SELECT acme_domain FROM settings")).scalar()
    try:
        get_cached_settings(db)  # populate the cache with the pre-write row
        db.execute(text("UPDATE settings SET acme_domain = 'db-only.example.com'"))
        db.commit()

        resp = generate_self_signed(db, {"username": "tester"})
        assert resp.success is True, resp.msg
        assert get_cached_settings(db).acme_domain == "db-only.example.com", "cache must reload after the endpoint ran"
    finally:
        _restore(db, "acme_domain", previous)
        db.close()
