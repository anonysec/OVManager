#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# ovmanager — OVManager panel manager (installed as ovmanager/ovm).
# Day-to-day operations for an installed panel: status, service control,
# logs, backups, TLS, recovery. Install/update/uninstall live in
# install.sh — this script delegates to it.
#
#   ovm                  Interactive numbered menu (needs a terminal)
#   ovm status           Show panel URL, health and version
#   ovm update           Update via install.sh (backs up data first)
#   ovm uninstall        Remove the app (data kept unless --purge)
#
set -Eeuo pipefail

INSTALL_DIR="${OVM_APP_DIR:-/opt/ovmanager}"
VERSION="1.0.43"

usage() {
    # Thirteen verbs, one screen. The old help was sixty-four lines: twenty-seven
    # commands listed one per line, a five-paragraph note about which half runs
    # in Python, and an architecture paragraph that belongs in CONTRIBUTING.md.
    # Anything that did not fit is one flag away rather than one screen away.
    cat << EOF >&2
  ovmanager — panel manager v${VERSION}  (alias: ovm)

  USAGE
    ovm status              Service, health, version, panel URL  (--all for paths)
    ovm logs [N|-f]         Last N lines, or follow live
    ovm doctor [--fix]      Health checks; --fix applies the safe ones
    ovm restart             Restart the panel
    ovm enable | disable    Automatic start on or off

    ovm tls                 Certificate — lists the options
    ovm auth                Owner credential — lists the options
    ovm url                 Panel URL — lists the options

    ovm backup [--keep N]   Write a data backup now
    ovm backup schedule     on | off | status — the host timer
    ovm restore [NAME]      List backups, or restore one

    ovm update              Staged update; recovers an interrupted one first
    ovm rollback            Restore the pre-update code snapshot
    ovm uninstall           Remove the app (--purge for data too)

  ROOT
    Every command needs root, including the read-only ones: they all read .env,
    which holds the secret panel URL path. Run 'sudo ovm <command>'. The web
    panel itself needs no root — any account can log in.

  full reference: ovm help --all
EOF
}

# The full reference. Kept because "one flag away" only works if the flag is
# there: every command, every flag, and where it lives.
usage_full() {
    cat << EOF >&2
  ovmanager — panel manager v${VERSION}  (alias: ovm)

  COMMANDS
    ovm status              Service, health, version, panel URL
    ovm status --all        Adds mode, port, data and install paths
    ovm logs [N|-f]         Last N lines (default 100), or follow live
    ovm doctor [--all]      Health checks; --all lists every one
    ovm doctor --fix        Same checks, plus safe automatic repairs
    ovm restart             Restart the panel service
    ovm enable | disable    Turn automatic start on or off

    ovm tls                 Certificate: key, cert, expiry
    ovm tls selfsigned      New self-signed certificate
    ovm tls le IP|DOMAIN    Let's Encrypt — ip or domain, detected
    ovm tls custom CERT KEY Use your own pair
    ovm auth                Owner credential and what to do next
    ovm auth key            Print the one-time setup key
    ovm auth reset          Set a new owner password
    ovm url                 Panel URL, and where the prefix comes from
    ovm url set PREFIX      Set a custom path prefix
    ovm url reset           Generate a fresh random path

    ovm backup [--keep N]   Write a verified data backup now
    ovm backup schedule     on | off | status — the host timer
    ovm restore [NAME]      List data backups, or restore one by name
    ovm update              Staged update with automatic failover
    ovm rollback            Restore the newest pre-update code snapshot
    ovm uninstall [--purge] Remove the app (data kept unless --purge)
    ovm config              Every effective setting and where it comes from
    ovm completion          Install bash completion, print the source line
    ovm version-script      The installer's own version and commit

  RETIRED NAMES — still work, no longer in the short help
    ovm https              → ovm tls selfsigned | le | custom
    ovm tls-status         → ovm tls
    ovm owner-claim        → ovm auth key
    ovm reset-password     → ovm auth reset
    ovm reset-urlpath      → ovm url reset
    ovm auto-backup        → ovm backup schedule
    ovm recovery           → ovm url
    ovm doctor-fix         → ovm doctor --fix
    ovm start | stop       → ovm restart
    ovm recover-update     → ovm update (it recovers first)

  OPTIONS
    -p, --pass PASS     auth reset: new owner password (min 8, not a
                        common word or placeholder)
    -y, --yes           Never prompt
    --fix               doctor: apply safe automatic fixes
    -a, --all            status and doctor: include everything
    --keep N            backup: how many backups to keep (1-500)
    --time HH:MM        backup schedule: daily run time
    --purge             uninstall: also delete data + certs
    -v, --version V     update: pin a release, e.g. -v v1.0.15
    -h, --help          This help

  ENVIRONMENT
    OVM_APP_DIR   installed tree (default /opt/ovmanager, tests override)
    OVM_DATA_DIR  data dir (default /var/lib/ovmanager, tests override)
    OVM_PASS      same as --pass
    CI=true       implies -y

  .env
    Written once by the installer and never by this tool. It owns the boot
    settings outright — DATA_DIR, HOST, PORT, JWT_SECRET_KEY, SSL_KEYFILE,
    SSL_CERTFILE, PUBLIC_URL — because the database cannot be opened without
    DATA_DIR and the socket cannot bind without HOST and PORT. Edit it freely;
    changes take effect on restart, and `ovm config` shows what is in force.

    Everything not named there (url path, owner, subscription prefix, proxy
    trust) is a database row, changed in the panel or by the command that owns
    it. SSL_KEYFILE and SSL_CERTFILE say where `ovm tls` puts the certificate —
    the file names the location, and the command writes to it.

  Status, doctor, backups, restore and auth run from the Python CLI in cli/ —
  the single implementation, on docker installs too, because the owner
  credential is a database row and the container is where it lives. Logs and
  url reset stay host-side (a container has no journalctl and no host .env), as
  do update, uninstall, rollback, certificate issuance, and the restart around
  a restore. Update and uninstall live in install.sh; this script delegates so
  there is one copy of each.
EOF
}
# `ovm help` and a bare `ovm` print usage and stop. Handled here, before
# anything is sourced, because the libraries live inside the install tree —
# which is 0700 and root-owned — so a non-root caller could never load them.
# These two are the only invocations that stay open to a normal user.
_ovm_mode="command"
for _ovm_arg in "$@"; do
    case "$_ovm_arg" in
        -h|--help|help) _ovm_mode="help"; break ;;
        -*) continue ;;
        *) _ovm_mode="command"; break ;;
    esac
