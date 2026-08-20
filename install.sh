# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

#!/bin/bash
# ══════════════════════════════════════════════════════════════════════
#  OVManager — OpenVPN Panel Installer
#
#  Install :  bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
#  Update  :  bash <(curl -Ls URL) update
#  Remove  :  bash <(curl -Ls URL) uninstall
#
#  A single, OS-aware installer for native (systemd) and Docker deploys.
#  It bootstraps uv + Node.js, validates input, backs up data before every
#  destructive step, and verifies the panel answers /health afterwards.
# ══════════════════════════════════════════════════════════════════════

set -Eeuo pipefail

# ── Config ─────────────────────────────────────────────────────────────
REPO="anonysec/OVManager"
BRANCH="main"
INSTALL_DIR="/opt/ovmanager"
DATA_DIR="/var/lib/ovmanager"
DEFAULT_PORT=2095
DEFAULT_PATH=""
DEFAULT_USER="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.7"

# ── Colors ─────────────────────────────────────────────────────────────
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; BL=$'\033[34m'; CY=$'\033[36m'; GY=$'\033[90m'
[[ -t 1 ]] || { NC=''; B=''; D=''; WH=''; GR=''; RD=''; YL=''; BL=''; CY=''; GY=''; }

# ── UI helpers ─────────────────────────────────────────────────────────
line()  { echo -e "  $1" >&2; }
step()  { line "${GR}  ✓${NC} $1"; }
info()  { line "${CY}  →${NC} $1"; }
warn()  { line "${YL}  ⚠${NC} $1"; }
field() { printf "  ${GY}%-18s${NC} %s\n" "$1" "$2"; }
sep()   { line "${GY}$(printf '%.0s─' {1..56})${NC}"; }

spinner() {
    local msg="$1" pid=$2 chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0 rc=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${CY}%s${NC} %-46s" "${chars:$((i%9)):1}" "$msg" >&2
        sleep 0.1; i=$(( i + 1 ))
    done
    wait "$pid" 2>/dev/null || rc=$?
    printf "\r\033[K" >&2
    [[ $rc -eq 0 ]] && step "$msg" || { line "${RD}  ✗${NC} $msg"; return 1; }
}

die()  { echo -e "\n  ${RD}Error:${NC} $1\n" >&2; exit 1; }
trap 'echo -e "\n  ${RD}Interrupted.${NC}" >&2; exit 1' INT TERM

is_tty() { [[ -t 0 ]]; }
ask() {  # ask <label> <default> [hidden]
    local label="$1" default="$2" hidden="${3:-}" val=""
    if is_tty; then
        if [[ "$hidden" == "h" ]]; then
            printf "  ${WH}%-18s${NC} ${GY}[%s]${NC} : " "$label" "$default"
            read -rs val; printf "\n"
        else
            printf "  ${WH}%-18s${NC} ${GY}[%s]${NC} : " "$label" "$default"
            read -r val
        fi
    fi
    if [[ -z "$val" ]]; then val="$default"; fi
    echo "$val"
}

confirm() {  # confirm <msg> → true/false; non-interactive = true with -y
    [[ "$YES" -eq 1 ]] && return 0
    if is_tty; then
        printf "  %s [${GR}Y${NC}/n] : " "$1"
        read -r c
        [[ ! "$c" =~ ^[Nn]$ ]]
    else
        return 0
    fi
}

# ── OS / package manager ───────────────────────────────────────────────
OS_ID="" OS_NAME="" PKG_INSTALL="" PKG_UPDATE=""

detect_os() {
    if [[ -f /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-}"; OS_NAME="${PRETTY_NAME:-$OS_ID}"
    else
        die "Unsupported OS — no /etc/os-release found."
    fi
    case "$OS_ID" in
        debian|ubuntu)      PKG_UPDATE="apt-get update -qq";  PKG_INSTALL="apt-get install -y -qq" ;;
        rhel|centos|rocky|almalinux|fedora)
            if command -v dnf >/dev/null 2>&1; then
                PKG_UPDATE="dnf -q makecache"; PKG_INSTALL="dnf install -y -q"
            else
                PKG_UPDATE="yum -q makecache"; PKG_INSTALL="yum install -y -q"
            fi ;;
        arch)               PKG_UPDATE="pacman -Sy --noconfirm"; PKG_INSTALL="pacman -S --noconfirm" ;;
        alpine)             PKG_UPDATE="apk update -q";         PKG_INSTALL="apk add -q" ;;
        *) die "Unsupported distribution: ${OS_ID:-unknown}" ;;
    esac
}

