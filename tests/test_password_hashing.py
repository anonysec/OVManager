"""Tests for backend/auth/hash.py after the passlib → bcrypt switch.

The important guarantee is backwards compatibility: every password hash
already stored in an operator's ``admins`` table was produced by passlib and
must keep verifying, with no forced password reset.
"""

import bcrypt

from backend.auth.hash import hash_password, needs_rehash, verify_password

_LEGACY_HASH = "$2b$12$Noj4Q2Z4AlKlUA233LcJnuZaFeUORJ53JC2sKNGauoXoI7TpLdv0G"


def test_hash_then_verify_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$2b$12$")
    assert verify_password("correct horse battery staple", hashed)


def test_wrong_password_is_rejected():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_legacy_passlib_hash_still_verifies():
    assert verify_password("SuperSecret123!", _LEGACY_HASH)
    assert not verify_password("not-the-password", _LEGACY_HASH)


def test_hash_uses_12_rounds_matching_passlib_default():
    hashed = hash_password("anything")
    assert bcrypt.checkpw(b"anything", hashed.encode())
    assert hashed.split("$")[2] == "12"


def test_long_password_is_truncated_on_a_character_boundary():
    password = "ÿ" * 100
    hashed = hash_password(password)
    assert verify_password(password, hashed)

    assert verify_password("ÿ" * 36, hashed)
    assert not verify_password("ÿ" * 35, hashed)


def test_truncation_never_produces_invalid_utf8():
    """A 3-byte character straddling the 72-byte cut must be dropped whole."""
    password = "€" * 40
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("€" * 22, hashed)


def test_long_ascii_password_over_72_bytes():
    password = "a" * 200
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert verify_password("a" * 201, hashed)


def test_malformed_hash_returns_false_instead_of_raising():
    assert not verify_password("anything", "not-a-bcrypt-hash")
    assert not verify_password("anything", "")
    assert not verify_password("anything", "$2b$12$short")


def test_empty_password_hashes_and_verifies():
    hashed = hash_password("")
    assert verify_password("", hashed)
    assert not verify_password("x", hashed)


def test_needs_rehash_detects_weak_or_foreign_hashes():
    assert not needs_rehash(hash_password("strong-enough"))
    assert not needs_rehash(_LEGACY_HASH)
    assert needs_rehash("$2b$10$" + "A" * 53)  # only 10 rounds
    assert needs_rehash("garbage")
    assert needs_rehash("")
