#!/usr/bin/env bash
# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT
#
# OVManager installer — bootstraps the Go binary (PasarGuard-style).
#
set -Eeuo pipefail

REPO="${OVM_REPO:-anonysec/OVManager}"
APP_SLUG="ovmanager"
INSTALL_DIR="${OVM_INSTALL_DIR:-/opt/ovmanager}"
DATA_DIR="${OVM_DATA_DIR:-/var/lib/ovmanager}"
DEFAULT_PORT="${OVM_DEFAULT_PORT:-2095}"
DEFAULT_URLPATH="${OVM_DEFAULT_URLPATH:-dashboard}"
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="${OVM_VERSION:-2.4.6}"
IMAGE_REPO="${OVM_IMAGE_REPO:-ghcr.io/anonysec/ovmanager}"
if [[ -f internal/version/version.go ]]; then
    VERSION=$(grep -E '^const Version = ' internal/version/version.go | sed -E 's/.*"([^"]+)".*/\1/')
fi
BIN_DIR="${OVM_BIN_DIR:-/usr/local/bin}"
PANEL_USER="${OVM_PANEL_USER:-ovmanager}"
CLI_NAME="ovmanager"

PORT_VAL="${OVM_PORT:-$DEFAULT_PORT}"
URLPATH_VAL="${OVM_URLPATH:-$DEFAULT_URLPATH}"
HEALTH_TIMEOUT="${OVM_HEALTH_TIMEOUT:-40}"
ACME_TIMEOUT="${OVM_ACME_TIMEOUT:-60}"
INTERACTIVE=0
YES=0
FROM_SOURCE=0
DOCKER="${OVM_DOCKER:-1}"
DOCKER_EXPLICIT=0
SRC=""
DEST=""
ACTION="install"
ACTION_GIVEN=0
UPDATE_ARGS=()

SSL_MODE="${OVM_SSL_MODE:-}"
SSL_DOMAIN="${OVM_ACME_DOMAIN:-}"
SSL_CERT_SRC=""
# ── Atomic shared-lib bootstrap (PasarGuard style) ───────────────────
# Shared helpers live in lib/common.sh. For a checkout they sit beside this
# script; for an installed copy they live under /usr/local/lib/ovmanager-scripts/lib.
# All files are staged first and only swapped in if EVERY download succeeds, so
# a partial/failed refresh never leaves a half-updated set.
SHARED_LIB_DIR=""
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh" ]]; then
    SHARED_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")/lib"
else
    SHARED_LIB_DIR="/usr/local/lib/ovmanager-scripts/lib"
fi

REQUIRED_SHARED_LIBS="common.sh"
bootstrap_shared_libs() {
    local fetch_repo="anonysec/OVManager"
    local bootstrap_dir="/usr/local/lib/ovmanager-scripts/lib"
    local tmp_dir=""
    tmp_dir=$(mktemp -d) || return 1
    if ! curl -fsSL --connect-timeout 5 "https://github.com/${fetch_repo}/raw/main/lib/common.sh" -o "$tmp_dir/common.sh"; then
        rm -rf "$tmp_dir"; return 1
    fi
    mkdir -p "$bootstrap_dir" || { rm -rf "$tmp_dir"; return 1; }
    if ! install -m 644 "$tmp_dir/common.sh" "$bootstrap_dir/common.sh"; then
        rm -rf "$tmp_dir"; return 1
    fi
    rm -rf "$tmp_dir"
    SHARED_LIB_DIR="$bootstrap_dir"
    return 0
}

# For an installed copy, refresh shared libs best-effort (PasarGuard style).
if [[ ! -f "$SHARED_LIB_DIR/common.sh" ]]; then
    bootstrap_shared_libs || true
fi
if [[ ! -f "$SHARED_LIB_DIR/common.sh" ]]; then
    echo "Missing shared library: $SHARED_LIB_DIR/common.sh" >&2
    exit 1
