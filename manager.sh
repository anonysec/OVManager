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
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.2.8"
COMPOSE_FILE="$DATA_DIR/ovmanager-compose.yml"
INSTALLER="$INSTALL_DIR/install.sh"
# Installed command names (same as the installer used).
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
CLI_NAME="ovmanager"
CLI_ALIAS="ovm"

# Shared helpers (output, prompts, TLS, menus). REPO fallback lets this
# script run straight from a checkout (./manager.sh) as well as installed.
if [[ -f "$INSTALL_DIR/lib/common.sh" ]]; then
    # shellcheck disable=SC1091
    . "$INSTALL_DIR/lib/common.sh"
elif [[ -f "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh" ]]; then
    # shellcheck disable=SC1091
    . "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
else
    printf '\n  Error: lib/common.sh not found (looked in %s/lib and ./lib)\n\n' "$INSTALL_DIR" >&2
    exit 1
fi

# ── Flags (defaults) ───────────────────────────────────────────────────
PORT="" ADMIN_PASS="" MODE="" PIN=""
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
ACTION=""
YES=0 PURGE=0 JSON=0 FIX=0
LOGS_ARG=""
AUTO_BACKUP_ACTION="" BACKUP_TIME="" BACKUP_KEEP=""
OPERATION_LOCK="${DATA_DIR}/.operation.lock"
OPERATION_LOCK_HELD=0

operation_begin() {
    local name="$1" owner=""
    mkdir -p "$DATA_DIR"
    if ! mkdir "$OPERATION_LOCK" 2>/dev/null; then
        owner="$(cat "$OPERATION_LOCK/pid" 2>/dev/null || true)"
        if [[ "$owner" =~ ^[0-9]+$ ]] && ! kill -0 "$owner" 2>/dev/null; then
            warn "Removing stale operation lock from process $owner"
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





# Interactive if the operator did not pass -y AND we can talk to a terminal.
# `curl | bash` has no stdin TTY; humans still work via /dev/tty.
# AI / CI must pass -y (or CI=true) so this never blocks on a prompt.

# Stronger check for the interactive menu: stdin must be a real terminal or
# an openable /dev/tty. Scripts and pipes take the subcommand path instead.

# Masked input: prints one * per character on stderr, backspace works, and
# the value goes to stdout (never echoed as plain text). Reads stdin, so
# callers redirect /dev/tty when needed.




# Explicit-yes prompt (default NO): used for destructive extras like deleting
# data during uninstall. Non-interactive runs keep the safe answer.





# ── OS ─────────────────────────────────────────────────────────────────
OS_ID="" OS_NAME="" PKG_INSTALL="" PKG_UPDATE=""



has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }

check_root() { [[ "$EUID" -eq 0 ]] || die "Must run as root (sudo)."; }

# ── Spinner / steps ────────────────────────────────────────────────────

# ── Deps ───────────────────────────────────────────────────────────────
UV_BIN=""





# ── Backup / firewall / health ─────────────────────────────────────────





# ── TLS ────────────────────────────────────────────────────────────────
# Private keys must never be world-readable. Native mode runs the panel as
# root (600 root-owned is fine); Docker mode runs it as appuser (uid 1000)
# with the files mounted read-only, so the key is owned by that uid. The
# certificate is public and stays 644.






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

# ── Native ─────────────────────────────────────────────────────────────


# ── Docker ─────────────────────────────────────────────────────────────



# ── Validate / wizard / plan ───────────────────────────────────────────
# ── Actions ────────────────────────────────────────────────────────────


do_status() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    # Panel path prefix as written at install time (.env). If it was changed
    # later in Settings → General, the live value lives in the DB instead.
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        PATHPREFIX="$(awk -F= '/^URLPATH=/{print $2; exit}' "$INSTALL_DIR/.env" | tr -d '\r')"
    fi
    local scheme url mode health ver
    scheme="$(scheme_of)"
    if [[ -f "$COMPOSE_FILE" ]]; then mode="docker"; else mode="native"; fi
    url="$(panel_url)"
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 5; then
        health="ok"
    else
        health="unreachable (check logs)"
    fi
    ver="$(curl -fskS --max-time 3 "${scheme}://127.0.0.1:${PORT}/health" 2>/dev/null \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")"
    hr
    kv "Installed" "yes ($INSTALL_DIR)"
    kv "Mode"      "$mode"
    kv "Open"      "$url"
    kv "Health"    "$health"
    kv "Version"   "$ver"
    kv "Data"      "$DATA_DIR"
    hr
    if [[ "$JSON" -eq 1 ]]; then
        python3 - "$mode" "$url" "$health" "$ver" "$INSTALL_DIR" "$DATA_DIR" "$PORT" <<'PY'
