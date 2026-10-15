"""render.sh is the only thing that decides what the installers look like.

These are golden transcripts: exact bytes for a terminal, and exact bytes for a
pipe. They exist because the output is generated — the fade repaints, the
spinner rewrites its own row, the cursor arithmetic is mine and nobody reading
the diff can check it by eye. A regression here is a mangled terminal, not a
wrong character, so the assertions are about the whole rendered stream rather
than a substring.

Two rules are pinned as behaviour rather than style:

  1. A piped run produces the same TEXT as a terminal run. The animation, the
     fade and the cursor moves are motion and colour only. If that ever stops
     being true, a CI log describes a different run than a watched one.
  2. Colour never carries meaning alone. Every coloured thing also has a glyph
     or a word, so NO_COLOR=1 and LANG=C lose nothing.
"""

import os
import pty
import re
import subprocess
import tempfile
from pathlib import Path

import inline_lib

REPO = Path(__file__).resolve().parent.parent
# Sourced in this order and the order matters: common.sh sets the colour globals
# and the INT/TERM trap that render.sh reads at source time, and prompt.sh calls
# render_ask(). These are the sections cut out of install.sh's inline block.
LIBS = [inline_lib.path(n) for n in ("common.sh", "render.sh", "prompt.sh")]

# Braille, box drawing and block characters all live above U+00FF; a terminal
# or locale that cannot show them gets the ASCII set instead.
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _probe(script: str, *, promptable: bool) -> str:
    """A bash file with the libs sourced and one snippet appended."""
    return (
        "set -Eeuo pipefail\n"
        + "".join(f'. "{lib}"\n' for lib in LIBS)
        + f"can_prompt() {{ return {0 if promptable else 1}; }}\n"
        + f"{script}\n"
    )


