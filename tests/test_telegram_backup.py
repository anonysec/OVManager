from types import SimpleNamespace

from backend.operations import telegram_backup as tb


def test_scheduled_backup_delivers_plain_telegram_copy(monkeypatch, tmp_path):
    import asyncio

    import backend.app as app_module
    import backend.routers.maintenance as maintenance
    from backend.db.engine import SessionLocal
    from backend.db.models import Settings

    bundle = tmp_path / "scheduled.ovmbak"
    bundle.write_bytes(b"bundle")
    delivered = []

    monkeypatch.setattr(maintenance, "create_panel_backup", lambda keep: bundle)
    monkeypatch.setattr(
        tb,
        "send_backup_document",
        lambda path, settings: (
            delivered.append((path, settings.owner_telegram_id)) or tb.TelegramBackupResult(True, message_id=99, file_id="f")
        ),
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
    finally:
        row = db.query(Settings).first()
        row.auto_backup_enabled, row.telegram_backup_enabled, row.owner_telegram_id, row.offsite_backup_target = previous
        db.commit()
        db.close()


class _Response:
    ok = True
    status_code = 200

    @staticmethod
    def json():
        return {"result": {"message_id": 42, "document": {"file_id": "telegram-file"}}}


def test_send_document_uploads_bundle_as_is(monkeypatch, tmp_path):
    backup = tmp_path / "panel.ovmbak"
    backup.write_bytes(b"verified bundle")
    settings = SimpleNamespace(owner_telegram_id=1234, bot_token="123:secret")
    seen = {}

    def fake_post(url, **kwargs):
        assert "123:secret" in url
        assert kwargs["data"]["chat_id"] == "1234"
        document = kwargs["files"]["document"][1]
        assert document.read() == b"verified bundle"
        seen["name"] = kwargs["files"]["document"][0]
        return _Response()

    monkeypatch.setattr(tb.requests, "post", fake_post)
    result = tb.send_backup_document(backup, settings)
    assert result.ok is True
    assert result.message_id == 42
    assert result.file_id == "telegram-file"
    assert result.sha256 and len(result.sha256) == 64
    assert result.size == len(b"verified bundle")
    assert seen["name"] == "panel.ovmbak"


def test_send_document_requires_configuration(monkeypatch, tmp_path):
    backup = tmp_path / "panel.ovmbak"
    backup.write_bytes(b"bundle")
    result = tb.send_backup_document(
        backup,
        SimpleNamespace(owner_telegram_id=None, bot_token=None),
    )
    assert result.ok is False
    assert "not configured" in result.error
