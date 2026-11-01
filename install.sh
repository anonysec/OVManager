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
VERSION="${OVM_VERSION:-2.3.0}"
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
write_backup_units() {
    local dest="${1:-$INSTALL_DIR}"
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.service" <<UNIT
[Unit]
Description=OVManager daily backup
After=${SYSTEMD_SERVICE}

[Service]
Type=oneshot
EnvironmentFile=$dest/.env
User=$PANEL_USER
Group=$PANEL_USER
ExecStart=$dest/$APP_SLUG backup --keep 7
UNIT
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.timer" <<UNIT
[Unit]
Description=Run the OVManager daily backup

[Timer]
OnCalendar=*-*-* 01:15:00
RandomizedDelaySec=45min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    chmod 644 /etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.service /etc/systemd/system/${SYSTEMD_SERVICE%.service}-backup.timer
}
write_acme_renew_units() {
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.service" <<UNIT
[Unit]
Description=OVManager ACME certificate renewal check
After=${SYSTEMD_SERVICE}

[Service]
Type=oneshot
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/$APP_SLUG tls renew
UNIT
    cat > "/etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.timer" <<UNIT
[Unit]
Description=Run the OVManager ACME renewal check weekly

[Timer]
OnCalendar=weekly
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    chmod 644 /etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.service /etc/systemd/system/${SYSTEMD_SERVICE%.service}-acme-renew.timer
}
enable_acme_renew_timer() {
    systemctl daemon-reload
    systemctl enable --now "${SYSTEMD_SERVICE%.service}-acme-renew.timer" >/dev/null 2>&1 || _warn "Could not enable the ACME renew timer"
}
enable_backup_timer() {
    systemctl daemon-reload
    systemctl enable --now "${SYSTEMD_SERVICE%.service}-backup.timer" >/dev/null 2>&1 || _warn "Could not enable the backup timer"
}
grant_panel_access() {
    local dest="${1:-$INSTALL_DIR}"
    chmod 755 "$dest"; chmod 755 "$dest/$APP_SLUG"
    mkdir -p "$DATA_DIR"; chown -R "$PANEL_USER:$PANEL_USER" "$DATA_DIR"; chmod 700 "$DATA_DIR"
    chown "root:$PANEL_USER" "$dest/.env"; chmod 640 "$dest/.env"
}
install_cli() {
    local dest="${1:-$INSTALL_DIR}"
    mkdir -p "$BIN_DIR" 2>/dev/null || { _warn "Could not create $BIN_DIR"; return 0; }
    ln -sf "$dest/$APP_SLUG" "$BIN_DIR/$CLI_NAME"
    _ok "command  $BIN_DIR/$CLI_NAME"
}

install_completion() {
    local dest="${1:-$INSTALL_DIR}"
    local completion_dir="/etc/bash_completion.d"
    local completion_file="$completion_dir/$CLI_NAME"
    mkdir -p "$completion_dir" 2>/dev/null || return 0
    if "$dest/$APP_SLUG" completion bash >"$completion_file" 2>/dev/null; then
        chmod 644 "$completion_file" 2>/dev/null || true
        _ok "completion  $completion_file"
    else
        rm -f "$completion_file" 2>/dev/null || true
    fi
}

uninstall_completion() {
    local completion_file="/etc/bash_completion.d/$CLI_NAME"
    if [[ -f "$completion_file" ]]; then
        rm -f "$completion_file" && _ok "removed $completion_file" || true
    fi
}

# OVNode's installer currently bootstraps its helpers into APP_DIR before it
# checks whether APP_DIR exists. Preserve the pre-bootstrap state when this
# exact upstream ordering is present; do not remove or overwrite existing nodes.
run_node_installer() {
    local script before='    load_helpers' check='    # install
    if [[ -d "$APP_DIR" ]]; then'
    local snapshot='    local ovm_node_dir_existed=0
    [[ -d "$APP_DIR" ]] && ovm_node_dir_existed=1
    load_helpers'
    local fixed_check='    # install
    if [[ "$ovm_node_dir_existed" -eq 1 ]]; then'
    if ! script="$(curl -fsSL https://raw.githubusercontent.com/anonysec/OVNode/v1.4.12/install.sh)" || [[ -z "$script" ]]; then
        _warn "Could not download the OVNode installer."
        return 1
    fi
    # Match both the call and the later install check, not similarly named
    # helpers in a future installer. If upstream fixes this, leave it alone.
    if [[ "$script" == *"$before"*"$check"* && "$script" == *'load_helpers() {'* ]]; then
        script="${script/"$before"/"$snapshot"}"
        script="${script/"$check"/"$fixed_check"}"
    fi
    if [[ "$EUID" -eq 0 ]]; then
        bash -c "$script"
    else
        sudo bash -c "$script"
    fi
}

