"""cli/render.py is the only thing that decides what the CLI looks like.

The seven renderers each used to hand-roll ``f"  {'Label':<14} {value}"`` and
``f"  Error: {msg}"``, and the panel ended up with three different indents and a
label column one character too narrow for ``Service account`` — the check most
likely to fail, so the one whose status did not line up. These are the
invariants that stopped that, and they are checkable rather than a matter of
taste.

Layout is asserted against render.sh's constants on purpose. `ovm status` and the
install card must land on the same columns, or they read as two products.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import inline_lib

REPO = Path(__file__).resolve().parent.parent
RENDER_SH = inline_lib.path("render.sh")


from cli import doctor, render, status, tls  # noqa: E402
from cli.doctor import Check  # noqa: E402

# ── The row ─────────────────────────────────────────────────────────────






# ── Colour ──────────────────────────────────────────────────────────────


def test_there_is_no_colour_at_all():
    """These screens live for thirty milliseconds.

    A fade or a green tick on output that has already scrolled past is noise,
    not signal, and it is the one thing that would make `ovm status | grep`
    useless. Plain text, always — which is also why NO_COLOR needs no handling
    here.
    """
    source = (REPO / "cli" / "render.py").read_text(encoding="utf-8")
    assert "\\033" not in source
    assert "\\x1b" not in source
    for module in ("status", "tls", "doctor", "backup", "restore", "password", "urlpath"):
        text = (REPO / "cli" / f"{module}.py").read_text(encoding="utf-8")
        assert "\\033" not in text, module


def test_a_renderer_never_emits_an_escape_sequence():
    d = {
        "ok": True,
        "installed": True,
        "mode": "native",
        "service": "active",
        "health": "ok",
        "version": "1.0.0",
        "url": "https://h:2095/k3f9/",
        "install_dir": "/opt/ovmanager",
        "data_dir": "/var/lib/ovmanager",
        "port": 2095,
    }
    for text in (
        status.render_text(d, show_all=True),
        status.render_text({"ok": False, "installed": False, "error": "gone"}),
        tls.render_text({"ok": True, "tls": True, "key": "/k", "cert": "/c", "expiry": "2036"}),
        doctor.render_text([Check(name="Disk", ok=False, detail="full", fix="free it")]),
    ):
        assert "\x1b" not in text


# ── Glyphs ──────────────────────────────────────────────────────────────



def test_glyphs_fall_back_to_ascii_when_the_locale_cannot_show_them():
    """LANG=C is a real install path, and a box with no locale set is a real
    container. Braille and box drawing come out as literal mojibake."""
    script = (
        "import locale, os\n"
        "locale.getpreferredencoding = lambda *a: 'ANSI_X3.4-1968'\n"
        "from cli import render\n"
        "print(render.glyphs())\n"
    )
    env = {**os.environ, "LANG": "C", "LC_ALL": "C", "PYTHONPATH": str(REPO)}
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, cwd=REPO, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "✓" not in out.stdout
    assert out.stdout.strip() == "('ok', 'XX')"




# ── Failure shape ───────────────────────────────────────────────────────




# ── doctor ──────────────────────────────────────────────────────────────


def _checks(*failures: Check) -> list[Check]:
    ok = [Check(name=n, ok=True, detail=d) for n, d in (("Service", "active"), ("Disk", "8G free"))]
    return ok + list(failures)



def test_doctor_puts_failures_first_with_their_fix():
    text = doctor.render_text(_checks(Check(name="Disk", ok=False, detail="only 4% free", fix="free space on /var")))
    assert text.splitlines()[0].startswith("  ✗ 1 problems")
    assert "free space on /var" in text
    # The passing checks are counted, not listed.
    assert "2 other checks passed" in text




# ── status ──────────────────────────────────────────────────────────────



def test_status_on_a_missing_install_is_a_failure_not_a_table():
    text = status.render_text({"ok": False, "installed": False, "error": "Not installed (/x missing)"})
    assert text.startswith("  ✗")
    assert "Service" not in text


# ── Grouped commands ────────────────────────────────────────────────────




# ── One renderer ────────────────────────────────────────────────────────


def test_no_cli_module_builds_a_row_by_hand():
    """No f-string label padding outside render.py.

    This is the invariant the file was created for. Seven renderers each had
    their own, and they drifted in indent, in width, and in how a failure was
    spelled.
    """
    import re as _re

    pattern = _re.compile(r"\{\s*['\"]\w+['\"]\s*:<\s*\d+\s*\}|\{\s*['\"]Error:")
    offenders = {}
    for path in sorted((REPO / "cli").glob("*.py")):
        if path.name in ("render.py", "main.py"):
            continue
        hits = [i for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if pattern.search(line)]
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"hand-built rows back in {offenders}"


def test_no_cli_module_repeats_the_locale_detection():
    """One place decides whether Unicode is available. A second copy is how the
    ASCII fallback drifts out of sync with the glyphs."""
    pattern = re.compile(r"getpreferredencoding|LC_CTYPE")
    offenders = [
        p.name
        for p in sorted((REPO / "cli").glob("*.py"))
        if p.name != "render.py" and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, offenders


def test_locale_is_read_lazily():
    """A container with no LANG must not crash the import.

    ``locale.getpreferredencoding`` can raise, and this module is imported by
    every command including the ones that only print a table.
    """
    script = (
        "import locale\n"
        "def boom(*a, **k): raise ValueError('no locale')\n"
        "locale.getpreferredencoding = boom\n"
        "from cli import render\n"
        "print(render.glyphs())\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=REPO, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip()


def test_renderer_is_importable_without_a_terminal():
    """Nothing here may consult isatty — that is the whole argument for plain
    text, and a stray call would make output depend on where it is piped."""
    source = (REPO / "cli" / "render.py").read_text(encoding="utf-8")
    assert "isatty" not in source
    assert "NO_COLOR" not in source