import json, sys
mode, url, health, ver, install, data, port = sys.argv[1:]
print(json.dumps({
    "ok": health == "ok",
    "installed": True,
    "mode": mode,
    "url": url,
    "health": health,
    "version": ver,
    "install_dir": install,
    "data_dir": data,
    "port": int(port),
}, ensure_ascii=False, indent=2))
PY
    fi
}

# Mirrors the panel's boot-time validation (backend/config.py): >= 12 chars
# and no placeholder-looking values.
# Empty output = acceptable; otherwise the human-readable reason.


# Interactive re-prompt until the typed password passes the panel's rules
# (max 3 tries, then fail fast — never install a password the panel rejects).

# Recovery for a lost owner password: rewrite only ADMIN_PASSWORD= in the
# installed .env, restart, then wait for /health. Never echoes the password.
do_reset_password() {
    if [[ -n "$ADMIN_PASS" ]]; then
        validate_admin_password "$ADMIN_PASS"
    fi
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing) — nothing to reset."
    local envfile="$INSTALL_DIR/.env"
    [[ -f "$envfile" ]] || die "Config not found: $envfile — install OVManager first."
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"

    if [[ -z "$ADMIN_PASS" ]]; then
        can_prompt || die "No password given. Use: $0 reset-password --admin-pass 'new-password'  (or set OVM_ADMIN_PASS)"
        line ""
        local p1 p2
        p1="$(ask "New password" "" "h")"
        p2="$(ask "Confirm password" "" "h")"
        [[ "$p1" == "$p2" ]] || die "Passwords do not match."
        ADMIN_PASS="$p1"
        validate_admin_password "$ADMIN_PASS"
    fi

    # Store the password as a bcrypt hash (ADMIN_PASSWORD_HASH) and drop the
    # legacy plaintext line. Falls back to plaintext mode only when the
    # panel's Python (bcrypt) is not available.
    local pass_line="ADMIN_PASSWORD=$ADMIN_PASS"
    local pybin="$INSTALL_DIR/.venv/bin/python"
    [[ "$MODE" == "docker" ]] && pybin="docker exec ovmanager /app/.venv/bin/python"
    if [[ -x "$INSTALL_DIR/.venv/bin/python" || "$MODE" == "docker" ]]; then
        local h
        if h="$(HASH_SRC="$ADMIN_PASS" $pybin - <<'PY' 2>/dev/null
import os, sys
sys.path.insert(0, "/app" if os.path.isdir("/app") else ".")
try:
    from backend.auth.hash import hash_password
    print(hash_password(os.environ["HASH_SRC"]))
except Exception:
    sys.exit(1)
