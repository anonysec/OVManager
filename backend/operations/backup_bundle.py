"""Versioned, verifiable OVManager backup bundles.

A bundle is a gzip-compressed tar archive with an ``.ovmbak`` suffix.  The
format deliberately starts small: a consistent SQLite snapshot plus a
manifest and checksums.  New members can be introduced by a future format
version without making callers guess from filenames.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.version import __version__

FORMAT_NAME = "ovmanager-backup"
FORMAT_VERSION = 1
BUNDLE_SUFFIX = ".ovmbak"
_DB_MEMBER = "panel.db"
_MANIFEST_MEMBER = "manifest.json"
_CHECKSUM_MEMBER = "checksums.sha256"
_ALLOWED_MEMBERS = {_DB_MEMBER, _MANIFEST_MEMBER, _CHECKSUM_MEMBER}
_MAX_MEMBER_SIZE = 512 * 1024 * 1024


class BackupBundleError(ValueError):
    """The backup artifact is malformed, corrupt, or unsupported."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_sqlite(path: Path) -> None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupBundleError(f"database is not readable: {exc}") from exc
    if not row or row[0] != "ok":
        raise BackupBundleError(f"database integrity check failed: {row[0] if row else 'no result'}")


def create_bundle(
    snapshot: Path,
    backup_dir: Path,
    *,
    created_at: datetime | None = None,
    label: str = "backup",
) -> Path:
    """Publish a private, atomic, verified bundle containing ``snapshot``."""

    if not label or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in label):
        raise BackupBundleError("backup label contains unsupported characters")

    if not snapshot.is_file():
        raise BackupBundleError("database snapshot does not exist")
    _check_sqlite(snapshot)
    backup_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(backup_dir, 0o700)
    except OSError:
        pass

    now = created_at or datetime.now(UTC)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    final = backup_dir / f"ovmanager-{label}-{stamp}-v{FORMAT_VERSION}{BUNDLE_SUFFIX}"
    counter = 1
    while final.exists():
        final = backup_dir / f"ovmanager-{label}-{stamp}-{counter}-v{FORMAT_VERSION}{BUNDLE_SUFFIX}"
        counter += 1

    checksum = _sha256(snapshot)
    manifest: dict[str, Any] = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": now.isoformat(),
        "database": _DB_MEMBER,
        "database_sha256": checksum,
    }

    fd, raw_tmp = tempfile.mkstemp(prefix=".ovmanager-backup-", suffix=".part", dir=backup_dir)
    os.close(fd)
    tmp = Path(raw_tmp)
    os.chmod(tmp, 0o600)
    try:
        with tempfile.TemporaryDirectory(prefix="ovmanager-bundle-") as raw_stage:
            stage = Path(raw_stage)
            manifest_path = stage / _MANIFEST_MEMBER
            checksums_path = stage / _CHECKSUM_MEMBER
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            checksums_path.write_text(f"{checksum}  {_DB_MEMBER}\n", encoding="ascii")
            with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as archive:
                archive.add(snapshot, arcname=_DB_MEMBER, recursive=False)
                archive.add(manifest_path, arcname=_MANIFEST_MEMBER, recursive=False)
                archive.add(checksums_path, arcname=_CHECKSUM_MEMBER, recursive=False)
        verify_bundle(tmp)
        os.replace(tmp, final)
        os.chmod(final, 0o600)
        return final
    finally:
        tmp.unlink(missing_ok=True)


def _safe_members(archive: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    members: dict[str, tarfile.TarInfo] = {}
    for member in archive.getmembers():
        if member.name not in _ALLOWED_MEMBERS:
            raise BackupBundleError(f"unexpected bundle member: {member.name}")
        if not member.isfile() or member.issym() or member.islnk():
            raise BackupBundleError(f"unsafe bundle member: {member.name}")
        if member.size < 0 or member.size > _MAX_MEMBER_SIZE:
            raise BackupBundleError(f"bundle member has invalid size: {member.name}")
        if member.name in members:
            raise BackupBundleError(f"duplicate bundle member: {member.name}")
        members[member.name] = member
    missing = _ALLOWED_MEMBERS - set(members)
    if missing:
        raise BackupBundleError("bundle is missing: " + ", ".join(sorted(missing)))
    return members


def _read_small(archive: tarfile.TarFile, member: tarfile.TarInfo, limit: int = 128 * 1024) -> bytes:
    if member.size > limit:
        raise BackupBundleError(f"bundle metadata is too large: {member.name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise BackupBundleError(f"cannot read bundle member: {member.name}")
    return stream.read(limit + 1)


def verify_bundle(bundle: Path) -> dict[str, Any]:
    """Verify structure, metadata, checksum, and SQLite integrity."""

    if not bundle.is_file():
        raise BackupBundleError("backup bundle does not exist")
    try:
        with tarfile.open(bundle, "r:gz") as archive:
            members = _safe_members(archive)
            try:
                manifest = json.loads(_read_small(archive, members[_MANIFEST_MEMBER]))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise BackupBundleError("invalid backup manifest") from exc
            if manifest.get("format") != FORMAT_NAME:
                raise BackupBundleError("not an OVManager backup bundle")
            if manifest.get("format_version") != FORMAT_VERSION:
                raise BackupBundleError(f"unsupported backup format version: {manifest.get('format_version')}")
            expected = str(manifest.get("database_sha256", ""))
            if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected.lower()):
                raise BackupBundleError("manifest database checksum is invalid")
            checksum_line = _read_small(archive, members[_CHECKSUM_MEMBER]).decode("ascii", errors="strict").strip()
            if checksum_line != f"{expected}  {_DB_MEMBER}":
                raise BackupBundleError("checksums file does not match manifest")
            db_stream = archive.extractfile(members[_DB_MEMBER])
            if db_stream is None:
                raise BackupBundleError("cannot read bundled database")
            digest = hashlib.sha256()
            with tempfile.NamedTemporaryFile(prefix="ovmanager-verify-", suffix=".db") as db_tmp:
                for chunk in iter(lambda: db_stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    db_tmp.write(chunk)
                db_tmp.flush()
                if digest.hexdigest() != expected:
                    raise BackupBundleError("database checksum mismatch")
                _check_sqlite(Path(db_tmp.name))
    except (tarfile.TarError, OSError) as exc:
        raise BackupBundleError(f"invalid backup archive: {exc}") from exc
    return manifest


def extract_database(bundle: Path, destination: Path) -> dict[str, Any]:
    """Verify ``bundle`` and atomically extract its SQLite member."""

    manifest = verify_bundle(bundle)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    os.close(fd)
    tmp = Path(raw_tmp)
    os.chmod(tmp, 0o600)
    try:
        with tarfile.open(bundle, "r:gz") as archive, tmp.open("wb") as output:
            members = _safe_members(archive)
            stream = archive.extractfile(members[_DB_MEMBER])
            if stream is None:
                raise BackupBundleError("cannot read bundled database")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        _check_sqlite(tmp)
        os.replace(tmp, destination)
        os.chmod(destination, 0o600)
        return manifest
    finally:
        tmp.unlink(missing_ok=True)