pkg_install() {
    info "Installing: $*"
    $PKG_UPDATE >/dev/null 2>&1 || true
    $PKG_INSTALL "$@" >/dev/null 2>&1 || die "Failed to install: $* (run the command manually: $PKG_INSTALL $*)"
}

has_systemd() { command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; }

# ── Arg parsing ────────────────────────────────────────────────────────
PORT="" PATHPREFIX="" ADMIN_USER="" ADMIN_PASS=""
TLS_MODE="" TLS_DOMAIN="" TLS_KEY="" TLS_CERT=""
PUBLIC_URL="" DOCKER_FLAG=0 ACTION="install" YES=0 PURGE=0

show_help() {
    cat << 'EOF'
  Usage:
    bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
    bash <(curl -Ls URL) update
    bash <(curl -Ls URL) uninstall

  Commands:
    (none)              Install or update OVManager
    update              Pull latest changes, rebuild, restart (with backup)
    uninstall           Remove OVManager (data kept unless --purge)

  Flags:
    --port PORT         Panel port (default: 2095)
    --path URLPATH      URL path prefix, e.g. mypanel (default: root)
    --admin-user USER   Admin username (default: admin)
    --admin-pass PASS   Admin password (required)
    --public-url URL    Canonical public URL for subscription links
    --tls-le DOMAIN     Let's Encrypt for a domain
    --tls-ip            Let's Encrypt short-lived cert for the server IP
    --tls-self          Self-signed certificate
    --tls-custom K C    Use existing key + cert files
    --tls-none          Plain HTTP
    --docker            Deploy with Docker (builds from source)
    --yes  | -y         Non-interactive: accept defaults, skip confirmations
    --purge             With uninstall: also remove data and certificates
    --help | -h         Show this help
EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port)        [[ $# -ge 2 ]] || die "--port needs a value"; PORT="$2"; shift 2 ;;
            --path)        [[ $# -ge 2 ]] || die "--path needs a value"; PATHPREFIX="${2#/}"; PATHPREFIX="${PATHPREFIX%/}"; shift 2 ;;
            --admin-user)  [[ $# -ge 2 ]] || die "--admin-user needs a value"; ADMIN_USER="$2"; shift 2 ;;
            --admin-pass)  [[ $# -ge 2 ]] || die "--admin-pass needs a value"; ADMIN_PASS="$2"; shift 2 ;;
            --public-url)  [[ $# -ge 2 ]] || die "--public-url needs a value"; PUBLIC_URL="$2"; shift 2 ;;
            --tls-le)      [[ $# -ge 2 ]] || die "--tls-le needs a domain"; TLS_MODE="le"; TLS_DOMAIN="$2"; shift 2 ;;
            --tls-ip)      TLS_MODE="le-ip"; shift ;;
            --tls-self)    TLS_MODE="self"; shift ;;
            --tls-custom)  [[ $# -ge 3 ]] || die "--tls-custom needs KEY CERT"; TLS_MODE="custom"; TLS_KEY="$2"; TLS_CERT="$3"; shift 3 ;;
            --tls-none)    TLS_MODE="none"; shift ;;
            --docker)      DOCKER_FLAG=1; shift ;;
            --yes|-y)      YES=1; shift ;;
            --purge)       PURGE=1; shift ;;
            --uninstall)   ACTION="uninstall"; shift ;;
            --help|-h)     show_help ;;
            update)        ACTION="update"; shift ;;
            uninstall)     ACTION="uninstall"; shift ;;
            *)             die "Unknown option: $1 (--help for usage)" ;;
        esac
    done
}

# ── Validation ─────────────────────────────────────────────────────────
is_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 )); }