fi
# shellcheck source=lib/common.sh
source "$SHARED_LIB_DIR/common.sh"

prompt_interactive() {
    [[ "$INTERACTIVE" -eq 1 && "$YES" -eq 0 ]] || return 0
    [[ -t 0 ]] || return 0
    render_note "Press Enter to keep the bracketed default."
    local in_port in_path
    in_port="$(ask "panel port" "$PORT_VAL")"
    if [[ -n "${in_port// /}" ]]; then
        in_port="${in_port// /}"
        if validate_port "$in_port"; then PORT_VAL="$in_port"; else render_warn "Invalid port '$in_port', using default $PORT_VAL"; fi
    fi
    in_path="$(ask "panel url path" "$URLPATH_VAL")"
    in_path="${in_path// /}"; in_path="${in_path#/}"; in_path="${in_path%/}"
    if [[ -n "$in_path" ]]; then
        if validate_urlpath "$in_path"; then URLPATH_VAL="$in_path"; else render_warn "Invalid URL path '$in_path', using default $URLPATH_VAL"; fi
    fi
}

setup_ssl_wizard() {
    [[ "$INTERACTIVE" -eq 1 && "$YES" -eq 0 ]] || { [[ -n "$SSL_DOMAIN" ]] && SSL_MODE="domain"; return 0; }
    [[ -t 0 ]] || return 0
    render_stage "SSL setup"
    colorized_echo cyan "Choose SSL setup method for panel installation:"
    colorized_echo green "  1) Let's Encrypt Domain certificate"
    colorized_echo green "  2) Let's Encrypt IP certificate (short-lived)"
    colorized_echo green "  3) Custom certificate + key paths"
    colorized_echo yellow "  4) Self-signed certificate (testing)"
    colorized_echo yellow "  5) No SSL"
    colorized_echo yellow "Port 80 (or configured --ssl-http-port) must be reachable for Let's Encrypt."
    local choice
    read -p "Select SSL option [1-5] (default: 1): " choice
    choice="${choice// /}"
    [ -z "$choice" ] && choice="1"
    case "$choice" in
    1)
        SSL_MODE="domain"
        while [[ -z "$SSL_DOMAIN" ]]; do
            SSL_DOMAIN="$(ask "domain for SSL certificate" "")"
            SSL_DOMAIN="${SSL_DOMAIN// /}"
            [[ -z "$SSL_DOMAIN" ]] && { render_fail "domain" "cannot be empty"; continue; }
            is_domain "$SSL_DOMAIN" || { render_fail "domain" "invalid format: $SSL_DOMAIN"; SSL_DOMAIN=""; }
        done
        ;;
    2)
        SSL_MODE="ip"
        local detected_ip input_ip
        detected_ip="$(get_public_ipv4 || true)"
        if [[ -n "$detected_ip" ]]; then
            input_ip="$(ask "IPv4 for SSL certificate" "$detected_ip")"
        else
            input_ip="$(ask "IPv4 for SSL certificate" "")"
        fi
        input_ip="${input_ip// /}"
        if [[ -z "$input_ip" && -n "$detected_ip" ]]; then input_ip="$detected_ip"; fi
        if ! is_ipv4 "$input_ip"; then render_fail "IPv4" "invalid: $input_ip"; SSL_MODE="none"; return 0; fi
        SSL_IP="$input_ip"; INSTALL_IP_SSL=1
        ;;
    3)
        SSL_MODE="custom"
        while true; do
            SSL_CERT_SRC="$(ask "full path to certificate file" "")"
            SSL_CERT_SRC=$(echo "$SSL_CERT_SRC" | tr -d '"' | tr -d "'" | xargs)
            [[ -f "$SSL_CERT_SRC" && -r "$SSL_CERT_SRC" && -s "$SSL_CERT_SRC" ]] && break
            render_fail "certificate" "file not found/readable: $SSL_CERT_SRC"
        done
        while true; do
            SSL_KEY_SRC="$(ask "full path to private key file" "")"
            SSL_KEY_SRC=$(echo "$SSL_KEY_SRC" | tr -d '"' | tr -d "'" | xargs)
            [[ -f "$SSL_KEY_SRC" && -r "$SSL_KEY_SRC" && -s "$SSL_KEY_SRC" ]] && break
            render_fail "private key" "file not found/readable: $SSL_KEY_SRC"
        done
        ;;
    4)
        SSL_MODE="selfsigned"
        SELF_SIGNED_TARGET="$(ask "domain or IP for self-signed cert" "localhost")"
        SELF_SIGNED_TARGET="${SELF_SIGNED_TARGET// /}"
        [[ -z "$SELF_SIGNED_TARGET" ]] && SELF_SIGNED_TARGET="localhost"
        INSTALL_SELF_SIGNED=1
        ;;
    5|*) SSL_MODE="none" ;;
    esac
}

