# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import io
import json
import sqlite3
import stat
import tarfile
from datetime import UTC, datetime

import pytest

from backend.operations.backup_bundle import BackupBundleError, create_bundle, extract_database, verify_bundle


def _database(path, value="before"):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE probe (value TEXT)")
    conn.execute("INSERT INTO probe VALUES (?)", (value,))
    conn.commit()
    conn.close()


def test_bundle_create_verify_and_extract(tmp_path):
    source = tmp_path / "source.db"
    _database(source)
    backup_dir = tmp_path / "backups"

    bundle = create_bundle(source, backup_dir, created_at=datetime(2026, 9, 21, 12, 0, tzinfo=UTC))
    assert bundle.name == "ovmanager-backup-20260921_120000-v1.ovmbak"
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o600

    manifest = verify_bundle(bundle)
    assert manifest["format"] == "ovmanager-backup"
    assert manifest["format_version"] == 1
    assert manifest["database"] == "panel.db"

    restored = tmp_path / "restored.db"
    extract_database(bundle, restored)
    conn = sqlite3.connect(restored)
    try:
        assert conn.execute("SELECT value FROM probe").fetchone()[0] == "before"
    finally:
        conn.close()
    assert stat.S_IMODE(restored.stat().st_mode) == 0o600


def test_bundle_checksum_corruption_is_rejected(tmp_path):
    source = tmp_path / "source.db"
    _database(source)
    bundle = create_bundle(source, tmp_path / "backups")

    # Rebuild a structurally valid archive with a modified database while
    # retaining the original manifest/checksum files.
    corrupt = tmp_path / "corrupt.ovmbak"
    with tarfile.open(bundle, "r:gz") as original, tarfile.open(corrupt, "w:gz") as output:
        for member in original.getmembers():
            payload = original.extractfile(member).read()
            if member.name == "panel.db":
                payload += b"corrupt"
            info = tarfile.TarInfo(member.name)
            info.size = len(payload)
            output.addfile(info, io.BytesIO(payload))

    with pytest.raises(BackupBundleError, match="checksum mismatch"):
        verify_bundle(corrupt)


def test_bundle_rejects_unexpected_and_unsafe_members(tmp_path):
    bad = tmp_path / "bad.ovmbak"
    manifest = json.dumps({"format": "ovmanager-backup", "format_version": 1}).encode()
    with tarfile.open(bad, "w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
    with pytest.raises(BackupBundleError, match="unexpected bundle member"):
        verify_bundle(bad)


def test_bundle_rejects_non_sqlite_snapshot(tmp_path):
    source = tmp_path / "fake.db"
    source.write_bytes(b"not sqlite")
    with pytest.raises(BackupBundleError, match="database"):
        create_bundle(source, tmp_path / "backups")