# Print after the node installer (which clears the terminal), and before any
# unbounded log follow. Never read an old claim key merely to display it.
show_install_summary() {
    local port="$1" urlpath="$2" key="$3" display_path host_ip scheme=http
    display_path="${urlpath#/}"; display_path="${display_path%/}"
    [[ -n "$display_path" ]] && display_path="/${display_path}/" || display_path="/"
    if curl -fsSk --max-time 3 "https://127.0.0.1:${port}/health" >/dev/null 2>&1; then
        scheme=https
    fi
    colorized_echo blue "Installation complete"
    _ok "URL     ${scheme}://127.0.0.1:$port$display_path"
    if [[ -n "$key" ]]; then
        _ok "Key     $key   (shown once — save it)"
    elif [[ -f "$DATA_DIR/owner-claim.key" ]]; then
        _note "existing claim key kept at $DATA_DIR/owner-claim.key"
    else
        _note "No new claim key was created (the panel may already be claimed)."
    fi
    host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"; host_ip="${host_ip:-<host>}"
    _ok "SSH     ssh -L $port:127.0.0.1:$port $host_ip"
    _note "Open the URL through the SSH tunnel to access the panel."
    [[ -n "$key" ]] && _note "Paste the key to claim the panel and set your password."
    return 0
}

offer_node_and_logs() {
    local mode="${1:-native}" port="$2" urlpath="$3" key="${4:-}" choice=""
    if [[ "$INTERACTIVE" -ne 1 || "$YES" -eq 1 || ! -t 0 ]]; then
        _note "Skipping optional OVNode/logs prompts (non-interactive)."
        show_install_summary "$port" "$urlpath" "$key"
        return 0
    fi
    echo
    colorized_echo yellow "OVManager installed."
    read -r -p "Do you want to install OVNode on the same server? (y/n) " choice || true
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        run_node_installer || _warn "OVNode installation failed; the panel remains installed."
    else
        _note "Skipping OVNode installation."
    fi
    show_install_summary "$port" "$urlpath" "$key"
    echo
    choice=""
    read -r -p "Follow service logs? (y/n) " choice || true
    if [[ "$choice" =~ ^[Yy]$ ]]; then
        if [[ "$mode" == "docker" ]]; then
            docker logs -f ovmanager
        else
            journalctl -u "$SYSTEMD_SERVICE" -f
        fi
    fi
}

verify_acme() {
    local data_dir="$1" cert key i check
    cert="$data_dir/tls/fullchain.pem"; key="$data_dir/tls/privkey.pem"
    _note "waiting for the Let's Encrypt certificate (up to $((ACME_TIMEOUT * 3))s)…"
    for ((i = 0; i < ACME_TIMEOUT; i++)); do
        if [[ -s "$cert" && -s "$key" ]]; then
            if check="$(openssl x509 -in "$cert" -noout -checkend 86400 2>/dev/null)" && [[ "$check" == "Certificate will not expire"* ]]; then
                _ok "acme    certificate installed at $cert"; return 0
            fi
        fi
        sleep 3
    done
    _warn "no Let's Encrypt certificate after 3 minutes — panel continues on plain HTTP"
    return 0
}

