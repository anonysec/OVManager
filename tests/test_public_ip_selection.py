"""Let's Encrypt for this IP must name a routable address, not the first one.

The le-ip paths take `hostname -I`'s first field, which on a host with a docker
bridge or a cloud metadata NIC ahead of the public address is a private IP — and
Let's Encrypt refuses those outright.

These run each file's own `public_ip` with `hostname -I` stubbed through a real
PATH shim, because a source-text assertion cannot tell a working fix from a
comment that mentions one, and an interpolated stub cannot carry a newline.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _public_ip_from(shell: str, hostname_output: str) -> str:
    """Run that shell file's own public_ip against a fake `hostname -I`.

    The stub lives in its own directory on PATH and reads its payload from an
    env var, so nothing about the address list has to survive shell quoting.
    """
    shim = REPO / "tests" / "_hostname_shim"
    shim.mkdir(exist_ok=True)
    try:
        (shim / "hostname").write_text(
            "#!/usr/bin/env bash\n"
            'case "$1" in -I|--all-ip-addresses) printf "%s" "$STUB_HOSTNAME_I" ;;\n'
            '*) exec /usr/bin/hostname "$@" ;;\n'
            "esac\n",
            encoding="utf-8",
        )
        (shim / "hostname").chmod(0o755)
        # public_ip asks ipify.org and ifconfig.me FIRST, so a live network
        # answers with this host's real address and the stub is never consulted.
        # A curl stub that always fails forces it down to `hostname -I`.
        (shim / "curl").write_text("#!/usr/bin/env bash\nexit 6\n", encoding="utf-8")
        (shim / "curl").chmod(0o755)

        src = (REPO / shell).read_text(encoding="utf-8")
        m = re.search(r"^public_ip\(\) \{.*?\n\}", src, re.MULTILINE | re.DOTALL)
        assert m, f"{shell} has no public_ip function"

        script = f"set -euo pipefail\n{m.group(0)}\nprintf 'RESULT=%s' \"$(public_ip || true)\"\n"
        out = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO),
            env={
                **os.environ,
                "STUB_HOSTNAME_I": hostname_output,
                "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}",
            },
        )
        got = re.search(r"RESULT=(.*)", out.stdout)
        return (got.group(1) if got else "").strip()
    finally:
        subprocess.run(["rm", "-rf", str(shim)], check=False)


# what this VPS reports: the public address first, then five docker bridges,
# then IPv6. No host is guaranteed to order them that way.
BRIDGES_FIRST = (
    "169.254.169.254 203.0.113.7\n",  # a cloud metadata NIC ahead of the address
    "2a01:4f8:1c1a:d354::1 198.51.100.4\n",  # IPv6 ahead of it
    "172.17.0.1 172.18.0.1 198.51.100.9\n",  # docker bridges only
    "2.28.122.51 172.19.0.1 172.18.0.1 172.17.0.1 2a01:4f8:1c1a:d354::1\n",
)


@pytest.mark.parametrize("shell", ["install.sh", "manager.sh"])
@pytest.mark.parametrize(
    ("hostname_output", "expected"),
    [
        ("2.28.122.51 172.19.0.1 172.18.0.1 172.17.0.1 2a01:4f8:1c1a:d354::1\n", "2.28.122.51"),
        ("169.254.169.254 203.0.113.7\n", "203.0.113.7"),
        ("2a01:4f8:1c1a:d354::1 198.51.100.4\n", "198.51.100.4"),
        ("172.17.0.1 172.18.0.1 198.51.100.9\n", "198.51.100.9"),
    ],
    ids=["this-vps", "metadata-first", "ipv6-first", "bridges-first"],
)
def test_public_ip_names_a_routable_address(shell, hostname_output, expected):
    got = _public_ip_from(shell, hostname_output)
    assert got == expected, (
        f"{shell}: public_ip returned {got!r} for {hostname_output!r} — a private or IPv6 address is refused by Let's Encrypt"
    )


@pytest.mark.parametrize("shell", ["install.sh", "manager.sh"])
def test_no_tls_domain_path_takes_the_first_hostname_field(shell):
    """A site that assigns TLS_DOMAIN from `hostname -I` is the bug itself."""
    src = (REPO / shell).read_text(encoding="utf-8")
    offenders = [line.strip() for line in re.findall(r"^.*TLS_DOMAIN=.*$", src, re.MULTILINE) if "hostname -I" in line]
    assert not offenders, f"{shell}: TLS_DOMAIN still reads the first field: {offenders}"