validate_input() {
    is_port "$PORT"   || die "Invalid port: '$PORT'"
    [[ -n "$ADMIN_USER" ]] || ADMIN_USER="$DEFAULT_USER"
    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || die "Invalid admin username (3-64 chars, letters/digits/._-)"
    [[ -n "$ADMIN_PASS" ]] || die "Admin password is required (--admin-pass or interactive install)"
    [[ ${#ADMIN_PASS} -ge 8 ]] || die "Admin password must be at least 8 characters"
    if [[ -n "$PATHPREFIX" ]]; then
        [[ "$PATHPREFIX" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "URL path may only contain letters, digits, dash and underscore"
    fi
    case "$TLS_MODE" in
        le|le-ip|self|custom|none) ;;
        *) die "Invalid TLS mode: '$TLS_MODE' (le | le-ip | self | custom | none)" ;;
    esac
}

port_in_use() { ss -ltn 2>/dev/null | awk -v p=":${1}$" '$4 ~ p {exit 0} END {exit 1}'; }

# ── Dependency bootstrap ───────────────────────────────────────────────
ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_BIN="$(command -v uv)"; step "uv found: $UV_BIN"; return
    fi
    info "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || \
        python3 -m pip install --quiet uv >/dev/null 2>&1 || \
        die "Could not install uv. Install it manually: curl -LsSf https://astral.sh/uv/install.sh | sh"
    UV_BIN="$(command -v uv 2>/dev/null || true)"
    [[ -n "$UV_BIN" ]] || UV_BIN="$HOME/.local/bin/uv"
    [[ -x "$UV_BIN" ]] || die "uv not found after install"
    step "uv installed: $UV_BIN"
}

ensure_node() {
    if command -v node >/dev/null 2>&1; then
        local maj; maj="$(node -v 2>/dev/null | sed 's/^v//;s/\..*//')"
        if (( maj < 20 )); then
            warn "Node.js $(node -v) found — Vite 7 needs >= 20.19; install Node 22 LTS"
        fi
        command -v npm >/dev/null 2>&1 || pkg_install npm
        return
    fi
    info "Installing Node.js 22 LTS..."
    case "$OS_ID" in
        debian|ubuntu)
            curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1 \
                && pkg_install nodejs \
                || die "Could not install Node.js from NodeSource"
            ;;
        *) pkg_install nodejs npm ;;
    esac
    command -v node >/dev/null 2>&1 || die "Node.js installation failed"
    step "Node.js $(node -v) ready"
}

check_deps() {
    local missing=()
    for cmd in curl tar openssl git python3; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] || pkg_install "${missing[@]}"
    step "System dependencies present"
}

# ── Backups ────────────────────────────────────────────────────────────
backup_dir() {
    local src="$1" label="$2"
    [[ -d "$src" ]] || return 0
    mkdir -p /var/backups
    local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
    local base; base="$(basename "$src")"
    local file="/var/backups/${label}-${base}-${stamp}.tar.gz"
    info "Backing up ${label} data to $file ..."
    tar -czf "$file" -C "$(dirname "$src")" "$base" 2>/dev/null \
        || warn "Backup failed for $src — continuing anyway"
    step "Backup saved: $file"
}

# ── TLS ────────────────────────────────────────────────────────────────
generate_self_signed() {
    info "Generating self-signed certificate..."
    mkdir -p /etc/ssl/self-signed
    local cn; cn="$(hostname -I 2>/dev/null | awk '{print $1}')"
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout /etc/ssl/self-signed/privkey.pem \
        -out /etc/ssl/self-signed/fullchain.pem \
        -subj "/C=US/ST=Local/L=Local/O=OVManager/CN=${cn}" >/dev/null 2>&1
    TLS_KEY="/etc/ssl/self-signed/privkey.pem"
    TLS_CERT="/etc/ssl/self-signed/fullchain.pem"
    step "Self-signed certificate generated"
}

ensure_acme() {
    if [[ ! -x "$HOME/.acme.sh/acme.sh" ]]; then
        info "Installing acme.sh..."
        curl -s https://get.acme.sh | sh >/dev/null 2>&1 || die "Failed to install acme.sh"
    fi
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
            step "Existing certificate valid for ${days_left} more days"
            return 0
        fi
        warn "Certificate expires soon (${days_left}d) — renewing..."
    fi

    local extra_args=()
    if [[ "$is_ip" == "1" ]]; then
        info "Issuing short-lived certificate for IP $domain (6 days)..."
        extra_args=(--certificate-profile shortlived --days 6)
    else
        info "Issuing certificate for $domain..."
    fi

    "$HOME/.acme.sh/acme.sh" --issue -d "$domain" --standalone "${extra_args[@]}" \
        --accountemail "$email" >/dev/null 2>&1 \
        || die "Failed to issue Let's Encrypt certificate for $domain"

    # reloadcmd is set again after the service exists so renewals restart it
    "$HOME/.acme.sh/acme.sh" --install-cert -d "$domain" \
        --key-file "$outdir/privkey.pem" \
        --fullchain-file "$outdir/fullchain.pem" \
        --reloadcmd "systemctl restart $SYSTEMD_SERVICE >/dev/null 2>&1 || true" >/dev/null 2>&1 \
        || die "Failed to install certificate to $outdir"
    step "Certificate installed to $outdir"
}

