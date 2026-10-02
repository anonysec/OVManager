"""install.sh and manager.sh each carry one copy of the installer helpers.

These eight were scripts/lib/*.sh, fetched over the network at startup so a
`curl | bash` one-liner could find them. That was the worst decision in the
file: the installer's own behaviour came from a git tag, so between a push and
a release, install.sh on main ran the *previous* version of the code that draws
its output and asks its questions. A half-fetched set could also be sourced,
and a missing tag stopped the installer before it printed anything.

They are inline now, in both programs. The invariant is no longer "one
definition across installer+lib" — there is no lib. It is:

  1. a helper is defined at most once within one program, so no program has two
     copies of the same idea to drift apart, and
  2. the two programs' helper blocks are byte-identical, so the installer that
     draws the output and the manager that repairs the install cannot disagree
     about what that output looks like.

install.sh and manager.sh still each define their own main/usage/parse_args.
Those are two different programs with two different dispatchers, not two copies
of one helper, so the duplication ban stops at each program's own dispatchers.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
MANAGER = REPO / "manager.sh"
PROGRAMS = (INSTALLER, MANAGER)

# One entry per former scripts/lib file. The banner is what marks each section
# inside the program, and it is the only place these names are recorded, so
# adding or renaming a helper's section fails this rather than silently
# drifting the two copies apart.
LIB_NAMES = ("common.sh", "render.sh", "prompt.sh", "env.sh", "system.sh", "backup.sh", "tls.sh", "policy.sh")

DEFINITION = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\(\)", re.M)
BANNER = re.compile(r"^# =+$")


def _lib_block(path: Path) -> str:
    """The helper block inside one program: banner #1 through policy.sh's end.

    Located by its own shape rather than a line number, because the two
    programs carry different code on either side of it. The block opens at the
    first `# ===` banner and ends with the closing brace of the last helper of
    the last section — release_checksum_url, which policy.sh ends with.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if BANNER.match(line)]
    assert starts, f"{path.name} has no helper-block banner"
    end = next(i for i, line in enumerate(lines) if "release_checksum_url() {" in line)
    close = next(i for i in range(end, len(lines)) if lines[i].rstrip() == "}")
    return "".join(lines[starts[0] : close + 1])


def _defined(path: Path) -> list[str]:
    return DEFINITION.findall(path.read_text(encoding="utf-8"))


