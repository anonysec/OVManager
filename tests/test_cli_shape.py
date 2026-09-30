"""The CLI's shape, end to end through the bash that dispatches to it.

`test_cli_render.py` covers what the characters are. This covers the other half
of the same argument: that a bare grouped command reaches its own option list
rather than a menu, that a retired name still works, and that `config` is
reachable at all.

The premise is that a CLI nobody can predict is a CLI nobody uses twice. The
help is short because everything else is one flag away — which only works if
the flag is there and the commands it names actually run.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANAGER = REPO / "manager.sh"

# The thirteen verbs on the short list. What the user asked the tool to be.
SHORT_LIST = (
    "status",
    "logs",
    "doctor",
    "restart",
    "enable | disable",
    "tls",
    "auth",
    "url",
    "backup",
    "restore",
    "update",
    "rollback",
    "uninstall",
)

# Old name → what replaced it. Silent, not warned: a deprecation line on every
# cron job that calls `ovm auto-backup` is noise, not notice.
RETIRED = {
    "https": "tls",
    "tls-status": "tls",
    "owner-claim": "auth",
    "reset-password": "auth",
    "reset-urlpath": "url",
    "recovery": "url",
    "auto-backup": "backup schedule",
    "recover-update": "update",
    "doctor-fix": "doctor --fix",
}


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    return subprocess.run(
        ["bash", str(MANAGER), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def help_text(*args: str) -> str:
    out = run(*args)
    assert out.returncode == 0, out.stderr
    return out.stdout + out.stderr


# ── The short list ──────────────────────────────────────────────────────


def test_the_short_help_is_one_screen():
    """Sixty-four lines was the problem. The whole point is that this fits."""
    lines = help_text().splitlines()
    assert len(lines) < 32, f"short help is {len(lines)} lines"


def test_the_short_help_carries_every_verb():
    text = help_text()
    for verb in SHORT_LIST:
        assert f"ovm {verb}" in text, f"short help missing ovm {verb}"


def test_the_short_help_has_no_flag_section():
    """Inline hints are fine; a separate enumeration is a second list."""
    text = help_text()
    for section in ("OPTIONS", "ENVIRONMENT", "RETIRED NAMES", "COMMANDS"):
        assert section not in text, f"short help carries a {section} section"


def test_the_short_help_says_why_root_is_required():
    """It is surprising, so it is explained rather than asserted.

    Every command needs root, including the read-only ones, because they read
    `.env`. A user who is told "must be root" with no reason concludes the tool
    is broken.
    """
    assert "sudo ovm" in help_text()


# ── The full reference ──────────────────────────────────────────────────


def test_the_full_reference_is_reachable_and_separate():
    text = help_text("help", "--all")
    assert "COMMANDS" in text
    assert text != help_text(), "if the two screens are the same, one should not exist"


def test_every_retired_name_is_documented_with_its_successor():
    text = help_text("help", "--all")
    for old, new in RETIRED.items():
        assert old in text, f"{old} is dispatched but undocumented"
        assert new in text, f"{old} has no successor named"


def test_the_full_reference_explains_who_runs_where():
    """Half the tool is Python, half is bash, and it is not obvious which.

    Kept here rather than in the short list: it is true and it is not something
    anyone needs while in a hurry.
    """
    text = help_text("help", "--all")
    assert "cli/" in text and "install.sh" in text


def test_the_full_reference_states_the_env_rule():
    text = help_text("help", "--all")
    assert "never" in text and ".env" in text
    assert "written once" in text.lower()


# ── Grouped commands ────────────────────────────────────────────────────


def test_three_commands_are_grouped():
    """tls, auth and url are the three that had more than one action.

    Grouping them is what made the short list fit; splitting them is what put
    twenty-seven verbs on a screen.
    """
    for name in ("tls", "auth", "url"):
        assert f"ovm {name} " in help_text(), name


def test_a_bare_group_command_reaches_its_option_list():
    """`ovm tls` with no subcommand tells you what `ovm tls` can do.

    Run with a scratch install so the certificate read is harmless, and the
    check is that the options are listed — not that the command exits zero.
    """
    # Pointed at an install that does not exist, so the certificate read is
    # guaranteed to fail. The options must still be there: a command whose
    # purpose is to say what it can do cannot be allowed to die before it says.
    out = run("tls", env={"OVM_APP_DIR": "/nonexistent", "CI": "1"})
    combined = out.stdout + out.stderr
    for option in ("ovm tls selfsigned", "ovm tls le IP|DOMAIN", "ovm tls custom CERT KEY"):
        assert option in combined, f"{option} missing from a failing read:\n{combined}"


def test_an_unknown_group_option_names_the_group():
    """A typo must point at the list of valid options.

    `ovm tls selsigned` → "see: ovm tls". Not "unknown option", which sends the
    reader to the help for a command that has one screen and four options.
    """
    out = run("tls", "selsigned", env={"CI": "1"})
    assert "see: ovm tls" in out.stdout + out.stderr, out.stdout + out.stderr


def test_the_three_groups_validate_their_arguments():
    """Each subcommand's arity is checked before anything is attempted."""
    for args, expect in (
        (("tls", "le"), "ip or a domain"),
        (("tls", "custom"), "CERT and KEY"),
        (("url", "set"), "path"),
    ):
        out = run(*args, env={"CI": "1"})
        assert expect in out.stdout + out.stderr, f"{args}: {out.stdout}{out.stderr}"


