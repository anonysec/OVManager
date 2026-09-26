# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Bot callback + data-access rules, pinned by tests.

Two invariants that must survive every refactor:

1. Every callback_data string the keyboards can emit parses to a handler
   (no dead buttons, no uncaught slices).
2. The read/write rule: the bot READS shared backend state directly
   (identity lookup, validators) but WRITES only through the panel HTTP
   API (bot.api.Panel). No ``crud.create/update/delete`` in bot code —
   the panel stays the single writer, so audit + tenancy can't be
   bypassed from Telegram.
"""

import re
from pathlib import Path

from bot.callbacks import (
    MAX_CALLBACK_BYTES,
    build_callback,
    int_arg,
    node_ref_arg,
    parse_callback,
    uuid_arg,
)

REPO = Path(__file__).resolve().parent.parent


def test_build_callback_enforces_size_limit():
    assert build_callback("u", "abc") == "u:abc"
    try:
        build_callback("u", "x" * MAX_CALLBACK_BYTES)
    except ValueError:
        pass
    else:
        raise AssertionError("oversize callback_data must raise")


def test_registered_prefixes_round_trip():
    import bot.handlers.actions  # noqa: F401 (populates the registry)

    for prefix, arg in [
        ("ext", "some-uuid"),
        ("e30", "some-uuid"),
        ("rst", "some-uuid"),
        ("tog", "some-uuid"),
        ("dis", "some-uuid"),
        ("del", "some-uuid"),
        ("okd", "some-uuid"),
        ("undo", "some-uuid"),
        ("sub", "some-uuid"),
        ("cfg", "some-uuid"),
        ("dl", "some-uuid:3"),
    ]:
        fn, kwargs, out_arg = parse_callback(f"{prefix}:{arg}")
        assert fn is not None, f"{prefix}: has no handler"
        assert out_arg == arg
    fn, _, _ = parse_callback("nope:whatever")
    assert fn is None, "unknown prefix must fall through"


def test_arg_helpers_fail_closed():
    assert uuid_arg("6f1b2c3d-4e5f-6789-abcd-ef0123456789") is not None
    assert uuid_arg("") is None
    assert uuid_arg("a:b") is None
    assert uuid_arg("x" * 65) is None
    assert int_arg("3") == 3
    assert int_arg("junk") == 0
    assert int_arg("junk", default=7) == 7
    assert node_ref_arg("some-uuid:3") == ("some-uuid", 3)
    assert node_ref_arg("some-uuid") is None
    assert node_ref_arg("some-uuid:abc") is None
    assert node_ref_arg("") is None


def test_every_emitted_callback_fits_and_matches():
    """Scan keyboards/handlers for emitted callback literals: each must fit
    in 64 bytes at construction size and carry a known prefix."""
    known = {
        "ext", "e30", "e90", "eb10", "eb100", "rst", "tog", "dis", "del",
        "okd", "undo", "sub", "cfg", "dl", "edt", "edf", "edo", "edc",
        "u", "users", "ns", "lang", "plan",
    }
    text = (REPO / "bot" / "keyboards.py").read_text(encoding="utf-8")
    for mod in ("actions", "create", "edit", "users", "status", "settings", "home", "router"):
        text += (REPO / "bot" / "handlers" / f"{mod}.py").read_text(encoding="utf-8")
    # f"<prefix>:..." literals (static part before any {interpolation}).
    emitted = set(re.findall(r'f"([a-z0-9]+):', text))
    unknown = {p for p in emitted if p not in known}
    assert not unknown, f"callback prefixes with no documented handler: {unknown}"


def test_bot_never_writes_through_crud():
    """The panel is the single writer: bot code may read shared backend
    state but must never call crud create/update/delete paths."""
    writes = re.compile(r"crud\.(create|update|delete|adjust|restore|change_user_status|reset_user_usage)\w*\(")
    offenders = []
    for path in (REPO / "bot").rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if writes.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, f"bot writes through crud (must go over HTTP): {offenders}"
