#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer — native (systemd) or Docker.
#
# Zero-question by default: bare run installs with safe generated values.
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)
#
# Interactive wizard:
#   bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh) interactive
#
# AI / CI (never prompts):
#   curl -sSL URL | sudo bash -s -- --docker --yes
#
# No owner password is set here: the install prints a one-time claim key and
# the operator claims the panel in the browser (ovm auth key reprints one).
#
# Day-to-day operations (status, logs, backup, restore, TLS, recovery) live in the
# manager: ovm  (installed as ovmanager/ovm).
#
set -Eeuo pipefail

# Forks: point source downloads (and update pulls) at your own repo.
REPO="${OVM_REPO:-anonysec/OVManager}"
APP_SLUG="ovmanager"
BRANCH="main"
# Production installs use only signed/checksummed release artifacts. Developers
# who need a source checkout use git and the contributor documentation.
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.0.43"
IMAGE_REPO="ghcr.io/${REPO,,}"
ACTIVE_IMAGE_VERSION="$VERSION"
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"

# The account the panel runs as on a native install: an HTTPS server parsing
# untrusted input from anyone who can reach the port, so as root a remote
# compromise of the web app was a compromise of the box. It needs almost
# nothing — read its own code, read .env, write its data directory, read the
# TLS key — and cannot update itself, because `ovm update` replaces the tree
# and restarts the unit as root. Docker already takes this shape with appuser.
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

# ── The installer is one file ──────────────────────────────────────────────
#
# These eight helpers were scripts/lib/*.sh, fetched over the network at
# startup so a `curl | bash` one-liner could find them. That was the worst
# decision in the file: the installer's own behaviour came from a git tag, so
# between a push and a release, install.sh on main ran the *previous* version
# of the code that draws its output and asks its questions. It also meant a
# half-fetched set could be sourced, and a missing tag stopped the installer
# before it printed anything.
#
# They are here now. The only thing this installer downloads is the payload it
# installs, which is a checksummed release archive.
#
# manager.sh carries the same block, byte for byte. The two are different
# programs with different dispatchers, so each holds its own copy deliberately;
# tests/test_lib_sourcing.py enforces that a helper is defined once per program
# and that the two copies do not drift.

# ==========================================================================
# common.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
#
# Colour globals and the fatal-exit path. Rendering lives in render.sh; this
# file owns what it needs to render at all, and the one thing rendering must
# not own — the exit.

# ── Colour / TTY ───────────────────────────────────────────────────────
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; CY=$'\033[36m'; GY=$'\033[90m'
OR=$'\033[38;5;208m'
# Colour only when stderr is a terminal. Every helper in this library writes to
# fd 2, so the gate must test fd 2: [[ -t 1 ]] passed on `2>install.log` from a
# terminal and wrote escape codes into the log, and failed on `>/dev/null` and
# stripped colour from a terminal that could show it. The node side already uses
# [[ -t 2 ]] — this matches it.
# TERM=dumb is in the same condition as NO_COLOR and not a colour: a dumb
# terminal honours no escapes at all, and writing them produces the visible
# garbage the mode exists to prevent.
[[ -t 2 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]] \
    || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; CY=''; GY=''; OR=''; }

trap 'printf "\n  %bInterrupted.%b\n" "$RD" "$NC" >&2; exit 130' INT TERM

# Fatal exit. Deliberately NOT a render helper: this is the exit path, not
# decoration, and it must keep working when the terminal is unusable, when
# render.sh failed to source, and when output is a pipe. The Run ID is the
# support handle — it ties a log, a backup file and an update journal together.
die() {
    local run_id="${OVM_RUN_ID:-$(date +%Y%m%d-%H%M%S)-$$}"
    printf '\n  %bError:%b %s\n  %bRun ID:%b %s\n\n' "$RD" "$NC" "$1" "$GY" "$NC" "$run_id" >&2
    exit 1
}

is_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }

