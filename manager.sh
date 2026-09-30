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
VERSION="1.0.0"

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

# Shared helpers (output, prompts, TLS, menus). REPO fallback lets this
# script run straight from a checkout (./manager.sh) as well as installed.
# scripts/lib is the simulated installer repo: one file per concern.
for _cand in "$INSTALL_DIR/scripts/lib" "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/scripts/lib"; do
    if [[ -d "$_cand" ]]; then
        for _lib in "$_cand"/common.sh "$_cand"/render.sh "$_cand"/prompt.sh "$_cand"/env.sh "$_cand"/system.sh "$_cand"/backup.sh "$_cand"/tls.sh "$_cand"/policy.sh; do
            # shellcheck disable=SC1090
            . "$_lib"
        done
        _lib_found=1
        break
    fi
done
if [[ "${_lib_found:-0}" -ne 1 ]]; then
    printf '\n  Error: scripts/lib not found (looked in %s/scripts/lib and ./scripts/lib)\n\n' "$INSTALL_DIR" >&2
    exit 1
fi
unset _cand _lib _lib_found

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
        can_prompt || die "No password given. Use: $0 reset-password -p 'new-password'  (or set OVM_PASS)"
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
            if [[ -f "$timer" ]]; then
                render_note "Host timer: enabled ($(systemctl is-active ovmanager-backup.timer 2>/dev/null || echo unknown))"
                systemctl list-timers ovmanager-backup.timer --no-pager 2>/dev/null | sed -n '2p' || true
            else
                render_note "Host timer: disabled  (enable: ovm auto-backup on)"
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
            die "Pick a mode: --self, --domain <name>, --ip, or --key <file> --cert <file>. Read the current certificate with: ovm tls-status" ;;
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
        render_warn "To change the password instead: ovm reset-password"
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
completion help tls-status https recovery owner-claim reset-password reset-urlpath \
recover-update"
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
            logs) ACTION="logs"
                if [[ $# -ge 2 && ( "$2" == "-f" || "$2" =~ ^[0-9]+$ ) ]]; then
                    LOGS_ARG="$2"; shift 2
                else
                    shift
                fi ;;
            backup) ACTION="backup"; shift
                if [[ "$1" == "schedule" ]]; then
                    ACTION="auto-backup"; AUTO_BACKUP_ACTION="status"; shift 2
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
cmd_doctor() { _cli_py doctor; }

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
    if ! is_docker_mode; then _cli_py doctor-fix; return $?; fi
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
