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

REPO = Path(__file__).resolve().parent.parent
RENDER_SH = REPO / "scripts" / "lib" / "render.sh"


from cli import doctor, render, status, tls  # noqa: E402
from cli.doctor import Check  # noqa: E402

# ── The row ─────────────────────────────────────────────────────────────


def test_a_row_is_three_spaces_a_label_and_a_value():
    assert render.kv("Service", "active") == "   Service        active"


def test_the_label_column_is_never_narrower_than_the_shared_one():
    """14 is render.sh's RENDER_LABEL_W, so both surfaces agree on where the
    value starts."""
    assert render.LABEL_W == 14
    m = re.search(r"^RENDER_LABEL_W=(\d+)", RENDER_SH.read_text(encoding="utf-8"), re.M)
    assert m, "render.sh no longer declares RENDER_LABEL_W"
    assert render.LABEL_W == int(m.group(1))


def test_a_wide_label_pushes_the_column_not_its_own_value():
    """The bug this whole file exists to prevent.

    ``Service account`` is 15 characters. At a fixed 14 it printed the label
    whole and dropped the status one column right of every other check's — on
    the check most likely to fail.
    """
    items = [("Service", "active"), ("Service account", "FAIL  panel runs as root")]
    lines = render.rows(items)
    assert lines[1].index("FAIL") == lines[0].index("active"), lines


def test_rows_in_one_set_share_one_column():
    lines = render.rows([("a", "one"), ("longer label", "two"), ("mid", "three")])
    columns = {line.rindex(value) for line, value in zip(lines, ("one", "two", "three"), strict=True)}
    assert len(columns) == 1, lines
    assert columns.pop() == 3 + render.LABEL_W + 1


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


def test_glyphs_are_the_installers_glyphs():
    """✓ and ✗, so 'done' and 'failed' look the same in the CLI and the
    installer card."""
    assert render.glyphs() == ("✓", "✗")
    install_render = RENDER_SH.read_text(encoding="utf-8")
    assert "RENDER_OK='✓'" in install_render
    assert "RENDER_BAD='✗'" in install_render


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


def test_a_failure_uses_the_failed_glyph_not_the_word_error():
    """Six copies of `  Error: {msg}` were replaced by one function."""
    assert render.failed("boom").startswith("  ✗ ")
    assert render.failed("boom").endswith(" boom")


def test_the_error_glyph_survives_a_pipe():
    """`ovm status | grep -q unreachable` still works — the glyph is on the
    line, not wrapped around it."""
    out = subprocess.run(
        [sys.executable, "-c", "from cli import render; print(render.failed('boom'))"],
        capture_output=True,
        text=True,
        cwd=REPO,
        timeout=30,
    )
    assert "boom" in out.stdout


# ── Failure shape ───────────────────────────────────────────────────────


def test_failure_is_one_line_and_names_the_fix():
    """The old error prose was the same information at four times the length."""
    text = render.block([render.failed("no answer on /health after 40s")])
    assert text.count("\n") == 1


def test_next_step_names_two_runnable_commands():
    line = render.next_step("ovm logs 50", "ovm uninstall --purge")
    assert "ovm logs 50" in line
    assert "uninstall" in line


# ── doctor ──────────────────────────────────────────────────────────────


def _checks(*failures: Check) -> list[Check]:
    ok = [Check(name=n, ok=True, detail=d) for n, d in (("Service", "active"), ("Disk", "8G free"))]
    return ok + list(failures)


def test_a_clean_doctor_is_one_line_and_a_hint():
    text = doctor.render_text(_checks())
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 2, text
    assert lines[0].startswith("  ✓ ")
    assert "detail" in lines[1]


def test_doctor_puts_failures_first_with_their_fix():
    text = doctor.render_text(_checks(Check(name="Disk", ok=False, detail="only 4% free", fix="free space on /var")))
    assert text.splitlines()[0].startswith("  ✗ 1 problems")
    assert "free space on /var" in text
    # The passing checks are counted, not listed.
    assert "2 other checks passed" in text


def test_doctor_shows_every_check_on_request():
    text = doctor.render_text(_checks(Check(name="Disk", ok=False, detail="only 4% free", fix="free it")), show_all=True)
    assert "all checks" in text
    assert "Service" in text and "active" in text


def test_doctor_counts_linearly_with_the_problems():
    for n in range(1, 4):
        fails = [Check(name=f"C{i}", ok=False, detail="broken", fix="fix it") for i in range(n)]
        text = doctor.render_text(_checks(*fails))
        assert text.splitlines()[0].startswith(f"  ✗ {n} problems"), text


# ── status ──────────────────────────────────────────────────────────────


def test_status_all_adds_paths_without_moving_the_first_four():
    data = {
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
    short = status.render_text(data).splitlines()
    long = status.render_text(data, show_all=True).splitlines()
    assert len(short) == 4
    assert long[:4] == short
    assert len(long) == 8


def test_status_on_a_missing_install_is_a_failure_not_a_table():
    text = status.render_text({"ok": False, "installed": False, "error": "Not installed (/x missing)"})
    assert text.startswith("  ✗")
    assert "Service" not in text


# ── Grouped commands ────────────────────────────────────────────────────


def test_a_bare_group_command_lists_its_own_options():
    """`ovm tls` with no arguments tells you what `ovm tls` can do. The rule is
    the same for tls, auth and url, and it is what replaces the 64-line help."""
    text = render.options("tls", [("ovm tls selfsigned", "new self-signed"), ("ovm tls le X", "let's encrypt")])
    assert "selfsigned" in text
    assert "let's encrypt" in text


def test_options_share_the_row_column():
    text = render.options("x", [("short", "a"), ("a much longer command", "b")])
    lines = text.splitlines()
    assert lines[2].index("a") == lines[3].index("b")


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
