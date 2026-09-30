"""`.env` is a declaration, not a second place to keep state.

The rule this file pins: the installer writes `.env` once, at install, and
nothing ever writes it again. Everything else — ``ovm tls``, the panel's
certificate manager, an update — fulfils what `.env` says or leaves it alone.

The old behaviour was two locations with a hidden winner. ``main.py`` preferred
``DATA_DIR/tls/`` over ``SSL_KEYFILE``/``SSL_CERTFILE``, so an operator who
carefully placed a certificate at the path in ``.env`` watched the panel keep
serving the old one, with no error anywhere to explain it. That is the class of
bug a second location always produces, and it is why there is one now.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from cli import config, tls

REPO = Path(__file__).resolve().parent.parent
MAIN = REPO / "main.py"
TLS_ROUTER = REPO / "backend" / "routers" / "tls.py"
MANAGER = REPO / "manager.sh"


# ── .env is never written ───────────────────────────────────────────────


def test_no_cli_command_opens_env_for_writing():
    """The whole rule, in one grep.

    Any write to `.env` after install would reintroduce the split-brain: the
    file an operator edits is no longer the file the software reads, and the
    only way to find out which is which is to read two of them.
    """
    offenders = []
    for path in sorted((REPO / "cli").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "open(" in line and any(mode in line for mode in ('"w"', "'w'", '"a"', "'a'")):
                if ".env" in line or "env_path" in line or "env_file" in line:
                    offenders.append(f"{path.name}:{lineno}")
    assert not offenders, f"cli writes .env at {offenders}"


def test_the_manager_only_reads_env():
    """`env_get` reads. There is no writer, and adding one is the bug."""
    text = MANAGER.read_text(encoding="utf-8")
    assert "env_get" in text
    writers = re.findall(r"^\s*(?:printf|echo|cat)\s+.*>\s*\"?\$\{?INSTALL_DIR\}?\.env", text, re.M)
    assert not writers, f"manager.sh writes .env: {writers}"
    assert "env_set" not in text, "env_set is a writer and must not come back"


def test_config_is_read_only():
    """`ovm config` has no setters at all.

    A read-only tool is the only safe thing to point at a file the operator owns.
    """
    text = (REPO / "cli" / "config.py").read_text(encoding="utf-8")
    for verb in ("write_text", "shutil.copy", "os.replace", "os.rename", "unlink"):
        assert verb not in text, f"config.py calls {verb}"


# ── The declared pair wins ──────────────────────────────────────────────


def test_declared_paths_outrank_the_legacy_directory():
    """.env names the certificate, so .env's paths are the certificate.

    Checked on the source, because this is precedence and precedence is exactly
    the thing that has silently changed before.
    """
    body = function(MAIN, "_resolve_ssl_paths")
    assert "tls_paths.key_path()" in body, "the shared resolver is not being used"
    # The legacy directory is a fallback, never a preference.
    assert body.index("tls_paths.key_path()") < body.index("legacy_key"), (
        "the legacy DATA_DIR/tls pair is being consulted before the declared paths"
    )


def test_the_router_writes_to_the_declared_paths():
    """Same rule on the other writer: the browser's certificate upload."""
    key = function(TLS_ROUTER, "_key_path")
    assert "tls_paths.key_path()" in key, "the key path is still hardcoded to DATA_DIR/tls"
    cert = function(TLS_ROUTER, "_cert_path")
    assert "tls_paths.cert_path()" in cert, "the cert path is still hardcoded to DATA_DIR/tls"


def test_the_atomic_write_guard_follows_the_declaration():
    """The old guard refused any write outside DATA_DIR/tls.

    Left in place it would have made the whole change a no-op — every write
    would raise — so the guard had to move with the paths rather than around
    them. It is still a guard: resolved paths, not strings, and only the
    declared pair or the bookkeeping directory.
    """
    body = function(TLS_ROUTER, "_atomic_write")
    assert "outside the panel TLS directory" not in body, "the old fixed guard is still here"
    assert "allowed" in body and "resolve()" in body
    assert "_key_path()" in body and "_cert_path()" in body