def _code(path: Path) -> list[str]:
    """Every line of a program with its trailing comment cut off.

    Comments are how the history of this decision is recorded — why the helpers
    are inline, what they used to be — so a bare search for the old path would
    ban the explanation along with the code. Stripping at the first ``#`` is the
    same rule _calls() uses: prose stays prose, and only something the shell
    would actually execute counts.
    """
    return [line.split("#", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]


# ── Layout ──────────────────────────────────────────────────────────────


def test_the_lib_directory_is_gone():
    """Nothing executes a path under scripts/lib any more.

    The directory was deleted when the helpers moved inline. A live reference is
    not a harmless leftover: manager.sh's root gate reads .env out of a 0700
    root-owned tree, so a manager that still went looking for the lib would fail
    on a directory that no longer ships — and the error the operator saw would
    name scripts/lib rather than the missing code.
    """
    assert not (REPO / "scripts" / "lib").exists(), "scripts/lib is back"
    stale = {path.name: [i for i, line in enumerate(_code(path), 1) if "scripts/lib" in line] for path in PROGRAMS}
    stale = {k: v for k, v in stale.items() if v}
    assert not stale, f"still executes a scripts/lib path: {stale}"


def test_both_programs_carry_every_section():
    """Each program carries all eight sections, by banner name.

    A section that went missing from one program would still leave the other
    looking complete, and the copy would drift the next time either was edited.
    """
    for path in PROGRAMS:
        block = _lib_block(path)
        for name in LIB_NAMES:
            assert re.search(rf"^# {re.escape(name)}$", block, re.M), f"{path.name} is missing the {name} section"


def test_no_helper_is_defined_twice_in_one_program():
    """One definition per helper per program.

    This is what the deleted parity test covered, now asserted over each program
    on its own terms: a second definition of the same helper in one file is two
    copies of one idea, and the second silently wins.
    """
    for path in PROGRAMS:
        seen: dict[str, int] = {}
        for line_no, name in enumerate(_defined(path), 1):
            assert name not in seen, f"{path.name}:{line_no} redefines {name}() (first at line {seen[name]})"
            seen[name] = line_no
        assert seen, f"{path.name} defines no functions at all"


def test_the_two_helper_blocks_are_identical():
    """install.sh's helpers and manager.sh's helpers are the same bytes.

    The installer draws the output and asks the questions; the manager repairs
    an install that already exists. If the two disagree about render_menu or
    confirm_no, the operator sees one interface while installing and a different
    one while recovering. Copying the block is safe only because this holds it
    to the other copy — the drift guard the old 45-name allowlist used to be,
    expressed as a fact about the file rather than a list to maintain.
    """
    a, b = _lib_block(INSTALLER), _lib_block(MANAGER)
    assert a == b, (
        f"helper blocks have drifted: install.sh {len(a)} bytes vs manager.sh {len(b)} bytes. "
        "Copy install.sh's block into manager.sh (or vice versa) so they match byte for byte."
    )


# ── Rendering is one place ──────────────────────────────────────────────
#
# The output vocabulary moved out of the two installers and the old helpers into
# the render section. A caller that invents its own printf is how the two
# programs drifted apart in the first place, so the ban is enforced rather than
# documented.

RETIRED_HELPERS = ("step", "info", "warn", "kv", "hr", "fail", "line")


def _calls(name: str, source: str) -> list[int]:
    """Lines that call <name> as a command.

    Tolerates the forms a real call takes — bare, after && , after || , after a
    `|| {` group, after `;` — so `x || warn "..."` is caught as well as
    `warn "..."`. A commented line is not a call.

    Written as a single-pass command-boundary match rather than the nested
    quantifier this used to be. That pattern was
    ``^\\s*(?:[^#\\n]*?(?:&&|\\|\\||\\{|;)\\s*)*NAME`` — a lazy ``*?`` inside a
    ``*``, which backtracks exponentially in the number of separators on the
    line. One 78-character line with ten ``;`` took 0.93 seconds to *fail*.

    Comments are handled by cutting the line at the first ``#``, which is
    precisely what ``[^#\\n]`` did, so the matches are identical.
    """
    pat = re.compile(r"(?:^|[;&|{()\s])" + re.escape(name) + r'\s+["\']')
    hits = []
    for i, ln in enumerate(source.splitlines(), 1):
        if pat.search(ln.split("#", 1)[0]):
            hits.append(i)
    return hits


def test_the_retired_output_helpers_are_gone():
    """Nothing may reintroduce step/info/warn/kv/hr/fail/line.

    These were the old vocabulary. Each one printed a hardcoded glyph or
    colour inline, which is exactly the duplication the render section exists
    to remove: the panel card and the node card were once two copies of the
    same idea, and they drifted. `line` is included because render_line
    replaced it and `line` is far too easy to reach for by accident.
    """
    offenders = {}
    for path in PROGRAMS:
        source = path.read_text(encoding="utf-8")
        hits = {name: _calls(name, source) for name in RETIRED_HELPERS}
        hits = {k: v for k, v in hits.items() if v}
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"retired output helpers back in use: {offenders}"


def test_render_owns_the_only_output_primitives():
    """The primitives are defined once per program, in the render section.

    _render_out is the single writer for indented output. If a second appears
    anywhere, some script has started printing outside the renderer and the
    fade/flush accounting will not know about the row it consumed.
    """
    for path in PROGRAMS:
        source = path.read_text(encoding="utf-8")
        for primitive in ("_render_out", "_render_paint"):
            defined = DEFINITION.findall(_lib_block(path))
            assert source.count(f"{primitive}() {{") == 1, f"{path.name} defines {primitive}() more than once"
            assert primitive in defined, f"{path.name} lost {primitive}() from the render section"


def test_the_helper_block_has_no_panel_imports():
    """One-way boundary: the helper block is pure shell + system tools.

    Any reference to panel code (backend/bot/frontend/cli Python) means the
    installer's shell helpers have started depending on the application, and the
    split is void — the panel could not be installed before it was deployable.
    """
    offenders = []
    for path in PROGRAMS:
        block = _lib_block(path)
        for i, line in enumerate(block.splitlines(), 1):
            if re.search(r"backend\.|bot\.|frontend/|from cli|import cli|cli\.main", line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, f"helper block references panel code: {offenders}"


def test_the_installer_downloads_only_its_payload():
    """The one thing the installer fetches is the checksummed release archive.

    This is the point of the inline: fetching the helpers meant the installer's
    own behaviour came from a tag. A curl-fetch of source that is not the release
    payload brings that back, so the ban is on any network fetch outside the
    release/checksum paths and the pinned third-party installers.
    """
    source = INSTALLER.read_text(encoding="utf-8")
    fetches = re.findall(r"curl -fsSLO?\s+(?:-o\s+\S+\s+)?[\"']?(https?://[^\"')\s]+)", source)
    allowed = ("raw.githubusercontent.com/${REPO}",)
    offenders = [u for u in fetches if not u.startswith(allowed) and "acme.sh" not in u and "astral.sh" not in u]
    assert not offenders, f"installer fetches something other than its payload: {offenders}"