rand_path() {
    openssl rand -hex 4 2>/dev/null || head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

rand_pass() {
    openssl rand -base64 12 2>/dev/null | tr -d '/+=\n' | head -c 12
}

rand_hex() {
    openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

# ==========================================================================
# render.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
#
# Every character this project puts on a terminal. It knows how a line looks;
# it never knows what happened, which service was started, or whether a port is
# free. That split is the whole reason it is a separate file: install.sh owns
# the sequence, render.sh owns the rendering, and either can be replaced alone.
#
# Everything writes to fd 2, for the same reason it always has: stdout stays
# parseable (`ovm status --all`, `install.sh version-script`) while progress
# goes to the terminal, so `install.sh ... > file` still logs.
#
# Design rules, in the order they matter:
#   1. Non-TTY output is byte-identical to TTY output. The animation, the
#      fade and the cursor moves are colour and motion only — never content.
#      A piped CI log must not describe a different run than a watched one.
#   2. Colour never carries meaning alone. Every coloured thing also has a
#      glyph or a word, so NO_COLOR=1 and LANG=C lose nothing.
#   3. Bold is reserved for things a human might type or copy back: the
#      selected menu number, a URL, a secret.
#   4. Every redraw is best-effort. A terminal that cannot do it gets the
#      static form and a slower install, never a failed one.

# ── Capability detection ───────────────────────────────────────────────
# One decision, made once, read everywhere. Resolved at source time so the
# helpers below are branch-free.
#
# The colour gate tests fd 2, not fd 1: every helper here writes to fd 2, and
# `install.sh 2>install.log` from a terminal used to pass [[ -t 1 ]] and write
# escape codes into the log. The node side already tests -t 2; this matches it.
if [[ -t 2 && -z "${NO_COLOR:-}" && "${TERM:-dumb}" != "dumb" ]]; then
    RENDER_COLOR=1
else
    RENDER_COLOR=0
fi

# Braille is the only widely-available frame set that reads as continuous
# rotation without shifting the line. LANG=C and a non-UTF-8 SSH client get the
# dot frames, which are the same visual idea in one column.
if [[ "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" == *[Uu][Tt][Ff]* ]]; then
    RENDER_SPINNER_UNICODE=1
else
    RENDER_SPINNER_UNICODE=0
fi

# Animation is motion on a screen nobody is watching, and cursor-up-and-rewrite
# is the one thing in this file that can fail a `set -e` shell. It therefore
# runs only when stderr is a terminal.
#
# Deliberately NOT also gated on stdin: `curl -sSL URL | sudo bash -s -- --yes`
# is the documented install path and its stdin is the pipe, yet its stderr is
# the operator's terminal. Requiring a tty on stdin meant the most common way
# to install the panel got the degraded output.
# A dumb terminal honours no escapes at all — not SGR, not cursor motion — so
# it gets the static form as well as no colour. NO_COLOR is narrower: it is a
# request about colour specifically, and a terminal that declined colour still
# repaints fine, so the motion stays.
if [[ -t 2 && "${TERM:-dumb}" != "dumb" ]]; then
    RENDER_ANIMATE=1
else
    RENDER_ANIMATE=0
fi

# Three depths, not more: a terminal that can show three greys reliably shows
# them, and a fourth is indistinguishable from the third on most palettes.
RENDER_FADE_0=$'\033[38;5;250m'   # finished, still fresh
RENDER_FADE_1=$'\033[38;5;244m'   # one step further back
RENDER_FADE_2=$'\033[38;5;240m'   # the rest of the run

# ── Primitives ──────────────────────────────────────────────────────────

# Every glyph in one place, ASCII and Unicode pairs. Callers never type a
# character directly, so LANG=C output stays coherent.
if [[ "$RENDER_SPINNER_UNICODE" -eq 1 ]]; then
    RENDER_FRAMES='⣾⣽⣻⢿⡿⣟⣯⣷'
    RENDER_POINTER='▸'
    RENDER_OK='✓'
    RENDER_BAD='✗'
    RENDER_RULE='──────────────────────────────────────────────'
    RENDER_BAR_FULL='█'
    RENDER_BAR_EMPTY='░'
else
    RENDER_FRAMES='-\|/-\'
    RENDER_POINTER='>'
    RENDER_OK='ok'
    RENDER_BAD='XX'
    RENDER_RULE='----------------------------------------------'
    RENDER_BAR_FULL='#'
    RENDER_BAR_EMPTY='.'
fi

_render_paint() {  # _render_paint <colour> <text> — no-op when colour is off
    if [[ "$RENDER_COLOR" -eq 1 ]]; then printf '%b%s%b' "$1" "$2" "${NC:-}"; else printf '%s' "$2"; fi
}

_render_out() { printf '  %b\n' "$*" >&2; }

# Note that output was written BELOW the progress block without repainting it.
#
# Every plain line — a blank, a card row, a warning — pushes the cursor one row
# further from the block's first row, and the next repaint has to know that or
# it lands a row too low and leaves a duplicate step line behind. Anything that
# writes while a block is on screen goes through here.
_render_cursor_advanced() {
    [[ "$RENDER_ANIMATE" -eq 1 ]] || return 0
    [[ "${RENDER_TOP:-0}" -gt 0 ]] || return 0
    RENDER_TOP=$(( RENDER_TOP + 1 ))
    return 0
}

# Milliseconds → a fixed-width human duration. Sub-second steps read as "0.4s"
# rather than vanishing: the right column is the answer to "why did this take
# twenty seconds", so it must never be the one thing that is blank.
_render_ms() {
    [[ -n "${1:-}" ]] || { printf ''; return 0; }
    awk -v ms="${1}" 'BEGIN { s = ms / 1000; if (s >= 60) printf "%dm%02ds", int(s/60), s%60; else if (s >= 10) printf "%.0fs", s; else printf "%.1fs", s }' | tr -d '\n' | awk '{ printf "%7s", $0 }'
}

_render_bar() {  # _render_bar <fraction 0-1> <width>
    local filled width="${2:-24}" frac="$1" i bar=""
    filled="$(awk -v f="$frac" -v w="$width" 'BEGIN { n = int(f * w + 0.5); print (n < 0 ? 0 : (n > w ? w : n)) }')"
    for (( i = 0; i < width; i++ )); do
        if (( i < filled )); then bar+="$RENDER_BAR_FULL"; else bar+="$RENDER_BAR_EMPTY"; fi
    done
    printf '%s' "$bar"
}

# ── Banner / screen ─────────────────────────────────────────────────────

render_banner() {  # render_banner <name> <version>
    local name="$1" version="$2"
    _render_out "$(_render_paint "$B" "$name")  $version  $(_render_paint "$GY" "· anonysec")"
    render_rule
}

render_rule() { _render_out "$(_render_paint "$GY" "$RENDER_RULE")"; }

# Wipe between wizard steps. TTY only: `clear` in a pipe writes form feeds into
# the log and destroys the record of what was chosen. A caller that reaches the
# wizard has already been proven able to prompt, so this is belt-and-braces
# rather than the primary check.
render_screen() {
    [[ "$RENDER_ANIMATE" -eq 1 ]] || return 0
    # `clear 2>/dev/null`, not `command clear >/dev/null 2>&1`. `clear` clears
    # by *printing* escape codes, so redirecting its stdout to /dev/null threw
    # the codes away and the screen was never cleared — the exact opposite of
    # what that redirection looks like it is doing. Only stderr is silenced, to
    # keep "terminal not found" out of the output. The printf fallback still
    # covers a host where `clear` is missing or non-functional.
    clear 2>/dev/null || printf '\033[H\033[2J\033[3J' >&2 || true
    return 0
}

# ── Menu ───────────────────────────────────────────────────────────────
#
# Numbers only. The arrow-key version redrew the menu in place on a separate fd
# and read single keystrokes from /dev/tty with a two-second timeout, so a
# pasted line, a closed terminal or a tmux that lost the pane could leave a
# half-drawn frame on screen — and every one of those timeouts was a branch to
# get right. Typing a number needs none of it, and `ask` already reads the
# answer. A person who reaches for the arrows loses the arrows and nothing
# else; the menu is still a menu.
#
# render_menu <title> <tag> <label> [<tag> <label> ...] → prints the tag.

render_menu() {
    shift    # title is the caller's; the banner already said what this is
    local -a tags=() labels=()
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    local count=${#tags[@]}
    [[ "$count" -gt 0 ]] || return 1

    local i=0
    while (( i < count )); do
        printf '  %b%d%b  %s\n' "$B" "$(( i + 1 ))" "$NC" "${labels[$i]}" >&2
        i=$(( i + 1 ))
    done

    local n
    n="$(ask "choice" "1")"
    [[ "$n" =~ ^[0-9]+$ ]] || n=1
    # Wrap into range rather than crash on 0 or a stray large number. The
    # modulo is done in bash's own arithmetic, where a negative operand keeps
    # its sign: $(( (0 - 1) % 3 )) is -1, and indexing with -1 is the last
    # element rather than the first. Adding the count first keeps it positive.
    printf '%s' "${tags[$(( ((10#$n - 1) + count) % count ))]}"
    return 0
}

# ── Progress ───────────────────────────────────────────────────────────
#
# A step is one line: [n/6] ✓ label   detail   time. The counter is the only
# header — phase names were a second, competing way of saying where you are,
# and the indentation that came with them cost more than they explained.
#
# Finished lines recede: a step holds full weight for one beat, then drops a
# grey per beat, so the eye has a moving edge to follow and the whole run reads
# as faint history once it ends. That trail is left in the scrollback, which is
# why it survives into a piped log — the colours differ, the text does not.
#
# Non-TTY never redraws and never animates: each step prints once, the moment
# it finishes, in order. Identical text, no cursor movement, so a CI log reads
# as a plain record of the run.

RENDER_TOTAL=0
RENDER_LABELS=()
RENDER_DETAILS=()
RENDER_TIMES=()
RENDER_DONE=0
RENDER_NOW=0
RENDER_DRAWN=0
RENDER_TOP=0
RENDER_SETTLE=0

_render_ms_since() {  # ms since RENDER_NOW, as a plain integer
    local now="${1:-}" tail
    now="$(date +%s%N 2>/dev/null || printf '')"
    [[ "$now" == *N* ]] || now="$(date +%s 2>/dev/null || printf 0)000000000"
    tail="${now##*.}"; [[ "$tail" =~ ^[0-9]+$ ]] || tail=0
    tail=$(( 10#$tail / 1000000 ))
    local start="${RENDER_NOW##*.}"; [[ "$start" =~ ^[0-9]+$ ]] || start=0
    start=$(( 10#$start / 1000000 ))
    local d=$(( tail - start ))
    (( d < 0 )) && d=0
    printf '%s' "$d"
}

_render_now() {
    local now
    now="$(date +%s%N 2>/dev/null || printf '')"
    [[ "$now" == *N* ]] || now="$(date +%s 2>/dev/null || printf 0)000000000"
    printf '%s' "$now"
}

# Grey by steps-back. Three depths only: a terminal that renders three reliably
# renders them, and a fourth is indistinguishable from the third on most
# palettes. Without colour every depth is the same — which is the point, the
# glyph still says which step is running.
#
# RENDER_SETTLE overrides all of it: once the run is over there is no "current"
# step left to point at, so the whole block drops to the faintest depth and the
# card that follows is the only thing on screen at full weight.
_render_depth_colour() {
    local back="$1"
    [[ "$RENDER_COLOR" == 1 ]] || { printf ''; return 0; }
    [[ "${RENDER_SETTLE:-0}" == 1 ]] && { printf '%s' "$RENDER_FADE_2"; return 0; }
    [[ "$back" -le 0 ]] && { printf ''; return 0; }
    [[ "$back" == 1 ]] && { printf '%s' "$RENDER_FADE_0"; return 0; }
    [[ "$back" == 2 ]] && { printf '%s' "$RENDER_FADE_1"; return 0; }
    printf '%s' "$RENDER_FADE_2"
}

# Column widths, so the block reads as a table: counter, glyph, label, detail,
# time. Everything is padded to the widest value seen so far, which is why a
# label set early does not make later lines jitter.
_render_widths() {  # sets _W_LABEL _W_DETAIL
    local i n=${#RENDER_LABELS[@]} l d
    _W_LABEL=0; _W_DETAIL=0
    for (( i = 0; i < n; i++ )); do
        l=${#RENDER_LABELS[$i]}
        d=${#RENDER_DETAILS[$i]}
        (( l > _W_LABEL )) && _W_LABEL=$l
        (( d > _W_DETAIL )) && _W_DETAIL=$d
    done
    (( _W_LABEL < 8 )) && _W_LABEL=8
    (( _W_DETAIL < 10 )) && _W_DETAIL=10
    return 0
}

_render_step_line() {  # _render_step_line <index> <frame> [no-newline]
    local i="$1" frame="${2:-}" nl="${3:-}" running=0
    (( i == RENDER_DONE )) && running=1
    _render_widths
    local back=$(( RENDER_DONE - i ))
    local c="$(_render_depth_colour "$back")"
    local label="${RENDER_LABELS[$i]}" detail="${RENDER_DETAILS[$i]}" time="${RENDER_TIMES[$i]}"
    # The spinner is a separate process holding a snapshot of the arrays, so it
    # hands the live detail over in a variable instead. One detail, whichever
    # process is painting it.
    [[ -n "${RENDER_DETAILS_SNAPSHOT:-}" ]] && detail="$RENDER_DETAILS_SNAPSHOT"
    local counter="" glyph glyph_c body
    if (( RENDER_TOTAL > 1 )); then
        counter="$(printf '%b[%d/%d]%b' "$c" "$(( i + 1 ))" "$RENDER_TOTAL" "$NC")"
    fi
    if (( running )); then
        # The running step is the only full-weight line on screen. Its clock
        # ticks, because a step that has said nothing for a minute is
        # indistinguishable from a hung installer.
        glyph="${frame:-$RENDER_POINTER}"; glyph_c="$OR"
        body="$(printf '%b%-*s%b  %-*s' "$OR" "$_W_LABEL" "$label" "$NC" "$_W_DETAIL" "$detail")"
        time="$(_render_ms_since "$RENDER_NOW")"
    else
        glyph="$RENDER_OK"; glyph_c="$GR"
        body="$(printf '%-*s  %-*s' "$_W_LABEL" "$label" "$_W_DETAIL" "$detail")"
    fi
    if [[ -n "$nl" ]]; then
        printf '  %b%s%b %b%s%b %b%s%b %7s' \
            "$c" "$counter" "$NC" \
            "$glyph_c" "$glyph" "$NC" \
            "$c" "$body" "$NC" \
            "$(_render_ms "$time")"
    else
        printf '  %b%s%b %b%s%b %b%s%b %7s\n' \
            "$c" "$counter" "$NC" \
            "$glyph_c" "$glyph" "$NC" \
            "$c" "$body" "$NC" \
            "$(_render_ms "$time")"
    fi
}

_render_repaint() {  # repaint the whole block in place
    [[ "$RENDER_ANIMATE" -eq 1 ]] || return 0
    local total=${#RENDER_LABELS[@]} i
    (( total > 0 )) || return 0
    # The block's first row, tracked rather than derived.
    #
    # A step that animated leaves a half-drawn line behind it, so the cursor is
    # not simply one past the block's last row: the repaint has to reach further
    # back to find the top. RENDER_TOP is the distance from the cursor to that
    # first row, and the spinner's own row is part of it — which is why unwatch
    # adds one.
    (( RENDER_TOP > 0 )) && printf '\033[%dA\033[J' "$RENDER_TOP" >&2 2>/dev/null || true
    for (( i = 0; i < total; i++ )); do
        _render_step_line "$i" >&2 2>/dev/null || true
    done
    RENDER_DRAWN="$total"
    RENDER_TOP="$total"
    return 0
}

# render_begin <label> <total> — open a step.
#
# The number is the caller's position, so a mode that skips a step (docker has
# no uv to install) still numbers honestly. The total is a floor, not a cap: if
# more steps open than were declared — a conditional branch the caller did not
# count — the denominator grows to match rather than printing [7/6]. A counter
# that overcounts is worse than no counter.
render_begin() {
    RENDER_NOW="$(_render_now)"
    local next=$(( ${#RENDER_LABELS[@]} + 1 ))
    if (( next > ${2:-1} )); then RENDER_TOTAL="$next"; else RENDER_TOTAL="$2"; fi
    RENDER_LABELS+=("$1")
    RENDER_DETAILS+=("")
    RENDER_TIMES+=("")
    RENDER_DONE=$(( ${#RENDER_LABELS[@]} - 1 ))
    RENDER_SPIN_PID=""
    RENDER_SPIN_FLAG=""
    return 0
}

# render_watch [detail] — start animating the running step. Separate from
# render_begin so a caller doing something quick does not spawn a subshell for
# it, and so non-TTY spawns nothing at all.
render_watch() {
    [[ "$RENDER_ANIMATE" -eq 1 ]] || return 0
    local idx="$RENDER_DONE" detail="${1:-${RENDER_DETAILS[$RENDER_DONE]:-}}"
    RENDER_SPIN_DETAIL="$(_render_flagfile)"
    RENDER_SPIN_FLAG="$(_render_flagfile)"
    printf '%s' "$detail" > "$RENDER_SPIN_DETAIL" 2>/dev/null || true
    render_spin "$idx" "$RENDER_SPIN_DETAIL" "$RENDER_SPIN_FLAG" &
    RENDER_SPIN_PID=$!
    disown 2>/dev/null || true
    return 0
}

_render_flagfile() {
    local f
    f="$(mktemp "${TMPDIR:-/tmp}/render-spin.XXXXXX" 2>/dev/null)" || f=""
    [[ -n "$f" ]] || return 0
    rm -f "$f"
    printf '%s' "$f"
}

# Stop the animation and account for the row it left behind. Safe to call when
# it was never started.
#
# The spinner ended mid-row (no trailing newline), so the cursor is parked at
# the end of that line. The newline here closes it and turns it into a real row
# the block's next repaint has to include.
render_unwatch() {
    [[ -n "${RENDER_SPIN_PID:-}" ]] || return 0
    kill "$RENDER_SPIN_PID" 2>/dev/null || true
    wait "$RENDER_SPIN_PID" 2>/dev/null || true
    if [[ -n "${RENDER_SPIN_FLAG:-}" && -e "$RENDER_SPIN_FLAG" ]]; then
        printf '\n' >&2
        RENDER_DRAWN=$(( RENDER_DRAWN + 1 ))
        RENDER_TOP=$(( RENDER_TOP + 1 ))
    fi
    [[ -n "${RENDER_SPIN_FLAG:-}" ]] && rm -f "$RENDER_SPIN_FLAG" 2>/dev/null
    [[ -n "${RENDER_SPIN_DETAIL:-}" ]] && rm -f "$RENDER_SPIN_DETAIL" 2>/dev/null
    RENDER_SPIN_PID=""
    RENDER_SPIN_FLAG=""
    RENDER_SPIN_DETAIL=""
    return 0
}

# render_bytes <have> <total> <kb_per_s> — the detail line for a transfer.
# With a total it is a bar, without one it is a plain count that grows. The
# bar appears the moment the size is known and not before, so the one number on
# screen is never a fiction.
_render_bytes() {
    local have="${1:-0}" total="${2:-}" rate="${3:-0}"
    if [[ "$total" =~ ^[0-9]+$ ]] && (( total > 0 )); then
        local frac mb_have mb_total
        frac="$(awk -v h="$have" -v t="$total" 'BEGIN{print h/t}')"
        mb_have="$(awk -v b="$have" 'BEGIN{printf "%.1f", b/1048576}')"
        mb_total="$(awk -v b="$total" 'BEGIN{printf "%.0f", b/1048576}')"
        render_note "$(printf '%s  %s/%s MB · %s MB/s' "$(_render_bar "$frac" 16)" "$mb_have" "$mb_total" "$rate")"
    else
        render_note "$(awk -v b="$have" 'BEGIN{printf "%.1f MB · %s MB/s", b/1048576, '"$rate"'}')"
    fi
    return 0
}

# render_note <detail> — annotate the running step. Free to call repeatedly;
# only the last call before render_done survives.
#
# With no step open it prints instead of swallowing the text: a lib helper
# (tls.sh, backup.sh) can be called outside a numbered step — from a wizard, a
# repair, or `ovm tls` — and its message must not vanish into a step that does
# not exist.
render_note() {
    local last=$(( ${#RENDER_DETAILS[@]} - 1 ))
    if (( last < 0 )); then
        render_line "$1"
        return 0
    fi
    RENDER_DETAILS[$last]="$1"
    # A running spinner reads its detail from a file; updating it here is what
    # makes the running line change instead of sitting on its first value.
    if [[ -n "${RENDER_SPIN_DETAIL:-}" && -n "${RENDER_SPIN_PID:-}" ]]; then
        printf '%s' "$1" > "$RENDER_SPIN_DETAIL" 2>/dev/null || true
    fi
    return 0
}

# render_spin <index> <detail-file> <painted-flag> — animate one line until
# killed. A no-op without a terminal, so a non-TTY run spawns nothing at all.
#
# The detail arrives through a FILE, not through the step arrays. The spinner is
# a background subshell: it inherited a snapshot of RENDER_DETAILS when it
# forked and would otherwise repaint the same text for the whole step, so a
# health check that reports "attempt 7/40" would sit there saying "attempt 1/40".
# Reading a file each frame is what makes a long step show progress.
#
# <painted-flag> lets the parent know whether anything reached the screen: a
# step that failed instantly never painted, and counting a line that is not
# there makes every later repaint drift up one row.
render_spin() {
    [[ "$RENDER_ANIMATE" -eq 1 ]] || return 0
    local idx="$1" dfile="${2:-}" flag="${3:-}"
    local frames="$RENDER_FRAMES"
    local n=${#frames} i=0 detail=""
    while :; do
        detail=""
        [[ -n "$dfile" && -r "$dfile" ]] && detail="$(cat "$dfile" 2>/dev/null)"
        RENDER_DETAILS_SNAPSHOT="$detail"
        _render_spin_line "$idx" "${frames:$(( i % n )):1}" >&2 2>/dev/null || true
        [[ -n "$flag" ]] && : > "$flag" 2>/dev/null || true
        sleep 0.12
        i=$(( i + 1 ))
    done
}

# One spinner frame, on ONE row, forever.
#
# The frame is written without a trailing newline and every iteration starts by
# returning to the start of that row and clearing it. With a newline the cursor
# walks down a row per frame, and after a few seconds the animation is a column
# of stale frames instead of one line that spins — which is exactly what the
# first version did.
#
# RENDER_DRAWN is deliberately untouched: this is a separate process with its
# own copy of that counter, and the parent owns the block's accounting. It
# learns that one extra row exists from the painted-flag file.
_render_spin_line() {
    local idx="$1" frame="$2"
    printf '\r\033[K' >&2 2>/dev/null || true
    _render_step_line "$idx" "$frame" no-newline >&2
    return 0
}

# render_done <detail> [ms] — close the running step as ok. In a terminal it
# rewrites the line in place; everywhere else it appends it once.
render_done() {
    local last=$(( ${#RENDER_LABELS[@]} - 1 ))
    (( last >= 0 )) || return 0
    [[ -n "${1:-}" ]] && RENDER_DETAILS[$last]="$1"
    RENDER_TIMES[$last]="${2:-$(_render_ms_since "$RENDER_NOW")}"
    render_unwatch
    RENDER_DONE=$(( last + 1 ))
    if [[ "$RENDER_ANIMATE" -eq 1 ]]; then
        # Repaint: the step that just finished was the running one, so it now
        # recedes a grey and the block shifts a shade down with it.
        _render_repaint
    else
        _render_step_line "$last" >&2
    fi
    return 0
}

# render_settle — the run is over. Repaints the block one last time with
# everything at the faintest depth, so the card below it is the only thing on
# screen that pulls the eye. A no-op without a terminal, where the block was
# printed once and is already in the scrollback.
render_settle() {
    [[ "$RENDER_ANIMATE" -eq 1 ]] || return 0
    render_unwatch
    RENDER_SETTLE=1
    _render_repaint
    RENDER_SETTLE=0
    return 0
}

# Leave the block in the scrollback and stop painting over it. Called before
# anything else prints, so a card never lands on top of a half-drawn step.
render_flush() { RENDER_DRAWN=0; RENDER_TOP=0; return 0; }

# ── Plain lines ─────────────────────────────────────────────────────────
# Everything that is not a numbered step. One place, so there is exactly one
# answer to "how is ordinary output indented and coloured".

render_line() { _render_out "$*"; _render_cursor_advanced; }
render_blank() { printf '\n' >&2; _render_cursor_advanced; }

# render_ok <text> — a completed thing that is not one of the numbered steps.
# The green check is the same glyph the progress block uses, so "done" looks
# the same everywhere in the installer.
render_ok() {
    printf '  %b%s%b  %s\n' "$GR" "$RENDER_OK" "$NC" "$1" >&2
    _render_cursor_advanced
}

# render_warn <text> — a caveat. Yellow, no glyph: a mid-run warning marker on
# its own line is the thing operators learn to skip, so the colour carries it
# and the text carries the meaning.
render_warn() {
    printf '  %b%s%b\n' "$YL" "$1" "$NC" >&2
    _render_cursor_advanced
}

# Card rows share one label width, so every value starts in the same column.
# 14 is the longest label either card uses ("install name" is 12, "setup key"
# and "not written" are shorter) — wide enough for the node card's labels, and
# not so wide that a short value sits in the middle of the screen.
RENDER_LABEL_W=14

# render_kv <label> <value> — a label/value row.
render_kv() {
    printf '   %b%-*s%b %s\n' "$GY" "$RENDER_LABEL_W" "$1" "$NC" "$2" >&2
    _render_cursor_advanced
}

# render_kv_w <width> <label> <value> — a row in a column this caller computed.
#
# A fixed width only works when every label is shorter than it. At 14, a
# 44-character backup filename printed whole and dropped its date a column right
# of every other row's, so a table of timestamps lined up with nothing. Pass the
# width the set actually needs and the values line up.
render_kv_w() {
    printf '   %b%-*s%b %s\n' "$GY" "$1" "$2" "$NC" "$3" >&2
    _render_cursor_advanced
}

# render_key — a secret. The only thing in the installer that gets bold white,
# because it is the only thing that must not be skimmed past.
render_key() {
    printf '   %b%-*s%b %b%s%b\n' "$GY" "$RENDER_LABEL_W" "$1" "$NC" "$B" "$2" "$NC" >&2
    _render_cursor_advanced
}

# render_url — bold for the same reason as render_key: it gets copied.
render_url() { render_kv "$1" "$(_render_paint "$B" "$2")"; }

# ── Card ───────────────────────────────────────────────────────────────
#
# The finish card fades in line by line, and the secret is passed in second so
# it is on screen before the lines that explain it: an operator who interrupts
# at the second line has the one thing they must not lose.
#
# render_card <title> <secret-label> <secret> <row>... — rows are "label|value".
# The uninstall line is added by render_card_undo, not here, so a caller that
# has no uninstall command does not print a broken one.

render_card() {
    local title="$1" secret_label="$2" secret="$3"; shift 3
    render_settle
    render_flush
    render_blank
    _render_out "$(_render_paint "$B" "$title")"
    render_rule
    [[ -n "$secret_label" ]] && render_key "$secret_label" "$secret"
    local row
    for row in "$@"; do
        [[ "$row" == *"|"* ]] || continue
        render_kv "${row%%|*}" "${row#*|}"
    done
    render_blank
    return 0
}

# render_card_undo <url> — the removal command, spelled out in full. An operator
# who wants it later is reading a log or a terminal scrollback, not the source.
render_card_undo() {
    render_blank
    _render_out "$(printf '%buninstall:%b %s' "$GY" "$NC" "$1")"
    render_blank
}

# ── Failure ────────────────────────────────────────────────────────────
#
# One line, then one way out. The gap between what was promised and what
# happened is the thing an operator actually needs, and it fits in a line — the
# rest of the old error prose was the same information at four times the length.

render_fail() {  # render_fail <label> <cause>
    local last=$(( ${#RENDER_LABELS[@]} - 1 ))
    if (( last >= 0 )); then
        render_unwatch
        RENDER_TIMES[$last]="${RENDER_TIMES[$last]:-$(_render_ms_since "$RENDER_NOW")}"
        RENDER_DONE=$(( last + 1 ))
    fi
    render_settle
    render_flush
    printf '  %b%s%b %b%s%b  %s\n' "$RD" "$RENDER_BAD" "$NC" "$B" "$1" "$NC" "$2" >&2
    return 0
}

render_next() {  # render_next <how to look> <how to remove>
    printf '  %bnext%b  %s · uninstall: %s\n' "$GY" "$NC" "$1" "$2" >&2
    _render_cursor_advanced
    return 0
}

# ── Ask ─────────────────────────────────────────────────────────────────
# Styled to match the menu: the default is bold, the label is dim, and the
# colon sits after the bracket so the answer's position never moves.

render_ask() {  # render_ask <label> <default>
    printf '  %b%s%b %b[%s]%b: ' "$GY" "$1" "$NC" "$B" "$2" "$NC" >&2
}

render_ask_note() { _render_out "$(_render_paint "$GY" "$1")"; }

# ==========================================================================
# prompt.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
# Pure helpers only.
# Interactive prompts, menus, spinners.

# Interactive only when -y was not passed and a terminal is reachable: `curl |
# bash` has no stdin TTY, though /dev/tty usually works.
can_prompt() {
    [[ "${YES:-0}" -eq 0 ]] || return 1
    [[ -t 0 ]] && return 0
    # /dev/tty can exist but be unopenable (containers, detached shells):
    # actually try to open it, or prompts silently fall back to defaults.
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Interactive menu only: scripts and pipes take the subcommand path instead.
has_tty() {
    [[ -t 0 ]] && return 0
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Reads stdin, so callers redirect /dev/tty when needed.
_masked_read() {
    local buf="" ch
    while IFS= read -rsn1 ch; do
        case "$ch" in
            ""|$'\n'|$'\r') break ;;
            $'\x7f'|$'\b')
                if [[ -n "$buf" ]]; then buf="${buf%?}"; printf '\b \b' >&2; fi ;;
            *) buf+="$ch"; printf '*' >&2 ;;
        esac
    done
    printf '\n' >&2
    printf '%s' "$buf"
}

_read_reply() {  # hidden? → prints the line on stdout
    local hidden="${1:-}" buf=""
    if [[ -t 0 ]]; then
        if [[ "$hidden" == "h" ]]; then _masked_read; return 0; fi
        read -r buf
    elif [[ -e /dev/tty && -r /dev/tty ]]; then
        if [[ "$hidden" == "h" ]]; then _masked_read </dev/tty; return 0; fi
        read -r buf </dev/tty
    else
        return 1
    fi
    printf '%s' "$buf"
}

ask() {  # ask <label> <default> [hidden]
    local label="$1" default="$2" hidden="${3:-}" val=""
    if can_prompt; then
        render_ask "$label" "$default"
        val="$(_read_reply "$hidden")" || true
    fi
    [[ -n "$val" ]] || val="$default"
    printf '%s' "$val"
}

# confirm <question> [default] — default is y, which is what a run with no
# gets. A destructive caller must pass n: answering "yes" on nobody's behalf
# made `ovm rollback` replace the running install from a cron job or pipeline.
confirm() {
    [[ "${YES:-0}" -eq 1 ]] && return 0
    local default="${2:-y}"
    if ! can_prompt; then
        [[ "$default" == "y" ]]
        return
    fi
    render_ask "$1" "$([ "$default" = y ] && printf 'Y/n' || printf 'y/N')"
    local c=""
    c="$(_read_reply)" || true
    [[ ! "$c" =~ ^[Nn]$ ]]
}

# Explicit-yes prompt (default NO): non-interactive runs keep the safe answer.
confirm_no() {
    [[ "${YES:-0}" -eq 1 ]] && return 1
    can_prompt || return 1
    render_ask "$1" "y/N"
    local c=""
    c="$(_read_reply)" || true
    [[ "$c" =~ ^[Yy]$ ]]
}

# confirm_word <question> <word> — the destructive default. `uninstall` asks
# for the word "purge" before it deletes a database, and Enter keeps the data.
# A plain y/N made the destructive answer one stray keystroke away from the
# default, which is the wrong way round.
confirm_word() {
    local question="$1" word="$2" reply=""
    [[ "${YES:-0}" -eq 1 ]] && return 0
    can_prompt || return 1
    render_ask "$question" "press enter to keep it"
    reply="$(_read_reply)" || true
    [[ "$reply" == "$word" ]]
}

run_step() {
    local label="$1"; shift
    "$@" >/dev/null 2>&1 &
    local pid=$! rc=0
    render_watch
    wait "$pid" 2>/dev/null || rc=$?
    if [[ $rc -eq 0 ]]; then
        render_done ""
        return 0
    fi
    render_fail "$label" "command failed with status $rc"
    return 1
}

# Menu. The drawing and the keystrokes belong to render.sh; this is the
# ask-side wrapper for callers that just want a tag back.
#
# The old version preferred whiptail when it happened to be installed, which
# meant the same menu rendered two completely different ways on two different
# boxes. One renderer, so the pointer, the number and the arrow always agree.
tui_select() { render_menu "$@"; }

# ==========================================================================
# env.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
# Pure helpers only.
# Atomic .env read/write.

env_get() {  # env_get FILE KEY → value (empty when missing)
    grep -E "^$2=" "$1" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true
}

env_set() {  # env_set FILE KEY VALUE — rewrite one line, atomically
    local file="$1" key="$2" value="$3" tmp
    tmp="$(mktemp)" || die "Could not stage $file"
    awk -v k="$key" -v v="$value" '
        BEGIN { done = 0 }
        $0 ~ "^" k "=" { if (!done) { print k "=" v; done = 1; next } }
        { print }
        END { if (!done) print k "=" v }
    ' "$file" > "$tmp" || { rm -f "$tmp"; die "Could not update $file"; }
    cat "$tmp" > "$file" || { rm -f "$tmp"; die "Could not update $file"; }
    rm -f "$tmp"
}

# ==========================================================================
# system.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
# Pure helpers only.
# Services, firewall, health, URLs.

# systemd waits up to TimeoutStopSec (90s default) for a stuck service, which
# operators read as a frozen installer. Bound the wait, then force the unit.
systemctl_bounded() {  # systemctl_bounded stop|restart|<other systemctl verb> [unit]
    local action="$1" unit="${2:-$SYSTEMD_SERVICE}" timeout="${OVM_STOP_TIMEOUT:-20}"
    case "$action" in
        stop)
            timeout "$timeout" systemctl stop "$unit" >/dev/null 2>&1 && return 0
            render_warn "Service stop timed out after ${timeout}s — force-killing $unit"
            systemctl kill -s KILL "$unit" >/dev/null 2>&1 || true
            return 0
            ;;
        restart)
            timeout "$timeout" systemctl restart "$unit" >/dev/null 2>&1 && return 0
            render_warn "Service restart timed out after ${timeout}s — force-restarting $unit"
            systemctl kill -s KILL "$unit" >/dev/null 2>&1 || true
            sleep 1
            systemctl start "$unit" >/dev/null 2>&1 || render_warn "Could not start $unit — check logs"
            return 0
            ;;
        *)
            # Anything else is a real systemctl verb, run as asked.
            #
            # This used to fall through to the restart branch, which meant
            # `systemctl_bounded daemon-reload` silently *restarted the
            # service* and never reloaded anything. The damage was not
            # theoretical: a 1.0.27 update failed verification, the failover
            # put the old unit back on disk, called this to reload it — and
            # systemd went on running the migrated unit, so the box was left
            # trying to start as a service account against a root-owned tree
            # and would not come up until someone ran daemon-reload by hand.
            timeout "$timeout" systemctl "$action" "$unit" >/dev/null 2>&1
            return $?
            ;;
    esac
}

# This box's public address, as Let's Encrypt would see it. Tried first from a
# public resolver (the address the internet routes to), then from the local
# interfaces, filtered to globally routable ranges.
public_ip() {
    local ip
    for ip in $(curl -fsS --max-time 3 https://api.ipify.org 2>/dev/null) \
              $(curl -fsS --max-time 3 https://ifconfig.me/ip 2>/dev/null); do
        [[ "$ip" =~ ^[0-9a-fA-F:.]+$ ]] && { printf '%s' "$ip"; return 0; }
    done
    for ip in $(hostname -I 2>/dev/null); do
        case "$ip" in
            *:*) continue ;;                       # skip IPv6: LE and the panel's TLS paths are v4 here
            127.*|10.*|192.168.*|169.254.*) continue ;;
            172.1[6-9].*|172.2[0-9].*|172.3[01].*) continue ;;   # 172.16/12 is private
            *) printf '%s' "$ip"; return 0 ;;
        esac
    done
    return 1
}

# Every routable address on this host, for a box with more than one. The
# Let's Encrypt prompt names them so an operator with several IPs can pick the
# one the certificate should carry instead of guessing.
public_ips() {
    local ip out=""
    for ip in $(hostname -I 2>/dev/null); do
        case "$ip" in
            *:*) continue ;;
            127.*|10.*|192.168.*|169.254.*) continue ;;
            172.1[6-9].*|172.2[0-9].*|172.3[01].*) continue ;;
            *) out+="$ip " ;;
        esac
    done
    printf '%s' "${out% }"
}

# Does this string look like a bare IP rather than a hostname? Decides whether
# a Let's Encrypt request is the short-lived IP kind or the ordinary domain one,
# so one free-text prompt can serve both.
is_ip_literal() {
    [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || [[ "$1" == *:* ]]
}

# Resolve and report, so a certificate attempt is not spent discovering a
# misconfigured record. Prints "<ip>" on success, empty otherwise.
resolve_host() {
    local host="$1"
    getent hosts "$host" 2>/dev/null | awk '{ print $1; exit }' || true
}

open_firewall_port() {
    local port="$1"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow "$port/tcp" >/dev/null 2>&1 && render_ok "UFW allowed ${port}/tcp"
    elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null 2>&1 \
            && firewall-cmd --reload >/dev/null 2>&1 \
            && render_ok "firewalld allowed ${port}/tcp"
    fi
}

wait_health() {
    local url="$1" tries="${2:-30}" i
    for i in $(seq 1 "$tries"); do
        curl -fskS -o /dev/null --max-time 3 "$url" 2>/dev/null && return 0
        sleep 1
    done
    return 1
}

# wait_health_live — wait_health, but the running step's detail counts the
# attempts.
#
# The old wait was forty seconds of complete silence, which is indistinguishable
# from a hang and is the single most-reported "is this thing stuck?" moment in
# an install. Each poll updates the step line, so the operator sees it is
# trying and how long it has been trying.
wait_health_live() {  # wait_health_live <url> <tries>
    local url="$1" tries="${2:-30}" i ms=0 code=""
    for (( i = 1; i <= tries; i++ )); do
        code="$(curl -fskS -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || true)"
        if [[ "$code" == "200" ]]; then
            render_note "200 in ${ms}ms"
            return 0
        fi
        render_note "waiting · attempt ${i}/${tries}"
        sleep 1
        ms=$(( ms + 1000 ))
    done
    return 1
}

scheme_of() { [[ "${TLS_MODE:-none}" == "none" ]] && printf 'http' || printf 'https'; }

panel_url() {
    local host scheme
    host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$host" ]] || host="127.0.0.1"
    scheme="$(scheme_of)"
    if [[ -n "${PATHPREFIX:-}" ]]; then
        printf '%s://%s:%s/%s/' "$scheme" "$host" "$PORT" "$PATHPREFIX"
    else
        printf '%s://%s:%s/' "$scheme" "$host" "$PORT"
    fi
}

port_in_use() {
    command -v ss >/dev/null 2>&1 || return 1
    # `found=1` + `exit !found`, not `exit 0`: awk still runs END after an
    # `exit 0` in a rule, so `END { exit 1 }` always won and this function
    # reported every port as free. Which meant the "port already in use"
    # guard never fired — not for a busy install port, and not for the port 80
    # check before Let's Encrypt.
    ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p { found = 1 } END { exit !found }'
}

# ==========================================================================
# backup.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
# Pure helpers only.
# Safety backups + code snapshots for update failover.

backup_dir() {
    local src="$1" label="$2"
    [[ -d "$src" ]] || return 0
    mkdir -p /var/backups
    local stamp base file
    stamp="$(date +%Y%m%d-%H%M%S)"
    base="$(basename "$src")"
    file="/var/backups/${label}-${base}-${stamp}.tar.gz"
    render_note "Backup ${label} → $file"
    tar -czf "$file" -C "$(dirname "$src")" "$base" 2>/dev/null \
        || render_warn "Backup failed for $src — continuing"
    # render_ok, not the retired `step` — which was still being called here
    # after the vocabulary moved, and got away with it because the test meant
    # to catch exactly this was silently failing to match `then step`.
    if [[ -f "$file" ]]; then render_ok "Backup  $file"; fi
    return 0
}

# Code-tree snapshots for update failover: keep the newest $keep.
snapshot_code() {  # snapshot_code <dir> <label> [keep=2] → prints the file
    local dir="$1" label="$2" keep="${3:-2}"
    [[ -d "$dir" ]] || die "Not installed ($dir missing)"
    mkdir -p /var/backups
    local stamp base file
    stamp="$(date +%Y%m%d-%H%M%S)"
    base="$(basename "$dir")"
    file="/var/backups/${label}-code-${base}-${stamp}.tar.gz"
    tar -czf "$file" -C "$(dirname "$dir")" "$base" 2>/dev/null \
        || die "Could not snapshot $dir"
    render_ok "Snapshot  $file"
    local old
    old="$(ls -t /var/backups/${label}-code-*.tar.gz 2>/dev/null | tail -n +$((keep + 1)) || true)"
    if [[ -n "$old" ]]; then
        # shellcheck disable=SC2086
        rm -f $old
    fi
    printf '%s' "$file"
}

latest_snapshot() {  # latest_snapshot <label> → prints newest code snapshot or empty
    ls -t /var/backups/"$1"-code-*.tar.gz 2>/dev/null | head -1 || true
}

# ==========================================================================
# tls.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
# Pure helpers only.
# TLS: self-signed, acme.sh, Let's Encrypt, setup dispatch.

_is_docker_install() {  # MODE when the installer set it, else the compose file's presence
    if [[ -n "${MODE:-}" ]]; then
        [[ "$MODE" == "docker" ]]
    else
        [[ -n "${COMPOSE_FILE:-}" && -f "${COMPOSE_FILE:-}" ]]
    fi
}

secure_tls_files() {
    local key="$1" cert="$2"
    if [[ -f "$key" ]]; then
        # Who reads this key depends on the deployment, and getting it wrong is
        # not cosmetic: the key becomes unreadable by whoever serves TLS and
        # the panel dies on its next start. Docker reads it as the image's
        # appuser (uid 1000) through a read-only mount, so ownership is what
        # lets it in. The native panel is a service account that reads through
        # the group, and nothing on this path runs as root on its behalf —
        # chowning to 1000 unconditionally is what made `ovm https --self`
        # restart straight into a PermissionError from inside uvicorn.
        if _is_docker_install; then
            chown 1000:1000 "$key" 2>/dev/null || true
            chmod 600 "$key"
        else
            chgrp "${PANEL_USER:-ovmanager}" "$key" 2>/dev/null || true
            chmod 640 "$key"
        fi
    fi
    [[ -f "$cert" ]] && chmod 644 "$cert"
    return 0
}

_existing_tls_pair_usable() {  # <key> <cert> → 0 when an intact, unexpired pair is already there
    local key="$1" cert="$2" key_pub cert_pub
    [[ -s "$key" && -s "$cert" ]] || return 1
    openssl x509 -noout -checkend 0 -in "$cert" >/dev/null 2>&1 || return 1
    key_pub="$(openssl pkey -pubout -in "$key" 2>/dev/null | openssl sha256)" || return 1
    cert_pub="$(openssl x509 -pubkey -noout -in "$cert" 2>/dev/null | openssl sha256)" || return 1
    [[ -n "$key_pub" && "$key_pub" == "$cert_pub" ]]
}

generate_self_signed() {
    render_note "Self-signed certificate…"
    local key="/etc/ssl/self-signed/privkey.pem"
    local cert="/etc/ssl/self-signed/fullchain.pem"
    mkdir -p /etc/ssl/self-signed
    # /etc/ssl/self-signed is shared with OVNode on the same host: regenerating
    # replaces the node's identity and invalidates the certificate the panel
    # pinned for it, so an intact pair is kept and only its permissions are
    # re-asserted. `ovm https --self` is the explicit way to ask for a new one.
    if [[ "${TLS_REGENERATE:-0}" != "1" ]] && _existing_tls_pair_usable "$key" "$cert"; then
        TLS_KEY="$key"
        TLS_CERT="$cert"
        secure_tls_files "$key" "$cert"
        render_ok "Certificate  $TLS_CERT  (existing — reused)"
        return 0
    fi
    local cn; cn="$(hostname -I 2>/dev/null | awk '{print $1}')"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$key" \
        -out "$cert" \
        -subj "/C=US/ST=Local/L=Local/O=OVManager/CN=${cn}" >/dev/null 2>&1
    secure_tls_files "$key" "$cert"
    TLS_KEY="$key"
    TLS_CERT="$cert"
    render_ok "Certificate  $TLS_CERT"
}

ACME_INSTALL_VERSION="3.1.1"

# Download a third-party installer to a file and run it, instead of piping
# curl straight into a root shell. Not a signature check — it stops a corrupt
# or truncated response and an obvious redirect stub, not a compromised vendor,
# which is why package-manager installs are tried first.
fetch_and_run_installer() {  # url expected-prefix tmpname
    local url="$1" prefix="$2" name="$3" script first rc
    script="$(mktemp "/tmp/${name}.XXXXXX.sh")"
    if ! curl -fsSL --max-time 60 -o "$script" -- "$url"; then
        rm -f "$script"
        return 1
    fi
    first="$(head -c 200 "$script" 2>/dev/null || true)"
    case "$first" in
        *"$prefix"*) : ;;
        *) rm -f "$script"; return 1 ;;
    esac
    sh "$script" >/dev/null 2>&1
    rc=$?
    rm -f "$script"
    return $rc
}

ensure_acme() {
    [[ -x "$HOME/.acme.sh/acme.sh" ]] && return 0
    render_note "Installing acme.sh…"
    # get.acme.sh is a moving target; the tagged release is not, and this
    # install runs as root.
    fetch_and_run_installer \
        "https://raw.githubusercontent.com/acmesh-official/acme.sh/${ACME_INSTALL_VERSION}/acme.sh" \
        "#!/usr/bin/env sh" "acme-install" \
        || fetch_and_run_installer \
        "https://raw.githubusercontent.com/acmesh-official/acme.sh/${ACME_INSTALL_VERSION}/acme.sh" \
        "#!/bin/sh" "acme-install" \
        || die "Failed to install acme.sh — install certbot instead: apt install certbot"
}

issue_lets_encrypt() {
    local domain="$1" is_ip="$2"
    ensure_acme
    local email="acme-$(openssl rand -hex 4)@example.com"
    local outdir="/etc/letsencrypt/$domain"
    mkdir -p "$outdir"
    if [[ -f "$outdir/fullchain.pem" ]]; then
        local expiry days_left=0
        expiry="$(openssl x509 -enddate -noout -in "$outdir/fullchain.pem" 2>/dev/null | cut -d= -f2)"
        days_left=$(( ($(date -d "$expiry" +%s 2>/dev/null || echo 0) - $(date +%s)) / 86400 ))
        if (( days_left > 7 )); then
            render_ok "Existing certificate valid ${days_left}d"
            return 0
        fi
        render_warn "Certificate expires in ${days_left}d — renewing"
    fi
    local extra_args=()
    if [[ "$is_ip" == "1" ]]; then
        render_note "Short-lived certificate for IP $domain…"
        extra_args=(--certificate-profile shortlived --days 6)
    else
        render_note "Let's Encrypt for $domain…"
    fi
    "$HOME/.acme.sh/acme.sh" --issue -d "$domain" --standalone "${extra_args[@]}" \
        --accountemail "$email" >/dev/null 2>&1 \
        || die "Failed to issue Let's Encrypt certificate for $domain"
    "$HOME/.acme.sh/acme.sh" --install-cert -d "$domain" \
        --key-file "$outdir/privkey.pem" \
        --fullchain-file "$outdir/fullchain.pem" \
        --reloadcmd "if [ -f $COMPOSE_FILE ]; then chown 1000:1000 $outdir/privkey.pem 2>/dev/null || true; chmod 600 $outdir/privkey.pem; else chgrp ${PANEL_USER:-ovmanager} $outdir/privkey.pem 2>/dev/null || true; chmod 640 $outdir/privkey.pem; fi; chmod 644 $outdir/fullchain.pem; systemctl restart $SYSTEMD_SERVICE >/dev/null 2>&1 || docker restart ovmanager >/dev/null 2>&1 || true" \
        >/dev/null 2>&1 || die "Failed to install certificate to $outdir"
    # Renewals re-apply permissions through the reloadcmd above, which has to
    # branch the same way this function does — it runs later, on its own, long
    # after these variables are gone, so it cannot call back into here.
    secure_tls_files "$outdir/privkey.pem" "$outdir/fullchain.pem"
    render_ok "Certificate  $outdir"
}

setup_tls() {
    case "$TLS_MODE" in
        le)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
            issue_lets_encrypt "$TLS_DOMAIN" "0"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        le-ip)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it (or --tls 1 for now)"
            TLS_DOMAIN="${TLS_DOMAIN:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
            issue_lets_encrypt "$TLS_DOMAIN" "1"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        self) generate_self_signed ;;
        custom)
            [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom key/cert not found: $TLS_KEY $TLS_CERT"
            local out="/etc/letsencrypt/${TLS_DOMAIN:-panel}"
            mkdir -p "$out"
            cp "$TLS_KEY" "$out/privkey.pem"
            cp "$TLS_CERT" "$out/fullchain.pem"
            secure_tls_files "$out/privkey.pem" "$out/fullchain.pem"
            TLS_KEY="$out/privkey.pem"; TLS_CERT="$out/fullchain.pem"
            ;;
        none) ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
}

# ==========================================================================
# policy.sh
# ==========================================================================
#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Inline helper block. install.sh and manager.sh each carry a copy of this,
# kept byte-identical by tests/test_lib_sourcing.py.
# Pure helpers only.
# Password policy + release artifact URLs.

# Mirrors the panel's boot-time validation (backend/config.py): >= 8 chars
# and no placeholder-looking values.
admin_password_problem() {
    local pass="$1" lowered
    [[ -n "$pass" ]] || { printf 'must not be empty'; return 0; }
    [[ "$pass" != *$'\n'* && "$pass" != *$'\r'* ]] \
        || { printf 'must be a single line'; return 0; }
    [[ ${#pass} -ge 8 ]] \
        || { printf 'must be at least 8 characters (the panel requires >= 8)'; return 0; }
    lowered="${pass,,}"
    case "$lowered" in
        *change-me*|*changeme*|*change_me*|*password123*|*admin123*)
            printf 'looks like a placeholder — choose a strong password (the panel rejects change-me/changeme/change_me/password123/admin123)' ;;
    esac
    return 0
}

validate_admin_password() {
    local problem
    problem="$(admin_password_problem "$1")"
    [[ -z "$problem" ]] || die "Admin password $problem"
}

# Max 3 tries, then fail fast — never install a password the panel rejects.
prompt_validate_admin_password() {
    local tries=0 problem
    while (( tries < 3 )); do
        problem="$(admin_password_problem "$ADMIN_PASS")"
        if [[ -z "$problem" ]]; then
            render_ok "Password set (hidden while typing)"
            return 0
        fi
        render_warn "Weak password: $problem"
        tries=$((tries + 1))
        [[ $tries -lt 3 ]] && ADMIN_PASS="$(ask "Admin password" "" "h")"
    done
    die "No acceptable password after 3 tries (need >= 8 characters, not a common word)"
}

# ── Owner claim key ────────────────────────────────────────────────────
# Not the credential: the panel re-reads the file on every claim attempt and
# deletes it once the claim succeeds, so regenerating one is safe.
claim_key_path() { printf '%s/owner-claim.key' "$DATA_DIR"; }

# mint_claim_key → writes the key 0600 and prints it (stdout only).
#
# Ownership follows the data dir: the service account natively, uid 1000 under
# Docker — a key those users cannot read is a key that cannot be claimed.
mint_claim_key() {
    local path key owner=""
    path="$(claim_key_path)"
    key="$(rand_hex | cut -c1-32)"
    mkdir -p "$DATA_DIR"
    ( umask 077; printf '%s\n' "$key" > "$path" ) || die "Could not write $path"
    chmod 600 "$path" 2>/dev/null || true
    if [[ "${MODE:-}" == "docker" || ( -z "${MODE:-}" && -f "$DATA_DIR/ovmanager-compose.yml" ) ]]; then
        owner="1000:1000"
    elif [[ -n "${PANEL_USER:-}" ]]; then
        owner="$PANEL_USER:$PANEL_USER"
    fi
    [[ -n "$owner" ]] && chown "$owner" "$path" 2>/dev/null || true
    printf '%s\n' "$key"
}

release_base() { printf '%s-%s' "$APP_SLUG" "$VERSION"; }

release_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.tar.gz' \
        "$REPO" "$VERSION" "$(release_base)"
}

release_checksum_url() {
    printf 'https://github.com/%s/releases/download/v%s/%s.sha256' \
        "$REPO" "$VERSION" "$(release_base)"
}


# Pinpoint trap: any future failure (real or environmental) reports the exact
# command and line instead of surfacing as a mystery message elsewhere.
trap 'render_warn "Command failed near line $LINENO (running: ${BASH_COMMAND:0:80})"' ERR

# ── Flags (defaults) ───────────────────────────────────────────────────
# Three flags: -y/--yes, --docker, -h/--help. Everything else that used to be
# a flag is an OVM_* environment variable (see apply_env).
PORT="" PATHPREFIX="" ADMIN_USER=""
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
PUBLIC_URL="" MODE="" ACTION="install" PIN=""
YES=0 PURGE=0 DRY=0 PATH_SET=0
CLI_GIVEN=0 CLAIM_KEY=""
OPERATION_LOCK="${DATA_DIR}/.operation.lock"
OPERATION_LOCK_HELD=0
UPDATE_STATE="${DATA_DIR}/update-state.json"
UPDATE_MARKER="${DATA_DIR}/update-maintenance"
UPDATE_STAGE="$(dirname "$INSTALL_DIR")/.${APP_SLUG}.staging"
UPDATE_PREVIOUS="$(dirname "$INSTALL_DIR")/.${APP_SLUG}.previous"

update_state() {
    local phase="$1" from="${2:-unknown}" target="${3:-$VERSION}" backup="${4:-}"
    mkdir -p "$DATA_DIR"
    python3 - "$UPDATE_STATE" "$phase" "$from" "$target" "$backup" <<'PY'
import json, os, sys, tempfile, time
path, phase, old, target, backup = sys.argv[1:]
data = {"phase": phase, "from_version": old, "to_version": target,
        "safety_backup": backup or None, "updated_at": int(time.time()), "pid": os.getppid()}
fd, tmp = tempfile.mkstemp(prefix=".update-state-", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, 0o600); os.replace(tmp, path)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY
}

# The owner is claimed in the browser with a one-time key, not created here:
# a key can be reprinted at will (ovm auth key) because it is not the
# credential, so nothing stolen from scrollback or a file is reusable.
# mint_claim_key lives in scripts/lib/policy.sh.
issue_claim_key() {
    CLAIM_KEY="$(mint_claim_key)" || render_warn "Could not write the claim key — run: ovm auth key"
    return 0
}

update_safety_backup() {
    local keep=10 path
    # The installed tree's transactional backup first; any failure (missing
    # module, older signature) falls back to a legacy bundle so old releases
    # can still update.
    if [[ "$MODE" == "docker" ]]; then
        if path="$(docker exec ovmanager /app/.venv/bin/python -c \
            "from backend.routers.maintenance import create_panel_backup; p=create_panel_backup(${keep}, label='pre-update'); print(p or '')" 2>/dev/null)"; then
            # The backup is created through the /app/data bind mount. Journal the
            # host path so reboot recovery can verify and restore it.
            printf '%s\n' "${path/#\/app\/data/$DATA_DIR}"
            return 0
        fi
    else
        if path="$( ( cd "$INSTALL_DIR" && .venv/bin/python -c \
            "from backend.routers.maintenance import create_panel_backup; p=create_panel_backup(${keep}, label='pre-update'); print(p or '')" 2>/dev/null) )"; then
            printf '%s\n' "$path"
            return 0
        fi
    fi
    render_warn "Installed release lacks transactional backups — legacy safety bundle"
    # Installed release predates transactional backups: build an equivalent
    # .ovmbak with stdlib python. restore_update_database consumes both
    # variants unchanged.
    legacy_safety_bundle "${1:-unknown}" || return 1
}

legacy_safety_bundle() {
    local app_version="$1" backup_dir="${DATA_DIR}/backups"
    [[ -f "${DATA_DIR}/ovmanager.db" ]] || return 0
    mkdir -p "$backup_dir" && chmod 700 "$backup_dir"
    python3 - "$DATA_DIR" "$backup_dir" "$app_version" <<'PY' || return 1
import hashlib, json, os, sqlite3, sys, tarfile, tempfile
from datetime import datetime, timezone
data_dir, backup_dir, app_version = sys.argv[1], sys.argv[2], sys.argv[3]
src = os.path.join(data_dir, "ovmanager.db")
con = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
try:
    row = con.execute("PRAGMA quick_check").fetchone()
finally:
    con.close()
if not row or row[0] != "ok":
    raise SystemExit("source database integrity failed")
fd, snap = tempfile.mkstemp(prefix=".ovmanager-snapshot-", suffix=".db", dir=backup_dir)
os.close(fd); os.chmod(snap, 0o600)
s = sqlite3.connect("file:%s?mode=ro" % src, uri=True)
d = sqlite3.connect(snap)
try:
    s.backup(d)
finally:
    d.close(); s.close()
digest = hashlib.sha256()
with open(snap, "rb") as f:
    for chunk in iter(lambda: f.read(1048576), b""):
        digest.update(chunk)
digest = digest.hexdigest()
now = datetime.now(timezone.utc)
manifest = {"format": "ovmanager-backup", "format_version": 1,
            "app_version": app_version, "created_at": now.isoformat(),
            "database": "panel.db", "database_sha256": digest}
stamp = now.strftime("%Y%m%d_%H%M%S")
final = os.path.join(backup_dir, "ovmanager-pre-update-%s-v1.ovmbak" % stamp)
fd, tmp = tempfile.mkstemp(prefix=".ovmanager-backup-", suffix=".part", dir=backup_dir)
os.close(fd); os.chmod(tmp, 0o600)
try:
    with tempfile.TemporaryDirectory(prefix="ovmanager-bundle-") as stage:
        with open(os.path.join(stage, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, sort_keys=True, indent=2); f.write("\n")
        with open(os.path.join(stage, "checksums.sha256"), "w", encoding="ascii") as f:
            f.write("%s  panel.db\n" % digest)
        with tarfile.open(tmp, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(snap, arcname="panel.db", recursive=False)
            archive.add(os.path.join(stage, "manifest.json"), arcname="manifest.json", recursive=False)
            archive.add(os.path.join(stage, "checksums.sha256"), arcname="checksums.sha256", recursive=False)
    with tarfile.open(tmp, "r:gz") as archive:
        names = {m.name for m in archive.getmembers() if m.isfile()}
        if names != {"panel.db", "manifest.json", "checksums.sha256"}:
            raise SystemExit("bundle verification failed")
        data = archive.extractfile("panel.db").read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit("bundle checksum mismatch")
    os.replace(tmp, final); os.chmod(final, 0o600)
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
    try: os.unlink(snap)
    except FileNotFoundError: pass
print(final)
PY
    # Retention for legacy pre-update bundles (backend prunes only its own).
    ls -t "$backup_dir"/ovmanager-pre-update-*.ovmbak 2>/dev/null | tail -n +11 | xargs -r rm -f
    return 0
}

# True when the live database no longer matches the safety bundle (schema
# version): the candidate migrated it, so failover must restore. Matching
# versions mean it never migrated and the restore is skipped, and a
# missing/unreadable live database also requests a restore.
# Version reported by the candidate. Native: loopback /health discloses it.
# Docker: host-side requests never see a version (loopback-only disclosure),
# so read it from inside the container — its filesystem IS the staged image,
# and wait_health already proved the process answers.
candidate_version() {
    if [[ "$MODE" == "docker" ]]; then
        docker exec ovmanager /app/.venv/bin/python -c \
            "from backend.version import __version__; print(__version__)" 2>/dev/null || true
    else
        curl -fskS --max-time 5 "${scheme}://127.0.0.1:${PORT}/health" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version",""))' 2>/dev/null || true
    fi
}

db_restore_needed() {
    python3 - "$1" "${DATA_DIR}/ovmanager.db" <<'PY'
import os, sqlite3, sys, tarfile, tempfile
bundle, live = sys.argv[1], sys.argv[2]
def version(path):
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
try:
    live_version = version(live)
except Exception:
    raise SystemExit(0)
with tarfile.open(bundle, "r:gz") as tf:
    data = tf.extractfile("panel.db").read()
fd, tmp = tempfile.mkstemp(prefix=".update-compare-")
try:
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    bundle_version = version(tmp)
finally:
    os.unlink(tmp)
raise SystemExit(0 if bundle_version != live_version else 1)
PY
}

restore_update_database() {
    local bundle="$1" db="${2:-${DATA_DIR}/ovmanager.db}"
    [[ -f "$bundle" ]] || return 1
    python3 - "$bundle" "$db" <<'PY'
import hashlib, json, os, tarfile, tempfile, sys
bundle, db = sys.argv[1:]
with tarfile.open(bundle, "r:gz") as tf:
    names = {m.name for m in tf.getmembers() if m.isfile()}
    if names != {"panel.db", "manifest.json", "checksums.sha256"}:
        raise SystemExit("unsafe update backup")
    manifest = json.load(tf.extractfile("manifest.json"))
    checksum_line = tf.extractfile("checksums.sha256").read().decode("ascii").strip()
    data = tf.extractfile("panel.db").read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != manifest.get("database_sha256") or checksum_line != f"{digest}  panel.db":
        raise SystemExit("update backup checksum mismatch")
parent = os.path.dirname(db); fd, tmp = tempfile.mkstemp(prefix=".update-rollback-", dir=parent)
try:
    try:
        current = os.stat(db); mode = current.st_mode & 0o777; owner = (current.st_uid, current.st_gid)
    except FileNotFoundError:
        mode = 0o600; owner = None
    with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, mode)
    if owner is not None: os.chown(tmp, *owner)
    os.replace(tmp, db)
    for suffix in ("-wal", "-shm"):
        try: os.unlink(db + suffix)
        except FileNotFoundError: pass
finally:
    try: os.unlink(tmp)
    except FileNotFoundError: pass
PY
}

operation_begin() {
    local name="$1" owner=""
    mkdir -p "$DATA_DIR"
    if ! mkdir "$OPERATION_LOCK" 2>/dev/null; then
        owner="$(cat "$OPERATION_LOCK/pid" 2>/dev/null || true)"
        if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
            render_warn "Removing stale operation lock from process $owner"
            rm -rf "$OPERATION_LOCK"
            mkdir "$OPERATION_LOCK" || die "Another maintenance operation is running"
        else
            die "Another maintenance operation is running${owner:+ (process $owner)}. Try again later."
        fi
    fi
    printf '%s\n' "$$" > "$OPERATION_LOCK/pid"
    printf '%s\n' "$name" > "$OPERATION_LOCK/action"
    chmod 700 "$OPERATION_LOCK"
    OPERATION_LOCK_HELD=1
}

operation_end() {
    [[ "$OPERATION_LOCK_HELD" -eq 1 ]] || return 0
    rm -rf "$OPERATION_LOCK"
    OPERATION_LOCK_HELD=0
}

trap operation_end EXIT

[[ "${CI:-}" == "true" || "${NONINTERACTIVE:-}" == "1" ]] && YES=1

# A release version: MAJOR.MINOR.PATCH, optionally with a pre-release or build
# suffix (1.2.3-rc1, 1.2.3+build5), and an optional leading v. The tag it
# resolves to is "v" + this (see release_url), so both spellings work.
valid_release_version() {
    [[ "$1" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]
}

# ── OS / deps ──────────────────────────────────────────────────────────
detect_os() {
    if [[ -f /etc/os-release ]]; then
        # /etc/os-release defines its own VERSION — keep the app version.
        local _app_version="$VERSION"
        # shellcheck disable=SC1091
        . /etc/os-release
        VERSION="$_app_version"
        OS_ID="${ID:-}"; OS_NAME="${PRETTY_NAME:-$OS_ID}"
    else
        die "Unsupported OS — no /etc/os-release."
    fi
    case "$OS_ID" in
        debian|ubuntu) PKG_UPDATE="apt-get update -qq"; PKG_INSTALL="apt-get install -y -qq" ;;
        rhel|centos|rocky|almalinux|fedora)
            if command -v dnf >/dev/null 2>&1; then
                PKG_UPDATE="dnf -q makecache"; PKG_INSTALL="dnf install -y -q"
            else
                PKG_UPDATE="yum -q makecache"; PKG_INSTALL="yum install -y -q"
            fi ;;
        arch)   PKG_UPDATE="pacman -Sy --noconfirm"; PKG_INSTALL="pacman -S --noconfirm" ;;
        alpine) PKG_UPDATE="apk update -q";          PKG_INSTALL="apk add -q" ;;
        *) die "Unsupported distribution: ${OS_ID:-unknown}" ;;
    esac
}

pkg_install() {
    render_note "packages: $*"
    $PKG_UPDATE >/dev/null 2>&1 || true
    $PKG_INSTALL "$@" >/dev/null 2>&1 || die "Failed to install: $*  ($PKG_INSTALL $*)"
}

has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }

check_root() { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }

UV_BIN=""
UV_INSTALL_VERSION="0.12.19"

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"; render_note "uv  $UV_BIN"; return
    fi
    render_note "installing uv…"
    # Trusted sources first (distro package, then the pinned release on the
    # index), then the upstream script.
    pkg_install uv >/dev/null 2>&1 \
        || python3 -m pip install --quiet "uv==${UV_INSTALL_VERSION}" >/dev/null 2>&1 \
        || python3 -m pip install --quiet uv >/dev/null 2>&1 \
        || fetch_and_run_installer "https://astral.sh/uv/${UV_INSTALL_VERSION}/install.sh" "#!/bin/sh" "uv-install" \
        || die "Could not install uv. Manual: python3 -m pip install uv  (or https://docs.astral.sh/uv/)"
    UV_BIN="$(command -v uv 2>/dev/null || true)"
    [[ -n "$UV_BIN" ]] || UV_BIN="$HOME/.local/bin/uv"
    [[ -x "$UV_BIN" ]] || die "uv not found after install"
    render_note "uv  $UV_BIN"
}

ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        render_note "installing Docker Engine…"
        if [[ "$PKG_INSTALL" == apt* ]]; then
            $PKG_UPDATE >/dev/null 2>&1 || true
            $PKG_INSTALL docker.io >/dev/null 2>&1 \
                || $PKG_INSTALL docker-ce >/dev/null 2>&1 \
                || die "Could not install Docker. https://docs.docker.com/engine/install/"
        else
            pkg_install docker docker-compose-plugin 2>/dev/null || pkg_install docker
        fi
        command -v docker >/dev/null 2>&1 || die "Docker binary not found"
    fi
    docker compose version >/dev/null 2>&1 \
        || command -v docker-compose >/dev/null 2>&1 \
        || die "Docker Compose v2 is required (docker compose plugin)"
    render_note "Docker  $(docker --version 2>/dev/null | head -1)"
}

check_deps() {
    local missing=()
    for cmd in curl tar openssl git python3 sha256sum; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] || pkg_install "${missing[@]}"
    render_done "system tools present"
}

# Pre-flight: fail BEFORE downloading anything when the box cannot host us.
preflight_install() {
    detect_os
    check_deps
    if [[ -n "$PORT" ]]; then
        port_available_or_die "$PORT" "interactive wizard asks"
    fi
    if ! has_systemd && [[ "${MODE:-native}" != "docker" ]]; then
        die "systemd not found — native install needs it (use --mode docker)"
    fi
}

# A broken download (redirect stub, proxy block page) must fail here with
# a clear message — never as a checksum mismatch further down.
is_release_archive() { tar -tzf "$1" >/dev/null 2>&1; }

# fetch_to_file <url> <path> — download with a live byte count on the running
# step.
#
# curl's own progress meter writes carriage returns to stderr, which fights the
# progress block for the same row and ends up interleaved with it. One writer
# per row: count the bytes here and feed the step's detail line instead.
#
# The total is unknown until the headers arrive, so it appears a moment after
# the start rather than being guessed up front — a bar that claims a size it
# does not have is worse than a byte count that grows.
fetch_to_file() {
    local url="$1" out="$2"
    local started elapsed rate=0 total="" rc=0 pid
    started="$(_render_now)"
    curl -fsSL -o "$out" "$url" &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        local have
        # 2>/dev/null comes FIRST, before the input redirect. Bash applies
        # redirections left to right, so `wc -c < "$out" 2>/dev/null` leaves
        # the first one to fail on its own and print the shell's error before
        # anything is redirected: curl has not created $out yet on the first
        # poll, and the install showed a bare
        #   line 472: /tmp/tmp.XXXX/ovmanager-1.0.4.tar.gz: No such file or directory
        # in the middle of a download that was in fact fine.
        #
        # The -e test says the same thing without leaning on redirect order: no
        # file yet means zero bytes so far, which is the honest reading for a
        # progress count.
        have=0
        [[ -f "$out" ]] && have="$(wc -c < "$out" 2>/dev/null || printf 0)"
        have="${have// /}"
        elapsed=$(( $(( $(_render_now) - started )) / 1000000 ))
        (( elapsed < 1 )) && elapsed=1
        rate=$(( have / elapsed / 1024 ))
        if [[ -z "$total" ]]; then
            # Ask once, up front, rather than on the first poll: this is a
            # second connection that costs a round trip right when the main one
            # is warming up, and the answer is the same every time.
            total="$(curl -fsSLI --max-time 5 "$url" 2>/dev/null \
                | awk 'tolower($1)=="content-length:"{print $2}' | tail -1 | tr -d '\r[:space:]')"
        fi
        # Until the server's size is known the bar would read 0.0/0 MB and sit
        # there — eleven seconds of a step that looks stalled rather than
        # working. Elapsed time says the truth in the meantime, which is what
        # rustup, uv and bun all print before they have a total either.
        if [[ -z "$total" ]]; then
            render_note "downloading · ${elapsed}s elapsed"
        else
            _render_bytes "$have" "$total" "$rate"
        fi
        sleep 0.4
    done
    wait "$pid" 2>/dev/null || rc=$?
    return $rc
}

# Download the versioned release file into $1 (an existing directory). The
# tarball holds a repo snapshot plus the prebuilt frontend/dist, so no git or
# npm is needed on the server; the .sha256 sidecar is verified before extraction.
fetch_release() {
    local dest="$1" work base
    base="$(release_base)"
    work="$(mktemp -d)"
    # The download is the one step with real bytes to report, so it gets a live
    # byte count instead of a spinner with nothing behind it.
    render_watch "downloading v${VERSION}"
    fetch_to_file "$(release_url)" "$work/$base.tar.gz" \
        || { rm -rf "$work"; render_done "unavailable"; die "No verified release file is available for v${VERSION}"; }
    render_done ""
    is_release_archive "$work/$base.tar.gz" \
        || { rm -rf "$work"; die "Download for v${VERSION} is not a release archive. Re-bootstrap with the latest installer: bash <(curl -sSL https://raw.githubusercontent.com/${REPO}/main/install.sh)"; }
    curl -fsSL -o "$work/$base.sha256" "$(release_checksum_url)" 2>/dev/null \
        || { rm -rf "$work"; die "Release checksum file is missing for v${VERSION}"; }
    ( cd "$work" && sha256sum -c "$base.sha256" >/dev/null ) \
        || { rm -rf "$work"; die "Release checksum mismatch for v${VERSION}"; }
    render_note "$(release_size "$work/$base.tar.gz") · sha256 ok"
    render_unwatch
    mkdir -p "$dest"
    # --no-same-owner: an archive from an older release still carries whatever
    # uid built it, and extracting as root would restore that. The install runs
    # as root, so honouring the archive's numeric ids is exactly backwards.
    tar --no-same-owner -xzf "$work/$base.tar.gz" -C "$dest" \
        || { rm -rf "$work"; die "Extract failed"; }
    # Root-owned explicitly, so the tree does not depend on how it was built.
    # The root requirement below depends on this: a tree this user cannot
    # traverse is what keeps a non-root operator out of the panel's secrets.
    chown -R root:root "$dest"
    rm -rf "$work"
    render_done ""
}

ensure_panel_user() {  # create the service account if it is not there yet
    [[ "$MODE" == "docker" ]] && return 0   # the image has its own appuser
    if ! id -u "$PANEL_USER" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir "$DATA_DIR" \
            --shell /usr/sbin/nologin --comment "OVManager panel service account" "$PANEL_USER" \
            || die "Could not create the $PANEL_USER service account"
        render_note "account $PANEL_USER"
    fi
}

# Give the service account exactly what it needs, and no more.
#
#   .env      0640 root:$PANEL_USER  group-read, so no local account but the
#                                   service one can see the admin hash, the
#                                   JWT key or the secret URL path
#   tree      0750 root:$PANEL_USER  readable and traversable by the service
#                                   account, invisible to everyone else
#   data dir  0700 $PANEL_USER       the panel writes the database; it is the
#                                   owner's job and nobody else's business
#   TLS key   0640 root:$PANEL_USER  same reasoning as .env
grant_panel_access() {
    [[ "$MODE" == "docker" ]] && return 0
    chgrp "$PANEL_USER" "$INSTALL_DIR/.env" 2>/dev/null || true
    chmod 640 "$INSTALL_DIR/.env"
    chown root:"$PANEL_USER" "$INSTALL_DIR"
    chmod 750 "$INSTALL_DIR"
    [[ -n "$TLS_KEY" && -f "$TLS_KEY" ]] && { chgrp "$PANEL_USER" "$TLS_KEY" 2>/dev/null || true; chmod 640 "$TLS_KEY"; }
    # The venv is interpreter, not state: the panel user needs to read and
    # execute it, nothing more. Installs made while the umask leaked have it
    # 0700 root:root, which the service cannot even traverse.
    if [[ -d "$INSTALL_DIR/.venv" ]]; then
        chgrp -R "$PANEL_USER" "$INSTALL_DIR/.venv" 2>/dev/null || true
        chmod -R g+rX,o-rwx "$INSTALL_DIR/.venv" 2>/dev/null || true
    fi
    chown -R "$PANEL_USER":"$PANEL_USER" "$DATA_DIR"
    chmod 700 "$DATA_DIR"
}

write_env() {
    local jwt
    jwt="$(openssl rand -base64 48 2>/dev/null | tr -d '\n')"
    # In Docker mode the .env is consumed INSIDE the container, where the
    # data dir is the /app/data mount — never the host path (writing the
    # host path here made fresh Docker installs crash-loop with
    # PermissionError as appuser). Native mode keeps the host path.
    local data_dir="$DATA_DIR"
    [[ "$MODE" == "docker" ]] && data_dir="/app/data"
    # Scoped to this write. Unscoped, it leaked into everything the installer
    # did afterwards: `uv sync` then created .venv 0700 root:root, the panel
    # user could not traverse into it, and the service died with
    # status=203/EXEC on every fresh native install.
    (
    umask 077
    {
        printf 'HOST=0.0.0.0\n'
        printf 'PORT=%s\n' "$PORT"
        printf 'URLPATH=%s\n' "$PATHPREFIX"
        printf 'ADMIN_USERNAME=%s\n' "$ADMIN_USER"
        # No credential here, ever: the owner is a row in the panel database
        # (schema v16). The install prints a one-time claim key instead, and
        # the browser turns that into the bcrypt row. ADMIN_PASSWORD in .env
        # is ignored by the panel.
        printf 'JWT_SECRET_KEY=%s\n' "$jwt"
        printf 'DATA_DIR=%s\n' "$data_dir"
        [[ -n "$PUBLIC_URL" ]] && printf 'PUBLIC_URL=%s\n' "$PUBLIC_URL"
        [[ -n "$TLS_KEY" ]] && printf 'SSL_KEYFILE=%s\n' "$TLS_KEY"
        [[ -n "$TLS_CERT" ]] && printf 'SSL_CERTFILE=%s\n' "$TLS_CERT"
    } > "$INSTALL_DIR/.env"
    )
    # Ownership is applied later, in share_env_with_container, once the image
    # is on the box and its gid can be read rather than guessed.
    [[ "$MODE" == "docker" ]] || chmod 600 "$INSTALL_DIR/.env"
    render_note "$INSTALL_DIR/.env"
}

# The container reads the .env through a read-only bind mount, not through
# compose `env_file`: compose expands $NAME inside env_file values, which
# truncates a bcrypt hash at its salt. So the file must be readable by the app
# user's group and by nobody else — 0600 root puts the panel's own config out
# of reach, and chowning to uid 1000 would hand the admin hash and the JWT
# secret to the first human user on the host.
#
# The gid is read from the image, so there is no constant to keep in step with
# the Dockerfile and no assumption about which gids this host already uses.
share_env_with_container() {
    local envfile="$INSTALL_DIR/.env" gid
    # `id -g ovpanel` would look up a *user* by that name; the group is in
    # /etc/group, which getent reads. The awk fallback needs no libc tools.
    gid="$(docker run --rm --entrypoint getent "${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}" group ovpanel 2>/dev/null | cut -d: -f3 | tr -d '[:space:]')"
    [[ "$gid" =~ ^[0-9]+$ ]] || gid="$(docker run --rm --entrypoint /bin/sh "${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}" -c "awk -F: '\$3 == \"ovpanel\" {print \$3}' /etc/group" 2>/dev/null | tr -d '[:space:]')"
    [[ "$gid" =~ ^[0-9]+$ ]] && [[ "$gid" != "0" ]] \
        || die "Could not read the ovpanel gid from ${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}. The panel config must be readable by that group, so this cannot be guessed — check 'docker run --rm --entrypoint getent $IMAGE_REPO:$ACTIVE_IMAGE_VERSION group ovpanel'."
    # Group-sharing the config only widens access to a group that has no
    # members. If the image's gid already belongs to a populated group on this
    # host, the admin hash and the JWT secret would become readable by those
    # members — refuse rather than quietly widen.
    local existing members
    existing="$(getent group "$gid" 2>/dev/null | cut -d: -f1)"
    members="$(getent group "$gid" 2>/dev/null | cut -d: -f4)"
    if [[ -n "$members" ]]; then
        die "GID $gid belongs to group '$existing' on this host and it has members ($members). Sharing the panel config by that group would expose the secret panel URL path to them. Rebuild the image with a different gid for ovpanel, or remove those members."
    fi
    [[ -n "$existing" ]] || groupadd -g "$gid" ovpanel 2>/dev/null || true
    chown "root:$gid" "$envfile"
    chmod 640 "$envfile"
}

read_env_port() {
    [[ -f "$INSTALL_DIR/.env" ]] || return 0
    local p
    p="$(awk -F= '/^PORT=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    [[ -n "$p" ]] && PORT="${PORT:-$p}"
    local t
    t="$(awk -F= '/^SSL_KEYFILE=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    if [[ -n "$t" && -z "$TLS_MODE" ]]; then TLS_MODE="self"; fi
}

# ── Native ─────────────────────────────────────────────────────────────
write_systemd_unit() {
    cat > "/etc/systemd/system/$SYSTEMD_SERVICE" << UNIT
[Unit]
Description=OVManager OpenVPN Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Not root: the panel is a network-facing service, and a compromise of it
# should not be a compromise of the host. It reads its code and .env through
# the $PANEL_USER group, owns its data directory, and cannot update itself.
User=${PANEL_USER}
Group=${PANEL_USER}
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DATA_DIR=${DATA_DIR}"
# The panel owns every file it writes (db, wal, logs) and no other service
# reads them, so the database must be private from its very first byte
# instead of world-readable until 'ovm doctor --fix' notices.
UMask=0077
# The venv's own interpreter, not \`uv run\`: \`uv run\` re-resolves and
# rebuilds the project before starting it, writing egg-info and the lock into
# the tree, which an unprivileged service account cannot do. The venv python
# needs no write access and is what uv ends up executing anyway.
ExecStart=${INSTALL_DIR}/.venv/bin/python3 main.py
# uv exits 143 on SIGTERM: a clean 'ovm stop' must read as inactive,
# not failed, so status and doctor report the truth.
SuccessExitStatus=143
Restart=on-failure
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload >/dev/null 2>&1
    systemctl enable "$SYSTEMD_SERVICE" >/dev/null 2>&1
    render_note "$SYSTEMD_SERVICE"
}

# ── Docker ─────────────────────────────────────────────────────────────
COMPOSE_FILE="$DATA_DIR/ovmanager-compose.yml"

write_compose() {
    mkdir -p "$DATA_DIR"
    # The image runs as appuser (uid 1000); a root-owned host dir would
    # make the container crash-loop on first DB write (the mount masks
    # the prepared /app/data). Match Dockerfile's `useradd -u 1000`.
    chown -R 1000:1000 "$DATA_DIR"
    cat > "$COMPOSE_FILE" << COMPOSE
services:
  ovmanager:
    image: ${IMAGE_REPO}:${ACTIVE_IMAGE_VERSION}
    container_name: ovmanager
    restart: unless-stopped
    ports:
      - "${PORT}:${PORT}"
    # No env_file: compose expands \$NAME inside env_file values, which
    # truncates ADMIN_PASSWORD_HASH at its salt and any password containing
    # a dollar sign. The panel reads the same file from disk instead
    # (pydantic-settings resolves it to /app/.env), so there is one source
    # of truth. The \$ is escaped because this heredoc is unquoted.
    volumes:
      - ${DATA_DIR}:/app/data
      - ${INSTALL_DIR}/.env:/app/.env:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /etc/ssl/self-signed:/etc/ssl/self-signed:ro
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import socket; socket.create_connection(('127.0.0.1', ${PORT}), 3)\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 25s
COMPOSE
    render_note "$COMPOSE_FILE"
}

compose_up() {
    write_compose
    render_note "pulling image"
    ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" pull ) \
        || die "docker compose pull failed — is the image published?"
    # The image is here now, so its own gid can be read rather than guessed.
    share_env_with_container
    ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d ) \
        || die "docker compose startup failed — docker logs ovmanager"
    render_done "ovmanager"
}

# The panel binds this port on the host in both modes, so one check serves
# both: the wizard wants it at prompt time and validate_input on the
# non-interactive path, and two copies of the test would drift.
port_available_or_die() {  # port_available_or_die <port> [hint]
    # `if`, not `port_in_use ... && die`: a && list returns 1 when the port is
    # free, so as a plain statement under `set -e` that aborted every
    # non-interactive install. A condition is also exempt from the ERR trap,
    # which otherwise warned on every free port.
    if port_in_use "$1"; then
        die "Port $1 is already in use — free it or pick another${2:+ ($2)}"
    fi
    return 0
}

# ── Validate / wizard / plan ───────────────────────────────────────────
validate_input() {
    is_port "$PORT" || die "Invalid port: '$PORT'"
    # A non-interactive install defaults PORT *after* preflight_install has
    # already run, so preflight's check never saw it: without this, a busy port
    # on the documented `curl ... | bash -s -- --docker --yes` one-liner failed
    # much later with a raw Docker "address already in use" error.
    port_available_or_die "$PORT"
    [[ -n "$ADMIN_USER" ]] || ADMIN_USER="$DEFAULT_USER"
    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || die "Admin username: 3–64 letters, digits, . _ -"
    if [[ -n "$PATHPREFIX" ]]; then
        [[ "$PATHPREFIX" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "URL path: letters, digits, dash, underscore"
    fi
    case "$TLS_MODE" in
        le)
            [[ -n "$TLS_DOMAIN" ]] || die "--tls 2 needs --tls-domain DOMAIN" ;;
        le-ip|self|custom) ;;
        none)
            die "Plain HTTP is not allowed — pick TLS: 1 self-signed (default),\n         2 Let's Encrypt domain, 3 Let's Encrypt IP, or 4 custom." ;;
        *) die "Invalid TLS mode: '$TLS_MODE'" ;;
    esac
    if [[ "$TLS_MODE" == "custom" ]]; then
        [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom TLS files not found"
    fi
}

# Numbered steps on one screen, each option carrying what it means. This is the
# shape the installer had before the renderer rewrite replaced it with one
# cleared screen per question, and it is the better one: the whole plan is
# visible at once, the answers stay on screen instead of scrolling away, and
# nothing clears under a fast typist.
wizard() {
    if [[ -z "$PORT" ]]; then
        render_line "$(printf '%bStep 1/4 — Panel port%s' "$B" "$NC")"
        render_line "  ${WH}1${NC}  Default: ${DEFAULT_PORT}"
        render_line "  ${WH}2${NC}  Custom"
        render_line "  ${WH}3${NC}  Random"
        local pc
        pc="$(ask "Port choice" "1")"
        case "${pc:-1}" in
            2) PORT="$(ask "Port" "${PORT:-$DEFAULT_PORT}")" ;;
            3) if command -v shuf >/dev/null 2>&1; then PORT="$(shuf -i 1024-62000 -n 1)"; else PORT="$DEFAULT_PORT"; fi ;;
            *) : "${PORT:=$DEFAULT_PORT}" ;;
        esac
        is_port "$PORT" || die "Invalid port: '$PORT'"
        port_available_or_die "$PORT"
        render_line ""
    fi

    if [[ "$PATH_SET" -eq 0 ]]; then
        render_line "$(printf '%bStep 2/4 — Panel URL path%s' "$B" "$NC")"
        render_line "  ${GY}A secret path hides the panel from scanners (random is safest).${NC}"
        local path_default="random"
        [[ "$PATH_SET" -eq 1 ]] && path_default="${PATHPREFIX:-root}"
        local path_in
        path_in="$(ask "URL path  (random / root / name)" "$path_default")"
        case "$path_in" in
            root|"/") PATHPREFIX="" ;;
            random|"") PATHPREFIX="$(rand_path)" ;;
            *) PATHPREFIX="${path_in#/}"; PATHPREFIX="${PATHPREFIX%/}" ;;
        esac
        PATH_SET=1
        render_line ""
    fi

    if [[ -z "$ADMIN_USER" ]]; then
        render_line "$(printf '%bStep 3/4 — Owner login%s' "$B" "$NC")"
        render_line "  ${GY}No password is set here: the Ready card prints a one-time claim${NC}"
        render_line "  ${GY}key, and you choose the owner password in the browser.${NC}"
        ADMIN_USER="$(ask "Admin user" "${ADMIN_USER:-$DEFAULT_USER}")"
        render_line ""
    fi

    if [[ -z "$TLS_MODE" ]]; then
        render_line "$(printf '%bStep 4/4 — Certificate (always encrypted)%s' "$B" "$NC")"
        render_line "  ${WH}1${NC}  Self-signed (default)      encrypted; one browser warning to click through"
        render_line "  ${WH}2${NC}  Let's Encrypt (domain)     needs a domain pointed here + free port 80"
        render_line "  ${WH}3${NC}  Let's Encrypt (this IP)    short-lived cert, no domain needed"
        render_line "  ${WH}4${NC}  Custom key + cert          bring your own PEM files"
        local tls
        tls="$(ask "TLS" "1")"
        case "${tls:-1}" in
            1) TLS_MODE="self" ;;
            2) TLS_MODE="le"; TLS_DOMAIN="$(ask "Domain" "${TLS_DOMAIN:-}")"
               [[ -n "$TLS_DOMAIN" ]] || die "Domain required for Let's Encrypt" ;;
            3) TLS_MODE="le-ip"; TLS_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')" ;;
            4) TLS_MODE="custom"
               TLS_CERT="$(ask "Cert file" "${TLS_CERT:-}")"
               TLS_KEY="$(ask "Key file" "${TLS_KEY:-}")"
               [[ -f "$TLS_CERT" && -f "$TLS_KEY" ]] || die "Custom TLS files not found" ;;
            *) TLS_MODE="self" ;;
        esac
    fi

    return 0
}