done
# No arguments at all, or an explicit help request, prints usage. An unknown
# flag is not help: it falls through to parse_args, which rejects it — a typo
# must not look like a successful command.
if [[ $# -eq 0 || "$_ovm_mode" == "help" ]]; then
    unset _ovm_mode _ovm_arg
    # `ovm help --all` is one flag away from the short list. "One flag away"
    # only works if the flag is there: the retired names, every option, and
    # where each half runs all live in that second screen.
    if [[ " $* " == *" --all "* ]]; then usage_full; else usage; fi
    exit 0
fi
unset _ovm_mode _ovm_arg

# Root gate, unconditional from here: only real commands get this far.
#
# Builtins only, because nothing has been sourced yet and die() lives in the
# libraries — which is also why the check cannot live at the dispatch arms: a
# non-root caller never reaches them, because sourcing out of a 0700 root-owned
# tree fails first (1.0.21 told an operator only "scripts/lib not found").
if [[ "$(id -u)" -ne 0 ]]; then
    printf '  Error: Must run as root (sudo). Every ovm command reads %s/.env,\n' "$INSTALL_DIR" >&2
    printf '         which holds the secret panel URL path and the install config.\n' >&2
    printf '         (The owner credential is a database row, not a .env value.)\n' >&2
    printf '         For the panel itself, just sign in.\n\n' >&2
    exit 1
fi

DATA_DIR="${OVM_DATA_DIR:-/var/lib/ovmanager}"
DEFAULT_PORT=2095
# Only ever a label for the login line when .env has no ADMIN_USERNAME — which
# the panel could not boot without. It was used without being defined, so the
# final report of a reset died under `set -u`.
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
COMPOSE_FILE="$DATA_DIR/ovmanager-compose.yml"
INSTALLER="$INSTALL_DIR/install.sh"
# Installed command names (same as the installer used).
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

# ── The manager is one file ──────────────────────────────────────────────
#
# These eight were scripts/lib/*.sh, fetched or sourced from the install tree.
# Sourcing them from inside a 0700 root-owned tree is what a non-root caller
# could never get past, and the copy held in step by hand is what drifts. The
# helpers are here instead, identical to the ones in install.sh.
#
# The installer and this script are two different programs with two different
# dispatchers, so they each carry their own copy deliberately —
# tests/test_lib_sourcing.py enforces that a helper is defined once per program.

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
# to install the panel got the degraded output. The menu is the one thing that
# genuinely needs keystrokes, and render_menu checks for /dev/tty itself.
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
# The pointer and the number on the input line are the same thing. Arrows do
# not "select" separately: they move the cursor and rewrite the digits, and
# Enter always reads back what is visible. One source of truth means no branch
# where the pointer and the number disagree, which is the bug every hand-rolled
# arrow menu grows.
#
# render_menu <title> <tag> <label> [<tag> <label> ...] → prints the tag.
# Falls back to a plain numbered read when there is no terminal to draw on.

render_menu() {
    shift    # title is the caller's; the banner already said what this is
    local -a tags=() labels=()
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    local count=${#tags[@]}
    [[ "$count" -gt 0 ]] || return 1

    _menu_draw() {  # reads _MENU_TAGS/_MENU_LABELS/_MENU_CUR
        local i=0 n=${#_MENU_TAGS[@]}
        while (( i < n )); do
            if (( i == _MENU_CUR )); then
                printf '  %b%s%b  %b%d%b  %s\n' \
                    "$OR" "$RENDER_POINTER" "$NC" "$B" "$(( i + 1 ))" "$NC" "${_MENU_LABELS[$i]}"
            else
                printf '    %b%d%b  %s\n' "$GY" "$(( i + 1 ))" "$NC" "${_MENU_LABELS[$i]}"
            fi
            i=$(( i + 1 ))
        done
    }

    _MENU_TAGS=("${tags[@]}"); _MENU_LABELS=("${labels[@]}"); _MENU_CUR=0

    if [[ "$RENDER_ANIMATE" -ne 1 || ! -e /dev/tty || ! -r /dev/tty ]]; then
        _menu_draw >&2
        local n
        n="$(ask "choice" "1")"
        [[ "$n" =~ ^[0-9]+$ ]] || n=1
        printf '%s' "${tags[$(( (n - 1) % count ))]}"
        return 0
    fi

    # Own fd for the drawing. The keystroke reader must not see the menu's own
    # writes on the same descriptor, and the prompt line is rewritten in place,
    # so the two are kept apart from here down.
    exec 3>&2
    local frame=$(( count + 3 )) ch c1 c2 reply="" digits=""
    local hint='↑↓ move · ⏎ confirm'
    [[ "$RENDER_SPINNER_UNICODE" -eq 1 ]] || hint='type a number · ↑↓ move'
    while true; do
        printf '\033[%dA\033[J' "$frame" >&3 2>/dev/null || true
        _menu_draw >&3
        printf '  %b%s%b\n' "$GY" "$hint" "$NC" >&3
        printf '  %bchoice [%s%d%s]%b: ' "$NC" "$B" "$(( _MENU_CUR + 1 ))" "$NC" "$NC" >&3

        # One keystroke, no Enter. Every read is timed: a pasted line, a closed
        # terminal or a tmux that lost the pane must not wedge the installer
        # mid-menu with a half-drawn frame on screen.
        if ! IFS= read -rsn1 -t 2 ch < /dev/tty; then
            # Timed out with nothing typed. Fall back to a plain line read so a
            # keystroke-free session (a CI runner with a pty, a flaky tmux) still
            # completes instead of redrawing forever.
            # The newline ends the prompt line above, and `ask` would print that
            # same prompt a second time — so every run that took the fallback
            # showed "choice [1]:" twice, once with the cursor already past it.
            # Read the line directly: the prompt is on screen and we have just
            # moved off it, and the default is applied by the next line either
            # way.
            printf '\n' >&3
            IFS= read -r digits || digits=""
            [[ "$digits" =~ ^[0-9]+$ ]] || digits=$(( _MENU_CUR + 1 ))
            reply=$(( (10#$digits - 1) % count + 1 ))
            break
        fi
        # A bare newline comes back from `read -n1` as an empty string with a
        # zero status: the delimiter was consumed and there was nothing left.
        # Without this, Enter would redraw the menu and wait again.
        [[ -z "$ch" ]] && ch=$'\n'
        case "$ch" in
            $'\n'|$'\r'|$'\x04')
                reply=$(( _MENU_CUR + 1 )); break ;;
            $'\033')
                # CSI is three bytes: ESC [ <final>. Read the two that follow
                # with a short timeout — an ESC alone (a bare Escape keypress)
                # times out here and is ignored, which is the wanted behaviour.
                if IFS= read -rsn1 -t 0.3 c1 < /dev/tty && IFS= read -rsn1 -t 0.3 c2 < /dev/tty; then
                    case "$c2" in
                        A) (( _MENU_CUR > 0 )) && _MENU_CUR=$(( _MENU_CUR - 1 )) ;;
                        B) (( _MENU_CUR < count - 1 )) && _MENU_CUR=$(( _MENU_CUR + 1 )) ;;
                    esac
                fi ;;
            $'\x7f'|$'\b')
                digits="${digits%?}"
                (( _MENU_CUR > 0 )) || _MENU_CUR=0 ;;
            [0-9])
                digits="$ch"
                _MENU_CUR=$(( 10#$ch - 1 ))
                (( _MENU_CUR >= count )) && _MENU_CUR=$(( count - 1 )) ;;
        esac
    done
    exec 3>&-
    printf '%s' "${tags[$(( reply - 1 ))]}"
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

# ── Flags (defaults) ───────────────────────────────────────────────────
PORT="" ADMIN_PASS="" MODE="" PIN=""
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT="" HTTPS_MODE=""
# Grouped-command state. `tls` picks a subcommand, `auth` picks an action, `url`
# picks set-or-rotate — each with a bare form that just lists the options.
AUTH_ACTION="key" URLPATH_SET="" URLPATH_RESET=0
ACTION=""
YES=0 PURGE=0 FIX=0 SHOW_ALL=0
LOGS_ARG=""
AUTO_BACKUP_ACTION="" BACKUP_TIME="" BACKUP_KEEP=""
RESTORE_NAME=""
OPERATION_LOCK="${DATA_DIR}/.operation.lock"
OPERATION_LOCK_HELD=0

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

# ── OS ─────────────────────────────────────────────────────────────────
OS_ID="" OS_NAME="" PKG_INSTALL="" PKG_UPDATE=""

has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }

check_root() { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }

# ── Deps ───────────────────────────────────────────────────────────────
UV_BIN=""

# ── Source / env ───────────────────────────────────────────────────────
read_env_port() {
    [[ -f "$INSTALL_DIR/.env" ]] || return 0
    local p
    p="$(awk -F= '/^PORT=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    [[ -n "$p" ]] && PORT="${PORT:-$p}"
    local t
    t="$(awk -F= '/^SSL_KEYFILE=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    if [[ -n "$t" && -z "$TLS_MODE" ]]; then TLS_MODE="self"; fi
}

# ── Actions ────────────────────────────────────────────────────────────

# Recovery for a lost owner password: prompt for the new one (bash can talk to
# a terminal; the CLI's getpass cannot be driven from here), hand it to the one
# implementation — cli/password.py through `_cli_py` — then restart and wait for
# /health. Never echoes the password.
#
# Nothing here writes .env, and nothing may: it used to write
# ADMIN_PASSWORD_HASH into it, but backend/config.py ignores the field and
# seeds.py imports it once on the fresh-install path, so the command printed
# success while the old password kept working. The credential is the owner's row
# in the panel database, and the CLI is its only writer.
do_reset_password() {
    if [[ -n "$ADMIN_PASS" ]]; then
        validate_admin_password "$ADMIN_PASS"
    else
        can_prompt || die "No password given. Use: $0 auth reset -p 'new-password'  (or set OVM_PASS)"
        render_line ""
        local p1 p2
        p1="$(ask "New password" "" "h")"
        p2="$(ask "Confirm password" "" "h")"
        [[ "$p1" == "$p2" ]] || die "Passwords do not match."
        ADMIN_PASS="$p1"
        validate_admin_password "$ADMIN_PASS"
    fi
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing) — nothing to reset."
    local envfile="$INSTALL_DIR/.env"
    [[ -f "$envfile" ]] || die "Config not found: $envfile — install OVManager first."
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"

    # In the environment, not in argv: `ps` shows every process's arguments, so
    # a password passed on the command line would be readable by any user on
    # the box.
    export OVM_ADMIN_PASS="$ADMIN_PASS"
    _cli_py reset-password \
        || die "Password not changed — the owner row in the panel database was not updated (see above)."
    render_ok "Password updated  (bcrypt row in the panel database)"

    # The panel reads that row on every login, so nothing has to be reloaded
    # for the new password to be live; the restart is what `ovm reset-password`
    # documents, and a failed one must not hide the successful change.
    restart_service

    local scheme url admin
    scheme="$(scheme_of)"
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 12 \
        || render_warn "No answer on /health yet — check the logs (ovm logs)"
    # Same source as `status`: URLPATH from .env (a later Settings change
    # lives in the DB, not here).
    PATHPREFIX="$(awk -F= '/^URLPATH=/{print $2; exit}' "$envfile" | tr -d '\r')"
    url="$(panel_url)"
    admin="$(awk -F= '/^ADMIN_USERNAME=/{print $2; exit}' "$envfile" | tr -d '\r')"
    [[ -n "$admin" ]] || admin="$DEFAULT_USER"
    render_line ""
    render_rule
    render_kv "Password" "${GR}updated${NC}"
    render_kv "Login"    "${WH}${admin}${NC}"
    render_kv "Open"     "${WH}${url}${NC}"
    render_rule
    render_line ""
}

# Update and uninstall live in install.sh — delegate, one implementation.
run_installer() {
    [[ -e "$INSTALL_DIR" ]] || [[ "$1" == "uninstall" ]] || die "Not installed ($INSTALL_DIR missing)"
    [[ -x "$INSTALLER" ]] || die "Installer missing ($INSTALLER)"
    exec "$INSTALLER" "$@"
}

delegate_update() {
    local args=()
    [[ "$YES" -eq 1 ]] && args+=(-y)
    [[ -n "$PIN" ]] && args+=(-v "$PIN")
    run_installer update "${args[@]}"
}

delegate_uninstall() {
    local args=()
    [[ "$YES" -eq 1 ]] && args+=(-y)
    [[ "$PURGE" -eq 1 ]] && args+=(--purge)
    run_installer uninstall "${args[@]}"
}

# ── Manager menu (x-ui style) ──────────────────────────────────────────

is_docker_mode() { [[ -f "$COMPOSE_FILE" ]]; }

# systemd waits up to TimeoutStopSec (90s default) for a stuck service, which
# operators read as a frozen installer. Bound the wait, then force the unit.
STOP_TIMEOUT="${OVM_STOP_TIMEOUT:-20}"

service_autostart_status() {
    if is_docker_mode; then
        local policy
        policy="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' ovmanager 2>/dev/null || true)"
        [[ -n "$policy" && "$policy" != "no" ]] && printf 'enabled' || printf 'disabled'
    else
        systemctl is-enabled --quiet "$SYSTEMD_SERVICE" 2>/dev/null && printf 'enabled' || printf 'disabled'
    fi
}

service_action() {  # start|stop|restart|enable|disable
    if is_docker_mode; then
        command -v docker >/dev/null 2>&1 || die "Docker not found on this host"
        case "$1" in
            restart) docker restart -t 10 ovmanager >/dev/null || die "docker restart ovmanager failed" ;;
            enable)  docker update --restart unless-stopped ovmanager >/dev/null || die "Could not enable automatic start" ;;
            disable) docker update --restart no ovmanager >/dev/null || die "Could not disable automatic start" ;;
            start|stop) docker "$1" ovmanager >/dev/null || die "docker $1 ovmanager failed" ;;
            *) die "Unknown service action: $1" ;;
        esac
    else
        case "$1" in
            restart) systemctl_bounded restart ;;
            enable|disable) systemctl "$1" "$SYSTEMD_SERVICE" >/dev/null || die "Could not $1 automatic start" ;;
            stop) systemctl_bounded stop ;;
            start) systemctl start "$SYSTEMD_SERVICE" >/dev/null || die "Could not start $SYSTEMD_SERVICE" ;;
            *) die "Unknown service action: $1" ;;
        esac
    fi
    case "$1" in
        enable) render_ok "Automatic start enabled" ;;
        disable) render_ok "Automatic start disabled (the running panel was not stopped)" ;;
        *) render_ok "Panel $1: done" ;;
    esac
}

