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

import atexit
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MANAGER = REPO / "manager.sh"

# A copy of manager.sh with the root gate disabled, built once per session. The
# gate is two checks — the `id -u` one at the top of the file and check_root() —
# and neutralising only the second is not enough, because the first runs first.
_neutered_src = MANAGER.read_text(encoding="utf-8").splitlines()
_start = next(i for i, ln in enumerate(_neutered_src) if ln.startswith('if [[ "$(id -u)" -ne 0 ]]'))
_end = next(i for i in range(_start, len(_neutered_src)) if _neutered_src[i] == "fi")
_neutered_src[_start] = "if false; then"
_neutered_src = [
    ln.replace('check_root() { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }', "check_root() { return 0; }")
    for ln in _neutered_src
]
# Beside manager.sh, and removed on the way out. It has to be: the script
# resolves scripts/lib relative to its own location, so a copy in /tmp cannot
# find the libs and dies before it parses anything. A leftover file in the repo
# root would be committed by the next `git add -A`.
_NEUTERED = REPO / ".manager-nogate.sh"
_NEUTERED.write_text("\n".join(_neutered_src) + "\n", encoding="utf-8")


def _drop_neutered() -> None:
    _NEUTERED.unlink(missing_ok=True)


atexit.register(_drop_neutered)

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
    """Run the real manager.sh, through a neutered root gate.

    The gate matters: every command requires root, so on a non-root runner — CI,
    which is deliberately non-root — the script exits at the gate and never
    reaches the parser. Four tests here asserted on messages the parser only
    prints after that, and they passed on a root box while failing everywhere
    else. The gate is neutered the same way test_manager_sh.py does it, on the
    code rather than the comment above it.
    """
    import os

    return subprocess.run(
        ["bash", str(_NEUTERED), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def help_text(*args: str) -> str:
    out = run(*args)
    assert out.returncode == 0, out.stderr
    return out.stdout + out.stderr


# ── The dispatcher, actually run ─────────────────────────────────────────

# The regression this file exists for. Three node commands shipped broken in
# f77cf87 and every test passed, because the tests read the source rather than
# running the command: `ovn backup schedule` answered "Unknown option" because
# parse_args had two `backup)` arms and bash took the first. The same shape of
# bug is possible here, so the panel gets the same behavioural sweep.
ALL_VERBS = (
    "status",
    "status --all",
    "logs",
    "doctor",
    "restart",
    "enable",
    "disable",
    "tls",
    "auth",
    "url",
    "backup",
    "backup schedule",
    "restore",
    "update",
    "rollback",
    "config",
    "help",
)

RETIRED_VERBS = (
    "https",
    "tls-status",
    "owner-claim",
    "reset-password",
    "reset-urlpath",
    "recovery",
    "auto-backup status",
    "recover-update",
    "doctor-fix",
)


def _no_dispatch_failure(command: str) -> None:
    out = run(*command.split(), env={"OVM_APP_DIR": "/nonexistent", "CI": "1"})
    combined = out.stdout + out.stderr
    assert "Unknown option" not in combined, f"ovm {command} does not dispatch:\n{combined}"


def test_every_advertised_verb_dispatches():
    for command in ALL_VERBS:
        _no_dispatch_failure(command)


def test_every_retired_verb_still_dispatches():
    for command in RETIRED_VERBS:
        _no_dispatch_failure(command)


def test_no_dispatch_arm_is_defined_twice():
    """Bash takes the first matching arm and silently ignores the rest, so a
    duplicated arm is not an error — it is a command that quietly does the old
    thing. That is how `ovn backup schedule` shipped dead."""
    source = MANAGER.read_text(encoding="utf-8")
    body = source[source.index("parse_args() {") :]
    body = body[: body.index("\n# ──") if "\n# ──" in body else len(body)]
    arms = re.findall(r"^\s{12}([-\w|]+)\)", body, re.M)
    seen, dupes = set(), set()
    for arm in arms:
        (dupes if arm in seen else seen).add(arm)
    assert not dupes, f"duplicate dispatch arms: {sorted(dupes)}"


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


# ── The docs must teach the commands that exist ──────────────────────────

# A reference that documents seven removed commands is worse than none: it sends
# people to names the short help does not list, and it never mentions the three
# grouped commands that replaced them. This was true of both repos' docs until
# 2026-09-30.

REFERENCE = REPO / "scripts" / "docs" / "cli-reference.md"
RETIRED_IN_PROSE = (
    "ovm https",
    "ovm tls-status",
    "ovm owner-claim",
    "ovm reset-password",
    "ovm reset-urlpath",
    "ovm recover-update",
    "ovm doctor-fix",
)


def _prose_only(text: str) -> str:
    """The document minus the retired-names table, which is meant to name them."""
    if "### Retired names" in text:
        return text.split("### Retired names")[0] + text.split("## Status and service")[-1]
    return text


def test_the_reference_does_not_teach_retired_commands():
    prose = _prose_only(REFERENCE.read_text(encoding="utf-8"))
    for name in RETIRED_IN_PROSE:
        assert name not in prose, f"cli-reference.md still teaches `{name}`"


def test_the_reference_documents_the_grouped_commands():
    text = REFERENCE.read_text(encoding="utf-8")
    for name in ("ovm tls", "ovm auth", "ovm url"):
        assert name in text, f"cli-reference.md never mentions `{name}`"
    for sub in ("tls selfsigned", "tls le", "tls custom", "auth key", "auth reset", "url set"):
        assert sub in text, f"cli-reference.md never mentions `{sub}`"


def test_the_reference_states_the_env_rule():
    """The one rule a reader cannot infer: nothing writes .env after install."""
    # Whitespace-normalised: the sentence is wrapped, and a line break in the
    # middle of it must not decide whether the rule is documented.
    text = " ".join(REFERENCE.read_text(encoding="utf-8").split())
    assert "ever edits it again" in text
    assert "ovm config" in text


# ── No retired name where an operator can read it ────────────────────────

# The install card said "reprint: ovm owner-claim" after that name was retired,
# and three error messages in manager.sh still said reset-password and
# tls-status. A retired name still works, so nothing breaks — the operator is
# just sent to a command the tool does not advertise.

RETIRED_NAMES = (
    "ovm owner-claim",
    "ovm reset-password",
    "ovm tls-status",
    "ovm recover-update",
    "ovm doctor-fix",
    "ovm reset-urlpath",
    "ovm recovery",
    "ovm auto-backup",
)


def _arm_named(source: str, name: str) -> str:
    """One parse_args arm, comments removed.

    The comments explaining these two bugs mention the broken forms by name, so
    an assertion over the raw text would match the explanation rather than the
    code — and pass against a fix that removed the comment but not the bug.
    """
    start = source.index(f'{name}) ACTION="{name}"')
    arm = source[start : source.index(";;", start)]
    return "\n".join(ln for ln in arm.splitlines() if not ln.strip().startswith("#"))


def _readable_lines(path: Path) -> list[str]:
    """Lines a person could see: not comments, not the retired-names table."""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        out.append(f"{i}: {line}")
    return out


@pytest.mark.parametrize(
    "path",
    [
        REPO / "manager.sh",
        REPO / "install.sh",
        REPO / "cli" / "doctor.py",
        REPO / "cli" / "password.py",
        REPO / "cli" / "urlpath.py",
        REPO / "backend" / "config.py",
        REPO / "backend" / "routers" / "owner_claim.py",
    ],
    ids=lambda p: p.name,
)
def test_no_retired_name_in_operator_facing_text(path):
    offenders = [line for line in _readable_lines(path) if any(n in line for n in RETIRED_NAMES)]
    # The retired-names table in help --all is the one place they belong.
    offenders = [ln for ln in offenders if "→" not in ln]
    assert not offenders, f"{path.name} still shows a retired name:\n" + "\n".join(offenders)


def test_the_ready_card_prints_a_runnable_uninstall_command():
    """It is a function, and the card interpolated it as a variable.

    `set -u` made that a fatal unbound variable on the last line of a successful
    install — after the panel was already serving — so a working install exited
    non-zero and the card had no uninstall line at all.
    """
    source = (REPO / "install.sh").read_text(encoding="utf-8")
    start = source.index("success_card() {")
    card = source[start : source.index("\n}\n", start)]
    assert "$(installer_uninstall_command)" in card, "the card must call it, not interpolate it"
    # A bare $name is an unset variable under `set -u`, which is what made a
    # successful install exit non-zero on its last line.
    bare = card.replace("$(installer_uninstall_command)", "")
    assert "$installer_uninstall_command" not in bare


# ── The two bugs a real install found ────────────────────────────────────

# Both of these passed 904 tests. Neither was visible except by installing on a
# clean box and typing the command.


def test_bare_backup_does_not_read_a_missing_argument():
    """`ovm backup` is the first command an operator runs, and it died.

    The arm shifted "backup" away and then read `$1` unguarded. With no
    arguments left that is an unbound variable under `set -u`, so the command
    failed with "line 864: $1: unbound variable" and wrote no backup at all —
    a silent loss of the thing you run a backup for.
    """
    source = MANAGER.read_text(encoding="utf-8")
    arm = _arm_named(source, "backup")
    # The first read of an argument after `shift` must be defaulted. Later reads
    # sit behind a `$# -ge 1` guard and are fine.
    first_read = next(ln for ln in arm.splitlines() if '"$1"' in ln or '"${1' in ln)
    assert '"${1:-}"' in first_read, f"unguarded read of a shifted argument: {first_read.strip()}"


def test_backup_schedule_consumes_its_own_action():
    """`ovm backup schedule` printed nothing and exited 0.

    `shift 2` on one remaining argument is fatal under `set -u`, and it fired
    after ACTION was set — so the command looked like it had run. The action
    word after "schedule" also fell through to the next arm: `on` was rejected
    as an unknown option and `status` ran the full status screen.
    """
    source = MANAGER.read_text(encoding="utf-8")
    arm = _arm_named(source, "backup")
    assert "shift 2" not in arm, "shift 2 on one argument is fatal under set -u"
    assert 'AUTO_BACKUP_ACTION="$1"' in arm, "the action word must be consumed here"


def test_doctor_forwards_the_all_flag():
    """`ovm doctor --all` printed the same summary as `ovm doctor`.

    The flag parsed — the subcommand gets the shared parent — and was then
    dropped, because cmd_doctor() called the CLI with no arguments. So the
    help's own "detail: ovm doctor --all" pointed at a command that changed
    nothing, and a failing check could not be shown in full.
    """
    source = MANAGER.read_text(encoding="utf-8")
    for fn in ("cmd_doctor", "cmd_doctor_fix"):
        start = source.index(f"{fn}() {{")
        body = source[start : source.index("\n}\n", start)]
        assert "SHOW_ALL" in body, f"{fn}() drops --all"
        assert "--all" in body, f"{fn}() never forwards --all"
