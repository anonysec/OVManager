"""`--purge` must remove what the panel wrote, and nothing it did not.

Certificates live outside the install and data directories, so the purge left
them: a working private key at /etc/ovmanager/tls survived every uninstall, at a
path the operator had just been told was gone.

/etc/ssl/self-signed is shared — OVNode writes the same path — so removing it on
a panel uninstall would break a node that is still installed.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _do_uninstall(src: str) -> str:
    """The whole function body. A non-greedy `.*?\n}` stops at the first inner
    closing brace, which is inside the purge block — so the lines this test
    cares about were never in the slice."""
    start = src.index("do_uninstall() {")
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start : j + 1]
    raise AssertionError("do_uninstall has no closing brace")


def _host_of(src: str, value: str) -> str:
    """Run the real host_of out of install.sh."""
    m = re.search(r"^host_of\(\) \{.*?\n\}", src, re.MULTILINE | re.DOTALL)
    assert m, "install.sh has no host_of"
    script = f'set -euo pipefail\n{m.group(0)}\nhost_of "$1"\n'
    out = subprocess.run(["bash", "-c", script, "_", value], capture_output=True, text=True, timeout=30)
    return out.stdout.strip()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("panel.example.com", "panel.example.com"),
        ("https://panel.example.com/sub", "panel.example.com"),
        ("panel.example.com:2095", "panel.example.com"),
        ("203.0.113.7", "203.0.113.7"),
        ("https://203.0.113.7", "203.0.113.7"),
        ("sub.panel.example.com", "sub.panel.example.com"),
    ],
)
def test_host_of_keeps_the_whole_host(value, expected):
    """A trim chain that reduces this to "panel" points the purge nowhere."""
    assert _host_of((REPO / "install.sh").read_text(encoding="utf-8"), value) == expected


def test_purge_removes_the_certificates_it_owns():
    src = (REPO / "install.sh").read_text(encoding="utf-8")
    body = _do_uninstall(src)
    assert "rm -rf /etc/ovmanager" in body, (
        "--purge leaves /etc/ovmanager/tls behind: a private key the operator was told was gone"
    )
    assert "/etc/letsencrypt/" in body and "purge_domain" in body, "a Let's Encrypt certificate directory is also left behind"


def test_purge_does_not_touch_the_shared_certificate():
    src = (REPO / "install.sh").read_text(encoding="utf-8")
    body = _do_uninstall(src)
    removals = re.findall(r"rm -rf ([^\s;]+)", body)
    assert not any("ssl/self-signed" in r for r in removals), (
        "/etc/ssl/self-signed is shared with OVNode — removing it on a panel uninstall breaks a node that is still installed"
    )
    # and the reason is on the record, so the next reader does not "fix" it.
    # Matched loosely: the comment wraps mid-sentence.
    flat = re.sub(r"#", " ", body)
    flat = re.sub(r"\s+", " ", flat)
    assert "OVNode writes the same path" in flat