PY
)"; then
            [[ -n "$h" ]] && pass_line="ADMIN_PASSWORD_HASH=$h"
        fi
    fi
    [[ "$pass_line" == ADMIN_PASSWORD_HASH=* ]] \
        && step "Password hashed (bcrypt) — no plaintext in .env" \
        || warn "bcrypt unavailable — writing plaintext (it will be hashed on first panel boot)."

    [[ -w "$envfile" ]] || die "Config $envfile is not writable — chmod 600 $envfile and retry."
    local tmp
    tmp="$(mktemp "${envfile}.XXXXXX")" || die "Could not create a temp file next to $envfile"
    # Value rides in the environment, not in an awk -v assignment: passwords
    # may contain backslashes and -v would interpret them. Only the
    # ADMIN_PASSWORD(_HASH) line changes; every other line is copied verbatim.
    if ! NEWLINE="$pass_line" awk '
        BEGIN { nl = ENVIRON["NEWLINE"] }
        /^ADMIN_PASSWORD=/ { found = 1; next }
        /^ADMIN_PASSWORD_HASH=/ { print nl; hashfound = 1; next }
        { print }
        END { if (!hashfound && found) print nl; if (!found && !hashfound) exit 1 }
    ' "$envfile" > "$tmp"; then
        rm -f "$tmp"
        die "Could not update $envfile (no ADMIN_PASSWORD= line?)"
    fi
    chown --reference="$envfile" "$tmp" 2>/dev/null || true
    chmod 600 "$tmp"
    if ! mv -f "$tmp" "$envfile" 2>/dev/null; then
        rm -f "$tmp"
        die "Could not replace $envfile — is it read-only?"
    fi
    step "Config updated  $envfile (0600)"

    # A failed restart must not hide the successful password change: warn
    # and still report the new credentials/login URL.
    if [[ -f "$COMPOSE_FILE" ]]; then
        if command -v docker >/dev/null 2>&1 && docker restart ovmanager >/dev/null 2>&1; then
            step "Container restarted  ovmanager"
        else
            warn "Could not restart the container — run: docker restart ovmanager"
        fi
    else
        systemctl_bounded restart
        if systemctl is-active --quiet "$SYSTEMD_SERVICE"; then
            step "Service restarted  $SYSTEMD_SERVICE"
        else
            warn "Could not restart $SYSTEMD_SERVICE — run: systemctl restart $SYSTEMD_SERVICE"
        fi
    fi

    local scheme url admin
    scheme="$(scheme_of)"
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 12 \
        || warn "No answer on /health yet — check the logs (install.sh status)"
    # Same source as `status`: URLPATH from .env (a later Settings change
    # lives in the DB, not here).
    PATHPREFIX="$(awk -F= '/^URLPATH=/{print $2; exit}' "$envfile" | tr -d '\r')"
    url="$(panel_url)"
    admin="$(awk -F= '/^ADMIN_USERNAME=/{print $2; exit}' "$envfile" | tr -d '\r')"
    [[ -n "$admin" ]] || admin="$DEFAULT_USER"
    line ""
    hr
    kv "Password" "${GR}updated${NC}"
    kv "Login"    "${WH}${admin}${NC}"
    kv "Open"     "${WH}${url}${NC}"
    hr
    line ""
}

# Update and uninstall live in install.sh — delegate so there is exactly one
# implementation. Machine flags pass through (stdout JSON contract kept).
run_installer() {
    [[ -e "$INSTALL_DIR" ]] || [[ "$1" == "uninstall" ]] || die "Not installed ($INSTALL_DIR missing)"
    [[ -x "$INSTALLER" ]] || die "Installer missing ($INSTALLER)"
    exec "$INSTALLER" "$@"
}

delegate_update() {
    local args=()
    [[ "$YES" -eq 1 ]] && args+=(-y)
    [[ "$JSON" -eq 1 ]] && args+=(-j)
    [[ -n "$PIN" ]] && args+=(-v "$PIN")
    run_installer update "${args[@]}"
}

delegate_uninstall() {
    local args=()
    [[ "$YES" -eq 1 ]] && args+=(-y)
    [[ "$JSON" -eq 1 ]] && args+=(-j)
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
        enable) step "Automatic start enabled" ;;
        disable) step "Automatic start disabled (the running panel was not stopped)" ;;
        *) step "Panel $1: done" ;;
    esac
}

restart_service() {
    service_action restart >/dev/null 2>&1 || warn "Restart failed — check the service manually"
}

show_logs() {
    local arg="${1:-100}"
    if is_docker_mode; then
        if [[ "$arg" == "-f" ]]; then docker logs -f --tail 100 ovmanager; else docker logs --tail "$arg" ovmanager; fi \
            || warn "Could not read container logs"
    elif [[ "$arg" == "-f" ]]; then
        journalctl -u "$SYSTEMD_SERVICE" -n 100 -f || warn "Could not read logs"
    else
        journalctl -u "$SYSTEMD_SERVICE" -n "$arg" --no-pager || warn "Could not read logs"
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

backup_now() {
    operation_begin backup
    mkdir -p "$DATA_DIR"
    local created="" keep="${BACKUP_KEEP:-14}"
    if is_docker_mode; then
        created="$(docker exec ovmanager /app/.venv/bin/python -c \
            "from backend.routers.maintenance import create_panel_backup; p=create_panel_backup(${keep}); print(p or '')" 2>/dev/null)" \
            || { operation_end; die "Backup failed — check: docker logs ovmanager"; }
    else
        [[ -x "$INSTALL_DIR/.venv/bin/python" ]] || { operation_end; die "Panel Python environment not found"; }
        created="$(cd "$INSTALL_DIR" && .venv/bin/python -c \
            "from backend.routers.maintenance import create_panel_backup; p=create_panel_backup(${keep}); print(p or '')" 2>/dev/null)" \
            || { operation_end; die "Backup failed — run: ovm doctor"; }
    fi
    operation_end
    [[ -n "$created" ]] || die "Backup skipped because the panel database was not found"
    step "Verified backup  $created"
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
            step "Auto backup enabled: daily at ${time}, keeping ${keep} tarballs"
            ;;
        off)
            systemctl disable --now ovmanager-backup.timer >/dev/null 2>&1 || true
            rm -f "$timer" "$service"
            systemctl daemon-reload >/dev/null 2>&1 || true
            step "Auto backup disabled (host timer removed)"
            ;;
        status|"")
            if [[ -f "$timer" ]]; then
                info "Host timer: enabled ($(systemctl is-active ovmanager-backup.timer 2>/dev/null || echo unknown))"
                systemctl list-timers ovmanager-backup.timer --no-pager 2>/dev/null | sed -n '2p' || true
            else
                info "Host timer: disabled  (enable: ovm auto-backup on)"
            fi
            info "Panel schedule is separate and configured in Settings → Advanced → Backup."
            ;;
        *)
            die "Usage: $CLI_NAME auto-backup on [--time HH:MM] [--keep N] | off | status" ;;
    esac
}