restart_service() {
    service_action restart >/dev/null 2>&1 || render_warn "Restart failed — check the service manually"
}

show_logs() {
    local arg="${1:-100}"
    if is_docker_mode; then
        if [[ "$arg" == "-f" ]]; then docker logs -f --tail 100 ovmanager; else docker logs --tail "$arg" ovmanager; fi \
            || render_warn "Could not read container logs"
    elif [[ "$arg" == "-f" ]]; then
        journalctl -u "$SYSTEMD_SERVICE" -n 100 -f || render_warn "Could not read logs"
    else
        journalctl -u "$SYSTEMD_SERVICE" -n "$arg" --no-pager || render_warn "Could not read logs"
    fi
}

# Keep only the newest N tarballs this installer writes (/var/backups).
prune_backups() {
    local keep="${1:-14}" i=0 f
    [[ "$keep" =~ ^[0-9]+$ ]] || keep=14
    shopt -s nullglob
    local files=(/var/backups/panel-*.tar.gz)
    shopt -u nullglob
    ((${#files[@]} > keep)) || return 0
    while IFS= read -r f; do
        i=$((i + 1))
        if ((i > keep)); then rm -f "$f"; fi
    done < <(ls -1t "${files[@]}" 2>/dev/null)
    return 0
}

# Host-level daily backup: a systemd timer that runs `ovmanager backup`.
# Separate from the panel-scheduled backup (Settings → Advanced → Backup).
auto_backup_units_write() {
    local time="$1" keep="$2"
    local service="/etc/systemd/system/ovmanager-backup.service"
    local timer="/etc/systemd/system/ovmanager-backup.timer"
    cat > "$service" << EOF
[Unit]
Description=OVManager automatic backup

[Service]
Type=oneshot
ExecStart=${BIN_DIR}/${CLI_NAME} backup --keep ${keep}
EOF
    cat > "$timer" << EOF
[Unit]
Description=Daily OVManager backup

[Timer]
OnCalendar=*-*-* ${time}:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

auto_backup_cli() {
    local action="${1:-status}" service timer time keep
    service="/etc/systemd/system/ovmanager-backup.service"
    timer="/etc/systemd/system/ovmanager-backup.timer"
    time="${BACKUP_TIME:-03:30}"
    keep="${BACKUP_KEEP:-14}"
    case "$action" in
        on)
            [[ "$time" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || die "Invalid time '$time' (use HH:MM)"
            [[ "$keep" =~ ^[0-9]+$ ]] && ((keep >= 1 && keep <= 500)) || die "Invalid --keep '$keep' (1-500)"
            command -v systemctl >/dev/null 2>&1 || die "systemd not found — the auto-backup timer needs it"
            auto_backup_units_write "$time" "$keep"
            systemctl daemon-reload
            systemctl enable --now ovmanager-backup.timer >/dev/null 2>&1 \
                || die "Could not enable the backup timer (systemd available?)"
            render_ok "Auto backup enabled: daily at ${time}, keeping ${keep} tarballs"
            ;;
        off)
            systemctl disable --now ovmanager-backup.timer >/dev/null 2>&1 || true
            rm -f "$timer" "$service"
            systemctl daemon-reload >/dev/null 2>&1 || true
            render_ok "Auto backup disabled (host timer removed)"
            ;;
        status|"")
            # render_kv, and the row that changes it uses the current name.
            # This was a hand-built "Label: value" line naming `auto-backup`, a
            # command no longer in the short help — the node's copy of this was
            # fixed and the panel's was not.
            if [[ -f "$timer" ]]; then
                render_kv "Auto backup" "enabled"
                render_kv "Timer" "$(systemctl is-active ovmanager-backup.timer 2>/dev/null || echo unknown)"
                render_kv "Next" "$(systemctl list-timers ovmanager-backup.timer --no-pager 2>/dev/null | sed -n '2p' | awk '{print $1, $2, $3}')"
            else
                render_kv "Auto backup" "disabled"
                render_kv "Enable" "ovm backup schedule on"
            fi
            render_note "Panel schedule is separate and configured in Settings → Advanced → Backup."
            ;;
        *)
            die "Usage: $CLI_NAME auto-backup on [--time HH:MM] [--keep N] | off | status" ;;
    esac
}

show_login_info() {
    local user path port ip url
    user="$(env_get "$INSTALL_DIR/.env" ADMIN_USERNAME)"; : "${user:=admin}"
    port="$(env_get "$INSTALL_DIR/.env" PORT)"; : "${port:=$DEFAULT_PORT}"
    ip="$(_public_ip)"
    # The live prefix, read from the panel rather than .env: URLPATH has been a
    # settings row since v16 and .env is only the seed the installer wrote. The
    # URL is built from the live value, because a URL built from the seed is
    # exactly the URL that 404s.
    local live
    live="$(_cli_py urlpath-show 2>/dev/null || true)"
    path="$(printf '%s' "$live" | sed -n 's/^ *Prefix  *//p')"
    [[ "$path" == "none — served at /" || "$path" == "none" ]] && path=""
    if [[ -n "$path" ]]; then url="https://${ip}:${port}/${path}/"; else url="https://${ip}:${port}/"; fi
    render_kv "Panel"      "$url"
    render_kv "Prefix"     "${path:-none — served at /}"
    render_kv "Source"     "database — .env seeds it once, at install"
    render_kv "Owner"      "$user"
    render_kv "Public url" "$(env_get "$INSTALL_DIR/.env" PUBLIC_URL || true)"
    render_blank
    render_kv "Set"   "ovm url set NAME"
    render_kv "Reset" "ovm url reset — a fresh random path"
}

# The box's routable address, preferring what the internet dials. A panel behind
# NAT still needs the public one, or the printed URL is unreachable from the
# operator's laptop.
_public_ip() {
    local ip
    for ip in $(curl -fsS --max-time 2 https://api.ipify.org 2>/dev/null); do
        [[ "$ip" =~ ^[0-9.]+$ ]] && { printf '%s' "$ip"; return 0; }
    done
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    printf '%s' "${ip:-127.0.0.1}"
}

# `ovm auth` with no subcommand. The panel has exactly one owner credential and
# two states, and the right command differs between them — so the state comes
# first and the command follows from it.
show_auth_state() {
    local owner claimed="yes"
    owner="$(env_get "$INSTALL_DIR/.env" ADMIN_USERNAME)"; : "${owner:=admin}"
    # The key file is deleted the moment the claim succeeds, so its presence is
    # the signal — no database read, and no way for the two to disagree.
    [[ -f "$(claim_key_path)" ]] && claimed="no"
    render_kv "Owner"   "$owner"
    render_kv "Claimed" "$claimed"
    render_blank
    if [[ "$claimed" == "no" ]]; then
        render_kv "Key"    "ovm auth key — paste it at the panel's /setup page"
    else
        render_kv "Reset"  "ovm auth reset — set a new owner password"
        render_line "  the key is spent; change the password in the panel or here"
    fi
}

# `ovm url set` / `ovm url reset`. A database write, never a .env one: the prefix
# has been a settings row since v16, and .env is the seed the installer wrote.
# Writing the seed instead is how `ovm reset-urlpath` silently did nothing.
cmd_url() {
    local want="${1:-}" rotate="${2:-0}"
    if [[ -z "$want" && "$rotate" -eq 0 ]]; then show_login_info; return 0; fi

    local value
    if [[ "$rotate" -eq 1 ]]; then
        # Rotating, not clearing: a random prefix is the whole point of having
        # one, so `reset` moves to a fresh random path and serving at the root
        # stays something you have to ask for explicitly.
        value="$(_rand_urlpath)"
    else
        value="${want#/}"; value="${value%/}"
        [[ "$value" =~ ^[A-Za-z0-9_-]{1,64}$ ]] \
            || die "url path: letters, digits, dash and underscore only (or / for the root)"
    fi

    local out rc=0
    out="$(_cli_py urlpath-set "$value")" || rc=$?
    [[ $rc -eq 0 ]] || { printf '%s\n' "$out" >&2; exit 1; }
    printf '%s\n' "$out" >&2
    render_line "  restart to serve it: ovm restart"
}

_rand_urlpath() {
    openssl rand -hex 4 2>/dev/null || head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

# Certificate issuance. Non-interactive: the mode comes from the flags, so this
# is scriptable and a mistake cannot leave a half-answered prompt.
do_https() {
    local envfile="$INSTALL_DIR/.env"
    [[ -f "$envfile" ]] || die "Not installed ($envfile missing)"
    # A key or cert on their own is enough intent to mean "use my own pair", so
    # the missing half gets a message about the missing half.
    if [[ -n "$TLS_KEY" || -n "$TLS_CERT" ]]; then HTTPS_MODE="custom"; fi
    local chosen=0
    case "$HTTPS_MODE" in
        self)
            # The operator asked for a new certificate, so reuse must not
            # apply: `--self` on a host that already has a pair (shared with
            # OVNode) would otherwise silently keep the old one.
            TLS_MODE="self"; TLS_REGENERATE=1; chosen=1 ;;
        le)
            [[ -n "$TLS_DOMAIN" ]] || die "Let's Encrypt for a domain needs --domain (or use --ip, or --self)"
            TLS_MODE="le"; chosen=1 ;;
        le-ip)
            TLS_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')"
            [[ -n "$TLS_DOMAIN" ]] || die "Could not work out this host's IP for --ip"
            TLS_MODE="le-ip"; chosen=1 ;;
        custom)
            [[ -n "$TLS_KEY" && -n "$TLS_CERT" ]] || die "--key and --cert are both required"
            [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Key or certificate file not found: $TLS_KEY $TLS_CERT"
            TLS_MODE="custom"; chosen=1 ;;
        *)
            die "Pick a mode: ovm tls selfsigned | le IP|DOMAIN | custom CERT KEY. Read the current certificate with: ovm tls" ;;
    esac
    (( chosen )) || die "No certificate mode selected"

    operation_begin https-certificate
    if ! setup_tls; then operation_end; return 0; fi
    # .env is not edited. It declared where the certificate goes (or stayed
    # silent, and there is a documented default); either way the job now is to
    # put the files where it said, not to record where they ended up. Recording
    # is what produced two locations and a panel that served the one nobody
    # could see.
    _tls_install_to_declared "$TLS_KEY" "$TLS_CERT"
    render_ok "Certificate updated"
    restart_service
    operation_end
    return 0
}

