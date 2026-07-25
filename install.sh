#!/bin/bash
# OVManager — OpenVPN Panel Installer
# Usage: bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)

set -uo pipefail

# ═══════════════════════════════════════
#  C O N F I G
# ═══════════════════════════════════════
REPO="anonysec/OVManager"
INSTALL_DIR="/opt/ovmanager"
DEFAULT_PORT=2095
DEFAULT_PATH="dash"
DEFAULT_USER="admin"
DEFAULT_PASS="admin"
SYSTEMD_SERVICE="ovmanager.service"
VERSION="1.5"

# ═══════════════════════════════════════
#  C O L O R S
# ═══════════════════════════════════════
NC=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
WH=$'\033[97m'; GR=$'\033[32m'; RD=$'\033[31m'
YL=$'\033[33m'; BL=$'\033[34m'; CY=$'\033[36m'; GY=$'\033[90m'

# ═══════════════════════════════════════
#  U I
# ═══════════════════════════════════════
line()   { echo -e "  $1"; }
step()   { line "${GR}  ✓${NC} $1"; }
info()   { line "${CY}  →${NC} $1"; }
warn()   { line "${YL}  ⚠${NC} $1"; }
field()  { printf "  ${GY}%-16s${NC} %s\n" "$1" "$2"; }
sep()    { line "${GY}$(printf '%.0s─' {1..52})${NC}"; }

spinner() {
    local msg="$1" pid=$2 chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏' i=0
    while kill -0 "$pid" 2>/dev/null; do
        printf "\r  ${CY}%s${NC} %-48s" "${chars:$((i%9)):1}" "$msg"
        sleep 0.1; ((i++))
    done
    wait "$pid" 2>/dev/null
    local rc=$?
    printf "\r\033[K"
    [[ $rc -eq 0 ]] && step "$msg" || { line "${RD}  ✗${NC} $msg"; return 1; }
}

prompt_val() {
    local var="$1" label="$2" default="$3" hidden="${4:-}"
    local val=""
    if [[ -t 0 ]]; then
        if [[ "$hidden" == "h" ]]; then
            printf "  ${WH}%-16s${NC} ${GY}[%s]${NC} : " "$label" "$default"
            read -rs val; printf "\n"
        else
            printf "  ${WH}%-16s${NC} ${GY}[%s]${NC} : " "$label" "$default"
            read -r val
        fi
    fi
    [[ -z "$val" ]] && val="$default"
    eval "$var='$val'"
}

die() { echo -e "\n  ${RD}Error:${NC} $1\n"; exit 1; }
trap 'echo -e "\n  ${RD}Interrupted.${NC}"; exit 1' INT TERM

# ═══════════════════════════════════════
#  H E L P / A R G S
# ═══════════════════════════════════════
show_help() {
    cat << 'EOF'
  Usage:
    bash <(curl -Ls https://anonysec.github.io/OVManager/install.sh)
    bash <(curl -Ls URL) update
    bash <(curl -Ls URL) uninstall

  Commands:
    (none)              Install or update OVManager
    update              Pull latest changes and restart
    uninstall           Remove OVManager completely

  Flags:
    --port PORT         Panel port (default: 2095)
    --path URLPATH      URL path prefix (default: dash)
    --admin-user USER   Admin username
    --admin-pass PASS   Admin password
    --tls-key PATH      TLS private key
    --tls-cert PATH     TLS certificate
    --docker            Use Docker
    --help              Show this help
EOF
    exit 0
}

PORT="" PATHPREFIX="" ADMIN_USER="" ADMIN_PASS="" TLS_KEY="" TLS_CERT=""
DOCKER_FLAG=0 ACTION="install"

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --port)       PORT="$2"; shift 2 ;;
            --path)       PATHPREFIX="$2"; shift 2 ;;
            --admin-user) ADMIN_USER="$2"; shift 2 ;;
            --admin-pass) ADMIN_PASS="$2"; shift 2 ;;
            --tls-key)    TLS_KEY="$2"; shift 2 ;;
            --tls-cert)   TLS_CERT="$2"; shift 2 ;;
            --docker)     DOCKER_FLAG=1; shift ;;
            --uninstall)  ACTION="uninstall"; shift ;;
            --help|-h)    show_help ;;
            uninstall)    ACTION="uninstall"; shift ;;
            update)       ACTION="update"; shift ;;
            *)            die "Unknown option: $1. Use --help for usage." ;;
        esac
    done
}

# ═══════════════════════════════════════
#  S E T U P
# ═══════════════════════════════════════
interactive_setup() {
    prompt_val PORT       "Port"       "$DEFAULT_PORT"
    prompt_val PATHPREFIX "URL path"   "$DEFAULT_PATH"
    prompt_val ADMIN_USER "Admin user" "$DEFAULT_USER"
    prompt_val ADMIN_PASS "Admin pass" "$DEFAULT_PASS" "h"
    sep
    field "Install dir" "$INSTALL_DIR"
    field "Install mode" "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native)"
    sep
    if [[ -t 0 ]]; then
        printf "  Proceed with installation? [${GR}Y${NC}/n] : "
        read -r c; [[ "$c" =~ ^[Nn]$ ]] && die "Cancelled."
    fi
}