ask_lets_encrypt() {
    local here detected others
    here="$(public_ip || true)"
    detected="${TLS_DOMAIN:-${here:-}}"
    others="$(public_ips)"
    if [[ -n "$others" && "$others" != "$here "* && "$others" != "$here" ]]; then
        render_ask_note "this box answers on ${others// /, }"
    fi
    render_ask_note "Let's Encrypt sees whatever you type here — an IP gets a short-lived cert, a name gets a normal one"
    local answer
    answer="$(ask "ip or domain" "$detected")"
    [[ -n "$answer" ]] || answer="$detected"
    [[ -n "$answer" ]] || die "Let's Encrypt needs an IP or a domain"

    if is_ip_literal "$answer"; then
        TLS_MODE="le-ip"; TLS_DOMAIN="$answer"
        return 0
    fi
    TLS_MODE="le"; TLS_DOMAIN="$answer"
    # Say what the name resolves to before spending a rate-limited issuance on
    # it. A wrong record fails the request and burns one of Let's Encrypt's
    # weekly attempts, which is the expensive way to learn a typo.
    local resolved
    resolved="$(resolve_host "$answer")"
    if [[ -z "$resolved" ]]; then
        render_warn "$answer does not resolve yet — DNS has to point here before the certificate can be issued"
    elif [[ -n "$here" && "$resolved" != "$here" ]]; then
        render_warn "$answer resolves to $resolved, not $here — Let's Encrypt will refuse it"
    fi
    return 0
}

