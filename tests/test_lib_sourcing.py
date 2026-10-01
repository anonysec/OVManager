"""scripts/lib is the one definition of each helper, and install.sh sources it.

install.sh used to carry a byte-identical copy of all 46 lib helpers, held in
sync by a 45-name allowlist (the retired tests/test_lib_parity.py). It now
fetches the libs at startup and sources them, which makes the copy impossible
rather than merely checked — and makes the invariant directly assertable: a
helper has exactly one definition.

install.sh and manager.sh still each define their own main/usage/parse_args.
Those are two different programs with two different dispatchers, not two copies
of one helper, so the invariant is stated over the libs.
"""

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALLER = REPO / "install.sh"
MANAGER = REPO / "manager.sh"
LIB_DIR = REPO / "scripts" / "lib"
LIB_NAMES = ("common.sh", "render.sh", "prompt.sh", "env.sh", "system.sh", "backup.sh", "tls.sh", "policy.sh")

DEFINITION = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)\(\)", re.M)


def _defined(path: Path) -> list[str]:
    return DEFINITION.findall(path.read_text(encoding="utf-8"))


def _function(name: str) -> str:
    """The definition of a helper, wherever it lives (installer or lib)."""
    for path in (INSTALLER, *(LIB_DIR / lib for lib in LIB_NAMES)):
        match = re.search(
            rf"^{re.escape(name)}\(\) \{{.*?^\}}",
            path.read_text(encoding="utf-8"),
            re.M | re.DOTALL,
        )
        if match:
            return match.group(0)
    raise AssertionError(f"{name}() is defined in neither install.sh nor scripts/lib")


def _assignment(name: str) -> str:
    """A global assignment copied out of install.sh, for the bootstrap harness."""
    return next(line for line in INSTALLER.read_text(encoding="utf-8").splitlines() if line.startswith(f"{name}="))


def _harness(tmp_path: Path, *, stub_curl: bool = False) -> Path:
    """install.sh's lib bootstrap, alone, as a script it thinks is install.sh.

    The functions are the real ones: they read their own URL from the same
    LIB_BASE/LIB_FILES assignments install.sh uses, and BASH_SOURCE points at
    this file, so the "libs beside the script" fast path does not apply and the
    fetch path is the one under test.
    """
    curl = 'curl() { printf "%s\\n" "$@" >> "$CURL_LOG"; return 1; }\n' if stub_curl else ""
    body = "\n".join(_function(name) for name in ("_boot_die", "_libs_source", "_libs_install"))
    path = tmp_path / "harness.sh"
    path.write_text(
        "set -Eeuo pipefail\n"
        'REPO="anonysec/OVManager"\nVERSION="9.9.9"\n'
        f"{_assignment('LIB_BASE')}\n{_assignment('LIB_FILES')}\n"
        f"{curl}{body}\n"
        "_libs_install\n"
        "printf 'defined=%s\\n' \"$(type -t rand_pass)\"\n",
        encoding="utf-8",
    )
    return path


def _run(script: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **env},
    )


def test_lib_layout():
    expected = set(LIB_NAMES)
    found = {p.name for p in LIB_DIR.glob("*.sh")}
    assert found == expected, f"scripts/lib layout changed: {sorted(found)}"


def test_no_helper_is_defined_in_two_files():
    """What the deleted parity test covered, now asserted directly."""
    origin: dict[str, str] = {}
    for path in (LIB_DIR / lib for lib in LIB_NAMES):
        for name in _defined(path):
            assert name not in origin, f"{name}() is defined in both {origin[name]} and {path.name}"
            origin[name] = path.name
    assert origin, "scripts/lib defines no functions at all"
    elsewhere = sorted(name for name in origin if name in _defined(INSTALLER) or name in _defined(MANAGER))
    assert elsewhere == [], f"these lib helpers are defined again outside scripts/lib: {elsewhere}"


def test_manager_sources_lib_not_copies():
    manager = MANAGER.read_text(encoding="utf-8")
    assert "scripts/lib" in manager
    for name in _defined(LIB_DIR / "common.sh") + _defined(LIB_DIR / "render.sh"):
        assert not re.search(rf"^{re.escape(name)}\(\)", manager, re.M), f"manager.sh duplicates {name}"


# ── Rendering is one place ──────────────────────────────────────────────
#
# The output vocabulary moved out of the two installers and the old helpers into
# scripts/lib/render.sh. A caller that invents its own printf is how the two
# installers drifted apart in the first place, so the ban is enforced rather
# than documented.

RETIRED_HELPERS = ("step", "info", "warn", "kv", "hr", "fail", "line")


def _calls(name: str, path: Path) -> list[int]:
    """Lines that call <name> as a command.

    Tolerates the forms a real call takes — bare, after && , after || , after a
    `|| {` group, after `;` — so `x || warn "..."` is caught as well as
    `warn "..."`. A commented line is not a call.

    Written as a single-pass command-boundary match rather than the nested
    quantifier this used to be. That pattern was
    ``^\\s*(?:[^#\\n]*?(?:&&|\\|\\||\\{|;)\\s*)*NAME`` — a lazy ``*?`` inside a
    ``*``, which backtracks exponentially in the number of separators on the
    line. One 78-character line in common.sh with ten ``;`` took 0.93 seconds
    to *fail*, and this single test was 43 of the suite's 175 seconds.

    Comments are handled by cutting the line at the first ``#``, which is
    precisely what ``[^#\\n]`` did, so the matches are identical.
    """
    pat = re.compile(r"(?:^|[;&|{()\s])" + re.escape(name) + r'\s+["\']')
    hits = []
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if pat.search(ln.split("#", 1)[0]):
            hits.append(i)
    return hits