verify_health() {
    local port="$1" want="$2" i body got
    for ((i = 0; i < HEALTH_TIMEOUT; i++)); do
        body="$(curl -fsS --max-time 3 "http://127.0.0.1:${port}/health" 2>/dev/null || true)"
        if [[ -z "$body" ]]; then
            body="$(curl -fsSk --max-time 3 "https://127.0.0.1:${port}/health" 2>/dev/null || true)"
        fi
        if [[ -n "$body" ]]; then
            got="$(printf '%s' "$body" | grep -o '"version":"[^"]*"' | cut -d'"' -f4)"
            if [[ "$got" == "$want" ]]; then _ok "health  v$got on port $port"; return 0; fi
            [[ -n "$got" ]] && _warn "health reports '$got', expected '$want'"
        fi
        printf '.' >&2; sleep 1
    done
    printf '\n' >&2
    return 1
}

do_from_source() {
    local src="${SRC:-$PWD}" dest="${DEST:-$INSTALL_DIR}" service unit port key health
    [[ -d "$src" ]] || die "no source directory: $src"
    [[ -f "$src/cmd/main.go" ]] || die "no Go source tree in $src (cmd/main.go missing)"
    [[ -d "$src/web/dist" ]] || die "web/dist missing in $src — run: cd web && npm run build"
    check_root; ensure_panel_user
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    command -v rsync >/dev/null || die "rsync not found"
    command -v go >/dev/null || die "go not found — install Go 1.27+"
    dest="${dest%/}"
    if [[ "$dest" == "$INSTALL_DIR" ]]; then
        if [[ -e "$INSTALL_DIR/$APP_SLUG" || -e "/etc/systemd/system/$SYSTEMD_SERVICE" ]]; then
            die "--build refuses to overwrite the live install at $INSTALL_DIR; pass --dest DIR"
        fi
    fi
    service="$(basename "$dest").service"; unit="/etc/systemd/system/$service"
    rsync -a --delete --exclude .git --exclude .venv --exclude __pycache__ --exclude node_modules --exclude .pytest_cache --exclude .slim --exclude .env --exclude /data "$src/" "$dest/"
    mkdir -p "$dest/internal/webfs/dist"
    cp -a "$dest/web/dist/." "$dest/internal/webfs/dist/"
    ( cd "$dest" && go build -o "$APP_SLUG" ./cmd )
    mkdir -p "$dest/data"; chown -R "$PANEL_USER:$PANEL_USER" "$dest/data"; chmod 700 "$dest/data"
    if [[ ! -f "$dest/.env" ]]; then
        cat > "$dest/.env" <<EOF
PORT=2095
URLPATH=dashboard
HOST=127.0.0.1
DATA_DIR=$dest/data
ADMIN_USERNAME=admin
EOF
        chown "root:$PANEL_USER" "$dest/.env"; chmod 640 "$dest/.env"
    fi
    if [[ ! -f "$dest/data/owner-claim.key" ]]; then
        key="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-32)"
        ( umask 077; printf '%s\n' "$key" > "$dest/data/owner-claim.key" )
        chmod 600 "$dest/data/owner-claim.key"; chown "$PANEL_USER:$PANEL_USER" "$dest/data/owner-claim.key"
        _note "setup key (shown once): $key"
    fi
    port="$(awk -F= -v k=PORT '$1==k{print $2;exit}' "$dest/.env" 2>/dev/null)"; port="${port:-2095}"
    cat > "$unit" <<UNIT
[Unit]
Description=OVManager panel (dev install)
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
$(unit_hardening "$dest" "$dest/data")
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "$unit"
    systemctl daemon-reload
    systemctl restart "$service" 2>/dev/null || systemctl enable --now "$service" >/dev/null 2>&1 || true
    health=""
    for _ in $(seq 1 30); do
        curl -fsS --max-time 2 "http://127.0.0.1:$port/health" >/dev/null 2>&1 && { health=1; break; }
        sleep 1
    done
    [[ -n "$health" ]] || _warn "no /health on port $port yet — check: systemctl status $service"
    _ok "installed $dest (service $service, port $port)"
}

ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        _note "installing Docker Engine..."
        if command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq >/dev/null 2>&1 || true
            apt-get install -y -qq docker.io docker-compose-plugin >/dev/null 2>&1 || apt-get install -y -qq docker-ce docker-compose-plugin >/dev/null 2>&1 || die "Could not install Docker via apt"
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y docker docker-compose-plugin >/dev/null 2>&1 || die "Could not install Docker via dnf"
        else
            die "Docker not found. Install manually: https://docs.docker.com/engine/install/"
        fi
    fi
    command -v docker >/dev/null 2>&1 || die "Docker binary not found"
    docker compose version >/dev/null 2>&1 || docker-compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"
    _ok "Docker present"
}
compose_file() { printf '%s/docker-compose.yml' "$DATA_DIR"; }
write_compose_file() {
    local compose; compose="$(compose_file)"
    mkdir -p "$DATA_DIR"
    {
        printf 'services:\n'; printf '  ovmanager:\n'
        printf '    image: %s:%s\n' "$IMAGE_REPO" "$VERSION"
        printf '    container_name: ovmanager\n'; printf '    restart: unless-stopped\n'
        printf '    network_mode: host\n'; printf '    environment:\n'
        printf '      HOST: 0.0.0.0\n'; printf '      PORT: %s\n' "$PORT_VAL"
        printf '      URLPATH: %s\n' "$URLPATH_VAL"; printf '      ADMIN_USERNAME: %s\n' "$DEFAULT_USER"
        printf '      DATA_DIR: /app/data\n'
        if [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]]; then
            printf '      OVM_ACME_DOMAIN: %s\n' "$SSL_DOMAIN"
            printf '      SSL_CERTFILE: /app/data/tls/fullchain.pem\n'; printf '      SSL_KEYFILE: /app/data/tls/privkey.pem\n'
        fi
        if [[ "$SSL_MODE" == "custom" ]]; then
            printf '      SSL_CERTFILE: %s\n' "$SSL_CERT_SRC"; printf '      SSL_KEYFILE: %s\n' "$SSL_KEY_SRC"
        fi
        if [[ "$SSL_MODE" == "ip" || "$SSL_MODE" == "selfsigned" ]]; then
            printf '      SSL_CERTFILE: /app/data/tls/fullchain.pem\n'; printf '      SSL_KEYFILE: /app/data/tls/privkey.pem\n'
        fi
        printf '    volumes:\n'; printf '      - %s:/app/data\n' "$DATA_DIR"
        printf '    logging:\n'; printf '      options:\n'
        printf '        max-size: "5m"\n'; printf '        max-file: "3"\n'
    } > "$compose"
    chmod 600 "$compose"; _ok "Compose file written: $compose"
}
setup_docker() {
    ensure_docker; write_compose_file
    mkdir -p "$DATA_DIR"
    _note "pulling ${IMAGE_REPO}:${VERSION}"
    docker pull "${IMAGE_REPO}:${VERSION}" >/dev/null 2>&1 || _warn "pull failed; continuing with cached image"
    local c_user
    c_user="$(docker inspect -f '{{.Config.User}}' "${IMAGE_REPO}:${VERSION}" 2>/dev/null || echo "")"
    # The published distroless image declares USER nonroot, which need not
    # exist in the host's passwd database. Its numeric uid/gid are 65532.
    [[ "$c_user" == "nonroot" ]] && c_user="65532:65532"
    if [[ -n "$c_user" && "$c_user" != "root" && "$c_user" != "0" && "$c_user" != "0:0" ]]; then
        chown -R "$c_user" "$DATA_DIR" || die "Could not grant the container access to $DATA_DIR"
    fi
    chmod 700 "$DATA_DIR" 2>/dev/null || true
    # Mint only on a fresh database; never replace an existing panel identity.
    DOCKER_CLAIM_KEY=""
    if [[ ! -e "$DATA_DIR/ovmanager.db" && ! -e "$DATA_DIR/owner-claim.key" ]]; then
        DOCKER_CLAIM_KEY="$(openssl rand -hex 16)" || die "Could not create claim key"
        ( umask 077; printf '%s\n' "$DOCKER_CLAIM_KEY" > "$DATA_DIR/owner-claim.key" )
        if [[ -n "$c_user" && "$c_user" != "root" && "$c_user" != "0" && "$c_user" != "0:0" ]]; then
            chown "$c_user" "$DATA_DIR/owner-claim.key" || die "Could not grant the container access to the claim key"
        fi
    fi
    _note "starting container"
    docker compose -f "$(compose_file)" up -d
    _ok "container started"
}