# ── Firewall ───────────────────────────────────────────────────────────
open_firewall_port() {
    local port="$1"
    if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        ufw allow "$port/tcp" >/dev/null 2>&1 && step "UFW: allowed port $port/tcp"
    elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        firewall-cmd --permanent --add-port="$port/tcp" >/dev/null 2>&1 && \
        firewall-cmd --reload >/dev/null 2>&1 && step "firewalld: allowed port $port/tcp"
    fi
}

# ── Systemd ────────────────────────────────────────────────────────────
write_systemd_unit() {
    cat > "/etc/systemd/system/$SYSTEMD_SERVICE" << UNIT
[Unit]
Description=OVManager OpenVPN Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="DATA_DIR=${DATA_DIR}"
ExecStart=${UV_BIN} run main.py
Restart=on-failure
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload >/dev/null 2>&1
    systemctl enable "$SYSTEMD_SERVICE" >/dev/null 2>&1
    step "systemd unit written: /etc/systemd/system/$SYSTEMD_SERVICE"
}

wait_health() {
    local url="$1" tries="${2:-30}"
    local i
    # -k: self-signed certs are fine for a loopback health probe
    for i in $(seq 1 "$tries"); do
        curl -fskS -o /dev/null --max-time 3 "$url" 2>/dev/null && return 0
        sleep 1
    done
    return 1
}

# ── Install ────────────────────────────────────────────────────────────
write_env() {
    local jwt_secret bot_key=""
    jwt_secret="$(openssl rand -base64 48 2>/dev/null | tr -d '\n')"
    # Fernet key for Telegram bot token encryption (optional but handy)
    bot_key="$("$INSTALL_DIR/.venv/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' 2>/dev/null || true)"

    cat > "$INSTALL_DIR/.env" << EOF
HOST=0.0.0.0
PORT=${PORT}
URLPATH=${PATHPREFIX}
ADMIN_USERNAME=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASS}
JWT_SECRET_KEY=${jwt_secret}
JWT_ACCESS_TOKEN_EXPIRES=1800
JWT_REFRESH_TOKEN_EXPIRES=604800
DATA_DIR=${DATA_DIR}
$( [[ -n "$PUBLIC_URL" ]] && echo "PUBLIC_URL=${PUBLIC_URL}" )
$( [[ -n "$bot_key" ]] && echo "BOT_ENCRYPT_KEY=${bot_key}" )
$( [[ -n "$TLS_KEY" ]] && echo "SSL_KEYFILE=${TLS_KEY}" )
$( [[ -n "$TLS_CERT" ]] && echo "SSL_CERTFILE=${TLS_CERT}" )
EOF
    chmod 600 "$INSTALL_DIR/.env"
    step "Configuration written to $INSTALL_DIR/.env"
}

setup_tls() {
    case "$TLS_MODE" in
        le)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it"
            issue_lets_encrypt "$TLS_DOMAIN" "0"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        le-ip)
            port_in_use 80 && die "Port 80 is busy — Let's Encrypt standalone needs it"
            TLS_DOMAIN="${TLS_DOMAIN:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
            issue_lets_encrypt "$TLS_DOMAIN" "1"
            TLS_KEY="/etc/letsencrypt/$TLS_DOMAIN/privkey.pem"
            TLS_CERT="/etc/letsencrypt/$TLS_DOMAIN/fullchain.pem"
            ;;
        self)
            generate_self_signed
            ;;
        custom)
            [[ -f "$TLS_KEY" && -f "$TLS_CERT" ]] || die "Custom key/cert files not found: $TLS_KEY $TLS_CERT"
            local out="/etc/letsencrypt/${TLS_DOMAIN:-panel}"
            mkdir -p "$out"
            cp "$TLS_KEY" "$out/privkey.pem"
            cp "$TLS_CERT" "$out/fullchain.pem"
            TLS_KEY="$out/privkey.pem"; TLS_CERT="$out/fullchain.pem"
            ;;
        none) ;;
    esac
}