show_login_info() {
    local user path port ip url
    user="$(env_get "$INSTALL_DIR/.env" ADMIN_USERNAME)"; : "${user:=admin}"
    path="$(env_get "$INSTALL_DIR/.env" URLPATH)"
    port="$(env_get "$INSTALL_DIR/.env" PORT)"; : "${port:=$DEFAULT_PORT}"
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    if [[ -n "$path" ]]; then url="https://${ip}:${port}/${path}/"; else url="https://${ip}:${port}/"; fi
    kv "URL"   "$url"
    kv "Login" "$user"
    info "Password: the one you set (or the generated one saved at install)."
    info "If the URL 404s, the live path may differ — change it in Settings → General."
}

reset_urlpath_now() {
    if is_docker_mode; then
        docker exec ovmanager /app/.venv/bin/python main.py --reset-urlpath || die "Reset failed"
    else
        ( cd "$INSTALL_DIR" && .venv/bin/python main.py --reset-urlpath ) || die "Reset failed"
    fi
    step "Panel path reset — the panel is served at / again"
}

do_tls_menu() {
    local envfile="$INSTALL_DIR/.env"
    [[ -f "$envfile" ]] || die "Not installed ($envfile missing)"
    local key cert expiry
    key="$(env_get "$envfile" SSL_KEYFILE)"
    cert="$(env_get "$envfile" SSL_CERTFILE)"
    expiry="$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2 || true)"
    line ""
    line "${B}HTTPS certificate${NC}"
    kv "Key file"  "${key:-<none>}"
    kv "Cert file" "${cert:-<none>}"
    [[ -n "$expiry" ]] && kv "Expires" "$expiry"
    line ""
    line "  1) Self-signed (regenerate)"
    line "  2) Let's Encrypt for a domain"
    line "  3) Let's Encrypt for this IP"
    line "  4) Custom key + cert paths"
    line "  0) Back"
    local c; c="$(ask "Select" "0")"
    case "${c:-0}" in
        1) TLS_MODE="self" ;;
        2) TLS_MODE="le"; TLS_DOMAIN="$(ask "Domain" "")"
           [[ -n "$TLS_DOMAIN" ]] || { warn "Domain required"; return 0; } ;;
        3) TLS_MODE="le-ip"; TLS_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')" ;;
        4) TLS_MODE="custom"; TLS_KEY="$(ask "Key file" "")"; TLS_CERT="$(ask "Cert file" "")"
           [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || { warn "Key/cert files not found"; return 0; } ;;
        0|*) return 0 ;;
    esac
    operation_begin https-certificate
    if ! setup_tls; then operation_end; return 0; fi
    env_set "$envfile" SSL_KEYFILE "$TLS_KEY"
    env_set "$envfile" SSL_CERTFILE "$TLS_CERT"
    step "Certificate updated"
    restart_service
    operation_end
    return 0
}