check_root() {
    [[ "$EUID" -ne 0 ]] && die "Must run as root."
}

check_deps() {
    local missing=()
    for cmd in curl tar openssl git; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        info "Installing missing dependencies: ${missing[*]}"
        apt-get update -qq >/dev/null && apt-get install -y -qq "${missing[@]}" >/dev/null \
            || die "Failed to install: ${missing[*]}"
    fi
    step "All system dependencies are available"
}

# ═══════════════════════════════════════
#  I N S T A L L
# ═══════════════════════════════════════
do_install() {
    [[ -d "$INSTALL_DIR" ]] && die "Already installed. Use --uninstall first."

    sep
    info "Cloning OVManager repository..."
    if command -v git >/dev/null 2>&1; then
        git clone --depth 1 --branch main "https://github.com/${REPO}.git" "$INSTALL_DIR" >/dev/null 2>&1 &
        spinner "Cloning repository" $!
    else
        curl -sSLo /tmp/ovm.tar.gz "https://github.com/${REPO}/archive/refs/heads/main.tar.gz" >/dev/null 2>&1 &
        spinner "Downloading tarball" $!
        tar -xzf /tmp/ovm.tar.gz -C /opt/ >/dev/null 2>&1
        mv "/opt/OVManager-main" "$INSTALL_DIR" 2>/dev/null || die "Extract failed"
        rm -f /tmp/ovm.tar.gz
    fi

    info "Installing Python packages with uv..."
    cd "$INSTALL_DIR"
    uv sync --quiet 2>&1 &
    spinner "Python packages installed" $!

    info "Writing .env configuration..."
    local jwt_secret
    jwt_secret=$(openssl rand -base64 48 2>/dev/null || head -c 48 /dev/urandom | base64)
    [[ -f "$INSTALL_DIR/.env.example" ]] || die ".env.example not found"
    sed \
        -e "s|^ADMIN_USERNAME=.*|ADMIN_USERNAME=${ADMIN_USER}|" \
        -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=${ADMIN_PASS}|" \
        -e "s|^PORT=.*|PORT=${PORT}|" \
        -e "s|^URLPATH=.*|URLPATH=${PATHPREFIX}|" \
        -e "s|^VITE_URLPATH=.*|VITE_URLPATH=${PATHPREFIX}|" \
        -e "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=\"${jwt_secret}\"|" \
        "$INSTALL_DIR/.env.example" > "$INSTALL_DIR/.env"
    [[ -n "$TLS_KEY" && -f "$TLS_KEY" ]] && echo "SSL_KEYFILE=\"${TLS_KEY}\"" >> "$INSTALL_DIR/.env"
    [[ -n "$TLS_CERT" && -f "$TLS_CERT" ]] && echo "SSL_CERTFILE=\"${TLS_CERT}\"" >> "$INSTALL_DIR/.env"
    step "Configuration saved to $INSTALL_DIR/.env"

    if [[ -f "$INSTALL_DIR/frontend/package.json" ]]; then
        info "Building frontend (this may take a minute)..."
        cd "$INSTALL_DIR/frontend"
        npm ci --silent >/dev/null 2>&1 &
        spinner "Node.js dependencies installed" $!
        npm run build --silent >/dev/null 2>&1 &
        spinner "Frontend assets built" $!
    fi

    if [[ $DOCKER_FLAG -eq 1 ]]; then
        setup_docker
    else
        info "Setting up systemd service..."
        local real_uv; real_uv=$(command -v uv)
        cat > "/etc/systemd/system/${SYSTEMD_SERVICE}" << SVCEOF
[Unit]
Description=OVManager OpenVPN Panel
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=${real_uv} run main.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF
        systemctl daemon-reload >/dev/null 2>&1
        systemctl enable "$SYSTEMD_SERVICE" >/dev/null 2>&1
        systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 &
        spinner "Service started" $!
    fi

    sep
    line ""
    step "${B}Installation complete!${NC}"
    line ""
    line "  ${WH}Access:${NC}  http://$(hostname -I | awk '{print $1}'):${PORT}/${PATHPREFIX}/"
    line "  ${WH}Login:${NC}   ${GR}${ADMIN_USER}${NC} / ${GR}${ADMIN_PASS}${NC}"
    line ""
    line "  ${GY}Manage:${NC}  systemctl status ${SYSTEMD_SERVICE}"
    line "  ${GY}Logs:${NC}    journalctl -u ${SYSTEMD_SERVICE} -f"
    line ""
}

