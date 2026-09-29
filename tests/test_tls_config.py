"""Auto-detect fallback in backend/tls_config.py.

The installers (install.sh / scripts/lib/tls.sh) write the self-signed pair as
``privkey.pem`` + ``fullchain.pem``; this module used to look for ``cert.pem`` +
``key.pem``, so the fallback branch could never fire.
"""

import pytest

from backend import tls_config
from backend.tls_config import TLSConfig


@pytest.fixture(autouse=True)
def _no_tls_env(monkeypatch):
    for name in ("SSL_CERTFILE", "SSL_KEYFILE", "PANEL_DOMAIN"):
        monkeypatch.delenv(name, raising=False)


def test_self_signed_pair_written_by_the_installer_is_detected(monkeypatch, tmp_path):
    monkeypatch.setattr(tls_config, "SELF_SIGNED_DIR", str(tmp_path))
    (tmp_path / "privkey.pem").write_text("key")
    (tmp_path / "fullchain.pem").write_text("cert")

    assert TLSConfig.get_ssl_config() == {
        "cert_file": str(tmp_path / "fullchain.pem"),
        "key_file": str(tmp_path / "privkey.pem"),
    }


def test_self_signed_dir_without_a_pair_reports_no_tls(monkeypatch, tmp_path):
    monkeypatch.setattr(tls_config, "SELF_SIGNED_DIR", str(tmp_path))
    (tmp_path / "privkey.pem").write_text("key")

    assert TLSConfig.get_ssl_config() == {"cert_file": "", "key_file": ""}


def test_env_pair_wins_over_the_self_signed_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(tls_config, "SELF_SIGNED_DIR", str(tmp_path))
    (tmp_path / "privkey.pem").write_text("key")
    (tmp_path / "fullchain.pem").write_text("cert")
    monkeypatch.setenv("SSL_KEYFILE", "/env/key.pem")
    monkeypatch.setenv("SSL_CERTFILE", "/env/cert.pem")

    assert TLSConfig.get_ssl_config() == {"cert_file": "/env/cert.pem", "key_file": "/env/key.pem"}
