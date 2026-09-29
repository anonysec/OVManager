"""One file-digest helper for the backup paths.

``backup_bundle`` and ``telegram_backup`` each carried their own chunked
SHA-256 — same algorithm, same 1 MiB chunk, different names. These digests
gate backup integrity, so a divergence between the two copies is a silent
"verified" on a corrupt or tampered bundle.
"""

import hashlib

import pytest


def test_matches_a_known_digest(tmp_path):
    from backend.utils.checksums import sha256_file

    payload = b"ovmanager-backup-payload"
    target = tmp_path / "bundle.ovmbak"
    target.write_bytes(payload)

    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_hashes_a_file_larger_than_one_chunk(tmp_path):
    """The chunked read must not truncate or double-count."""
    from backend.utils.checksums import sha256_file

    payload = b"x" * (3 * 1024 * 1024 + 7)
    target = tmp_path / "big.ovmbak"
    target.write_bytes(payload)

    assert sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_empty_file(tmp_path):
    from backend.utils.checksums import sha256_file

    target = tmp_path / "empty"
    target.write_bytes(b"")
    assert sha256_file(target) == hashlib.sha256(b"").hexdigest()


def test_missing_file_raises(tmp_path):
    from backend.utils.checksums import sha256_file

    with pytest.raises(OSError):
        sha256_file(tmp_path / "nope")


def test_both_backup_paths_use_the_shared_helper():
    """Neither module may keep a private copy."""
    import inspect

    from backend.operations.backup import bundle, telegram

    for module in (bundle, telegram):
        src = inspect.getsource(module)
        assert "def _sha256" not in src, f"{module.__name__} still defines its own digest"
        assert "sha256_file" in src, f"{module.__name__} does not use the shared helper"