def test_atomic_write_still_refuses_a_path_it_does_not_own(tmp_path, monkeypatch):
    """The guard must still bite, or widening it was just removing it."""
    import backend.routers.tls as tlsr

    monkeypatch.setattr(tlsr, "_key_path", lambda: tmp_path / "declared.key")
    monkeypatch.setattr(tlsr, "_cert_path", lambda: tmp_path / "declared.crt")
    monkeypatch.setattr(tlsr, "_tls_dir", lambda: tmp_path / "state")

    with pytest.raises(ValueError, match="outside the declared certificate paths"):
        tlsr._atomic_write(tmp_path / "elsewhere" / "sneaky.pem", b"x", 0o600)


def test_atomic_write_allows_the_declared_paths(tmp_path, monkeypatch):
    import backend.routers.tls as tlsr

    key = tmp_path / "declared.key"
    monkeypatch.setattr(tlsr, "_key_path", lambda: key)
    monkeypatch.setattr(tlsr, "_cert_path", lambda: tmp_path / "declared.crt")
    monkeypatch.setattr(tlsr, "_tls_dir", lambda: tmp_path / "state")

    tlsr._atomic_write(key, b"-----BEGIN PRIVATE KEY-----", 0o600)
    assert key.read_bytes() == b"-----BEGIN PRIVATE KEY-----"
    assert oct(key.stat().st_mode)[-3:] == "600"


# ── Migration ───────────────────────────────────────────────────────────


def test_migration_copies_rather_than_moves():
    """The old pair is left alone.

    An operator who has a working certificate in the old location has no reason
    to trust a program that deletes it during a read command. Copy, confirm it
    serves, then remove it by hand.
    """
    from backend.routers.tls import migrate_legacy_tls

    assert "read_bytes" in inspect(migrate_legacy_tls), "migration should read the old pair"
    assert "unlink" not in inspect(migrate_legacy_tls), "migration must not delete anything"


def test_migration_never_overwrites_a_declared_certificate(tmp_path, monkeypatch):
    """Someone who put a certificate where .env says is not going to have it
    replaced by one from the old directory."""
    import backend.routers.tls as tlsr

    state = tmp_path / "state"
    state.mkdir()
    (state / "privkey.pem").write_bytes(b"old-key")
    (state / "fullchain.pem").write_bytes(b"old-cert")
    new = tmp_path / "declared"
    new.mkdir()
    (new / "privkey.pem").write_bytes(b"MINE")
    (new / "fullchain.pem").write_bytes(b"MINE")

    monkeypatch.setattr(tlsr, "_tls_dir", lambda: state)
    monkeypatch.setattr(tlsr, "_key_path", lambda: new / "privkey.pem")
    monkeypatch.setattr(tlsr, "_cert_path", lambda: new / "fullchain.pem")

    result = tlsr.migrate_legacy_tls()
    assert result["ok"] is True
    assert result["migrated"] is False
    assert (new / "privkey.pem").read_bytes() == b"MINE"


def test_migration_fills_an_empty_declared_path(tmp_path, monkeypatch):
    """The common case: .env names a path, the old pair holds the certificate."""
    import backend.routers.tls as tlsr

    state = tmp_path / "state"
    state.mkdir()
    (state / "privkey.pem").write_bytes(b"old-key")
    (state / "fullchain.pem").write_bytes(b"old-cert")
    new = tmp_path / "declared"
    monkeypatch.setattr(tlsr, "_tls_dir", lambda: state)
    monkeypatch.setattr(tlsr, "_key_path", lambda: new / "privkey.pem")
    monkeypatch.setattr(tlsr, "_cert_path", lambda: new / "fullchain.pem")
    written = {}
    monkeypatch.setattr(tlsr, "_write_managed_files", lambda k, c, m: written.update(k=k, c=c, m=m))

    result = tlsr.migrate_legacy_tls()
    assert result["migrated"] is True
    assert written["k"] == b"old-key" and written["c"] == b"old-cert"
    assert result["to"].endswith("fullchain.pem")


def test_migration_is_silent_when_there_is_nothing_to_do():
    """This runs before every `ovm tls` read.

    A line saying "nothing happened" on every read is the kind of noise that
    teaches people to ignore output.
    """
    assert tls.render_migrate({"ok": True, "migrated": False}) == ""
    assert tls.render_migrate({"ok": False, "migrated": False}) == ""


