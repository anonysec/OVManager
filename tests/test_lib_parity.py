"""install.sh and lib/common.sh must carry identical copies of shared helpers.

install.sh runs standalone (curl-pipe installs), so it duplicates the
library core. This test fails the suite on any drift between the two.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
LIB_DIR = REPO / "scripts" / "lib"

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
    expected = {"common.sh", "prompt.sh", "env.sh", "system.sh", "backup.sh", "tls.sh", "policy.sh"}
    found = {p.name for p in LIB_DIR.glob("*.sh")}
    assert found == expected, f"scripts/lib layout changed: {sorted(found)}"


def test_shared_helpers_in_sync():
    installer = INSTALLER.read_text(encoding="utf-8")
    drifted = []
    for lib_file in sorted(LIB_DIR.glob("*.sh")):
        lib = lib_file.read_text(encoding="utf-8")
        names = re.findall(r"^([a-z_][a-z0-9_]*)\(\)", lib, re.M)
        assert names, f"{lib_file.name} defines no functions"
        for name in names:
            if extract(installer, name) != extract(lib_file.read_text(), name):
                drifted.append(f"{lib_file.name}:{name}")
    assert not drifted, f"scripts/lib out of sync with install.sh: {drifted}"


def test_manager_sources_lib_not_copies():
    manager = (REPO / "manager.sh").read_text(encoding="utf-8")
    assert "scripts/lib" in manager
    for name in SHARED:
        assert not re.search(rf"^{re.escape(name)}\(\)", manager, re.M), f"manager.sh duplicates lib function: {name}"


def test_lib_has_no_panel_imports():
    """One-way boundary: scripts/lib is pure shell + system tools. Any
    reference to panel code (backend/bot/frontend/cli Python) means the
    simulated installer repo leaks into the app — the split is void."""
    import re as _re

    offenders = []
    for lib_file in sorted(LIB_DIR.glob("*.sh")):
        for i, line in enumerate(lib_file.read_text(encoding="utf-8").splitlines(), 1):
            if _re.search(r"backend\.|bot\.|frontend/|from cli|import cli|cli\.main", line):
                offenders.append(f"{lib_file.name}:{i}: {line.strip()}")
    assert not offenders, f"scripts/lib references panel code: {offenders}"