def test_the_retired_output_helpers_are_gone():
    """Nothing may reintroduce step/info/warn/kv/hr/fail/line.

    These were the old vocabulary. Each one printed a hardcoded glyph or
    colour inline, which is exactly the duplication render.sh exists to remove:
    the panel card and the node card were once two copies of the same idea, and
    they drifted. `line` is included because render_line replaced it and
    `line` is far too easy to reach for by accident.
    """
    offenders = {}
    for path in (INSTALLER, MANAGER, *(p for p in LIB_DIR.glob("*.sh") if p.name != "render.sh")):
        hits = {name: _calls(name, path) for name in RETIRED_HELPERS}
        hits = {k: v for k, v in hits.items() if v}
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"retired output helpers back in use: {offenders}"


def test_render_owns_the_only_output_primitives():
    """The primitives are defined once, in render.sh.

    _render_out is the single writer for indented output. If it appears
    anywhere else, some script has started printing outside the renderer and the
    fade/flush accounting will not know about the row it consumed.
    """
    for path in (INSTALLER, MANAGER, *(p for p in LIB_DIR.glob("*.sh") if p.name != "render.sh")):
        source = path.read_text(encoding="utf-8")
        assert "_render_out()" not in source, f"{path.name} defines its own _render_out"
        assert "_render_paint()" not in source, f"{path.name} defines its own _render_paint"
    render = (LIB_DIR / "render.sh").read_text(encoding="utf-8")
    assert "_render_out() {" in render
    assert "_render_paint() {" in render


def test_the_installer_fetches_render_sh():
    """render.sh has to be in the fetched set, or a curl-piped install has no
    output vocabulary at all and dies on the first render_* call."""
    files = next(line for line in INSTALLER.read_text(encoding="utf-8").splitlines() if line.startswith("LIB_FILES="))
    assert "render" in files, files


def test_lib_has_no_panel_imports():
    """One-way boundary: scripts/lib is pure shell + system tools. Any
    reference to panel code (backend/bot/frontend/cli Python) means the
    simulated installer repo leaks into the app — the split is void."""
    offenders = []
    for lib in sorted(LIB_DIR.glob("*.sh")):
        for i, line in enumerate(lib.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"backend\.|bot\.|frontend/|from cli|import cli|cli\.main", line):
                offenders.append(f"{lib.name}:{i}: {line.strip()}")
    assert not offenders, f"scripts/lib references panel code: {offenders}"


def test_the_fetch_is_pinned_to_this_installers_version():
    """`install.sh -v 1.0.15` must fetch *this* installer's libs.

    The libs are installer infrastructure, and a tag predating the split has
    none at all — pinning them to the --version target would break installing
    that version outright. The pin is applied in main(), after the libs are up,
    so nothing can read it first.
    """
    source = INSTALLER.read_text(encoding="utf-8")
    base = next(line for line in source.splitlines() if line.startswith("LIB_BASE="))
    assert "raw.githubusercontent.com/${REPO}/v${VERSION}/scripts/lib" in base, base
    assert "PIN" not in base, base
    assert source.index("\n_libs_install\n") < source.index('VERSION="${PIN#v}"')


def test_a_complete_set_is_sourced(tmp_path):
    harness = _harness(tmp_path)
    r = _run(harness, {"OVM_LIB_BASE": f"file://{LIB_DIR}"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "defined=function", r.stdout


def test_a_partial_set_is_never_sourced(tmp_path):
    """One missing file must leave the environment untouched, not half-built."""
    partial = tmp_path / "partial"
    partial.mkdir()
    for lib in sorted(LIB_DIR.glob("*.sh")):
        if lib.name != "policy.sh":
            (partial / lib.name).write_text(lib.read_text(encoding="utf-8"), encoding="utf-8")
    harness = _harness(tmp_path)
    r = _run(harness, {"OVM_LIB_BASE": f"file://{partial}"})
    assert r.returncode == 1, r.stdout
    assert "Error:" in r.stderr
    assert f"file://{partial}/policy.sh" in r.stderr, r.stderr
    assert "defined=" not in r.stdout, "a partial set was sourced"


def test_the_failure_names_the_url_it_could_not_fetch(tmp_path):
    harness = _harness(tmp_path, stub_curl=True)
    log = tmp_path / "curl.log"
    r = _run(harness, {"CURL_LOG": str(log)})
    assert r.returncode == 1, r.stdout
    url = "https://raw.githubusercontent.com/anonysec/OVManager/v9.9.9/scripts/lib/common.sh"
    assert log.read_text(encoding="utf-8").split()[-1] == url, log.read_text(encoding="utf-8")
    assert url in r.stderr, r.stderr
    assert "defined=" not in r.stdout