def test_migration_says_where_the_certificate_went():
    text = tls.render_migrate({"ok": True, "migrated": True, "from": "/a/old", "to": "/a/new"})
    assert "/a/old" in text and "/a/new" in text
    assert "left in place" in text, "the reader must know the old copy still exists"


# ── `ovm config` ────────────────────────────────────────────────────────


def _install(tmp_path, env):
    from cli.env import Install

    (tmp_path / ".env").write_text(
        "".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8"
    )
    return Install.detect(install_dir=str(tmp_path), data_dir=env.get("DATA_DIR", str(tmp_path)))


def test_config_says_where_every_value_lives(tmp_path):
    data = config.collect(
        _install(tmp_path, {"PORT": "2095", "DATA_DIR": str(tmp_path), "SSL_CERTFILE": "/c"})
    )
    text = config.render_text(data)
    for key in ("DATA_DIR", "HOST", "PORT", "SSL_KEYFILE", "SSL_CERTFILE"):
        assert key in text, key
    assert ".env" in text


def test_config_names_the_keys_that_are_not_in_env(tmp_path):
    """The question a hand-edited .env raises is 'is this file or the database?'.

    Answering it means naming what is *not* in the file, which is the half an
    operator editing it is most likely to be wrong about.
    """
    text = config.render_text(config.collect(_install(tmp_path, {"PORT": "2095"})))
    assert "in the database, not .env" in text
    for key, _ in config.RUNTIME_KEYS:
        assert key in text, key


def test_config_never_shows_the_secret(tmp_path):
    """`JWT_SECRET_KEY` is reported as set or unset, never printed.

    A config dump that leaks the signing key is a config dump nobody pastes into
    a ticket, which was the reason to have one.
    """
    data = config.collect(
        _install(tmp_path, {"PORT": "2095", "JWT_SECRET_KEY": "s3cret-value-not-to-print"})
    )
    text = config.render_text(data)
    assert "s3cret-value-not-to-print" not in text
    assert "set" in text


def test_config_falls_back_to_the_environment(tmp_path):
    """Docker has no .env on the host; the values arrive as variables."""
    os.environ["OVM_TEST_ONLY_PORT"] = "9999"
    try:
        data = config.collect(_install(tmp_path, {"PORT": "2095"}))
        port = next(v for k, v, _, _ in data["rows"] if k == "PORT")
        assert port == "2095", "the file wins over the environment, as at boot"
    finally:
        del os.environ["OVM_TEST_ONLY_PORT"]


def test_config_rows_share_one_column(tmp_path):
    """Both blocks align independently — that is what a per-block width buys.

    One global width would work too, but it would pad the eight short keys out
    to the width of ``subscription path`` and buy nothing.
    """
    text = config.render_text(config.collect(_install(tmp_path, {"PORT": "2095"})))
    boot, _, database = text.partition("in the database, not .env")
    for block in (boot, database):
        rows = [ln for ln in block.splitlines() if re.match(r"^   \S", ln)]
        # The value starts where the label and its padding end, so that offset
        # is the column — which is the thing that was wobbling.
        starts = {re.match(r"^   \S+\s+", ln).end() for ln in rows}
        assert len(starts) == 1, f"label columns wobble: {sorted(starts)}"


def test_config_reports_unset_rather_than_blank(tmp_path):
    """A blank value and a missing one look identical in a table. They are not."""
    text = config.render_text(config.collect(_install(tmp_path, {"PORT": "2095"})))
    assert "unset" in text


def test_config_output_is_plain(tmp_path):
    assert "\x1b" not in config.render_text(config.collect(_install(tmp_path, {"PORT": "1"})))


def inspect(func) -> str:
    import inspect as _inspect

    return _inspect.getsource(func)


def function(path: Path, name: str) -> str:
    """The body of one top-level function, for source-level assertions.

    Precedence and guards are the kind of thing that changes silently, and a
    behavioural test for "which of two paths wins" needs a real certificate on
    a real port to mean anything.
    """
    source = path.read_text(encoding="utf-8")
    start = source.index(f"def {name}(")
    rest = source[start + 1 :]
    nxt = re.search(r"^(?:def |class |@)", rest, re.M)
    return source[start : start + 1 + nxt.start()] if nxt else source[start:]