# Put a freshly issued pair where the panel will actually look for it.
#
# When .env names the pair that is the destination and setup_tls wrote there
# already, so there is nothing to do. When .env is silent there is one default
# (see backend/tls_paths) and the certificate moves there — including a Let's
# Encrypt pair, whose /etc/letsencrypt location is not something the panel could
# have guessed.
_tls_install_to_declared() {
    local want_key="$1" want_cert="$2"
    local envfile="$INSTALL_DIR/.env"
    local decl_key decl_cert
    decl_key="$(env_get "$envfile" SSL_KEYFILE)"
    decl_cert="$(env_get "$envfile" SSL_CERTFILE)"
    if [[ -n "$decl_key" && -n "$decl_cert" ]]; then
        [[ "$decl_key" == "$want_key" ]] && return 0
        mkdir -p "$(dirname "$decl_key")" "$(dirname "$decl_cert")"
        cp -f "$want_key" "$decl_key" || die "Could not install the key at $decl_key"
        cp -f "$want_cert" "$decl_cert" || die "Could not install the certificate at $decl_cert"
        secure_tls_files "$decl_key" "$decl_cert"
        return 0
    fi
    local dir="/etc/ovmanager/tls"
    mkdir -p "$dir" || die "Could not create $dir"
    cp -f "$want_key" "$dir/privkey.pem" || die "Could not install the key"
    cp -f "$want_cert" "$dir/fullchain.pem" || die "Could not install the certificate"
    secure_tls_files "$dir/privkey.pem" "$dir/fullchain.pem"
    render_kv "Installed" "$dir"
    render_note "Set SSL_KEYFILE and SSL_CERTFILE in $envfile to use a path of your own."
}