do_recovery_menu() {
    while true; do
        line ""
        line "${B}Recovery${NC}"
        line "  1) Show panel URL and login"
        line "  2) Reset the owner password"
        line "  3) Reset the panel URL path"
        line "  0) Back"
        local c; c="$(ask "Select" "0")"
        case "${c:-0}" in
            1) show_login_info ;;
            2) do_reset_password ;;
            3) reset_urlpath_now ;;
            0|*) return 0 ;;
        esac
    done
}


# ── Health check (doctor) ────────────────────────────────────────────
# Read-only by default; --fix applies only safe automatic fixes
# (restart a dead service, prune old backups).
do_doctor() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    [[ "$FIX" -eq 1 ]] && operation_begin doctor-fix
    read_env_port
    : "${PORT:=$DEFAULT_PORT}"
    local problems=0
    hr
    line "${B}Panel health${NC}"
    # 1. Service.
    local svc="unknown"
    if [[ -f "$COMPOSE_FILE" ]]; then
        if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx ovmanager; then svc="running (docker)"; fi
    elif has_systemd; then
        svc="$(systemctl is-active "$SYSTEMD_SERVICE" 2>/dev/null || echo unknown)"
    fi
    if [[ "$svc" == *"running"* || "$svc" == "active" ]]; then
        kv "Service" "${GR}$svc${NC}"
    else
        kv "Service" "${RD}$svc${NC}"
        warn "Fix: ovm restart"
        problems=$((problems + 1))
        if [[ "$FIX" -eq 1 ]]; then
            info "Restarting the service…"
            restart_service && svc="active" && problems=$((problems - 1)) || true
        fi
    fi
    # 2. Automatic start.
    local autostart
    autostart="$(service_autostart_status)"
    if [[ "$autostart" == "enabled" ]]; then
        kv "Auto start" "${GR}enabled${NC}"
    else
        kv "Auto start" "${YL}disabled${NC}"
        warn "Fix: ovm enable"
        problems=$((problems + 1))
        if [[ "$FIX" -eq 1 ]]; then
            if [[ "$EUID" -eq 0 ]]; then
                service_action enable && problems=$((problems - 1)) || true
            else
                warn "Automatic start needs root — rerun: sudo ovm doctor --fix"
            fi
        fi
    fi
    # 3. Disk.
    local disk
    disk="$(df "$DATA_DIR" 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%' || echo 0)"
    if (( disk < 80 )); then
        kv "Disk" "${GR}${disk}% used${NC}"
    else
        kv "Disk" "${YL}${disk}% used${NC}"
        warn "Fix: ovm backup --keep 7, then remove old tarballs in /var/backups"
        problems=$((problems + 1))
        if [[ "$FIX" -eq 1 ]]; then
            prune_backups 7 && problems=$((problems - 1)) || true
        fi
    fi
    # 3. Panel answers.
    local scheme ver="?"
    scheme="$(scheme_of)"
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 5; then
        ver="$(curl -fskS --max-time 3 "${scheme}://127.0.0.1:${PORT}/health" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")"
        kv "Panel" "${GR}ok (v$ver)${NC}"
    else
        kv "Panel" "${RD}unreachable${NC}"
        warn "Fix: ovm logs 50, then ovm restart"
        problems=$((problems + 1))
    fi
    # 4. TLS certificate expiry.
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        local cert days_left
        cert="$(env_get "$INSTALL_DIR/.env" SSL_CERTFILE)"
        if [[ -n "$cert" && -f "$cert" ]]; then
            days_left=$(( ($(date -d "$(openssl x509 -enddate -noout -in "$cert" 2>/dev/null | cut -d= -f2)" +%s 2>/dev/null || echo 0) - $(date +%s)) / 86400 ))
            if (( days_left > 30 )); then
                kv "Certificate" "${GR}expires in ${days_left}d${NC}"
            elif (( days_left > 0 )); then
                kv "Certificate" "${YL}expires in ${days_left}d${NC}"
                warn "Fix: ovm https"
                problems=$((problems + 1))
            else
                kv "Certificate" "${RD}expired${NC}"
                warn "Fix: ovm https"
                problems=$((problems + 1))
            fi
        else
            kv "Certificate" "${YL}not found${NC}"
            problems=$((problems + 1))
        fi
    fi
    # 6. Interrupted update journal / write-block marker. A non-terminal
    # journal also counts when a crash happened before the marker was flushed.
    local update_interrupted=0
    [[ -f "$DATA_DIR/update-maintenance" ]] && update_interrupted=1
    if [[ "$update_interrupted" -eq 0 && -f "$DATA_DIR/update-state.json" ]]; then
        python3 - "$DATA_DIR/update-state.json" <<'PY' >/dev/null 2>&1 || update_interrupted=1