# What the install is about to do, in one line, as the first progress step.
#
# This replaced a nine-row plan card printed before every mutating action. The
# card restated every value the operator had just been asked for, and a wall of
# grey labels in front of the run is not a safety feature — the wizard is. What
# is worth keeping is the machine's own state, because nobody chose it and it is
# the thing that changes whether the run can succeed.
preflight_summary() {
    local os="${OS_NAME:-linux}" free
    free="$(df -h --output=avail /opt 2>/dev/null | tail -1 | tr -d ' ')"
    printf '%s · %s free at /opt · :%s free' "$os" "${free:-?}" "$PORT"
}

success_card() {
    local url key note
    url="$(panel_url)"
    if [[ -n "$CLAIM_KEY" ]]; then
        key="$CLAIM_KEY"
        note="$(printf '  %bone-time%s · reprint: %sovm auth key%s' "$GY" "$NC" "$B" "$NC")"
    else
        key="$(printf '%snot written%s  %s(run: ovm auth key)%s' "$RD" "$NC" "$GY" "$NC")"
        note=""
    fi
    render_card "ready" "setup key" "$key" \
        "panel|$url/setup" \
        "user|$ADMIN_USER — password set by you, in the browser" \
        "tls|$(tls_summary)" \
        "logs|$CLI_ALIAS logs -f" \
        "data|$DATA_DIR"
    [[ -n "$note" ]] && render_line "$note"
    if [[ "$TLS_MODE" == "self" ]]; then
        render_line "$(printf '  %sthe browser certificate warning is expected on a self-signed cert — %sovm tls%s replaces it' "$GY" "$B" "$NC")"
    fi
    # Called, not interpolated. A bare reference is an unset variable — `set -u`
    # turns it into a fatal "unbound variable" at the very last line of a
    # successful install, after the panel is already serving. The card printed
    # with no uninstall line and the installer exited non-zero, so a working
    # install looked like a failed one. This was the one place it missed:
    # render_next on the failure path already had the parens.
    render_line "  uninstall: $(installer_uninstall_command)"
    render_blank
}