# Roll back to the newest pre-update code snapshot (update failover).
do_rollback() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    local snap
    snap="$(latest_snapshot panel)"
    [[ -n "$snap" ]] || die "No code snapshot in /var/backups — nothing to roll back to"
    check_root
    render_note "Rolling back to: $snap"
    [[ "$YES" -eq 1 ]] || confirm "Restore the pre-update tree and restart?" n || die "Cancelled."
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    local scheme; scheme="$(scheme_of)"
    if [[ -f "$COMPOSE_FILE" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" down ) >/dev/null 2>&1 || true
    else
        systemctl_bounded stop >/dev/null 2>&1 || true
    fi
    tar -xzf "$snap" -C "$(dirname "$INSTALL_DIR")" \
        || die "Rollback extract failed — snapshot kept at $snap"
    if [[ -f "$COMPOSE_FILE" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" up -d ) >/dev/null 2>&1 \
            || render_warn "Could not start the container — docker logs ovmanager"
    else
        run_step "Service restarted" systemctl_bounded restart
    fi
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        render_ok "Rolled back and healthy"
    else
        die "Rollback did not restore health — snapshot at $snap, data backups in /var/backups. Check logs."
    fi
}

# ── Restore ────────────────────────────────────────────────────────────
# Put a stored backup back over the live database. The CLI owns the transaction
# (stage and verify a candidate, copy the live database aside, activate it, roll
# back on failure); the host owns what the CLI cannot do: refuse without an
# explicit confirmation, and restart the panel onto the database it replaced.
do_restore() {
    local name="$1"
    local backup="$DATA_DIR/backups/$name"
    case "$name" in
        */*|.*) die "Invalid backup name: $name" ;;
    esac
    [[ -f "$backup" ]] || die "No such backup: $name — 'ovm restore' lists them"
    check_root
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    local scheme; scheme="$(scheme_of)"
    render_note "Restoring: $name"
    confirm "Replace the live database with this backup?" n || die "Cancelled."

    local rc=0
    if is_docker_mode; then
        # The CLI runs inside the panel container, so it has to be up for the
        # restore; the restart is what makes the panel reopen the file it was
        # replaced with.
        cmd_restore "$name" || rc=$?
        ( cd "$INSTALL_DIR" && docker compose -f "$COMPOSE_FILE" restart ) >/dev/null 2>&1 \
            || render_warn "Could not restart the container — docker restart ovmanager"
    else
        systemctl_bounded stop >/dev/null 2>&1 || true
        cmd_restore "$name" || rc=$?
        systemctl_bounded restart >/dev/null 2>&1 || true
    fi
    # The panel comes back either way: a failed restore must not leave the box
    # down.
    if [[ "$rc" -ne 0 ]]; then
        die "Restore failed — the panel was restarted on the previous database. Check: ovm logs 100"
    fi
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        render_ok "Restored $name and healthy"
    else
        die "Restored $name but /health is not answering — check: ovm logs 100 (the pre-restore safety copies are in $DATA_DIR/backups)"
    fi
}

# ── Usage / args / menu / main ─────────────────────────────────────────

# Print a fresh claim key for an unclaimed panel. Safe to run repeatedly
# *because* it is not the credential: the panel reads this file per attempt and
# deletes it once the claim succeeds, so a reprinted key replaces, never adds to.
do_owner_claim() {
    check_root
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing) — nothing to claim."
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    local url claimed=0
    url="$(panel_url)"
    # Ask the panel first: a claimed panel refuses every key (409), so printing
    # one without that warning sends the operator to a dead page. A panel that
    # is down does not answer, and the key is harmless either way — the endpoint
    # checks the claim state before the key.
    if curl -fskS --max-time 3 "${url}api/owner-claim" 2>/dev/null \
        | grep -q '"claimable":[[:space:]]*false'; then
        claimed=1
    fi
    local key
    key="$(mint_claim_key)" || die "Could not write $(claim_key_path)"
    render_line ""
    if [[ "$claimed" -eq 1 ]]; then
        render_warn "This panel already has an owner — this key cannot be claimed."
        render_warn "To change the password instead: ovm auth reset"
    fi
    render_kv "Claim key" "${YL}${key}${NC}"
    render_kv "Open"      "${WH}${url}claim${NC}"
    render_kv "Expires"   "${GY}never — spent on the first successful claim${NC}"
    render_line ""
    render_note "Choose the owner password in the browser; it is stored hashed, never in .env."
    render_line ""
}

# Bash completion for this command, written where bash already looks.
#
# The list below is the same surface usage() prints; both are hand-kept, so a
# new subcommand has to be added in both places.
# Completion offers the current names plus the retired ones, because a tab
# completing `ovm auto-b` to a command that then errors is worse than a longer
# word. Help --all carries the mapping.
OVM_SUBCOMMANDS="status start stop restart enable disable logs doctor doctor-fix \
tls auth url backup auto-backup restore rollback update uninstall version-script \
config completion help tls-status https recovery owner-claim reset-password \
reset-urlpath recover-update"
OVM_FLAGS="-y --yes -a --all --fix --keep --time --purge -v --version -h --help -p --pass --self --domain --ip --key --cert"

do_completion() {
    local dir="${OVM_COMPLETION_DIR:-/etc/bash_completion.d}" path
    path="$dir/$CLI_ALIAS"
    mkdir -p "$dir" 2>/dev/null || die "Could not create $dir"
    cat > "$path" << COMPLETION
# ${CLI_ALIAS} completion — generated by: $CLI_ALIAS completion
_${CLI_ALIAS}() {
    local cur prev
    cur="\${COMP_WORDS[COMP_CWORD]}"
    prev="\${COMP_WORDS[COMP_CWORD-1]}"
    case "\$prev" in
        -v|--version) COMPREPLY=(); return ;;
        --key|--cert) COMPREPLY=( \$(compgen -f -- "\$cur") ); return ;;
    esac
    if [[ "\$COMP_CWORD" -eq 1 ]]; then
        COMPREPLY=( \$(compgen -W "$OVM_SUBCOMMANDS" -- "\$cur") )
        return
    fi
    COMPREPLY=( \$(compgen -W "$OVM_FLAGS" -- "\$cur") )
}
complete -F _${CLI_ALIAS} $CLI_ALIAS $CLI_NAME
COMPLETION
    chmod 644 "$path" 2>/dev/null || true
    render_ok "Completion  $path"
    render_line ""
    render_line "  Activate it in this shell:"
    render_line "    ${WH}source $path${NC}"
    render_line ""
}

# Which installer did you actually run? The installed tree comes from a release
# tarball, so the commit is normally unknown — the script says so rather than
# inventing one.
do_version_script() {
    if [[ -x "$INSTALLER" ]]; then
        "$INSTALLER" version-script && return 0
    fi
    printf 'installer  (missing — %s)\n' "$INSTALLER"
    printf 'manager    v%s\n' "$VERSION"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -p|--pass)    [[ $# -ge 2 ]] || die "-p needs a password"; ADMIN_PASS="$2"; shift 2 ;;
            -y|--yes) YES=1; shift ;;
            -a|--all) SHOW_ALL=1; shift ;;
            --fix) FIX=1; shift ;;
            --purge) PURGE=1; shift ;;
            -v|--version) [[ $# -ge 2 ]] || die "--version needs vX.Y.Z"; PIN="$2"; shift 2 ;;
            --keep) [[ $# -ge 2 ]] || die "--keep needs a number"; BACKUP_KEEP="$2"; shift 2 ;;
            --time) [[ $# -ge 2 ]] || die "--time needs HH:MM"; BACKUP_TIME="$2"; shift 2 ;;
            -h|--help) usage; exit 0 ;;
            help) ACTION="help"; shift ;;
            status) ACTION="status"; shift ;;
            # start/stop were never runbooks, they were reflexes: stopping a
            # healthy panel to restart it is `restart`, and that is one command.
            start|stop|restart|enable|disable) ACTION="$1"; shift ;;
            # `config` had a dispatch arm and a help entry but no arm here, so
            # `ovm config` answered "Unknown option". A test asserted the arm
            # existed and passed — it never ran the command. Every verb is now
            # covered by the sweep in tests/test_cli_shape.py.
            config) ACTION="config"; shift ;;
            logs) ACTION="logs"
                if [[ $# -ge 2 && ( "$2" == "-f" || "$2" =~ ^[0-9]+$ ) ]]; then
                    LOGS_ARG="$2"; shift 2
                else
                    shift
                fi ;;
            backup) ACTION="backup"; shift
                # A defaulted read, not a bare one: a bare `ovm backup` leaves no
                # arguments, and under `set -u` reading the first one there is a
                # fatal unbound variable. So the command every operator runs
                # first died on that line and wrote no backup.
                if [[ "${1:-}" == "schedule" ]]; then
                    # One shift, not two: the arm already consumed "backup", so
                    # only "schedule" is left, and `shift 2` on one argument is a
                    # fatal error under `set -u`. The node's copy had exactly this
                    # and it shipped broken twice — `ovn backup schedule` answered
                    # "Unknown option: schedule" because a duplicate `backup)` arm
                    # made the second, working one dead code.
                    ACTION="auto-backup"; AUTO_BACKUP_ACTION="status"
                    shift
                    # Then the action, if there is one. Without this the next
                    # word falls through to the next arm: `backup schedule on`
                    # said "Unknown option: on", and `backup schedule status` ran
                    # the full status screen instead.
                    if [[ $# -ge 1 && "$1" != -* ]]; then
                        AUTO_BACKUP_ACTION="$1"; shift
                    fi
                fi ;;
            restore) ACTION="restore"; shift
                if [[ $# -ge 1 && "$1" != -* ]]; then RESTORE_NAME="$1"; shift; fi ;;

            # ── the three grouped commands ──
            # Bare, a group prints what it can do; a subcommand acts. One rule,
            # the same for all three, so the shape is learned once.
            tls) ACTION="tls"; shift
                if [[ $# -ge 1 && "$1" != -* ]]; then
                    case "$1" in
                        selfsigned) HTTPS_MODE="self"; shift ;;
                        le) [[ $# -ge 2 ]] || die "ovm tls le needs an ip or a domain"
                            TLS_DOMAIN="$2"; shift 2 ;;
                        custom) [[ $# -ge 3 ]] || die "ovm tls custom needs CERT and KEY"
                            TLS_CERT="$2"; TLS_KEY="$3"; shift 3 ;;
                        *) die "ovm tls: unknown option '$1'  (see: ovm tls)" ;;
                    esac
                fi ;;
            auth) ACTION="auth"; shift
                if [[ $# -ge 1 && "$1" != -* ]]; then
                    case "$1" in
                        key) AUTH_ACTION="key"; shift ;;
                        reset|reset-password) AUTH_ACTION="reset"; shift ;;
                        *) die "ovm auth: unknown option '$1'  (see: ovm auth)" ;;
                    esac
                else
                    AUTH_ACTION="state"
                fi ;;
            url) ACTION="url"; shift
                if [[ $# -ge 1 && "$1" != -* ]]; then
                    case "$1" in
                        set) [[ $# -ge 2 ]] || die "ovm url set needs a path"
                            URLPATH_SET="$2"; shift 2 ;;
                        reset) URLPATH_RESET=1; shift ;;
                        *) die "ovm url: unknown option '$1'  (see: ovm url)" ;;
                    esac
                fi ;;

            # ── retired names ──
            # Still dispatched, no longer in the short help. Mapping table in
            # `ovm help --all`; nothing warns, because a deprecation line on
            # every cron job that calls `ovm auto-backup` is noise, not notice.
            https|tls-status) ACTION="tls"; shift ;;
            --self) HTTPS_MODE="self"; shift ;;
            --domain) [[ $# -ge 2 ]] || die "--domain needs a hostname"; TLS_DOMAIN="$2"; HTTPS_MODE="le"; shift 2 ;;
            --ip) HTTPS_MODE="le-ip"; shift ;;
            --key) [[ $# -ge 2 ]] || die "--key needs a file"; TLS_KEY="$2"; shift 2 ;;
            --cert) [[ $# -ge 2 ]] || die "--cert needs a file"; TLS_CERT="$2"; shift 2 ;;
            auto-backup) ACTION="auto-backup"; shift
                if [[ $# -ge 1 && "$1" != -* ]]; then AUTO_BACKUP_ACTION="$1"; shift; fi ;;
            recovery) ACTION="url"; shift ;;
            owner-claim) ACTION="auth"; AUTH_ACTION="key"; shift ;;
            reset-password) ACTION="auth"; AUTH_ACTION="reset"; shift ;;
            reset-urlpath) ACTION="url"; URLPATH_RESET=1; shift ;;
            completion) ACTION="completion"; shift ;;
            version-script|script-version) ACTION="version-script"; shift ;;
            doctor) ACTION="doctor"; shift ;;
            doctor-fix) ACTION="doctor-fix"; shift ;;
            rollback) ACTION="rollback"; shift ;;
            update|recover-update) ACTION="update"; shift ;;
            uninstall) ACTION="uninstall"; shift ;;
            *) die "Unknown option: $1  (see --help)" ;;
        esac
    done
    # Resolved here, not in the `doctor` arm: `--fix` is usually written after
    # the subcommand (`ovm doctor --fix`), so at the moment that arm runs FIX is
    # still 0 and the documented form silently ran a plain doctor — reporting
    # the problems and fixing none of them. Only the flags-first spelling
    # (`ovm --fix doctor`) ever worked.
    #
    # An `if`, not `[[ ... ]] && ACTION=...`: as the last statement of the
    # function the latter returns 1 whenever the condition is false, and `set -e`
    # then aborts every other command with no output at all.
    if [[ "$ACTION" == "doctor" && "$FIX" -eq 1 ]]; then
        ACTION="doctor-fix"
    fi
    return 0
}

main() {
    parse_args "$@"
    [[ -z "$ADMIN_PASS" && -n "${OVM_PASS:-}" ]] && ADMIN_PASS="$OVM_PASS"
    # No interactive menu: bare `ovm` prints the command list, so a stray
    # invocation in a script cannot start waiting for input.
    [[ -z "$ACTION" ]] && { usage; exit 0; }
# The operator CLI (cli/) is the implementation for every read and diagnostic
# command; this file decides how to reach it — one implementation, no bash twin
# to drift out of sync.
#
# Native: the install's own virtualenv, so `$py -m cli.main` runs directly.
# Docker: there is no host virtualenv, so the same command runs inside the panel
# container. The host .env reaches it as environment variables (compose
# env_file) rather than as a file, and the data dir is the /app/data mount, so
# `--in-container` plus a host-observed `--service-state` is all it needs.
#
# logs, reset-password and reset-urlpath cannot run in the container at all (no
# docker CLI, no host .env to rewrite) and stay host-side.
_cli_py() {  # _cli_py <command> [args...] → the CLI's exit code
    if is_docker_mode; then
        # --public-ip because a container only knows its own address, and the
        # operator needs the host's to reach the panel.
        #
        # OVM_ADMIN_PASS by name only: `docker exec` starts from the container's
        # environment, not this one, so the reset secret has to be named — and
        # `-e NAME=value` would put the password in `ps` on this host, which is
        # the one thing the CLI's environment contract exists to avoid.
        local -a secret_env=()
        [[ -n "${OVM_ADMIN_PASS:-}" ]] && secret_env=(-e OVM_ADMIN_PASS)
        docker exec ${secret_env[@]+"${secret_env[@]}"} ovmanager /app/.venv/bin/python -m cli.main \
            --install-dir /app --data-dir /app/data --in-container \
            --service-state "$(_host_service_state)" \
            --public-ip "$(hostname -I 2>/dev/null | awk '{print $1}')" "$@"
        return $?
    fi
    local py="$INSTALL_DIR/.venv/bin/python"
    [[ -x "$py" ]] || die "Panel virtualenv missing ($py) — repair with: $CLI_NAME update"
    ( cd "$INSTALL_DIR" && "$py" -m cli.main "$@" )
}

# The same call, but a missing interpreter is a returned code rather than an
# exit. Only for screens whose job is to print something regardless: `ovm tls`
# with no subcommand has to list its options even on a box it cannot read, or
# the one command that would explain the problem is the one that cannot run.
_cli_py_soft() {
    local py="$INSTALL_DIR/.venv/bin/python"
    if [[ ! -x "$py" ]]; then
        render_warn "cannot reach the panel interpreter at $py"
        return 1
    fi
    ( cd "$INSTALL_DIR" && "$py" -m cli.main "$@" )
}

# What the host can see and the container cannot: `docker ps`.
_host_service_state() {
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx ovmanager; then
        printf 'running'
    else
        printf 'stopped'
    fi
}

# One wrapper per command, shared by the interactive menu and the argv
# dispatcher, so there is a single path to each command.
cmd_status() {
    local sargs=()
    [[ "$SHOW_ALL" -eq 1 ]] && sargs+=(--all)
    _cli_py status ${sargs[@]+"${sargs[@]}"}
}

cmd_logs() {  # journalctl/docker logs do not exist inside the container
    if is_docker_mode; then show_logs "${LOGS_ARG:-100}"; else _cli_py logs "${LOGS_ARG:-100}"; fi
}

cmd_backup() { _cli_py backup ${BACKUP_KEEP:+--keep "$BACKUP_KEEP"}; }
cmd_restore() { _cli_py restore "$@"; }
cmd_tls_status() { _cli_py tls-status; }
cmd_doctor() {
    # Forwards --all, as cmd_status always has. Without this the flag parsed,
    # was ignored, and the help's "detail: ovm doctor --all" pointed at a command
    # that printed the same summary either way — so a failing check could not be
    # shown in full without guessing at other arguments. The node's copy has
    # always forwarded it; the panel's did not.
    local dargs=()
    [[ "$SHOW_ALL" -eq 1 ]] && dargs+=(--all)
    _cli_py doctor ${dargs[@]+"${dargs[@]}"}
}

# `ovm tls` with no subcommand. Reads the installed certificate and then lists
# what it can replace it with — so the answer to "what am I running, and how do I
# change it" is one screen instead of two commands to remember.
cmd_tls_options() {
    # The option list is the point of this command, so it is printed whatever
    # the read does. An operator who came here to find out what `ovm tls` can do
    # must not be met with a stack trace from the thing it was about to offer.
    # One warning per cause, not per attempt: two lines saying the same thing
    # about the same missing file is how a real problem gets missed.
    if _cli_py_soft tls-migrate; then
        _cli_py_soft tls-status \
            || render_warn "could not read the installed certificate — the options below still apply"
    else
        render_warn "the certificate state below is unknown; the options are not"
    fi
    render_blank
    render_kv "Set"     "ovm tls selfsigned"
    render_kv "Encrypt" "ovm tls le IP|DOMAIN"
    render_kv "Custom"  "ovm tls custom CERT KEY"
    render_line "  the paths come from .env — this writes the certificate, never the file"
}

cmd_doctor_fix() {
    check_root
    if ! is_docker_mode; then
        local fargs=()
        [[ "$SHOW_ALL" -eq 1 ]] && fargs+=(--all)
        _cli_py doctor-fix ${fargs[@]+"${fargs[@]}"}
        return $?
    fi
    # The fixes are all host operations — restart the service, set the restart
    # policy, chmod the host .env — so they run here and the checks still come
    # from the CLI in the container.
    case "$(_host_service_state)" in
        running) docker restart -t 10 ovmanager >/dev/null 2>&1 || render_warn "docker restart ovmanager failed" ;;
        *) render_warn "Container is not running — start it with: docker start ovmanager" ;;
    esac
    docker update --restart unless-stopped ovmanager >/dev/null 2>&1 \
        || render_warn "Could not enable automatic start"
    local envfile="$INSTALL_DIR/.env"
    if [[ -f "$envfile" ]]; then
        chmod 600 "$envfile" 2>/dev/null || render_warn "Could not chmod $envfile"
    else
        render_warn "Config $envfile not found — cannot check its mode"
    fi
    _cli_py doctor
}

    case "$ACTION" in
        # Every command below needs root, including the read-only ones: they
        # read .env, which holds JWT_SECRET_KEY and the secret URL path that is
        # the panel's only defence against scanners.
        status) check_root; cmd_status; exit $? ;;
        start|stop|restart|enable|disable) check_root; service_action "$ACTION"; exit 0 ;;
        logs) check_root; cmd_logs; exit $? ;;
        backup) check_root; cmd_backup; exit $? ;;
        restore)
            check_root
            # No name is the listing: a read, so it neither prompts nor touches
            # the running panel.
            if [[ -z "$RESTORE_NAME" ]]; then
                cmd_restore
                exit $?
            fi
            do_restore "$RESTORE_NAME"
            exit 0 ;;
        auto-backup) check_root; auto_backup_cli "$AUTO_BACKUP_ACTION"; exit 0 ;;
        completion) do_completion; exit $? ;;
        config) check_root; _cli_py config; exit $? ;;
        # Delegate: the installer is what the operator is asking about, and
        # there is exactly one implementation of the answer.
        version-script) do_version_script; exit $? ;;
        # ── the three grouped commands ──
        # Bare, each prints what it can do; the retired spellings land here too
        # and behave identically, which is what makes them safe to keep.
        tls)
            check_root
            if [[ -z "$HTTPS_MODE" ]]; then cmd_tls_options; else do_https; fi
            exit $? ;;
        auth)
            # Bare `ovm auth` is the state, because the two actions are only
            # meaningful against it: a spent key is not a problem to solve, and a
            # forgotten password is not solvable in the panel — that is the door
            # you cannot open.
            if [[ "$AUTH_ACTION" == "state" ]]; then show_auth_state; exit 0; fi
            if [[ "$AUTH_ACTION" == "key" ]]; then do_owner_claim; exit $?; fi
            check_root
            # Validated before the root gate so bad input fails the same way for
            # root and non-root callers, exactly as reset-password always did.
            # One path for every install: -p/OVM_PASS, the interactive prompt,
            # native and Docker. bash collects the password and restarts; the
            # CLI writes the row.
            [[ -n "$ADMIN_PASS" ]] && validate_admin_password "$ADMIN_PASS"
            do_reset_password
            exit $? ;;
        url)
            check_root
            cmd_url "$URLPATH_SET" "$URLPATH_RESET"
            exit $? ;;
        help) usage_full; exit 0 ;;
        doctor) check_root; cmd_doctor; exit $? ;;
        doctor-fix) check_root; cmd_doctor_fix; exit $? ;;
        rollback) check_root; do_rollback; exit 0 ;;
        # update/uninstall/recover-update exec the installer, which has its own
        # root check — refusing here means one gate for the whole CLI and a
        # clear message, instead of exec'ing a script only to be told no.
        update) check_root; delegate_update; exit 0 ;;
        recover-update) check_root; run_installer recover-update; exit 0 ;;
        uninstall) check_root; delegate_uninstall; exit 0 ;;
    esac
}

main "$@"
