"""Remote-line rewriting for panel-generated .ovpn files (B2/B4)."""

from backend.node.management import _inject_remote_lines

SAMPLE = b"client\ndev tun\nremote 10.0.0.1 1194\n<ca>\nX\n</ca>\n"


def test_domain_prepended_and_fallback_appended():
    out = _inject_remote_lines(SAMPLE, "vpn.example.com", 1194, [("10.0.0.2", 1195)]).decode()
    lines = out.splitlines()
    assert lines[2] == "remote vpn.example.com 1194"
    assert lines[3] == "remote 10.0.0.1 1194"
    assert lines[4] == "remote 10.0.0.2 1195"


def test_no_domain_keeps_node_remote_and_adds_fallback():
    out = _inject_remote_lines(SAMPLE, None, 1194, [("10.0.0.2", 1195)]).decode()
    lines = out.splitlines()
    assert lines[2] == "remote 10.0.0.1 1194"
    assert lines[3] == "remote 10.0.0.2 1195"


def test_no_domain_no_fallbacks_is_unchanged():
    assert _inject_remote_lines(SAMPLE, None, 1194, []) == SAMPLE


def test_missing_remote_block_is_unchanged():
    body = b"client\ndev tun\n"
    assert _inject_remote_lines(body, "vpn.example.com", 1194, [("10.0.0.2", 1195)]) == body
