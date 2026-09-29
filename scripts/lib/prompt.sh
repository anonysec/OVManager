#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# Part of scripts/lib (the simulated installer repo): sourced by manager.sh,
# and fetched and sourced by install.sh at startup (curl-pipe standalone).
# One definition per helper — tests/test_lib_sourcing.py enforces that.
# Pure helpers only.
# Interactive prompts, menus, spinners.

# Interactive if the operator did not pass -y AND we can talk to a terminal.
# `curl | bash` has no stdin TTY; humans still work via /dev/tty.
# AI / CI must pass -y (or CI=true) so this never blocks on a prompt.
can_prompt() {
    [[ "${YES:-0}" -eq 0 ]] || return 1
    [[ -t 0 ]] && return 0
    # /dev/tty can exist but be unopenable (containers, detached shells):
    # actually try to open it, or prompts silently fall back to defaults.
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Stronger check for the interactive menu: stdin must be a real terminal or
# an openable /dev/tty. Scripts and pipes take the subcommand path instead.
has_tty() {
    [[ -t 0 ]] && return 0
    { : </dev/tty; } 2>/dev/null && return 0
    return 1
}

# Masked input: prints one * per character on stderr, backspace works, and
# the value goes to stdout (never echoed as plain text). Reads stdin, so
# callers redirect /dev/tty when needed.
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
        printf '  %b%-18s%b %b[%s]%b : ' "$WH" "$label" "$NC" "$GY" "$default" "$NC" >&2
        val="$(_read_reply "$hidden")" || true
    fi
    [[ -n "$val" ]] || val="$default"
    printf '%s' "$val"
}

# confirm <question> [default] — default is y, which is what an unattended
# run gets. A destructive caller must pass n: with no terminal there is
# nobody to answer, and answering "yes" on their behalf made `ovm rollback`
# replace the running install with a snapshot whenever it was invoked from a
# cron job, a CI step or a pipeline.
confirm() {
    [[ "${YES:-0}" -eq 1 ]] && return 0
    local default="${2:-y}"
    if ! can_prompt; then
        [[ "$default" == "y" ]]
        return
    fi
    printf '  %s [%bY%b/n] : ' "$1" "$GR" "$NC" >&2
    local c=""
    c="$(_read_reply)" || true
    [[ ! "$c" =~ ^[Nn]$ ]]
}

# Explicit-yes prompt (default NO): used for destructive extras like deleting
# data during uninstall. Non-interactive runs keep the safe answer.
confirm_no() {
    [[ "${YES:-0}" -eq 1 ]] && return 1
    can_prompt || return 1
    printf '  %s [y/%bN%b] : ' "$1" "$GR" "$NC" >&2
    local c=""
    c="$(_read_reply)" || true
    [[ "$c" =~ ^[Yy]$ ]]
}

run_step() {
    local msg="$1"; shift
    if [[ -t 1 ]]; then
        "$@" >/dev/null 2>&1 &
        local pid=$! chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0 rc=0
        while kill -0 "$pid" 2>/dev/null; do
            printf '\r  %b%s%b  %-46s' "$OR" "${chars:$((i % 10)):1}" "$NC" "$msg" >&2
            sleep 0.08; i=$((i + 1))
        done
        wait "$pid" 2>/dev/null || rc=$?
        printf '\r\033[K' >&2
        if [[ $rc -eq 0 ]]; then step "$msg"; else fail "$msg"; return 1; fi
    else
        info "$msg"
        "$@" || { fail "$msg"; return 1; }
        step "$msg"
    fi
}

# Boxed menu when whiptail is already installed; colored menu otherwise.
tui_select() {  # tui_select "Title" tag label [tag label ...] → prints the tag
    local title="$1"; shift
    local tags=() labels=()
    while [[ $# -ge 2 ]]; do tags+=("$1"); labels+=("$2"); shift 2; done
    if command -v whiptail >/dev/null 2>&1 && can_prompt; then
        local args=() i=0 out=""
        for tag in "${tags[@]}"; do args+=("$tag" "${labels[$i]}"); i=$((i + 1)); done
        out="$(whiptail --title "$title" --menu "Choose an action" 24 78 12 "${args[@]}" 3>&1 1>&2 2>&3)" && {
            printf '%s' "$out"
            return 0
        }
        return 0
    fi
    line "  ${B}${title}${NC}"; line ""
    local i=0
    for tag in "${tags[@]}"; do
        i=$((i + 1))
        printf '  %b%d%b)  %s\n' "$WH" "$i" "$NC" "${labels[$((i - 1))]}" >&2
    done
    line ""
    local choice; choice="$(ask "Select" "1")"
    [[ "$choice" =~ ^[0-9]+$ ]] || { printf '%s' "${tags[0]}"; return 0; }
    printf '%s' "${tags[$(((choice - 1) % ${#tags[@]}))]}"
}