def run(script: str, *, tty: bool, **env: str) -> str:
    """Run a snippet WITHOUT a terminal and return raw stderr.

    This is the pipe path: no -t 2, so no colour and no animation. Pass
    tty=False for it — the flag is kept only so the intent reads at the call
    site, because a test that thinks it has a terminal but does not is exactly
    how the fade tests came to assert nothing.
    """
    assert not tty, "use run_pty for anything that needs a real terminal"
    full = _probe(script, promptable=False)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.sh"
        path.write_text(full, encoding="utf-8")
        r = subprocess.run(
            ["bash", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            # TERM is set here rather than inherited: render.sh gates motion on
            # ${TERM:-dumb}, so a runner with no TERM silently tests the
            # no-motion path while these assertions look for a repaint.
            env={"TERM": "xterm-256color", **os.environ, **env},
            stdin=subprocess.DEVNULL,
        )
    assert r.returncode == 0, r.stderr
    return r.stderr


def run_pty(script: str, *, stdin_pipe: bool = False, **env: str) -> str:
    """Run a snippet WITH a terminal on stderr, and return what it drew.

    A pty is the only way to get -t 2 true, and -t 2 is what gates colour,
    animation and the whole repaint path. Without this the fade, the spinner
    and the cursor accounting are untested code that only runs on a developer's
    terminal.

    stdin_pipe=True models `curl … | bash`: stdin is a pipe, stderr is still the
    operator's terminal.
    """
    full = _probe(script, promptable=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.sh"
        path.write_text(full, encoding="utf-8")
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            ["bash", str(path)],
            stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=slave,
            env={"TERM": "xterm-256color", **os.environ, **env},
        )
        os.close(slave)
        chunks = []
        try:
            while True:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
        finally:
            os.close(master)
            proc.wait(timeout=60)
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    assert proc.returncode == 0, b"".join(chunks).decode("utf-8", "replace")
    return b"".join(chunks).decode("utf-8", "replace")


def strip(text: str) -> str:
    return ANSI.sub("", text)


def screen(raw: str) -> list[str]:
    """Replay a terminal stream and return the final screen contents.

    Enough of a VT: cursor-up, erase-to-end, carriage return, newline. Any
    escape it does not model is dropped, which is fine — this is about what the
    operator ends up looking at, not about the bytes on the wire.
    """
    rows: list[str] = []
    row = 0
    col = 0
    i = 0
    while i < len(raw):
        m = re.match(r"\x1b\[(\d*)A", raw[i:])
        if m:
            row = max(0, row - int(m.group(1) or 1))
            col = 0
            i += m.end()
            continue
        m = re.match(r"\x1b\[J", raw[i:])
        if m:
            del rows[row:]
            col = 0
            i += m.end()
            continue
        m = re.match(r"\x1b\[K", raw[i:])
        if m:
            while len(rows) <= row:
                rows.append("")
            rows[row] = rows[row][:col]
            i += m.end()
            continue
        m = re.match(r"\x1b\[[0-9;]*[A-Za-z]", raw[i:])
        if m:
            i += m.end()
            continue
        ch = raw[i]
        if ch == "\n":
            row += 1
            col = 0
            i += 1
            continue
        if ch == "\r":
            col = 0
            i += 1
            continue
        while len(rows) <= row:
            rows.append("")
        rows[row] = rows[row][:col].ljust(col) + ch
        col += 1
        i += 1
    return [strip(r).rstrip() for r in rows]


# ── Banner ──────────────────────────────────────────────────────────────


def test_the_rule_is_ascii_without_a_utf8_locale():
    out = strip(run('render_banner "OVNode" "v2.0.0"', tty=False, LANG="C", LC_ALL="C"))
    assert "─" not in out
    assert "-" * 46 in out


# ── Progress block ───────────────────────────────────────────────────────

STEPS = """
render_begin "preflight" 3; render_done "debian 12 · 14G free" 412
render_begin "release" 3;   render_done "38.0 MB · sha256 ok" 9100
render_begin "health" 3;    render_done "200 in 41ms" 6900
"""


def test_the_glyph_says_what_the_colour_says():
    lines = [ln for ln in strip(run(STEPS, tty=False)).splitlines() if ln.strip()]
    for ln in lines:
        assert "✓" in ln


def test_no_colour_output_keeps_the_glyph_and_drops_the_escape():
    raw = run(STEPS, tty=False, NO_COLOR="1")
    assert "\x1b[" not in raw
    assert "✓" in strip(raw)


def test_ascii_output_keeps_the_meaning():
    lines = [ln for ln in strip(run(STEPS, tty=False, LC_ALL="C")).splitlines() if ln.strip()]
    for ln in lines:
        assert "ok" in ln, ln
        assert "✓" not in ln


def test_the_total_grows_rather_than_overcounting():
    """A step the caller did not count must not print [4/3].

    The denominator is a floor. A counter that overruns its own total is worse
    than no counter — it reads as a bug in the installer, and it is the kind of
    bug nobody reports because they assume they miscounted.
    """
    script = (
        'render_begin "a" 2; render_done "" 100\nrender_begin "b" 2; render_done "" 100\nrender_begin "c" 2; render_done "" 100\n'
    )
    out = strip(run(script, tty=False))
    assert "[3/3]" in out
    assert "[3/2]" not in out


# ── Transfers ───────────────────────────────────────────────────────────


# Two steps, so the counter is present and the release line is findable: a
# single-step run drops [1/1] as noise, which is its own tested rule.
_TRANSFER = (
    'render_begin "preflight" 2; render_done "ok" 400\n'
    'render_begin "release" 2; render_watch; '
    '_render_bytes {have} {total} {rate}; render_unwatch; render_done "" 9000'
)


def _transfer_row(**env) -> str:
    script = _TRANSFER.format(
        have=env.pop("have", "5000000"),
        total=env.pop("total", '""'),
        rate=env.pop("rate", "412"),
    )
    rows = screen(run_pty(script, **env))
    return next(r for r in rows if "[2/2]" in r)


def test_the_bar_is_ascii_without_utf8():
    line = _transfer_row(have="13002342", total="38002342", rate="4100", LC_ALL="C")
    assert "#" in line and "." in line
    assert "█" not in line and "░" not in line


# ── Failure ─────────────────────────────────────────────────────────────


def test_failure_is_ascii_too():
    out = strip(run('render_begin "v" 1; render_fail "v" "boom"', tty=False, LC_ALL="C"))
    assert "XX" in out
    assert "boom" in out


# ── Card ────────────────────────────────────────────────────────────────


CARD = 'render_card "ready" "setup key" "4f9c-2a71" "panel|https://h:2095/setup" "logs|ovm logs -f"'


# ── Ask ─────────────────────────────────────────────────────────────────


def test_a_typed_number_selects_that_item():
    """2 on a three-item menu returns the second tag, not the first."""
    out = strip(
        run(
            'ask() { printf "%s" "2"; }; render_menu "" a "one" b "two" c "three"',
            tty=False,
        )
    )
    assert "two" in out


# ── Colour discipline ───────────────────────────────────────────────────


def test_colour_is_gated_on_stderr_being_a_terminal():
    """Every renderer writes to fd 2, so the gate must test fd 2.

    [[ -t 1 ]] passed on `2>install.log` from a terminal and wrote escape codes
    into the log, and failed on `>/dev/null` and stripped colour from a terminal
    that could show it.
    """
    raw = run(STEPS, tty=False)
    assert "\x1b[" not in raw


def test_dumb_terminal_gets_no_colour():
    raw = run_pty(STEPS, TERM="dumb")
    assert "\x1b[" not in raw


def test_a_pipe_gets_no_animation():
    """Non-TTY must not spawn a spinner, must not move the cursor.

    Not just for tidiness: the cursor codes would land in a CI artifact, and the
    spinner would be a background process with nothing to draw on.
    """
    raw = run(
        'render_begin "a" 2; render_watch; sleep 0.3; render_done "" 100\nrender_begin "b" 2; render_done "" 200',
        tty=False,
    )
    assert "\x1b[" not in raw
    assert "\r" not in raw


def test_non_tty_text_matches_tty_text_exactly():
    """Rule 1 of the design: a pipe describes the same run a terminal shows.

    Both sides are stripped of colour and motion. If this ever fails, a CI log
    and a watched install disagree, and only one of them is believed.
    """
    script = (
        'render_begin "preflight" 3; render_done "debian 12 · 14G free" 412\n'
        'render_begin "release" 3; render_watch; sleep 0.3; render_done "38.0 MB" 9100\n'
        'render_begin "health" 3; render_done "200 in 41ms" 6900\n'
        f"{CARD}\n"
    )
    piped = [ln.rstrip() for ln in strip(run(script, tty=False)).splitlines() if ln.strip()]
    drawn = [ln.rstrip() for ln in screen(run_pty(script)) if ln.strip()]
    assert piped == drawn, (piped, drawn)


def test_render_takes_no_arguments_that_could_be_injected():
    """Values are arguments, never format strings.

    A secret that reached a printf format would be a shell-injection surface in
    the one place a secret is printed.
    """
    render = inline_lib.section("render.sh")
    fns = ("render_kv", "render_kv_w", "render_key", "render_card", "render_note", "render_warn")
    for fn in fns:
        start = render.index(f"{fn}() {{")
        end = render.index("\n}\n", start)
        body = render[start:end]
        assert "eval" not in body, fn


def test_render_kv_w_takes_the_column_it_is_given():
    """A fixed width only works while every label is shorter than it.

    At 14, a 40-character backup filename printed whole and dropped its value a
    column right of every other row's — the same failure ``Service account``
    caused in the CLI, in the other direction. A caller that knows its own
    labels passes the width they need.
    """
    text = strip(run("render_kv_w 30 short x\nrender_kv_w 30 a-much-longer-label y", tty=False))
    rows = [ln for ln in text.splitlines() if ln.strip()]
    assert len(rows) == 2, text
    # The value is the last word on the row, so its offset is the column.
    columns = {ln.rindex(ln.split()[-1]) for ln in rows}
    assert len(columns) == 1, f"values do not share a column: {rows}"