fetch_source() {
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch "$BRANCH" "https://github.com/${REPO}.git" "$INSTALL_DIR" >/dev/null 2>&1 &
        spinner "Cloning repository" $!
    else
        curl -sSLo /tmp/ovm.tar.gz "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" &
        spinner "Downloading source tarball" $!
        mkdir -p "$INSTALL_DIR"
        tar -xzf /tmp/ovm.tar.gz --strip-components=1 -C "$INSTALL_DIR" >/dev/null 2>&1 \
            || die "Extract failed"
        rm -f /tmp/ovm.tar.gz
    fi
}

build_frontend() {
    [[ -f "$INSTALL_DIR/frontend/package.json" ]] || return 0
    info "Building frontend..."
    cd "$INSTALL_DIR/frontend"
    npm ci --no-audit --no-fund >/dev/null 2>&1 &
    spinner "Node.js dependencies installed" $!
    npm run build >/dev/null 2>&1 &
    spinner "Frontend built" $!
}

start_service() {
    systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 &
    spinner "Service started" $!
}

do_install() {
    if [[ -d "$INSTALL_DIR" ]]; then die "Already installed ($INSTALL_DIR exists). Use 'uninstall' first."; fi
    mkdir -p "$DATA_DIR"

    sep; info "Downloading OVManager ($BRANCH)..."
    fetch_source

    info "Installing Python dependencies (uv sync)..."
    cd "$INSTALL_DIR"
    "$UV_BIN" sync --quiet 2>&1 &
    spinner "Python packages installed" $!

    setup_tls
    write_env

    build_frontend

    local scheme="http"
    if [[ "$TLS_MODE" != "none" ]]; then scheme="https"; fi

    if [[ "$DOCKER_FLAG" -eq 1 ]]; then
        setup_docker
    else
        if ! has_systemd; then
            die "systemd not found — native install requires systemd (use --docker instead)"
        fi
        write_systemd_unit
        start_service
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 30 \
        || warn "Panel did not answer /health yet — check: journalctl -u $SYSTEMD_SERVICE -n 50"

    # The app only seeds URLPATH (and other first-boot state) into the DB on
    # its second start; restart once more so the configured prefix is live
    # before we hand over the panel to the user.
    info "Finalizing first-boot configuration..."
    if [[ "$DOCKER_FLAG" -eq 1 ]]; then
        docker restart ovmanager >/dev/null 2>&1 || true
    else
        systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 || true
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 30 \
        || warn "Panel did not answer /health after finalize — check: journalctl -u $SYSTEMD_SERVICE -n 50"
    open_firewall_port "$PORT"

    local host; host="$(hostname -I 2>/dev/null | awk '{print $1}')"
    local access="${scheme}://${host}:${PORT}/"
    if [[ -n "$PATHPREFIX" ]]; then access="${scheme}://${host}:${PORT}/${PATHPREFIX}/"; fi

    sep; line ""
    step "${B}Installation complete!${NC}"
    line ""
    field "Access"   "${WH}${access}${NC}"
    field "Login"    "${GR}${ADMIN_USER}${NC} / (password you supplied)"
    if [[ -n "$PATHPREFIX" ]]; then field "URL path" "/${PATHPREFIX}/"; fi
    line ""
    field "Manage"   "systemctl status ${SYSTEMD_SERVICE}"
    field "Logs"     "journalctl -u ${SYSTEMD_SERVICE} -f"
    field "Data"     "$DATA_DIR"
    line ""
    if [[ "$TLS_MODE" == "le" || "$TLS_MODE" == "le-ip" ]]; then
        line "  ${GY}Note:${NC} certificates auto-renew via acme.sh (reloads the service)."
    fi
    line ""
    info "Next: install an OVNode agent (its installer prints an API key),"
    info "then add it in the panel under Nodes → Add Node."
    line ""
}