check_acme_domain() {
    [[ -z "$SSL_DOMAIN" ]] && return 0
    if [[ -s "$DATA_DIR/tls/fullchain.pem" && -s "$DATA_DIR/tls/privkey.pem" ]]; then
        local check
        if check="$(openssl x509 -in "$DATA_DIR/tls/fullchain.pem" -noout -checkend 86400 2>/dev/null)" && [[ "$check" == "Certificate will not expire"* ]]; then
            _ok "acme    existing certificate still valid - skipping"
            SSL_DOMAIN=""; SSL_MODE="none"; return 0
        fi
    fi
    if (exec 3<>/dev/tcp/127.0.0.1/80) 2>/dev/null; then
        _warn "port 80 is in use - skipping auto ACME issuance"
        _note "free port 80, then run: ovmanager tls issue $SSL_DOMAIN"
        SSL_DOMAIN=""; SSL_MODE="none"; return 0
    fi
    if is_domain "$SSL_DOMAIN"; then
        _ok "acme    Let's Encrypt issuance scheduled for $SSL_DOMAIN"
    else
        _warn "OVM_ACME_DOMAIN '$SSL_DOMAIN' is not a valid DNS name"
        SSL_DOMAIN=""; SSL_MODE="none"
    fi
}

write_env() {
    local envfile="$1" data_dir="$2"
    if [[ -f "$envfile" ]]; then chmod 600 "$envfile" 2>/dev/null || true; return 0; fi
    mkdir -p "$data_dir"
    (
    umask 077
    {
        printf 'HOST=127.0.0.1\n'
        printf 'PORT=%s\n' "$PORT_VAL"
        printf 'URLPATH=%s\n' "$URLPATH_VAL"
        printf 'ADMIN_USERNAME=%s\n' "$DEFAULT_USER"
        printf 'DATA_DIR=%s\n' "$data_dir"
        if [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]]; then
            printf 'SSL_CERTFILE=%s/tls/fullchain.pem\n' "$data_dir"
            printf 'SSL_KEYFILE=%s/tls/privkey.pem\n' "$data_dir"
            printf 'OVM_ACME_DOMAIN=%s\n' "$SSL_DOMAIN"
            mkdir -p "$data_dir/tls"
        fi
        if [[ "$SSL_MODE" == "custom" ]]; then
            printf 'SSL_CERTFILE=%s\n' "$SSL_CERT_SRC"
            printf 'SSL_KEYFILE=%s\n' "$SSL_KEY_SRC"
        fi
        if [[ "$SSL_MODE" == "ip" || "$SSL_MODE" == "selfsigned" ]]; then
            printf 'SSL_CERTFILE=%s/tls/fullchain.pem\n' "$data_dir"
            printf 'SSL_KEYFILE=%s/tls/privkey.pem\n' "$data_dir"
        fi
    } > "$envfile"
    )
    cat >> "$envfile" <<'OPTS'

