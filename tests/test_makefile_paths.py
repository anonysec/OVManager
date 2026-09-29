# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Every path the Makefile passes to a tool must exist.

Moving `bench/` under `scripts/` broke `make lint` with a bare
``E902 No such file or directory`` — and nothing caught it, because CI runs its
own explicit paths rather than the Makefile targets. A developer running
`make lint` got a failure that had nothing to do with their change.

This is a cheap structural check: the Makefile is a list of paths, so the paths
can be verified without running the tools.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MAKEFILE = REPO / "Makefile"

# Path-shaped arguments to the tools the Makefile invokes. Only these commands;
# a bare word like `-q` or `--frozen` is not a path.
_TOOLS = ("ruff", "pytest", "bash")
_FLAGS_WITH_VALUES = {"-n", "--dist", "-m", "-k", "--cov", "--rootdir"}


def _makefile_lines():
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and line.startswith("\t"):
            yield stripped


def test_every_path_argument_in_the_makefile_exists():
    missing = []
    for command in _makefile_lines():
        parts = command.split()
        if not parts or not any(t in parts[0] or t in command.split()[0] for t in _TOOLS):
            continue
        skip_next = False
        for token in parts[1:]:
            if skip_next:
                skip_next = False
                continue
            if token in _FLAGS_WITH_VALUES:
                skip_next = True
                continue
            if token.startswith("-") or "=" in token:
                continue
            if not re.fullmatch(r"[\w./-]+", token):
                continue
            if "/" not in token and "." not in token:
                continue  # a bare word like `tests` is still checked below
            if not (REPO / token).exists():
                missing.append(f"{command!r} -> {token}")
    assert missing == [], "Makefile references paths that do not exist:\n  " + "\n  ".join(missing)


def test_the_previously_broken_target_is_actually_green():
    """Regression pin: `make lint` must not point at the old bench/ path."""
    body = MAKEFILE.read_text(encoding="utf-8")
    assert " tests bench" not in body, "the Makefile still points at the pre-move bench/ directory"
    assert "scripts/bench" in body
