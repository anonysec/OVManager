# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Client-IP resolution behind a trusted reverse proxy.

The regression this guards against: trusting the *leftmost* X-Forwarded-For
entry, which a client can supply itself (nginx `$proxy_add_x_forwarded_for`
keeps it in front of the real address), allowing rate-limit bypass.
"""

from starlette.requests import Request

from backend.client_ip import client_ip
from backend.config import config


def _request(headers: dict | None = None, client=("10.0.0.9", 12345)) -> Request:
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "headers": raw,
            "client": client,
        }
    )


def test_direct_peer_used_without_trusted_proxy(monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY", False)
    assert client_ip(_request({"X-Forwarded-For": "1.2.3.4"})) == "10.0.0.9"


def test_no_header_uses_direct_peer(monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY", True)
    assert client_ip(_request()) == "10.0.0.9"


def test_rightmost_hop_is_the_one_trusted(monkeypatch):
    """A spoofed client prefix must not win: the proxy appends the real IP."""
    monkeypatch.setattr(config, "TRUSTED_PROXY", True)
    req = _request({"X-Forwarded-For": "6.6.6.6, 6.6.6.7, 203.0.113.9"})
    assert client_ip(req) == "203.0.113.9"


def test_single_value_is_used(monkeypatch):
    """Proxies that overwrite the header leave exactly one value."""
    monkeypatch.setattr(config, "TRUSTED_PROXY", True)
    assert client_ip(_request({"X-Forwarded-For": "198.51.100.7"})) == "198.51.100.7"


def test_whitespace_and_ipv6(monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY", True)
    assert client_ip(_request({"X-Forwarded-For": " 2001:db8::1 , 2001:db8::2"})) == "2001:db8::2"


def test_malformed_rightmost_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY", True)
    assert client_ip(_request({"X-Forwarded-For": "1.2.3.4, not-an-ip"})) == "10.0.0.9"
    assert client_ip(_request({"X-Forwarded-For": "1.2.3.4, 1.2.3.4:5678"})) == "10.0.0.9"


def test_no_client_returns_unknown(monkeypatch):
    monkeypatch.setattr(config, "TRUSTED_PROXY", False)
    assert client_ip(_request(client=None)) == "unknown"
