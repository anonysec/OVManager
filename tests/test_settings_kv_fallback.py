"""get_setting: KV hit wins, legacy column second, default last (Task 10)."""

import pytest

from backend.config import get_setting
from backend.db import crud


@pytest.fixture(autouse=True)
def _restore_settings():
    """Snapshot the notify_node_down column and drop stray KV rows."""
    from backend.db.engine import SessionLocal
    from backend.db.models import Settings

    db = SessionLocal()
    try:
        row = crud.get_settings(db)
        previous = row.notify_node_down
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.execute(_delete_kv("notify_node_down"))
        db.query(Settings).update({"notify_node_down": previous})
        db.commit()
        crud.refresh_settings(db)
    finally:
        db.close()


def _delete_kv(key: str):
    from sqlalchemy import text

    return text("DELETE FROM settings_kv WHERE key = :k").bindparams(k=key)


def test_kv_value_overrides_the_legacy_column():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        row = crud.get_settings(db)
        row.notify_node_down = True
        db.commit()
        crud.refresh_settings(db)
        crud.set_kv(db, "notify_node_down", "false")
        db.commit()
    finally:
        db.close()

    assert get_setting("notify_node_down") is False, "a KV hit must win over the column"


def test_missing_key_falls_back_to_the_column():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        row = crud.get_settings(db)
        row.notify_node_down = False
        db.commit()
        crud.refresh_settings(db)
        db.execute(_delete_kv("notify_node_down"))
        db.commit()
    finally:
        db.close()

    assert get_setting("notify_node_down") is False, "no KV row means the legacy column decides"


def test_unknown_key_returns_the_default():
    assert get_setting("totally.unknown.key", "dflt") == "dflt"


def test_non_json_kv_value_comes_back_verbatim():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        crud.set_kv(db, "sync.mode", "plain-string")
        db.commit()
    finally:
        db.close()
    try:
        assert get_setting("sync.mode") == "plain-string"
    finally:
        db = SessionLocal()
        try:
            db.execute(_delete_kv("sync.mode"))
            db.commit()
        finally:
            db.close()