# ── Optional (uncomment to use) ────────────────────────────────────────
# PUBLIC_URL=https://panel.example.com
# SSL_CERTFILE=/path/to/fullchain.pem
# SSL_KEYFILE=/path/to/privkey.pem
# TRUSTED_PROXY=false
# OVM_ACME_DOMAIN=
# OVM_ACME_DIRECTORY_URL=
# OVM_ACME_HTTP_PORT=80
# OVM_TRAFFIC_POLL_SECONDS=10
# NODE_TLS_INSECURE_FALLBACK=false
OPTS
    chmod 600 "$envfile"
    chown "root:$PANEL_USER" "$envfile"
    chmod 640 "$envfile"
    _note "$envfile"
}

mint_claim_key() {
    local path="$1" key
    mkdir -p "$(dirname "$path")"
    [[ -f "$path" ]] && return 0
    key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
    ( umask 077; printf '%s\n' "$key" > "$path" )
    chmod 600 "$path"
    chown "$PANEL_USER:$PANEL_USER" "$path"
    printf '%s\n' "$key"
}

ensure_panel_user() {
    mkdir -p "$DATA_DIR"
    if ! id -u "$PANEL_USER" >/dev/null 2>&1; then
        useradd --system --no-create-home --home-dir "$DATA_DIR" --shell /usr/sbin/nologin --comment "OVManager panel service account" "$PANEL_USER" >/dev/null 2>&1 || die "Could not create the $PANEL_USER account"
    fi
    if getent group systemd-journal >/dev/null 2>&1; then
        usermod -a -G systemd-journal "$PANEL_USER" 2>/dev/null || true
    fi
}