# ── Docker ─────────────────────────────────────────────────────────────
setup_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        info "Installing Docker Engine..."
        if [[ "$PKG_INSTALL" == apt* ]]; then
            $PKG_UPDATE >/dev/null 2>&1 || true
            $PKG_INSTALL docker.io >/dev/null 2>&1 \
                || $PKG_INSTALL docker-ce >/dev/null 2>&1 \
                || die "Could not install Docker via apt. Install manually: https://docs.docker.com/engine/install/"
        else
            pkg_install docker docker-compose-plugin >/dev/null 2>&1 || pkg_install docker
        fi
        command -v docker >/dev/null 2>&1 || die "Docker binary not found — install Docker Engine manually"
    fi
    command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 \
        || die "Docker Compose v2 is required (docker compose plugin)"

    mkdir -p "$DATA_DIR"
    local compose="$DATA_DIR/ovmanager-compose.yml"
    cat > "$compose" << COMPOSE
services:
  ovmanager:
    build:
      context: ${INSTALL_DIR}
      dockerfile: Dockerfile
    container_name: ovmanager
    restart: unless-stopped
    ports:
      - "${PORT}:${PORT}"
    env_file:
      - ${INSTALL_DIR}/.env
    volumes:
      - ${DATA_DIR}:/app/data
      - /etc/letsencrypt:/etc/letsencrypt:ro
      - /etc/ssl/self-signed:/etc/ssl/self-signed:ro
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health', timeout=3)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
COMPOSE

    info "Building and starting Docker containers (first build takes a while)..."
    ( cd "$INSTALL_DIR" && docker compose -f "$compose" up -d --build ) >/dev/null 2>&1 &
    spinner "Docker stack started" $!
    wait_health "http://127.0.0.1:${PORT}/health" 60 \
        || warn "Panel did not answer /health — check: docker logs ovmanager"
}

# ── Update ─────────────────────────────────────────────────────────────
do_update() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    line ""; info "Updating OVManager..."
    # Auto-detect the deployment mode: a compose file in the data dir means
    # this install was done with --docker, even when `update` is called
    # without the flag (previously the systemd branch ran and reported
    # success while the stale container kept serving).
    if [[ -f "$DATA_DIR/ovmanager-compose.yml" ]]; then
        DOCKER_FLAG=1
        info "Detected Docker deployment (compose file present)"
    fi
    ensure_uv
    [[ "$DOCKER_FLAG" -eq 1 ]] || ensure_node
    backup_dir "$DATA_DIR" "panel"

    cd "$INSTALL_DIR"
    if [[ -d .git ]]; then
        git stash --quiet 2>/dev/null || true
        git pull --rebase origin "$BRANCH" 2>&1 &
        spinner "Pulling latest changes" $!
        git stash pop --quiet 2>/dev/null || true
    else
        warn "No git checkout — re-downloading source over existing install (data/.env preserved)"
        curl -sSLo /tmp/ovm.tar.gz "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" &
        spinner "Downloading source" $!
        tar -xzf /tmp/ovm.tar.gz --strip-components=1 -C "$INSTALL_DIR" >/dev/null 2>&1 || die "Extract failed"
        rm -f /tmp/ovm.tar.gz
    fi

    "$UV_BIN" sync --quiet 2>&1 &
    spinner "Updating Python dependencies" $!
    build_frontend

    local scheme="http"
    if [[ "$TLS_MODE" != "none" ]]; then scheme="https"; fi
    if [[ "$DOCKER_FLAG" -eq 1 ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$DATA_DIR/ovmanager-compose.yml" up -d --build ) >/dev/null 2>&1 &
        spinner "Recreating Docker stack" $!
    else
        start_service
    fi
    wait_health "${scheme}://127.0.0.1:${PORT}/health" 60 \
        || warn "Panel did not answer /health — check: journalctl -u $SYSTEMD_SERVICE -n 50"
    step "Update complete"
    line ""
}

# ── Uninstall ──────────────────────────────────────────────────────────
do_uninstall() {
    [[ -d "$INSTALL_DIR" ]] || die "Not installed ($INSTALL_DIR missing)"
    confirm "Remove OVManager and stop the service?" || die "Cancelled."

    systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null || true
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SYSTEMD_SERVICE"
    systemctl daemon-reload 2>/dev/null || true

    if command -v docker >/dev/null 2>&1 && [[ -f "$DATA_DIR/ovmanager-compose.yml" ]]; then
        ( cd "$INSTALL_DIR" && docker compose -f "$DATA_DIR/ovmanager-compose.yml" down ) >/dev/null 2>&1 || true
        docker rm -f ovmanager >/dev/null 2>&1 || true
    fi

    rm -rf "$INSTALL_DIR"
    if [[ "$PURGE" -eq 1 ]]; then
        backup_dir "$DATA_DIR" "panel-pre-purge"
        rm -rf "$DATA_DIR"
        step "Data directory removed"
    else
        step "App removed. Data kept at $DATA_DIR (use --purge to remove it too)"
    fi
    step "OVManager uninstalled"
    line ""
}

# ── Interactive setup ──────────────────────────────────────────────────
interactive_setup() {
    PORT="$(ask "Port" "$DEFAULT_PORT")"
    PATHPREFIX="$(ask "URL path (empty=root)" "$DEFAULT_PATH")"
    ADMIN_USER="$(ask "Admin user" "$DEFAULT_USER")"
    ADMIN_PASS="$(ask "Admin pass" "" "h")"
    [[ -n "$ADMIN_PASS" ]] || die "Admin password cannot be empty"

    sep; line "  TLS:"
    line "  ${WH}1${NC})  Let's Encrypt (domain)      ${WH}2${NC})  Let's Encrypt (IP)"
    line "  ${WH}3${NC})  Self-signed                 ${WH}4${NC})  Custom cert path"
    line "  ${WH}5${NC})  None (HTTP)"
    local tls_choice
    tls_choice="$(ask "TLS mode" "5")"
    case "${tls_choice:-5}" in
        1) TLS_MODE="le"; TLS_DOMAIN="$(ask "Domain" "")"; [[ -n "$TLS_DOMAIN" ]] || die "Domain required for Let's Encrypt" ;;
        2) TLS_MODE="le-ip"; TLS_DOMAIN="$(hostname -I 2>/dev/null | awk '{print $1}')" ;;
        3) TLS_MODE="self" ;;
        4) TLS_MODE="custom"; TLS_KEY="$(ask "Key file" "")"; TLS_CERT="$(ask "Cert file" "")" ;;
        *) TLS_MODE="none" ;;
    esac
}