import json, sys
phase = json.load(open(sys.argv[1])).get("phase")
raise SystemExit(0 if phase in {"committed", "failed_over"} else 1)
PY
    fi
    if [[ "$update_interrupted" -eq 1 ]]; then
        kv "Update" "${YL}recovery required${NC}"
        warn "Fix: ovm recover-update"
        problems=$((problems + 1))
        if [[ "$FIX" -eq 1 ]]; then
            info "Recovering the interrupted update…"
            if "$INSTALLER" recover-update; then
                problems=$((problems - 1))
            else
                warn "Update recovery needs manual attention"
            fi
        fi
    else
        kv "Update" "${GR}no interrupted transaction${NC}"
    fi
    # 7. Backup age (legacy tarballs and the transactional .ovmbak format).
    local newest age
    newest="$(ls -t /var/backups/panel-*.tar.gz "$DATA_DIR"/backups/*.ovmbak 2>/dev/null | head -1 || true)"
    if [[ -n "$newest" ]]; then
        age=$(( ($(date +%s) - $(stat -c %Y "$newest" 2>/dev/null || echo 0)) / 86400 ))
        if (( age <= 7 )); then
            kv "Backup" "${GR}${age}d old${NC}"
        else
            kv "Backup" "${YL}${age}d old${NC}"
            warn "Fix: ovm backup"
            problems=$((problems + 1))
        fi
    else
        kv "Backup" "${YL}none yet${NC}"
        warn "Fix: ovm backup"
        problems=$((problems + 1))
    fi
    # 8. Private file permissions (native only — Docker data belongs to
    # uid 1000 inside the container, so only report there).
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        local perm_bad=""
        [[ "$(stat -c %a "$DATA_DIR" 2>/dev/null || echo 0)" == "700" ]] || perm_bad="data dir"
        [[ ! -d "$DATA_DIR/backups" ]] || [[ "$(stat -c %a "$DATA_DIR/backups" 2>/dev/null || echo 0)" == "700" ]] || perm_bad="backups dir"
        local pf
        for pf in "$DATA_DIR"/ovmanager.db "$DATA_DIR"/update-state.json "$DATA_DIR"/update-maintenance; do
            [[ ! -f "$pf" ]] || [[ "$(stat -c %a "$pf" 2>/dev/null || echo 0)" == "600" ]] || perm_bad="$pf"
        done
        if [[ -z "$perm_bad" ]]; then
            kv "Permissions" "${GR}private${NC}"
        else
            kv "Permissions" "${YL}loose ($perm_bad)${NC}"
            warn "Fix: ovm doctor --fix"
            problems=$((problems + 1))
            if [[ "$FIX" -eq 1 ]]; then
                chmod 700 "$DATA_DIR" 2>/dev/null || true
                [[ ! -d "$DATA_DIR/backups" ]] || chmod 700 "$DATA_DIR/backups" 2>/dev/null || true
                chmod 600 "$DATA_DIR"/ovmanager.db "$DATA_DIR"/update-state.json "$DATA_DIR"/update-maintenance 2>/dev/null || true
                perm_bad=""
                [[ "$(stat -c %a "$DATA_DIR" 2>/dev/null || echo 0)" == "700" ]] || perm_bad="data dir"
                for pf in "$DATA_DIR"/ovmanager.db "$DATA_DIR"/update-state.json "$DATA_DIR"/update-maintenance; do
                    [[ ! -f "$pf" ]] || [[ "$(stat -c %a "$pf" 2>/dev/null || echo 0)" == "600" ]] || perm_bad="$pf"
                done
                [[ -z "$perm_bad" ]] && problems=$((problems - 1)) || warn "Some permissions could not be tightened"
            fi
        fi
    fi
    hr
    if (( problems == 0 )); then
        step "Healthy — nothing to fix"
    else
        warn "$problems problem(s) found"
    fi
    [[ "$FIX" -eq 1 ]] && operation_end
    return 0
}