do_install() {
    render_banner "OVManager" "$VERSION"
    render_kv "repository" "${REPO}"
    render_kv "arch" "$(detect_arch)"
    render_kv "os" "$(. /etc/os-release 2>/dev/null && echo "$ID $VERSION_ID" || uname -s)"
    render_blank
    if [[ "$SSL_MODE" == "selfsigned" && "$INSTALL_SELF_SIGNED" -eq 0 ]]; then
        INSTALL_SELF_SIGNED=1
        [[ -z "$SELF_SIGNED_TARGET" ]] && SELF_SIGNED_TARGET="localhost"
    fi
    if [[ "$INTERACTIVE" -eq 1 && "$YES" -eq 0 && "$DOCKER_EXPLICIT" -eq 0 && -t 0 ]]; then
        render_stage "Installation method"
        colorized_echo green "  1) Docker (default)"
        colorized_echo green "  2) Native (systemd)"
        local method_choice
        read -p "Select install method [1-2] (default: 1): " method_choice
        method_choice="${method_choice// /}"
        [ -z "$method_choice" ] && method_choice="1"
        case "$method_choice" in
            1) DOCKER=1 ;;
            2) DOCKER=0 ;;
            *) render_warn "Invalid choice '$method_choice', using Docker"; DOCKER=1 ;;
        esac
    fi
    if [[ "$DOCKER" -eq 1 ]]; then
        check_root
        check_deps
        colorized_echo blue "Configuration"
        prompt_interactive; setup_ssl_wizard
        if [[ "$SSL_MODE" == "domain" && -z "$SSL_DOMAIN" ]]; then _warn "no domain given - SSL disabled"; SSL_MODE="none"; fi
        [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]] && check_acme_domain
        _ok "port=$PORT_VAL  path=$URLPATH_VAL  tls=${SSL_MODE:-none}"
        colorized_echo blue "Docker"; setup_docker
        colorized_echo blue "Verification"
        verify_health "$PORT_VAL" "$VERSION" || die "The panel did not report v$VERSION on /health after 40s - docker logs ovmanager"
        _ok "installed v$VERSION via Docker (port $PORT_VAL)"
        offer_node_and_logs docker "$PORT_VAL" "$URLPATH_VAL" "$DOCKER_CLAIM_KEY"
        return 0
    fi
    local dest="${DEST:-$INSTALL_DIR}"
    [[ -n "$dest" && "$dest" != "/" ]] || die "refusing to operate on '$dest'"
    check_root
    if [[ -e "$dest" ]]; then
        # Idempotent: a second run upgrades instead of failing. With -y (or no
        # tty) we upgrade in place without prompting; interactive runs still ask.
        local override="n"
        if [[ "${YES:-0}" -eq 1 ]] || ! is_tty; then
            override="y"
        else
            override="$(ask "OVManager already installed at $dest. Override previous installation?" "n")"
        fi
        if [[ "$override" =~ ^[Yy]$ ]]; then
            local purge="n"
            if [[ "${YES:-0}" -eq 0 ]] && is_tty; then
                purge="$(ask "Purge existing data at $DATA_DIR too?" "n")"
            fi
            if [[ "$purge" =~ ^[Yy]$ ]]; then
                rm -rf "$DATA_DIR"; _ok "purged $DATA_DIR"
            fi
            do_update "$@"
            return $?
        else
            render_warn "Aborted installation"; return 0
        fi
    fi
    has_systemd || die "systemd not found — a native install needs it"
    check_deps
    printf '# Executing ovmanager install script, commit: %s\n' "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --short HEAD 2>/dev/null || echo main)"
    colorized_echo blue "Configuration"
    prompt_interactive; setup_ssl_wizard
    [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]] && check_acme_domain
    _ok "port=$PORT_VAL  path=$URLPATH_VAL  tls=${SSL_MODE:-none}"
    if is_port_in_use "$PORT_VAL"; then
        _warn "Port $PORT_VAL is already in use."
        if [[ "$INTERACTIVE" -eq 1 ]]; then
            local new_port
            while true; do
                new_port="$(ask "different port (1-65535) or q to abort" "")"
                new_port="${new_port// /}"
                [[ "$new_port" == "q" ]] && die "Installation aborted due to port conflict"
                if validate_port "$new_port"; then
                    if is_port_in_use "$new_port"; then _warn "Port $new_port is also in use."; else PORT_VAL="$new_port"; break; fi
                else
                    _warn "Invalid port: $new_port"
                fi
            done
        fi
    fi
    local key port urlpath
    colorized_echo blue "Creating panel user"; ensure_panel_user
    colorized_echo blue "Download"; fetch_release "$dest"
    colorized_echo blue "Writing environment file"; write_env "$dest/.env" "$DATA_DIR"
    key="$(mint_claim_key "$DATA_DIR/owner-claim.key")"
    colorized_echo blue "Installing systemd units"; write_systemd_unit "$dest"; write_backup_units "$dest"
    colorized_echo blue "Granting permissions"; grant_panel_access "$dest"
    colorized_echo blue "Installing CLI"; install_cli "$dest"; install_completion "$dest"
    colorized_echo blue "Service"
    systemctl daemon-reload
    if systemctl is-active --quiet "$SYSTEMD_SERVICE" 2>/dev/null; then
        systemctl restart "$SYSTEMD_SERVICE" || die "Could not restart $SYSTEMD_SERVICE"
    else
        systemctl enable --now "$SYSTEMD_SERVICE" >/dev/null 2>&1 || die "Could not start $SYSTEMD_SERVICE"
    fi
    enable_backup_timer
    [[ "$SSL_MODE" == "domain" && -n "$SSL_DOMAIN" ]] && { write_acme_renew_units; enable_acme_renew_timer; }
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
    for unit in "$SYSTEMD_SERVICE" "${SYSTEMD_SERVICE%.service}-backup.service" "${SYSTEMD_SERVICE%.service}-backup.timer" "${SYSTEMD_SERVICE%.service}-acme-renew.service" "${SYSTEMD_SERVICE%.service}-acme-renew.timer"; do
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