# Spelled out in full, every time. An operator who wants it later is reading a
# log or a scrollback, not this script, and a short form would not be runnable
# from either.
installer_uninstall_command() {
    local repo="${REPO}"
    printf 'bash <(curl -sSL https://raw.githubusercontent.com/%s/%s/install.sh) uninstall --purge -y' "$repo" "$BRANCH"
}

tls_summary() {
    case "$TLS_MODE" in
        self)    printf 'self-signed · replace anytime: %s tls' "$CLI_ALIAS" ;;
        le)      printf "lets encrypt · %s" "$TLS_DOMAIN" ;;
        le-ip)   printf 'lets encrypt · %s · short-lived' "$TLS_DOMAIN" ;;
        custom)  printf 'custom · %s' "$TLS_CERT" ;;
        *)       printf 'none' ;;
    esac
}

# ── Actions ────────────────────────────────────────────────────────────
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed ($INSTALL_DIR). Use: $0 update"
    mkdir -p "$DATA_DIR"
    # Native panel state holds secrets — private from birth (Docker data
    # belongs to uid 1000 instead; doctor --fix normalizes old installs).
    [[ "$MODE" == "docker" ]] || chmod 700 "$DATA_DIR"
    ensure_panel_user

    render_begin "preflight" 6
    render_done "$(preflight_summary)"

    render_begin "release" 6
    fetch_release "$INSTALL_DIR"

    render_begin "certificate" 6
    setup_tls
    write_env
    render_done "$(tls_summary)"

    local scheme; scheme="$(scheme_of)"

    if [[ "$MODE" == "docker" ]]; then
        render_begin "runtime" 6
        compose_up
        render_done "container ovmanager"
    else
        render_begin "runtime" 6
        ensure_uv
        cd "$INSTALL_DIR"
        render_note "python packages"
        render_watch "uv sync"
        "$UV_BIN" sync --frozen --no-dev --quiet >/dev/null 2>&1 \
            || die "Could not install the panel's Python packages"
        render_done "packages installed"
        grant_panel_access
        [[ -d "$INSTALL_DIR/frontend/dist" ]] || die "Verified release is missing the prebuilt frontend"
        render_note "frontend prebuilt"
        write_systemd_unit
        systemctl_bounded restart >/dev/null 2>&1 || die "Could not start $SYSTEMD_SERVICE"
        render_done "active"
    fi

    render_begin "health" 6
    wait_health_live "${scheme}://127.0.0.1:${PORT}/health" 40 || {
        render_fail "health" "no answer on /health after 40s"
        install_failure_next
        return 1
    }
    # Minted now, not earlier: grant_panel_access (runtime) chowns the data dir
    # to the panel user, and the panel reads the key file per claim.
    issue_claim_key
    if [[ "$MODE" == "docker" ]]; then
        docker restart ovmanager >/dev/null 2>&1 || true
    else
        systemctl_bounded restart >/dev/null 2>&1 || true
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 40 \
        || render_warn "no answer on /health after finalize — check $CLI_ALIAS logs -f"
    render_done "200"

    render_begin "command" 6
    open_firewall_port "$PORT"
    install_cli
    render_done "$BIN_DIR/$CLI_ALIAS"

    # The claim key is not a step of its own. Minting happens inside the health
    # step because it depends on the data dir the runtime chowned, and a step
    # whose label is "setup key" and whose detail is the key itself printed the
    # secret twice on one screen — once in the block, once in the card below it.
    success_card
}