# Roll back to the newest pre-update code snapshot (update failover).
do_rollback() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    local snap
    snap="$(latest_snapshot panel)"
    [[ -n "$snap" ]] || die "No code snapshot in /var/backups — nothing to roll back to"
    check_root
    info "Rolling back to: $snap"
    [[ "$YES" -eq 1 ]] || confirm "Restore the pre-update tree and restart?" || die "Cancelled."
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
            || warn "Could not start the container — docker logs ovmanager"
    else
        run_step "Service restarted" systemctl_bounded restart
    fi
    if wait_health "${scheme}://127.0.0.1:${PORT}/health" 60; then
        step "Rolled back and healthy"
    else
        die "Rollback did not restore health — snapshot at $snap, data backups in /var/backups. Check logs."
    fi
}

# ── Usage / args / menu / main ─────────────────────────────────────────
usage() {
    cat << EOF >&2
  ovmanager — OVManager panel manager v${VERSION} (alias: ovm)

  USAGE
    ovm                         Interactive numbered menu
    ovm status                  Show panel URL, health and version
    ovm update                  Staged update with automatic failover
    ovm recover-update          Recover an interrupted update transaction
    ovm restart                 Restart the panel service
    ovm enable|disable          Enable/disable automatic start
    ovm logs [N|-f]             Last N log lines (default 100), or follow
    ovm backup [--keep N]       Save a data backup now
    ovm https                   Show/replace the HTTPS certificate
    ovm tls                     Compatibility alias for ovm https
    ovm recovery                Login info, owner password, URL path
    ovm reset-password          Set a new owner password, then restart
    ovm doctor [--fix]          Health check (service, disk, cert, backups)
    ovm rollback                Restore the newest pre-update code snapshot
    ovm uninstall [--purge]     Remove the app (data kept unless --purge)

  OPTIONS
    -p, --pass PASS     reset-password: new owner password (min 12,
                        not a common word)
    -y, --yes           Never prompt
    -j, --json          Machine-readable result on stdout (logs on stderr)
    --fix               doctor: apply safe automatic fixes
    --purge             uninstall: also delete data + certs
    -h, --help          This help

  ENVIRONMENT
    OVM_APP_DIR   installed tree (default /opt/ovmanager, tests override)
    OVM_PASS      same as --pass
    CI=true       implies -y

  Update and uninstall are implemented in install.sh — this script
  delegates to \$INSTALL_DIR/install.sh so there is exactly one copy.
EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -p|--pass)    [[ $# -ge 2 ]] || die "-p needs a password"; ADMIN_PASS="$2"; shift 2 ;;
            -y|--yes) YES=1; shift ;;
            -j|--json) JSON=1; shift ;;
            --fix) FIX=1; shift ;;
            --purge) PURGE=1; shift ;;
            -v|--version) [[ $# -ge 2 ]] || die "--version needs vX.Y.Z"; PIN="$2"; shift 2 ;;
            --keep) [[ $# -ge 2 ]] || die "--keep needs a number"; BACKUP_KEEP="$2"; shift 2 ;;
            --time) [[ $# -ge 2 ]] || die "--time needs HH:MM"; BACKUP_TIME="$2"; shift 2 ;;
            -h|--help) usage ;;
            help) usage ;;
            status) ACTION="status"; shift ;;
            start|stop|restart|enable|disable) ACTION="$1"; shift ;;
            logs) ACTION="logs"
                if [[ $# -ge 2 && ( "$2" == "-f" || "$2" =~ ^[0-9]+$ ) ]]; then
                    LOGS_ARG="$2"; shift 2
                else
                    shift
                fi ;;
            backup) ACTION="backup"; shift ;;
            auto-backup) ACTION="auto-backup"; shift
                if [[ $# -ge 1 && "$1" != -* ]]; then AUTO_BACKUP_ACTION="$1"; shift; fi ;;
            https|tls) ACTION="https"; shift ;;
            recovery) ACTION="recovery"; shift ;;
            reset-password) ACTION="reset-password"; shift ;;
            reset-urlpath) ACTION="reset-urlpath"; shift ;;
            doctor) ACTION="doctor"; shift ;;
            rollback) ACTION="rollback"; shift ;;
            update) ACTION="update"; shift ;;
            recover-update) ACTION="recover-update"; shift ;;
            uninstall) ACTION="uninstall"; shift ;;
            *) die "Unknown option: $1  (see --help)" ;;
        esac
    done
}

