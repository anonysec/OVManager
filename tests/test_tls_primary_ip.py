"""The panel's own "certificate for this server's IP" must ask for a public one.

install.sh and manager.sh were both fixed to skip the private ranges; this path
was missed. On a host whose `hostname -I` puts a docker bridge or metadata NIC
first, the certificate request names a private IP and Let's Encrypt refuses it.
"""

import subprocess
from types import SimpleNamespace

import pytest

from backend.routers import tls


def _fake_hostname_i(monkeypatch, output):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=output, stderr=""),
    )


def test_a_docker_bridge_first_does_not_win(monkeypatch):
    # exactly what this VPS reports: public address, then five bridges
    _fake_hostname_i(monkeypatch, "2.28.122.51 172.19.0.1 172.18.0.1 172.17.0.1 172.21.0.1 172.20.0.1\n")
    assert tls._detect_primary_ip() == "2.28.122.51"


def test_a_metadata_nic_first_does_not_win(monkeypatch):
    _fake_hostname_i(monkeypatch, "169.254.169.254 203.0.113.7\n")
    assert tls._detect_primary_ip() == "203.0.113.7"


def test_ipv6_is_skipped(monkeypatch):
    _fake_hostname_i(monkeypatch, "2a01:4f8:1c1a:d354::1 198.51.100.4\n")
    assert tls._detect_primary_ip() == "198.51.100.4"


def test_a_private_only_host_still_returns_something_routable(monkeypatch):
    # nothing public; better the bridge than 127.0.0.1
    _fake_hostname_i(monkeypatch, "172.17.0.1 10.0.0.5\n")
    assert tls._detect_primary_ip() == "172.17.0.1"


@pytest.mark.parametrize("junk", ["", "not-an-ip\n", "localhost\n"])
def test_unusable_output_falls_through(monkeypatch, junk):
    _fake_hostname_i(monkeypatch, junk)
    # gethostbyname path or the 127.0.0.1 fallback — never a crash
    assert isinstance(tls._detect_primary_ip(), str)
