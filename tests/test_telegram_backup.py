# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

from pathlib import Path
from types import SimpleNamespace

from cryptography.fernet import Fernet

from backend.operations import telegram_backup as tb


def test_scheduled_backup_delivers_encrypted_telegram_copy(monkeypatch, tmp_path):
    import asyncio

    import backend.app as app_module
    import backend.routers.maintenance as maintenance
    from backend.config import config
    from backend.db.engine import SessionLocal
    from backend.db.models import Settings

    bundle = tmp_path / "scheduled.ovmbak"
    bundle.write_bytes(b"bundle")
    delivered = []

    monkeypatch.setattr(maintenance, "create_panel_backup", lambda keep: bundle)
    monkeypatch.setattr(config, "BACKUP_ENCRYPT_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(
        tb,
        "send_backup_document",
        lambda path, settings, key: delivered.append((path, settings.owner_telegram_id, key))
        or tb.TelegramBackupResult(True, message_id=99, file_id="f"),
    )

    db = SessionLocal()
    row = db.query(Settings).first()
    previous = (row.auto_backup_enabled, row.telegram_backup_enabled, row.owner_telegram_id, row.offsite_backup_target)
    try:
        row.auto_backup_enabled = True
        row.telegram_backup_enabled = True
        row.owner_telegram_id = 4321
        row.offsite_backup_target = None
        db.commit()
        asyncio.run(app_module.auto_backup_job())
        assert delivered and delivered[0][0] == bundle
        assert delivered[0][1] == 4321
        assert delivered[0][2] == config.BACKUP_ENCRYPT_KEY
    finally:
        row = db.query(Settings).first()
        row.auto_backup_enabled, row.telegram_backup_enabled, row.owner_telegram_id, row.offsite_backup_target = previous
        db.commit()
        db.close()



def test_stream_encryption_roundtrip_and_tamper_detection(tmp_path):
    source = tmp_path / "panel.ovmbak"
    source.write_bytes((b"backup-data-" * 200_000) + b"end")
    encrypted = tmp_path / "panel.ovmbak.enc"
    restored = tmp_path / "restored.ovmbak"
    key = Fernet.generate_key().decode()

    size, checksum = tb.encrypt_backup(source, encrypted, key)
    assert size == encrypted.stat().st_size
    assert len(checksum) == 64
    assert encrypted.read_bytes()[:8] == tb.MAGIC
    assert source.read_bytes() not in encrypted.read_bytes()

    tb.decrypt_backup(encrypted, restored, key)
    assert restored.read_bytes() == source.read_bytes()

    payload = bytearray(encrypted.read_bytes())
    payload[len(payload) // 2] ^= 1
    encrypted.write_bytes(payload)
    try:
        tb.decrypt_backup(encrypted, restored, key)
    except Exception:
        pass
    else:
        raise AssertionError("tampered ciphertext must not authenticate")


class _Response:
    ok = True
    status_code = 200

    @staticmethod
    def json():
        return {"result": {"message_id": 42, "document": {"file_id": "telegram-file"}}}


def test_send_document_encrypts_and_removes_staging(monkeypatch, tmp_path):
    backup = tmp_path / "panel.ovmbak"
    backup.write_bytes(b"verified bundle")
    key = Fernet.generate_key().decode()
    settings = SimpleNamespace(owner_telegram_id=1234, bot_token="stored")
    seen = {}

    monkeypatch.setattr(tb.crud, "decrypt_bot_token", lambda value: "123:secret")

    def fake_post(url, **kwargs):
        assert "123:secret" in url
        assert kwargs["data"]["chat_id"] == "1234"
        document = kwargs["files"]["document"][1]
        encrypted = document.read()
        assert encrypted.startswith(tb.MAGIC)
        assert b"verified bundle" not in encrypted
        seen["name"] = kwargs["files"]["document"][0]
        return _Response()

    monkeypatch.setattr(tb.requests, "post", fake_post)
    result = tb.send_backup_document(backup, settings, key)
    assert result.ok is True
    assert result.message_id == 42
    assert result.file_id == "telegram-file"
    assert result.sha256 and len(result.sha256) == 64
    assert seen["name"].endswith(".ovmbak.enc")
    assert not Path(str(backup) + ".enc").exists()


def test_send_document_requires_configuration(monkeypatch, tmp_path):
    backup = tmp_path / "panel.ovmbak"
    backup.write_bytes(b"bundle")
    monkeypatch.setattr(tb.crud, "decrypt_bot_token", lambda value: None)
    result = tb.send_backup_document(
        backup,
        SimpleNamespace(owner_telegram_id=None, bot_token=None),
        Fernet.generate_key().decode(),
    )
    assert result.ok is False
    assert "not configured" in result.error
