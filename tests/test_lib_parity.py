"""install.sh and lib/common.sh must carry identical copies of shared helpers.

install.sh runs standalone (curl-pipe installs), so it duplicates the
library core. This test fails the suite on any drift between the two.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
LIB = REPO / "lib" / "common.sh"

SHARED = [
    "line",
    "step",
    "info",
    "warn",
    "fail",
    "kv",
    "hr",
    "die",
    "is_port",
    "rand_path",
    "rand_pass",
    "rand_hex",
    "can_prompt",
    "has_tty",
    "_masked_read",
    "_read_reply",
    "ask",
    "confirm",
    "confirm_no",
    "run_step",
    "backup_dir",
    "snapshot_code",
    "latest_snapshot",
    "open_firewall_port",
    "wait_health",
    "scheme_of",
    "panel_url",
    "secure_tls_files",
    "generate_self_signed",
    "ensure_acme",
    "issue_lets_encrypt",
    "port_in_use",
    "setup_tls",
    "env_get",
    "env_set",
    "systemctl_bounded",
    "admin_password_problem",
    "validate_admin_password",
    "prompt_validate_admin_password",
    "tui_select",
    "release_base",
    "release_url",
    "release_checksum_url",
]


def extract(text: str, name: str) -> str:
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(name)}\(\)", ln))
    if lines[start].rstrip().endswith("}"):
        return lines[start]
    end = start
    while lines[end] != "}":
        end += 1
    return "\n".join(lines[start : end + 1])


def test_lib_exists():
    assert LIB.is_file(), "lib/common.sh missing"


def test_shared_helpers_in_sync():
    installer = INSTALLER.read_text(encoding="utf-8")
    lib = LIB.read_text(encoding="utf-8")
    drifted = [n for n in SHARED if extract(installer, n) != extract(lib, n)]
    assert not drifted, f"lib/common.sh out of sync with install.sh: {drifted}"


def test_manager_sources_lib_not_copies():
    manager = (REPO / "manager.sh").read_text(encoding="utf-8")
    assert "lib/common.sh" in manager
    for name in SHARED:
        assert not re.search(rf"^{re.escape(name)}\(\)", manager, re.M), f"manager.sh duplicates lib function: {name}"