# ── Main ───────────────────────────────────────────────────────────────
main() {
    parse_args "$@"
    command clear >/dev/null 2>&1 || true
    line ""
    line "  ${B}OVManager${NC} — OpenVPN Panel Installer ${GY}v${VERSION}${NC}"
    sep; line ""

    case "$ACTION" in
        uninstall) do_uninstall; exit 0 ;;
        update)    [[ "$YES" -eq 1 ]] || confirm "Update OVManager now?" || exit 0; do_update; exit 0 ;;
    esac

    if [[ -d "$INSTALL_DIR" ]]; then
        warn "OVManager is already installed"
        if is_tty; then
            line ""
            line "  ${GR}1${NC})  Update to latest version"
            line "  ${YL}2${NC})  Uninstall"
            line "  ${GY}3${NC})  Quit"
            line ""
            local choice; choice="$(ask "Select" "1")"
            case "${choice:-1}" in
                1) do_update ;;
                2) do_uninstall ;;
                *) exit 0 ;;
            esac
        else
            info "Already installed — run with 'update' to refresh it."
        fi
        exit 0
    fi

    detect_os
    if [[ "$YES" -eq 0 && ( -z "$PORT" || -z "$ADMIN_USER" ) ]]; then
        interactive_setup
    else
        : "${PORT:=$DEFAULT_PORT}"
        : "${PATHPREFIX:=$DEFAULT_PATH}"
        : "${ADMIN_USER:=$DEFAULT_USER}"
        : "${TLS_MODE:=none}"
    fi
    validate_input

    field "OS"        "$OS_NAME"
    field "Mode"      "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native)"
    field "Port"      "$PORT"
    if [[ -n "$PATHPREFIX" ]]; then field "URL path" "/${PATHPREFIX}/"; fi
    field "Admin"     "$ADMIN_USER"
    field "TLS"       "$TLS_MODE"
    field "Install"   "$INSTALL_DIR"
    field "Data"      "$DATA_DIR"
    if [[ "$TLS_MODE" == "none" ]]; then
        warn "TLS is DISABLED — the panel (and admin password) will travel in plaintext."
        warn "For internet exposure use --tls-le/--tls-ip/--tls-self; for LAN-only use a private network."
    fi
    sep
    confirm "Proceed with installation?" || die "Cancelled."

    check_root
    check_deps
    ensure_uv
    [[ "$DOCKER_FLAG" -eq 1 ]] || ensure_node
    do_install
}

check_root() { if [[ "$EUID" -ne 0 ]]; then die "Must run as root."; fi; }

main "$@"
