"""File digests for backup integrity.

``backup_bundle`` and ``telegram_backup`` each carried their own chunked
SHA-256 — same algorithm, same 1 MiB chunk, two names. These digests decide
whether a bundle is "verified", so one implementation is the point.
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