setup_docker() {
    local jwt_secret; jwt_secret=$(openssl rand -base64 48 2>/dev/null)
    cat > "$INSTALL_DIR/docker-compose.yml" << EOF
version: '3.8'
services:
  ovmanager:
    image: ghcr.io/anonysec/ovmanager:latest
    container_name: ovmanager
    restart: unless-stopped
    ports:
      - "${PORT}:${PORT}"
    environment:
      - ADMIN_USERNAME=${ADMIN_USER}
      - ADMIN_PASSWORD=${ADMIN_PASS}
      - PORT=${PORT}
      - URLPATH=${PATHPREFIX}
      - JWT_SECRET_KEY=${jwt_secret}
    volumes:
      - ./data:/app/data
    networks:
      - ovmanager-net
  db:
    image: postgres:15
    restart: unless-stopped
    environment:
      POSTGRES_DB: ovmanager
      POSTGRES_USER: ovmanager
      POSTGRES_PASSWORD: ovmanager
    networks:
      - ovmanager-net
    volumes:
      - db_data:/var/lib/postgresql/data
networks:
  ovmanager-net:
    driver: bridge
volumes:
  db_data:
EOF
    cd "$INSTALL_DIR"
    docker compose up -d 2>/dev/null &
    spinner "Docker containers started" $!
}

do_update() {
    [[ ! -d "$INSTALL_DIR" ]] && die "Not installed"
    line ""
    info "Updating OVManager..."
    cd "$INSTALL_DIR"
    git pull origin main 2>&1 &
    spinner "Pulling latest changes" $!
    uv sync --quiet 2>&1 &
    spinner "Updating Python dependencies" $!
    if [[ -f "frontend/package.json" ]]; then
        cd frontend
        npm ci --silent >/dev/null 2>&1 &
        spinner "Updating Node.js dependencies" $!
        npm run build --silent >/dev/null 2>&1 &
        spinner "Rebuilding frontend" $!
    fi
    systemctl restart "$SYSTEMD_SERVICE" >/dev/null 2>&1 &
    spinner "Service restarted" $!
    step "Update complete"
    line ""
}

do_uninstall() {
    if [[ -t 0 ]]; then
        printf "  Remove OVManager and stop service? [y/N] : "; read -r c
        [[ ! "$c" =~ ^[Yy]$ ]] && die "Cancelled."
    fi
    systemctl stop "$SYSTEMD_SERVICE" 2>/dev/null
    systemctl disable "$SYSTEMD_SERVICE" 2>/dev/null
    rm -f "/etc/systemd/system/${SYSTEMD_SERVICE}"
    systemctl daemon-reload 2>/dev/null
    rm -rf "$INSTALL_DIR"
    step "Uninstalled"
    line ""
}

# ═══════════════════════════════════════
#  M A I N
# ═══════════════════════════════════════
main() {
    parse_args "$@"
    clear

    line ""
    line "  ${B}OVManager${NC} — OpenVPN Panel Installer ${GY}v${VERSION}${NC}"
    sep
    line ""

    # Handle subcommands
    case "$ACTION" in
        uninstall)
            do_uninstall; exit 0 ;;
        update)
            do_update; exit 0 ;;
    esac

    # If already installed, check for updates
    if [[ -d "$INSTALL_DIR" ]]; then
        warn "OVManager is already installed"
        line ""
        # Check if remote has new commits
        cd "$INSTALL_DIR" 2>/dev/null
        git fetch origin main --quiet 2>/dev/null
        local LOCAL=$(git rev-parse HEAD 2>/dev/null)
        local REMOTE=$(git rev-parse origin/main 2>/dev/null)
        local HAS_UPDATE=0
        [[ "$LOCAL" != "$REMOTE" ]] && HAS_UPDATE=1

        if [[ -t 0 ]]; then
            if [[ $HAS_UPDATE -eq 1 ]]; then
                line "  ${GR}1${NC})  Update to latest version"
            fi
            line "  ${RD}2${NC})  Reinstall (remove and install fresh)"
            line "  ${GY}3${NC})  Quit"
            line ""
            printf "  Select [${GR}1${NC}] : "
            read -r choice
            if [[ $HAS_UPDATE -eq 1 ]]; then
                case "${choice:-1}" in
                    1|"") do_update; exit 0 ;;
                    2)    do_uninstall; do_install ;;
                    *)    line ""; exit 0 ;;
                esac
            else
                case "${choice:-2}" in
                    2)    do_uninstall; do_install ;;
                    *)    line ""; exit 0 ;;
                esac
            fi
        else
            [[ $HAS_UPDATE -eq 1 ]] && { info "New version available, updating..."; do_update; exit 0; }
            info "Already up to date."
            exit 0
        fi
    fi

    if [[ -z "$PORT" && -z "$ADMIN_USER" ]]; then
        interactive_setup
    else
        : "${PORT:=$DEFAULT_PORT}"
        : "${PATHPREFIX:=$DEFAULT_PATH}"
        : "${ADMIN_USER:=$DEFAULT_USER}"
        : "${ADMIN_PASS:=$DEFAULT_PASS}"
        field "Port"       "$PORT"
        field "URL path"   "/${PATHPREFIX}/"
        field "Admin user" "$ADMIN_USER"
        field "Install dir" "$INSTALL_DIR"
        field "Install mode" "$([ $DOCKER_FLAG -eq 1 ] && echo Docker || echo Native)"
        sep
    fi

    check_root
    check_deps
    do_install
}

main "$@"