# The way out, printed once on failure: how to see what happened, and how to
# remove the install. Two commands, both runnable as printed.
install_failure_next() {
    render_next "$CLI_ALIAS logs 50" "$(installer_uninstall_command)"
}

# Sizes a downloaded file or a directory. The release step reports what actually
# arrived, not just "done" — the number is also the first thing anyone
# suspicious of a slow or truncated download looks at.
release_size() {
    local kb
    if [[ -f "$1" ]]; then
        kb=$(( $(wc -c < "$1" 2>/dev/null || printf 0) / 1024 ))
    else
        kb="$(du -sk "$1" 2>/dev/null | awk '{print $1}')"
    fi
    if [[ -n "$kb" ]]; then
        awk -v k="$kb" 'BEGIN{printf "%.1f MB", k/1024}'
    fi
    return 0
}

do_update() {
    operation_begin update
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    render_line "$(printf '  %b→ %sv%s → %sv%s' "$OR" "$NC" "$VERSION")"
    [[ -f "$COMPOSE_FILE" ]] && MODE="docker"
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    : "${TLS_MODE:=none}"
    if [[ "$MODE" == "docker" ]]; then ensure_docker; else ensure_uv; fi

    local from_version safety snapshot scheme activated=0
    from_version="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' "$INSTALL_DIR/backend/version.py" 2>/dev/null | head -1)"
    : "${from_version:=unknown}"
    scheme="$(scheme_of)"
    update_state preflight "$from_version" "$VERSION"

    render_begin "backup" 6
    safety="$(update_safety_backup "$from_version")" || die "Could not create the mandatory pre-update backup"
    [[ -n "$safety" && -f "$safety" ]] || die "The pre-update backup was not created"
    snapshot="$(snapshot_code "$INSTALL_DIR" "panel" 2)"
    render_done "$(basename "$safety" 2>/dev/null)"
    update_state staging "$from_version" "$VERSION" "$safety"

    render_begin "stage" 6
    rm -rf "$UPDATE_STAGE"
    mkdir -p "$UPDATE_STAGE"
    fetch_release "$UPDATE_STAGE"
    cp -p "$INSTALL_DIR/.env" "$UPDATE_STAGE/.env" || die "Could not preserve configuration"
    chmod 600 "$UPDATE_STAGE/.env"
    # Retired secrets must not reach the candidate: the new backend rejects
    # unknown .env keys and would crash-loop on first boot.
    sed -i '/^BACKUP_ENCRYPT_KEY=/d' "$UPDATE_STAGE/.env"
    if [[ "$MODE" != "docker" ]]; then
        render_note "python packages"
        ( cd "$UPDATE_STAGE" && "$UV_BIN" sync --frozen --no-dev --quiet ) >/dev/null 2>&1 \
            || die "Could not prepare the staged release; current version is still running"
        [[ -d "$UPDATE_STAGE/frontend/dist" ]] || die "Verified release is missing the prebuilt frontend"
    fi
    render_done ""

    render_begin "maintenance" 6
    : > "$UPDATE_MARKER"
    chmod 600 "$UPDATE_MARKER"
    update_state activating "$from_version" "$VERSION" "$safety"
    if [[ "$MODE" == "docker" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
    else
        systemctl_bounded stop
    fi
    render_done "writes paused"

    render_begin "activate" 6
    rm -rf "$UPDATE_PREVIOUS"
    if mv "$INSTALL_DIR" "$UPDATE_PREVIOUS" && mv "$UPDATE_STAGE" "$INSTALL_DIR"; then
        activated=1
    else
        # If the first rename never happened, the active release is untouched.
        # If it did, restore it before clearing maintenance mode. A failed
        # restore deliberately leaves the marker in place to block writes.
        if [[ -d "$INSTALL_DIR" ]] || { [[ -d "$UPDATE_PREVIOUS" ]] && mv "$UPDATE_PREVIOUS" "$INSTALL_DIR"; }; then
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from_version" "$VERSION" "$safety"
            die "Could not activate the staged release; the previous release remains active and data was not changed"
        fi
        update_state recovery_required "$from_version" "$VERSION" "$safety"
        die "Could not activate or restore release files. Writes remain blocked; run: ovm update (it recovers an interrupted one first)"
    fi

    # Deliberately no service-account *migration* here. It was here in 1.0.26
    # and 1.0.28 and made every update a coin flip: the migration rewrote the
    # unit before the candidate was verified, so a candidate that failed for any
    # other reason left a half-applied migration the failover could not undo.
    # `ovm doctor --fix` is the only path that changes the account.
    #
    # Re-applying the *grant* is required instead: the step above replaced the
    # whole tree, so on a box where the panel already runs unprivileged the new
    # tree is root-owned again and the service cannot even chdir into it (1.0.30
    # -> 1.0.31 failed verification with CHDIR: Permission denied). The grant is
    # idempotent and changes no ownership of the unit, so it is safe to repeat.
    if [[ "$MODE" != "docker" ]] && ! grep -qE '^User=root\s*$' "/etc/systemd/system/$SYSTEMD_SERVICE" 2>/dev/null; then
        grant_panel_access
        render_note "access re-granted for $PANEL_USER"
    fi

    local start_ok=0
    if [[ "$MODE" == "docker" ]]; then
        ( compose_up ) && start_ok=1 || true
    else
        render_note "starting candidate"
        systemctl_bounded restart >/dev/null 2>&1 && start_ok=1 || true
    fi

    render_begin "verify" 6
    update_state verifying "$from_version" "$VERSION" "$safety"
    if [[ "$start_ok" -eq 1 ]] && wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        local reported
        reported="$(candidate_version)"
        [[ "$reported" == "$VERSION" ]] || { render_warn "Candidate reported version '${reported:-unknown}', expected '$VERSION'"; start_ok=0; }
    else
        start_ok=0
    fi

    if [[ "$start_ok" -ne 1 ]]; then
        render_fail "verify" "candidate did not answer — failing over to v${from_version}"
        update_state failing_over "$from_version" "$VERSION" "$safety"
        if [[ "$MODE" == "docker" ]]; then
            ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
        else
            systemctl_bounded stop >/dev/null 2>&1 || true
        fi
        rm -rf "$UPDATE_STAGE"
        mv "$INSTALL_DIR" "$UPDATE_STAGE" || true
        mv "$UPDATE_PREVIOUS" "$INSTALL_DIR" \
            || { update_state recovery_required "$from_version" "$VERSION" "$safety"; die "Automatic failover could not restore the previous release. Snapshot: $snapshot"; }
        local db_restored=0
        if db_restore_needed "$safety"; then
            restore_update_database "$safety" \
                || { update_state recovery_required "$from_version" "$VERSION" "$safety"; die "Previous code was restored but the database safety backup could not be restored"; }
            db_restored=1
        else
            render_note "database untouched — restore skipped"
        fi

        local rollback_started=0
        if [[ "$MODE" == "docker" ]]; then
            ACTIVE_IMAGE_VERSION="$from_version"
            ( compose_up ) && rollback_started=1 || true
        else
            systemctl_bounded restart >/dev/null 2>&1 && rollback_started=1 || true
        fi
        if [[ "$rollback_started" -eq 1 ]] && wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from_version" "$VERSION" "$safety"
            if [[ "$db_restored" -eq 1 ]]; then
                die "Update failed over safely to v${from_version}. Data was restored from $safety. Check logs before retrying."
            else
                die "Update failed over safely to v${from_version} (database was untouched — no restore needed). Check logs before retrying."
            fi
        fi
        update_state recovery_required "$from_version" "$VERSION" "$safety"
        die "Update recovery needs attention. Previous files: $INSTALL_DIR; safety backup: $safety; snapshot: $snapshot"
    fi

    render_begin "commit" 6
    install_cli
    rm -f "$UPDATE_MARKER"
    # Verification mode intentionally paused all background writers. Restart
    # once without the marker so normal scheduling resumes, then require one
    # final healthy response before committing the journal.
    if [[ "$MODE" == "docker" ]]; then
        docker restart ovmanager >/dev/null 2>&1 || true
    else
        systemctl_bounded restart >/dev/null 2>&1 || true
    fi
    if ! wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        : > "$UPDATE_MARKER"; chmod 600 "$UPDATE_MARKER"
        update_state recovery_required "$from_version" "$VERSION" "$safety"
        die "Candidate passed verification but failed its final restart. Writes are blocked; run: ovm update (it recovers an interrupted one first)"
    fi
    update_state committed "$from_version" "$VERSION" "$safety"
    render_done "v${from_version} → v${VERSION}"
    render_line "  rollback: $CLI_ALIAS rollback"
    return 0
}

do_recover_update() {
    if [[ ! -f "$UPDATE_STATE" ]]; then
        [[ -f "$UPDATE_MARKER" ]] && die "Update maintenance marker exists but its state journal is missing"
        render_ok "no interrupted update needs recovery"
        return 0
    fi
    local phase from target safety scheme reported
    # Captured, not read from a process substitution. A substitution runs in its
    # own process: a corrupt journal printed a python traceback to the terminal
    # while `read` returned non-zero, and the ERR trap then added its own line —
    # so the operator saw two stack traces and then the one sentence that
    # explained the problem. Assigning first lets `|| ` swallow the failure
    # quietly, and the unreadable journal is reported as exactly that.
    local journal=""
    journal="$(python3 - "$UPDATE_STATE" 2>/dev/null <<'PY'
import json, sys
x=json.load(open(sys.argv[1]))
print(x.get("phase","unknown"), x.get("from_version","unknown"), x.get("to_version","unknown"), x.get("safety_backup") or "")
PY
)" || journal=""
    [[ -n "$journal" ]] || die "Update state journal is unreadable"
    read -r phase from target safety <<< "$journal"
    case "$phase" in
        committed|failed_over)
            if [[ ! -f "$UPDATE_MARKER" ]]; then
                render_ok "no interrupted update needs recovery"
                return 0
            fi
            ;;
        preflight|staging)
            # Activation had not begun: the installed release and database are
            # untouched, so stale staging content can be discarded safely.
            check_root
            rm -rf "$UPDATE_STAGE"
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from" "$target" "$safety"
            render_ok "cleared an interrupted pre-activation update · v${from} remains active"
            return 0
            ;;
        activating|verifying|failing_over|recovery_required) ;;
        *) die "Update journal has unknown phase '$phase'; writes remain blocked" ;;
    esac
    check_root
    if [[ ! -f "$UPDATE_MARKER" ]]; then
        : > "$UPDATE_MARKER"
        chmod 600 "$UPDATE_MARKER"
        render_warn "re-created the missing update maintenance marker"
    fi
    [[ -f "$COMPOSE_FILE" ]] && MODE="docker" || MODE="native"
    read_env_port; : "${PORT:=$DEFAULT_PORT}"; : "${TLS_MODE:=none}"
    scheme="$(scheme_of)"
    reported="$(candidate_version)"
    if [[ -n "$reported" && "$reported" == "$target" ]]; then
        rm -f "$UPDATE_MARKER"
        update_state committed "$from" "$target" "$safety"
        render_ok "recovered update journal · v${target} is healthy"
        return 0
    fi
    if [[ -n "$reported" && "$reported" == "$from" && ! -d "$UPDATE_PREVIOUS" ]]; then
        rm -f "$UPDATE_MARKER"
        update_state failed_over "$from" "$target" "$safety"
        render_ok "recovered update journal · previous v${from} is healthy"
        return 0
    fi
    [[ -d "$UPDATE_PREVIOUS" ]] || {
        # Activation never swapped the trees (killed before/during the
        # rename): the installed release IS the pre-update one, so discard
        # staging and (re)start it. The database was never touched.
        rm -rf "$UPDATE_STAGE"
        if [[ "$MODE" == "docker" ]]; then
            ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d ) >/dev/null 2>&1 || true
        else
            systemctl_bounded restart >/dev/null 2>&1 || systemctl start "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
        fi
        if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
            rm -f "$UPDATE_MARKER"
            update_state failed_over "$from" "$target" "$safety"
            render_ok "interrupted update never activated · v${from} restarted, staging discarded"
            return 0
        fi
        update_state recovery_required "$from" "$target" "$safety"
        die "Interrupted update never activated and v${from} does not answer health. Run: ovm logs 100"
    }
    render_warn "interrupted candidate is unhealthy — failing over to v${from}"
    if [[ "$MODE" == "docker" ]]; then
        docker rm -f ovmanager >/dev/null 2>&1 || true
    else
        systemctl_bounded stop >/dev/null 2>&1 || true
    fi
    rm -rf "$UPDATE_STAGE"
    [[ -d "$INSTALL_DIR" ]] && mv "$INSTALL_DIR" "$UPDATE_STAGE"
    mv "$UPDATE_PREVIOUS" "$INSTALL_DIR" || die "Could not restore the previous release directory"
    [[ -n "$safety" ]] && restore_update_database "$safety" \
        || die "Previous release restored, but the database safety backup could not be restored"
    if [[ "$MODE" == "docker" ]]; then
        ACTIVE_IMAGE_VERSION="$from"
        compose_up
    else
        systemctl_bounded restart
    fi
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        rm -f "$UPDATE_MARKER"
        update_state failed_over "$from" "$target" "$safety"
        render_ok "interrupted update failed over safely to v${from}"
        return 0
    fi
    update_state recovery_required "$from" "$target" "$safety"
    die "Previous release was restored but is not healthy. Run: ovm logs 100"
}

