"""File digests for backup integrity.

These digests decide whether a bundle counts as "verified", so backup_bundle
and telegram_backup share one implementation rather than each carrying a
private chunked SHA-256.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file, streamed so a large bundle stays off the heap."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