backup_submenu() {
    while true; do
        line ""
        line "${B}Backup${NC}"
        line "  ${WH}1${NC}) Backup now"
        line "  ${WH}2${NC}) Auto-backup status"
        line "  ${WH}3${NC}) Enable daily auto-backup"
        line "  ${WH}4${NC}) Disable auto-backup"
        line "  ${WH}0${NC}) Back"
        line ""
        local c
        c="$(ask "Select" "0")"
        case "${c:-0}" in
            1) check_root; backup_now ;;
            2) auto_backup_cli status ;;
            3) check_root; auto_backup_cli on ;;
            4) check_root; auto_backup_cli off ;;
            0|*) return 0 ;;
        esac
    done
}

service_submenu() {
    while true; do
        line ""
        line "${B}Service${NC}"
        hr
        kv "Auto start" "$(service_autostart_status)"
        line ""
        line "  ${WH}1.${NC} Start"
        line "  ${WH}2.${NC} Stop"
        line "  ${WH}3.${NC} Restart"
        line "  ${WH}4.${NC} Enable automatic start"
        line "  ${WH}5.${NC} Disable automatic start"
        line ""
        line "  ${WH}0.${NC} Back"
        line ""
        local c; c="$(ask "Select" "0")"
        case "${c:-0}" in
            1) check_root; service_action start ;;
            2) check_root; confirm_no "Stop OVManager?" && service_action stop ;;
            3) check_root; service_action restart ;;
            4) check_root; service_action enable ;;
            5) check_root; service_action disable ;;
            0) return 0 ;;
            *) warn "Choose a number from 0 to 5." ;;
        esac
    done
}

# Grouped numbered menu: full power, one screen, nothing hidden.
manager_menu() {
    while true; do
        line ""
        line "${B}OVManager${NC}  ${GY}v${VERSION}${NC}"
        hr
        line ""
        line "  ${WH}1.${NC} Status"
        line "  ${WH}2.${NC} Service"
        line "  ${WH}3.${NC} Logs"
        line "  ${WH}4.${NC} Update"
        line "  ${WH}5.${NC} Backups"
        line "  ${WH}6.${NC} HTTPS certificate"
        line "  ${WH}7.${NC} Diagnostics and repair"
        line "  ${WH}8.${NC} Recovery"
        line "  ${WH}9.${NC} Uninstall"
        line ""
        line "  ${WH}0.${NC} Exit"
        line ""
        local c
        c="$(ask "Select" "0")"
        case "${c:-0}" in
            1) do_status ;;
            2) service_submenu ;;
            3) show_logs "${LOGS_ARG:-100}" ;;
            4) delegate_update ;;
            5) backup_submenu ;;
            6) check_root; do_tls_menu ;;
            7) do_doctor ;;
            8) check_root; do_recovery_menu ;;
            9) delegate_uninstall ;;
            0) return 0 ;;
            *) warn "Choose a number from 0 to 9." ;;
        esac
    done
}

main() {
    parse_args "$@"
    [[ -z "$ADMIN_PASS" && -n "${OVM_PASS:-}" ]] && ADMIN_PASS="$OVM_PASS"
    if [[ "$JSON" -eq 1 ]]; then YES=1; fi
    if [[ -z "$ACTION" ]]; then
        if can_prompt; then
            manager_menu
            exit 0
        fi
        die "No terminal — run 'ovm help' for the command list."
    fi
    case "$ACTION" in
        status) do_status; exit 0 ;;
        start|stop|restart|enable|disable) check_root; service_action "$ACTION"; exit 0 ;;
        logs) show_logs "${LOGS_ARG:-100}"; exit 0 ;;
        backup) check_root; backup_now; exit 0 ;;
        auto-backup) check_root; auto_backup_cli "$AUTO_BACKUP_ACTION"; exit 0 ;;
        https) check_root; do_tls_menu; exit 0 ;;
        recovery) check_root; do_recovery_menu; exit 0 ;;
        reset-password)
            # Validate before the root gate so bad input fails the same
            # way for root and non-root callers (CI runs non-root).
            [[ -n "$ADMIN_PASS" ]] && validate_admin_password "$ADMIN_PASS"
            check_root; do_reset_password; exit 0 ;;
        reset-urlpath) check_root; reset_urlpath_now; exit 0 ;;
        doctor) do_doctor; exit 0 ;;
        rollback) do_rollback; exit 0 ;;
        update) delegate_update; exit 0 ;;
        recover-update) run_installer recover-update; exit 0 ;;
        uninstall) delegate_uninstall; exit 0 ;;
    esac
}

main "$@"