unit_hardening() {
    local p
    for p in "$@"; do
        case "$p/" in /tmp/*|/var/tmp/*|/run/*|/home/*|/root/*|/dev/shm/*) return 0 ;; esac
    done
    printf 'NoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\n'
}

write_systemd_unit() {
    local dest="${1:-$INSTALL_DIR}"
    cat > "/etc/systemd/system/$SYSTEMD_SERVICE" <<UNIT
[Unit]
Description=OVManager OpenVPN Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=$dest
EnvironmentFile=$dest/.env
Environment="OVM_APP_DIR=$dest"
User=$PANEL_USER
Group=$PANEL_USER
SupplementaryGroups=systemd-journal
ExecStart=$dest/$APP_SLUG
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
$(unit_hardening "$dest" "$DATA_DIR")

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "/etc/systemd/system/$SYSTEMD_SERVICE"
}
colorized_echo blue "Installing systemd units"; write_systemd_unit "$dest"
    colorized_echo blue "Granting permissions"; grant_panel_access "$dest"
    colorized_echo blue "Installing CLI"; install_cli "$dest"; install_completion "$dest"
    colorized_echo blue "Service"
    systemctl daemon-reload
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then
        systemctl restart "$SYSTEMD_SERVICE" || die "Could not restart $SYSTEMD_SERVICE"
    else
        systemctl enable --now "$SYSTEMD_SERVICE" >/dev/null 2>&1 || die "Could not start $SYSTEMD_SERVICE"
    fi
        _ok "service $SYSTEMD_SERVICE started"
    if [[ "$INSTALL_SELF_SIGNED" -eq 1 ]]; then
        colorized_echo blue "TLS (self-signed)"
        if "$dest/$APP_SLUG" tls selfsigned "${SELF_SIGNED_TARGET:-localhost}" >/dev/null 2>&1; then
            systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
            _ok "self-signed certificate issued for ${SELF_SIGNED_TARGET:-localhost}"
        else
            _warn "self-signed cert issuance failed"
        fi
    fi
    [[ "$SSL_MODE" == "custom" ]] && _ok "custom certificate configured (SSL_CERTFILE=$SSL_CERT_SRC)"
    if [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]]; then
        colorized_echo blue "TLS (Let's Encrypt domain)"
        if "$dest/$APP_SLUG" tls acme "$SSL_DOMAIN" >/dev/null 2>&1; then
            systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
            _ok "certificate issued for $SSL_DOMAIN"
        else
            _warn "domain certificate issuance failed - run 'ovmanager tls acme $SSL_DOMAIN' later"
        fi
    fi
    if [[ "$SSL_MODE" == "ip" && -n "$SSL_IP" ]]; then
        colorized_echo blue "TLS (Let's Encrypt IP)"
        if "$dest/$APP_SLUG" tls acme "$SSL_IP" >/dev/null 2>&1; then
            systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
            _ok "IP certificate step done for $SSL_IP"
        else
            _warn "IP certificate issuance failed - run 'ovmanager tls acme $SSL_IP' later"
        fi
    fi
    port="$(awk -F= -v k=PORT '$1==k{print $2;exit}' "$dest/.env" 2>/dev/null)"; port="${port:-$DEFAULT_PORT}"
    urlpath="$(awk -F= -v k=URLPATH '$1==k{print $2;exit}' "$dest/.env" 2>/dev/null)"; urlpath="${urlpath:-$DEFAULT_URLPATH}"
    colorized_echo blue "Verification"
    verify_health "$port" "$VERSION" || die "The panel did not report v$VERSION on /health after 40s"
    _ok "installed v$VERSION to $dest (service $SYSTEMD_SERVICE, port $port)"
    [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]] && verify_acme "$DATA_DIR"
    offer_node_and_logs native "$port" "$urlpath" "$key"
}

do_update() {
    [[ -x "$INSTALL_DIR/$APP_SLUG" ]] || die "not installed at $INSTALL_DIR — run the installer first"
    exec "$INSTALL_DIR/$APP_SLUG" update "$@"
}
do_status() {
    if [[ ! -d "$INSTALL_DIR" ]]; then render_fail "status" "Not Installed"; return 1; fi
    if command -v systemctl >/dev/null 2>&1; then
        if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then render_ok "Status: Up"; else render_warn "Status: Down"; fi
    else render_ask_note "Status: Unknown (no systemd)"; fi
    [[ -x "$BIN_DIR/$CLI_NAME" ]] && "$BIN_DIR/$CLI_NAME" status 2>/dev/null || true
}
do_uninstall() {
    local purge=0 dest="${DEST:-$INSTALL_DIR}"
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --purge) purge=1; shift ;;
            -y|--yes) shift ;;
            *) die "Unknown option for uninstall: $1" ;;
        esac
    done
    # Interactive confirmation (PasarGuard style)
    if [[ -t 0 && "$YES" -eq 0 && $# -eq 0 ]]; then
        local confirm purge_confirm
        confirm="$(ask "really uninstall OVManager?" "n")"
        [[ "$confirm" =~ ^[Yy]$ ]] || { render_warn "Aborted."; return 0; }
        purge_confirm="$(ask "remove data files too ($DATA_DIR)?" "n")"
        [[ "$purge_confirm" =~ ^[Yy]$ ]] && purge=1
    fi
    check_root
    if command -v docker >/dev/null 2>&1; then
        docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'ovmanager' && { docker rm -f ovmanager >/dev/null 2>&1 && _ok "removed container ovmanager" || true; }
        rm -f "$(compose_file)" 2>/dev/null || true
    fi
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then systemctl stop "$SYSTEMD_SERVICE"; _ok "stopped $SYSTEMD_SERVICE"; fi
    if systemctl is-enabled --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then systemctl disable "$SYSTEMD_SERVICE"; _ok "disabled $SYSTEMD_SERVICE"; fi
    for unit in "$SYSTEMD_SERVICE"; do
        [[ -f "/etc/systemd/system/$unit" ]] && { rm -f "/etc/systemd/system/$unit"; _ok "removed /etc/systemd/system/$unit"; }
    done
    systemctl daemon-reload 2>/dev/null || true
    for d in "$INSTALL_DIR" "$dest"; do [[ -d "$d" ]] && { rm -rf "$d"; _ok "removed $d"; }; done
    [[ -L "$BIN_DIR/$APP_SLUG" ]] && { rm -f "$BIN_DIR/$APP_SLUG"; _ok "removed $BIN_DIR/$APP_SLUG"; }
    uninstall_completion
    if [[ "$purge" -eq 1 ]]; then
        [[ -d "$DATA_DIR" ]] && { rm -rf "$DATA_DIR"; _ok "purged $DATA_DIR"; }
        id -u "$PANEL_USER" >/dev/null 2>&1 && { userdel "$PANEL_USER" 2>/dev/null && _ok "removed user $PANEL_USER" || true; }
    else
        _note "data preserved at $DATA_DIR (use --purge to remove)"
    fi
    _ok "OVManager uninstalled"
}

usage() {
    cat <<EOF
OVManager Setup v${VERSION}

USAGE
  bash <(curl -sSL https://raw.githubusercontent.com/anonysec/OVManager/main/install.sh)

COMMANDS
  install                    Install OVManager (default)
  update [--version vX.Y.Z]  Hand off to \`ovmanager update\`
  uninstall [--purge]        Remove panel, service, and CLI
  status                     Show installation status
  up                         Start the panel
  down                       Stop the panel
  restart                    Restart the panel
  logs                       Tail panel logs
  cli                        Run the ovmanager CLI
  backup                     Run a backup now
  restore                    Restore a backup
  edit-env                   Edit the .env file
  install-script             (Re)install CLI + bash completion
  install-node               Install OVNode on this server
  version-script             Print installer version and commit
  help                       Show this help

OPTIONS
  -i, --interactive          Ask for port, URL path, and SSL setup
  -y, --yes                  Accept defaults without prompts
  --acme DOMAIN              Let's Encrypt certificate for DOMAIN
  --build [DIR]              Dev install from a working tree
  --dest DIR                 with --build: destination
  --docker                   Install/run via Docker (default)
  --version V                Override installer version (default from source tree)
  --native                   Install native binary (systemd) instead of Docker
  --ssl MODE                 SSL mode: domain|ip|custom|selfsigned|none
  -h, --help                 Show this help

ENVIRONMENT
  OVM_PORT, OVM_URLPATH, OVM_ACME_DOMAIN, OVM_SSL_MODE
  OVM_PANEL_USER, OVM_BIN_DIR, OVM_REPO, OVM_DOCKER
EOF
    exit 0
}
script_commit() {
    local dir candidate
    dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf 'unknown'; return 0; }
    candidate="$dir"
    while [[ -n "$candidate" && "$candidate" != "/" ]]; do
        if [[ -e "$candidate/.git" ]]; then git -C "$candidate" rev-parse --short HEAD 2>/dev/null || printf 'unknown'; return 0; fi
        candidate="$(dirname -- "$candidate")"
    done
    printf 'unknown'
}
print_version_script() { local commit; commit="$(script_commit)"; printf 'installer  v%s\n' "$VERSION"; printf 'commit     %s\n' "$commit"; }

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --build|--from-source) FROM_SOURCE=1; shift; if [[ $# -ge 1 && "$1" != -* ]]; then SRC="$1"; shift; fi ;;
            --acme) [[ $# -ge 2 ]] || die "--acme needs a domain"; SSL_DOMAIN="$2"; SSL_MODE="domain"; shift 2 ;;
            --version) [[ $# -ge 2 ]] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
            --ssl)  [[ $# -ge 2 ]] || die "--ssl needs a mode"; SSL_MODE="$2"; shift 2 ;;
            -i|--interactive) INTERACTIVE=1; shift ;;
            --docker) DOCKER=1; DOCKER_EXPLICIT=1; shift ;;
            --native) DOCKER=0; shift ;;
            -y|--yes) YES=1; shift ;;
            -h|--help) usage ;;
            help) usage ;;
            status) ACTION="status"; ACTION_GIVEN=1; shift ;;
            version-script|script-version) ACTION="version-script"; ACTION_GIVEN=1; shift ;;
            update) ACTION="update"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            uninstall) ACTION="uninstall"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            up) ACTION="up"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            down) ACTION="down"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            restart) ACTION="restart"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            logs) ACTION="logs"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            cli) ACTION="cli"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            backup) ACTION="backup"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            restore) ACTION="restore"; ACTION_GIVEN=1; shift; UPDATE_ARGS=("$@"); break ;;
            edit-env) ACTION="edit-env"; ACTION_GIVEN=1; shift ;;
            install-script) ACTION="install-script"; ACTION_GIVEN=1; shift ;;
            install-node) ACTION="install-node"; ACTION_GIVEN=1; shift ;;
            install) shift ;;
            interactive) INTERACTIVE=1; shift ;;
            *) die "Unknown option: $1  (see --help)" ;;
        esac
    done
}

is_docker_install() { docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'ovmanager'; }

up_command() {
    if is_docker_install; then
        docker compose -f "$(compose_file)" up -d
    else
        "$INSTALL_DIR/$APP_SLUG" service start
    fi
}
down_command() {
    if is_docker_install; then
        docker compose -f "$(compose_file)" down
    else
        "$INSTALL_DIR/$APP_SLUG" service stop
    fi
}
restart_command() {
    if is_docker_install; then
        docker compose -f "$(compose_file)" restart
    else
        "$INSTALL_DIR/$APP_SLUG" service restart
    fi
}
logs_command() {
    if is_docker_install; then
        docker logs -f ovmanager
    else
        "$INSTALL_DIR/$APP_SLUG" logs
    fi
}
cli_command() { exec "$INSTALL_DIR/$APP_SLUG" "$@"; }
backup_command() { "$INSTALL_DIR/$APP_SLUG" backup "$@"; }
restore_command() { "$INSTALL_DIR/$APP_SLUG" restore "$@"; }
edit_env_command() {
    local editor="${EDITOR:-nano}"
    command -v "$editor" >/dev/null 2>&1 || editor="vi"
    "$editor" "$INSTALL_DIR/.env"
}
install_script_command() { install_cli "$INSTALL_DIR"; install_completion "$INSTALL_DIR"; }

install_node_command() {
    colorized_echo blue "=============================="
    colorized_echo magenta "   Install OVNode   "
    colorized_echo blue "=============================="
    echo
    run_node_installer
}

main() {
    if [[ $# -eq 0 && -t 0 && "${YES:-0}" -eq 0 ]]; then
        render_banner "OVManager" "$VERSION"
        local choice
        choice="$(render_menu "" \
            install "Install OVManager" \
            update "Update OVManager" \
            status "Show status" \
            uninstall "Uninstall OVManager" \
            logs "Tail logs" \
            quit "Quit")"
        [[ "$choice" == "quit" ]] && return 0
        set -- "$choice"
    fi
    parse_args "$@"
    case "$ACTION" in
        version-script) print_version_script; return 0 ;;
        update) do_update "${UPDATE_ARGS[@]}" ;;
        status) do_status; return 0 ;;
        uninstall) do_uninstall "${UPDATE_ARGS[@]}"; return 0 ;;
        up) up_command; return 0 ;;
        down) down_command; return 0 ;;
        restart) restart_command; return 0 ;;
        logs) logs_command; return 0 ;;
        cli) shift; cli_command "$@"; return 0 ;;
        backup) shift; backup_command "$@"; return 0 ;;
        restore) shift; restore_command "$@"; return 0 ;;
        edit-env) edit_env_command; return 0 ;;
        install-script) install_script_command; return 0 ;;
        install-node) install_node_command; return 0 ;;
    esac
    if [[ "$FROM_SOURCE" -eq 1 ]]; then do_from_source; else do_install; fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