do_uninstall() {
    operation_begin uninstall
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    check_root
    # The list comes before the question, and the question is not yes/no: the
    # destructive answer is a word, so a stray Enter keeps the data. A y/N
    # prompt puts "yes, delete the database" one keystroke from the default.
    render_screen
    render_line "  $(printf '%bthis removes%b' "$B" "$NC")"
    render_rule
    render_kv "service" "$SYSTEMD_SERVICE"
    render_kv "files" "$(dir_size "$INSTALL_DIR")   $INSTALL_DIR"
    if [[ "$PURGE" -eq 1 ]]; then
        render_kv "data" "$(printf '%s%s%s   %s ← users, settings, certs' "$RD" "$DATA_DIR" "$NC" "$GY")"
    else
        render_kv "data" "$(dir_size "$DATA_DIR")   $DATA_DIR"
    fi
    render_rule
    confirm_word "delete the data as well? type purge" "purge" && PURGE=1
    confirm "remove the app and stop the service?" n || die "Cancelled."

    render_begin "uninstall" 1
    systemctl_bounded stop
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SYSTEMD_SERVICE"
    systemctl daemon-reload 2>/dev/null || true
    if command -v docker >/dev/null 2>&1 && [[ -f "$COMPOSE_FILE" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
        docker rm -f ovmanager >/dev/null 2>&1 || true
    fi
    remove_cli
    rm -rf "$INSTALL_DIR"
    if [[ "$PURGE" -eq 1 ]]; then
        backup_dir "$DATA_DIR" "panel-pre-purge"
        rm -rf "$DATA_DIR"
        render_done "data removed"
    else
        render_done "app removed · data kept at $DATA_DIR"
    fi
    render_blank
}

# Sizes a directory for the uninstall list. Present because "210 MB" and "84 MB"
# read very differently, and an operator deciding whether to purge needs the
# number in front of them, not after.
dir_size() {
    local kb
    kb="$(du -sk "$1" 2>/dev/null | awk '{print $1}')"
    if [[ -n "$kb" ]]; then
        awk -v k="$kb" 'BEGIN { printf "%.0f MB", k/1024 }'
    fi
    return 0
}

# The front door: one menu, asked before anything else on a bare run.
#
# `uninstall` is only on the menu when there is something to uninstall. Offering
# it on a clean host would put a destructive action in the same list as the
# ordinary ones, where a mistyped digit lands on it.
#
# Install mode is chosen here and nowhere else — the wizard does not ask it
# again, so the two cannot disagree.
start_menu() {
    local tag
    if [[ -d "$INSTALL_DIR" ]]; then
        render_line "  ${GY}OVManager is already installed at ${INSTALL_DIR}${NC}"
        render_blank
        tag="$(render_menu "" \
            install    "install" \
            docker     "install with docker" \
            uninstall  "uninstall" \
            exit       "exit")"
        case "$tag" in
            uninstall)
                check_root
                do_uninstall
                return 0
                ;;
            install|docker)
                # Installing over an existing panel is an update: it keeps the
                # database, the URL path, the certificate and the owner's
                # credential. Going through do_update rather than a fresh
                # do_install is what makes that true — a fresh install would
                # hand out a new claim key and a new secret path, and the owner
                # would be locked out of the panel they were trying to reach.
                check_root
                detect_os
                check_deps
                if ! confirm "Update it to v${VERSION} now?" "y"; then
                    # They declined the update, which usually means they wanted
                    # a clean slate. Say how, rather than leaving them to guess
                    # at the flag.
                    render_blank
                    render_line "  $(printf '%bto reinstall from scratch:%s' "$B" "$NC")"
                    render_line "    bash <(curl -sSL https://raw.githubusercontent.com/${REPO}/${BRANCH}/install.sh) uninstall --purge -y"
                    render_blank
                    return 0
                fi
                do_update
                return 0
                ;;
            *)
                render_line "  nothing was changed"
                return 0
                ;;
        esac
    fi

    tag="$(render_menu "" \
        install    "install" \
        docker     "install with docker" \
        exit       "exit")"
    case "$tag" in
        install) MODE="native" ;;
        docker)  MODE="docker" ;;
        *)       render_line "  nothing was changed"; exit 0 ;;
    esac
    check_root
    detect_os
    check_deps
    wizard
    validate_input
    do_install
}


