"""A second service on this host must not lose its TLS identity to the panel's.

``/etc/ssl/self-signed`` is a shared convention: OVNode keeps its own
certificate in exactly the two files this panel writes, and the panel's own
single-VPS guide tells operators to install both on the same host. OVNode's
installer used to overwrite the pair and ``chmod 600`` the key, which drops
the group read the panel's non-root service account (``User=ovmanager``) needs
— uvicorn then fails in ``create_ssl_context`` and the service never starts,
while ``ovm doctor`` still reports "Problems 0".

An intact pair is now reused untouched, with permissions still asserted.
These tests exercise that decision against real openssl, and pin the structure
that keeps it safe.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANAGER = REPO / "manager.sh"
LIB = REPO / "scripts" / "lib" / "tls.sh"


def _shell(script: str) -> subprocess.CompletedProcess:
    """Run a snippet with the shared TLS lib sourced, the way install.sh does."""
    return subprocess.run(
        ["bash", "-c", 'set -euo pipefail\n. "' + str(LIB) + '"\n' + script],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _usable(key: Path, cert: Path) -> bool:
    """True when the pair would be kept rather than regenerated."""
    return _shell(f'_existing_tls_pair_usable "{key}" "{cert}"').returncode == 0


def _pair(directory: Path, *, not_before: str | None = None, not_after: str | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / "privkey.pem"
    cert = directory / "fullchain.pem"
    command = ["openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-subj", "/CN=test"]
    command += ["-keyout", str(key), "-out", str(cert)]
    if not_before and not_after:
        command += ["-not_before", not_before, "-not_after", not_after]
    else:
        command += ["-days", "3650"]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        pytest.skip(f"openssl cannot build the test certificate: {done.stderr.strip()[:200]}")
    return key, cert


def _body(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\(\) \{{(.*?)^\}}", text, re.M | re.DOTALL)
    assert match, f"{name}() not found in {path.name}"
    return match.group(1)


def _permissions(body: str) -> list[int]:
    """Line indices of the statements that change TLS file permissions.

    ``generate_self_signed`` delegates the chmod to ``secure_tls_files``, so
    matching the literal command would find nothing and the ordering guard
    below would pass without testing anything. Matched at the start of the
    line: the word "chmod" inside a comment is not a statement.
    """
    return [
        i
        for i, line in enumerate(body.splitlines())
        if re.match(r"\s*(?:chmod|chown|chgrp)\b", line) or line.strip().startswith("secure_tls_files")
    ]


def test_an_intact_pair_is_reused(tmp_path):
    key, cert = _pair(tmp_path)
    assert _usable(key, cert), "an existing self-signed pair must be kept as-is"


def test_a_missing_pair_is_not_reused(tmp_path):
    assert not _usable(tmp_path / "privkey.pem", tmp_path / "fullchain.pem")


def test_a_mismatched_pair_is_not_reused(tmp_path):
    """A key that does not match its certificate serves a broken listener,
    so the pair has to be replaced rather than trusted."""
    key_a, _ = _pair(tmp_path / "a")
    _, cert_b = _pair(tmp_path / "b")
    assert not _usable(key_a, cert_b)


def test_an_expired_certificate_is_not_reused(tmp_path):
    key, cert = _pair(tmp_path, not_before="20200101000000Z", not_after="20200102000000Z")
    assert not _usable(key, cert), "an expired certificate must be replaced, not reused"


def test_a_truncated_certificate_is_not_reused(tmp_path):
    """A half-written file must not pass for a usable certificate."""
    key, cert = _pair(tmp_path)
    cert.write_text(cert.read_text(encoding="utf-8")[:400], encoding="utf-8")
    assert not _usable(key, cert)


def test_an_empty_key_is_not_reused(tmp_path):
    key, cert = _pair(tmp_path)
    key.write_text("", encoding="utf-8")
    assert not _usable(key, cert)


def test_nothing_chmods_before_the_reuse_path_returns():
    """Reuse is only safe if the pair is judged before permissions are touched.

    A chmod reached ahead of the reuse branch strips the panel's group read
    even though its certificate was kept — the failure would only move. And
    the reuse branch has to return before the regeneration tail, which both
    overwrites the pair and tightens the key.
    """
    body = _body(LIB, "generate_self_signed")
    lines = body.splitlines()
    assert "_existing_tls_pair_usable" in body
    decision = next(i for i, line in enumerate(lines) if "_existing_tls_pair_usable" in line)
    reuse = next(i for i, line in enumerate(lines) if line.strip() == "return 0")
    regen = next(i for i, line in enumerate(lines) if line.strip().startswith("openssl req -x509"))
    touching = _permissions(body)
    assert touching, "generate_self_signed no longer asserts file permissions at all"
    assert decision < min(touching), "permissions are changed before the pair is judged"
    assert reuse < regen, "a reused pair must return before regeneration overwrites it"
    assert [i for i in touching if i > regen], "the regeneration tail must still tighten the key"


def test_the_reused_pair_is_still_handed_to_the_installer():
    """grant_panel_access only chgrps and chmods 640 the key it is told about.

    A reuse branch that returned without setting TLS_KEY would leave the
    service account with no repair path for a key whose group read a node
    install took away, which is the failure this reuse exists to prevent.
    """
    lines = _body(LIB, "generate_self_signed").splitlines()
    reuse = next(i for i, line in enumerate(lines) if line.strip() == "return 0")
    branch = "\n".join(lines[:reuse])
    assert 'TLS_KEY="$key"' in branch
    assert 'TLS_CERT="$cert"' in branch


def test_regeneration_is_still_reachable_on_request():
    """`ovm https --self` is advertised as a new certificate, so on a host
    that already has a shared pair it must not be answered by the reuse
    branch."""
    assert "TLS_REGENERATE" in _body(LIB, "generate_self_signed"), "there must be a way to ask for a new certificate"
    assert "TLS_REGENERATE=1" in _body(MANAGER, "do_https"), "the explicit --self path must bypass reuse"