# ── url is a real command, not a .env edit ──────────────────────────────


def test_url_set_writes_the_database_not_env():
    """The prefix is a settings row; `.env` is only the seed.

    `ovm reset-urlpath` used to look like it did this and did nothing an
    operator could see, which is the failure this whole shape exists to prevent.
    """
    source = MANAGER.read_text(encoding="utf-8")
    body = source[source.index("cmd_url()") : source.index("_rand_urlpath()")]
    assert "urlpath-set" in body, "the write must go through the panel's own code"
    assert "env_set" not in body
    assert ".env" not in body.replace("$INSTALL_DIR/.env", ""), "cmd_url must not touch .env"


def test_url_reset_rotates_rather_than_clears():
    """A random prefix is the point of having one.

    `reset` moves to a fresh random path; serving at the root stays something
    you have to ask for explicitly, because it is the thing that gets found by
    a scanner.
    """
    source = MANAGER.read_text(encoding="utf-8")
    body = source[source.index("cmd_url()") : source.index("_rand_urlpath()")]
    assert "_rand_urlpath" in body
    assert "served at /" not in body, "reset must not fall back to the root path"


def test_url_reports_the_live_prefix_not_the_seed():
    """The URL is built from what the panel is serving.

    A URL built from the `.env` seed is exactly the URL that 404s, which is the
    question an operator runs `ovm url` to answer.
    """
    source = MANAGER.read_text(encoding="utf-8")
    body = source[source.index("show_login_info()") : source.index("_public_ip()")]
    assert "urlpath-show" in body, "the live prefix must be read from the panel"
    assert "Source" in body, "and the screen must say where the prefix comes from"


# ── update absorbs recover-update ───────────────────────────────────────


def test_recover_update_is_still_dispatched():
    """An interrupted update is a real state someone will hit.

    Silently mapping it to `update` would be fine only if `update` actually
    recovers first — which is asserted in the installer's own tests. Here the
    point is just that the name does not error.
    """
    out = run("recover-update", env={"CI": "1", "OVM_APP_DIR": "/nonexistent"})
    combined = out.stdout + out.stderr
    assert "Unknown option" not in combined, combined


def test_completion_offers_both_the_current_and_retired_names():
    """A tab that completes to a command which then errors is worse than a
    longer word."""
    source = MANAGER.read_text(encoding="utf-8")
    match = re.search(r'OVM_SUBCOMMANDS="([^"]*)"', source, re.S)
    assert match, "the completion word list is gone"
    words = match.group(1).split()
    for name in ("status", "tls", "auth", "url", "uninstall"):
        assert name in words, name
    for old in ("auto-backup", "recover-update", "reset-urlpath"):
        assert old in words, old


# ── config ──────────────────────────────────────────────────────────────


def test_config_is_dispatched():
    source = MANAGER.read_text(encoding="utf-8")
    assert "config) check_root; _cli_py config" in source, "ovm config is not reachable"


def test_config_never_appears_in_the_short_list():
    """It is a read, not something you reach for when something is wrong.

    The short list is arranged by how often it is needed; a troubleshooting
    command belongs in the full reference, not in front of `uninstall`.
    """
    assert "ovm config" not in help_text()
    assert "ovm config" in help_text("help", "--all")