# manager.sh is installed as "ovmanager" (+ "ovm" alias), so day-to-day ops
# live outside this installer. Refreshed on every update, which auto-swaps
# boxes whose ovm is an old installer copy.
install_cli() {
    local src="${INSTALL_DIR}/manager.sh"
    [[ -f "$src" ]] || return 0
    mkdir -p "$BIN_DIR" 2>/dev/null || { render_warn "Could not create $BIN_DIR"; return 0; }
    if cp -f "$src" "$BIN_DIR/$CLI_NAME" 2>/dev/null && chmod 0755 "$BIN_DIR/$CLI_NAME"; then
        ln -sf "$CLI_NAME" "$BIN_DIR/$CLI_ALIAS" 2>/dev/null || true
        render_ok "Command  ${BIN_DIR}/${CLI_NAME}  (alias: ${CLI_ALIAS})"
    else
        render_warn "Could not install the $CLI_NAME command into $BIN_DIR"
    fi
}

remove_cli() {
    rm -f "$BIN_DIR/$CLI_NAME" "$BIN_DIR/$CLI_ALIAS" 2>/dev/null || true
}

# ── Help / args / main ─────────────────────────────────────────────────
usage() {
    cat <<EOF
OVManager Setup v${VERSION}

USAGE
  Interactive:
    bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)

  No terminal (accepts every default without asking):
    curl -sSL URL | sudo bash -s -- --yes

  No terminal, with Docker:
    curl -sSL URL | sudo bash -s -- --docker --yes

COMMANDS
  update [-v VERSION]       Staged update with backup and automatic failover
  recover-update            Recover an update interrupted by reboot/power loss
  uninstall [--purge]       Remove the app; keep data unless --purge
  version-script            Print this installer's version and commit
  help                      Show this help

OPTIONS
  -y, --yes                 Never prompt
  --docker                  Install with Docker
  -h, --help                Show this help

Every other install setting is an OVM_* environment variable — no flag, so an
run with no terminal and an interactive one cannot disagree:
  OVM_MODE=native|docker        OVM_PORT / OVM_PATH      OVM_ADMIN_USER
  OVM_TLS=self|le|le-ip|custom  OVM_TLS_DOMAIN           OVM_PUBLIC_URL
  OVM_TLS_KEY / OVM_TLS_CERT    OVM_VERSION (update pin)

DEPRECATED (still works)
  These are accepted, but each prints a warning naming what to use instead:
  -p, --pass PASS           has no effect: the owner password is chosen in the
                            browser, with the claim key printed when this ends
  --mode native|docker      use --docker, or OVM_MODE
  --tls 1|2|3|4             use OVM_TLS (1 self, 2 le, 3 le-ip, 4 custom)
  --tls-domain DOMAIN       use OVM_TLS_DOMAIN
  --tls-key FILE            use OVM_TLS_KEY
  --tls-cert FILE           use OVM_TLS_CERT
  -i                        use the "interactive" command

Fresh installs mint a one-time claim key, never a password. Open the Ready
card's URL, paste the key, and choose the owner password in the browser.
ovm auth key prints a fresh key at any time before the panel is claimed.

After installation, use ovm (alias: ovmanager) for status, service controls,
logs, backups, HTTPS, diagnostics, recovery, updates, and uninstall.

EXIT
  0 ok   1 error   2 already installed/cancelled   130 interrupted
EOF
    exit 0
}

# One line to stderr per deprecated flag, naming the replacement.
deprecated_flag() {  # deprecated_flag "FLAG" "what to use instead"
    render_warn "$1 is deprecated — use $2"
}

# `version-script` / `script-version`: which installer did you actually run?
#
# VERSION is embedded; a commit only exists when this file sits in a git
# checkout. The release tarball is a `git archive` with no .git, and a
# curl-piped installer is a lone file, so both report the commit as unknown
# rather than guessing at one.
script_commit() {
    local dir candidate
    dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf 'unknown'; return 0; }
    candidate="$dir"
    while [[ -n "$candidate" && "$candidate" != "/" ]]; do
        if [[ -e "$candidate/.git" ]]; then
            # Read-only, and only when a checkout is there: the common case
            # never invokes git at all.
            git -C "$candidate" rev-parse --short HEAD 2>/dev/null || printf 'unknown'
            return 0
        fi
        candidate="$(dirname -- "$candidate")"
    done
    printf 'unknown'
}

print_version_script() {
    local commit
    commit="$(script_commit)"
    printf 'installer  v%s\n' "$VERSION"
    if [[ "$commit" == "unknown" ]]; then
        printf 'commit     unknown — not a git checkout (downloaded installer)\n'
    else
        printf 'commit     %s\n' "$commit"
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        CLI_GIVEN=1
        case "$1" in
            -p|--pass)    [[ $# -ge 2 ]] || die "-p needs a password"
                           # Accepted and dropped: honouring it would be a lie,
                           # because the owner password is set in the browser.
                           deprecated_flag "-p, --pass" "the claim key: the owner password is set in the browser"
                           shift 2 ;;
            --docker)      MODE="docker"; shift ;;
            --mode)        [[ $# -ge 2 ]] || die "--mode needs native or docker"
                           deprecated_flag "--mode" "--docker (or OVM_MODE=native|docker)"
                           MODE="$2"; shift 2 ;;
            --tls)         [[ $# -ge 2 ]] || die "--tls needs 1, 2, 3 or 4 (see --help)"
                           deprecated_flag "--tls" "OVM_TLS=self|le|le-ip|custom"
                           case "$2" in
                               1) TLS_MODE="self" ;;
                               2) TLS_MODE="le" ;;
                               3) TLS_MODE="le-ip" ;;
                               4) TLS_MODE="custom" ;;
                               *) die "--tls needs 1, 2, 3 or 4 (see --help)" ;;
                           esac
                           shift 2 ;;
            --tls-domain)  [[ $# -ge 2 ]] || die "--tls-domain needs a domain"
                           deprecated_flag "--tls-domain" "OVM_TLS_DOMAIN"
                           TLS_DOMAIN="$2"; shift 2 ;;
            --tls-key)     [[ $# -ge 2 ]] || die "--tls-key needs a file"
                           deprecated_flag "--tls-key" "OVM_TLS_KEY"
                           TLS_KEY="$2"; shift 2 ;;
            --tls-cert)    [[ $# -ge 2 ]] || die "--tls-cert needs a file"
                           deprecated_flag "--tls-cert" "OVM_TLS_CERT"
                           TLS_CERT="$2"; shift 2 ;;
            -v|--version)  [[ $# -ge 2 ]] || die "--version needs vX.Y.Z"; PIN="$2"; shift 2 ;;
            -y|--yes) YES=1; shift ;;
            --purge)       PURGE=1; shift ;;
            -i)            deprecated_flag "-i" "the 'interactive' command"
                           ACTION="interactive"; shift ;;
            -h|--help)     usage ;;
            help)          usage ;;
            version-script|script-version) ACTION="version-script"; shift ;;
            update)        ACTION="update"; shift ;;
            recover-update) ACTION="recover-update"; shift ;;
            uninstall)     ACTION="uninstall"; shift ;;
            interactive)   ACTION="interactive"; shift ;;
            status|start|stop|restart|logs|backup|auto-backup|tls|recovery|reset-password|reset-urlpath|menu)
                           die "'$1' moved to the manager — use: ovm $1" ;;
            install)       die "'install' is the default — just drop the word" ;;
            *)             die "Unknown option: $1  (see --help)" ;;
        esac
    done
}

apply_env() {
    [[ -z "$MODE" && -n "${OVM_MODE:-}" ]] && MODE="$OVM_MODE"
    [[ -z "$PORT" && -n "${OVM_PORT:-}" ]] && PORT="$OVM_PORT"
    if [[ "$PATH_SET" -eq 0 && -n "${OVM_PATH:-}" ]]; then
        PATHPREFIX="${OVM_PATH#/}"; PATHPREFIX="${PATHPREFIX%/}"
        [[ "$PATHPREFIX" == "root" ]] && PATHPREFIX=""
        PATH_SET=1
    fi
    [[ -z "$ADMIN_USER" && -n "${OVM_ADMIN_USER:-}" ]] && ADMIN_USER="$OVM_ADMIN_USER"
    [[ -z "$TLS_MODE" && -n "${OVM_TLS_MODE:-}" ]] && TLS_MODE="$OVM_TLS_MODE"
    [[ -z "$TLS_MODE" && -n "${OVM_TLS:-}" ]] && TLS_MODE="$OVM_TLS"
    [[ -z "$TLS_DOMAIN" && -n "${OVM_TLS_DOMAIN:-}" ]] && TLS_DOMAIN="$OVM_TLS_DOMAIN"
    [[ -z "$TLS_KEY" && -n "${OVM_TLS_KEY:-}" ]] && TLS_KEY="$OVM_TLS_KEY"
    [[ -z "$TLS_CERT" && -n "${OVM_TLS_CERT:-}" ]] && TLS_CERT="$OVM_TLS_CERT"
    [[ -z "$PIN" && -n "${OVM_VERSION:-}" ]] && PIN="$OVM_VERSION"
    [[ -z "$PUBLIC_URL" && -n "${OVM_PUBLIC_URL:-}" ]] && PUBLIC_URL="$OVM_PUBLIC_URL"
    # Silently ignoring a credential the operator passed is worse than refusing
    # it: say so, once.
    if [[ -n "${OVM_PASS:-}${OVM_ADMIN_PASS:-}" ]]; then
        deprecated_flag "OVM_PASS / OVM_ADMIN_PASS" "the claim key: the owner password is set in the browser"
    fi
    # Explicit success: the trailing && lines above return 1 when their
    # tests are false, which would trip `set -e` on return.
    return 0
}

main() {
    parse_args "$@"
    apply_env
    if [[ -n "$PIN" ]]; then
        valid_release_version "$PIN" \
            || die "Bad --version '$PIN' (use 1.2.3, v1.2.3, 1.2.3-rc1)"
        VERSION="${PIN#v}"
    fi
    # Before the banner and before root: "which installer did you actually
    # run?" is a support question, and the CDN caches for ~5 minutes.
    [[ "$ACTION" == "version-script" ]] && { print_version_script; exit 0; }
    if can_prompt; then
        command clear >/dev/null 2>&1 || true
    fi
    banner

    # Root is required only for paths that change the system. Dry plan
    # output and the already-installed guard must work for anyone,
    # including CI sandboxes and non-root operators.
    case "$ACTION" in
        uninstall) check_root; do_uninstall; exit 0 ;;
        recover-update) do_recover_update; exit 0 ;;
        update)
            detect_os
            check_deps
            check_root
            [[ "$YES" -eq 1 ]] || confirm "Update OVManager to v${VERSION} now?" || exit 0
            do_update
            exit 0
            ;;
        interactive)
            [[ -d "$INSTALL_DIR" ]] && die "Already installed ($INSTALL_DIR). Use: $0 update"
            check_root
            detect_os
            check_deps
            run_wizard_install
            exit 0
            ;;
    esac

    # A bare run with no terminal: say which state it is in, because the two
    # have different commands and the answer differs.
    if [[ "$CLI_GIVEN" -eq 0 && "$YES" -eq 0 ]] && ! can_prompt; then
        if [[ -d "$INSTALL_DIR" ]]; then
            # Exit 2, not die's 1: "already installed" is a state the caller
            # asked about, not a failure, and `install.sh ... || true` in a
            # provisioning script must be able to tell the two apart.
            render_fail "already installed" "$INSTALL_DIR — re-run with: $0 update"
            exit 2
        fi
        die "No interactive terminal. Use --yes to Install or --docker --yes to Install with Docker."
    fi

    # A bare interactive run gets the front door: one menu that chooses the
    # action, then the wizard for its details. It ends the run itself, having
    # either installed, uninstalled or exited.
    if [[ "$CLI_GIVEN" -eq 0 && "$YES" -eq 0 ]]; then
        start_menu
        exit 0
    fi

    # Everything from here is the machine path: flags, OVM_* env, or --yes.
    if [[ -d "$INSTALL_DIR" ]]; then
        render_fail "already installed" "$INSTALL_DIR — re-run with: $0 update"
        exit 2
    fi

    check_root
    detect_os
    check_deps

    : "${PORT:=$DEFAULT_PORT}"
    if [[ "$PATH_SET" -eq 0 ]]; then
        PATHPREFIX="$(rand_path)"
    fi
    : "${ADMIN_USER:=$DEFAULT_USER}"
    : "${TLS_MODE:=self}"
    : "${MODE:=native}"

    validate_input
    do_install
}

run_wizard_install() {
    wizard
    validate_input
    do_install
}

banner() {
    render_banner "OVManager" "v${VERSION}"
}

# Dispatch only when run, not when sourced, so the tests can source the
# functions above and exercise them against a sandbox without installing
# anything. `bash install.sh ...` is unaffected: there $0 is this file.
# Run main when executed as a file OR with no source file at all. The second
# case is the documented pipe form — `curl … | sudo bash -s -- --yes` leaves
# BASH_SOURCE unset, and under `set -u` the bare `"${BASH_SOURCE[0]}"` here was
# an "unbound variable" fatal, so that one-liner never ran at all. Sourcing
# still sets BASH_SOURCE to the sourcing file, which is not $0.
if [[ -z "${BASH_SOURCE[0]:-}" || "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
